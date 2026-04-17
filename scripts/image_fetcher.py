#!/usr/bin/env python3
"""
Unsplash API で記事のカバー画像を取得する。
"""

import os
import requests


UNSPLASH_API = "https://api.unsplash.com"

GENRE_KEYWORDS = {
    "money":      ["money", "business", "success", "wealth"],
    "investment": ["investment", "stock market", "finance", "growth"],
}

FALLBACK_KEYWORDS = ["success", "business", "technology"]


def fetch_cover_image(genre_id: str, title: str) -> dict | None:
    """
    記事タイトルとジャンルに合うUnsplash画像を返す。
    {"url": str, "credit": str, "download_url": str}
    """
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not access_key:
        print("[WARN] UNSPLASH_ACCESS_KEY 未設定。画像スキップ。")
        return None

    keywords = GENRE_KEYWORDS.get(genre_id, FALLBACK_KEYWORDS)

    for kw in keywords:
        result = _search(access_key, kw)
        if result:
            return result

    return None


def _search(access_key: str, query: str) -> dict | None:
    try:
        resp = requests.get(
            f"{UNSPLASH_API}/search/photos",
            params={
                "query":       query,
                "per_page":    1,
                "orientation": "landscape",
            },
            headers={"Authorization": f"Client-ID {access_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None

        photo = results[0]
        return {
            "url":          photo["urls"]["regular"],
            "thumb":        photo["urls"]["small"],
            "credit":       f'Photo by {photo["user"]["name"]} on Unsplash',
            "download_url": photo["links"]["download_location"],
        }
    except Exception as e:
        print(f"[WARN] Unsplash検索失敗 ({query}): {e}")
        return None


def trigger_download(access_key: str, download_url: str):
    """Unsplash利用規約に従いダウンロードイベントを記録する"""
    try:
        requests.get(
            download_url,
            headers={"Authorization": f"Client-ID {access_key}"},
            timeout=5,
        )
    except Exception:
        pass
