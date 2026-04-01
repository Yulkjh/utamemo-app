"""
指定したユーザーをスタッフに昇格するコマンド

使用方法:
  python manage.py make_staff 豆腐
  python manage.py make_staff --list  (全ユーザー一覧)
  python manage.py make_staff --remove 豆腐  (スタッフ権限を削除)
"""

from django.core.management.base import BaseCommand
from users.models import User


class Command(BaseCommand):
    help = '指定したユーザーをスタッフに昇格する（admin・個人情報へのアクセス権限）'

    def add_arguments(self, parser):
        parser.add_argument('username', nargs='?', default=None, help='スタッフにするユーザー名')
        parser.add_argument('--list', action='store_true', help='全ユーザー一覧を表示')
        parser.add_argument('--remove', action='store_true', help='スタッフ権限を削除する')

    def handle(self, *args, **options):
        if options['list']:
            self.stdout.write('\n=== ユーザー一覧 ===')
            for u in User.objects.all().order_by('id'):
                role = ''
                if u.is_staff:
                    role = ' [STAFF]'
                self.stdout.write(f'  {u.id}: {u.username} (plan={u.plan}){role}')
            self.stdout.write('')
            return

        username = options['username']
        if not username:
            self.stderr.write(self.style.ERROR('ユーザー名を指定してください。例: python manage.py make_staff 豆腐'))
            return

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'ユーザー "{username}" が見つかりません。'))
            self.stdout.write('--list で全ユーザーを確認できます。')
            return

        if options['remove']:
            user.is_staff = False
            user.save()
            self.stdout.write(self.style.SUCCESS(f'✅ {user.username} のスタッフ権限を削除しました。'))
        else:
            user.is_staff = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f'✅ {user.username} をスタッフに設定しました。'))
