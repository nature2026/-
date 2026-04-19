#!/usr/bin/env python3
"""
記事生成: Groq API (Llama 3.3 70B) を使って note 向け有料記事を生成する。
無料部分と有料部分を別々に生成することで確実に 5000 字超を達成する。
"""

import os
import time
from groq import Groq

FREE_RATIO = 0.30


def _call_groq(client: Groq, system: str, user: str, retries: int = 3) -> str:
    for attempt in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                temperature=0.85,
                max_tokens=4096,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"[WARN] Groq attempt {attempt}/{retries}: {str(e)[:120]}")
            if attempt == retries:
                raise
            time.sleep(8 * attempt)
    return ""


def _build_free_prompt(genre: dict, themes: list[str], today: str) -> str:
    themes_text = "\n".join(f"・{t}" for t in themes)
    return f"""今日（{today}）のトレンドテーマを踏まえ、{genre['name']}ジャンルのnote有料記事の「無料公開パート」を日本語で書いてください。

【トレンドテーマ（1つ選ぶ）】
{themes_text}

【あなたのペルソナ】
{genre['persona']}

【書く内容（この順番で）】

1. タイトル（記事の冒頭1行目）
   - 形式: # タイトル
   - 【2026年最新】などの権威ワード＋具体的な数字（「7ステップ」「月15万円」等）

2. 導入文（700〜900字）
   - 読者が今まさに抱えている具体的な悩みを描写する
   - 著者自身の失敗談→転換点のエピソード1つ
   - この記事を読むと得られる成果を明示
   - 著者の実績を数字で示す（信頼感）

3. 無料公開セクション（1000〜1200字）
   ## なぜ多くの人は〇〇で失敗するのか？
   → 失敗する理由を3つ、各200字以上で説明
   → リアルな失敗エピソード（架空でも具体的に）
   ## 成功者が密かにやっていること
   → 成功の鍵に触れる（ただし詳細は有料パートへ）
   → 有料パートへの誘導文で締める

4. 最終行（必須）
   ＝＝＝ ここから有料 ＝＝＝

【ルール】
- Markdownで出力（## ## を見出しに使う）
- 絵文字を適度に使う 🚀💡✅
- 合計1800〜2200字で書く
- 省略・要約は禁止"""


def _build_paid_prompt(genre: dict, title: str, today: str) -> str:
    return f"""note有料記事のタイトルは「{title}」です。
この記事の「有料公開パート」のみを日本語で書いてください。ジャンル: {genre['name']}（{genre['price']}円）

【書く内容（全て書くこと。省略禁止）】

## ステップ解説（5〜6ステップ）
各ステップを ## ステップN: タイトル の見出しで書く。
各ステップは350字以上。具体的なツール名・操作手順・数字を含む。

## ケーススタディ（2例）
## 📖 実例: 〇〇さん（年齢・職業）のケース
各例は300字以上。実践内容・得た成果（数字）・感情の変化を書く。

## すぐ使えるテンプレート（2個）
## 📋 テンプレート: 〇〇用
[ ] で空欄を示し、コピペしてすぐ使える形式にする。

## よくある質問（5問）
## ❓ よくある質問
Q: 具体的な質問
A: 150字以上の詳細な回答

## まとめ・行動計画
## 🎯 今日から始める行動計画
今日・今週・今月にやることを具体的に書く。

【ルール】
- Markdownで出力（## ### を見出しに使う）
- 絵文字を使う 💰📊🔑
- 合計3500〜4500字で書く
- 省略・「〜略〜」・箇条書きだけは禁止。文章で深掘りすること"""


def generate(genre: dict, themes: list[str], today: str, retries: int = 3) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY が未設定です。")

    client = Groq(api_key=api_key)
    system_base = (
        "あなたは日本語の有料記事を書くプロのライターです。"
        "指示された構成・文字数を必ず守り、途中で終わらせず最後まで書き切ります。"
    )

    # Pass 1: タイトル + 無料パート（マーカー行で終わる）
    print("[INFO] Pass 1: 無料パート生成中...")
    free_md = _call_groq(client, system_base, _build_free_prompt(genre, themes, today), retries)
    print(f"[INFO] Pass 1 完了 ({len(free_md)}字)")

    # タイトル抽出
    title = "【2026年最新】完全ガイド"
    for line in free_md.splitlines():
        if line.strip().startswith("# "):
            title = line.strip()[2:].strip()
            break

    # Pass 2: 有料パート
    print("[INFO] Pass 2: 有料パート生成中...")
    paid_md = _call_groq(client, system_base, _build_paid_prompt(genre, title, today), retries)
    print(f"[INFO] Pass 2 完了 ({len(paid_md)}字)")

    # 結合
    MARKER = "＝＝＝ ここから有料"
    if MARKER not in free_md:
        free_md = free_md.rstrip() + "\n\n＝＝＝ ここから有料 ＝＝＝"

    # free_md のマーカー行まで = free_part、paid_md 全体 = paid_part
    idx = free_md.index(MARKER)
    free_part = free_md[:idx].strip()

    full_md = free_md + "\n\n" + paid_md
    total = len(full_md)
    print(f"[INFO] 記事生成完了 合計{total}字（無料{len(free_part)}字 + 有料{len(paid_md)}字）")

    return {
        "title":         title,
        "free_part":     free_part,
        "paid_part":     paid_md.strip(),
        "full_markdown": full_md,
    }
