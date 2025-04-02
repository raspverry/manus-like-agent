# tools/message_tools.py
"""
ユーザーへのメッセージ送信・受信を扱うツール。
"""
import logging
from typing import Union, List
from tools.tool_registry import tool

logger = logging.getLogger(__name__)

@tool(
    name="message_notify_user",
    description="応答不要のメッセージをユーザーに送信する",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "attachments": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}}
                ]
            }
        },
        "required": ["text"]
    }
)
def message_notify_user(text: str, attachments: Union[str, List[str], None] = None):
    logger.info(f"ユーザーへの通知: {text}")
    print(f"\n[通知] {text}")
    if attachments:
        print(f"[添付] {attachments}")
    return "メッセージを送信しました"

@tool(
    name="message_ask_user",
    description="ユーザーに質問し、応答を待つ",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "attachments": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}}
                ]
            },
            "suggest_user_takeover": {
                "type": "string",
                "enum": ["none", "browser"]
            }
        },
        "required": ["text"]
    }
)
def message_ask_user(text: str, attachments: Union[str, List[str], None] = None, suggest_user_takeover: str = "none"):
    logger.info(f"ユーザーへの質問: {text}")
    print(f"\n[質問] {text}")
    if attachments:
        print(f"[添付] {attachments}")
    if suggest_user_takeover != "none":
        print(f"[提案] {suggest_user_takeover} の操作をユーザーに引き継ぐ")
    response = input("ユーザーの応答: ")
    return response
