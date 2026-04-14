"""0019_bulk_create_reviews で不正に一括作成されたレビューを削除する。

手動レビュー（個別にバラバラの reviewed_at を持つ）は残す。
一括作成分は migration 実行時に同一秒内に大量作成されたため、
reviewed_at の秒精度で 10件以上が同一タイムスタンプのグループを
特定し、そのレコードを削除する。
"""

from django.db import migrations
from django.db.models import Count
from django.db.models.functions import TruncSecond


def remove_bulk_created_reviews(apps, schema_editor):
    TrainingDataReview = apps.get_model('users', 'TrainingDataReview')

    # reviewed_at を秒単位で切り捨てて、同一秒に10件以上作成されたグループを検出
    # (手動レビューは1件ずつなので同一秒に10件以上はありえない)
    from django.db.models.functions import TruncSecond
    from django.db.models import Count

    bulk_timestamps = (
        TrainingDataReview.objects
        .annotate(ts=TruncSecond('reviewed_at'))
        .values('ts')
        .annotate(cnt=Count('id'))
        .filter(cnt__gte=10)
        .values_list('ts', flat=True)
    )

    total_deleted = 0
    for ts in bulk_timestamps:
        from datetime import timedelta
        # 同一秒内に作られたレコードを全て削除
        deleted, _ = TrainingDataReview.objects.filter(
            reviewed_at__gte=ts,
            reviewed_at__lt=ts + timedelta(seconds=1),
        ).delete()
        total_deleted += deleted

    if total_deleted:
        print(f'一括作成レビュー削除: {total_deleted}件')
    else:
        print('一括作成レビューなし (手動レビューのみ)')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0021_merge_0019_bulk_0020_reviewbackup'),
    ]

    operations = [
        migrations.RunPython(remove_bulk_created_reviews, noop),
    ]
