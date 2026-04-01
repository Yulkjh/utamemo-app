"""
このコマンドは非推奨です。代わりに make_staff を使用してください。

使用方法:
  python manage.py make_staff 豆腐
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = '【非推奨】make_staff を使用してください'

    def add_arguments(self, parser):
        parser.add_argument('username', nargs='?', default=None)
        parser.add_argument('--list', action='store_true')

    def handle(self, *args, **options):
        self.stderr.write(self.style.WARNING(
            '⚠️  make_superuser は非推奨です。代わりに make_staff を使用してください。\n'
            '   例: python manage.py make_staff 豆腐'
        ))
