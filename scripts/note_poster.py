#!/usr/bin/env python3
"""
note.com 自動投稿: Playwright でブラウザを操作して記事を公開する。
"""

import os
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

NOTE_LOGIN_URL  = "https://note.com/login"
NOTE_NEW_URL    = "https://note.com/notes/new"


async def _login(page, email: str, password: str):
    await page.goto(NOTE_LOGIN_URL, wait_until="networkidle")
    await page.wait_for_timeout(1500)

    # メールアドレス入力
    await page.fill('input[name="email"]', email)
    await page.wait_for_timeout(500)

    # パスワード入力
    await page.fill('input[name="password"]', password)
    await page.wait_for_timeout(500)

    # ログインボタン
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(2000)

    if "login" in page.url:
        raise RuntimeError("ログイン失敗。メールアドレスとパスワードを確認してください。")

    print("[INFO] ログイン成功")


async def _fill_title(page, title: str):
    # タイトル入力欄を探す
    title_sel = [
        '[placeholder="タイトル"]',
        '[data-placeholder="タイトル"]',
        '.o-noteEditHeader__title',
        'textarea[name="title"]',
    ]
    for sel in title_sel:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=5000)
            await el.click()
            await el.fill(title)
            print(f"[INFO] タイトル入力完了: {title[:40]}...")
            return
        except Exception:
            pass
    raise RuntimeError("タイトル入力欄が見つかりませんでした")


async def _fill_body(page, free_part: str, paid_part: str):
    # 本文エディタを探す
    editor_sel = [
        '.ProseMirror',
        '[contenteditable="true"]',
        '.o-noteEditContents__body',
    ]
    editor = None
    for sel in editor_sel:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=5000)
            editor = el
            break
        except Exception:
            pass

    if not editor:
        raise RuntimeError("本文エディタが見つかりませんでした")

    await editor.click()
    await page.wait_for_timeout(500)

    # 無料部分を入力
    await page.evaluate(
        """(text) => {
            const el = document.querySelector('.ProseMirror') ||
                       document.querySelector('[contenteditable="true"]');
            if (!el) throw new Error('editor not found');
            el.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('insertText', false, text);
        }""",
        free_part,
    )
    await page.wait_for_timeout(800)

    # 有料ラインを挿入
    await _insert_paid_line(page)
    await page.wait_for_timeout(800)

    # 有料部分を入力
    await page.keyboard.press("End")
    await page.keyboard.press("Enter")
    await page.evaluate(
        """(text) => {
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                const textNode = document.createTextNode(text);
                range.insertNode(textNode);
                range.setStartAfter(textNode);
                range.collapse(true);
                selection.removeAllRanges();
                selection.addRange(range);
            }
        }""",
        paid_part,
    )
    print("[INFO] 本文入力完了")


async def _insert_paid_line(page):
    """有料コンテンツラインを挿入する"""
    # ツールバーの「有料ライン」ボタンを探す
    paid_line_selectors = [
        'button[aria-label*="有料"]',
        'button[title*="有料"]',
        '[data-testid="paid-line-button"]',
    ]
    for sel in paid_line_selectors:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=3000)
            await btn.click()
            print("[INFO] 有料ラインを挿入しました")
            return
        except Exception:
            pass
    # ボタンが見つからない場合はテキストで代替
    print("[WARN] 有料ラインボタンが見つからず。テキストで代替します。")
    await page.keyboard.press("Enter")
    await page.keyboard.type("--- ここから有料 ---")
    await page.keyboard.press("Enter")


async def _set_price_and_publish(page, price: int):
    # 「公開設定」ボタン
    pub_btn_selectors = [
        'button:has-text("公開設定")',
        'button:has-text("投稿設定")',
        '[data-testid="publish-button"]',
        'button.o-publishButton',
    ]
    for sel in pub_btn_selectors:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=5000)
            await btn.click()
            break
        except Exception:
            pass

    await page.wait_for_timeout(1500)

    # 有料設定
    paid_toggle_selectors = [
        'label:has-text("有料")',
        'input[type="radio"][value="paid"]',
        '[data-testid="paid-toggle"]',
    ]
    for sel in paid_toggle_selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=3000)
            await el.click()
            await page.wait_for_timeout(500)
            print("[INFO] 有料設定をオン")
            break
        except Exception:
            pass

    # 価格入力
    price_input_selectors = [
        'input[name="price"]',
        'input[placeholder*="価格"]',
        'input[placeholder*="金額"]',
        '[data-testid="price-input"]',
    ]
    for sel in price_input_selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=3000)
            await el.triple_click()
            await el.type(str(price))
            print(f"[INFO] 価格設定: {price}円")
            break
        except Exception:
            pass

    await page.wait_for_timeout(500)

    # 「投稿する」ボタン
    submit_selectors = [
        'button:has-text("投稿する")',
        'button:has-text("公開する")',
        'button:has-text("投稿")',
        '[data-testid="submit-button"]',
    ]
    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=5000)
            await btn.click()
            print("[INFO] 投稿ボタンをクリック")
            break
        except Exception:
            pass

    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    print(f"[INFO] 投稿完了: {page.url}")
    return page.url


async def post(article: dict, price: int) -> str:
    """
    note.com に記事を投稿して URL を返す。
    環境変数: NOTE_EMAIL, NOTE_PASSWORD
    """
    email    = os.environ.get("NOTE_EMAIL")
    password = os.environ.get("NOTE_PASSWORD")
    if not email or not password:
        raise ValueError("NOTE_EMAIL / NOTE_PASSWORD が未設定です。")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            await _login(page, email, password)

            await page.goto(NOTE_NEW_URL, wait_until="networkidle")
            await page.wait_for_timeout(2000)

            await _fill_title(page, article["title"])
            await page.wait_for_timeout(500)

            await _fill_body(page, article["free_part"], article["paid_part"])
            await page.wait_for_timeout(1000)

            url = await _set_price_and_publish(page, price)
            return url or page.url

        finally:
            await browser.close()


def post_sync(article: dict, price: int) -> str:
    return asyncio.run(post(article, price))
