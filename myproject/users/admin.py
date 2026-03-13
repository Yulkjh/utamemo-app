from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.admin import AdminSite
from django.utils import timezone
from .models import User
from myproject.security import (
    get_client_ip, is_locked_out, record_failed_login,
    clear_login_attempts, get_login_attempts, MAX_LOGIN_ATTEMPTS
)
import logging

logger = logging.getLogger(__name__)


class SecureAdminSite(AdminSite):
    """セキュリティ強化された管理サイト"""
    
    def login(self, request, extra_context=None):
        """管理画面ログインにアカウントロック機能を追加"""
        ip_address = get_client_ip(request)
        
        if request.method == 'POST':
            username = request.POST.get('username', '')
            
            # ロックアウトチェック
            if is_locked_out(username) or is_locked_out(ip_address):
                logger.warning(f'管理画面ロックアウト: user={username}, IP={ip_address}')
                from django.contrib import messages
                messages.error(request, 'ログイン試行回数の上限に達しました。30分後にもう一度お試しください。')
                return super().login(request, extra_context)
        
        response = super().login(request, extra_context)
        
        if request.method == 'POST':
            username = request.POST.get('username', '')
            # ログイン成功の場合はリダイレクト（status 302）
            if response.status_code == 302:
                clear_login_attempts(username, ip_address)
            else:
                # ログイン失敗
                record_failed_login(username, ip_address)
                attempts = get_login_attempts(username)
                logger.warning(
                    f'管理画面ログイン失敗: user={username}, IP={ip_address}, '
                    f'attempts={attempts}/{MAX_LOGIN_ATTEMPTS}'
                )
        
        return response


# デフォルトのAdminSiteをセキュア版に置き換え
secure_admin_site = SecureAdminSite(name='secure_admin')


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        ('認証情報', {'fields': ('username',)}),
        ('個人情報', {'fields': ('first_name', 'last_name', 'email')}),
        ('権限', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('BAN管理', {'fields': ('is_banned', 'ban_reason', 'banned_at')}),
        ('日時', {'fields': ('last_login', 'date_joined')}),
        ('プラン・課金', {
            'fields': ('plan', 'plan_expires_at', 'stripe_customer_id', 'stripe_subscription_id')
        }),
        ('プロフィール', {'fields': ('bio', 'profile_image')}),
        ('メール通知', {'fields': ('receive_reminder_emails', 'last_reminder_sent')}),
    )
    
    # 一覧表示
    list_display = (
        'id', 'username', 'email', 'plan', 'plan_expires_at',
        'song_count', 'is_banned', 'is_superuser', 'is_staff', 'is_active', 'date_joined',
    )
    list_display_links = ('id', 'username')
    list_filter = ('is_banned', 'is_superuser', 'is_staff', 'is_active', 'plan')
    ordering = ('-date_joined',)
    date_hierarchy = 'date_joined'
    list_per_page = 30
    
    search_fields = ('username', 'email', 'first_name', 'last_name', 'stripe_customer_id')
    
    # 読み取り専用フィールド
    readonly_fields = ('last_login', 'date_joined', 'banned_at', 'last_reminder_sent')
    
    # 一括アクション
    actions = ['ban_users', 'unban_users', 'reset_to_free_plan']
    
    def song_count(self, obj):
        """ユーザーの楽曲数を表示"""
        from songs.models import Song
        return Song.objects.filter(created_by=obj).count()
    song_count.short_description = '楽曲数'
    
    @admin.action(description='選択したユーザーをBANする')
    def ban_users(self, request, queryset):
        """選択したユーザーをBANする"""
        # スーパーユーザー・スタッフはBANできない
        queryset = queryset.exclude(is_superuser=True).exclude(is_staff=True)
        count = queryset.filter(is_banned=False).update(
            is_banned=True,
            banned_at=timezone.now(),
            ban_reason='管理者によりBANされました',
        )
        self.message_user(request, f'{count}人のユーザーをBANしました。')
    
    @admin.action(description='選択したユーザーのBANを解除する')
    def unban_users(self, request, queryset):
        """選択したユーザーのBANを解除する"""
        count = queryset.filter(is_banned=True).update(
            is_banned=False,
            banned_at=None,
            ban_reason='',
        )
        self.message_user(request, f'{count}人のユーザーのBANを解除しました。')
    
    @admin.action(description='選択したユーザーをフリープランに戻す')
    def reset_to_free_plan(self, request, queryset):
        """有料プランをフリーにリセット"""
        count = queryset.exclude(plan='free').update(
            plan='free',
            plan_expires_at=None,
            stripe_subscription_id=None,
        )
        self.message_user(request, f'{count}人のユーザーをフリープランにリセットしました。')
