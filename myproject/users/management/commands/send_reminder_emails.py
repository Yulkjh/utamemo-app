"""
長期間ログインしていないユーザーにリマインドメールを送信するコマンド

使い方:
    python manage.py send_reminder_emails

Renderでの定期実行:
    Cron Job を設定して毎日実行
"""
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import Q
from datetime import timedelta
from users.models import User


class Command(BaseCommand):
    help = '長期間ログインしていないユーザーにリマインドメールを送信'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=14,
            help='何日間ログインしていないユーザーに送信するか（デフォルト: 14日）'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='実際にはメールを送信せず、対象ユーザーを表示のみ'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        
        # 指定日数以上ログインしていないユーザーを取得
        threshold_date = timezone.now() - timedelta(days=days)
        
        # 条件:
        # - メールアドレスがある
        # - 最終ログインが閾値より前
        # - アクティブなユーザー
        # - リマインドメールを受け取る設定になっている
        # - 最近リマインドメールを送っていない
        inactive_users = User.objects.filter(
            email__isnull=False,
            is_active=True,
            last_login__lt=threshold_date,
            receive_reminder_emails=True
        ).exclude(
            email=''
        )
        
        # 直近7日以内にリマインドメールを送ったユーザーは除外
        reminder_threshold = timezone.now() - timedelta(days=7)
        inactive_users = inactive_users.filter(
            Q(last_reminder_sent__isnull=True) | 
            Q(last_reminder_sent__lt=reminder_threshold)
        )
        
        self.stdout.write(f"対象ユーザー数: {inactive_users.count()}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING('ドライラン: メールは送信されません'))
            for user in inactive_users:
                days_inactive = (timezone.now() - user.last_login).days if user.last_login else 'N/A'
                self.stdout.write(f"  - {user.username} ({user.email}) - {days_inactive}日間未ログイン")
            return
        
        sent_count = 0
        error_count = 0
        
        for user in inactive_users:
            try:
                self.send_reminder_email(user)
                sent_count += 1
                
                # リマインド送信日時を更新
                user.last_reminder_sent = timezone.now()
                user.save(update_fields=['last_reminder_sent'])
                    
                self.stdout.write(f"送信成功: {user.username} ({user.email})")
                
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f"送信失敗: {user.username} - {str(e)}")
                )
        
        self.stdout.write(
            self.style.SUCCESS(f"完了: {sent_count}件送信, {error_count}件エラー")
        )

    def send_reminder_email(self, user):
        """リマインドメールを送信"""
        days_inactive = (timezone.now() - user.last_login).days if user.last_login else 0
        
        subject = f"【UTAMEMO】お久しぶりです！新しい楽曲を作りませんか？"
        
        # テキストメール本文
        message = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UTAMEMO - また会えて嬉しいです！
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{user.username} 様

UTAMEMOをご利用いただきありがとうございます。

最後のログインから{days_inactive}日が経ちました。
新しい学習用の楽曲を作ってみませんか？

▼ UTAMEMOにアクセス
https://utamemo.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【新機能のお知らせ】
- AI音楽生成の品質が向上しました
- より多くのジャンルに対応
- 作成した楽曲を共有できます

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

このメールは自動送信されています。
配信停止をご希望の場合は、ログイン後の設定画面から変更できます。

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
