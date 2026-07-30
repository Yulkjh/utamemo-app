"""
外部データ提供元（DataPartner）のデータを完全削除するコマンド

覚書等の「削除依頼を受けたら復元不可能な方法で削除・破棄する」義務（第4条相当）を
履行するためのコマンド。DBの TrainingData / TrainingDataReview に加え、
training/data/ 以下のJSONファイル・スナップショットも対象を削除する。

このコマンドは不可逆な操作のため、--yes を明示しない限りプレビュー（変更なし）のみ行う。

使い方:
  python manage.py purge_partner_data clearnote                     # プレビューのみ（何も削除しない）
  python manage.py purge_partner_data clearnote --yes                # 実際に削除する
  python manage.py purge_partner_data clearnote --yes --reason "契約終了に伴う削除依頼"
  python manage.py purge_partner_data clearnote --yes --operator yourname
"""
import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from songs.models import DataPartner, TrainingData, PartnerDataAccessLog
from users.models import make_data_hash, TrainingDataReview

logger = logging.getLogger(__name__)

# training/data/ 配下で、パートナーデータが混入しうるJSONファイル
JSON_TARGET_RELATIVE_PATHS = [
    ('training', 'data', 'lyrics_training_data.json'),
    ('training', 'data', 'lyrics_training_data.json.bak'),
    ('training', 'data', 'sample_training_data.json'),
    ('training', 'data', 'lyrics_training_data_hq.json'),
    ('data', 'lyrics_training_data.json'),
]


def _record_hash(rec):
    """レコードの `_hash` を使い、なければ make_data_hash で計算する"""
    h = rec.get('_hash')
    if h:
        return h
    return make_data_hash(rec.get('input', ''))


class Command(BaseCommand):
    help = 'DataPartner に紐づく学習データをDB・JSONファイルの両方から完全削除する（不可逆）'

    def add_arguments(self, parser):
        parser.add_argument('partner_slug', help='削除対象の DataPartner の slug')
        parser.add_argument('--reason', default='', help='削除理由（監査ログに記録）')
        parser.add_argument('--operator', default=None, help='削除を実行したユーザー名（監査ログに記録）')
        parser.add_argument(
            '--yes',
            action='store_true',
            help='実際に削除を実行する。指定しない場合はプレビューのみで何も変更しない。',
        )

    def handle(self, *args, **options):
        try:
            partner = DataPartner.objects.get(slug=options['partner_slug'])
        except DataPartner.DoesNotExist:
            raise CommandError(f'DataPartner "{options["partner_slug"]}" が見つかりません。')

        operator_user = None
        if options['operator']:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                operator_user = User.objects.get(username=options['operator'])
            except User.DoesNotExist:
                raise CommandError(f'ユーザー "{options["operator"]}" が見つかりません。')

        qs = TrainingData.objects.filter(data_partner=partner)
        count = qs.count()
        hashes = set(qs.values_list('data_hash', flat=True))

        review_count = TrainingDataReview.all_objects.filter(data_hash__in=hashes).count()

        repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        file_matches = {}
        for parts in JSON_TARGET_RELATIVE_PATHS:
            path = repo_root.joinpath(*parts)
            if not path.exists():
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    file_records = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.stdout.write(self.style.WARNING(f'  読み込み失敗（スキップ）: {path} ({e})'))
                continue
            matched = sum(1 for rec in file_records if _record_hash(rec) in hashes)
            if matched:
                file_matches[path] = matched

        snapshots_dir = repo_root / 'training' / 'data' / 'snapshots'
        if snapshots_dir.is_dir():
            for path in snapshots_dir.glob('*.json'):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        file_records = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    self.stdout.write(self.style.WARNING(f'  読み込み失敗（スキップ）: {path} ({e})'))
                    continue
                if not isinstance(file_records, list):
                    continue
                matched = sum(1 for rec in file_records if isinstance(rec, dict) and _record_hash(rec) in hashes)
                if matched:
                    file_matches[path] = matched

        self.stdout.write(f'対象パートナー: {partner.name} ({partner.slug})')
        self.stdout.write(f'DB上の TrainingData: {count} 件')
        self.stdout.write(f'紐づく TrainingDataReview（ソフトデリート含む）: {review_count} 件')
        if file_matches:
            self.stdout.write('該当するJSONファイル:')
            for path, matched in file_matches.items():
                self.stdout.write(f'  {path}: {matched} 件')
        else:
            self.stdout.write('該当するJSONファイルなし')

        if not options['yes']:
            self.stdout.write(self.style.WARNING(
                '\nプレビューのみ実行しました。何も削除していません。'
                '実際に削除するには --yes を指定してください。'
            ))
            return

        if count == 0 and not file_matches:
            self.stdout.write(self.style.WARNING('削除対象がありません。'))
            return

        with transaction.atomic():
            TrainingDataReview.all_objects.filter(data_hash__in=hashes).delete()
            qs.delete()
            partner.is_active = False
            partner.deletion_requested_at = partner.deletion_requested_at or timezone.now()
            partner.save(update_fields=['is_active', 'deletion_requested_at'])
            PartnerDataAccessLog.objects.create(
                data_partner=partner,
                action='delete',
                user=operator_user,
                record_count=count,
                detail=options['reason'] or f'purge_partner_data (files_touched={len(file_matches)})',
            )

        touched_files = []
        failed_files = []
        for path, matched in file_matches.items():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    file_records = json.load(f)
                remaining = [rec for rec in file_records if _record_hash(rec) not in hashes]
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(remaining, f, ensure_ascii=False, indent=2)
                touched_files.append(path)
            except OSError as e:
                failed_files.append((path, str(e)))

        self.stdout.write(self.style.SUCCESS(
            f'\n完了: DB {count} 件削除, レビュー履歴 {review_count} 件削除, '
            f'JSONファイル {len(touched_files)} 件を更新しました。'
        ))
        if failed_files:
            self.stdout.write(self.style.ERROR('以下のファイルは更新に失敗しました。手動で確認してください:'))
            for path, err in failed_files:
                self.stdout.write(self.style.ERROR(f'  {path}: {err}'))
