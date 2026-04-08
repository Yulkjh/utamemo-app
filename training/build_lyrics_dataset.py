#!/usr/bin/env python3
"""
エグスプロージョン「本能寺の変」スタイルの歌詞学習データ生成

既存の学習データを「本能寺の変」風のスタイルに変換・拡張する。
歌詞の特徴:
  - 学習内容をリズミカルに歌詞化
  - 韻を踏む (ラップ的要素)
  - ダジャレ・語呂合わせ
  - 繰り返しサビで覚えやすく
  - メタ的表現 (「覚えよう」等) は使わない → 内容そのものを歌詞に

使い方:
  # 既存のscorer結果をベースに歌詞学習データ生成
  python build_lyrics_dataset.py --input data/importance_results.jsonl --output data/lyrics_honnou_style.json

  # テンプレートベースでサンプル生成 (APIなし)
  python build_lyrics_dataset.py --template --output data/lyrics_style_samples.json

  # Gemini APIでスタイル変換 (大量生成)
  python build_lyrics_dataset.py --input data/importance_results.jsonl --use-gemini --output data/lyrics_gemini.json
"""

import argparse
import json
import logging
import os
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =========================================================================
# 本能寺の変スタイル テンプレート
# =========================================================================

HONNOU_STYLE_EXAMPLES = [
    {
        "input_text": "1582年、本能寺の変。織田信長は家臣の明智光秀に討たれた。信長は天下統一を目前にしていた。",
        "genre": "hip-hop",
        "keywords": ["1582年", "本能寺の変", "織田信長", "明智光秀", "天下統一"],
        "lyrics": (
            "1582 本能寺 炎が上がる夜\n"
            "信長ステージ 天下統一 あと一歩のところ\n"
            "光秀 裏切りの一手 歴史が動く\n"
            "「敵は本能寺にあり」 その声が轟く\n\n"
            "燃える本能寺 (本能寺!)\n"
            "信長の夢が (夢が!)\n"
            "1582 覚えとけ\n"
            "光秀のリベリオン\n\n"
            "明智光秀 三日天下の男\n"
            "秀吉 中国大返し 怒涛のカウンター\n"
            "山崎の戦い 光秀 散る\n"
            "天下の行方 次のステージへ"
        ),
    },
    {
        "input_text": "光合成は植物が光エネルギーを使って二酸化炭素と水からグルコースと酸素を作る反応。葉緑体で行われる。化学式: 6CO2 + 6H2O → C6H12O6 + 6O2",
        "genre": "pop",
        "keywords": ["光合成", "光エネルギー", "二酸化炭素", "グルコース", "葉緑体", "6CO2"],
        "lyrics": (
            "太陽の光 キャッチして (キャッチ!)\n"
            "葉緑体が フル回転\n"
            "CO2と水を ミックスして\n"
            "グルコース 作るぜ エナジー全開\n\n"
            "光合成! 光合成!\n"
            "6CO2 + 6H2O\n"
            "C6H12O6 + 6O2\n"
            "酸素も出すよ ありがとう植物\n\n"
            "葉っぱの中の 小さな工場\n"
            "葉緑体が 頑張ってる\n"
            "光のエネルギー 化学に変換\n"
            "それが光合成 生命のエンジン"
        ),
    },
    {
        "input_text": "英単語: abandon (放棄する), abstract (抽象的な), accommodate (収容する), acknowledge (認める)",
        "genre": "pop",
        "keywords": ["abandon", "abstract", "accommodate", "acknowledge"],
        "lyrics": (
            "abandon 捨てろ 古い自分を\n"
            "放棄して 新しいステージへ\n"
            "abstract 抽象的な 夢の形\n"
            "具体化するのは 君次第\n\n"
            "accommodate 収容する 全部受け入れろ\n"
            "acknowledge 認めよう 今の現実\n\n"
            "A から始まる 4つの言葉\n"
            "abandon abstract\n"
            "accommodate acknowledge\n"
            "リズムに乗せて 頭に入れろ"
        ),
    },
]


SYSTEM_PROMPT_HONNOU = (
    "あなたはエグスプロージョン「本能寺の変」スタイルで学習用歌詞を作る専門AIです。\n"
    "ルール:\n"
    "1. 学習テキストのキーワード・年号・公式は必ず正確に歌詞に組み込む\n"
    "2. リズミカルで韻を踏む (ラップ・ヒップホップ的要素OK)\n"
    "3. 繰り返しのサビを作り覚えやすくする\n"
    "4. 合いの手・掛け声を入れる (例: (本能寺!) (Yeah!) )\n"
    "5. ダジャレ・語呂合わせを積極的に使う\n"
    "6. 「覚えよう」「暗記しよう」等のメタ的表現は禁止\n"
    "7. 「全てが大事」「忘れずに」等の励ましフレーズも禁止\n"
    "8. 内容そのものを面白く歌詞にする\n"
)


