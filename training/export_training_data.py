#!/usr/bin/env python3
"""
UTAMEMOの既存歌詞データをLoRA学習用JSONに変換するスクリプト

使い方:
  cd myproject
  python manage.py shell < ../training/export_training_data.py

出力: training/data/lyrics_training_data.json

データの流れ:
  ユーザーがノート(コクヨ等)の写真を撮影
  → OCR(Gemini Vision)でテキスト抽出 → Lyrics.original_text
  → Gemini Textで歌詞生成 → Lyrics.content
  → このスクリプトで (original_text → content) のペアを学習データとして抽出
  → LoRAでLlama 3に「ノートテキスト→暗記歌詞」の変換能力を学習させる

コクヨデータの活用:
  コクヨ社のノート(CamiApp等)から取り込んだデータは original_text に保存されている。
  ノートデータの特徴（箇条書き・図表説明・要点まとめ）を含む学習ペアを
  重点的に抽出することで、ノート特有の構造に対応した歌詞生成を学習できる。
"""
import json
import os
import re
import sys

# Django設定を読み込み
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

import django
django.setup()

from songs.models import Song, Lyrics


def classify_source_type(original_text):
    """元テキストの種類を分類（ノートデータの構造分析）
    
    コクヨのノートデータの特徴:
    - 箇条書き（・、１、(1)、① 等）
    - 要点まとめ形式
    - 図表の説明
    - 見出し+本文の構造
    
    Returns: 'note' (ノート構造), 'textbook' (教科書的), 'plain' (その他)
    """
    if not original_text:
        return 'plain'
    
    lines = original_text.strip().split('\n')
    
    # 箇条書き・番号付きリストの割合
    bullet_patterns = re.compile(r'^[\s]*[・●○▪■□◆◇▸▹►▻➤→⇒\-\*]|^[\s]*[\d①②③④⑤⑥⑦⑧⑨⑩]+[\.、\)）]|^[\s]*[\(（][\d]+[\)）]')
    bullet_count = sum(1 for line in lines if bullet_patterns.match(line))
    
    # 見出しっぽい行（短い行+長い行のパターン）
    short_lines = sum(1 for line in lines if 0 < len(line.strip()) <= 15)
    
    total_lines = max(len([l for l in lines if l.strip()]), 1)
    bullet_ratio = bullet_count / total_lines
    short_ratio = short_lines / total_lines
    
    if bullet_ratio > 0.3 or short_ratio > 0.4:
        return 'note'  # ノート構造（箇条書き・見出し多い）
    elif len(original_text) > 300:
        return 'textbook'  # 教科書的（長文）
    else:
        return 'plain'


def assess_quality(content, original_text):
    """学習データの品質スコアを計算 (0.0 - 1.0)
    
    高品質データの条件:
    1. 歌詞にセクションラベルが正しくある
    2. 元テキストの重要語が歌詞に含まれている
    3. 適切な長さがある
    4. 繰り返し構造（Chorus）がある
    """
    score = 0.0
    
    # セクションラベルの質
    sections = re.findall(r'\[(Verse|Chorus|Bridge|Intro|Outro|Hook)', content)
    if len(sections) >= 4:
        score += 0.3  # 十分な構造
    elif len(sections) >= 2:
        score += 0.15
    
    # Chorusの繰り返し（暗記に重要）
    chorus_count = content.count('[Chorus]')
    if chorus_count >= 2:
        score += 0.2  # Chorus繰り返しあり（暗記効果高い）
    elif chorus_count >= 1:
        score += 0.1
    
    # 歌詞の長さ
    content_len = len(content)
    if 400 <= content_len <= 2000:
        score += 0.2  # 適切な長さ
    elif 200 <= content_len < 400:
        score += 0.1
    
    # 元テキストの重要語が歌詞に含まれているか
    if original_text:
        # 元テキストからカタカナ語・漢字語・数字を抽出
        keywords = set(re.findall(r'[\u4e00-\u9fff]{2,}|[\u30a0-\u30ff]{3,}|\d{2,}', original_text))
        if keywords:
            found = sum(1 for kw in keywords if kw in content)
            keyword_ratio = found / len(keywords)
            score += min(keyword_ratio * 0.3, 0.3)  # 重要語の含有率
    
    return min(score, 1.0)


