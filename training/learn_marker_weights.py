#!/usr/bin/env python3
"""
マーカー重みの自動学習スクリプト

OCRアノテーション済みノートデータを分析し、各マーカーの「重要度への寄与」を
統計的に算出して scorer.py の VISUAL_MARKERS 重みを最適化する。

考え方:
  ノート作成者は重要な情報ほど「目立つ装飾」を使う傾向がある。
  だが「赤字 = 最重要」とは限らない。実際のデータから:
    1. 選択性 (selectivity): そのマーカーがどれだけ厳選して使われているか
    2. 共起性 (co-occurrence): 他のマーカーと一緒に使われる割合
    3. 文書横断一貫性 (cross-doc): 複数ノートで同じ語に同じマーカーが使われるか
  を計算し、これらを統合して最適な重みを導出する。

使い方:
  # OCRテキストフォルダから学習
  python learn_marker_weights.py --input-dir data/ocr_texts/

  # 既存のimportance_dataset.jsonlから学習
  python learn_marker_weights.py --dataset data/importance_dataset.jsonl

  # 結果を scorer.py に自動反映
  python learn_marker_weights.py --input-dir data/ocr_texts/ --apply

  # 最小サンプル数を指定 (デフォルト: 50ページ)
  python learn_marker_weights.py --input-dir data/ocr_texts/ --min-pages 100
"""

import argparse
import json
import logging
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# scorer.py と同じマーカーパターン定義
MARKER_PATTERNS = {
    "red":       re.compile(r"\[red\](.*?)\[/red\]"),
    "bold":      re.compile(r"\[bold\](.*?)\[/bold\]"),
    "underline": re.compile(r"\[underline\](.*?)\[/underline\]"),
    "highlight": re.compile(r"\[highlight\](.*?)\[/highlight\]"),
    "box":       re.compile(r"\[box\](.*?)\[/box\]"),
    "star":      re.compile(r"\[star\](.*?)\[/star\]"),
    "bracket":   re.compile(r"【(.*?)】"),
}

# 全マーカーを除去するパターン
STRIP_ALL_MARKERS = re.compile(
    r"\[(red|bold|underline|highlight|box|star)\](.*?)\[/\1\]"
    r"|【(.*?)】"
)


def normalize_term(term: str) -> str:
    cleaned = term.strip()
    cleaned = re.sub(r'^[\s\-・,、。:：;；\(\)\[\]「」『』【】]+', '', cleaned)
    cleaned = re.sub(r'[\s\-・,、。:：;；\(\)\[\]「」『』【】]+$', '', cleaned)
    return cleaned if len(cleaned) >= 2 else ''


@dataclass
class MarkerStats:
    """マーカーごとの統計情報"""
    name: str
    total_uses: int = 0                      # マーカーが使われた総回数
    pages_with_marker: int = 0               # このマーカーが出現したページ数
    unique_terms: set = field(default_factory=set)  # マークされたユニーク語のセット
    co_occurrence: Counter = field(default_factory=Counter)  # 他マーカーとの共起回数
    terms_per_page: list = field(default_factory=list)  # ページごとのマーク語数


@dataclass
class PageStats:
    """1ページ(ファイル)ごとの統計"""
    total_words: int = 0                     # テキスト内の総ワード数
    marker_terms: dict = field(default_factory=dict)  # マーカー名 -> [語のリスト]


def count_words(text: str) -> int:
    """テキスト内の意味のあるワード数をカウント"""
    plain = STRIP_ALL_MARKERS.sub(r"\2\3", text)
    # 日本語: 漢字2文字以上、カタカナ3文字以上  /  英語: 3文字以上
    tokens = re.findall(
        r'[一-龥]{2,}|[ァ-ヴー]{3,}|[A-Za-z]{3,}|[0-9]{3,4}年', plain
    )
    return len(tokens)


