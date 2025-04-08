# llm/azure_openai_client.py
"""
Azure OpenAI クライアント（最新版・JSON モード対応）
====================================================
* Azure OpenAI 専用エンドポイントでチャット補完を呼び出す。
* `response_format={"type": "json_object"}` を任意で指定可能。
* トークン使用量を含む usage 辞書を返却。
* SDK v1 系列に依存し、追加の `openai.types` インポートは不要。
"""

from __future__ import annotations

from core.logging_config import logger
import os
from typing import Any, Dict, List, Tuple

from openai import AzureOpenAI




class AzureOpenAIClient:
    """Azure OpenAI Service ラッパー。"""

    def __init__(self) -> None:
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2023-12-01-preview")
        deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

        if not all([api_key, endpoint, deployment_name]):
            raise EnvironmentError("Azure OpenAI の環境変数が不足しています。")

        self._client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
            max_retries=0
        )
        self._deployment = deployment_name
        logger.info("Azure OpenAI クライアント初期化完了")

    # ---------------------------------------------------------
    # チャット補完
    # ---------------------------------------------------------
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        force_json: bool = False,
    ) -> Tuple[str, Dict[str, Any]]:
        """ChatCompletion 呼び出し。

        Returns:
            content: 生成テキスト
            usage:   {prompt_tokens, completion_tokens, total_tokens}
        """
        params: Dict[str, Any] = {
            "model": self._deployment,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if force_json:
            params["response_format"] = {"type": "json_object"}

        try:
            resp = self._client.chat.completions.create(**params)
            content = resp.choices[0].message.content or ""
            usage = resp.usage.model_dump() if resp.usage else {}
            return content, usage
        except Exception as exc:
            logger.error(f"Azure OpenAI 呼び出し失敗: {exc}")
            raise

    def call_azure_openai(
        self,
        prompt: str,
        system_prompt: str,
        model: str,  # 無視されるが互換性のため残す
        temperature: float,
        max_tokens: int,
        force_json: bool = False,
    ) -> str:
        content, _ = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            force_json=force_json,
        )
        return content
