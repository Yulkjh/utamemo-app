from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """カスタムユーザーモデル（メールアドレス不要）"""
    
    # プラン選択肢
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('pro', 'Pro'),
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
        """Proプランかどうかを判定"""
        from django.utils import timezone
        if self.plan != 'pro':
            return False
        if self.plan_expires_at and self.plan_expires_at < timezone.now():
            return False
        return True

    class Meta:
        verbose_name = 'ユーザー'
        verbose_name_plural = 'ユーザー'

    def __str__(self):
        return self.username
