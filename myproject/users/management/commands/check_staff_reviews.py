"""
スタッフの学習データレビュー義務をチェックする日次コマンド

処理:
1. training-data に一度でもアクセスした全スタッフの pending_reviews を +3
2. pending_reviews > 0 のスタッフにリマインドメールを送信
3. pending_reviews >= 15 のスタッフを自動ロック (is_review_locked = True)

使い方:
    python manage.py check_staff_reviews
    python manage.py check_staff_reviews --dry-run  # メール送信・DB更新なし

Renderでの定期実行:
    Cron Job で毎日1回実行
"""
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from users.models import StaffReviewObligation
import logging

logger = logging.getLogger(__name__)

DAILY_INCREMENT = 3
LOCK_THRESHOLD = 15


class Command(BaseCommand):
    help = 'スタッフの学習データレビュー義務を日次チェック（+3累積、メール、ロック）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='実際にはDB更新・メール送信せず、対象を表示のみ',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.localdate()

        obligations = StaffReviewObligation.objects.select_related('user').filter(
            user__is_staff=True,
            user__is_active=True,
        )

        if not obligations.exists():
            self.stdout.write('対象スタッフなし')
            return

        incremented = 0
        emails_sent = 0
        locked = 0

        for ob in obligations:
            # 同じ日に二重加算しない
            if ob.last_checked_date >= today:
                self.stdout.write(f'  SKIP(本日チェック済み): {ob.user.username}')
                continue

            old_pending = ob.pending_reviews
            new_pending = old_pending + DAILY_INCREMENT

            if dry_run:
                self.stdout.write(
                    f'  [DRY-RUN] {ob.user.username}: '
                    f'{old_pending} → {new_pending}'
                    f'{" → 🔒ロック" if new_pending >= LOCK_THRESHOLD else ""}'
                )
                incremented += 1
                continue

            # +3 加算
            ob.pending_reviews = new_pending
            ob.last_checked_date = today

            # 15以上でロック
            if new_pending >= LOCK_THRESHOLD and not ob.is_review_locked:
                ob.is_review_locked = True
                locked += 1
                logger.warning(
                    f'Staff review lock: {ob.user.username} '
                    f'(pending={new_pending})'
                )

            ob.save(update_fields=[
                'pending_reviews', 'last_checked_date', 'is_review_locked',
            ])
            incremented += 1

            self.stdout.write(
                f'  {ob.user.username}: {old_pending} → {new_pending}'
                f'{" → 🔒ロック" if ob.is_review_locked else ""}'
            )

            # リマインドメール送信
            if ob.user.email and new_pending > 0:
                try:
                    self._send_reminder(ob.user, new_pending, ob.is_review_locked)
                    ob.last_reminder_sent = timezone.now()
                    ob.save(update_fields=['last_reminder_sent'])
                    emails_sent += 1
                    self.stdout.write(f'    → メール送信: {ob.user.email}')
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'    → メール送信失敗: {e}')
                    )

        self.stdout.write(self.style.SUCCESS(
            f'完了: {incremented}件加算, {emails_sent}件メール, {locked}件ロック'
        ))

    def _send_reminder(self, user, pending, is_locked):
        """リマインドメールを送信"""
        if is_locked:
            subject = '【UTAMEMO】⚠️ アカウントがロックされました - 学習データレビューが必要です'
            status_line = (
                f'⚠️ 未処理レビューが {pending} 件に達したため、'
                f'あなたのスタッフアカウントはロックされました。\n'
                f'ロックを解除するには、学習データの編集・削除を行い '
                f'{LOCK_THRESHOLD} 件未満にしてください。'
            )
        else:
            subject = f'【UTAMEMO】学習データレビューのお願い（未処理: {pending}件）'
            status_line = (
                f'現在 {pending} 件の学習データレビューが未処理です。\n'
                f'1日あたり {DAILY_INCREMENT} 件ずつ累積されます。\n'
                f'{LOCK_THRESHOLD} 件以上になるとアカウントがロックされます。'
            )

        message = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UTAMEMO - 学習データレビューのお知らせ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{user.username} 様

{status_line}

▼ 学習データ管理ページ
https://utamemo.com/staff/training-data/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【レビュー方法】
- 学習データの内容を確認し、必要に応じて編集または削除してください
- 1件の編集または削除で、未処理数が1件減ります

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

このメールは自動送信されています。

UTAMEMO Team
https://utamemo.com
"""

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
