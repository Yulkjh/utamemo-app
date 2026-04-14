"""旧: 全学習データに対してレビュー済みレコードを一括作成していた。
ルール違反 (手動レビューのみ許可) のため no-op に変更。
既にRenderで適用済みなので削除はせず空にしている。
不正レビューは 0022_remove_bulk_reviews で削除される。
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0018_recalculate_data_hash'),
    ]

    operations = [
        # no-op: 一括レビュー作成は撤回済み
    ]
