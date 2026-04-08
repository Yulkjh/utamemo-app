#!/usr/bin/env python3
"""
ノート重要度スコアリングモジュール

OCRテキストから重要ワードをスコア付けするハイブリッドシステム。
Phase 1: ルールベース (赤字/太字/下線/見出し位置等の視覚特徴)
Phase 2: LLMリファイン (意味的文脈でスコア調整)

使い方:
  # ルールベースのみ (LLM不要)
  python -m note_importance.scorer --input note.txt --mode rule

  # ハイブリッド (ルール + LLM)
  python -m note_importance.scorer --input note.txt --mode hybrid --model Qwen/Qwen2.5-1.5B-Instruct

  # ディレクトリ一括処理
  python -m note_importance.scorer --input-dir ./ocr_output/ --output results.jsonl
"""

import argparse
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =========================================================================
# ビジュアルマーカーの定義 (OCRアノテーション形式)
# =========================================================================
# OCR出力テキストで視覚特徴を以下の形式でアノテーションする想定:
#   [red]赤字テキスト[/red]
#   [bold]太字テキスト[/bold]
#   [underline]下線テキスト[/underline]
#   [highlight]蛍光ペン[/highlight]
#   [box]枠囲み[/box]
#   [star]★マーク付き[/star]
#   【】はそのまま (既存のbuild_importance_dataset.pyと互換)

VISUAL_MARKERS = {
    "red":       {"pattern": r"\[red\](.*?)\[/red\]",             "weight": 10.0},
    "bold":      {"pattern": r"\[bold\](.*?)\[/bold\]",           "weight": 8.0},
    "underline": {"pattern": r"\[underline\](.*?)\[/underline\]", "weight": 6.0},
    "highlight": {"pattern": r"\[highlight\](.*?)\[/highlight\]", "weight": 7.0},
    "box":       {"pattern": r"\[box\](.*?)\[/box\]",             "weight": 9.0},
    "star":      {"pattern": r"\[star\](.*?)\[/star\]",           "weight": 5.0},
    "bracket":   {"pattern": r"【(.*?)】",                        "weight": 8.0},
}

# 見出しパターン
HEADING_PATTERNS = [
    r"^第[0-9一二三四五六七八九十百]+[章節回編]",
    r"^[0-9]+[\.\)]\s",
    r"^[①②③④⑤⑥⑦⑧⑨⑩]",
    r"^(ポイント|重要|要点|まとめ|公式|定義|定理|用語|例題|練習)",
    r"^(Chapter|Section|Point|Summary|Key)\s",
    r"^#{1,3}\s",
]

# 学習コンテンツ特有の重要パターン
CONTENT_PATTERNS = {
    "year":      {"pattern": r"[0-9]{3,4}年",                                    "weight": 4.0},
    "formula":   {"pattern": r"[A-Za-z]+\s*[=＝]\s*[A-Za-z0-9\+\-\*/\(\)]+",     "weight": 5.0},
    "chemical":  {"pattern": r"[A-Z][a-z]?[0-9]*(?:[A-Z][a-z]?[0-9]*)+",         "weight": 5.0},
    "unit":      {"pattern": r"[0-9]+(?:\.[0-9]+)?(?:℃|cm|mm|kg|g|m|km|L|ml|Hz|V|A|mol|Pa)", "weight": 3.0},
    "katakana":  {"pattern": r"[ァ-ヴー]{3,}",                                   "weight": 2.0},
    "kanji_term": {"pattern": r"[一-龥]{2,6}",                                   "weight": 1.0},
    "english":   {"pattern": r"[A-Z][a-z]{2,}(?:\s[A-Z][a-z]+)*",                "weight": 2.0},
}

# スコアリングに無視するパターン
IGNORE_PATTERNS = [
    r"^[ぁ-ん]{1,3}$",         # 短いひらがな (の、は、が 等)
    r"^[0-9]+$",               # 数字のみ
    r"^[a-z]{1,2}$",           # 短い英小文字
    r"^(する|ある|いる|なる|できる|れる|られる)$",
]


@dataclass
class ScoredWord:
    """スコア付きワード"""
    term: str
    rule_score: float = 0.0
    llm_score: Optional[float] = None
    final_score: float = 0.0
    markers: list = field(default_factory=list)  # 検出された視覚特徴
    context: str = ""  # ワードが出現した文脈(前後の文)


def normalize_term(term: str) -> str:
    """ワードを正規化"""
    cleaned = term.strip()
    cleaned = re.sub(r'^[\s\-・,、。:：;；\(\)\[\]「」『』]+', '', cleaned)
    cleaned = re.sub(r'[\s\-・,、。:：;；\(\)\[\]「」『』]+$', '', cleaned)
    if len(cleaned) < 2:
        return ''
    return cleaned


