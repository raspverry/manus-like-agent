# ui/streamlit_app.py
"""
Streamlitを使用したウェブインターフェース（旧 UI レイアウト + 無限ループ修正）
"""

import os
import sys
from core.logging_config import logger
import threading
import time
import queue
from typing import Any, Dict

import streamlit as st

# プロジェクトルートを import パスに追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import CONFIG
from core.agent import Agent
from core.planner import Planner
from tools.tool_registry import ToolRegistry
from llm.azure_openai_client import AzureOpenAIClient
from core.memory import Memory
from core.enhanced_memory import EnhancedMemory



# ------------------------------------------------------------------
# メッセージキュー
# ------------------------------------------------------------------
msg_queue: queue.Queue = queue.Queue()


# ------------------------------------------------------------------
# Agent 生成
# ------------------------------------------------------------------
def create_agent() -> Agent:
    prompt_dir = CONFIG["system"]["prompt_dir"]
    try:
        with open(os.path.join(prompt_dir, "system_prompt.txt"), encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        system_prompt = "あなたはManusのようなエージェントです。"

    llm_client = AzureOpenAIClient()
    planner = Planner(llm_client)
    registry = ToolRegistry()

    for mod in [
        "tools.message_tools",
        "tools.shell_tools",
        "tools.file_tools",
        "tools.info_tools",
        "tools.deploy_tools",
        "tools.browser_tools",
        "tools.codeact_tools",
        "tools.system_tools",
    ]:
        registry.register_tools_from_module(mod)

    # message ツールを UI キューに差し替え
    registry.register_tool(
        "message_notify_user",
        lambda text, attachments=None: msg_queue.put(("notify", text)),
        registry.get_tool_spec("message_notify_user"),
    )
    registry.register_tool(
        "message_ask_user",
        lambda text, attachments=None, suggest_user_takeover="none": msg_queue.put(
            ("ask", text)
        ),
        registry.get_tool_spec("message_ask_user"),
    )

    # Memory
    if CONFIG["memory"].get("use_vector_memory", False):
        memory = EnhancedMemory(workspace_dir=CONFIG["system"]["workspace_dir"])
    else:
        memory = Memory(workspace_dir=CONFIG["system"]["workspace_dir"])

    return Agent(llm_client, system_prompt, registry, planner, memory)


# ------------------------------------------------------------------
# Agent 実行スレッド
# ------------------------------------------------------------------
def run_agent(agent: Agent, task_input: str, stop_event: threading.Event):
    def _runner():
        try:
            msg_queue.put(("status", "🟢 エージェントが起動しました"))
            agent.start(task_input)
            msg_queue.put(("status", "✅ エージェントが完了しました"))
        except Exception as exc:
            logger.error(f"Agent 実行エラー: {exc}", exc_info=True)
            msg_queue.put(("error", f"エラー: {exc}"))
        finally:
            stop_event.set()

    threading.Thread(target=_runner, daemon=True).start()


# ------------------------------------------------------------------
# Streamlit アプリ
# ------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Manus‑Like Agent", page_icon="🤖", layout="wide")

    # ---------------- セッション初期化 ---------------- #
    if "agent" not in st.session_state:
        st.session_state.agent = create_agent()
    if "agent_thread" not in st.session_state:
        st.session_state.agent_thread = None
    if "stop_event" not in st.session_state:
        st.session_state.stop_event = threading.Event()
    if "messages" not in st.session_state:
        st.session_state.messages: list[Dict[str, Any]] = []
    if "is_asking" not in st.session_state:
        st.session_state.is_asking = False
    if "ask_message" not in st.session_state:
        st.session_state.ask_message = ""

    # ---------------- サイドバー ---------------- #
    with st.sidebar:
        st.header("設定")
        st.text(f"ワークスペース: {CONFIG['system']['workspace_dir']}")
        st.text(f"使用モデル: {CONFIG['llm']['model']}")

        if st.session_state.agent_thread and st.session_state.agent_thread.is_alive():
            if st.button("処理を停止", type="primary"):
                st.session_state.agent.stop()
                st.session_state.stop_event.set()

        if st.button("履歴をクリア"):
            st.session_state.messages.clear()
            st.rerun()

    # ---------------- メインパネル ---------------- #
    st.title("Manus‑Like Agent 🤖")
    col1, col2 = st.columns([2, 1])

    # -------- メッセージ履歴 -------- #
    with col1:
        st.subheader("エージェントとの対話")
        for m in st.session_state.messages:
            with st.chat_message("user" if m["type"] == "user" else "assistant"):
                st.markdown(m["content"])

        # 入力フォーム
        if not (st.session_state.agent_thread and st.session_state.agent_thread.is_alive()):
            user_query = st.text_area("タスクを指示してください", key="query_input")
            if st.button("送信"):
                if user_query.strip():
                    st.session_state.messages.append({"type": "user", "content": user_query})
                    st.session_state.stop_event.clear()
                    
                    # Thread オブジェクトを生成して保持
                    th = threading.Thread(
                        target=run_agent,
                        args=(st.session_state.agent, user_query, st.session_state.stop_event),
                        daemon=True,
                    )
                    st.session_state.agent_thread = th
                    th.start()
                    st.rerun()

    # -------- ステータスパネル -------- #
    with col2:
        st.subheader("エージェントステータス")
        if st.session_state.agent_thread and st.session_state.agent_thread is True:
            st.info("🔄 処理中…")
        else:
            st.info("⏸️ アイドル状態")

    # ---------------- キュー処理 ---------------- #
    processed = False
    while not msg_queue.empty():
        kind, text = msg_queue.get()
        processed = True
        if kind == "notify":
            st.session_state.messages.append({"type": "notify", "content": text})
        elif kind == "ask":
            st.session_state.is_asking = True
            st.session_state.ask_message = text
            st.session_state.messages.append({"type": "agent", "content": f"質問: {text}"})
        elif kind == "status":
            st.session_state.messages.append({"type": "status", "content": text})
        elif kind == "error":
            st.session_state.messages.append({"type": "error", "content": text})

    # 変化があった場合のみ再描画
    if processed:
        st.rerun()


if __name__ == "__main__":
    main()
