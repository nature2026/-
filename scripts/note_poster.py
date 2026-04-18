#!/usr/bin/env python3
"""
note.com 自動投稿: クッキー認証 + Playwright でブラウザを操作して記事を公開する。
"""

import os
import json
import re
import asyncio
import tempfile
import requests as req_lib
from pathlib import Path
from playwright.async_api import async_playwright

NOTE_TOP_URL = "https://note.com"
NOTE_NEW_URL = "https://note.com/notes/new"
DEBUG_DIR    = Path(__file__).parent.parent / "articles" / "debug"


def _save_ss(page, name: str):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return page.screenshot(path=str(DEBUG_DIR / f"{name}.png"))


async def _login_with_cookies(context, cookies_json: str):
    """クッキーをセットしてログイン済み状態にする"""
    cookies = json.loads(cookies_json)
    # Playwright形式に変換
    pw_cookies = []
    for c in cookies:
        pc = {
            "name":   c["name"],
            "value":  c["value"],
            "domain": c.get("domain", ".note.com"),
            "path":   c.get("path", "/"),
        }
        if c.get("expirationDate"):
            pc["expires"] = int(c["expirationDate"])
        if "sameSite" in c:
            ss = c["sameSite"]
            if ss in ("Strict", "Lax", "None"):
                pc["sameSite"] = ss
        pw_cookies.append(pc)
    await context.add_cookies(pw_cookies)
    print(f"[INFO] クッキー {len(pw_cookies)} 件をセット")


async def _upload_cover_image(page, image_url: str):
    try:
        resp = req_lib.get(image_url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] 画像DL失敗: {e}")
        return

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(resp.content)
        tmp_path = f.name

    cover_selectors = [
        'button:has-text("カバー画像")',
        '[data-testid="cover-image-button"]',
        '.o-noteEditHeader__coverImage button',
        'button[aria-label*="カバー"]',
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
            return
        except Exception:
            pass
    print("[WARN] カバー画像アップロードをスキップ")


async def _fill_title(page, title: str):
    for sel in [
        '[placeholder="記事タイトル"]',
        '[data-placeholder="記事タイトル"]',
        '[placeholder="タイトル"]',
        '[data-placeholder="タイトル"]',
        '.o-noteEditHeader__title',
        'textarea[name="title"]',
        'h1[contenteditable="true"]',
        'div[contenteditable="true"][data-placeholder]',
    ]:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=4000, state="visible")
            await el.click()
            await page.wait_for_timeout(300)
            await el.fill(title)
            print(f"[INFO] タイトル入力: {title[:30]}...")
            return
        except Exception:
            pass

    # フォールバック: keyboard入力
    try:
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(500)
        await page.keyboard.type(title)
        print(f"[INFO] タイトル入力(keyboard): {title[:30]}...")
        return
    except Exception:
        pass

    raise RuntimeError("タイトル入力欄が見つかりませんでした")


def _strip_markdown(text: str) -> str:
    """Markdownの記号を除去してnoteエディタ用プレーンテキストに変換"""
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)  # 見出し
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)      # 太字/斜体
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)                   # 画像
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)        # リンク
    text = re.sub(r'^[-*]\s+', '・', text, flags=re.MULTILINE)   # 箇条書き
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)    # 番号リスト
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)        # 区切り線
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)                # コード
    return text


async def _fill_body(page, free_part: str, paid_part: str):
    full_content = _strip_markdown(free_part) + "\n\n＝＝＝ ここから有料 ＝＝＝\n\n" + _strip_markdown(paid_part)

    # まず「+」ボタンをクリックしてエディタをアクティブにする
    try:
        plus_btn = page.locator('button[aria-label*="追加"], button.p-note-editor__add-button, button:has-text("+")').first
        await plus_btn.wait_for(timeout=3000, state="visible")
        await plus_btn.click()
        await page.wait_for_timeout(500)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
    except Exception:
        pass

    for sel in ['.ProseMirror', '[contenteditable="true"]', '.o-noteEditContents__body']:
        try:
            els = page.locator(sel)
            count = await els.count()
            # タイトル以外の2番目以降のcontenteditable（本文）を使う
            el = els.nth(1) if count > 1 else els.first
            await el.wait_for(timeout=5000, state="visible")
            await el.click()
            await page.wait_for_timeout(500)
            await page.evaluate(
                """(text) => {
                    const els = document.querySelectorAll('.ProseMirror, [contenteditable="true"]');
                    const el = els.length > 1 ? els[1] : els[0];
                    if (el) {
                        el.focus();
                        document.execCommand('selectAll', false, null);
                        document.execCommand('insertText', false, text);
                    }
                }""",
                full_content,
            )
            await _save_ss(page, "05_body_filled")
            print("[INFO] 本文入力完了")
            return
        except Exception:
            pass
    raise RuntimeError("本文エディタが見つかりませんでした")


