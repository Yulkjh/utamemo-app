"""TrainingDataReview の data_hash を現在の lyrics_training_data.json で再計算する"""

import hashlib
import json
import os

from django.db import migrations


def recalculate_data_hash(apps, schema_editor):
    TrainingDataReview = apps.get_model('users', 'TrainingDataReview')

    # 学習データJSON読み込み
    data_path = os.path.join(
        os.path.dirname(__file__), '..', '..', '..', 'training', 'data', 'lyrics_training_data.json'
    )
    data_path = os.path.abspath(data_path)

    if not os.path.exists(data_path):
        print(f'WARNING: {data_path} not found, skipping recalculation')
        return

    with open(data_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    index_to_hash = {}
    for i, record in enumerate(raw_data):
        input_text = record.get('input', '')[:100]
        h = hashlib.sha256(input_text.encode('utf-8')).hexdigest()[:16]
        index_to_hash[i] = h

    updated = 0
    deleted = 0
    for review in TrainingDataReview.objects.all():
        new_hash = index_to_hash.get(review.data_index, '')
        if not new_hash:
            # データ範囲外のレビューは削除
            review.delete()
            deleted += 1
            continue
        if review.data_hash != new_hash:
            # unique_together 重複チェック
            if TrainingDataReview.objects.filter(
                data_hash=new_hash, reviewer=review.reviewer
            ).exclude(pk=review.pk).exists():
                review.delete()
                deleted += 1
                continue
            review.data_hash = new_hash
            review.save(update_fields=['data_hash'])
            updated += 1

    print(f'TrainingDataReview data_hash 再計算: {updated}件更新, {deleted}件削除')


def reverse_recalculate(apps, schema_editor):
    pass  # 元に戻す必要なし


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0017_populate_data_hash'),
    ]

    operations = [
        migrations.RunPython(recalculate_data_hash, reverse_recalculate),
    ]
