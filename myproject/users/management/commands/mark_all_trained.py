"""
全既存学習データを一括で reviewed & trained としてマークする管理コマンド。

過去のデータは全て学習に使われた実績があるため、
TrainingDataReview を作成し trained_at を現在日時にセットする。

Usage:
    python manage.py mark_all_trained
    python manage.py mark_all_trained --reviewer=admin_username
"""
import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import TrainingDataReview, User

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '全既存学習データを reviewed & trained としてマーク'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reviewer',
            type=str,
            default=None,
            help='レビュー者のユーザー名。省略時は最初のsuperuserを使用',
        )

    def handle(self, *args, **options):
        data_path = (
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / 'training' / 'data' / 'lyrics_training_data.json'
        )
        if not data_path.exists():
            self.stderr.write(self.style.ERROR(f'データファイルが見つかりません: {data_path}'))
            return

        with open(data_path, 'r', encoding='utf-8') as f:
            records = json.load(f)

        total = len(records)
        self.stdout.write(f'Total records: {total}')

        reviewer_name = options.get('reviewer')
        if reviewer_name:
            reviewer = User.objects.filter(username=reviewer_name).first()
        else:
            reviewer = User.objects.filter(is_superuser=True).first()
            if not reviewer:
                reviewer = User.objects.filter(is_staff=True).first()

        if not reviewer:
            self.stderr.write(self.style.ERROR('レビュー者が見つかりません'))
            return

        self.stdout.write(f'Reviewer: {reviewer.username}')

        now = timezone.now()
        created_count = 0
        updated_count = 0

        for i in range(total):
            obj, created = TrainingDataReview.objects.get_or_create(
                data_index=i,
                reviewer=reviewer,
                defaults={'trained_at': now},
            )
            if created:
                created_count += 1
            elif obj.trained_at is None:
                obj.trained_at = now
                obj.save(update_fields=['trained_at'])
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'完了: {created_count} 件作成, {updated_count} 件更新, '
            f'全 {total} 件を trained マーク'
        ))
