# tools/codeact_tools.py
"""
強化されたCodeActツール: LLMがPythonコードを生成し、それをDockerサンドボックスで実行する。
Manusのようなエージェントシステムで、コードをアクションとして使用する「CodeAct」パラダイムを実装。
"""
import logging
from typing import Optional, Dict, Any
import json
import time
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
            "description": {"type": "string", "description": "(オプション) コードの目的説明"}
        },
        "required": ["code"]
    }
)
def code_execute(code: str, container_id: Optional[str] = None, description: Optional[str] = None):
    """
    LLMが生成したPythonコードをDockerサンドボックスで実行します。
    
    Args:
        code: 実行するPythonコード
        container_id: (オプション) 既存のコンテナID。指定しない場合は「codeact-session」
        description: (オプション) コードの目的説明、ログ記録用
    
    Returns:
        実行結果を含む文字列
    """
    description_text = f"目的: {description}" if description else "コード実行"
    logger.info(f"{description_text} - コード実行開始")
    
    start_time = time.time()
    sandbox = get_sandbox()
    stdout, stderr, exit_code = sandbox.execute_python(container_id or "codeact-session", code)
    execution_time = time.time() - start_time
    
    if stderr:
        logger.warning(f"コード実行でエラー発生 (終了コード: {exit_code}): {stderr[:100]}...")
        return f"[実行時間: {execution_time:.2f}秒]\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\nExitCode: {exit_code}"
    else:
        logger.info(f"コード実行成功 (実行時間: {execution_time:.2f}秒)")
        return f"[実行時間: {execution_time:.2f}秒]\n\n[stdout]\n{stdout}\nExitCode: {exit_code}"

@tool(
    name="code_analyze_and_execute",
    description="問題を分析し、それを解決するコードを生成して実行します",
    parameters={
        "type": "object",
        "properties": {
            "problem": {"type": "string", "description": "解決すべき問題の説明"},
            "context": {"type": "string", "description": "(オプション) 追加コンテキスト情報"},
            "container_id": {"type": "string", "description": "(オプション) 既存コンテナID"}
        },
        "required": ["problem"]
    }
)
def code_analyze_and_execute(problem: str, context: str = "", container_id: Optional[str] = None):
    """
    問題を分析し、それを解決するPythonコードを生成して実行します。
    
    このツールは「CodeAct」パラダイムの実装例で、アクションをコードとして表現します。
    LLMはこの関数を直接呼び出すのではなく、問題を解決するコードを生成して
    code_executeツールで実行するよう促されます。
    
    Args:
        problem: 解決すべき問題の説明
        context: 追加のコンテキスト情報
        container_id: 既存のコンテナID
    
    Returns:
        コード実行の結果を含む文字列
    """
    # 注: この関数の実装はLLMが問題に対するコードを直接生成することを期待しています
    # そのため、実際の関数コールではなく、プロンプトガイダンスとして機能します
    return "この関数は直接呼び出すためではなく、プロンプトガイダンスです。問題を解析し、Pythonコードを生成して実行してください。"

@tool(
    name="codeact_data_analysis",
    description="データ分析と処理のためのコードを実行します",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "実行するPythonコード"},
            "data_file": {"type": "string", "description": "分析対象のデータファイルパス"},
            "container_id": {"type": "string", "description": "(オプション) 既存コンテナID"}
        },
        "required": ["code", "data_file"]
    }
)
def codeact_data_analysis(code: str, data_file: str, container_id: Optional[str] = None):
    """
    データ分析と処理のためのコードを実行します。
    
    データファイルパスを指定して、pandas、numpy、matplotlib等のライブラリを使った
    データ分析コードを実行するために最適化されています。
    
    Args:
        code: 実行するPythonコード
        data_file: 分析対象のデータファイルパス
        container_id: 既存のコンテナID
    
    Returns:
        分析結果を含む文字列
    """
    # データファイルの存在確認
    import os
    if not os.path.exists(data_file):
        return f"エラー: 指定されたデータファイル '{data_file}' が存在しません。"
    
    # 必要なライブラリをimportするコードをプリペンド
    enhanced_code = f"""
# 必要なライブラリをインポート
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import os
import json
import sys

# データファイルパスを設定
DATA_FILE = "{data_file}"

# メイン処理
try:
    # ユーザーコードを実行
    {code}
except Exception as e:
    print(f"エラーが発生しました: {{str(e)}}")
    import traceback
    print(traceback.format_exc())
"""
    
    # 分析実行のログ記録
    logger.info(f"データ分析を実行: {data_file}")
    
    # Dockerサンドボックスでコードを実行
    sandbox = get_sandbox()
    stdout, stderr, exit_code = sandbox.execute_python(container_id or "codeact-session", enhanced_code)
    
    if stderr and exit_code != 0:
        logger.warning(f"データ分析でエラー発生: {stderr[:100]}...")
        return f"データ分析エラー:\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\nExitCode: {exit_code}"
    else:
        # 画像ファイルが生成されたかチェック (一般的なデータ可視化の結果)
        # ここでは簡易的な例として、標準出力のみを返す
        logger.info(f"データ分析成功: {data_file}")
        return f"データ分析結果:\n\n{stdout}"
