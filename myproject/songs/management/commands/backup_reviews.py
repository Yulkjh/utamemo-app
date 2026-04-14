"""
レビューデータのバックアップ・復元コマンド

使い方:
  python manage.py backup_reviews                     # バックアップ作成（DB保存）
  python manage.py backup_reviews --restore latest    # 最新バックアップから復元
  python manage.py backup_reviews --restore 3         # ID指定で復元
  python manage.py backup_reviews --list              # バックアップ一覧
  python manage.py backup_reviews --restore-deleted   # ソフトデリート分を復元
"""
import logging

from django.core.management.base import BaseCommand

from users.models import ReviewBackup, TrainingDataReview, User

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'レビューデータのバックアップ・復元'

    def add_arguments(self, parser):
        parser.add_argument(
            '--restore',
            default=None,
            help='復元するバックアップID ("latest" で最新)',
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='バックアップ一覧を表示',
        )
        parser.add_argument(
            '--restore-deleted',
            action='store_true',
            help='ソフトデリートされたレビューを復元',
        )
        parser.add_argument(
            '--note',
            default='',
            help='バックアップにメモを付ける',
        )

    def handle(self, *args, **options):
        if options['list']:
            return self._list_backups()
        if options['restore']:
            return self._restore(options['restore'])
        if options['restore_deleted']:
            return self._restore_deleted()
        return self._create_backup(options.get('note', ''))

    def _create_backup(self, note=''):
        # all_objects で削除済みも含めてバックアップ
        reviews = TrainingDataReview.all_objects.select_related('reviewer').all()
        data = []
        for r in reviews:
            data.append({
                'data_hash': r.data_hash,
                'data_index': r.data_index,
                'reviewer_username': r.reviewer.username,
                'reviewed_at': r.reviewed_at.isoformat() if r.reviewed_at else None,
                'trained_at': r.trained_at.isoformat() if r.trained_at else None,
                'is_deleted': r.is_deleted,
            })

        backup = ReviewBackup.objects.create(
            snapshot=data,
            record_count=len(data),
            note=note or 'auto',
        )

        self.stdout.write(self.style.SUCCESS(
            f'バックアップ完了: ID={backup.id} ({len(data)} 件)'
        ))

        # 古いバックアップを自動削除（最新20個のみ保持）
        old_ids = (
            ReviewBackup.objects.order_by('-created_at')
            .values_list('id', flat=True)[20:]
        )
        if old_ids:
            deleted, _ = ReviewBackup.objects.filter(id__in=list(old_ids)).delete()
            self.stdout.write(f'  古いバックアップ {deleted} 件削除')

    def _list_backups(self):
        backups = ReviewBackup.objects.order_by('-created_at')[:20]
        if not backups:
            self.stdout.write('バックアップはありません')
            return

        for bp in backups:
            active = sum(1 for d in bp.snapshot if not d.get('is_deleted', False))
            self.stdout.write(
                f'  ID={bp.id}  {bp.created_at:%Y-%m-%d %H:%M}  '
                f'({active} 件アクティブ / {bp.record_count} 件合計)  {bp.note}'
            )

    def _restore(self, name):
        if name == 'latest':
            backup = ReviewBackup.objects.order_by('-created_at').first()
            if not backup:
                self.stderr.write(self.style.ERROR('バックアップがありません'))
                return
        else:
            try:
                backup = ReviewBackup.objects.get(id=int(name))
            except (ValueError, ReviewBackup.DoesNotExist):
                self.stderr.write(self.style.ERROR(f'バックアップが見つかりません: {name}'))
                return

        # 復元前にまず現在の状態をバックアップ
        self._create_backup(note='pre-restore')

        restored = 0
        skipped = 0
        for item in backup.snapshot:
            if item.get('is_deleted', False):
                continue
            try:
                user = User.objects.get(username=item['reviewer_username'])
            except User.DoesNotExist:
                skipped += 1
                continue

            existing = TrainingDataReview.all_objects.filter(
                data_hash=item['data_hash'],
                reviewer=user,
            ).first()

            if existing:
                if existing.is_deleted:
                    existing.restore()
                    restored += 1
                else:
                    skipped += 1
            else:
                TrainingDataReview.all_objects.create(
                    data_hash=item['data_hash'],
                    data_index=item['data_index'],
                    reviewer=user,
                    trained_at=item.get('trained_at'),
                    is_deleted=False,
                )
                restored += 1

        self.stdout.write(self.style.SUCCESS(
            f'復元完了: {restored} 件復元, {skipped} 件スキップ (ID={backup.id})'
        ))

    def _restore_deleted(self):
        """ソフトデリートされた全レビューを復元"""
        count = TrainingDataReview.all_objects.filter(
            is_deleted=True,
        ).update(is_deleted=False, deleted_at=None)
        self.stdout.write(self.style.SUCCESS(f'{count} 件のソフトデリートを復元しました'))