async def _publish(page, price: int):
    await _save_ss(page, "06_before_publish")

    # 「公開に進む」ボタン（note新UIのメインボタン）
    for sel in [
        'button:has-text("公開に進む")',
        'button:has-text("公開設定")',
        'button:has-text("投稿設定")',
        '[data-testid="publish-button"]',
        'button.o-publishButton',
    ]:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(timeout=5000, state="visible")
            await btn.click()
            await page.wait_for_timeout(2000)
            print(f"[INFO] 公開ボタン: {sel}")
            break
        except Exception:
            pass

    await _save_ss(page, "07_publish_modal")

    # 有料設定
    for sel in ['label:has-text("有料")', 'input[type="radio"][value="paid"]',
                'button:has-text("有料")', '[data-testid="paid-toggle"]']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=3000, state="visible")
            await el.click()
            await page.wait_for_timeout(800)
            print("[INFO] 有料設定オン")
            break
        except Exception:
            pass

    # 価格入力
    for sel in ['input[name="price"]', 'input[placeholder*="価格"]',
                'input[placeholder*="金額"]', 'input[type="number"]']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=3000, state="visible")
            await el.triple_click()
            await el.fill(str(price))
            await page.wait_for_timeout(500)
            print(f"[INFO] 価格: {price}円")
            break
        except Exception:
            pass

    await _save_ss(page, "07b_price_set")
    await page.wait_for_timeout(3000)

    # ページ下部までスクロールして遅延レンダリングを待つ
    await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(2000)
    await _save_ss(page, "07c_scrolled")

    # 全可視テキストをダンプ（ボタン文言を特定するため）
    try:
        visible_text = await page.inner_text("body")
        print(f"[DEBUG] 全可視テキスト: {visible_text[:4000]}")
    except Exception as e:
        print(f"[DEBUG] テキスト取得失敗: {e}")

    # TreeWalkerでテキストノードを直接探索（要素フィルタなし）
    text_nodes = await page.evaluate("""
        () => {
            const results = [];
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null
            );
            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                if (text.length > 0 && (
                    text.includes('投稿') || text.includes('公開') || text.includes('送信')
                )) {
                    const p = node.parentElement;
                    results.push({
                        text: text.slice(0, 30),
                        tag: p ? p.tagName : '',
                        role: p ? (p.getAttribute('role') || '') : '',
                        type: p ? (p.getAttribute('type') || '') : '',
                        class: p ? (p.className || '').toString().slice(0, 80) : '',
                    });
                }
            }
            return results;
        }
    """)
    print(f"[DEBUG] テキストノード(投稿/公開): {text_nodes}")

    # 投稿ボタンクリック
    publish_clicked = False

    # 1) Playwright標準クリック（全タグ対応）
    for sel in [
        'button:has-text("投稿する")', 'button:has-text("公開する")',
        '[role="button"]:has-text("投稿する")', '[role="button"]:has-text("公開する")',
        'a:has-text("投稿する")', 'a:has-text("公開する")',
        ':text("投稿する")', ':text("公開する")',
        '[type="submit"]',
    ]:
        try:
            el = page.locator(sel).first
            await el.scroll_into_view_if_needed(timeout=2000)
            await el.click(timeout=2000, force=True)
            print(f"[INFO] 投稿クリック: {sel}")
            publish_clicked = True
            break
        except Exception:
            pass

    if not publish_clicked:
        # 2) JSでテキストノードの親要素をクリック
        r = await page.evaluate("""
            () => {
                const keywords = ['投稿する', '公開する'];
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null
                );
                let node;
                while (node = walker.nextNode()) {
                    const text = node.textContent.trim();
                    if (keywords.includes(text)) {
                        const p = node.parentElement;
                        if (p) {
                            p.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                            return text + ' [' + p.tagName + '.' + (p.className||'').slice(0,40) + ']';
                        }
                    }
                }
                return null;
            }
        """)
        print(f"[INFO] JS click result: {r}")

    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    await _save_ss(page, "08_after_publish")
    print(f"[INFO] 投稿完了: {page.url}")
    return page.url


async def post(article: dict, price: int) -> str:
    cookies_json = os.environ.get("NOTE_COOKIES")
    if not cookies_json:
        raise ValueError("NOTE_COOKIES が未設定です。")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
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
            # クッキーでログイン
            await _login_with_cookies(context, cookies_json)

            # ログイン確認
            await page.goto(NOTE_TOP_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await _save_ss(page, "01_after_cookie_login")
            print(f"[INFO] トップURL: {page.url}")

            # 新規記事ページへ
            await page.goto(NOTE_NEW_URL, wait_until="networkidle")
            await page.wait_for_timeout(2000)
            await _save_ss(page, "02_new_article")

            if "login" in page.url:
                raise RuntimeError("クッキーが無効です。NOTE_COOKIESを更新してください。")

            # カバー画像
            cover = article.get("cover_image")
            if cover and cover.get("url"):
                await _upload_cover_image(page, cover["url"])

            await _fill_title(page, article["title"])
            await page.wait_for_timeout(500)

            await _fill_body(page, article["free_part"], article["paid_part"])
            await page.wait_for_timeout(1000)

            url = await _publish(page, price)
            return url or page.url

        except Exception:
            await _save_ss(page, "99_error")
            raise
        finally:
            await browser.close()


def post_sync(article: dict, price: int) -> str:
    return asyncio.run(post(article, price))
