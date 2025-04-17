import chainlit as cl
import requests
import asyncio
import websockets
import json
import os
import uuid
import logging
from typing import Dict, Any, Optional

# ログの設定: INFOレベルでログを出力します。
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("manus-chainlit")

# バックエンドAPIとWebSocketのURLを設定します。
# 必要に応じて環境変数や設定ファイルで管理してください。
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8001/api")
WS_BASE_URL = os.getenv("WS_BASE_URL", "ws://localhost:8001/ws")

# セッション情報を保持します。
session_data = {
    "session_id": None,
    "ws_connection": None,
    "is_connected": False
}

async def connect_to_websocket(session_id: str) -> bool:
    """
    バックエンドのWebSocketに接続します。
    成功するとTrueを返します。
    """
    try:
        logger.info(f"WebSocketに接続中: セッションID={session_id}")
        connection = await websockets.connect(f"{WS_BASE_URL}/{session_id}")
        session_data["ws_connection"] = connection
        session_data["is_connected"] = True
        # メッセージ受信の非同期タスクを開始
        asyncio.create_task(listen_for_messages(connection))
        return True
    except Exception as e:
        logger.error(f"WebSocket接続エラー: {e}")
        await cl.Message(content=f"WebSocket接続エラー: {e}", author="Error").send()
        return False

async def listen_for_messages(connection: websockets.WebSocketClientProtocol):
    """
    WebSocketからのメッセージを受信し、対応する処理を行います。
    """
    try:
        while session_data["is_connected"]:
            raw = await connection.recv()
            logger.info("WebSocketメッセージを受信しました")
            try:
                data = json.loads(raw)
                msg_type = data.get("type")
                content = data.get("content", "")

                if msg_type == "notify":
                    # 一方向通知メッセージ
                    await cl.Message(content=content).send()
                elif msg_type == "ask":
                    # ユーザーへの質問
                    await cl.Message(content=content).send()
                    # ユーザーの入力を待つ
                    response = await cl.AskUserMessage(content="").send()
                    logger.info(f"ユーザー応答: {response}")
                    # 応答をバックエンドへ送信
                    await connection.send(json.dumps({"type": "response", "content": response}))
                elif msg_type == "status":
                    # ステータス更新
                    await cl.Message(content=content, author="System").send()
                elif msg_type == "error":
                    # エラー表示
                    await cl.Message(content=content, author="Error").send()
                else:
                    # 未知のメッセージタイプ
                    logger.warning(f"未知のメッセージタイプ: {msg_type}")
            except json.JSONDecodeError:
                logger.error(f"無効なJSONフォーマット: {raw}")
                await cl.Message(content="サーバーから無効なメッセージが届きました。", author="Error").send()
    except websockets.exceptions.ConnectionClosed:
        logger.warning("WebSocket接続が閉じられました。再接続してください。")
        session_data["is_connected"] = False
        await cl.Message(content="エージェントとの接続が切断されました。ページをリロードして再接続してください。", author="System").send()
    except Exception as e:
        logger.error(f"WebSocket受信中エラー: {e}")
        session_data["is_connected"] = False
        await cl.Message(content=f"受信エラー: {e}", author="Error").send()

@cl.on_chat_start
async def on_chat_start():
    """
    新しいチャット開始時の初期化処理です。
    セッションIDを生成し、バックエンドへWebSocket接続を試みます。
    """
    session_data["session_id"] = str(uuid.uuid4())
    logger.info(f"新規チャットセッション開始: {session_data['session_id']}")

    success = await connect_to_websocket(session_data["session_id"])
    if success:
        # ウェルカムメッセージとシステム情報を表示
        await cl.Message(
            content="Manus-Like Agent 🤖\n\nタスクを入力してください。",
            author="System"
        ).send()
        await cl.Message(
            content="このエージェントはコマンド実行、ファイル作成、ウェブ検索など、さまざまなタスクをサポートします。",
            author="System",
            actions=[
                cl.Action(
                    name="stop_agent",
                    label="エージェントを停止",
                    description="実行中のエージェントを停止する",
                    payload={"session_id": session_data["session_id"]}
                )
            ]
        ).send()
    else:
        await cl.Message(content="バックエンドに接続できませんでした。サーバーの起動を確認してください。", author="Error").send()

@cl.on_message
async def on_message(message: cl.Message):
    """
    ユーザーからのメッセージ受信時のハンドラーです。
    バックエンドへタスクを送信します。
    """
    user_input = message.content
    logger.info(f"ユーザーメッセージ受信: {user_input}")

    if not session_data["is_connected"]:
        # 未接続状態なら再接続を試行
        logger.info("未接続のため再接続を試行します。")
        success = await connect_to_websocket(session_data["session_id"])
        if not success:
            await cl.Message(content="エージェントに接続できません。サーバーの起動を確認してください。", author="Error").send()
            return

    # タスクをバックエンドへ送信
    try:
        await session_data["ws_connection"].send(
            json.dumps({"type": "task", "content": user_input})
        )
    except Exception as e:
        logger.error(f"タスク送信エラー: {e}")
        await cl.Message(content=f"タスク送信エラー: {e}", author="Error").send()
        session_data["is_connected"] = False

@cl.action_callback("stop_agent")
async def on_stop_action(action: cl.Action):
    """
    停止ボタンがクリックされた時のコールバックです。
    payloadのsession_idを使ってエージェントを停止します。
    """
    sid = action.payload.get("session_id")
    if not sid or not session_data["is_connected"]:
        await cl.Message(content="停止できません：セッションが無効です。", author="Error").send()
        return

    logger.info(f"停止リクエスト: セッションID={sid}")
    # WebSocketで停止を送信
    try:
        await session_data["ws_connection"].send(json.dumps({"type": "stop"}))
        await cl.Message(content="エージェントに停止リクエストを送信しました。", author="System").send()
    except Exception as e:
        logger.error(f"WebSocket停止エラー: {e}")
        # フォールバックでREST APIを使用
        try:
            response = requests.post(f"{API_BASE_URL}/stop/{sid}")
            if response.status_code == 200:
                await cl.Message(content="エージェントを正常に停止しました。", author="System").send()
            else:
                await cl.Message(content=f"停止中にエラーが発生しました: {response.text}", author="Error").send()
        except Exception as err:
            logger.error(f"REST API停止エラー: {err}")
            await cl.Message(content=f"停止エラー: {err}", author="Error").send()

# ChainlitのCLIで起動するため、 __main__ ブロックは不要です。
