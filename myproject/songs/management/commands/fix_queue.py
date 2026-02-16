"""スタックした楽曲キューをクリーンアップするコマンド"""
from django.core.management.base import BaseCommand
from songs.models import Song


class Command(BaseCommand):
    help = 'スタックした楽曲キューをクリーンアップ'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix-stuck',
            action='store_true',
            help='generating状態で1時間以上経過した曲をfailedに変更',
        )

    def handle(self, *args, **options):
        # 1. 完了/失敗なのにqueue_positionが残っている曲をクリア
        stale = Song.objects.filter(
            generation_status__in=['completed', 'failed'],
            queue_position__isnull=False
        )
        stale_count = stale.count()
        if stale_count > 0:
            stale.update(queue_position=None)
            self.stdout.write(self.style.SUCCESS(
                f'✅ {stale_count}曲のスタック済みqueue_positionをクリアしました'
            ))
        else:
            self.stdout.write('queue_positionのスタックなし')

        # 2. 現在のキュー状況を表示
        pending = Song.objects.filter(generation_status='pending').order_by('created_at')
        generating = Song.objects.filter(generation_status='generating').order_by('created_at')
        
        self.stdout.write(f'\n📊 キュー状況:')
        self.stdout.write(f'  待機中(pending): {pending.count()}曲')
        self.stdout.write(f'  生成中(generating): {generating.count()}曲')
        
        for s in generating:
            elapsed = ''
            if s.started_at:
                from django.utils import timezone
                diff = (timezone.now() - s.started_at).total_seconds()
                elapsed = f' ({int(diff)}秒経過)'
            self.stdout.write(f'    - ID:{s.id} "{s.title}" queue_pos:{s.queue_position}{elapsed}')

        # 3. スタックしたgenerating曲の修復
        if options['fix_stuck']:
            from django.utils import timezone
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(hours=1)
            stuck = Song.objects.filter(
                generation_status='generating',
                started_at__lt=cutoff
            )
            stuck_count = stuck.count()
            if stuck_count > 0:
                stuck.update(generation_status='failed', queue_position=None, error_message='Stuck in generating state - auto-reset')
                self.stdout.write(self.style.WARNING(
                    f'⚠️ {stuck_count}曲のスタックしたgenerating曲をfailedに変更しました'
                ))
            
            # pending で started_at が None だが古すぎる曲もリセット
            old_pending = Song.objects.filter(
                generation_status='pending',
                created_at__lt=cutoff
            )
            old_count = old_pending.count()
            if old_count > 0:
                old_pending.update(generation_status='failed', queue_position=None, error_message='Stuck in pending state - auto-reset')
                self.stdout.write(self.style.WARNING(
                    f'⚠️ {old_count}曲のスタックしたpending曲をfailedに変更しました'
                ))

        # 4. queue_positionを再計算
        active_songs = Song.objects.filter(
            generation_status__in=['pending', 'generating']
        ).order_by('created_at')
        
        for index, song in enumerate(active_songs, start=1):
            if song.queue_position != index:
                song.queue_position = index
                song.save(update_fields=['queue_position'])
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ キュー位置を再計算しました（{active_songs.count()}曲）'))
