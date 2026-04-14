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
    
    # BAN（アカウント停止）
    is_banned = models.BooleanField(
        default=False,
        verbose_name='BAN済み'
    )
    ban_reason = models.TextField(
        blank=True,
        default='',
        verbose_name='BAN理由'
    )
    banned_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='BAN日時'
    )
    
    # 年齢確認・保護者同意
    birth_date = models.DateField(
        blank=True,
        null=True,
        verbose_name='生年月日',
        help_text='年齢確認のために使用（課金時の未成年チェック）'
    )
    parental_consent_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='保護者同意日時',
        help_text='未成年ユーザーが課金する際の保護者同意記録'
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
    
    # 利用規約同意
    tos_agreed_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='利用規約同意日時',
        help_text='ユーザーが利用規約・プライバシーポリシーに同意した日時'
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
    def age(self):
        """現在の年齢を計算"""
        if not self.birth_date:
            return None
        from datetime import date
        today = date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )
    
    @property
    def is_minor(self):
        """未成年（18歳未満）かどうか"""
        age = self.age
        if age is None:
            return None  # 生年月日未設定
        return age < 18
    
    @property
    def has_parental_consent(self):
        """保護者同意があるかどうか"""
        return self.parental_consent_at is not None
    
    def can_purchase(self):
        """課金可能かチェック（未成年は保護者同意が必要）"""
        if self.is_minor is None:
            # 生年月日未設定 → 課金前に入力を求める
            return False, 'birth_date_required'
        if self.is_minor and not self.has_parental_consent:
            return False, 'parental_consent_required'
        return True, 'ok'

    @property
    def is_pro(self):
        """有料プランかどうかを判定（スタッフは常にTrue）"""
        # スタッフは常にすべての機能にアクセス可能
        if self.is_staff:
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
        if self.is_staff:
            return True
        return self.plan in ['starter', 'pro', 'school'] and self.is_pro
    
    @property
    def is_pro_plan(self):
        """プロプラン以上かどうか"""
        if self.is_staff:
            return True
        return self.plan in ['pro', 'school'] and self.is_pro
    
    @property
    def is_school(self):
        """スクールプランかどうか"""
        if self.is_staff:
            return True
        return self.plan == 'school' and self.is_pro
    
    def get_monthly_song_limit(self):
        """月間作成可能曲数を取得（-1は無制限）"""
        # スタッフは無制限
        if self.is_staff:
            return -1
        limits = {
            'free': 5,  # 月5曲
            'starter': 70,  # 月70曲
            'pro': -1,  # 無制限
            'school': 100,
        }
        return limits.get(self.plan, 5)
    
    def get_model_limits(self):
        """月間楽曲生成制限を取得（-1は無制限）"""
        # スタッフは無制限
        if self.is_staff:
            return {'v8': -1}
        limits = {
            'free': {'v8': 5},        # フリー月5曲
            'starter': {'v8': 70},    # スターター月70曲
            'pro': {'v8': -1},        # 無制限
            'school': {'v8': 100},    # スクール月100曲
        }
        return limits.get(self.plan, limits['free'])

    def get_monthly_model_usage(self):
        """今月の楽曲生成使用回数を取得"""
        from django.utils import timezone
        from songs.models import Song
        
        now = timezone.now()
        first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        count = Song.objects.filter(
            created_by=self,
            created_at__gte=first_day
        ).count()
        
        return {'v8': count}

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


