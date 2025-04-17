# core/agent.py
"""
非同期版 Agent コア実装
======================
Manus ライクなエージェントの中心クラス。UI をブロックしないよう asyncio 化し、
ツール呼び出し・LLM 呼び出しをスレッドプールに逃がす。

主な特徴
--------
* start / stop の外部 API は同期のまま。内部で asyncio.run しているだけなので呼び出し側の変更は不要。
* 各ツール実行を asyncio.wait_for でタイムアウト制御。秒数は CONFIG["agent_loop"]["tool_timeout_seconds"]。
* stop() で _cancel_event をセットし、ループ内 await ポイントで即時キャンセル。
* タスクごとの進捗やコンテキスト要約など旧版のロジックは保持。
* Plan ↔ todo.md 同期対応
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
from core.logging_config import logger
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from config import CONFIG
from tools.tool_registry import ToolRegistry
from .context import Context
from .enhanced_memory import EnhancedMemory
from .memory import Memory
from .planner import Planner




# ---------------------------------------------------------------------------
# ヘルパ: 同期関数をスレッドプールで非同期化
# ---------------------------------------------------------------------------

def _to_thread(func, *args, **kwargs):
    """
    同期関数 `func` をデフォルト executor で実行し await 可能にする。
    kwargs がある場合は functools.partial で包む。
    """
    loop = asyncio.get_running_loop()
    if kwargs:
        func = functools.partial(func, *args, **kwargs)
        return loop.run_in_executor(None, func)
    return loop.run_in_executor(None, func, *args)


# ---------------------------------------------------------------------------
# Agent クラス
# ---------------------------------------------------------------------------

class Agent:
    """Manus ライク・エージェント（非同期 & Plan↔todo 同期版）"""

    def __init__(
        self,
        llm_client,
        system_prompt: str,
        tool_registry: ToolRegistry,
        planner: Optional[Planner] = None,
        memory: Optional[Memory] = None,
    ) -> None:
        self.llm_client = llm_client
        self.system_prompt = system_prompt
        self.tool_registry = tool_registry
        self.planner = planner or Planner(llm_client)

        # メモリ
        if memory is not None:
            self.memory = memory
        else:
            if CONFIG["memory"].get("use_vector_memory", False):
                self.memory = EnhancedMemory(Path(CONFIG["system"]["workspace_dir"]).as_posix())
            else:
                self.memory = Memory(workspace_dir=CONFIG["system"]["workspace_dir"])

        self.context = Context()
        self._cancel_event: Optional[asyncio.Event] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._start_time: float = 0.0
        self._iterations: int = 0

        # Plan ↔ todo 同期用
        self._plan_hash: str = ""
        self._todo_path = Path(CONFIG["system"]["workspace_dir"]) / CONFIG["memory"]["todo_file"]

    # ------------------------------------------------------------------ #
    # 公開 API
    # ------------------------------------------------------------------ #
    def start(self, user_input: str) -> None:
        asyncio.run(self._start_async(user_input))

    def stop(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    # ------------------------------------------------------------------ #
    # 内部処理
    # ------------------------------------------------------------------ #
    async def _start_async(self, user_input: str) -> None:
        self._cancel_event = asyncio.Event()
        self._start_time = time.time()
        self._iterations = 0

        self.context.add_event({"type": "Message", "content": user_input})
        await self._safe_tool("message_notify_user", {"message": "リクエストを受け付けました。計画を立案します。"})

        plan_text: str = await _to_thread(self.planner.create_plan, user_input)
        self.context.add_event({"type": "Plan", "content": plan_text})
        self._plan_hash = self._hash(plan_text)
        await _to_thread(self._write_todo_from_plan, plan_text, preserve_completed=False)

        self._loop_task = asyncio.create_task(self._agent_loop_async())
        await self._loop_task

    async def _agent_loop_async(self) -> None:
        cfg = CONFIG["agent_loop"]
        max_iter = cfg["max_iterations"]
        max_seconds = cfg["max_time_seconds"]
        summarize_every = cfg["auto_summarize_threshold"]
        tool_timeout = cfg.get("tool_timeout_seconds", 90)

        while not self._cancel_event.is_set() and self._iterations < max_iter:
            if time.time() - self._start_time > max_seconds:
                await self._safe_tool("message_notify_user", {"text": "時間上限を超過したため終了します。"})
                break

            self._iterations += 1

            # Plan ↔ todo 同期
            await _to_thread(self._sync_todo_with_latest_plan)

            # コンテキスト要約
            if summarize_every and self._iterations % summarize_every == 0:
                await _to_thread(self._summarize_context)

            prompt = await _to_thread(self._build_prompt)
            llm_resp = await _to_thread(self._get_llm_response, prompt)
            tool_call = await _to_thread(self._extract_tool_call, llm_resp)

            if tool_call is None:
                self.context.add_event({"type": "Observation", "content": "ツール呼び出し抽出失敗"})
                continue

            if tool_call["name"] == "idle":
                await self._safe_tool("message_notify_user", {"text": "タスクが完了しました。"})
                break

            try:
                result = await asyncio.wait_for(
                    _to_thread(self.tool_registry.execute_tool, tool_call["name"], tool_call.get("parameters", {})),
                    timeout=tool_timeout,
                )
            except asyncio.TimeoutError:
                result = f"ツール {tool_call['name']} が {tool_timeout} 秒でタイムアウトしました。"
            except Exception as exc:
                result = f"ツール実行エラー: {exc}"

            self.context.add_event({"type": "Observation", "tool": tool_call["name"], "content": result})
            await _to_thread(self.memory.update_from_observation, tool_call, result)

        if self._cancel_event.is_set():
            await self._safe_tool("message_notify_user", {"text": "ユーザーにより停止しました。"})
        else:
            await _to_thread(self._report_progress, True)

    # ------------------------------------------------------------------ #
    # Plan ↔ todo 同期ロジック
    # ------------------------------------------------------------------ #
    def _hash(self, txt: str) -> str:
        return hashlib.sha256(txt.encode("utf-8")).hexdigest()

    def _latest_plan_text(self) -> Optional[str]:
        for ev in reversed(self.context.get_events()):
            if ev["type"] == "Plan":
                return ev["content"]
        return None

    def _sync_todo_with_latest_plan(self) -> None:
        plan_text = self._latest_plan_text()
        if plan_text is None:
            return
        new_hash = self._hash(plan_text)
        if new_hash == self._plan_hash:
            return  # 変更なし
        # 計画が変わった → todo 再構築
        self._write_todo_from_plan(plan_text, preserve_completed=True)
        self._plan_hash = new_hash
        logger.info("Plan が更新されたため todo.md を再構築しました")

    def _write_todo_from_plan(self, plan_text: str, *, preserve_completed: bool) -> None:
        lines = plan_text.split("\n")
        step_lines = []
        for line in lines:
            m = re.match(r"(\d+)\.\s+(.*)", line)
            if m:
                step_lines.append((m.group(1), m.group(2)))
        if not step_lines:
            return

        completed: set[str] = set()
        if preserve_completed and self._todo_path.exists():
            for l in self._todo_path.read_text(encoding="utf-8").split("\n"):
                m = re.match(r"- \[x\] (\d+)\.", l)
                if m:
                    completed.add(m.group(1))

        with self._todo_path.open("w", encoding="utf-8") as f:
            f.write("# タスク ToDo リスト\n\n")
            for num, text in step_lines:
                mark = "x" if num in completed else " "
                f.write(f"- [{mark}] {num}. {text}\n")

    # ------------------------------------------------------------------ #
    # ユーティリティ（通知・要約・プロンプト生成など）
    # ------------------------------------------------------------------ #
    async def _safe_tool(self, name: str, params: Dict[str, Any]):
        try:
            await _to_thread(self.tool_registry.execute_tool, name, params)
        except Exception as exc:
            logger.error(f"通知ツール {name} 失敗: {exc}")

    def _summarize_context(self) -> None:
        events = self.context.get_events()
        if len(events) < 10:
            return
        recent, older = events[-10:], events[:-10]
        summary_prompt = "以下のイベントを簡潔に日本語で要約してください。\n\n"
        for ev in older:
            if ev["type"] == "Message":
                summary_prompt += f"ユーザー: {ev['content']}\n"
            elif ev["type"] == "Plan":
                summary_prompt += f"計画: {ev['content'][:200]}...\n"
            elif ev["type"] == "Action":
                summary_prompt += f"アクション: {json.dumps(ev['content'], ensure_ascii=False)}\n"
            elif ev["type"] == "Observation":
                summary_prompt += f"観察: {str(ev.get('content', ''))[:100]}...\n"
        summary, _ = self.llm_client.chat_completion(
            messages=[
                {"role": "system", "content": "あなたは要約アシスタントです。重要点のみ抽出してください。"},
                {"role": "user", "content": summary_prompt},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        self.context.clear()
        self.context.add_event({"type": "Summary", "content": summary})
        for ev in recent:
            self.context.add_event(ev)

    def _report_progress(self, is_final: bool = False):
        elapsed = time.time() - self._start_time
        m, s = divmod(int(elapsed), 60)
        prefix = "最終レポート" if is_final else "途中経過"
        msg = f"{prefix} – 経過時間: {m}分{s}秒, イテレーション: {self._iterations} 回"
        self.tool_registry.execute_tool("message_notify_user", {"text": msg})

    def _build_prompt(self) -> str:
        events_text = ""
        for ev in self.context.get_events():
            if ev["type"] == "Message":
                events_text += f"ユーザー: {ev['content']}\n"
            elif ev["type"] == "Plan":
                events_text += f"計画:\n{ev['content']}\n"
            elif ev["type"] == "Action":
                events_text += f"アクション呼び出し: {json.dumps(ev['content'], ensure_ascii=False)}\n"
            elif ev["type"] == "Observation":
                events_text += f"観察: {str(ev.get('content', ''))}\n"
            elif ev["type"] == "Summary":
                events_text += f"要約: {ev['content']}\n"
        memory_state = self.memory.get_relevant_state()
        tools = ", ".join(self.tool_registry.get_tool_names())
        return (
            f"{self.system_prompt}\n\n"
            f"==== イベントストリーム ====\n{events_text}\n\n"
            f"==== メモリ状態 ====\n{memory_state}\n\n"
            f"利用可能なツール: {tools}\n"
            "次のアクションとして必ず 1 つだけツールを JSON 形式で呼び出してください。\n"
            "フォーマット:\n```json\n{\"name\": <tool_name>, \"parameters\": {...}}\n```\n"
        )

    def _get_llm_response(self, prompt: str) -> str:
        content, _ = self.llm_client.chat_completion(
            messages=[{"role": "system", "content": self.system_prompt}, {"role": "user", "content": prompt}],
            temperature=CONFIG["llm"]["temperature"],
            max_tokens=CONFIG["llm"]["max_tokens"],
            force_json=False,
        )
        return content

    def _extract_tool_call(self, text: Dict) -> Optional[Dict[str, Any]]:
        # fence = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        # # raw = fence.group(1) if fence else None
        # if not raw:
        #     brace = re.search(r"(\{.*\})", text, re.DOTALL)
        #     raw = brace.group(1) if brace else None
        # if not raw:
        #     return None
        try:
            # data = json.loads(raw)
            data = text
            return data if "name" in data else None
        except Exception:
            return None

    # プロパティ
    @property
    def iterations(self) -> int:
        return self._iterations
