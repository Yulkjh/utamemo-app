from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """カスタムユーザーモデル（メールアドレス不要）"""
    
    # プラン選択肢
    PLAN_CHOICES = [
        ('free', 'フリー'),
        ('starter', 'スターター'),
        ('pro', 'プロ'),
        ('school', 'スクール'),
    ]
    
    email = models.EmailField(
        'メールアドレス',
        blank=True,
        null=True,
        help_text='オプション：パスワードリセット等に使用'
    )
    
    profile_image = models.ImageField(
        upload_to='profile_images/', 
        blank=True, 
        null=True,
        verbose_name='プロフィール画像'
    )
    profile_image_data = models.TextField(
        blank=True,
        null=True,
        verbose_name='プロフィール画像データ（Base64）'
    )
    bio = models.TextField(
        max_length=500, 
        blank=True,
        verbose_name='自己紹介'
    )
    
    # プラン情報
    plan = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default='free',
        verbose_name='プラン'
    )
    plan_expires_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='プラン有効期限'
    )
    
    # Stripe連携
    stripe_customer_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='Stripe顧客ID'
    )
    stripe_subscription_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='StripeサブスクリプションID'
    )
    
    # 注意: encryption_keyは将来の機能用に予約。
    # 現在は使用されていません。
    # 暗号化が必要な場合は、適切なKMS/HSMを使用してください。
    encryption_key = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='暗号化キー',
        help_text='Reserved for future use'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新日時'
    )
    
    # 暗号化キーの自動生成を削除（セキュリティリスク）
    # 平文でキーを保存するのは危険なため
    
    @property
    def is_pro(self):
        """有料プランかどうかを判定（管理者は常にTrue）"""
        # スタッフまたはスーパーユーザーは常にすべての機能にアクセス可能
        if self.is_staff or self.is_superuser:
            return True
        from django.utils import timezone
        if self.plan == 'free':
            return False
        if self.plan_expires_at and self.plan_expires_at < timezone.now():
            return False
        return True
    
    @property
    def is_starter(self):
        """スタータープラン以上かどうか"""
        if self.is_staff or self.is_superuser:
            return True
        return self.plan in ['starter', 'pro', 'school'] and self.is_pro
    
    @property
    def is_pro_plan(self):
        """プロプラン以上かどうか"""
        if self.is_staff or self.is_superuser:
            return True
        return self.plan in ['pro', 'school'] and self.is_pro
    
    @property
    def is_school(self):
        """スクールプランかどうか"""
        if self.is_staff or self.is_superuser:
            return True
        return self.plan == 'school' and self.is_pro
    
    def get_monthly_song_limit(self):
        """月間作成可能曲数を取得（-1は無制限）"""
        # 管理者は無制限
        if self.is_staff or self.is_superuser:
            return -1
        limits = {
            'free': 2,  # 1日2曲
            'starter': 80,
            'pro': -1,  # 無制限
            'school': 100,
        }
        return limits.get(self.plan, 2)
    
    def get_model_limits(self):
        """AIモデル別の月間制限を取得（-1は無制限）"""
        # 管理者は無制限
        if self.is_staff or self.is_superuser:
            return {'v7.5': -1, 'v7.6': -1, 'o2': -1}
        limits = {
            'free': {'v7.5': 999, 'v7.6': 0, 'o2': 5},  # フリーはv7.5無制限、v7.6は使用不可、O2は月5回
            'starter': {'v7.5': 40, 'v7.6': 25, 'o2': 15},
            'pro': {'v7.5': -1, 'v7.6': -1, 'o2': -1},  # 無制限
            'school': {'v7.5': 40, 'v7.6': 40, 'o2': 20},
        }
        return limits.get(self.plan, limits['free'])

    class Meta:
        verbose_name = 'ユーザー'
        verbose_name_plural = 'ユーザー'

    def __str__(self):
        return self.username
