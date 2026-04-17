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
import note_poster

JST = timezone(timedelta(hours=9))


def load_config() -> dict:
    with open(ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


def pick_genre(genres: list[dict]) -> dict:
    # 日付でジャンルをローテーション
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
        f.write(article["full_markdown"])
    return path


def run():
    today = datetime.now(tz=JST).strftime("%Y-%m-%d")
    print(f"\n{'='*50}")
    print(f"  AI note 自動投稿パイプライン  {today}")
    print(f"{'='*50}\n")

    cfg    = load_config()
    genre  = pick_genre(cfg["genres"])
    price  = genre.get("price", cfg["note"]["default_price"])

    # ① テーマ収集
    print("[STEP 1] テーマ収集...")
    themes = theme_collector.collect(genre)
    print(f"  取得テーマ: {themes[:3]}")

    # ② 記事生成
    print("\n[STEP 2] 記事生成 (Gemini)...")
    article = article_generator.generate(genre, themes, today)
    print(f"  タイトル: {article['title']}")

    # ③ ローカル保存
    path = save_article(article, genre["id"], today)
    print(f"  保存先: {path}")

    # ④ note投稿
    should_post = os.environ.get("NOTE_EMAIL") and os.environ.get("NOTE_PASSWORD")
    if should_post:
        print(f"\n[STEP 3] note.com に投稿 (価格: {price}円)...")
        url = note_poster.post_sync(article, price)
        print(f"  投稿URL: {url}")
    else:
        print("\n[SKIP] NOTE_EMAIL / NOTE_PASSWORD 未設定のため投稿をスキップ")
        print("  → articles/ フォルダの記事を手動でコピー＆ペーストしてください")

    print(f"\n{'='*50}")
    print("  完了！")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    run()
