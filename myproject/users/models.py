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
    
    # リマインドメール
    last_reminder_sent = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='最終リマインドメール送信日時'
    )
    receive_reminder_emails = models.BooleanField(
        default=True,
        verbose_name='リマインドメールを受け取る'
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
            'free': 15,  # 月15曲
            'starter': 70,  # 月70曲
            'pro': -1,  # 無制限
            'school': 100,
        }
        return limits.get(self.plan, 15)
    
    def get_model_limits(self):
        """AIモデル別の月間制限を取得（-1は無制限）"""
        # 管理者は無制限
        if self.is_staff or self.is_superuser:
            return {'v7.5': -1, 'v7.6': -1, 'o2': -1}
        limits = {
            'free': {'v7.5': 0, 'v7.6': 0, 'o2': 15},  # フリーはO2のみ月15曲
            'starter': {'v7.5': 15, 'v7.6': 20, 'o2': 35},  # スターター月70曲
            'pro': {'v7.5': -1, 'v7.6': -1, 'o2': -1},  # 無制限
            'school': {'v7.5': 40, 'v7.6': 40, 'o2': 20},
        }
        return limits.get(self.plan, limits['free'])

    def get_monthly_model_usage(self):
        """今月のAIモデル別使用回数を取得"""
        from django.utils import timezone
        from songs.models import Song
        
        now = timezone.now()
        first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        songs = Song.objects.filter(
            created_by=self,
            created_at__gte=first_day
        ).values_list('mureka_model', flat=True)
        
        usage = {'v7.5': 0, 'v7.6': 0, 'o2': 0}
        for model in songs:
            if model == 'mureka-7.5':
                usage['v7.5'] += 1
            elif model == 'mureka-7.6':
                usage['v7.6'] += 1
            elif model == 'mureka-o2':
                usage['o2'] += 1
        
        return usage

    def get_remaining_model_usage(self):
        """今月の残り使用可能回数を取得"""
        limits = self.get_model_limits()
        usage = self.get_monthly_model_usage()
        
        remaining = {}
        for model, limit in limits.items():
            if limit == -1:
                remaining[model] = -1  # 無制限
            else:
                remaining[model] = max(0, limit - usage.get(model, 0))
        
        return remaining

    def can_use_model(self, model_key):
        """指定されたモデルを使用可能かチェック"""
        remaining = self.get_remaining_model_usage()
        return remaining.get(model_key, 0) != 0  # -1（無制限）または残りがある場合

    class Meta:
        verbose_name = 'ユーザー'
        verbose_name_plural = 'ユーザー'

    def __str__(self):
        return self.username
