"""
既存のファイルベース prompt_config.json から DB (PromptTemplate) へ移行するコマンド。

使い方:
    python manage.py migrate_prompt_to_db
"""
import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand

from songs.models import PromptTemplate

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'prompt_config.json の内容を DB (PromptTemplate) に移行する'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='既存のDBデータがある場合も上書きする',
        )

    def handle(self, *args, **options):
        config_path = Path(__file__).resolve().parent.parent.parent.parent.parent / 'training' / 'data' / 'prompt_config.json'

        if not config_path.exists():
            self.stdout.write(self.style.WARNING(f'{config_path} が見つかりません。スキップします。'))
            return

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        instruction = config.get('instruction_template', '')
        if not instruction:
            self.stdout.write(self.style.WARNING('instruction_template が空です。スキップします。'))
            return

        # 既にDBにデータがあるかチェック
        existing = PromptTemplate.objects.filter(key='lyrics_instruction').first()
        if existing and not options['force']:
            self.stdout.write(self.style.WARNING(
                f'lyrics_instruction は既にDBに存在します（最終更新: {existing.updated_at}）。'
                f'上書きする場合は --force オプションを使ってください。'
            ))
            return

        obj = PromptTemplate.set_template(
            key='lyrics_instruction',
            content=instruction,
            user=None,
        )
        self.stdout.write(self.style.SUCCESS(
            f'lyrics_instruction を DB に移行しました（ID: {obj.pk}）'
        ))
