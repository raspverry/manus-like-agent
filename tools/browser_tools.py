# tools/browser_tools.py
"""
強化されたブラウザ操作ツール。Playwrightを使用した高度なウェブスクレイピングと対話機能を提供。
"""
import logging
import asyncio
import os
import json
import re
from typing import Optional, Union, Dict, Any, List
from urllib.parse import urlparse
from tools.tool_registry import tool
from playwright.async_api import async_playwright, Page

logger = logging.getLogger(__name__)

# グローバル変数
_browser_context = None
_current_page = None

async def _ensure_browser(headless: bool = True):
    """ブラウザセッションが存在することを確認し、必要に応じて初期化する"""
    global _browser_context, _current_page
    
    if _browser_context is not None:
        return _browser_context, _current_page
    
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=headless)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
    )
    
    _browser_context = context
    _current_page = await context.new_page()
    
    return context, _current_page

@tool(
    name="browser_navigate",
    description="Playwrightで指定URLにアクセスする",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "アクセスするURL"}
        },
        "required": ["url"]
    }
)
def browser_navigate(url: str):
    """
    指定されたURLにブラウザでアクセスします。
    
    Args:
        url: アクセスするURL
        
    Returns:
        ページの内容とタイトルを含む文字列
    """
    # 同期関数として実行
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_navigate_async(url))
    loop.close()
    return res

async def _navigate_async(url: str):
    """非同期でURLにアクセスし、ページ内容を取得"""
    context, page = await _ensure_browser(headless=True)
    
    try:
        # URLにプロトコルがなければ追加
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        
        # ページにアクセス
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        
        # ページが完全に読み込まれるまで少し待機
        await asyncio.sleep(2)
        
        # ページのタイトルとURLを取得
        title = await page.title()
        current_url = page.url
        
        # ページの内容をMarkdown形式で抽出
        extracted_text = await _extract_content_as_markdown(page)
        
        # 結果を整形
        result = (
            f"## ページ情報\n"
            f"タイトル: {title}\n"
            f"URL: {current_url}\n\n"
            f"## ページ内容\n"
            f"{extracted_text}\n\n"
            f"※注意: コンテンツが多すぎる場合は一部のみ表示されます。browser_scroll_downを使用して下にスクロールすると、さらに表示できます。"
        )
        
        return result
    except Exception as e:
        error_message = f"ナビゲーションエラー: {str(e)}"
        logger.error(error_message)
        return error_message

async def _extract_content_as_markdown(page: Page) -> str:
    """ページの内容をMarkdown形式で抽出"""
    try:
        # ページからテキストコンテンツを抽出するJavaScriptを実行
        markdown = await page.evaluate("""() => {
            function getVisibleText(element, depth = 0) {
                if (!element) return '';
                
                // 非表示要素をスキップ
                const style = window.getComputedStyle(element);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                    return '';
                }
                
                // テキストノードの場合
                if (element.nodeType === Node.TEXT_NODE) {
                    return element.textContent.trim() ? element.textContent.trim() + ' ' : '';
                }
                
                // 要素の種類に基づいてマークダウン形式に変換
                let md = '';
                const tagName = element.tagName ? element.tagName.toLowerCase() : '';
                
                // 見出し
                if (tagName.match(/^h[1-6]$/)) {
                    const level = tagName.charAt(1);
                    let prefix = '';
                    for (let i = 0; i < parseInt(level); i++) {
                        prefix += '#';
                    }
                    md += `\\n${prefix} `;
                }
                // 段落
                else if (tagName === 'p') {
                    md += '\\n\\n';
                }
                // リスト項目
                else if (tagName === 'li') {
                    md += '\\n- ';
                }
                // テーブル行
                else if (tagName === 'tr') {
                    md += '\\n|';
                }
                // テーブルデータ
                else if (tagName === 'td' || tagName === 'th') {
                    md += ' ';
                }
                
                // 子要素を再帰的に処理
                for (const child of element.childNodes) {
                    md += getVisibleText(child, depth + 1);
                }
                
                // 特定の要素の後に改行を追加
                if (tagName === 'div' || tagName === 'section' || tagName === 'article') {
                    md += '\\n';
                }
                else if (tagName === 'td' || tagName === 'th') {
                    md += ' |';
                }
                
                return md;
            }
            
            return getVisibleText(document.body).replace(/\\n\\s*\\n\\s*\\n/g, '\\n\\n').trim();
        }""")
        
        # 長すぎる場合は切り詰める
        if len(markdown) > 10000:
            markdown = markdown[:10000] + "...\n\n(コンテンツが長すぎるため切り詰められました)"
        
        return markdown
    except Exception as e:
        logger.error(f"コンテンツ抽出エラー: {str(e)}")
        return f"コンテンツの抽出に失敗しました: {str(e)}"

