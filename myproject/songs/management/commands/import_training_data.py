"""
学習データをJSONファイルからDBに移行するコマンド

使い方:
  python manage.py import_training_data                    # デフォルトパスから
  python manage.py import_training_data --path /some/file  # パス指定
  python manage.py import_training_data --dry-run          # 確認のみ
"""
import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from songs.models import TrainingData
from users.models import make_data_hash

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '学習データをJSONファイルからDBにインポート'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            default=None,
            help='JSONファイルのパス（未指定時は training/data/lyrics_training_data.json）',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='実際にはインポートせず件数のみ表示',
        )

    def handle(self, *args, **options):
        if options['path']:
            data_path = Path(options['path'])
        else:
            data_path = Path(__file__).resolve().parent.parent.parent.parent.parent / 'training' / 'data' / 'lyrics_training_data.json'

        if not data_path.exists():
            self.stderr.write(self.style.ERROR(f'ファイルが見つかりません: {data_path}'))
            return

        with open(data_path, 'r', encoding='utf-8') as f:
            records = json.load(f)

        self.stdout.write(f'JSONファイル: {len(records)} 件')
        self.stdout.write(f'DB既存: {TrainingData.objects.count()} 件')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('ドライラン: インポートしません'))
            return

        created = 0
        updated = 0
        skipped = 0

        with transaction.atomic():
            for record in records:
                input_text = record.get('input', '')
                data_hash = make_data_hash(input_text)

                existing = TrainingData.objects.filter(data_hash=data_hash).first()
                if existing:
                    # 内容が変わっていたら更新
                    changed = False
                    if existing.instruction != record.get('instruction', ''):
                        existing.instruction = record.get('instruction', '')
                        changed = True
                    if existing.input_text != input_text:
                        existing.input_text = input_text
                        changed = True
                    if existing.output_text != record.get('output', ''):
                        existing.output_text = record.get('output', '')
                        changed = True
                    if changed:
                        existing.save()
                        updated += 1
                    else:
                        skipped += 1
                else:
                    TrainingData.objects.create(
                        instruction=record.get('instruction', ''),
                        input_text=input_text,
                        output_text=record.get('output', ''),
                    )
                    created += 1

        self.stdout.write(self.style.SUCCESS(
            f'完了: {created} 件作成, {updated} 件更新, {skipped} 件スキップ'
        ))
