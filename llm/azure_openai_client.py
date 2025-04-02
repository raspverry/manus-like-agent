# llm/azure_openai_client.py
import os
from openai import AzureOpenAI
import logging

logger = logging.getLogger(__name__)

class AzureOpenAIClient:
    def __init__(self):
        # 環境変数から設定を取得
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2023-07-01-preview")
        deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "deployment-name")

        if not api_key or not azure_endpoint or not deployment_name:
            raise ValueError("Azure OpenAIの設定が不足しています (.envファイルを確認してください)")

        # AzureOpenAIクライアントの初期化
        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version
        )
        self.deployment_name = deployment_name
        logger.info("Azure OpenAIクライアントが初期化されました")

    def call_azure_openai(self, prompt: str, system_prompt: str, model: str, temperature: float, max_tokens: int) -> str:
        """
        Azure OpenAIでChatCompletionを呼び出し、応答テキストを返す。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        logger.info("Azure OpenAIへメッセージを送信中")
        try:
            completion = self.client.chat.completions.create(
                model=self.deployment_name,  # デプロイメント名を指定
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            # completion.to_json()は応答をJSON形式で返すので、choicesから内容を抽出
            result = completion.to_json()
            # 例: {"choices": [{"message": {"content": "返答テキスト", ...}}], ...}
            if isinstance(result, dict) and "choices" in result:
                return result["choices"][0]["message"]["content"]
            else:
                return str(result)
        except Exception as e:
            logger.error(f"Azure OpenAIエラー: {str(e)}")
            raise