def analyze_page(text: str) -> PageStats:
    """1ページ分のテキストを解析"""
    stats = PageStats(total_words=count_words(text))
    for marker_name, pattern in MARKER_PATTERNS.items():
        terms = []
        for m in pattern.finditer(text):
            t = normalize_term(m.group(1) if marker_name != "bracket" else m.group(1))
            if t:
                terms.append(t)
        if terms:
            stats.marker_terms[marker_name] = terms
    return stats


def compute_weights(
    pages: list[PageStats],
    min_pages: int = 50,
) -> dict[str, float]:
    """
    全ページの統計からマーカー重みを算出。

    3つのシグナルを統合:
      S1. 選択性 (selectivity): 1ページあたりのマーク語数が少ないほど厳選 → 高スコア
      S2. 共起性 (co-occurrence): 他のマーカーと共起する割合が高いほど重要
      S3. 文書横断一貫性: 複数ページで同じ語に使われるほど信頼性が高い

    最終重み = normalize(S1 * w1 + S2 * w2 + S3 * w3) → [5.0, 10.0] にスケーリング
    """
    total_pages = len(pages)
    if total_pages < min_pages:
        logger.warning(
            f"データ不足: {total_pages}ページ (最低{min_pages}ページ推奨)。"
            f"現在の重みが最適とは限りません。"
        )

    # --- マーカーごとの統計を集計 ---
    marker_stats: dict[str, MarkerStats] = {
        name: MarkerStats(name=name) for name in MARKER_PATTERNS
    }

    # 各マーカーの語を文書横断で集計
    cross_doc_terms: dict[str, Counter] = defaultdict(Counter)  # marker -> {term: doc_count}

    for page in pages:
        page_markers_present = set(page.marker_terms.keys())
        for marker_name, terms in page.marker_terms.items():
            ms = marker_stats[marker_name]
            ms.total_uses += len(terms)
            ms.pages_with_marker += 1
            ms.unique_terms.update(terms)
            ms.terms_per_page.append(len(terms))

            # 共起: このページで他のどのマーカーと一緒に使われたか
            for other in page_markers_present:
                if other != marker_name:
                    ms.co_occurrence[other] += 1

            # 文書横断
            for t in set(terms):
                cross_doc_terms[marker_name][t] += 1

    # --- 使われているマーカーのみ対象 ---
    active_markers = {
        name: ms for name, ms in marker_stats.items()
        if ms.total_uses > 0
    }
    if not active_markers:
        logger.error("マーカーが一切検出されませんでした。")
        return {}

    # --- S1: 選択性 (少ないほど厳選 → 高スコア) ---
    selectivity = {}
    for name, ms in active_markers.items():
        if ms.pages_with_marker > 0:
            avg_per_page = ms.total_uses / ms.pages_with_marker
            # 逆数: 1ページに1語だけマークされるのが最も選択的
            selectivity[name] = 1.0 / max(avg_per_page, 0.1)
        else:
            selectivity[name] = 0.0

    # --- S2: 共起性 (他マーカーと共起する割合) ---
    co_occ_score = {}
    for name, ms in active_markers.items():
        if ms.pages_with_marker > 0:
            co_occ_count = sum(ms.co_occurrence.values())
            # 共起回数 / 出現ページ数 → 「他のマーカーも一緒に使われるページ」の密度
            co_occ_score[name] = co_occ_count / ms.pages_with_marker
        else:
            co_occ_score[name] = 0.0

    # --- S3: 文書横断一貫性 (同じ語が複数ページでマークされる割合) ---
    cross_doc_score = {}
    for name, ms in active_markers.items():
        term_counts = cross_doc_terms[name]
        if len(ms.unique_terms) > 0:
            # 2ページ以上でマークされた語の割合
            multi_doc = sum(1 for c in term_counts.values() if c >= 2)
            cross_doc_score[name] = multi_doc / len(ms.unique_terms)
        else:
            cross_doc_score[name] = 0.0

    # --- 統合 ---
    raw_scores = {}
    for name in active_markers:
        s1 = selectivity.get(name, 0)
        s2 = co_occ_score.get(name, 0)
        s3 = cross_doc_score.get(name, 0)
        # 重み配分: 選択性50%, 共起性30%, 一貫性20%
        raw_scores[name] = s1 * 0.5 + s2 * 0.3 + s3 * 0.2

    # --- [5.0, 10.0] にスケーリング ---
    if not raw_scores:
        return {}
    min_raw = min(raw_scores.values())
    max_raw = max(raw_scores.values())
    spread = max_raw - min_raw if max_raw != min_raw else 1.0

    weights = {}
    for name, raw in raw_scores.items():
        normalized = (raw - min_raw) / spread  # 0~1
        weights[name] = round(5.0 + normalized * 5.0, 1)  # 5.0~10.0

    return weights


