#!/usr/bin/env python3
"""
UTAMEMO 学習データ品質チェッカー

Gemini APIを使って生成済みの学習データを評価し、
品質レポートを出力する。定期実行で品質を監視。

使い方:
  python quality_check.py --gemini-key YOUR_KEY
  python quality_check.py --gemini-key YOUR_KEY --sample 10 --recent
  python quality_check.py --gemini-key YOUR_KEY --full-report
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


EVALUATION_PROMPT = """あなたは暗記用歌詞データの品質評価AIです。
以下の学習データ（学習テキスト→歌詞）を5つの基準で評価してください。

## 学習テキスト:
{input_text}

## 生成された歌詞:
{output_text}

## 評価基準 (各10点満点):

1. **キーワード網羅率**: 学習テキストの重要用語（人名・年号・公式・地名等）が歌詞に含まれているか
2. **構造**: [Verse 1], [Chorus], [Verse 2] 等のセクション構成は適切か。2セクション以上あるか
3. **キャッチーさ**: 韻を踏んでいるか、リズム感があるか、覚えやすいか、合いの手があるか
4. **正確性**: 事実・年号・公式が正確に含まれているか（捏造がないか）
5. **スタイル**: エグスプロージョン「本能寺の変」のようなユーモアと教育性のバランスがあるか

JSON形式のみで出力してください（JSON以外は出力しないでください）:
{{
  "keyword_coverage": {{"score": 0, "found": ["見つかったキーワード"], "missing": ["不足しているキーワード"]}},
  "structure": {{"score": 0, "comment": "構造への短いコメント"}},
  "catchiness": {{"score": 0, "comment": "キャッチーさへの短いコメント"}},
  "accuracy": {{"score": 0, "issues": ["問題があれば記述"]}},
  "style": {{"score": 0, "comment": "スタイルへの短いコメント"}},
  "overall_score": 0,
  "grade": "S/A/B/C/D",
  "improvements": ["具体的な改善提案1", "具体的な改善提案2"]
}}

gradeの基準: S(45-50), A(38-44), B(30-37), C(20-29), D(0-19)"""


SUMMARY_PROMPT = """以下は{count}件の暗記用歌詞データの品質評価結果です。

{results_json}

全体の傾向を分析し、Gemini APIの生成プロンプトを改善するための具体的な提案をしてください。

