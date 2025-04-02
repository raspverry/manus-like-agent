# tools/browser_tools.py
"""
Playwrightを使用したブラウザ操作ツール。
"""
import logging
import asyncio
import os
from typing import Optional, Union
from tools.tool_registry import tool
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

_browser_context = None

async def _ensure_browser(headless: bool = True):
    global _browser_context
    if _browser_context is not None:
        return _browser_context
    
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=headless)
    context = await browser.new_context()
    _browser_context = context
    return context

@tool(
    name="browser_navigate",
    description="Playwrightで指定URLにアクセスする",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"}
        },
        "required": ["url"]
    }
)
def browser_navigate(url: str):
    # 同期関数として実行
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_navigate_async(url))
    loop.close()
    return res

async def _navigate_async(url: str):
    context = await _ensure_browser(headless=True)
    page = await context.new_page()
    try:
        await page.goto(url, timeout=15000)
        content = await page.content()
        title = await page.title()
        # ここでページ内容やタイトルを返す
        text = f"ページタイトル: {title}\n\nHTML:\n{content[:2000]}..."
        return text
    except Exception as e:
        return f"ナビゲート失敗: {str(e)}"

@tool(
    name="browser_view",
    description="現在のページ内容を表示する(Playwrightセッション内)",
    parameters={
        "type": "object",
        "properties": {}
    }
)
def browser_view():
    # ここでは最後に作ったページを参照(簡易)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_view_async())
    loop.close()
    return res

async def _view_async():
    if _browser_context is None:
        return "まだブラウザコンテキストがありません"
    pages = _browser_context.pages
    if not pages:
        return "ページが開かれていません"
    page = pages[-1]
    try:
        content = await page.content()
        title = await page.title()
        text = f"ページタイトル: {title}\n\nHTML:\n{content[:2000]}..."
        return text
    except Exception as e:
        return f"閲覧失敗: {str(e)}"

@tool(
    name="browser_click",
    description="ページ内の要素をクリックする(デモ)",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string"}
        },
        "required": ["selector"]
    }
)
def browser_click(selector: str):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_click_async(selector))
    loop.close()
    return res

async def _click_async(selector: str):
    if _browser_context is None:
        return "ブラウザコンテキストがありません"
    page = _browser_context.pages[-1]
    try:
        await page.click(selector, timeout=5000)
        return f"要素 '{selector}' をクリックしました"
    except Exception as e:
        return f"クリック失敗: {str(e)}"

@tool(
    name="browser_input",
    description="入力欄にテキストを入力してEnter可",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "text": {"type": "string"},
            "press_enter": {"type": "boolean"}
        },
        "required": ["selector","text","press_enter"]
    }
)
def browser_input(selector: str, text: str, press_enter: bool):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_input_async(selector, text, press_enter))
    loop.close()
    return res

async def _input_async(selector: str, text: str, press_enter: bool):
    if _browser_context is None:
        return "ブラウザコンテキストがありません"
    page = _browser_context.pages[-1]
    try:
        await page.fill(selector, text)
        if press_enter:
            await page.press(selector, "Enter")
        return f"入力完了: {selector} => {text}"
    except Exception as e:
        return f"入力失敗: {str(e)}"

@tool(
    name="browser_scroll_down",
    description="ページを下にスクロール(簡易)",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "integer"}
        },
        "required": ["amount"]
    }
)
def browser_scroll_down(amount: int):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_scroll_async(amount))
    loop.close()
    return res

async def _scroll_async(amount: int):
    if _browser_context is None:
        return "ブラウザコンテキストがありません"
    page = _browser_context.pages[-1]
    try:
        await page.evaluate(f"window.scrollBy(0, {amount})")
        return f"{amount}pxスクロールしました"
    except Exception as e:
        return f"スクロール失敗: {str(e)}"
