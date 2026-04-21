#!/usr/bin/env python3
"""
テーマ収集: Google Trends + RSS から今日の旬なテーマを取得する。
"""

import time
import feedparser
from datetime import datetime, timezone, timedelta

# ジャンルごとのエバーグリーンテーマ（Trends/RSS が取れなかった時のフォールバック）
EVERGREEN = {
    "claude_tips": [
        "Claude AIで作業時間を半分にする7つのプロンプト術",
        "ChatGPTからClaudeに乗り換えて気づいた圧倒的な違い",
        "エンジニアがClaudeを使ってコードレビューを自動化する方法",
        "Claudeに長文を要約させるときの最強プロンプトテンプレート",
        "Claude Projectsを使って個人ナレッジベースを構築する手順",
    ],
    "ai_dev": [
        "Claude APIで自分だけのAIエージェントを作る完全ガイド",
        "プロンプトエンジニアリングの基礎から応用まで実例で解説",
        "Claude APIとPythonで業務自動化ツールをゼロから作る方法",
        "AIエージェント開発で絶対に押さえるべきツール設計パターン",
        "Claude APIのコストを最小化しながら最大の出力を得るコツ",
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
