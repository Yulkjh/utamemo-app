"""
Share ID マイグレーション

既存レコードがある場合でも安全に share_id を追加するため、
3ステップで実行する:
1. null許容・ユニーク制約なしで share_id フィールドを追加
2. 既存レコードにランダムな share_id を設定
3. null不許容・ユニーク制約ありに変更
"""
import secrets
import string

from django.db import migrations, models


def generate_share_id():
    """8文字のランダムな英数字IDを生成"""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(8))


def populate_share_ids(apps, schema_editor):
    """既存の全Songレコードにユニークな share_id を設定"""
    Song = apps.get_model('songs', 'Song')
    existing_ids = set()

    for song in Song.objects.filter(share_id__isnull=True).iterator():
        new_id = generate_share_id()
        while new_id in existing_ids:
            new_id = generate_share_id()
        existing_ids.add(new_id)
        song.share_id = new_id
        song.save(update_fields=['share_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('songs', '0028_expand_vocal_style_choices'),
    ]

    operations = [
        # Step 1: null許容・ユニーク制約なしでフィールド追加
        migrations.AddField(
            model_name='song',
            name='share_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='URLに使われるランダムな共有ID',
                max_length=8,
                null=True,
                verbose_name='共有ID',
            ),
        ),
        # Step 2: 既存レコードにランダムな share_id を設定
        migrations.RunPython(
            populate_share_ids,
            migrations.RunPython.noop,
        ),
        # Step 3: null不許容・ユニーク制約ありに変更
        migrations.AlterField(
            model_name='song',
            name='share_id',
            field=models.CharField(
                db_index=True,
                default=generate_share_id,
                help_text='URLに使われるランダムな共有ID',
                max_length=8,
                unique=True,
                verbose_name='共有ID',
            ),
        ),
    ]
