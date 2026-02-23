from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.admin import AdminSite
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
        ('日時', {'fields': ('last_login', 'date_joined')}),
        ('追加情報', {'fields': ('bio', 'profile_image', 'plan', 'stripe_customer_id')}),
    )
    
    # 一覧表示：ユーザー名・権限・プランを表示
    list_display = ('id', 'username', 'email', 'plan', 'is_superuser', 'is_staff', 'is_active', 'date_joined')
    list_display_links = ('id', 'username')
    list_filter = ('is_superuser', 'is_staff', 'is_active', 'plan')
    ordering = ('-date_joined',)
    
    search_fields = ('username', 'email', 'first_name', 'last_name')
    
    # 読み取り専用フィールド
    readonly_fields = ('last_login', 'date_joined')
