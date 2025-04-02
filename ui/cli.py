# ui/cli.py
"""
コマンドラインインターフェース。
"""
import os
import sys
import logging
import readline
import atexit
import threading
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from ..config import CONFIG
from ..core.agent import Agent
from ..tools.tool_registry import ToolRegistry
from ..core.memory import Memory
from ..core.enhanced_memory import EnhancedMemory
from ..core.context import Context
from ..core.planner import Planner
from ..llm.azure_openai_client import AzureOpenAIClient
from ..tools import (message_tools, shell_tools, file_tools,
                     info_tools, deploy_tools, browser_tools, codeact_tools)

logger = logging.getLogger(__name__)

def create_agent() -> Agent:
    # システムプロンプト
    prompt_path = os.path.join(CONFIG["system"]["prompt_dir"], "system_prompt.txt")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except:
        system_prompt = "あなたはManusのようなエージェントです。"
    
    # AzureOpenAIクライアント
    llm_client = AzureOpenAIClient()
    
    # ツールレジストリ
    registry = ToolRegistry()
    registry.register_tools_from_module("manus_project.tools.message_tools")
    registry.register_tools_from_module("manus_project.tools.shell_tools")
    registry.register_tools_from_module("manus_project.tools.file_tools")
    registry.register_tools_from_module("manus_project.tools.info_tools")
    registry.register_tools_from_module("manus_project.tools.deploy_tools")
    registry.register_tools_from_module("manus_project.tools.browser_tools")
    registry.register_tools_from_module("manus_project.tools.codeact_tools")
    
    # Planner
    planner = Planner(llm_client)
    
    # Memory
    if CONFIG["memory"]["use_vector_memory"]:
        memory = EnhancedMemory(workspace_dir=CONFIG["system"]["workspace_dir"])
    else:
        memory = Memory(workspace_dir=CONFIG["system"]["workspace_dir"])
    
    agent = Agent(
        llm_client=llm_client,
        system_prompt=system_prompt,
        tool_registry=registry,
        planner=planner,
        memory=memory
    )
    return agent

def main(initial_task: Optional[str] = None):
    console = Console()
    
    # ヒストリファイル
    history_file = os.path.expanduser("~/.manus_history")
    try:
        readline.read_history_file(history_file)
        readline.set_history_length(1000)
    except FileNotFoundError:
        pass
    atexit.register(readline.write_history_file, history_file)
    
    agent = create_agent()
    
    console.print(Panel("[bold cyan]Manus-Like Agent CLI[/bold cyan]", title="ようこそ"))
    console.print("コマンド例: task <指示> / help / exit")
    
    if initial_task:
        agent.start(initial_task)
    
    while True:
        try:
            cmd = input("\n> ").strip()
            if not cmd:
                continue
            if cmd in ["exit", "quit"]:
                console.print("終了します")
                break
            elif cmd.startswith("task"):
                task_description = cmd[len("task"):].strip()
                if not task_description:
                    console.print("[red]タスク内容が指定されていません[/red]")
                else:
                    agent.start(task_description)
            elif cmd == "help":
                console.print("task <内容>: タスク開始\nstatus: 状況表示\nexit: 終了")
            elif cmd == "status":
                console.print("[cyan]エージェントの状態は特にありません。[/cyan]")
            else:
                console.print("[red]不明なコマンド。helpで確認[/red]")
        except KeyboardInterrupt:
            console.print("\nCtrl+C で終了")
            break
        except Exception as e:
            console.print(f"[red]エラー:[/red] {str(e)}")
    
    # 終了時にクリーンアップ
    agent.stop()
    from ..sandbox.sandbox import get_sandbox
    get_sandbox().cleanup()