def should_ignore(term: str) -> bool:
    """無視すべきワードか判定"""
    return any(re.fullmatch(p, term) for p in IGNORE_PATTERNS)


# =========================================================================
# Phase 1: ルールベーススコアリング
# =========================================================================

def rule_based_score(text: str, max_keywords: int = 50) -> list[ScoredWord]:
    """
    ルールベースで重要ワードをスコアリング。
    視覚特徴 (赤字/太字等) と構造特徴 (見出し/位置) を総合評価。
    """
    scores: dict[str, ScoredWord] = {}

    def add_score(term: str, weight: float, marker: str = "", context: str = ""):
        term = normalize_term(term)
        if not term or should_ignore(term):
            return
        if term not in scores:
            scores[term] = ScoredWord(term=term)
        scores[term].rule_score += weight
        if marker and marker not in scores[term].markers:
            scores[term].markers.append(marker)
        if context and not scores[term].context:
            scores[term].context = context[:200]

    # 1. 視覚マーカーからの抽出
    for marker_name, config in VISUAL_MARKERS.items():
        for m in re.finditer(config["pattern"], text):
            content = m.group(1)
            # マーカー内のテキストをワード分割
            sub_terms = re.findall(
                r'[A-Za-z][A-Za-z0-9_\-]{1,}'
                r'|[0-9]{2,4}年'
                r'|[ァ-ヴー]{2,}'
                r'|[一-龥]{2,}',
                content
            )
            if sub_terms:
                for t in sub_terms:
                    add_score(t, config["weight"], marker_name, content)
            else:
                # 分割できない場合はそのまま
                add_score(content, config["weight"], marker_name, content)

    # 2. 構造特徴 (見出し行のワードにボーナス)
    plain = re.sub(r'\[[a-z]+\]|\[/[a-z]+\]', '', text)  # マーカータグ除去
    lines = [line.strip() for line in plain.splitlines() if line.strip()]

    for line in lines:
        is_heading = any(re.search(p, line) for p in HEADING_PATTERNS)
        heading_bonus = 3.0 if is_heading else 0.0

        # コンテンツパターンマッチ
        for pat_name, config in CONTENT_PATTERNS.items():
            for m in re.finditer(config["pattern"], line):
                add_score(
                    m.group(0),
                    config["weight"] + heading_bonus,
                    pat_name if is_heading else "",
                    line
                )

    # 3. 出現頻度ボーナス (複数回出現 = 重要)
    word_counts = Counter()
    for line in lines:
        for m in re.findall(r'[一-龥]{2,}|[ァ-ヴー]{2,}|[A-Za-z]{3,}', line):
            n = normalize_term(m)
            if n and not should_ignore(n):
                word_counts[n] += 1
    for term, count in word_counts.items():
        if count >= 2:  # 2回以上出現
            freq_bonus = min(count * 0.5, 3.0)
            add_score(term, freq_bonus, "frequency")

    # スコアをソートして上位を返す
    result = sorted(scores.values(), key=lambda x: -x.rule_score)[:max_keywords]

    # 正規化 (0.0〜1.0)
    if result:
        max_score = result[0].rule_score
        if max_score > 0:
            for w in result:
                w.final_score = round(min(w.rule_score / max_score, 1.0), 3)
    return result


# =========================================================================
# Phase 2: LLMリファインスコアリング
# =========================================================================

def llm_refine_score(
    words: list[ScoredWord],
    full_text: str,
    model_name: str = "Qwen/Qwen2.5-1.5B-Instruct",
    device: str = "auto",
) -> list[ScoredWord]:
    """
    ルールベーススコアをLLMで文脈的にリファイン。
    モデルに全テキストとルールベース上位ワードを渡し、
    教科/分野を考慮した重要度を返してもらう。
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    logger.info(f"LLMリファインモデルをロード: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.float16,
        device_map=device,
    )
    model.eval()

    # ワードリストを整形
    word_list_str = "\n".join(
        f"- {w.term} (ルールスコア: {w.final_score:.2f}, 特徴: {','.join(w.markers) or 'なし'})"
        for w in words[:30]
    )

    prompt = f"""以下はノートのOCRテキストと、ルールベースで抽出された重要ワード候補です。
各ワードの教育的重要度を0.0〜1.0で評価してJSON配列で返してください。

