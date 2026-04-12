"""
既存の学習データに legacy_trained フラグを付与する管理コマンド。

過去のデータは全て学習に使われた実績があるが、
TrainingDataReview が存在しないためDB上で追跡できない。
JSONの _meta.legacy_trained = true で「過去に学習済み」を示す。

初回デプロイ時に1度だけ実行すれば良い（2回目以降はno-op）。

Usage:
    python manage.py mark_all_trained
"""
import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '既存学習データに legacy_trained フラグを付与'

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

        updated = 0
        for r in records:
            meta = r.setdefault('_meta', {})
            if not meta.get('legacy_trained'):
                meta['legacy_trained'] = True
                updated += 1

        if updated == 0:
            self.stdout.write('全レコードに legacy_trained が既に設定済みです')
            return

        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS(
            f'完了: {updated} / {len(records)} 件に legacy_trained フラグを付与'
        ))
