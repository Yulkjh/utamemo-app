"""
指定したユーザーをスーパーユーザーに昇格するコマンド

使用方法:
  python manage.py make_superuser 豆腐
  python manage.py make_superuser --list  (全ユーザー一覧)
"""

from django.core.management.base import BaseCommand
from users.models import User


class Command(BaseCommand):
    help = '指定したユーザーをスーパーユーザーに昇格する'

    def add_arguments(self, parser):
        parser.add_argument('username', nargs='?', default=None, help='スーパーユーザーにするユーザー名')
        parser.add_argument('--list', action='store_true', help='全ユーザー一覧を表示')

    def handle(self, *args, **options):
        if options['list']:
            self.stdout.write('\n=== ユーザー一覧 ===')
            for u in User.objects.all().order_by('id'):
                role = ''
                if u.is_superuser:
                    role = ' [SUPERUSER]'
                elif u.is_staff:
                    role = ' [STAFF]'
                self.stdout.write(f'  {u.id}: {u.username} (plan={u.plan}){role}')
            self.stdout.write('')
            return

        username = options['username']
        if not username:
            self.stderr.write(self.style.ERROR('ユーザー名を指定してください。例: python manage.py make_superuser 豆腐'))
            return

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'ユーザー "{username}" が見つかりません。'))
            self.stdout.write('--list で全ユーザーを確認できます。')
            return

        user.is_superuser = True
        user.is_staff = True
        user.save()

        self.stdout.write(self.style.SUCCESS(f'✅ {user.username} をスーパーユーザーに設定しました。'))
