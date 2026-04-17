#!/usr/bin/env python3
"""
note.com 自動投稿: Playwright でブラウザを操作して記事を公開する。
"""

import os
import asyncio
from playwright.async_api import async_playwright

NOTE_LOGIN_URL = "https://note.com/login"
NOTE_NEW_URL   = "https://note.com/notes/new"


async def _login(page, email: str, password: str):
    await page.goto(NOTE_LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    print(f"[INFO] ログインページURL: {page.url}")

    # ── メールアドレス入力 ──
    email_selectors = [
        'input[name="email"]',
        'input[type="email"]',
        'input[placeholder*="メール"]',
        'input[placeholder*="mail"]',
        '#email',
    ]
    for sel in email_selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=5000)
            await el.fill(email)
            print(f"[INFO] メール入力成功: {sel}")
            break
        except Exception:
            pass

    await page.wait_for_timeout(500)

    # ── 「次へ」ボタンがあれば押す（2ステップログイン対応）──
    next_selectors = [
        'button:has-text("次へ")',
        'button:has-text("続ける")',
        'button:has-text("Next")',
        'input[type="submit"]',
    ]
    for sel in next_selectors:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=3000)
            await btn.click()
            print(f"[INFO] 次へボタンクリック: {sel}")
            await page.wait_for_timeout(2000)
            break
        except Exception:
            pass

    # ── パスワード入力 ──
    pw_selectors = [
        'input[name="password"]',
        'input[type="password"]',
        '#password',
    ]
    for sel in pw_selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=5000)
            await el.fill(password)
            print(f"[INFO] パスワード入力成功: {sel}")
            break
        except Exception:
            pass

    await page.wait_for_timeout(500)

    # ── ログインボタン ──
    for sel in ['button[type="submit"]', 'button:has-text("ログイン")', 'button:has-text("サインイン")']:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=5000)
            await btn.click()
            print(f"[INFO] ログインボタンクリック: {sel}")
            break
        except Exception:
            pass

    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    print(f"[INFO] ログイン後URL: {page.url}")

    if "login" in page.url:
        html = await page.content()
        print(f"[DEBUG] ログイン失敗時のHTML（先頭800文字）:\n{html[:800]}")
        raise RuntimeError("ログイン失敗。NOTE_EMAIL・NOTE_PASSWORDを確認してください。")

    print("[INFO] ログイン成功！")


async def _fill_title(page, title: str):
    for sel in ['[placeholder="タイトル"]', '[data-placeholder="タイトル"]', '.o-noteEditHeader__title', 'textarea[name="title"]']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=5000)
            await el.click()
            await el.fill(title)
            print("[INFO] タイトル入力完了")
            return
        except Exception:
            pass
    raise RuntimeError("タイトル入力欄が見つかりませんでした")


async def _fill_body(page, free_part: str, paid_part: str):
    for sel in ['.ProseMirror', '[contenteditable="true"]', '.o-noteEditContents__body']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=5000)
            await el.click()
            await page.wait_for_timeout(500)
            full_content = free_part + "\n\n---ここから有料---\n\n" + paid_part
            await page.evaluate(
                """(text) => {
                    const el = document.querySelector('.ProseMirror') ||
                               document.querySelector('[contenteditable="true"]');
                    if (el) { el.focus(); document.execCommand('selectAll', false, null); document.execCommand('insertText', false, text); }
                }""",
                full_content,
            )
            print("[INFO] 本文入力完了")
            return
        except Exception:
            pass
    raise RuntimeError("本文エディタが見つかりませんでした")


async def _publish(page, price: int):
    for sel in ['button:has-text("公開設定")', 'button:has-text("投稿設定")', 'button.o-publishButton']:
        try:
            await page.locator(sel).first.click()
            await page.wait_for_timeout(1500)
            break
        except Exception:
            pass

    for sel in ['label:has-text("有料")', 'input[type="radio"][value="paid"]']:
        try:
            await page.locator(sel).first.click()
            await page.wait_for_timeout(500)
            print("[INFO] 有料設定オン")
            break
        except Exception:
            pass

    for sel in ['input[name="price"]', 'input[placeholder*="価格"]']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=3000)
            await el.triple_click()
            await el.type(str(price))
            print(f"[INFO] 価格: {price}円")
            break
        except Exception:
            pass

    for sel in ['button:has-text("投稿する")', 'button:has-text("公開する")', 'button:has-text("投稿")']:
        try:
            await page.locator(sel).first.click()
            break
        except Exception:
            pass

    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    print(f"[INFO] 投稿完了: {page.url}")
    return page.url


async def post(article: dict, price: int) -> str:
    email    = os.environ.get("NOTE_EMAIL")
    password = os.environ.get("NOTE_PASSWORD")
    if not email or not password:
        raise ValueError("NOTE_EMAIL / NOTE_PASSWORD が未設定です。")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
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
            url = await _publish(page, price)
            return url or page.url
        finally:
            await browser.close()


def post_sync(article: dict, price: int) -> str:
    return asyncio.run(post(article, price))
