#!/usr/bin/env python3
"""
記事生成: Groq API (Llama 3.3 70B) を使って note 向け有料記事を生成する。
"""

import os
import time
from groq import Groq

FREE_RATIO = 0.30
MIN_CHARS = 4000


def _build_prompt(genre: dict, themes: list[str], today: str) -> str:
    themes_text = "\n".join(f"・{t}" for t in themes)
    return f"""あなたは「{genre['persona']}」として、note.com で月200万円以上稼いでいる日本最高峰のライターです。
今日（{today}）のトレンドテーマをもとに、圧倒的に売れる note 有料記事を日本語で執筆してください。

# 選択するトレンドテーマ（最も読者に刺さるテーマを1つ選ぶ）
{themes_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 記事の基本仕様
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ジャンル: {genre['name']}
- 価格帯: {genre['price']}円の有料記事
- **合計文字数: 最低6000文字（絶対に省略しないこと）**
- 文体: 友人に話しかけるような親しみやすい口語体
- 対象読者: 20〜40代の会社員・フリーランス

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 記事構成（省略禁止。各セクションを全て書くこと）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### 【1】タイトル（記事の1行目に書く）
フォーマット: # タイトル
条件:
- 【2026年最新】や【完全版】などの権威ワードを入れる
- 具体的な数字を含む（「7ステップ」「月15万円」「3ヶ月で」など）
- 読者の悩みに直結する言葉を使う
- 40文字以内が理想

### 【2】リード文・導入（800〜1000文字）
- 読者の具体的な悩みを描写する（「毎月生活費が足りない」「老後2000万問題が怖い」など）
- 著者自身の失敗体験を1つ書く（読者に親近感を持たせる）
- この記事を読むと何が変わるか、具体的な成果を明示する
- 著者の簡単な実績（数字入り）で信頼感を高める

### 【3】無料公開セクション（1500〜2000文字）
- ## 見出し: 「なぜ多くの人は{genre['name']}で失敗するのか？」
  → 失敗する3つの理由を詳細に説明（各理由200文字以上）
  → 具体的な失敗エピソード（架空でOK。リアルに）
- ## 見出し: 「成功者と失敗者を分ける"たった1つの違い"」
  → 問題の核心に触れるが、解決策の詳細は有料部分へ誘導
- 有料部分への誘導文で締める

### 【4】マーカー（この行をそのまま入れる）
＝＝＝ ここから有料 ＝＝＝

### 【5】有料公開セクション（4000〜5000文字）
以下を全て含めること（省略不可）:

**A. 実践ステップ（番号付きリスト、5〜7ステップ）**
各ステップは見出し付きで最低400文字。具体的なツール名・URL・操作手順・数字を入れる。
例: 「## ステップ1: まず証券口座を開設する（所要時間15分）」

**B. ケーススタディ（2〜3例）**
「〇〇さん（32歳・会社員）は△△を実践して□□の成果を出した」形式。
各ケースは300文字以上。数字と感情の変化を書く。

**C. すぐに使えるテンプレート（2〜3個）**
見出し: 「## 📋 テンプレート：〇〇用」
コピペですぐ使える内容。空白を埋めるだけで使えるもの。

**D. よくある質問と回答（Q&A、5問以上）**
見出し: 「## ❓ よくある質問」
各回答は150文字以上。読者が実際に疑問に思うことへの丁寧な回答。

**E. まとめ・行動計画（400文字以上）**
見出し: 「## 🎯 まとめ｜今日から始める3ステップ」
今日・今週・今月にやることを具体的に書く。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 出力ルール（必ず守ること）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Markdownで出力（## ### で見出し）
- 絵文字を積極的に使う（🚀💡📊✅🔑💰など）
- 箇条書きだけでなく文章で深掘りする
- 具体的な数字・固有名詞・ツール名を多用する
- **省略・要約・「〜略〜」などは絶対に禁止**
- **必ず6000文字以上書く。足りない場合は各セクションを加筆する**
"""


def generate(genre: dict, themes: list[str], today: str, retries: int = 3) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY が未設定です。")

    client = Groq(api_key=api_key)
    prompt = _build_prompt(genre, themes, today)

    full_md = ""
    for attempt in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "あなたは日本語で記事を書くプロのライターです。"
                            "指示された文字数・構成を必ず守り、省略や要約は絶対にしません。"
                            "各セクションを丁寧に、具体的に、詳細に書きます。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.85,
                max_tokens=8000,
            )
            full_md = resp.choices[0].message.content
            char_count = len(full_md)
            print(f"[INFO] 記事生成完了 ({char_count}文字)")

            if char_count >= MIN_CHARS:
                break

            print(f"[WARN] 文字数不足 ({char_count} < {MIN_CHARS}). attempt={attempt}")
            if attempt < retries:
                time.sleep(5)

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
        end_of_marker = full_md.find('\n', idx)
        if end_of_marker == -1:
            end_of_marker = len(full_md)
        free_part = full_md[:idx].strip()
        paid_part = full_md[end_of_marker:].strip()
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
