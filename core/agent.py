# core/agent.py
"""
強化されたエージェントコア実装。Manusシステムのエージェントループ機能を改善。
Docker、Playwright、CodeAct等を統合し、LLMとやりとりする。
"""

import logging
import json
import os
import time
import re
from typing import Dict, Any, Optional, List, Tuple

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
        self.start_time = None
        self.iterations = 0
        self.last_summary_iteration = 0
    
    def start(self, user_input: str) -> None:
        """
        エージェントを起動し、ユーザー入力に基づいてタスクを開始します。
        
        Args:
            user_input: ユーザーからの入力テキスト
        """
        self.is_running = True
        self.start_time = time.time()
        self.iterations = 0
        self.last_summary_iteration = 0
        
        # イベントにユーザー入力を追加
        self.context.add_event({"type": "Message", "content": user_input})
        
        # 最初の通知
        try:
            self.tool_registry.execute_tool("message_notify_user", {
                "text": "リクエストを受け付けました。計画を立てて実行します。"
            })
        except Exception as e:
            logger.error(f"初期通知でエラー: {str(e)}")
        
        # 初期計画
        plan_text = self.planner.create_plan(user_input)
        self.context.add_event({"type": "Plan", "content": plan_text})
        
        # ToDoファイルの作成
        try:
            self._create_todo_from_plan(plan_text)
        except Exception as e:
            logger.error(f"ToDo作成でエラー: {str(e)}")
        
        # ループ開始
        self._agent_loop()
    
    def _create_todo_from_plan(self, plan_text: str) -> None:
        """
        計画テキストからToDo.mdファイルを作成します。
        
        Args:
            plan_text: 計画のテキスト
        """
        # 計画からステップを抽出
        lines = plan_text.split("\n")
        steps = []
        
        for line in lines:
            # "数字. テキスト" の形式を探す
            match = re.match(r'(\d+)\.\s+(.*)', line)
            if match:
                step_num = match.group(1)
                step_text = match.group(2)
                steps.append(f"- [ ] {step_num}. {step_text}")
        
        if not steps:
            # 別のフォーマットを試す
            for line in lines:
                if line.strip() and not line.startswith("目標:") and not line.startswith("#"):
                    # 行に何か意味のあるテキストがある場合は、それをステップとして追加
                    steps.append(f"- [ ] {line.strip()}")
        
        # ToDoファイルを作成
        todo_file = os.path.join(CONFIG["system"]["workspace_dir"], CONFIG["memory"]["todo_file"])
        
        # ヘッダーテキスト
        header = "# タスクToDoリスト\n\n"
        
        # 目標行を抽出
        goal_line = ""
        for line in lines:
            if line.startswith("目標:"):
                goal_line = line + "\n\n"
                break
        
        todo_content = header + goal_line + "\n".join(steps)
        
        # ファイルに書き込み
        with open(todo_file, "w", encoding="utf-8") as f:
            f.write(todo_content)
        
        logger.info(f"ToDo.mdファイルを作成しました（{len(steps)}ステップ）")
    
    def _agent_loop(self) -> None:
        """
        エージェントループのメイン処理。
        観察→分析→行動のサイクルを、タスクが完了するまで繰り返します。
        """
        iteration_count = 0
        max_iter = CONFIG["agent_loop"]["max_iterations"]
        max_time_seconds = CONFIG["agent_loop"]["max_time_seconds"]
        auto_summarize_threshold = CONFIG["agent_loop"]["auto_summarize_threshold"]
        
        while self.is_running and iteration_count < max_iter:
            # 実行時間チェック
            elapsed_time = time.time() - self.start_time
            if elapsed_time > max_time_seconds:
                logger.warning(f"最大実行時間（{max_time_seconds}秒）を超過しました。")
                self.tool_registry.execute_tool("message_notify_user", {
                    "text": f"最大実行時間（{max_time_seconds/60:.1f}分）を超過したため、処理を停止します。ここまでの進捗を報告します。"
                })
                self._report_progress()
                self.is_running = False
                break
            
            # イテレーションカウンタを増やす
            iteration_count += 1
            self.iterations = iteration_count
            
            # コンテキスト自動要約（必要な場合）
            if auto_summarize_threshold > 0 and iteration_count - self.last_summary_iteration >= auto_summarize_threshold:
                self._summarize_context()
                self.last_summary_iteration = iteration_count
            
            # プロンプト構築とLLM呼び出し
            prompt = self._build_prompt()
            response = self._get_llm_response(prompt)
            
            # ツール呼び出しを抽出
            tool_call = self._extract_tool_call(response)
            if not tool_call:
                logger.warning("有効なツール呼び出しが見つかりませんでした。再試行。")
                self.context.add_event({"type": "Observation", "content": "ツール呼び出し抽出に失敗"})
                continue
            
            if tool_call["name"] == "idle":
                # タスク完了
                reason = tool_call.get("parameters", {}).get("reason", "タスクが完了したため")
                logger.info(f"エージェントがアイドル状態に入ります: {reason}")
                self.tool_registry.execute_tool("message_notify_user", {
                    "text": f"タスクが完了しました: {reason}"
                })
                self._report_progress(is_final=True)
                self.is_running = False
                break
            
            # ツール実行
            self.context.add_event({"type": "Action", "tool": tool_call["name"], "content": tool_call})
            try:
                logger.info(f"ツール実行: {tool_call['name']}")
                result = self.tool_registry.execute_tool(tool_call["name"], tool_call.get("parameters", {}))
                self.context.add_event({"type": "Observation", "tool": tool_call["name"], "content": result})
                
                # メモリ更新
                self.memory.update_from_observation(tool_call, result)
                
                # 特定のツールの場合は追加処理
                self._handle_special_tool_results(tool_call, result)
                
            except Exception as e:
                error_msg = f"ツール {tool_call['name']} 実行中にエラー: {str(e)}"
                logger.error(error_msg)
                self.context.add_event({"type": "Observation", "tool": tool_call["name"], "error": str(e)})
        
        # ループ終了後の処理
        if self.iterations >= max_iter:
            logger.warning(f"最大イテレーション数（{max_iter}）に達しました。")
            self.tool_registry.execute_tool("message_notify_user", {
                "text": f"最大イテレーション数（{max_iter}）に達したため、処理を停止します。ここまでの進捗を報告します。"
            })
            self._report_progress()
        
        self.is_running = False
    
    def _summarize_context(self) -> None:
        """
        コンテキストの古い部分を要約して、コンテキストウィンドウを管理します。
        """
        events = self.context.get_events()
        
        # イベント数が十分に多い場合のみ要約
        if len(events) < 10:
            return
        
        # 最新のイベントを保持
        recent_events = events[-10:]
        older_events = events[:-10]
        
        # 要約用のプロンプト構築
        summary_prompt = (
            "以下のイベントシーケンスを簡潔に要約してください。要約は後続の処理のためのコンテキストとして使用されます。\n\n"
        )
        
        for ev in older_events:
            if ev["type"] == "Message":
                summary_prompt += f"ユーザー: {ev['content']}\n"
            elif ev["type"] == "Plan":
                summary_prompt += f"計画:\n{ev['content'][:200]}...\n"
            elif ev["type"] == "Action":
                action_str = f"{ev['tool']}" if "tool" in ev else str(ev["content"])
                summary_prompt += f"アクション: {action_str}\n"
            elif ev["type"] == "Observation":
                obs_str = str(ev["content"])[:100] + "..." if len(str(ev["content"])) > 100 else str(ev["content"])
                summary_prompt += f"観察: {obs_str}\n"
        
        # 要約をLLMで生成
        summary_response = self.llm_client.call_azure_openai(
            prompt=summary_prompt,
            system_prompt="あなたはイベントシーケンスを要約するアシスタントです。与えられたイベントの重要な情報を簡潔にまとめてください。",
            model=CONFIG["llm"]["model"],
            temperature=0.3,
            max_tokens=500
        )
        
        # 要約をコンテキストに追加
        self.context.clear()
        self.context.add_event({"type": "Summary", "content": summary_response})
        
        # 最新のイベントを戻す
        for ev in recent_events:
            self.context.add_event(ev)
        
        logger.info(f"コンテキストを要約しました: {len(older_events)}件のイベントを1件の要約に置き換えました")
    
    def _handle_special_tool_results(self, tool_call: Dict[str, Any], result: Any) -> None:
        """
        特定のツール実行結果に対する追加処理を行います。
        
        Args:
            tool_call: 実行されたツール呼び出し
            result: ツール実行の結果
        """
        tool_name = tool_call["name"]
        params = tool_call.get("parameters", {})
        
        # CodeActパラダイムのためのコード実行結果処理
        if tool_name == "code_execute":
            code = params.get("code", "")
            # コード実行の結果を分析し、必要に応じてメモリに保存
            if isinstance(result, str) and "エラー" not in result:
                # 成功したコード実行を記録
                self.memory.save_variable("last_successful_code", {
                    "code": code,
                    "result": result[:500],  # 長すぎる結果は切り詰める
                    "timestamp": time.time()
                })
        
        # ToDo更新の追跡
        elif tool_name == "file_str_replace" and os.path.basename(params.get("file", "")) == CONFIG["memory"]["todo_file"]:
            old_str = params.get("old_str", "")
            new_str = params.get("new_str", "")
            
            # ToDo項目の完了をトラッキング
            if "- [ ]" in old_str and "- [x]" in new_str:
                # ToDoの完了状態を取得
                todo_status = self.memory.get_todo_status()
                progress = f"{todo_status['completed']}/{todo_status['total']}"
                
                # 進捗を報告（定期的に）
                if todo_status["completed"] > 0 and todo_status["completed"] % 3 == 0:
                    try:
                        self.tool_registry.execute_tool("message_notify_user", {
                            "text": f"進捗状況: {progress} タスク完了 ({todo_status['progress_percent']:.1f}%)"
                        })
                    except:
                        pass
    
    def _report_progress(self, is_final: bool = False) -> None:
        """
        現在の進捗状況をユーザーに報告します。
        
        Args:
            is_final: 最終報告かどうか
        """
        # ToDo状態を取得
        todo_status = self.memory.get_todo_status()
        
        # 実行時間を計算
        elapsed_time = time.time() - self.start_time
        minutes, seconds = divmod(elapsed_time, 60)
        time_str = f"{int(minutes)}分{int(seconds)}秒"
        
        # メッセージ構築
        if is_final:
            message = f"タスク完了レポート (実行時間: {time_str}, イテレーション: {self.iterations}回)\n\n"
        else:
            message = f"途中経過レポート (実行時間: {time_str}, イテレーション: {self.iterations}回)\n\n"
        
        # ToDo進捗
        if todo_status["exists"]:
            message += f"ToDo進捗: {todo_status['completed']}/{todo_status['total']} タスク完了 ({todo_status['progress_percent']:.1f}%)\n\n"
        
        # ファイル操作の概要
        file_count = len(self.memory.file_registry)
        if file_count > 0:
            message += f"作成/更新ファイル数: {file_count}件\n"
            
            # 主要ファイルのリスト（最大5件）
            important_files = []
            for file_path in self.memory.file_registry:
                if file_path.endswith((".py", ".md", ".html", ".js", ".json", ".css")):
                    important_files.append(os.path.basename(file_path))
                if len(important_files) >= 5:
                    break
            
            if important_files:
                message += f"主要ファイル: {', '.join(important_files)}"
                if len(self.memory.file_registry) > 5:
                    message += f" 他 {len(self.memory.file_registry) - 5}件"
                message += "\n"
        
        try:
            # 報告
            self.tool_registry.execute_tool("message_notify_user", {
                "text": message
            })
        except Exception as e:
            logger.error(f"進捗報告中にエラー: {str(e)}")
    
    def _build_prompt(self) -> str:
        """
        LLMに送信するプロンプトを構築します。
        
        Returns:
            構築されたプロンプト文字列
        """
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
            elif ev["type"] == "Summary":
                events_text += f"これまでの要約: {ev['content']}\n"
        
        # メモリから関連状態を取得
        memory_state = self.memory.get_relevant_state()
        
        # ツール一覧
        all_tools = self.tool_registry.get_tool_names()
        
        prompt = (
            f"{self.system_prompt}\n\n"
            f"==== イベントストリーム ====\n{events_text}\n\n"
            f"==== メモリ状態 ====\n{memory_state}\n\n"
            f"利用可能なツール: {', '.join(all_tools)}\n"
            "ツールを1つだけJSONで呼び出してください。"
            "フォーマット:\n```json\n{\"name\": <tool_name>, \"parameters\": {...}}\n```\n"
            "なお、全ての日本語文はUTF-8で提供してください。\n"
        )
        return prompt
    
    def _get_llm_response(self, prompt: str) -> str:
        """
        LLMに問い合わせて応答を取得します。
        
        Args:
            prompt: LLMに送信するプロンプト
            
        Returns:
            LLMからの応答文字列
        """
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
        """
        LLMの応答からツール呼び出しを抽出します。
        
        Args:
            llm_response: LLMの応答テキスト
            
        Returns:
            抽出されたツール呼び出し、見つからない場合はNone
        """
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
        """
        エージェントを停止します。
        """
        if self.is_running:
            logger.info("エージェントを停止します")
            self.is_running = False
            
            # 正常に停止したことをユーザーに通知
            try:
                elapsed_time = time.time() - self.start_time
                minutes, seconds = divmod(elapsed_time, 60)
                time_str = f"{int(minutes)}分{int(seconds)}秒"
                
                self.tool_registry.execute_tool("message_notify_user", {
                    "text": f"ユーザーリクエストによりエージェントを停止しました。（実行時間: {time_str}）"
                })
            except:
                pass
