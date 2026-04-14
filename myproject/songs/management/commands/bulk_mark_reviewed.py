"""
全学習データを一括でレビュー済みにするコマンド

使い方:
  python manage.py bulk_mark_reviewed
  python manage.py bulk_mark_reviewed --username admin
  python manage.py bulk_mark_reviewed --dry-run
"""
import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand

from users.models import TrainingDataReview, User, make_data_hash

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '全学習データを一括でレビュー済みにマークする'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            default=None,
            help='レビュー者のユーザー名 (未指定時は最初のスーパーユーザー)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='実際には登録せず件数だけ表示',
        )

    def handle(self, *args, **options):
        data_path = Path(__file__).resolve().parent.parent.parent.parent.parent / 'training' / 'data' / 'lyrics_training_data.json'
        if not data_path.exists():
            self.stderr.write(self.style.ERROR(f'データファイルが見つかりません: {data_path}'))
            return

        with open(data_path, 'r', encoding='utf-8') as f:
            records = json.load(f)

        self.stdout.write(f'学習データ: {len(records)} 件')

        # レビュー者を決定
        username = options['username']
        if username:
            try:
                reviewer = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'ユーザーが見つかりません: {username}'))
                return
        else:
            reviewer = User.objects.filter(is_superuser=True).first()
            if not reviewer:
                self.stderr.write(self.style.ERROR('スーパーユーザーが見つかりません。--username で指定してください'))
                return

        self.stdout.write(f'レビュー者: {reviewer.username}')

        # 既存レビュー数
        existing = TrainingDataReview.objects.filter(reviewer=reviewer).count()
        self.stdout.write(f'既存レビュー: {existing} 件')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('ドライラン: 実際には登録しません'))
            return

        created_count = 0
        skipped_count = 0

        for i, record in enumerate(records):
            data_hash = make_data_hash(record.get('input', ''))
            _, created = TrainingDataReview.objects.get_or_create(
                data_hash=data_hash,
                reviewer=reviewer,
                defaults={'data_index': i},
            )
            if created:
                created_count += 1
            else:
                skipped_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'完了: {created_count} 件を新規登録, {skipped_count} 件はスキップ (既に登録済み)'
        ))

        total = TrainingDataReview.objects.filter(reviewer=reviewer, trained_at__isnull=True).count()
        self.stdout.write(f'未学習レビュー合計: {total} 件 (学習エージェントがこれを取得します)')