def build_training_record(example: dict) -> dict:
    """例データを学習レコードに変換"""
    user_prompt = (
        f"以下の学習テキストを{example['genre']}ジャンルの歌詞にしてください。\n"
        f"重要キーワード: {', '.join(example['keywords'])}\n\n"
        f"学習テキスト:\n{example['input_text']}"
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_HONNOU},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": example["lyrics"]},
        ]
    }


def generate_template_dataset(output_path: str):
    """テンプレートからサンプル学習データを生成"""
    records = [build_training_record(ex) for ex in HONNOU_STYLE_EXAMPLES]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    logger.info(f"テンプレートデータ {len(records)}件を保存: {output_path}")


def convert_importance_to_lyrics_data(input_path: str, output_path: str, genres: list[str] = None):
    """
    重要度スコアリング結果(JSONL) → 歌詞学習用データのシード(JSON)に変換。
    これを元にGemini APIかローカルLLMで歌詞を生成→手動で品質チェック→学習データ化。
    """
    if genres is None:
        genres = ["pop", "hip-hop", "rock", "EDM"]

    seeds = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            text = data.get("text", "")[:1500]
            keywords_raw = data.get("keywords", [])
            keywords = [k["term"] for k in keywords_raw[:10] if k.get("final_score", 0) > 0.3]

            if len(keywords) < 3:
                continue

            for genre in genres:
                seeds.append({
                    "input_text": text,
                    "genre": genre,
                    "keywords": keywords,
                    "source_file": data.get("source_file", f"line_{line_no}"),
                    "lyrics": "",  # ← ここを手動 or APIで埋める
                })

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(seeds, f, ensure_ascii=False, indent=2)
    logger.info(f"歌詞データシード {len(seeds)}件を保存: {output_path}")
    logger.info("次のステップ: 'lyrics'フィールドを手動 or Gemini APIで埋めてください")


def generate_with_gemini(input_path: str, output_path: str, api_key: str = None):
    """Gemini APIで歌詞生成してデータセットを拡充"""
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEYが必要です (環境変数 or --gemini-key)")

    try:
        import google.generativeai as genai
    except ImportError:
        raise SystemExit("pip install google-generativeai")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    with open(input_path, "r", encoding="utf-8") as f:
        seeds = json.loads(f.read())

    completed = []
    for i, seed in enumerate(seeds):
        if seed.get("lyrics"):
            completed.append(seed)
            continue

        prompt = (
            f"{SYSTEM_PROMPT_HONNOU}\n\n"
            f"以下の学習テキストを{seed['genre']}ジャンルの歌詞にしてください。\n"
            f"重要キーワード: {', '.join(seed['keywords'])}\n\n"
            f"学習テキスト:\n{seed['input_text']}"
        )

        try:
            response = model.generate_content(prompt)
            seed["lyrics"] = response.text
            completed.append(seed)
            logger.info(f"[{i+1}/{len(seeds)}] 歌詞生成完了 ({seed['genre']})")
        except Exception as e:
            logger.warning(f"[{i+1}/{len(seeds)}] 生成失敗: {e}")

    # 学習データ形式に変換
    records = []
    for seed in completed:
        if seed.get("lyrics"):
            records.append(build_training_record(seed))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    logger.info(f"学習データ {len(records)}件を保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="本能寺の変スタイル歌詞学習データ生成")
    parser.add_argument("--input", type=str, help="入力 (重要度JSONL or 歌詞シードJSON)")
    parser.add_argument("--output", type=str, required=True, help="出力JSONファイル")
    parser.add_argument("--template", action="store_true", help="テンプレートサンプルのみ生成")
    parser.add_argument("--use-gemini", action="store_true", help="Gemini APIで歌詞を生成")
    parser.add_argument("--gemini-key", type=str, help="Gemini APIキー")
    args = parser.parse_args()

    if args.template:
        generate_template_dataset(args.output)
    elif args.use_gemini:
        if not args.input:
            parser.error("--use-gemini には --input (歌詞シードJSON) が必要")
        generate_with_gemini(args.input, args.output, api_key=args.gemini_key)
    elif args.input:
        convert_importance_to_lyrics_data(args.input, args.output)
    else:
        parser.error("--input, --template, --use-gemini のいずれかを指定")


if __name__ == "__main__":
    main()
