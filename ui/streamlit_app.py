# ui/streamlit_app.py
"""
Streamlitを使用したウェブインターフェース。
"""
import streamlit as st
import os
import sys
import logging
import threading
import time
import queue
from typing import Optional

# 親ディレクトリをPythonパスに追加してインポートエラーを解決
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 絶対インポートを使用
try:
    from core.agent import Agent
    from tools.tool_registry import ToolRegistry
    from core.memory import Memory
    from core.enhanced_memory import EnhancedMemory
    from core.context import Context
    from core.planner import Planner
    from llm.azure_openai_client import AzureOpenAIClient
    from config import CONFIG
except ImportError as e:
    st.error(f"モジュールのインポートに失敗しました: {e}")
    st.info("プロジェクト構造を確認してください。")
    import sys
    sys.exit(1)

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# メッセージキュー (スレッド間通信用)
message_queue = queue.Queue()

def create_agent() -> Agent:
    """Agentオブジェクトを初期化して返す"""
    # システムプロンプト
    prompt_dir = CONFIG["system"]["prompt_dir"]
    try:
        with open(os.path.join(prompt_dir, "system_prompt.txt"), "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except:
        system_prompt = "あなたはManusのようなエージェントです。"
    
    # AzureOpenAIクライアント
    llm_client = AzureOpenAIClient()
    
    # ツールレジストリ
    registry = ToolRegistry()
    
    # ここでツールモジュールを登録
    from tools import message_tools, shell_tools, file_tools, info_tools, deploy_tools, browser_tools, codeact_tools
    
    registry.register_tools_from_module("tools.message_tools")
    registry.register_tools_from_module("tools.shell_tools")
    registry.register_tools_from_module("tools.file_tools")
    registry.register_tools_from_module("tools.info_tools")
    registry.register_tools_from_module("tools.deploy_tools")
    registry.register_tools_from_module("tools.browser_tools")
    registry.register_tools_from_module("tools.codeact_tools")
    registry.register_tools_from_module("tools.system_tools")
    
    # メッセージツールをオーバーライド
    registry.register_tool(
        "message_notify_user",
        lambda text, attachments=None: message_queue.put(("notify", text, attachments)),
        message_tools.message_notify_user.tool_spec
    )
    
    registry.register_tool(
        "message_ask_user",
        lambda text, attachments=None, suggest_user_takeover="none": 
            message_queue.put(("ask", text, attachments, suggest_user_takeover)),
        message_tools.message_ask_user.tool_spec
    )
    
    # Planner
    planner = Planner(llm_client)
    
    # Memory
    if CONFIG["memory"]["use_vector_memory"]:
        try:
            from sentence_transformers import SentenceTransformer
            memory = EnhancedMemory(workspace_dir=CONFIG["system"]["workspace_dir"])
        except ImportError:
            st.warning("sentence_transformersのインポートに失敗しました。通常のメモリを使用します。")
            memory = Memory(workspace_dir=CONFIG["system"]["workspace_dir"])
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

def agent_runner(agent, task_input, stop_event):
    """別スレッドでエージェントを実行する関数"""
    try:
        message_queue.put(("status", "エージェントが起動しました"))
        agent.start(task_input)
        message_queue.put(("status", "エージェントが処理を完了しました"))
    except Exception as e:
        logger.error(f"エージェント実行中にエラー: {str(e)}", exc_info=True)
        message_queue.put(("error", f"エラーが発生しました: {str(e)}"))
    finally:
        stop_event.set()

def main():
    # Streamlit UIの設定
    st.set_page_config(
        page_title="Manus-Like Agent",
        page_icon="🤖",
        layout="wide"
    )
    
    # セッション状態の初期化
    if 'agent' not in st.session_state:
        st.session_state.agent = create_agent()
    if 'agent_thread' not in st.session_state:
        st.session_state.agent_thread = None
    if 'stop_event' not in st.session_state:
        st.session_state.stop_event = threading.Event()
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'user_query' not in st.session_state:
        st.session_state.user_query = ""
    if 'is_asking' not in st.session_state:
        st.session_state.is_asking = False
    if 'ask_message' not in st.session_state:
        st.session_state.ask_message = ""
    if 'needs_rerun' not in st.session_state:
        st.session_state.needs_rerun = False
    
    # 前回のリランフラグをチェック
    if st.session_state.needs_rerun:
        st.session_state.needs_rerun = False
    
    # タイトル
    st.title("Manus-Like Agent 🤖")
    
    # サイドバー (設定など)
    with st.sidebar:
        st.header("設定")
        
        # ワークスペースパス表示
        st.text(f"ワークスペース: {CONFIG['system']['workspace_dir']}")
        
        # モデル情報
        st.text(f"使用モデル: {CONFIG['llm']['model']}")
        
        # 停止ボタン
        if st.session_state.agent_thread and st.session_state.agent_thread.is_alive():
            if st.button("処理を停止", type="primary"):
                st.session_state.stop_event.set()
                st.session_state.agent.stop()
                st.info("停止リクエストを送信しました")
                st.session_state.needs_rerun = True
                st.rerun()  # st.experimental_rerunの代わりにst.rerunを使用
        
        # クリアボタン
        if st.button("履歴をクリア"):
            st.session_state.messages = []
            st.session_state.needs_rerun = True
            st.rerun()  # st.experimental_rerunの代わりにst.rerunを使用
        
        # ワークスペースディレクトリの表示
        if os.path.exists(CONFIG["system"]["workspace_dir"]):
            st.subheader("ワークスペースファイル")
            files = os.listdir(CONFIG["system"]["workspace_dir"])
            for file in files:
                if not file.startswith('.'):
                    st.text(file)
    
    # メインパネル
    col1, col2 = st.columns([2, 1])
    
    # メッセージ履歴パネル
    with col1:
        st.subheader("エージェントとの対話")
        
        # メッセージの表示
        message_container = st.container()
        with message_container:
            for msg in st.session_state.messages:
                if msg["type"] == "user":
                    st.chat_message("user").write(msg["content"])
                elif msg["type"] == "agent":
                    st.chat_message("assistant").write(msg["content"])
                elif msg["type"] == "notify":
                    with st.chat_message("assistant"):
                        st.info(msg["content"])
                elif msg["type"] == "status":
                    st.info(msg["content"])
                elif msg["type"] == "error":
                    st.error(msg["content"])
        
        # ユーザー入力フォーム
        with st.container():
            if st.session_state.is_asking:
                # エージェントからの質問に回答するフォーム
                with st.form(key="answer_form"):
                    st.write(f"**質問**: {st.session_state.ask_message}")
                    user_answer = st.text_area("回答を入力", key="answer_input", height=100)
                    submit_answer = st.form_submit_button("送信")
                    if submit_answer and user_answer:
                        # 回答をキューに追加してフォームをリセット
                        st.session_state.messages.append({"type": "user", "content": user_answer})
                        st.session_state.is_asking = False
                        st.session_state.ask_message = ""
                        # ここで回答を返す
                        message_queue.put(("user_answer", user_answer))
                        st.session_state.needs_rerun = True
                        st.rerun()  # st.experimental_rerunの代わりにst.rerunを使用
            else:
                # 通常の入力フォーム
                with st.form(key="query_form"):
                    user_query = st.text_area("タスクを指示してください", key="query_input", height=100)
                    submit_query = st.form_submit_button("送信")
                    
                    if submit_query and user_query:
                        # エージェントがすでに実行中かチェック
                        if st.session_state.agent_thread and st.session_state.agent_thread.is_alive():
                            st.error("前回の処理が完了するまでお待ちください")
                        else:
                            # 新しいスレッドでエージェントを開始
                            st.session_state.stop_event.clear()
                            st.session_state.messages.append({"type": "user", "content": user_query})
                            st.session_state.agent_thread = threading.Thread(
                                target=agent_runner,
                                args=(st.session_state.agent, user_query, st.session_state.stop_event)
                            )
                            st.session_state.agent_thread.start()
                            st.session_state.needs_rerun = True
                            st.rerun()  # st.experimental_rerunの代わりにst.rerunを使用
    
    # ステータスパネル
    with col2:
        st.subheader("エージェントステータス")
        
        status_container = st.empty()
        
        # エージェントのステータス表示
        if st.session_state.agent_thread and st.session_state.agent_thread.is_alive():
            status_container.info("🔄 処理中...")
        else:
            status_container.info("⏸️ アイドル状態")
        
        # プランの表示 (あれば)
        if hasattr(st.session_state.agent, 'context'):
            plans = [event for event in st.session_state.agent.context.get_events() if event.get("type") == "Plan"]
            if plans:
                latest_plan = plans[-1]
                st.subheader("現在の計画")
                st.text_area("", latest_plan.get("content", ""), height=400, disabled=True)
    
    # メッセージキューの処理
    process_message_queue()

def process_message_queue():
    """メッセージキューを処理してUIを更新"""
    try:
        while not message_queue.empty():
            msg = message_queue.get_nowait()
            msg_type = msg[0]
            
            if msg_type == "notify":
                _, text, attachments = msg
                st.session_state.messages.append({"type": "notify", "content": text})
                st.session_state.needs_rerun = True
                st.rerun()  # st.experimental_rerunの代わりにst.rerunを使用
            
            elif msg_type == "ask":
                _, text, attachments, suggest_takeover = msg
                st.session_state.is_asking = True
                st.session_state.ask_message = text
                st.session_state.messages.append({"type": "agent", "content": f"質問: {text}"})
                st.session_state.needs_rerun = True
                st.rerun()  # st.experimental_rerunの代わりにst.rerunを使用
            
            elif msg_type == "status":
                _, text = msg
                st.session_state.messages.append({"type": "status", "content": text})
                st.session_state.needs_rerun = True
                st.rerun()  # st.experimental_rerunの代わりにst.rerunを使用
            
            elif msg_type == "error":
                _, text = msg
                st.session_state.messages.append({"type": "error", "content": text})
                st.session_state.needs_rerun = True
                st.rerun()  # st.experimental_rerunの代わりにst.rerunを使用
            
            # その他のメッセージタイプの処理
            
    except Exception as e:
        logger.error(f"メッセージキュー処理中にエラー: {str(e)}")

if __name__ == "__main__":
    main()
