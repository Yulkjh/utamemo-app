"""劇場アンケート回答を管理者メールへ一括送信するコマンド"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from songs.models import TheaterSurveyResponse


class Command(BaseCommand):
    help = '劇場アンケート回答を管理者メールへ一括送信'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='送信せず、件数とメール内容プレビューのみ表示',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        responses = TheaterSurveyResponse.objects.order_by('created_at')
        count = responses.count()

        admin_email = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', 'admin@utamemo.com')
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@utamemo.com')

        subject = f'【UNITE CINEMA MINATO】劇場アンケート全件送信（{count}件）'

        lines = [
            '劇場アンケート回答 一括送信',
            f'件数: {count}',
            '',
        ]

        for index, response in enumerate(responses, 1):
            lines.extend([
                f'[{index}] 回答日時: {response.created_at:%Y-%m-%d %H:%M:%S}',
                f'お名前: {response.visitor_name or "匿名"}',
                f'見たい作品: {response.desired_show}',
                f'ひとこと: {response.memo or "(未入力)"}',
                '',
            ])

        message = '\n'.join(lines)

        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY RUN] 送信は実行していません。'))
            self.stdout.write(f'宛先: {admin_email}')
            self.stdout.write(f'件名: {subject}')
            self.stdout.write('--- 本文プレビュー（先頭40行） ---')
            preview_lines = message.splitlines()[:40]
            for line in preview_lines:
                self.stdout.write(line)
            return

        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[admin_email],
            fail_silently=False,
        )

        self.stdout.write(self.style.SUCCESS(
            f'送信完了: {count}件を {admin_email} へ送信しました。'
        ))