class StaffReviewObligation(models.Model):
    """スタッフの学習データレビュー義務を管理するモデル

    - training-data ページに初回アクセスしたスタッフに自動作成
    - 毎日 pending_reviews が +3 累積
    - pending_reviews が 15 以上になると is_review_locked = True
    - ロック中は training-data 以外のスタッフ機能にアクセス不可
    - 編集 or 削除を行うと pending_reviews が -1
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='review_obligation',
        verbose_name='スタッフユーザー',
    )
    first_access_date = models.DateField(
        verbose_name='初回アクセス日',
        help_text='training-data ページに初めてアクセスした日',
    )
    pending_reviews = models.IntegerField(
        default=0,
        verbose_name='未処理レビュー数',
        help_text='毎日 +3 累積。編集/削除で -1。',
    )
    is_review_locked = models.BooleanField(
        default=False,
        verbose_name='レビューロック',
        help_text='True の場合、training-data 以外のスタッフ機能を制限',
    )
    last_checked_date = models.DateField(
        verbose_name='最終累積チェック日',
        help_text='日次タスクが最後に pending_reviews を加算した日',
    )
    last_reminder_sent = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='最終リマインドメール送信日時',
    )

    class Meta:
        verbose_name = 'スタッフレビュー義務'
        verbose_name_plural = 'スタッフレビュー義務'

    def __str__(self):
        status = '🔒ロック' if self.is_review_locked else '✅通常'
        return f'{self.user.username} - 未処理:{self.pending_reviews} {status}'


class TrainingDataEditLog(models.Model):
    """学習データの編集履歴を記録するモデル

    mark_reviewed 時に「編集されたか」を検証するために使用する。
    """
    data_index = models.IntegerField(
        verbose_name='データインデックス',
        help_text='lyrics_training_data.json 内のインデックス (0-based)',
    )
    editor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='training_edits',
        verbose_name='編集者',
    )
    edited_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='編集日時',
    )

    class Meta:
        verbose_name = '学習データ編集ログ'
        verbose_name_plural = '学習データ編集ログ'

    def __str__(self):
        return f'#{self.data_index + 1} edited by {self.editor.username}'


def make_data_hash(input_text):
    """学習データのinputからハッシュを生成 (SHA256先頭16文字)"""
    import hashlib
    return hashlib.sha256(input_text[:100].encode('utf-8')).hexdigest()[:16]


class ActiveReviewManager(models.Manager):
    """ソフトデリートされていないレビューのみ返すマネージャー"""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class TrainingDataReview(models.Model):
    """学習データの個別レコードに対するレビュー済みマーク

    スタッフが学習データを確認したことを記録する。
    data_hash は各レコードの input 先頭100文字の SHA256 ハッシュ（先頭16文字）。
    データの追加・削除でインデックスがずれてもレビューが正しく紐づく。
    data_index は表示用の参考値（同期時に更新される）。
    trained_at が設定されると「学習済み」として二重学習を防止。
    is_deleted=True のレコードはデフォルトでは表示されない（ソフトデリート）。
    """
    data_hash = models.CharField(
        max_length=16,
        verbose_name='データハッシュ',
        help_text='input先頭100文字のSHA256ハッシュ(先頭16文字)',
        default='',
        db_index=True,
    )
    data_index = models.IntegerField(
        verbose_name='データインデックス',
        help_text='lyrics_training_data.json 内のインデックス (0-based, 参考値)',
    )
    reviewer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='training_reviews',
        verbose_name='レビュー者',
    )
    reviewed_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='レビュー日時',
    )
    trained_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='学習完了日時',
        help_text='このデータが学習に使用された日時（null=未学習）',
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name='ソフトデリート',
        help_text='True の場合、論理削除済み（復元可能）',
        db_index=True,
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='削除日時',
    )

    objects = ActiveReviewManager()
    all_objects = models.Manager()

    class Meta:
        verbose_name = '学習データレビュー'
        verbose_name_plural = '学習データレビュー'
        unique_together = ('data_hash', 'reviewer')

    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def __str__(self):
        prefix = '[削除済] ' if self.is_deleted else ''
        return f'{prefix}#{self.data_index + 1} reviewed by {self.reviewer.username}'


class StaffMessage(models.Model):
    """スーパーユーザーからスタッフへのメッセージ"""
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_staff_messages',
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='received_staff_messages',
    )
    message = models.TextField(verbose_name='メッセージ')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'スタッフメッセージ'
        verbose_name_plural = 'スタッフメッセージ'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.sender.username} → {self.recipient.username}: {self.message[:30]}'


class ReviewBackup(models.Model):
    """レビューデータのDBバックアップ（デプロイ時に自動作成）"""
    snapshot = models.JSONField(
        verbose_name='バックアップデータ',
        help_text='TrainingDataReviewの全レコードをJSON形式で保存',
    )
    record_count = models.IntegerField(verbose_name='レコード数')
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        verbose_name = 'レビューバックアップ'
        verbose_name_plural = 'レビューバックアップ'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} ({self.record_count}件)'
