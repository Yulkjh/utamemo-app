#!/usr/bin/env python3
"""
歌詞生成LLM 品質評価モジュール

生成された歌詞の品質を複数の観点でスコアリングする。
学習データの品質フィルタリングと、学習済みモデルの性能評価に使う。

評価軸:
  1. キーワード含有率: 重要キーワードが歌詞に含まれているか
  2. 構造品質: [Verse] [Chorus] 等のセクション構造があるか
  3. 韻スコア: 行末が韻を踏んでいるか (日本語の母音パターン)
  4. 繰り返し: Chorusの繰り返しがあるか (暗記効果)
  5. NGワード: 禁止表現が含まれていないか

Track A (note_importance) とは完全に独立。
"""

import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =========================================================================
# 禁止表現 (メタ的な学習促進フレーズ → 歌詞には不要)
# =========================================================================

NG_PHRASES = [
    "覚えよう", "暗記しよう", "忘れずに", "テストに出る",
    "全てが大事", "しっかり学ぼう", "復習しよう", "頑張ろう",
    "重要です", "ポイントは", "まとめると", "以上が",
]


# =========================================================================
# 日本語母音マッピング (韻の判定用)
# =========================================================================

HIRAGANA_VOWEL = {}
for ch, vowel in [
    ("あかさたなはまやらわ", "a"), ("いきしちにひみり", "i"),
    ("うくすつぬふむゆる", "u"), ("えけせてねへめれ", "e"),
    ("おこそとのほもよろを", "o"), ("ん", "n"),
    ("がざだば", "a"), ("ぎじぢび", "i"),
    ("ぐずづぶ", "u"), ("げぜでべ", "e"),
    ("ごぞどぼ", "o"),
    ("ぱ", "a"), ("ぴ", "i"), ("ぷ", "u"), ("ぺ", "e"), ("ぽ", "o"),
]:
    for c in ch:
        HIRAGANA_VOWEL[c] = vowel


def _to_hiragana(text: str) -> str:
    """カタカナ → ひらがな変換"""
    result = []
    for ch in text:
        cp = ord(ch)
        if 0x30A1 <= cp <= 0x30F6:  # カタカナ
            result.append(chr(cp - 0x60))
        else:
            result.append(ch)
    return "".join(result)


def _get_ending_vowels(line: str, count: int = 2) -> str:
    """行末のひらがな母音パターンを取得"""
    line = _to_hiragana(line.strip().rstrip("!！?？)）」』】"))
    vowels = []
    for ch in reversed(line):
        v = HIRAGANA_VOWEL.get(ch)
        if v:
            vowels.append(v)
            if len(vowels) >= count:
                break
    vowels.reverse()
    return "".join(vowels)


def score_rhyme(lyrics: str) -> float:
    """
    韻スコア (0.0 - 1.0)
    連続する2行の行末母音が一致していれば韻を踏んでいると判定。
    """
    lines = [
        l.strip() for l in lyrics.split("\n")
        if l.strip() and not l.strip().startswith("[")
    ]
    if len(lines) < 2:
        return 0.0

    rhyme_count = 0
    for i in range(len(lines) - 1):
        v1 = _get_ending_vowels(lines[i])
        v2 = _get_ending_vowels(lines[i + 1])
        if v1 and v2 and v1 == v2:
            rhyme_count += 1

    return min(rhyme_count / max(len(lines) - 1, 1), 1.0)


def score_keyword_coverage(lyrics: str, keywords: list[str]) -> float:
    """
    キーワード含有率 (0.0 - 1.0)
    重要キーワードのうち歌詞に含まれている割合。
    """
    if not keywords:
        return 0.5  # キーワード未指定の場合は中間値

    found = sum(1 for kw in keywords if kw in lyrics)
    return found / len(keywords)


