from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # ユーザー名とパスワードを非表示にしたカスタムfieldsets
    fieldsets = (
        # ('認証情報', {'fields': ('username', 'password')}),  # 非表示
        ('個人情報', {'fields': ('first_name', 'last_name', 'email')}),
        ('権限', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('日時', {'fields': ('last_login', 'date_joined')}),
        ('追加情報', {'fields': ('bio', 'profile_image', 'plan', 'stripe_customer_id')}),
    )
    
    # 一覧表示でもユーザー名を匿名化
    list_display = ('id', 'email', 'plan', 'is_staff', 'date_joined')
    list_display_links = ('id',)  # IDでリンク
    ordering = ('-date_joined',)
    
    # ユーザー名での検索を無効化
    search_fields = ('email', 'first_name', 'last_name')
    
    # 読み取り専用フィールド
    readonly_fields = ('last_login', 'date_joined')
