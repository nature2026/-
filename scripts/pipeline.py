#!/usr/bin/env python3
"""
パイプライン: テーマ収集 → 記事生成 → note投稿 を一気通貫で実行する。
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import theme_collector
import article_generator
import image_fetcher
import note_poster

JST = timezone(timedelta(hours=9))


def load_config() -> dict:
    with open(ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


def pick_genre(genres: list[dict]) -> dict:
    day_index = datetime.now(tz=JST).toordinal() % len(genres)
    genre = genres[day_index]
    print(f"[INFO] 本日のジャンル: {genre['name']}")
    return genre


def save_article(article: dict, genre_id: str, today: str) -> Path:
    out_dir = ROOT / "articles"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{today}_{genre_id}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {article['title']}\n\n")
        if article.get("cover_image"):
            img = article["cover_image"]
            f.write(f"![カバー画像]({img['url']})\n")
            f.write(f"*{img['credit']}*\n\n")
        f.write(article["full_markdown"])
    return path


def run():
    today = datetime.now(tz=JST).strftime("%Y-%m-%d")
    print(f"\n{'='*50}")
    print(f"  AI note 自動投稿パイプライン  {today}")
    print(f"{'='*50}\n")

    cfg   = load_config()
    genre = pick_genre(cfg["genres"])
    price = genre.get("price", cfg["note"]["default_price"])

    # ① テーマ収集
    print("[STEP 1] テーマ収集...")
    themes = theme_collector.collect(genre)
    print(f"  取得テーマ: {themes[:3]}")

    # ② 記事生成
    print("\n[STEP 2] 記事生成 (Groq)...")
    article = article_generator.generate(genre, themes, today)
    print(f"  タイトル: {article['title']}")

    # ③ カバー画像取得
    print("\n[STEP 3] カバー画像取得 (Unsplash)...")
    cover = image_fetcher.fetch_cover_image(genre["id"], article["title"])
    if cover:
        article["cover_image"] = cover
        print(f"  画像URL: {cover['url']}")
        print(f"  クレジット: {cover['credit']}")
    else:
        article["cover_image"] = None
        print("  画像なし（スキップ）")

    # ④ ローカル保存（必ず実行）
    path = save_article(article, genre["id"], today)
    print(f"\n[STEP 4] 保存先: {path}")

    # ⑤ note投稿（失敗してもパイプライン全体は成功扱い）
    if os.environ.get("NOTE_COOKIES") or (os.environ.get("NOTE_EMAIL") and os.environ.get("NOTE_PASSWORD")):
        print(f"\n[STEP 5] note.com に投稿 (価格: {price}円)...")
        try:
            url = note_poster.post_sync(article, price)
            print(f"  投稿URL: {url}")
            if cover and os.environ.get("UNSPLASH_ACCESS_KEY"):
                image_fetcher.trigger_download(
                    os.environ["UNSPLASH_ACCESS_KEY"],
                    cover["download_url"],
                )
        except Exception as e:
            print(f"  [WARN] note投稿失敗（記事はarticles/に保存済み）: {e}")
    else:
        print("\n[SKIP] NOTE_EMAIL/PASSWORD 未設定 → articles/ から手動投稿してください")

    print(f"\n{'='*50}")
    print(f"  完了！記事: {path.name}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    run()