def score_structure(lyrics: str) -> float:
    """
    構造品質 (0.0 - 1.0)
    [Verse] [Chorus] 等のセクションラベルの有無と質。
    """
    score = 0.0
    sections = re.findall(r'\[(Verse|Chorus|Bridge|Intro|Outro|Hook)', lyrics)

    if len(sections) >= 5:
        score += 0.4
    elif len(sections) >= 3:
        score += 0.3
    elif len(sections) >= 1:
        score += 0.15

    # Chorusの繰り返し (暗記効果に重要)
    chorus_count = sum(1 for s in sections if s == "Chorus")
    if chorus_count >= 2:
        score += 0.3
    elif chorus_count >= 1:
        score += 0.15

    # 適切な長さ
    content_len = len(lyrics)
    if 300 <= content_len <= 2000:
        score += 0.2
    elif 150 <= content_len < 300:
        score += 0.1

    # 合いの手の存在
    kakegoe = re.findall(r'[（(][^)）]{1,10}[!！][)）]', lyrics)
    if kakegoe:
        score += 0.1

    return min(score, 1.0)


def score_ng_words(lyrics: str) -> float:
    """
    NGワードスコア (0.0 - 1.0)
    NGワードが含まれていなければ1.0、含まれるほど減点。
    """
    ng_count = sum(1 for phrase in NG_PHRASES if phrase in lyrics)
    if ng_count == 0:
        return 1.0
    elif ng_count <= 2:
        return 0.5
    else:
        return 0.0


def evaluate_lyrics(lyrics: str, keywords: list[str] = None) -> dict:
    """
    歌詞を総合評価。

    Returns:
        {
            "keyword_coverage": float,  # キーワード含有率
            "structure": float,         # 構造品質
            "rhyme": float,            # 韻スコア
            "ng_words": float,         # NGワードスコア
            "total": float,            # 総合スコア (加重平均)
        }
    """
    if not lyrics or not lyrics.strip():
        return {
            "keyword_coverage": 0.0,
            "structure": 0.0,
            "rhyme": 0.0,
            "ng_words": 0.0,
            "total": 0.0,
        }

    kw = score_keyword_coverage(lyrics, keywords or [])
    st = score_structure(lyrics)
    rh = score_rhyme(lyrics)
    ng = score_ng_words(lyrics)

    # 加重平均 (キーワード含有が最重要)
    total = kw * 0.35 + st * 0.30 + rh * 0.15 + ng * 0.20

    return {
        "keyword_coverage": round(kw, 3),
        "structure": round(st, 3),
        "rhyme": round(rh, 3),
        "ng_words": round(ng, 3),
        "total": round(total, 3),
    }


def evaluate_batch(records: list[dict]) -> dict:
    """
    学習データ全体の品質統計を計算。

    Args:
        records: SFT学習レコードのリスト (messages形式)

    Returns:
        {
            "count": int,
            "avg_total": float,
            "avg_keyword": float,
            "avg_structure": float,
            "avg_rhyme": float,
            "high_quality": int,   # total >= 0.6
            "low_quality": int,    # total < 0.3
        }
    """
    scores = []
    for record in records:
        lyrics = ""
        keywords_text = ""
        for msg in record.get("messages", []):
            if msg.get("role") == "assistant":
                lyrics = msg.get("content", "")
            if msg.get("role") == "user":
                keywords_text = msg.get("content", "")

        # ユーザープロンプトからキーワード抽出
        keywords = []
        kw_match = re.search(r"重要キーワード:\s*(.+?)(?:\n|$)", keywords_text)
        if kw_match:
            keywords = [k.strip() for k in kw_match.group(1).split(",")]

        score = evaluate_lyrics(lyrics, keywords)
        scores.append(score)

    if not scores:
        return {"count": 0}

    n = len(scores)
    return {
        "count": n,
        "avg_total": round(sum(s["total"] for s in scores) / n, 3),
        "avg_keyword": round(sum(s["keyword_coverage"] for s in scores) / n, 3),
        "avg_structure": round(sum(s["structure"] for s in scores) / n, 3),
        "avg_rhyme": round(sum(s["rhyme"] for s in scores) / n, 3),
        "high_quality": sum(1 for s in scores if s["total"] >= 0.6),
        "low_quality": sum(1 for s in scores if s["total"] < 0.3),
    }
