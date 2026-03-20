#!/usr/bin/env python3
"""
UTAMEMOの既存歌詞データをLoRA学習用JSONに変換するスクリプト

使い方:
  cd myproject
  python manage.py shell < ../training/export_training_data.py

出力: training/data/lyrics_training_data.json
"""
import json
import os
import sys

# Django設定を読み込み
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

import django
django.setup()

from songs.models import Song, Lyrics


def export_training_data():
    """DBから歌詞データを抽出してLoRA学習用フォーマットに変換"""

    output_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(output_dir, exist_ok=True)

    training_data = []
    skipped = 0

    # 歌詞が存在する曲を全件取得
    songs = Song.objects.filter(
        lyrics__isnull=False
    ).select_related('lyrics').all()

    for song in songs:
        lyrics = song.lyrics
        content = (lyrics.content or '').strip()
        original_text = (lyrics.original_text or '').strip()

        # 歌詞が短すぎるものはスキップ
        if len(content) < 50:
            skipped += 1
            continue

        # [Verse] [Chorus] などの構造がないものはスキップ
        if '[' not in content:
            skipped += 1
            continue

        # ジャンル情報
        genre = song.genre or 'pop'

        # 学習データエントリを作成
        if original_text and len(original_text) > 10:
            # 元テキストがある場合: テキスト → 歌詞 の変換を学習
            instruction = (
                f"あなたは暗記学習用の歌詞作成の専門家です。"
                f"以下の学習テキストから{genre}ジャンルの歌詞を作成してください。\n"
                f"韻を踏み、キャッチーで覚えやすい歌詞にしてください。\n"
                f"重要な用語・人物名・年号は必ず歌詞に含めてください。\n"
                f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。"
            )
            entry = {
                "instruction": instruction,
                "input": original_text,
                "output": content
            }
        else:
            # 元テキストがない場合: タイトル+ジャンルから歌詞生成を学習
            instruction = (
                f"あなたは暗記学習用の歌詞作成の専門家です。"
                f"「{song.title}」というタイトルで{genre}ジャンルの学習ソングの歌詞を作成してください。\n"
                f"韻を踏み、キャッチーで覚えやすい歌詞にしてください。\n"
                f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。"
            )
            entry = {
                "instruction": instruction,
                "input": "",
                "output": content
            }

        training_data.append(entry)

    # 出力
    output_path = os.path.join(output_dir, 'lyrics_training_data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(training_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 学習データ生成完了!")
    print(f"   - 有効データ: {len(training_data)} 件")
    print(f"   - スキップ: {skipped} 件")
    print(f"   - 出力先: {output_path}")

    # 統計情報
    if training_data:
        with_input = sum(1 for d in training_data if d['input'])
        without_input = len(training_data) - with_input
        avg_output_len = sum(len(d['output']) for d in training_data) / len(training_data)
        print(f"   - 元テキストあり: {with_input} 件")
        print(f"   - 元テキストなし: {without_input} 件")
        print(f"   - 平均歌詞長: {avg_output_len:.0f} 文字")

    return training_data


if __name__ == '__main__':
    export_training_data()