def load_pages_from_dir(input_dir: Path) -> list[PageStats]:
    """OCRテキストフォルダから読み込み"""
    txt_files = sorted(input_dir.rglob("*.txt"))
    if not txt_files:
        raise SystemExit(f"No .txt files found under: {input_dir}")

    pages = []
    for f in txt_files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if text.strip():
            pages.append(analyze_page(text))
    logger.info(f"読み込み: {len(pages)}ページ ({input_dir})")
    return pages


def load_pages_from_dataset(dataset_path: Path) -> list[PageStats]:
    """importance_dataset.jsonl から読み込み"""
    pages = []
    with dataset_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            text = rec.get("text", "")
            if text.strip():
                pages.append(analyze_page(text))
    logger.info(f"読み込み: {len(pages)}レコード ({dataset_path})")
    return pages


def print_report(
    pages: list[PageStats],
    weights: dict[str, float],
    marker_stats: dict[str, MarkerStats] | None = None,
):
    """分析結果レポートを表示"""
    total_pages = len(pages)
    print(f"\n{'='*60}")
    print(f"  マーカー重み学習レポート  ({total_pages} ページ分析)")
    print(f"{'='*60}\n")

    # マーカーごとの詳細統計 (再集計)
    stats: dict[str, MarkerStats] = {name: MarkerStats(name=name) for name in MARKER_PATTERNS}
    for page in pages:
        for marker_name, terms in page.marker_terms.items():
            ms = stats[marker_name]
            ms.total_uses += len(terms)
            ms.pages_with_marker += 1
            ms.unique_terms.update(terms)
            ms.terms_per_page.append(len(terms))

    active = {n: s for n, s in stats.items() if s.total_uses > 0}

    print(f"{'マーカー':<12} {'使用回数':>8} {'出現ページ':>10} {'平均/ページ':>10} {'ユニーク語':>10} {'学習重み':>8}")
    print("-" * 70)

    # 重みの降順でソート
    sorted_markers = sorted(weights.items(), key=lambda x: -x[1])
    for name, w in sorted_markers:
        ms = active.get(name)
        if ms:
            avg = ms.total_uses / ms.pages_with_marker if ms.pages_with_marker else 0
            print(f"  {name:<10} {ms.total_uses:>8} {ms.pages_with_marker:>10} {avg:>10.1f} {len(ms.unique_terms):>10} {w:>8.1f}")
        else:
            print(f"  {name:<10} {'(未検出)':>8} {'-':>10} {'-':>10} {'-':>10} {w:>8.1f}")

    # 使われていないマーカー
    unused = [n for n in MARKER_PATTERNS if n not in weights]
    if unused:
        print(f"\n  未使用マーカー: {', '.join(unused)}")

    print(f"\n{'='*60}")
    print("  導出された重み (scorer.py の VISUAL_MARKERS 用)")
    print(f"{'='*60}")
    for name, w in sorted_markers:
        print(f"  {name}: {w}")
    print()


