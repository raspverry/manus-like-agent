# core/agent.py
"""
Manusシステムで説明されるエージェントループのメイン処理。
Docker、Playwright、CodeAct等を統合し、LLMとやりとりする。
"""

import logging
import json
import os
from typing import Dict, Any, Optional

from tools.tool_registry import ToolRegistry
from .context import Context
from .planner import Planner
from .enhanced_memory import EnhancedMemory
from .memory import Memory

from config import CONFIG

logger = logging.getLogger(__name__)

class Agent:
    def __init__(
        self,
        llm_client,
        system_prompt: str,
        tool_registry: ToolRegistry,
        planner: Optional[Planner] = None,
        memory: Optional[Memory] = None
    ):
        self.llm_client = llm_client
        self.system_prompt = system_prompt
        self.tool_registry = tool_registry
        self.planner = planner or Planner(llm_client)
        
        if memory:
            self.memory = memory
        else:
            if CONFIG["memory"]["use_vector_memory"]:
                self.memory = EnhancedMemory(workspace_dir=CONFIG["system"]["workspace_dir"])
            else:
                self.memory = Memory(workspace_dir=CONFIG["system"]["workspace_dir"])
        
        self.context = Context()
        self.is_running = False
    
    def start(self, user_input: str) -> None:
        self.is_running = True
        
        # イベントにユーザー入力を追加
        self.context.add_event({"type": "Message", "content": user_input})
        
        # 最初の通知
        try:
            self.tool_registry.execute_tool("message_notify_user", {
                "text": "リクエストを受け付けました。計画を立てて実行します。"
            })
        except:
            pass
        
        # 初期計画
        plan_text = self.planner.create_plan(user_input)
        self.context.add_event({"type": "Plan", "content": plan_text})
        
        # ループ開始
        self._agent_loop()
    
    def _agent_loop(self) -> None:
        iteration_count = 0
        max_iter = CONFIG["agent_loop"]["max_iterations"]
        
        while self.is_running and iteration_count < max_iter:
            iteration_count += 1
            prompt = self._build_prompt()
            response = self._get_llm_response(prompt)
            
            # ツール呼び出しを抽出
            tool_call = self._extract_tool_call(response)
            if not tool_call:
                logger.warning("有効なツール呼び出しが見つかりませんでした。再試行。")
                self.context.add_event({"type": "Observation", "content": "ツール呼び出し抽出に失敗"})
                continue
            
            if tool_call["name"] == "idle":
                logger.info("エージェントがアイドル状態に入ります")
                self.tool_registry.execute_tool("message_notify_user", {
                    "text": "タスクが完了したため、アイドル状態に入ります。"
                })
                self.is_running = False
                break
            
            # ツール実行
            self.context.add_event({"type": "Action", "tool": tool_call["name"], "content": tool_call})
            try:
                result = self.tool_registry.execute_tool(tool_call["name"], tool_call.get("parameters", {}))
                self.context.add_event({"type": "Observation", "tool": tool_call["name"], "content": result})
                
                # メモリ更新
                self.memory.update_from_observation(tool_call, result)
                
            except Exception as e:
                error_msg = f"ツール {tool_call['name']} 実行中にエラー: {str(e)}"
                logger.error(error_msg)
                self.context.add_event({"type": "Observation", "tool": tool_call["name"], "error": str(e)})
        
        self.is_running = False
    
    def _build_prompt(self) -> str:
        # system_prompt + イベントをまとめてLLMに投げる
        events_text = ""
        events = self.context.get_events()
        for ev in events:
            if ev["type"] == "Message":
                events_text += f"ユーザー: {ev['content']}\n"
            elif ev["type"] == "Plan":
                events_text += f"計画:\n{ev['content']}\n"
            elif ev["type"] == "Action":
                # JSON形式のツール呼び出し
                action_str = json.dumps(ev["content"], ensure_ascii=False)
                events_text += f"アクション呼び出し: {action_str}\n"
            elif ev["type"] == "Observation":
                if "error" in ev:
                    events_text += f"観察(エラー): {ev['error']}\n"
                else:
                    obs_str = str(ev["content"])
                    events_text += f"観察: {obs_str}\n"
        
        # ツール一覧
        all_tools = self.tool_registry.get_tool_names()
        
        prompt = (
            f"{self.system_prompt}\n\n"
            f"==== イベントストリーム ====\n{events_text}\n\n"
            f"利用可能なツール: {', '.join(all_tools)}\n"
            "ツールを1つだけJSONで呼び出してください。"
            "フォーマット:\n```json\n{\"name\": <tool_name>, \"parameters\": {...}}\n```\n"
            "なお、全ての日本語文はUTF-8で提供してください。\n"
        )
        return prompt
    
    def _get_llm_response(self, prompt: str) -> str:
        from config import CONFIG
        
        try:
            response_text = self.llm_client.call_azure_openai(
                prompt=prompt,
                system_prompt=self.system_prompt,
                model=CONFIG["llm"]["model"],
                temperature=CONFIG["llm"]["temperature"],
                max_tokens=CONFIG["llm"]["max_tokens"]
            )
            return response_text
        except Exception as e:
            logger.error(f"LLM応答取得中にエラー: {str(e)}")
            return ""
    
    def _extract_tool_call(self, llm_response: str) -> Optional[Dict[str, Any]]:
        import re
        # ```json ... ```
        code_fence_match = re.search(r"```json\s*(\{.*?\})\s*```", llm_response, re.DOTALL)
        raw_json = None
        if code_fence_match:
            raw_json = code_fence_match.group(1)
        else:
            # fallback
            bracket_match = re.search(r"(\{.*\})", llm_response, re.DOTALL)
            if bracket_match:
                raw_json = bracket_match.group(1)
        
        if not raw_json:
            return None
        
        try:
            data = json.loads(raw_json)
            if "name" not in data:
                return None
            return data
        except:
            return None
    
    def stop(self) -> None:
        if self.is_running:
            logger.info("エージェントを停止します")
            self.is_running = False
