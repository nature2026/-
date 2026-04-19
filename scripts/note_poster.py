#!/usr/bin/env python3
"""
note.com 自動投稿: クッキー認証 + Playwright でブラウザを操作して記事を公開する。
"""

import json
import os
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
    cookies = json.loads(cookies_json)
    pw_cookies = []
    for c in cookies:
        pc = {"name": c["name"], "value": c["value"],
              "domain": c.get("domain", ".note.com"), "path": c.get("path", "/")}
        if c.get("expirationDate"):
            pc["expires"] = int(c["expirationDate"])
        ss = c.get("sameSite", "")
        if ss in ("Strict", "Lax", "None"):
            pc["sameSite"] = ss
        pw_cookies.append(pc)
    await context.add_cookies(pw_cookies)
    print(f"[INFO] クッキー {len(pw_cookies)} 件をセット")


async def _upload_cover(context, page, note_key: str, image_url: str) -> bool:
    """カバー画像アップロード: API → UI ファイル入力の順で試行"""
    try:
        img_bytes = req_lib.get(image_url, timeout=15).content
    except Exception as e:
        print(f"[WARN] カバー画像DL失敗: {e}")
        return False

    # CSRF トークン取得
    csrf = await page.evaluate(
        "() => document.querySelector('meta[name=\"csrf-token\"]')?.getAttribute('content')"
    )
    headers = {
        "Referer": f"https://editor.note.com/notes/{note_key}/edit",
        "Origin":  "https://editor.note.com",
    }
    if csrf:
        headers["X-CSRF-Token"] = csrf

    # API: /api/v1/files にアップロード後、eyecatch キーで紐付け
    for field in ["file", "image"]:
        try:
            r = await context.request.fetch(
                "https://note.com/api/v1/files", method="POST", headers=headers,
                multipart={field: {"name": "cover.jpg", "mimeType": "image/jpeg", "buffer": img_bytes}},
            )
            body = await r.text()
            print(f"[INFO] files API ({field}) {r.status}: {body[:200]}")
            if r.ok:
                data = json.loads(body)
                key = data.get("data", {}).get("key") or data.get("key")
                if key:
                    pr = await context.request.fetch(
                        f"https://note.com/api/v1/text_notes/{note_key}", method="PUT",
                        headers={**headers, "Content-Type": "application/json"},
                        data=json.dumps({"eyecatch_image_key": key}),
                    )
                    print(f"[INFO] eyecatch set {pr.status}: {(await pr.text())[:150]}")
                    if pr.ok:
                        return True
                return True  # ファイルのみアップロード成功
        except Exception as e:
            print(f"[WARN] files API ({field}): {e}")

    # UI: カバー画像ボタンを探してファイル選択
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(img_bytes)
            tmp_path = f.name

        # ページ上のカバー関連ボタンをログ出力（デバッグ用）
        btns = await page.evaluate("""
            () => [...document.querySelectorAll('button,[role="button"],label')].map(e => ({
                text: e.textContent.trim().slice(0, 30),
                aria: e.getAttribute('aria-label') || '',
                testid: e.getAttribute('data-testid') || '',
            }))
        """)
        cover_btns = [b for b in btns if any(
            k in (b["text"] + b["aria"] + b["testid"]).lower()
            for k in ["cover", "eyecatch", "カバー", "サムネ", "画像"]
        )]
        print(f"[DEBUG] カバー関連ボタン: {cover_btns}")

        for sel in [
            'button:has-text("カバー画像を設定")',
            'button:has-text("カバー画像")',
            'button:has-text("カバー")',
            '[aria-label*="カバー"]',
            '[data-testid*="eyecatch"]',
            '[data-testid*="cover"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() == 0:
                    continue
                async with page.expect_file_chooser(timeout=4000) as fc_info:
                    await el.click(timeout=3000)
                fc = await fc_info.value
                await fc.set_files(tmp_path)
                await page.wait_for_timeout(3000)
                print(f"[INFO] cover UI: {sel}")
                return True
            except Exception:
                pass
    except Exception as e:
        print(f"[WARN] cover UI失敗: {e}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return False


async def _fill_title(page, title: str):
    for sel in [
        '[placeholder="記事タイトル"]', '[data-placeholder="記事タイトル"]',
        '[placeholder="タイトル"]',    '[data-placeholder="タイトル"]',
        '.o-noteEditHeader__title',    'textarea[name="title"]',
        'h1[contenteditable="true"]',  'div[contenteditable="true"][data-placeholder]',
    ]:
        try:
            el = page.locator(sel).first
            await el.wait_for(timeout=4000, state="visible")
            await el.click()
            await page.wait_for_timeout(200)
            await el.fill(title)
            print(f"[INFO] タイトル入力: {title[:40]}...")
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
    text = re.sub(r'`{1,3}[^`\n]*`{1,3}', '', text)
    return text


async def _fill_body(page, free_part: str, paid_part: str):
    content = (
        _strip_markdown(free_part)
        + "\n\n＝＝＝ ここから有料 ＝＝＝\n\n"
        + _strip_markdown(paid_part)
    )
    for sel in ['.ProseMirror', '[contenteditable="true"]', '.o-noteEditContents__body']:
        try:
            els = page.locator(sel)
            count = await els.count()
            el = els.nth(1) if count > 1 else els.first
            await el.wait_for(timeout=5000, state="visible")
            await el.click()
            await page.wait_for_timeout(300)
            await page.evaluate(
                """(text) => {
                    const els = document.querySelectorAll('.ProseMirror, [contenteditable="true"]');
                    const el = els.length > 1 ? els[1] : els[0];
                    if (el) { el.focus(); document.execCommand('selectAll'); document.execCommand('insertText', false, text); }
                }""",
                content,
            )
            await _save_ss(page, "05_body_filled")
            print("[INFO] 本文入力完了")
            return
        except Exception:
            pass
    raise RuntimeError("本文エディタが見つかりませんでした")


async def _publish(page, price: int):
    await _save_ss(page, "06_before_publish")

    # 「公開に進む」ボタン
    for sel in ['button:has-text("公開に進む")', 'button:has-text("公開設定")',
                '[data-testid="publish-button"]', 'button.o-publishButton']:
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

    # 「記事タイプ」タブ
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

    # 有料ラジオを JS で選択
    paid_result = await page.evaluate("""
        () => {
            const radio = document.getElementById('paid') ||
                          document.querySelector('input[name="is_paid"][value="paid"]');
            if (!radio) return 'not found';
            radio.checked = true;
            ['click','change','input'].forEach(e =>
                radio.dispatchEvent(new Event(e, {bubbles: true}))
            );
            return 'ok';
        }
    """)
    print(f"[INFO] 有料ラジオ: {paid_result}")

    # 価格 input が出現するまで待つ（最大 8 秒）
    try:
        await page.wait_for_selector(
            'input#price, input[placeholder="300"]', timeout=8000
        )
    except Exception:
        print("[WARN] 価格input 待機タイムアウト")

    # 価格を React native setter + execCommand で設定
    price_result = await page.evaluate(f"""
        () => {{
            const input = document.getElementById('price') ||
                          document.querySelector('input[placeholder="300"]');
            if (!input) return 'not found';
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(input, '{price}');
            input.focus();
            document.execCommand('selectAll');
            document.execCommand('insertText', false, '{price}');
            ['input','change','blur'].forEach(e =>
                input.dispatchEvent(new Event(e, {{bubbles: true}}))
            );
            return 'value=' + input.value;
        }}
    """)
    print(f"[INFO] 価格設定: {price_result}")
    await page.wait_for_timeout(1000)

    # overflow コンテナを最下部にスクロールして「投稿する」を表示
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
    print(f"[INFO] スクロール: {scrolled}コンテナ")
    await page.wait_for_timeout(1500)
    await _save_ss(page, "07b_scrolled")

    # 投稿ボタンクリック
    for sel in [
        'button:has-text("投稿する")', 'button:has-text("公開する")',
        '[role="button"]:has-text("投稿する")', ':text("投稿する")', ':text("公開する")',
    ]:
        try:
            el = page.locator(sel).first
            await el.scroll_into_view_if_needed(timeout=2000)
            await el.click(timeout=2000, force=True)
            print(f"[INFO] 投稿クリック: {sel}")
            break
        except Exception:
            pass
    else:
        # フォールバック: TreeWalker で TEXT ノードを検索してクリック
        r = await page.evaluate("""
            () => {
                const kws = ['投稿する', '公開する'];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    if (kws.includes(node.textContent.trim())) {
                        const p = node.parentElement;
                        if (p) { p.dispatchEvent(new MouseEvent('click', {bubbles: true})); return p.tagName; }
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

            # カバー画像アップロード
            cover = article.get("cover_image")
            if cover and cover.get("url") and note_key and note_key != "new":
                ok = await _upload_cover(context, page, note_key, cover["url"])
                print("[INFO] カバー画像: " + ("完了" if ok else "失敗"))

            url = await _publish(page, price)
            return url or page.url

        except Exception:
            await _save_ss(page, "99_error")
            raise
        finally:
            await browser.close()


def post_sync(article: dict, price: int) -> str:
    return asyncio.run(post(article, price))