def apply_weights_to_scorer(weights: dict[str, float]):
    """scorer.py の VISUAL_MARKERS に学習した重みを反映"""
    scorer_path = Path(__file__).parent / "note_importance" / "scorer.py"
    if not scorer_path.exists():
        logger.error(f"scorer.py が見つかりません: {scorer_path}")
        return False

    content = scorer_path.read_text(encoding="utf-8")

    for name, new_weight in weights.items():
        # "name": {"pattern": ..., "weight": XX.X} の XX.X を置換
        pattern = re.compile(
            rf'("{name}"\s*:\s*\{{"pattern":\s*r"[^"]+",\s*"weight":\s*)([0-9]+\.?[0-9]*)'
        )
        content, count = pattern.subn(rf'\g<1>{new_weight}', content)
        if count:
            logger.info(f"  {name}: weight → {new_weight}")
        else:
            logger.warning(f"  {name}: scorer.py 内にパターンが見つからず、スキップ")

    # コメント更新
    content = content.replace(
        "# 重み = 視覚コントラスト (周囲との際立ち度) が高いほど大きい",
        "# 重み = データ学習済み (learn_marker_weights.py で自動算出)"
    )

    scorer_path.write_text(content, encoding="utf-8")
    logger.info(f"scorer.py を更新しました: {scorer_path}")
    return True


def save_report_json(
    pages: list[PageStats],
    weights: dict[str, float],
    output_path: Path,
):
    """分析結果をJSONで保存"""
    stats: dict[str, dict] = {}
    for page in pages:
        for marker_name, terms in page.marker_terms.items():
            if marker_name not in stats:
                stats[marker_name] = {
                    "total_uses": 0,
                    "pages_with_marker": 0,
                    "unique_terms_count": 0,
                    "unique_terms_sample": [],
                }
            stats[marker_name]["total_uses"] += len(terms)
            stats[marker_name]["pages_with_marker"] += 1

    # ユニーク語は再集計
    unique_sets: dict[str, set] = defaultdict(set)
    for page in pages:
        for marker_name, terms in page.marker_terms.items():
            unique_sets[marker_name].update(terms)
    for name in stats:
        stats[name]["unique_terms_count"] = len(unique_sets[name])
        stats[name]["unique_terms_sample"] = sorted(unique_sets[name])[:20]

    report = {
        "total_pages": len(pages),
        "learned_weights": weights,
        "marker_statistics": stats,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"レポート保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="OCRノートデータからマーカー重みを統計的に学習"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input-dir", type=str, help="OCRテキストフォルダ")
    group.add_argument("--dataset", type=str, help="importance_dataset.jsonl パス")
    parser.add_argument("--min-pages", type=int, default=50,
                        help="最低ページ数 (少ないと警告)")
    parser.add_argument("--apply", action="store_true",
                        help="結果を scorer.py に自動反映")
    parser.add_argument("--report", type=str, default="data/weight_learning_report.json",
                        help="レポートJSON出力先")
    args = parser.parse_args()

    # データ読み込み
    if args.input_dir:
        pages = load_pages_from_dir(Path(args.input_dir))
    else:
        pages = load_pages_from_dataset(Path(args.dataset))

    if not pages:
        raise SystemExit("読み込めるデータがありませんでした。")

    # 重み算出
    weights = compute_weights(pages, min_pages=args.min_pages)
    if not weights:
        raise SystemExit("マーカーが検出されず、重みを算出できませんでした。")

    # レポート表示
    print_report(pages, weights)

    # レポートJSON保存
    save_report_json(pages, weights, Path(args.report))

    # scorer.py に反映
    if args.apply:
        logger.info("scorer.py に重みを反映中...")
        apply_weights_to_scorer(weights)
        print("\n✓ scorer.py を更新しました。git diff で確認してください。")
    else:
        print("ヒント: --apply を付けると scorer.py に自動反映されます。")


if __name__ == "__main__":
    main()
