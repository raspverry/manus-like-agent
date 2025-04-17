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
import re
import json
from core.logging_config import logger
import os
from typing import Any, Dict, List, Tuple

from langchain_openai import AzureChatOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider



class AzureOpenAIClient:
    """Azure OpenAI Service ラッパー。"""

    def __init__(self) -> None:
        TOKEN_PROVIDER = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION")
        deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        
        model_name="gpt-4o"
        if not all([api_key, endpoint, deployment_name]):
            raise EnvironmentError("Azure OpenAI の環境変数が不足しています。")
        
        self._client = AzureChatOpenAI(
            # api_key=api_key,
            azure_ad_token_provider=TOKEN_PROVIDER,
            azure_endpoint=endpoint,
            api_version=api_version,
            azure_deployment=model_name,
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
            # "model": self._deployment,
            # "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if force_json:
            params["response_format"] = {"type": "json_object"}

        try:
            resp = self._client.invoke(messages,**params)
            
            # content = resp.choices[0].message.content or ""
            content = resp.content
            json_pattern = r'```json\s*(.*?)\s*```'
            
            match = re.search(json_pattern, content, re.DOTALL)
        
            if match:
                json_text = match.group(1).strip()
            else:
                # JSONブロックがない場合は、{で始まり}で終わる部分を探す
                json_pattern = r'(\{.*\})'
                match = re.search(json_pattern, content, re.DOTALL)
                if match:
                    json_text = match.group(1).strip()
                else:
                    print(content)
                    raise ValueError("JSONデータが見つかりません")
            result = json.loads(json_text)
            # Get usage from response_metadata
            usage = {}
            if hasattr(resp, 'response_metadata') and resp.response_metadata:
                if 'token_usage' in resp.response_metadata:
                    usage = resp.response_metadata['token_usage']
                elif 'usage_metadata' in resp.response_metadata:
                    usage = resp.response_metadata['usage_metadata']
            return result, usage
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
