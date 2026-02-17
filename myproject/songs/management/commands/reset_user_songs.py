"""特定ユーザーのスタックした楽曲をリセットするコマンド"""
from django.core.management.base import BaseCommand
from songs.models import Song
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = '特定ユーザーのスタックした楽曲をリセット'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='リセットするユーザー名')
        parser.add_argument(
            '--all-failed',
            action='store_true',
            help='failed曲も含めてすべてリセット',
        )

    def handle(self, *args, **options):
        username = options['username']
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'ユーザー「{username}」が見つかりません'))
            # 似た名前のユーザーを表示
            similar = User.objects.filter(username__icontains=username[:2])
            if similar.exists():
                self.stdout.write('候補:')
                for u in similar:
                    self.stdout.write(f'  - {u.username} (ID: {u.id})')
            return
        
        self.stdout.write(f'\n👤 ユーザー: {user.username} (ID: {user.id}, プラン: {user.plan})')
        
        # ユーザーの全曲状況
        songs = Song.objects.filter(created_by=user).order_by('-created_at')
        self.stdout.write(f'\n📊 楽曲状況:')
        
        status_counts = {}
        for song in songs:
            status = song.generation_status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        for status, count in status_counts.items():
            self.stdout.write(f'  {status}: {count}曲')
        
        # スタックした曲の詳細
        stuck_statuses = ['pending', 'generating']
        if options['all_failed']:
            stuck_statuses.append('failed')
        
        stuck_songs = songs.filter(generation_status__in=stuck_statuses)
        
        if not stuck_songs.exists():
            self.stdout.write(self.style.SUCCESS('\n✅ スタックした曲はありません'))
            return
        
        self.stdout.write(f'\n🔧 リセット対象:')
        for song in stuck_songs:
            elapsed = ''
            if song.started_at:
                from django.utils import timezone
                diff = (timezone.now() - song.started_at).total_seconds()
                elapsed = f', {int(diff)}秒経過'
            self.stdout.write(
                f'  ID:{song.id} "{song.title}" '
                f'status:{song.generation_status} '
                f'queue_pos:{song.queue_position} '
                f'error:{song.error_message or "なし"}'
                f'{elapsed}'
            )
        
        # リセット実行
        count = stuck_songs.count()
        stuck_songs.update(
            generation_status='failed',
            queue_position=None,
            error_message='管理者によりリセットされました。再生成してください。'
        )
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ {count}曲をリセットしました（failed状態に変更）'))
        self.stdout.write('ユーザーはページ上の「再生成する」ボタンから再試行できます。')
