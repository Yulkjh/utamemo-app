from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ('追加情報', {'fields': ('bio', 'profile_image')}),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'date_joined')
    ordering = ('-date_joined',)
