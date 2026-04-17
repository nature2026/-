#!/usr/bin/env python3
"""
note.com 自動投稿: Playwright でブラウザを操作して記事を公開する。
"""

import os
import asyncio
import tempfile
import requests as req_lib
from pathlib import Path
from playwright.async_api import async_playwright

NOTE_LOGIN_URL = "https://note.com/login"
NOTE_NEW_URL   = "https://note.com/notes/new"
DEBUG_DIR      = Path(__file__).parent.parent / "articles" / "debug"


def _save_screenshot(page_ref, name: str):
    """スクリーンショットをdebugフォルダに保存（非同期ラッパー用）"""
    return page_ref.screenshot(path=str(DEBUG_DIR / f"{name}.png"))


async def _login(page, email: str, password: str):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    await page.goto(NOTE_LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    await _save_screenshot(page, "01_login_page")
    print(f"[INFO] ログインページ: {page.url}")

    # メールアドレス入力
    email_filled = False
    for sel in ['input[name="email"]', 'input[type="email"]',
                'input[placeholder*="メール"]', 'input[placeholder*="mail"]', '#email']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=5000, state="visible")
            await el.fill(email)
            email_filled = True
            print(f"[INFO] メール入力: {sel}")
            break
        except Exception:
            pass

    if not email_filled:
        await _save_screenshot(page, "01_email_not_found")
        raise RuntimeError("メール入力欄が見つかりません")

    await page.wait_for_timeout(600)

    # 「次へ」ボタン（2ステップログイン）
    for sel in ['button:has-text("次へ")', 'button:has-text("続ける")',
                'button:has-text("Next")', 'a:has-text("次へ")']:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=2500, state="visible")
            await btn.click()
            print(f"[INFO] 次へボタン: {sel}")
            await page.wait_for_timeout(2000)
            break
        except Exception:
            pass

    await _save_screenshot(page, "02_after_next")

    # パスワード入力
    pw_filled = False
    for sel in ['input[name="password"]', 'input[type="password"]', '#password']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=6000, state="visible")
            await el.fill(password)
            pw_filled = True
            print(f"[INFO] パスワード入力: {sel}")
            break
        except Exception:
            pass

    if not pw_filled:
        await _save_screenshot(page, "02_password_not_found")
        raise RuntimeError("パスワード入力欄が見つかりません")

    await page.wait_for_timeout(600)

    # ログインボタン
    for sel in ['button[type="submit"]', 'button:has-text("ログイン")',
                'button:has-text("サインイン")', 'input[type="submit"]']:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=5000, state="visible")
            await btn.click()
            print(f"[INFO] ログインボタン: {sel}")
            break
        except Exception:
            pass

    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    await _save_screenshot(page, "03_after_login")
    print(f"[INFO] ログイン後URL: {page.url}")

    if "login" in page.url:
        raise RuntimeError(f"ログイン失敗。URL: {page.url} / Secrets の NOTE_EMAIL・NOTE_PASSWORD を確認してください。")

    print("[INFO] ログイン成功！")


async def _upload_cover_image(page, image_url: str):
    """Unsplash画像をダウンロードしてカバー画像にアップロードする"""
    # 画像をローカルに保存
    try:
        resp = req_lib.get(image_url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] 画像ダウンロード失敗: {e}")
        return

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(resp.content)
        tmp_path = f.name

    # カバー画像ボタンを探してクリック → FileChooser で upload
    cover_selectors = [
        'button:has-text("カバー画像")',
        '[data-testid="cover-image-button"]',
        '.o-noteEditHeader__coverImage button',
        'label:has-text("カバー画像")',
        'button[aria-label*="カバー"]',
        '.p-articleEditor__coverImageButton',
    ]
    for sel in cover_selectors:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=3000, state="visible")
            async with page.expect_file_chooser(timeout=5000) as fc_info:
                await btn.click()
            fc = await fc_info.value
            await fc.set_files(tmp_path)
            await page.wait_for_timeout(2500)
            print("[INFO] カバー画像アップロード完了")
            await _save_screenshot(page, "05_cover_uploaded")
            return
        except Exception:
            pass

    # ファイル input を直接探す
    try:
        file_input = page.locator('input[type="file"][accept*="image"]').first
        await file_input.wait_for(timeout=3000)
        await file_input.set_input_files(tmp_path)
        await page.wait_for_timeout(2500)
        print("[INFO] カバー画像 (input直接) アップロード完了")
    except Exception:
        print("[WARN] カバー画像のアップロードをスキップ")


