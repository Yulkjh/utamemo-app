"""非公開かつ長期間再生されていない楽曲を自動削除するコマンド

削除条件:
  - 非公開（is_public=False）
  - いいね数が10未満
  - 最後の再生から2ヶ月以上経過（再生履歴がない場合は作成日から2ヶ月）

削除対象外:
  - 公開中の楽曲
  - いいね数10以上の楽曲
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Max
from datetime import timedelta
from songs.models import Song

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '非公開かつ2ヶ月以上再生されていない楽曲を自動削除'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='実際には削除せず、対象楽曲を表示するだけ',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=60,
            help='未再生日数の閾値（デフォルト: 60日）',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        days_threshold = options['days']
        cutoff_date = timezone.now() - timedelta(days=days_threshold)

        # 非公開 & いいね数10未満の楽曲を取得し、最終再生日時をアノテーション
        candidates = (
            Song.objects
            .filter(is_public=False, likes_count__lt=10)
            .annotate(last_played=Max('play_histories__last_played_at'))
        )

        to_delete = []
        for song in candidates:
            # 再生履歴がある場合は最終再生日時、なければ作成日時で判定
            reference_date = song.last_played or song.created_at
            if reference_date < cutoff_date:
                to_delete.append(song)

        count = len(to_delete)

        if count == 0:
            self.stdout.write(self.style.SUCCESS('削除対象の楽曲はありません。'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'[DRY RUN] 削除対象: {count}曲'
            ))
            for song in to_delete:
                ref = song.last_played or song.created_at
                self.stdout.write(
                    f'  - [{song.pk}] {song.title} '
                    f'(作成者: {song.created_by.username}, '
                    f'いいね: {song.likes_count}, '
                    f'最終参照: {ref.strftime("%Y-%m-%d")})'
                )
        else:
            # 関連データ含めて削除（CASCADE）
            song_ids = [song.pk for song in to_delete]
            deleted_count, _ = Song.objects.filter(pk__in=song_ids).delete()
            logger.info(f'cleanup_inactive_songs: {deleted_count}曲を削除しました')
            self.stdout.write(self.style.SUCCESS(
                f'{deleted_count}曲の非アクティブ楽曲を削除しました。'
            ))
