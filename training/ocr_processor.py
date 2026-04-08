#!/usr/bin/env python3
"""
ノート画像 OCR プロセッサ (完全ローカル)

Qwen2.5-VL を使ってノート写真をテキスト化し、
視覚マーカー付きでスコアリングデータセットに変換する。

クラウドAPI不要。GPU上でローカル実行。
Linux / Windows 両対応。

使い方:
  # 単体テスト (デフォルト: 7B)
  python ocr_processor.py --image note.jpg

  # 自宅PC (4060 Ti 16GB) → 3B モデル
  python ocr_processor.py --image note.jpg --model Qwen/Qwen2.5-VL-3B-Instruct

  # フォルダ一括
  python ocr_processor.py --input-dir ./notebook_photos/ --output data/ocr_texts/

モデル選択:
  --model Qwen/Qwen2.5-VL-7B-Instruct   (デフォルト, 4080 16GB推奨)
  --model Qwen/Qwen2.5-VL-3B-Instruct   (4060 Ti 16GB OK)
"""

import argparse
import logging
from pathlib import Path

import torch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 対応画像形式
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tiff"}

DEFAULT_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"

OCR_PROMPT = """この画像に含まれるテキストをすべて正確に書き起こしてください。

ルール:
・改行や段落構造をそのまま保つ
・縦書きは上→下、右→左の順序で読む
・横書きは上→下、左→右の順序で読む
・見出し、本文、注釈、キャプションをすべて含める
・手書き文字も可能な限り正確に読み取る
・一部の語句だけが下線・太字・マーカー・色付き（赤字・青字等）で強調されている場合、その語句を【】で囲む（例: 【重要語句】）
・さらに、視覚的な強調の種類に応じてタグを付ける:
  赤字 → [red]文字[/red]
  太字 → [bold]文字[/bold]
  下線 → [underline]文字[/underline]
  蛍光ペン → [highlight]文字[/highlight]
  枠囲み → [box]文字[/box]
  ★マーク付き → [star]文字[/star]
・ただし文章全体が同じ色やスタイルの場合は強調ではないのでタグを付けない
・透かし、ページ番号、装飾は無視する
・テキストのみを出力し、説明や補足は一切書かない"""


class NotebookOCR:
    """Qwen2.5-VL を使ったローカル OCR

    モデルは初回呼び出し時にロードされ、以降は使い回す。
    """

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self.model = None
        self.processor = None

    def _load(self):
        """モデルとプロセッサをロード (遅延初期化)"""
        if self.model is not None:
            return

        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor

        logger.info(f"モデルをロード中: {self.model_name}")

        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model_name,
            torch_dtype=torch.bfloat16,
            device_map="auto",
        )

        self.processor = AutoProcessor.from_pretrained(
            self.model_name,
            min_pixels=256 * 28 * 28,
            max_pixels=1280 * 28 * 28,
        )

        logger.info(f"モデルロード完了: {self.model_name}")

    def extract_text(self, image_path: str) -> str:
        """画像からテキストを抽出

        Args:
            image_path: 画像ファイルのパス

        Returns:
            抽出されたテキスト (失敗時は空文字)
        """
        self._load()

        try:
            from qwen_vl_utils import process_vision_info

            # file:// URI に変換 (Qwen VL Utils の形式)
            abs_path = str(Path(image_path).resolve())
            image_uri = f"file://{abs_path}"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image_uri},
                        {"type": "text", "text": OCR_PROMPT},
                    ],
                }
            ]

            text_input = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            image_inputs, video_inputs = process_vision_info(messages)
            inputs = self.processor(
                text=[text_input],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            ).to(self.model.device)

            with torch.no_grad():
                generated_ids = self.model.generate(**inputs, max_new_tokens=2048)

            generated_ids_trimmed = [
                out_ids[len(in_ids):]
                for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output = self.processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]

            if output:
                logger.info(f"OCR成功: {Path(image_path).name} → {len(output)}文字")
            return output

        except Exception as e:
            logger.error(f"OCR エラー ({image_path}): {e}", exc_info=True)
            return ""


# グローバルインスタンス (Gradio UI等から使い回す用)
_default_ocr = None


def get_ocr(model_name: str = DEFAULT_MODEL) -> NotebookOCR:
    """シングルトン OCR インスタンスを取得"""
    global _default_ocr
    if _default_ocr is None or _default_ocr.model_name != model_name:
        _default_ocr = NotebookOCR(model_name)
    return _default_ocr


def extract_text_from_image(image_path: str, model_name: str = DEFAULT_MODEL) -> str:
    """画像からテキストを抽出 (便利関数)"""
    ocr = get_ocr(model_name)
    return ocr.extract_text(image_path)


def process_folder(input_dir: str, output_dir: str, model_name: str = DEFAULT_MODEL) -> list[dict]:
    """フォルダ内の画像を一括 OCR → テキストファイルとして保存

    Returns:
        処理結果のリスト [{"file": ..., "chars": ..., "status": ...}, ...]
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ocr = get_ocr(model_name)

    image_files = sorted(
        f for f in input_path.iterdir()
        if f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not image_files:
        logger.warning(f"画像が見つかりません: {input_dir}")
        return []

    results = []
    for img_file in image_files:
        text = ocr.extract_text(str(img_file))
        status = "ok" if text else "failed"

        if text:
            out_file = output_path / f"{img_file.stem}.txt"
            out_file.write_text(text, encoding="utf-8")

        results.append({
            "file": img_file.name,
            "chars": len(text),
            "status": status,
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="ノート画像 → OCR テキスト変換 (ローカルLLM)")
    parser.add_argument("--image", help="単一画像ファイル")
    parser.add_argument("--input-dir", help="画像フォルダ (一括処理)")
    parser.add_argument("--output", default="data/ocr_texts", help="出力先ディレクトリ")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help="VLMモデル名 (デフォルト: Qwen2.5-VL-7B, 軽量: Qwen/Qwen2.5-VL-3B-Instruct)",
    )
    args = parser.parse_args()

    if args.image:
        text = extract_text_from_image(args.image, model_name=args.model)
        if text:
            print(text)
        else:
            print("OCR失敗")
    elif args.input_dir:
        results = process_folder(args.input_dir, args.output, model_name=args.model)
        ok = sum(1 for r in results if r["status"] == "ok")
        print(f"処理完了: {ok}/{len(results)} 成功")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
