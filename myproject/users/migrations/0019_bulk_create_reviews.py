"""全学習データに対してレビュー済みレコードを一括作成する（staff userで）"""

import hashlib
import json
import os

from django.db import migrations


def bulk_create_reviews(apps, schema_editor):
    TrainingDataReview = apps.get_model('users', 'TrainingDataReview')
    User = apps.get_model('users', 'User')

    # staff ユーザーを取得（最初のsuperuserを使う）
    reviewer = User.objects.filter(is_superuser=True).first()
    if not reviewer:
        reviewer = User.objects.filter(is_staff=True).first()
    if not reviewer:
        print('WARNING: No staff user found, skipping')
        return

    # 学習データ読み込み
    data_path = os.path.join(
        os.path.dirname(__file__), '..', '..', '..', 'training', 'data', 'lyrics_training_data.json'
    )
    data_path = os.path.abspath(data_path)

    if not os.path.exists(data_path):
        print(f'WARNING: {data_path} not found')
        return

    with open(data_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    created = 0
    skipped = 0
    for i, record in enumerate(raw_data):
        input_text = record.get('input', '')[:100]
        h = hashlib.sha256(input_text.encode('utf-8')).hexdigest()[:16]
        _, was_created = TrainingDataReview.objects.get_or_create(
            data_hash=h,
            reviewer=reviewer,
            defaults={'data_index': i},
        )
        if was_created:
            created += 1
        else:
            skipped += 1

    print(f'TrainingDataReview 一括作成: {created}件作成, {skipped}件既存スキップ (reviewer={reviewer.username})')


def reverse_bulk(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0018_recalculate_data_hash'),
    ]

    operations = [
        migrations.RunPython(bulk_create_reviews, reverse_bulk),
    ]
