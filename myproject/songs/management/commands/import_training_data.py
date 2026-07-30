"""
学習データをJSONファイルからDBに移行するコマンド

使い方:
  python manage.py import_training_data                    # デフォルトパスから
  python manage.py import_training_data --path /some/file  # パス指定
  python manage.py import_training_data --dry-run          # 確認のみ
  python manage.py import_training_data --path clearnote_batch1.json --partner clearnote
                                                             # パートナー提供データとしてタグ付け
"""
import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from songs.models import TrainingData, DataPartner, PartnerDataAccessLog
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
        parser.add_argument(
            '--partner',
            default=None,
            help='このインポートを外部データ提供元としてタグ付けする DataPartner の slug（例: clearnote）',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='is_active=False（削除済み/契約終了）のパートナーへのインポートも許可する',
        )

    def handle(self, *args, **options):
        if options['path']:
            data_path = Path(options['path'])
        else:
            data_path = Path(__file__).resolve().parent.parent.parent.parent.parent / 'training' / 'data' / 'lyrics_training_data.json'

        if not data_path.exists():
            self.stderr.write(self.style.ERROR(f'ファイルが見つかりません: {data_path}'))
            return

        partner = None
        if options['partner']:
            try:
                partner = DataPartner.objects.get(slug=options['partner'])
            except DataPartner.DoesNotExist:
                raise CommandError(
                    f'DataPartner "{options["partner"]}" が見つかりません。'
                    f'先に Django admin で作成してください。'
                )
            if not partner.is_active and not options['force']:
                raise CommandError(
                    f'DataPartner "{partner.slug}" は is_active=False です'
                    f'（削除済みまたは契約終了）。続行するには --force を指定してください。'
                )

        with open(data_path, 'r', encoding='utf-8') as f:
            records = json.load(f)

        self.stdout.write(f'JSONファイル: {len(records)} 件')
        self.stdout.write(f'DB既存: {TrainingData.objects.count()} 件')
        if partner:
            self.stdout.write(f'タグ付け先: {partner.name} ({partner.slug})')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('ドライラン: インポートしません'))
            return

        created = 0
        updated = 0
        skipped = 0
        retagged = 0
        conflict_skipped = 0

        with transaction.atomic():
            for record in records:
                input_text = record.get('input', '')
                data_hash = make_data_hash(input_text)

                existing = TrainingData.objects.filter(data_hash=data_hash).first()
                if existing:
                    # 既に別パートナーのデータとしてタグ付け済みの場合は誤帰属を避けるためスキップ
                    if partner and existing.data_partner_id is not None and existing.data_partner_id != partner.id:
                        self.stdout.write(self.style.WARNING(
                            f'スキップ（別パートナー "{existing.data_partner.slug}" 提供済み）: {data_hash}'
                        ))
                        conflict_skipped += 1
                        continue

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
                    # 無タグの既存データにパートナーを指定した場合は明示的にタグ付けする
                    # （黙って自社データのままにすると第3条の目的外利用リスクになる）
                    if partner and existing.data_partner_id is None:
                        existing.data_partner = partner
                        changed = True
                        retagged += 1
                        self.stdout.write(self.style.WARNING(
                            f'既存の無タグデータを "{partner.slug}" としてタグ付けしました: {data_hash}'
                        ))
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
                        data_partner=partner,
                    )
                    created += 1

            if partner and (created or updated or retagged):
                PartnerDataAccessLog.objects.create(
                    data_partner=partner,
                    action='import',
                    record_count=created + updated,
                    detail=(
                        f'import_training_data --path {data_path.name} '
                        f'(created={created}, updated={updated}, retagged={retagged}, '
                        f'conflict_skipped={conflict_skipped})'
                    ),
                )

        msg = f'完了: {created} 件作成, {updated} 件更新, {skipped} 件スキップ'
        if partner:
            msg += f', {retagged} 件再タグ付け, {conflict_skipped} 件は別パートナーと衝突しスキップ'
        self.stdout.write(self.style.SUCCESS(msg))
