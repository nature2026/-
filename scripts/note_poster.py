#!/usr/bin/env python3
"""
note.com 自動投稿: クッキー認証 + Playwright でブラウザを操作して記事を公開する。
カバー画像は自動保存後にAPIで直接アップロードする。
"""

import os
import json
import re
import asyncio
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
    cookies = json.loads(cookies_json)
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


async def _upload_cover_via_context(context, note_key: str, image_url: str) -> bool:
    """Playwright contextのfetch APIでカバー画像をアップロード（ブラウザセッション使用）"""
    try:
        img_resp = req_lib.get(image_url, timeout=15)
        img_resp.raise_for_status()
        img_bytes = img_resp.content
    except Exception as e:
        print(f"[WARN] カバー画像DL失敗: {e}")
        return False

    for url in [
        f"https://note.com/api/v1/text_notes/{note_key}/eyecatch",
        f"https://note.com/api/v2/text_notes/{note_key}/eyecatch",
    ]:
        for field in ["image", "file"]:
            try:
                response = await context.request.fetch(
                    url,
                    method="POST",
                    headers={
                        "Referer": f"https://editor.note.com/notes/{note_key}/edit",
                        "Origin": "https://editor.note.com",
                    },
                    multipart={
                        field: {
                            "name": "cover.jpg",
                            "mimeType": "image/jpeg",
                            "buffer": img_bytes,
                        }
                    },
                )
                body = await response.text()
                print(f"[INFO] カバー画像API ({field}) {response.status}: {body[:200]}")
                if response.ok:
                    return True
            except Exception as e:
                print(f"[WARN] カバー画像fetch失敗 ({url} {field}): {e}")

    return False


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
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'^[-*]\s+', '・', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    return text


async def _fill_body(page, free_part: str, paid_part: str):
    full_content = _strip_markdown(free_part) + "\n\n＝＝＝ ここから有料 ＝＝＝\n\n" + _strip_markdown(paid_part)

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
            print("[INFO] 本文入力完了")
            return
        except Exception:
            pass
    raise RuntimeError("本文エディタが見つかりませんでした")


async def _publish(page, price: int):
    await _save_ss(page, "06_before_publish")

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
    await page.wait_for_timeout(2000)

    # 記事タイプタブをクリック
    for sel in ['button:has-text("記事タイプ")', ':text-is("記事タイプ")']:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=4000, state="visible")
            await el.click()
            await page.wait_for_timeout(1500)
            print(f"[INFO] 記事タイプタブ: {sel}")
            break
        except Exception:
            pass

    # 有料ラジオをReact対応JSで選択
    paid_result = await page.evaluate("""
        () => {
            const radio = document.getElementById('paid') ||
                          document.querySelector('input[name="is_paid"][value="paid"]');
            if (!radio) return 'not found';
            radio.checked = true;
            ['click', 'change', 'input'].forEach(evt =>
                radio.dispatchEvent(new Event(evt, {bubbles: true, cancelable: true}))
            );
            return 'checked: ' + radio.checked;
        }
    """)
    print(f"[INFO] 有料ラジオ: {paid_result}")
    await page.wait_for_timeout(1500)

    # 価格をReact native setter経由で設定
    price_result = await page.evaluate(f"""
        () => {{
            const input = document.getElementById('price') ||
                          document.querySelector('input[placeholder="300"]');
            if (!input) return 'not found';
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, '{price}');
            ['focus', 'input', 'change', 'blur'].forEach(evt =>
                input.dispatchEvent(new Event(evt, {{bubbles: true, cancelable: true}}))
            );
            return 'value: ' + input.value;
        }}
    """)
    print(f"[INFO] 価格JS: {price_result}")
    await page.wait_for_timeout(1500)

    # Playwrightからも価格入力（force）
    try:
        price_el = page.locator('input#price, input[placeholder="300"]').first
        await price_el.click(force=True)
        await price_el.select_text()
        await page.keyboard.type(str(price))
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(1000)
        print(f"[INFO] 価格keyboard: {price}円")
    except Exception as e:
        print(f"[WARN] keyboard入力: {e}")

    await page.wait_for_timeout(1000)

    # ドロワー内全スクロール可能コンテナを最下部へ（投稿ボタンを表示）
    scrolled = await page.evaluate("""
        () => {
            const els = [...document.querySelectorAll('*')].filter(el => {
                const s = window.getComputedStyle(el);
                return (s.overflowY === 'scroll' || s.overflowY === 'auto') &&
                       el.scrollHeight > el.clientHeight + 10;
            });
            els.forEach(el => { el.scrollTop = el.scrollHeight; });
            window.scrollTo(0, document.body.scrollHeight);
            return els.length;
        }
    """)
    print(f"[INFO] スクロール済みコンテナ: {scrolled}")
    await page.wait_for_timeout(1500)
    await _save_ss(page, "07b_scrolled")

    # 投稿ボタンクリック
    publish_clicked = False
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
        r = await page.evaluate("""
            () => {
                const keywords = ['投稿する', '公開する'];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
                let node;
                while (node = walker.nextNode()) {
                    const text = node.textContent.trim();
                    if (keywords.includes(text)) {
                        const p = node.parentElement;
                        if (p) {
                            p.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                            return text + ' [' + p.tagName + ']';
                        }
                    }
                }
                return null;
            }
        """)
        print(f"[INFO] JS click: {r}")

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
            await _login_with_cookies(context, cookies_json)

            await page.goto(NOTE_TOP_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            print(f"[INFO] トップURL: {page.url}")

            await page.goto(NOTE_NEW_URL, wait_until="networkidle")
            await page.wait_for_timeout(2000)
            await _save_ss(page, "02_new_article")

            if "login" in page.url:
                raise RuntimeError("クッキーが無効です。NOTE_COOKIESを更新してください。")

            await _fill_title(page, article["title"])
            await page.wait_for_timeout(500)

            await _fill_body(page, article["free_part"], article["paid_part"])

            # 自動保存を待ってノートIDを取得
            await page.wait_for_timeout(5000)
            note_key_match = re.search(r'/notes/([^/]+)', page.url)
            note_key = note_key_match.group(1) if note_key_match else None
            print(f"[INFO] ノートID: {note_key} (URL: {page.url})")

            # カバー画像をPlaywright contextのfetch APIでアップロード
            cover = article.get("cover_image")
            if cover and cover.get("url") and note_key and note_key != "new":
                ok = await _upload_cover_via_context(context, note_key, cover["url"])
                if ok:
                    print("[INFO] カバー画像アップロード完了")
                else:
                    print("[WARN] カバー画像アップロード失敗")
            else:
                print("[WARN] カバー画像スキップ（URL未取得またはURLなし）")

            url = await _publish(page, price)
            return url or page.url

        except Exception:
            await _save_ss(page, "99_error")
            raise
        finally:
            await browser.close()


def post_sync(article: dict, price: int) -> str:
    return asyncio.run(post(article, price))
