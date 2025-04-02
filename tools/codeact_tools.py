# tools/codeact_tools.py
"""
CodeActツール: LLMがPythonコードを生成し、それをDockerサンドボックスで実行する。
"""
import logging
from typing import Optional
from tools.tool_registry import tool
from sandbox.sandbox import get_sandbox

logger = logging.getLogger(__name__)

@tool(
    name="code_execute",
    description="LLMが生成したPythonコードをDockerサンドボックスで実行する",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "container_id": {"type": "string", "description": "(オプション) 既存コンテナID"},
        },
        "required": ["code"]
    }
)
def code_execute(code: str, container_id: Optional[str] = None):
    sandbox = get_sandbox()
    stdout, stderr, exit_code = sandbox.execute_python(container_id or "codeact-session", code)
    if stderr:
        return f"[stdout]\n{stdout}\n\n[stderr]\n{stderr}\nExitCode: {exit_code}"
    else:
        return f"[stdout]\n{stdout}\nExitCode: {exit_code}"