@tool(
    name="browser_extract_elements",
    description="ページから特定の要素を抽出する",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "抽出する要素のCSSセレクタ"},
            "attribute": {"type": "string", "description": "(オプション) 抽出する属性名"}
        },
        "required": ["selector"]
    }
)
def browser_extract_elements(selector: str, attribute: Optional[str] = None):
    """
    現在のページから特定の要素を抽出します。
    
    Args:
        selector: 抽出する要素のCSSセレクタ
        attribute: 抽出する属性名（指定しない場合はテキスト内容を抽出）
        
    Returns:
        抽出された要素のリストを含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_extract_elements_async(selector, attribute))
    loop.close()
    return res

async def _extract_elements_async(selector: str, attribute: Optional[str] = None):
    """非同期で要素を抽出"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # セレクタに一致する要素を取得
        elements = await _current_page.query_selector_all(selector)
        
        if not elements:
            return f"セレクタ '{selector}' に一致する要素が見つかりませんでした。"
        
        results = []
        
        for i, element in enumerate(elements):
            if attribute:
                # 特定の属性を抽出
                value = await element.get_attribute(attribute)
                results.append(f"{i+1}. [{attribute}] {value}")
            else:
                # テキスト内容を抽出
                text = await element.text_content()
                results.append(f"{i+1}. {text.strip()}")
        
        return f"抽出された要素 (合計: {len(results)}件):\n\n" + "\n".join(results)
    
    except Exception as e:
        error_message = f"要素抽出エラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_extract_structured_data",
    description="ウェブページから構造化データを抽出する",
    parameters={
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": ["table", "list", "form", "links"],
                "description": "抽出するデータの種類"
            }
        },
        "required": ["data_type"]
    }
)
def browser_extract_structured_data(data_type: str):
    """
    現在のウェブページから構造化データを抽出します。
    
    Args:
        data_type: 抽出するデータの種類（table, list, form, links）
        
    Returns:
        抽出された構造化データを含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_extract_structured_data_async(data_type))
    loop.close()
    return res

async def _extract_structured_data_async(data_type: str):
    """非同期で構造化データを抽出"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        if data_type == "table":
            # テーブルデータを抽出
            tables = await _current_page.query_selector_all("table")
            
            if not tables:
                return "ページ内にテーブルが見つかりませんでした。"
            
            results = []
            
            for i, table in enumerate(tables):
                table_data = await _current_page.evaluate("""(table) => {
                    const rows = Array.from(table.querySelectorAll('tr'));
                    return rows.map(row => {
                        const cells = Array.from(row.querySelectorAll('th, td'));
                        return cells.map(cell => cell.textContent.trim());
                    });
                }""", table)
                
                if table_data and table_data[0]:
                    results.append(f"テーブル {i+1}:\n")
                    
                    # ヘッダー行とデータ行を分離
                    headers = table_data[0]
                    data_rows = table_data[1:]
                    
                    # ヘッダーを表示
                    results.append("| " + " | ".join(headers) + " |")
                    results.append("| " + " | ".join(["---" for _ in headers]) + " |")
                    
                    # データ行を表示
                    for row in data_rows:
                        results.append("| " + " | ".join(row) + " |")
                    
                    results.append("\n")
            
            return "\n".join(results)
        
        elif data_type == "list":
            # リストデータを抽出
            lists = await _current_page.query_selector_all("ul, ol")
            
            if not lists:
                return "ページ内にリストが見つかりませんでした。"
            
            results = []
            
            for i, list_element in enumerate(lists):
                list_type = await list_element.get_attribute("type")
                is_ordered = await list_element.evaluate("element => element.tagName.toLowerCase() === 'ol'")
                
                list_items = await list_element.query_selector_all("li")
                if not list_items:
                    continue
                
                results.append(f"\nリスト {i+1} ({('順序付き' if is_ordered else '順序なし')}):")
                
                for j, item in enumerate(list_items):
                    text = await item.text_content()
                    prefix = f"{j+1}." if is_ordered else "-"
                    results.append(f"{prefix} {text.strip()}")
            
            return "\n".join(results)
        
        elif data_type == "form":
            # フォーム要素を抽出
            forms = await _current_page.query_selector_all("form")
            
            if not forms:
                return "ページ内にフォームが見つかりませんでした。"
            
            results = []
            
            for i, form in enumerate(forms):
                form_action = await form.get_attribute("action") or "未指定"
                form_method = await form.get_attribute("method") or "GET"
                
                results.append(f"\nフォーム {i+1}:")
                results.append(f"アクション: {form_action}")
                results.append(f"メソッド: {form_method}")
                results.append("フィールド:")
                
                input_elements = await form.query_selector_all("input, select, textarea, button")
                
                for input_elem in input_elements:
                    elem_type = await input_elem.evaluate("element => element.tagName.toLowerCase()")
                    
                    if elem_type == "input":
                        input_type = await input_elem.get_attribute("type") or "text"
                        name = await input_elem.get_attribute("name") or "未指定"
                        placeholder = await input_elem.get_attribute("placeholder") or ""
                        
                        results.append(f"- Input: type={input_type}, name={name}" + (f", placeholder=\"{placeholder}\"" if placeholder else ""))
                    
                    elif elem_type == "select":
                        name = await input_elem.get_attribute("name") or "未指定"
                        options = await input_elem.query_selector_all("option")
                        option_values = []
                        
                        for option in options:
                            text = await option.text_content()
                            value = await option.get_attribute("value")
                            option_values.append(f"{text.strip()}={value}")
                        
                        results.append(f"- Select: name={name}, options=[{', '.join(option_values[:5])}]" + ("..." if len(option_values) > 5 else ""))
                    
                    elif elem_type == "textarea":
                        name = await input_elem.get_attribute("name") or "未指定"
                        results.append(f"- Textarea: name={name}")
                    
                    elif elem_type == "button":
                        button_type = await input_elem.get_attribute("type") or "button"
                        text = await input_elem.text_content()
                        results.append(f"- Button: type={button_type}, text=\"{text.strip()}\"")
            
            return "\n".join(results)
        
        elif data_type == "links":
            # リンクを抽出
            links = await _current_page.query_selector_all("a[href]")
            
            if not links:
                return "ページ内にリンクが見つかりませんでした。"
            
            results = ["抽出されたリンク:"]
            
            current_url = _current_page.url
            parsed_current = urlparse(current_url)
            current_base = f"{parsed_current.scheme}://{parsed_current.netloc}"
            
            link_data = []
            
            for link in links:
                text = await link.text_content()
                href = await link.get_attribute("href")
                
                if not href or href.startswith("javascript:"):
                    continue
                
                # 相対URLを絶対URLに変換
                if href.startswith("/"):
                    href = f"{current_base}{href}"
                elif not href.startswith(("http://", "https://")):
                    href = f"{current_base}/{href}"
                
                link_data.append({"text": text.strip() or "[画像/アイコン]", "href": href})
            
            # リンクを重複排除して表示
            unique_links = []
            seen_hrefs = set()
            
            for link in link_data:
                if link["href"] not in seen_hrefs and link["text"]:
                    unique_links.append(link)
                    seen_hrefs.add(link["href"])
            
            # リンクの表示（上位50件まで）
            for i, link in enumerate(unique_links[:50]):
                results.append(f"{i+1}. [{link['text']}]({link['href']})")
            
            if len(unique_links) > 50:
                results.append(f"\n...さらに {len(unique_links) - 50} 件のリンクがあります。")
            
            return "\n".join(results)
        
        else:
            return f"未対応のデータ種類: {data_type}"
    
    except Exception as e:
        error_message = f"構造化データ抽出エラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_view",
    description="現在のページ内容を表示する",
    parameters={
        "type": "object",
        "properties": {}
    }
)
def browser_view():
    """
    現在開いているページの内容を表示します。
    
    Returns:
        ページの内容とタイトルを含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_view_async())
    loop.close()
    return res

async def _view_async():
    """非同期でページ内容を取得"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # ページのタイトルとURLを取得
        title = await _current_page.title()
        current_url = _current_page.url
        
        # ページの内容をMarkdown形式で抽出
        extracted_text = await _extract_content_as_markdown(_current_page)
        
        # 結果を整形
        result = (
            f"## 現在のページ情報\n"
            f"タイトル: {title}\n"
            f"URL: {current_url}\n\n"
            f"## ページ内容\n"
            f"{extracted_text}\n\n"
        )
        
        return result
    except Exception as e:
        error_message = f"ページ表示エラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_click",
    description="ページ内の要素をクリックする",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "クリックする要素のCSSセレクタ"},
            "index": {"type": "integer", "description": "(オプション) 複数ある場合のインデックス（0から開始）"}
        },
        "required": ["selector"]
    }
)
def browser_click(selector: str, index: int = 0):
    """
    指定されたセレクタの要素をクリックします。
    
    Args:
        selector: クリックする要素のCSSセレクタ
        index: 複数要素がある場合のインデックス（0から開始）
        
    Returns:
        クリック結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_click_async(selector, index))
    loop.close()
    return res

async def _click_async(selector: str, index: int = 0):
    """非同期で要素をクリック"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # セレクタに一致する要素を取得
        elements = await _current_page.query_selector_all(selector)
        
        if not elements:
            return f"セレクタ '{selector}' に一致する要素が見つかりませんでした。"
        
        if index >= len(elements):
            return f"指定されたインデックス {index} が範囲外です（要素数: {len(elements)}）。"
        
        # 対象の要素をクリック
        element = elements[index]
        await element.scroll_into_view_if_needed()
        await element.click()
        
        # クリック後にページが変わる可能性があるので少し待機
        await asyncio.sleep(2)
        
        # 新しいページ情報を取得
        title = await _current_page.title()
        url = _current_page.url
        
        return f"要素をクリックしました。\n現在のページ: {title} ({url})"
    
    except Exception as e:
        error_message = f"クリックエラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_input",
    description="入力欄にテキストを入力する",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "入力欄のCSSセレクタ"},
            "text": {"type": "string", "description": "入力するテキスト"},
            "press_enter": {"type": "boolean", "description": "入力後にEnterキーを押すかどうか"}
        },
        "required": ["selector", "text"]
    }
)
def browser_input(selector: str, text: str, press_enter: bool = False):
    """
    指定されたセレクタの入力欄にテキストを入力します。
    
    Args:
        selector: 入力欄のCSSセレクタ
        text: 入力するテキスト
        press_enter: 入力後にEnterキーを押すかどうか
        
    Returns:
        入力結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_input_async(selector, text, press_enter))
    loop.close()
    return res

async def _input_async(selector: str, text: str, press_enter: bool = False):
    """非同期で入力欄にテキストを入力"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # 入力欄を取得
        input_element = await _current_page.query_selector(selector)
        
        if not input_element:
            return f"セレクタ '{selector}' に一致する入力欄が見つかりませんでした。"
        
        # 現在の入力内容をクリア
        await input_element.click()
        await input_element.fill("")
        
        # 新しいテキストを入力
        await input_element.type(text, delay=50)  # 人間らしく少し遅延を入れて入力
        
        # Enterキーを押す（オプション）
        if press_enter:
            await input_element.press("Enter")
            # ページが変わる可能性があるので少し待機
            await asyncio.sleep(2)
        
        return f"テキスト「{text}」を入力しました。" + (" Enterキーを押しました。" if press_enter else "")
    
    except Exception as e:
        error_message = f"入力エラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_scroll_down",
    description="ページを下にスクロールする",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "(オプション) スクロールする量（ピクセル）"},
            "to_bottom": {"type": "boolean", "description": "(オプション) ページ最下部までスクロールするかどうか"}
        }
    }
)
def browser_scroll_down(amount: int = 500, to_bottom: bool = False):
    """
    ページを下にスクロールします。
    
    Args:
        amount: スクロールする量（ピクセル）
        to_bottom: ページ最下部までスクロールするかどうか
        
    Returns:
        スクロール結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_scroll_down_async(amount, to_bottom))
    loop.close()
    return res

async def _scroll_down_async(amount: int = 500, to_bottom: bool = False):
    """非同期でページをスクロール"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        if to_bottom:
            # ページ最下部までスクロール
            await _current_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            result = "ページ最下部までスクロールしました。"
        else:
            # 指定された量だけスクロール
            await _current_page.evaluate(f"window.scrollBy(0, {amount})")
            result = f"{amount}ピクセル下にスクロールしました。"
        
        # スクロール後に少し待機して、動的コンテンツがロードされる時間を確保
        await asyncio.sleep(1)
        
        return result
    
    except Exception as e:
        error_message = f"スクロールエラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_scroll_up",
    description="ページを上にスクロールする",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "(オプション) スクロールする量（ピクセル）"},
            "to_top": {"type": "boolean", "description": "(オプション) ページ最上部までスクロールするかどうか"}
        }
    }
)
def browser_scroll_up(amount: int = 500, to_top: bool = False):
    """
    ページを上にスクロールします。
    
    Args:
        amount: スクロールする量（ピクセル）
        to_top: ページ最上部までスクロールするかどうか
        
    Returns:
        スクロール結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_scroll_up_async(amount, to_top))
    loop.close()
    return res

async def _scroll_up_async(amount: int = 500, to_top: bool = False):
    """非同期でページを上にスクロール"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        if to_top:
            # ページ最上部までスクロール
            await _current_page.evaluate("window.scrollTo(0, 0)")
            result = "ページ最上部までスクロールしました。"
        else:
            # 指定された量だけ上にスクロール
            await _current_page.evaluate(f"window.scrollBy(0, -{amount})")
            result = f"{amount}ピクセル上にスクロールしました。"
        
        return result
    
    except Exception as e:
        error_message = f"スクロールエラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_screenshot",
    description="現在のページのスクリーンショットを撮影する",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "(オプション) 特定の要素のスクリーンショットを撮影する場合のCSSセレクタ"},
            "save_path": {"type": "string", "description": "スクリーンショットを保存するパス（.pngで終わる必要があります）"}
        },
        "required": ["save_path"]
    }
)
def browser_screenshot(save_path: str, selector: Optional[str] = None):
    """
    現在のページまたは特定の要素のスクリーンショットを撮影します。
    
    Args:
        save_path: スクリーンショットを保存するパス（.pngで終わる必要があります）
        selector: 特定の要素のスクリーンショットを撮影する場合のCSSセレクタ
        
    Returns:
        スクリーンショット結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_screenshot_async(save_path, selector))
    loop.close()
    return res

async def _screenshot_async(save_path: str, selector: Optional[str] = None):
    """非同期でスクリーンショットを撮影"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # 保存パスを絶対パスに変換
        if not os.path.isabs(save_path):
            save_path = os.path.abspath(save_path)
        
        # 保存ディレクトリが存在しない場合は作成
        save_dir = os.path.dirname(save_path)
        os.makedirs(save_dir, exist_ok=True)
        
        if selector:
            # 特定の要素のスクリーンショットを撮影
            element = await _current_page.query_selector(selector)
            
            if not element:
                return f"セレクタ '{selector}' に一致する要素が見つかりませんでした。"
            
            await element.screenshot(path=save_path)
            return f"要素 '{selector}' のスクリーンショットを '{save_path}' に保存しました。"
        else:
            # ページ全体のスクリーンショットを撮影
            await _current_page.screenshot(path=save_path, full_page=True)
            return f"ページ全体のスクリーンショットを '{save_path}' に保存しました。"
    
    except Exception as e:
        error_message = f"スクリーンショットエラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_run_javascript",
    description="ページでJavaScriptコードを実行する",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "実行するJavaScriptコード"}
        },
        "required": ["code"]
    }
)
def browser_run_javascript(code: str):
    """
    現在のページでJavaScriptコードを実行します。
    
    Args:
        code: 実行するJavaScriptコード
        
    Returns:
        実行結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_run_javascript_async(code))
    loop.close()
    return res

async def _run_javascript_async(code: str):
    """非同期でJavaScriptを実行"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # JavaScriptコードを実行
        result = await _current_page.evaluate(code)
        
        # 結果の型を確認して適切に処理
        if result is None:
            return "コードが実行されました。（戻り値なし）"
        elif isinstance(result, (dict, list)):
            # オブジェクトや配列はJSON文字列に変換
            return f"実行結果:\n```json\n{json.dumps(result, indent=2, ensure_ascii=False)}\n```"
        else:
            # プリミティブ型はそのまま文字列化
            return f"実行結果: {result}"
    
    except Exception as e:
        error_message = f"JavaScript実行エラー: {str(e)}"
        logger.error(error_message)
        return error_message
