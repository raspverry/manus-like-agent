# tools/info_tools.py
"""
検索エンジンを使用したWeb検索などの情報取得ツール。
(実際はAPI利用だが、ここではデモ用)
"""
import logging
import random
from tools.tool_registry import tool

logger = logging.getLogger(__name__)

DEMO_SEARCH = {
    "ai": [
        {
            "title": "AI総合ガイド",
            "url": "https://example.com/ai-guide",
            "snippet": "AIとは何か、機械学習・深層学習・応用事例などをまとめた記事。"
        },
        {
            "title": "AI最新ニュース2025",
            "url": "https://example.com/ai-news2025",
            "snippet": "2025年のAI技術動向と今後の課題について。"
        }
    ],
    "python": [
        {
            "title": "Python公式サイト",
            "url": "https://www.python.org/",
            "snippet": "Python言語の公式情報。ダウンロードやドキュメント。"
        },
        {
            "title": "Python入門",
            "url": "https://example.com/python-intro",
            "snippet": "初心者向けにPythonの文法・実践例を紹介。"
        }
    ]
}

@tool(
    name="info_search_web",
    description="検索エンジンでWeb検索を行う (デモ)",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "date_range": {
                "type": "string",
                "enum": ["all", "past_day", "past_week", "past_month", "past_year"]
            }
        },
        "required": ["query"]
    }
)
def info_search_web(query: str, date_range: str = "all"):
    # デモ実装
    logger.info(f"検索クエリ: {query}, date_range={date_range}")
    keywords = query.lower().split()
    results = []
    for kw in keywords:
        if kw in DEMO_SEARCH:
            results.extend(DEMO_SEARCH[kw])
    if not results:
        # ランダムで返す
        for vals in DEMO_SEARCH.values():
            results.extend(vals)
        results = random.sample(results, min(len(results), 2))
    out = f"検索クエリ: {query}\n"
    for i, r in enumerate(results, start=1):
        out += f"{i}. {r['title']} (URL: {r['url']})\n   概要: {r['snippet']}\n"
    return out