async def _fill_title(page, title: str):
    for sel in ['[placeholder="タイトル"]', '[data-placeholder="タイトル"]',
                '.o-noteEditHeader__title', 'textarea[name="title"]',
                'h1[contenteditable="true"]']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=5000, state="visible")
            await el.click()
            await el.fill(title)
            print(f"[INFO] タイトル入力完了: {title[:30]}...")
            return
        except Exception:
            pass
    raise RuntimeError("タイトル入力欄が見つかりませんでした")


async def _fill_body(page, free_part: str, paid_part: str):
    for sel in ['.ProseMirror', '[contenteditable="true"]', '.o-noteEditContents__body']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=5000, state="visible")
            await el.click()
            await page.wait_for_timeout(500)
            full_content = free_part + "\n\n＝＝＝ ここから有料 ＝＝＝\n\n" + paid_part
            await page.evaluate(
                """(text) => {
                    const el = document.querySelector('.ProseMirror') ||
                               document.querySelector('[contenteditable="true"]');
                    if (el) {
                        el.focus();
                        document.execCommand('selectAll', false, null);
                        document.execCommand('insertText', false, text);
                    }
                }""",
                full_content,
            )
            print("[INFO] 本文入力完了")
            return
        except Exception:
            pass
    raise RuntimeError("本文エディタが見つかりませんでした")


async def _publish(page, price: int):
    await _save_screenshot(page, "06_before_publish")

    # 公開設定ボタン
    for sel in ['button:has-text("公開設定")', 'button:has-text("投稿設定")',
                '[data-testid="publish-button"]', 'button.o-publishButton']:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=5000, state="visible")
            await btn.click()
            await page.wait_for_timeout(1500)
            print(f"[INFO] 公開設定ボタン: {sel}")
            break
        except Exception:
            pass

    await _save_screenshot(page, "07_publish_modal")

    # 有料設定
    for sel in ['label:has-text("有料")', 'input[type="radio"][value="paid"]',
                '[data-testid="paid-toggle"]']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=3000, state="visible")
            await el.click()
            await page.wait_for_timeout(500)
            print("[INFO] 有料設定オン")
            break
        except Exception:
            pass

    # 価格入力
    for sel in ['input[name="price"]', 'input[placeholder*="価格"]',
                'input[placeholder*="金額"]', '[data-testid="price-input"]']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=3000, state="visible")
            await el.triple_click()
            await el.type(str(price))
            print(f"[INFO] 価格: {price}円")
            break
        except Exception:
            pass

    await page.wait_for_timeout(500)

    # 投稿ボタン
    for sel in ['button:has-text("投稿する")', 'button:has-text("公開する")',
                'button:has-text("投稿")', '[data-testid="submit-button"]']:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=5000, state="visible")
            await btn.click()
            print(f"[INFO] 投稿ボタンクリック: {sel}")
            break
        except Exception:
            pass

    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    await _save_screenshot(page, "08_after_publish")
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
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        try:
            await _login(page, email, password)

            await page.goto(NOTE_NEW_URL, wait_until="networkidle")
            await page.wait_for_timeout(2000)
            await _save_screenshot(page, "04_new_article")

            # カバー画像アップロード
            cover = article.get("cover_image")
            if cover and cover.get("url"):
                await _upload_cover_image(page, cover["url"])

            await _fill_title(page, article["title"])
            await page.wait_for_timeout(500)

            await _fill_body(page, article["free_part"], article["paid_part"])
            await page.wait_for_timeout(1000)

            url = await _publish(page, price)
            return url or page.url

        except Exception as e:
            await _save_screenshot(page, "99_error")
            raise
        finally:
            await browser.close()


def post_sync(article: dict, price: int) -> str:
    return asyncio.run(post(article, price))
