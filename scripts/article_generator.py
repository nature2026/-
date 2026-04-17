#!/usr/bin/env python3
"""
記事生成: Groq API (Llama 3.3 70B) を使って note 向け有料記事を生成する。
"""

import os
import time
from groq import Groq

FREE_RATIO = 0.30


def _build_prompt(genre: dict, themes: list[str], today: str) -> str:
    themes_text = "\n".join(f"・{t}" for t in themes)
    return f"""あなたは「{genre['persona']}」として、note.com で月100万円以上稼いでいるトップライターです。
今日（{today}）のトレンドテーマをもとに、圧倒的に売れるnote有料記事を日本語で執筆してください。

# トレンドテーマ（この中から最も売れそうな1テーマを選んで書く）
{themes_text}

# 記事の要件
- ジャンル: {genre['name']}
- 価格帯: {genre['price']}円の有料記事
- 文字数: 合計3000〜5000文字
- 文体: 話しかけるような親しみやすい文体（読者は20〜40代）

# 必須の記事構成（この順番で書くこと）

## ① タイトル（1行）
- 【2026年最新】【完全版】などの権威ワードを入れる
- 数字を入れる（「7つの方法」「月10万円」など）
- 読者の悩みに直結する言葉を使う

## ② 導入文（無料公開）
- 読者の悩みに深く共感する（3〜4文）
- 「この記事を読めば〇〇できる」という約束（2〜3文）
- 著者の簡単な実績紹介（1〜2文）

## ③ 無料公開セクション（全体の30%）
- 「なぜ多くの人が失敗するのか」など問題提起
- 少し価値のある情報を提供（読者に「続きが読みたい」と思わせる）
- 最後に「でも本当に大切なのは次のステップです」など有料部分へ誘導

## ④ ＝＝＝ ここから有料 ＝＝＝（このマーカーを本文中に入れること）

## ⑤ 有料公開セクション（全体の70%）
- 具体的なステップ・手順（番号付きリスト）
- 実例・数字・テンプレートを豊富に含める
- 「すぐに使えるテンプレート」セクションを必ず入れる
- まとめ・行動計画（読者が今日から始められる内容）

# 出力形式
- Markdownで出力
- 見出しは ## または ### を使う
- 絵文字を適度に使う（読みやすさUP）
- タイトルは記事の冒頭に「# タイトル」として記載
"""


def generate(genre: dict, themes: list[str], today: str, retries: int = 3) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY が未設定です。")

    client = Groq(api_key=api_key)
    prompt = _build_prompt(genre, themes, today)

    for attempt in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=4096,
            )
            full_md = resp.choices[0].message.content
            print(f"[INFO] 記事生成完了 ({len(full_md)}文字)")
            break
        except Exception as e:
            err = str(e)
            print(f"[WARN] Groq attempt {attempt}/{retries}: {err[:200]}")
            if attempt == retries:
                raise
            time.sleep(10 * attempt)

    return _parse_article(full_md)


def _parse_article(full_md: str) -> dict:
    title = ""
    for line in full_md.strip().splitlines():
        if line.strip().startswith("# "):
            title = line.strip()[2:].strip()
            break
    if not title:
        title = "【2026年最新】完全ガイド"

    PAID_MARKER = "＝＝＝ ここから有料"
    if PAID_MARKER in full_md:
        idx = full_md.index(PAID_MARKER)
        free_part = full_md[:idx].strip()
        paid_part = full_md[idx:].strip()
    else:
        mid = int(len(full_md) * FREE_RATIO)
        split_at = full_md.rfind("\n\n", 0, mid) or mid
        free_part = full_md[:split_at].strip()
        paid_part = full_md[split_at:].strip()

    return {
        "title": title,
        "free_part": free_part,
        "paid_part": paid_part,
        "full_markdown": full_md,
    }
