"""既存の TrainingDataReview レコードに data_hash を算出して設定するデータマイグレーション"""

import hashlib
import json
import os

from django.db import migrations


def populate_data_hash(apps, schema_editor):
    TrainingDataReview = apps.get_model('users', 'TrainingDataReview')
    records_without_hash = TrainingDataReview.objects.filter(data_hash='')
    if not records_without_hash.exists():
        return

    # 学習データJSONを読み込み
    data_path = os.path.join(
        os.path.dirname(__file__), '..', '..', '..', 'training', 'data', 'lyrics_training_data.json'
    )
    data_path = os.path.abspath(data_path)
    index_to_hash = {}
    if os.path.exists(data_path):
        with open(data_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        for i, record in enumerate(raw_data):
            input_text = record.get('input', '')[:100]
            h = hashlib.sha256(input_text.encode('utf-8')).hexdigest()[:16]
            index_to_hash[i] = h

    updated = 0
    duplicates_skipped = 0
    for review in records_without_hash:
        h = index_to_hash.get(review.data_index, '')
        if not h:
            # インデックスがデータ範囲外 → 空ハッシュ生成(削除候補)
            h = hashlib.sha256(f'__unknown_index_{review.data_index}'.encode('utf-8')).hexdigest()[:16]
        # unique_together (data_hash, reviewer) の重複チェック
        if TrainingDataReview.objects.filter(data_hash=h, reviewer=review.reviewer).exclude(pk=review.pk).exists():
            duplicates_skipped += 1
            review.delete()
            continue
        review.data_hash = h
        review.save(update_fields=['data_hash'])
        updated += 1

    if updated or duplicates_skipped:
        print(f'TrainingDataReview data_hash 設定: {updated}件更新, {duplicates_skipped}件重複削除')


def reverse_populate(apps, schema_editor):
    TrainingDataReview = apps.get_model('users', 'TrainingDataReview')
    TrainingDataReview.objects.all().update(data_hash='')


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0016_alter_trainingdatareview_unique_together_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_data_hash, reverse_populate),
        migrations.AlterUniqueTogether(
            name='trainingdatareview',
            unique_together={('data_hash', 'reviewer')},
        ),
    ]
