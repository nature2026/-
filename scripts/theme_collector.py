#!/usr/bin/env python3
"""
テーマ収集: Google Trends + RSS から今日の旬なテーマを取得する。
"""

import time
import feedparser
from datetime import datetime, timezone, timedelta

# ジャンルごとのエバーグリーンテーマ（Trends/RSS が取れなかった時のフォールバック）
EVERGREEN = {
    "money": [
        "SNSで月10万円稼ぐ完全ロードマップ",
        "副業初心者が最初の1万円を稼ぐ最短ルート",
        "会社員が今すぐ始められる不労所得3選",
        "フリーランス転向前に知っておくべきリアルな収入事情",
        "noteで稼ぐ人がやっている記事構成の法則",
    ],
    "investment": [
        "新NISA満額活用で10年後の資産シミュレーション",
        "投資初心者が絶対にやってはいけない5つの失敗",
        "月3万円から始めるインデックス投資の具体的な手順",
        "高配当株vs成長株、どちらを選ぶべきか",
        "お金が貯まらない人に共通する思考パターン",
    ],
}


def _fetch_rss_themes(rss_feeds: list[str], hours_back: int = 24) -> list[str]:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
    themes = []
    for url in rss_feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if parsed:
                    pub_dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                title = entry.get("title", "").strip()
                if title:
                    themes.append(title)
        except Exception:
            pass
    return themes


def _fetch_google_trends(keywords: list[str]) -> list[str]:
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="ja-JP", tz=540, timeout=(10, 30), retries=2, backoff_factor=0.5)
        pytrends.build_payload(keywords[:5], timeframe="now 1-d", geo="JP")
        related = pytrends.related_queries()
        themes = []
        for v in related.values():
            top = v.get("top")
            if top is not None and not top.empty:
                themes.extend(top["query"].head(3).tolist())
        return themes
    except Exception:
        return []


def collect(genre: dict) -> list[str]:
    """
    1. Google Trends で関連クエリを取得
    2. RSS フィードから最新記事タイトルを取得
    3. 取れなかった場合はエバーグリーンテーマを使用
    返り値: テーマ文字列のリスト（最大5件）
    """
    themes: list[str] = []

    # Google Trends
    trend_themes = _fetch_google_trends(genre["keywords"])
    themes.extend(trend_themes)

    # RSS
    if len(themes) < 3:
        rss_themes = _fetch_rss_themes(genre["rss_feeds"])
        themes.extend(rss_themes)

    # フォールバック
    if not themes:
        themes = EVERGREEN.get(genre["id"], ["副業で稼ぐ方法"])

    # 重複除去・上限
    seen, unique = set(), []
    for t in themes:
        if t not in seen:
            seen.add(t)
            unique.append(t)
        if len(unique) >= 5:
            break

    return unique