JSON形式のみで出力してください:
{{
  "average_scores": {{
    "keyword_coverage": 0.0,
    "structure": 0.0,
    "catchiness": 0.0,
    "accuracy": 0.0,
    "style": 0.0,
    "overall": 0.0
  }},
  "grade_distribution": {{"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}},
  "common_issues": ["よく見られる問題1", "問題2"],
  "strengths": ["良い点1", "良い点2"],
  "prompt_improvements": [
    {{
      "target": "改善対象（例: instructionテンプレート）",
      "current_issue": "現在の問題",
      "suggestion": "具体的な改善案"
    }}
  ],
  "recommended_actions": ["次にやるべきこと1", "次にやるべきこと2"]
}}"""


def load_training_data(data_path):
    """学習データを読み込む"""
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_record(model, record, index, total, request_options):
    """1件のレコードを評価"""
    input_text = record.get("input", "")
    output_text = record.get("output", "")

    prompt = EVALUATION_PROMPT.format(
        input_text=input_text,
        output_text=output_text,
    )

    try:
        response = model.generate_content(prompt, request_options=request_options)
        text = response.text.strip()

        # JSON部分を抽出
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        result = json.loads(text)

        overall = result.get("overall_score", 0)
        grade = result.get("grade", "?")
        theme = input_text[:40]
        logger.info(f"  [{index+1}/{total}] {grade} ({overall}/50) - {theme}...")
        return result

    except json.JSONDecodeError as e:
        logger.warning(f"  [{index+1}/{total}] JSON解析失敗: {e}")
        return None
    except Exception as e:
        logger.warning(f"  [{index+1}/{total}] 評価失敗: {e}")
        return None


def generate_summary(model, results, request_options):
    """全体サマリーを生成"""
    # 結果を簡略化して送信（トークン削減）
    simplified = []
    for r in results:
        simplified.append({
            "keyword_coverage": r["keyword_coverage"]["score"],
            "structure": r["structure"]["score"],
            "catchiness": r["catchiness"]["score"],
            "accuracy": r["accuracy"]["score"],
            "style": r["style"]["score"],
            "overall": r["overall_score"],
            "grade": r["grade"],
            "improvements": r.get("improvements", []),
        })

    prompt = SUMMARY_PROMPT.format(
        count=len(results),
        results_json=json.dumps(simplified, ensure_ascii=False, indent=2),
    )

    try:
        response = model.generate_content(prompt, request_options=request_options)
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        logger.warning(f"サマリー生成失敗: {e}")
        return None


def print_report(results, summary, output_path=None):
    """レポートを出力"""
    report_lines = []

    def p(line=""):
        report_lines.append(line)
        print(line)

    p("=" * 60)
    p("  UTAMEMO 学習データ品質レポート")
    p(f"  生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    p(f"  評価件数: {len(results)}件")
    p("=" * 60)

    if summary:
        avg = summary.get("average_scores", {})
        p("")
        p("--- 平均スコア (各10点満点) ---")
        p(f"  キーワード網羅率: {avg.get('keyword_coverage', 0):.1f}")
        p(f"  構造:             {avg.get('structure', 0):.1f}")
        p(f"  キャッチーさ:     {avg.get('catchiness', 0):.1f}")
        p(f"  正確性:           {avg.get('accuracy', 0):.1f}")
        p(f"  スタイル:         {avg.get('style', 0):.1f}")
        p(f"  総合:             {avg.get('overall', 0):.1f} / 50")

        dist = summary.get("grade_distribution", {})
        p("")
        p("--- グレード分布 ---")
        for grade in ["S", "A", "B", "C", "D"]:
            count = dist.get(grade, 0)
            bar = "█" * count
            p(f"  {grade}: {bar} ({count})")

        p("")
        p("--- よくある問題 ---")
        for issue in summary.get("common_issues", []):
            p(f"  ・{issue}")

        p("")
        p("--- 良い点 ---")
        for s in summary.get("strengths", []):
            p(f"  ・{s}")

        p("")
        p("--- プロンプト改善提案 ---")
        for imp in summary.get("prompt_improvements", []):
            p(f"  [{imp.get('target', '?')}]")
            p(f"    問題: {imp.get('current_issue', '')}")
            p(f"    提案: {imp.get('suggestion', '')}")

        p("")
        p("--- 推奨アクション ---")
        for action in summary.get("recommended_actions", []):
            p(f"  → {action}")

    p("")
    p("=" * 60)

    # ファイルに保存
    if output_path:
        report_data = {
            "generated_at": datetime.now().isoformat(),
            "record_count": len(results),
            "individual_results": results,
            "summary": summary,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        p(f"詳細レポート保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="UTAMEMO 学習データ品質チェッカー")
    parser.add_argument("--gemini-key", type=str, default=os.getenv("GEMINI_API_KEY"),
                        help="Gemini APIキー")

    script_dir = Path(__file__).resolve().parent
    default_data = script_dir / "data" / "lyrics_training_data.json"
    parser.add_argument("--data-path", type=str, default=str(default_data),
                        help="学習データパス")

    parser.add_argument("--sample", type=int, default=10,
                        help="評価するサンプル数 (デフォルト: 10)")
    parser.add_argument("--recent", action="store_true",
                        help="最新のレコードを優先的に評価")
    parser.add_argument("--full-report", action="store_true",
                        help="全件評価 (時間とAPIコストに注意)")

    default_output = script_dir / "data" / "quality_report.json"
    parser.add_argument("--output", type=str, default=str(default_output),
                        help="レポート出力先")

    args = parser.parse_args()

    if not args.gemini_key:
        logger.error("Gemini APIキーが必要です (--gemini-key or GEMINI_API_KEY)")
        sys.exit(1)

    # Gemini初期化
    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("pip install google-generativeai が必要です")
        sys.exit(1)

    genai.configure(api_key=args.gemini_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    request_options = {"timeout": 90}

    # データ読み込み
    data = load_training_data(args.data_path)
    logger.info(f"学習データ: {len(data)}件")

    # サンプル抽出
    if args.full_report:
        sample = data
    elif args.recent:
        sample = data[-args.sample:]
    else:
        import random
        sample = random.sample(data, min(args.sample, len(data)))

    logger.info(f"評価対象: {len(sample)}件")
    logger.info("")

    # 各レコードを評価
    results = []
    for i, record in enumerate(sample):
        result = evaluate_record(model, record, i, len(sample), request_options)
        if result:
            results.append(result)
        time.sleep(1)  # レート制限対策

    logger.info("")
    logger.info(f"評価完了: {len(results)}/{len(sample)}件成功")

    # サマリー生成
    summary = None
    if len(results) >= 3:
        logger.info("全体サマリーを生成中...")
        summary = generate_summary(model, results, request_options)

    # レポート出力
    print_report(results, summary, output_path=args.output)


if __name__ == "__main__":
    main()
