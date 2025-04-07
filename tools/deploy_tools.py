# tools/deploy_tools.py
"""
デプロイに関するツール（デモ）。
"""
from core.logging_config import logger
import os
from tools.tool_registry import tool



@tool(
    name="deploy_expose_port",
    description="ローカルポートを一時公開する(デモ)",
    parameters={
        "type": "object",
        "properties": {
            "port": {"type": "integer"}
        },
        "required": ["port"]
    }
)
def deploy_expose_port(port: int):
    # 本来はngrokやcloudflared等を起動
    return f"ポート {port} をhttps://xxxxx.example.com で公開しました(デモ)"

@tool(
    name="deploy_apply_deployment",
    description="静的またはNext.jsのプロジェクトを本番にデプロイ(デモ)",
    parameters={
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["static", "nextjs"]},
            "local_dir": {"type": "string"}
        },
        "required": ["type","local_dir"]
    }
)
def deploy_apply_deployment(type: str, local_dir: str):
    # デモ実装
    if not os.path.exists(local_dir):
        return f"ディレクトリが存在しません: {local_dir}"
    return f"{type}アプリを {local_dir} からデプロイ成功(デモ)"