評価基準:
- テストに出そうな用語・人名・年号・公式 → 高スコア (0.8〜1.0)
- 教科の核心概念 → 高スコア (0.7〜0.9)
- 補足的・一般的な語 → 低スコア (0.1〜0.4)
- 接続詞・助詞・一般動詞 → 0.0

テキスト (先頭1000文字):
{full_text[:1000]}

ワード候補:
{word_list_str}

出力形式 (JSONのみ、他のテキスト不要):
[{{"term": "織田信長", "score": 0.95}}, {{"term": "1582年", "score": 0.9}}, ...]
"""

    messages = [
        {"role": "system", "content": "あなたは教育コンテンツの重要度を分析する専門家です。JSON形式で回答してください。"},
        {"role": "user", "content": prompt},
    ]
    input_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(input_text, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=1024,
            temperature=0.1,
            do_sample=True,
        )

    response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    logger.info(f"LLM応答 (先頭200文字): {response[:200]}")

    # JSON解析
    try:
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if json_match:
            llm_scores = json.loads(json_match.group(0))
            score_map = {item["term"]: float(item["score"]) for item in llm_scores}

            for w in words:
                if w.term in score_map:
                    w.llm_score = score_map[w.term]
                    # ルール60% + LLM40% のブレンド
                    w.final_score = round(w.final_score * 0.6 + w.llm_score * 0.4, 3)
        else:
            logger.warning("LLM応答からJSONを抽出できませんでした。ルールスコアをそのまま使用。")
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"LLM応答のパースに失敗: {e}。ルールスコアをそのまま使用。")

    # 再ソート
    words.sort(key=lambda x: -x.final_score)
    return words


# =========================================================================
# メイン処理
# =========================================================================

def score_text(
    text: str,
    mode: str = "rule",
    max_keywords: int = 50,
    model_name: str = "Qwen/Qwen2.5-1.5B-Instruct",
) -> list[ScoredWord]:
    """テキストをスコアリングして重要ワードを返す"""
    words = rule_based_score(text, max_keywords=max_keywords)

    if mode == "hybrid" and words:
        words = llm_refine_score(words, text, model_name=model_name)

    return words


def process_file(
    path: Path,
    mode: str = "rule",
    max_keywords: int = 50,
    model_name: str = "Qwen/Qwen2.5-1.5B-Instruct",
) -> dict:
    """ファイルを処理してスコアリング結果を辞書で返す"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    words = score_text(text, mode=mode, max_keywords=max_keywords, model_name=model_name)
    return {
        "source_file": str(path),
        "char_count": len(text),
        "mode": mode,
        "keywords": [asdict(w) for w in words],
    }


def main():
    parser = argparse.ArgumentParser(description="ノート重要度スコアリング")
    parser.add_argument("--input", type=str, help="入力テキストファイル")
    parser.add_argument("--input-dir", type=str, help="入力ディレクトリ (.txt再帰探索)")
    parser.add_argument("--output", type=str, default=None, help="出力JSONLファイル")
    parser.add_argument("--mode", choices=["rule", "hybrid"], default="rule",
                        help="rule=ルールベースのみ, hybrid=ルール+LLM")
    parser.add_argument("--model", type=str, default="Qwen/Qwen2.5-1.5B-Instruct",
                        help="LLMモデル名 (hybridモード時)")
    parser.add_argument("--max-keywords", type=int, default=50, help="最大キーワード数")
    parser.add_argument("--top", type=int, default=20, help="表示する上位ワード数")
    args = parser.parse_args()

    if not args.input and not args.input_dir:
        parser.error("--input または --input-dir を指定してください")

    files = []
    if args.input:
        files.append(Path(args.input))
    if args.input_dir:
        files.extend(sorted(Path(args.input_dir).rglob("*.txt")))

    if not files:
        raise SystemExit("対象ファイルが見つかりません")

    results = []
    for f in files:
        logger.info(f"処理中: {f}")
        result = process_file(f, mode=args.mode, max_keywords=args.max_keywords, model_name=args.model)
        results.append(result)

        # コンソール表示
        print(f"\n{'='*60}")
        print(f"📄 {f.name}  ({result['char_count']}文字)")
        print(f"{'='*60}")
        for i, kw in enumerate(result["keywords"][:args.top], 1):
            markers_str = f" [{', '.join(kw['markers'])}]" if kw["markers"] else ""
            llm_str = f" LLM:{kw['llm_score']:.2f}" if kw["llm_score"] is not None else ""
            print(f"  {i:2d}. {kw['term']:<20s}  スコア: {kw['final_score']:.3f}{markers_str}{llm_str}")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        logger.info(f"結果を保存: {out_path} ({len(results)}件)")


if __name__ == "__main__":
    main()