def export_training_data():
    """DBから歌詞データを抽出してLoRA学習用フォーマットに変換"""

    output_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(output_dir, exist_ok=True)

    training_data = []
    skipped = 0
    quality_stats = {'high': 0, 'medium': 0, 'low': 0}
    source_stats = {'note': 0, 'textbook': 0, 'plain': 0}

    # 歌詞が存在する曲を全件取得（タグ情報も含む）
    songs = Song.objects.filter(
        lyrics__isnull=False
    ).select_related('lyrics').prefetch_related('tags').all()

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
        
        # タグ情報（教科・トピック等）
        tags = list(song.tags.values_list('name', flat=True))
        
        # 元テキストの構造分類
        source_type = classify_source_type(original_text)
        source_stats[source_type] += 1
        
        # 品質スコア
        quality = assess_quality(content, original_text)

        # 学習データエントリを作成
        if original_text and len(original_text) > 10:
            # 元テキストがある場合: テキスト → 歌詞 の変換を学習
            # タグ情報があれば教科名を付加（ノート構造の文脈を与える）
            tag_hint = ""
            if tags:
                tag_hint = f"（教科/トピック: {', '.join(tags[:3])}）\n"
            
            # ノートデータの場合、ノート構造であることを明示
            note_hint = ""
            if source_type == 'note':
                note_hint = "このテキストはノートの要点まとめです。箇条書きや見出し構造に注意して歌詞に変換してください。\n"
            
            instruction = (
                f"あなたは暗記学習用の歌詞作成の専門家です。"
                f"以下の学習テキストから{genre}ジャンルの歌詞を作成してください。\n"
                f"{tag_hint}"
                f"{note_hint}"
                f"韻を踏み、キャッチーで覚えやすい歌詞にしてください。\n"
                f"重要な用語・人物名・年号は必ず歌詞に含めてください。\n"
                f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。"
            )
            entry = {
                "instruction": instruction,
                "input": original_text,
                "output": content,
                "_meta": {
                    "song_id": song.id,
                    "genre": genre,
                    "source_type": source_type,
                    "quality": round(quality, 2),
                    "tags": tags,
                }
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
                "output": content,
                "_meta": {
                    "song_id": song.id,
                    "genre": genre,
                    "source_type": source_type,
                    "quality": round(quality, 2),
                    "tags": tags,
                }
            }

        # 品質統計
        if quality >= 0.6:
            quality_stats['high'] += 1
        elif quality >= 0.3:
            quality_stats['medium'] += 1
        else:
            quality_stats['low'] += 1

        training_data.append(entry)

    # 品質順にソート（高品質が先頭）
    training_data.sort(key=lambda x: x['_meta']['quality'], reverse=True)

    # 出力（_meta はlogging用なので学習時は無視される）
    output_path = os.path.join(output_dir, 'lyrics_training_data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(training_data, f, ensure_ascii=False, indent=2)

    # 高品質データのみのバージョンも出力
    high_quality = [d for d in training_data if d['_meta']['quality'] >= 0.5]
    if high_quality:
        hq_path = os.path.join(output_dir, 'lyrics_training_data_hq.json')
        with open(hq_path, 'w', encoding='utf-8') as f:
            json.dump(high_quality, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 学習データ生成完了!")
    print(f"   - 有効データ: {len(training_data)} 件")
    print(f"   - スキップ: {skipped} 件")
    print(f"   - 出力先: {output_path}")

    # 統計情報
    if training_data:
        with_input = sum(1 for d in training_data if d['input'])
        without_input = len(training_data) - with_input
        avg_output_len = sum(len(d['output']) for d in training_data) / len(training_data)
        print(f"\n📊 データ統計:")
        print(f"   元テキスト(OCR)あり: {with_input} 件")
        print(f"   元テキストなし:       {without_input} 件")
        print(f"   平均歌詞長:           {avg_output_len:.0f} 文字")
        print(f"\n📝 元テキスト構造:")
        print(f"   ノート構造:   {source_stats['note']} 件 (箇条書き・見出し)")
        print(f"   教科書構造:   {source_stats['textbook']} 件 (長文)")
        print(f"   その他:       {source_stats['plain']} 件")
        print(f"\n⭐ 品質分布:")
        print(f"   高品質 (≥0.6): {quality_stats['high']} 件")
        print(f"   中品質 (≥0.3): {quality_stats['medium']} 件")
        print(f"   低品質 (<0.3): {quality_stats['low']} 件")

        if high_quality:
            print(f"\n💎 高品質データ ({len(high_quality)} 件) → {hq_path}")
            print(f"   → 学習推奨: python train.py --data_path data/lyrics_training_data_hq.json")

    return training_data


if __name__ == '__main__':
    export_training_data()
