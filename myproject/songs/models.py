from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinLengthValidator
import secrets
import string

User = get_user_model()


def generate_share_id():
    """8文字のランダムな共有IDを生成"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(8))


class Tag(models.Model):
    """タグモデル"""
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='タグ名'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )

    class Meta:
        verbose_name = 'タグ'
        verbose_name_plural = 'タグ'
        ordering = ['name']

    def __str__(self):
        return f"#{self.name}"


class Song(models.Model):
    """楽曲モデル"""
    title = models.CharField(
        max_length=200,
        verbose_name='タイトル'
    )
    artist = models.CharField(
        max_length=100,
        default='AI Generated',
        verbose_name='アーティスト'
    )
    genre = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='ジャンル'
    )
    vocal_style = models.CharField(
        max_length=30,
        choices=[
            ('女性ボーカル', (
                ('female', '女性ボーカル'),
                ('female_cute', 'かわいい系女性'),
                ('female_cool', 'クール系女性'),
                ('female_powerful', 'パワフル系女性'),
            )),
            ('男性ボーカル', (
                ('male', '男性ボーカル'),
                ('male_high', 'ハイトーン系男性'),
                ('male_low', 'ローボイス系男性'),
                ('male_rough', 'ワイルド系男性'),
            )),
            ('特殊スタイル', (
                ('duet', 'デュエット（男女）'),
                ('choir', 'コーラス / 合唱'),
                ('whisper', 'ウィスパー / ささやき'),
                ('child', '子供の声'),
            )),
            ('ボカロ風', (
                ('vocaloid_female', 'ボカロ風（女性）'),
                ('vocaloid_male', 'ボカロ風（男性）'),
            )),
        ],
        default='female',
        verbose_name='ボーカルスタイル'
    )
    mureka_model = models.CharField(
        max_length=20,
        choices=[
            ('mureka-v8', 'V8 - 最新モデル'),
        ],
        default='mureka-v8',
        verbose_name='Murekaモデル'
    )
    music_prompt = models.TextField(
        blank=True,
        null=True,
        verbose_name='音楽スタイルプロンプト',
        help_text='ユーザーが指定した音楽スタイルの詳細指示'
    )
    reference_song = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='リファレンス曲',
        help_text='参考にしたい曲名（例：YOASOBIの夜に駆ける）'
    )
    reference_audio_url = models.URLField(
        blank=True,
        null=True,
        verbose_name='リファレンス音声URL',
        help_text='アップロードされたリファレンス音声のURL'
    )
    tags = models.ManyToManyField(
        'Tag',
        blank=True,
        related_name='songs',
        verbose_name='タグ'
    )
    audio_file = models.FileField(
        upload_to='songs/',
        blank=True,
        null=True,
        verbose_name='音声ファイル'
    )
    audio_url = models.URLField(
        blank=True,
        null=True,
        verbose_name='音声URL'
    )
    cover_image = models.ImageField(
        upload_to='covers/',
        blank=True,
        null=True,
        verbose_name='カバー画像'
    )
    duration = models.DurationField(
        blank=True,
        null=True,
        verbose_name='再生時間'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='songs',
        verbose_name='作成者'
    )
    is_public = models.BooleanField(
        default=False,
        verbose_name='公開設定'
    )
    is_encrypted = models.BooleanField(
        default=False,
        verbose_name='暗号化済み'
    )
    generation_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', '待機中'),
            ('generating', '生成中'),
            ('completed', '完了'),
            ('failed', '失敗'),
        ],
        default='pending',
        verbose_name='生成ステータス'
    )
    queue_position = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name='キュー位置'
    )
    retry_count = models.PositiveIntegerField(
        default=0,
        verbose_name='再試行回数'
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name='エラーメッセージ',
        help_text='最後に発生したエラーの詳細'
    )
    started_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='生成開始日時'
    )
    completed_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='生成完了日時'
    )
    likes_count = models.PositiveIntegerField(
        default=0,
        verbose_name='いいね数'
    )
    total_plays = models.PositiveIntegerField(
        default=0,
        verbose_name='総再生回数'
    )
    source_image = models.ForeignKey(
        'UploadedImage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='songs',
        verbose_name='元画像'
    )
    karaoke_audio_url = models.URLField(
        blank=True,
        null=True,
        verbose_name='カラオケ音源URL',
        help_text='Demucsで生成されたインストゥルメンタル音源のURL'
    )
    karaoke_status = models.CharField(
        max_length=20,
        choices=[
            ('none', '未処理'),
            ('processing', '処理中'),
            ('completed', '完了'),
            ('failed', '失敗'),
        ],
        default='none',
        verbose_name='カラオケ処理ステータス'
    )
    share_id = models.CharField(
        max_length=8,
        unique=True,
        default=generate_share_id,
        verbose_name='共有ID',
        help_text='URLに使われるランダムな共有ID',
        db_index=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新日時'
    )

    class Meta:
        verbose_name = '楽曲'
        verbose_name_plural = '楽曲'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_public', '-created_at']),
            models.Index(fields=['generation_status']),
            models.Index(fields=['created_by', '-created_at']),
        ]

    def __str__(self):
        return f"{self.title} - {self.artist}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('songs:song_detail', kwargs={'pk': self.pk})

    def get_share_url(self):
        """シェア用の短縮URLパスを返す"""
        from django.urls import reverse
        return reverse('songs:song_share', kwargs={'share_id': self.share_id})

    def save(self, *args, **kwargs):
        if not self.share_id:
            self.share_id = generate_share_id()
            # ユニーク制約の衝突を回避
            while Song.objects.filter(share_id=self.share_id).exists():
                self.share_id = generate_share_id()
        super().save(*args, **kwargs)


class Lyrics(models.Model):
    """歌詞モデル"""
    song = models.OneToOneField(
        Song,
        on_delete=models.CASCADE,
        related_name='lyrics',
        verbose_name='楽曲'
    )
    content = models.TextField(
        validators=[MinLengthValidator(10)],
        verbose_name='歌詞内容',
        help_text='歌詞の本文を入力してください'
    )
    original_text = models.TextField(
        blank=True,
        verbose_name='元のテキスト',
        help_text='OCRで抽出された元のテキスト'
    )
    lrc_data = models.TextField(
        blank=True,
        null=True,
        verbose_name='LRC歌詞データ',
        help_text='タイムスタンプ付き歌詞（LRC形式）'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )

    class Meta:
        verbose_name = '歌詞'
        verbose_name_plural = '歌詞'

    def __str__(self):
        return f"{self.song.title} の歌詞"
    



class Like(models.Model):
    """いいねモデル"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='likes',
        verbose_name='ユーザー'
    )
    song = models.ForeignKey(
        Song,
        on_delete=models.CASCADE,
        related_name='likes',
        verbose_name='楽曲'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )

    class Meta:
        verbose_name = 'いいね'
        verbose_name_plural = 'いいね'
        unique_together = ('user', 'song')

    def __str__(self):
        return f"{self.user.username} likes {self.song.title}"


class Favorite(models.Model):
    """お気に入りモデル"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='favorites',
        verbose_name='ユーザー'
    )
    song = models.ForeignKey(
        Song,
        on_delete=models.CASCADE,
        related_name='favorites',
        verbose_name='楽曲'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )

    class Meta:
        verbose_name = 'お気に入り'
        verbose_name_plural = 'お気に入り'
        unique_together = ('user', 'song')

    def __str__(self):
        return f"{self.user.username} favorites {self.song.title}"


class Comment(models.Model):
    """コメントモデル"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name='ユーザー'
    )
    song = models.ForeignKey(
        Song,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name='楽曲'
    )
    content = models.TextField(
        max_length=500,
        validators=[MinLengthValidator(1)],
        verbose_name='コメント内容'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新日時'
    )

    class Meta:
        verbose_name = 'コメント'
        verbose_name_plural = 'コメント'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.content[:50]}..."


class UploadedImage(models.Model):
    """アップロードされた画像モデル"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='uploaded_images',
        verbose_name='ユーザー'
    )
    image = models.ImageField(
        upload_to='uploaded_images/',
        verbose_name='画像'
    )
    extracted_text = models.TextField(
        blank=True,
        verbose_name='抽出されたテキスト'
    )
    processed = models.BooleanField(
        default=False,
        verbose_name='処理済み'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )

    class Meta:
        verbose_name = 'アップロード画像'
        verbose_name_plural = 'アップロード画像'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.created_at.strftime('%Y-%m-%d')}"


class PlayHistory(models.Model):
    """再生履歴モデル（ユーザーごとの再生回数を追跡）"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='play_histories',
        verbose_name='ユーザー'
    )
    song = models.ForeignKey(
        Song,
        on_delete=models.CASCADE,
        related_name='play_histories',
        verbose_name='楽曲'
    )
    play_count = models.PositiveIntegerField(
        default=0,
        verbose_name='再生回数'
    )
    last_played_at = models.DateTimeField(
        auto_now=True,
        verbose_name='最終再生日時'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='初回再生日時'
    )

    class Meta:
        verbose_name = '再生履歴'
        verbose_name_plural = '再生履歴'
        unique_together = ('user', 'song')
        ordering = ['-last_played_at']

    def __str__(self):
        return f"{self.user.username} - {self.song.title} ({self.play_count}回)"


class Classroom(models.Model):
    """クラス（教室）モデル"""
    name = models.CharField(
        max_length=100,
        verbose_name='クラス名'
    )
    code = models.CharField(
        max_length=8,
        unique=True,
        verbose_name='参加コード',
        help_text='生徒が参加するためのコード'
    )
    description = models.TextField(
        blank=True,
        verbose_name='説明'
    )
    host = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='hosted_classrooms',
        verbose_name='ホスト'
    )
    members = models.ManyToManyField(
        User,
        through='ClassroomMembership',
        related_name='joined_classrooms',
        verbose_name='メンバー'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='アクティブ'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )

    class Meta:
        verbose_name = 'クラス'
        verbose_name_plural = 'クラス'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.code})"

    def generate_code():
        """ユニークな参加コードを生成"""
        import random
        import string
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not Classroom.objects.filter(code=code).exists():
                return code


class ClassroomMembership(models.Model):
    """クラスメンバーシップ（中間テーブル）"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name='ユーザー'
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        verbose_name='クラス'
    )
    joined_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='参加日時'
    )

    class Meta:
        verbose_name = 'クラスメンバーシップ'
        verbose_name_plural = 'クラスメンバーシップ'
        unique_together = ('user', 'classroom')

    def __str__(self):
        return f"{self.user.username} - {self.classroom.name}"


class ClassroomSong(models.Model):
    """クラス内共有楽曲"""
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name='shared_songs',
        verbose_name='クラス'
    )
    song = models.ForeignKey(
        Song,
        on_delete=models.CASCADE,
        related_name='classroom_shares',
        verbose_name='楽曲'
    )
    shared_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name='共有者'
    )
    shared_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='共有日時'
    )

    class Meta:
        verbose_name = 'クラス共有楽曲'
        verbose_name_plural = 'クラス共有楽曲'
        unique_together = ('classroom', 'song')
        ordering = ['-shared_at']

    def __str__(self):
        return f"{self.song.title} in {self.classroom.name}"


class FlashcardDeck(models.Model):
    """フラッシュカードデッキモデル"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='flashcard_decks',
        verbose_name='ユーザー'
    )
    title = models.CharField(
        max_length=200,
        verbose_name='デッキ名'
    )
    description = models.TextField(
        blank=True,
        verbose_name='説明'
    )
    source_song = models.ForeignKey(
        'Song',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='flashcard_decks',
        verbose_name='元楽曲'
    )
    source_image = models.ForeignKey(
        'UploadedImage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='flashcard_decks',
        verbose_name='元画像'
    )
    source_text = models.TextField(
        blank=True,
        verbose_name='元テキスト',
        help_text='OCRで抽出されたテキストまたは手動入力テキスト'
    )
    card_count = models.PositiveIntegerField(
        default=0,
        verbose_name='カード数'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新日時'
    )

    class Meta:
        verbose_name = 'フラッシュカードデッキ'
        verbose_name_plural = 'フラッシュカードデッキ'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', '-updated_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.card_count}枚)"

    def update_card_count(self):
        """選択済みカード数を更新"""
        self.card_count = self.flashcards.filter(is_selected=True).count()
        self.save(update_fields=['card_count'])


class Flashcard(models.Model):
    """フラッシュカードモデル"""
    MASTERY_CHOICES = [
        (0, '未学習'),
        (1, '学習中'),
        (2, 'もう少し'),
        (3, '覚えた'),
    ]

    IMPORTANCE_CHOICES = [
        ('high', '重要'),
        ('normal', '通常'),
    ]

    deck = models.ForeignKey(
        FlashcardDeck,
        on_delete=models.CASCADE,
        related_name='flashcards',
        verbose_name='デッキ'
    )
    term = models.CharField(
        max_length=500,
        verbose_name='用語（表面）'
    )
    definition = models.TextField(
        verbose_name='定義・説明（裏面）'
    )
    importance = models.CharField(
        max_length=10,
        choices=IMPORTANCE_CHOICES,
        default='normal',
        verbose_name='重要度'
    )
    is_selected = models.BooleanField(
        default=False,
        verbose_name='選択済み',
        help_text='ユーザーがデッキに含めることを選択したカード'
    )
    mastery_level = models.IntegerField(
        choices=MASTERY_CHOICES,
        default=0,
        verbose_name='習熟度'
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name='表示順'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='作成日時'
    )

    class Meta:
        verbose_name = 'フラッシュカード'
        verbose_name_plural = 'フラッシュカード'
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.term} → {self.definition[:50]}"


class TrainingSession(models.Model):
    """LLMトレーニング監視用モデル"""
    STATUS_CHOICES = [
        ('idle', 'Idle'),
        ('loading', 'Loading Model'),
        ('training', 'Training'),
        ('saving', 'Saving'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    COMMAND_CHOICES = [
        ('none', 'None'),
        ('start', 'Start Training'),
        ('stop', 'Stop Training'),
    ]

    TRAINING_TYPE_CHOICES = [
        ('lyrics', '歌詞生成LLM'),
        ('importance', 'ノート重要度LLM'),
    ]

    machine_name = models.CharField(max_length=100, verbose_name='マシン名')
    machine_ip = models.GenericIPAddressField(blank=True, null=True, verbose_name='IP')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='idle', verbose_name='ステータス')
    training_type = models.CharField(max_length=20, choices=TRAINING_TYPE_CHOICES, default='lyrics', verbose_name='学習タイプ')
    model_name = models.CharField(max_length=200, blank=True, verbose_name='モデル名')
    current_epoch = models.IntegerField(default=0, verbose_name='現在のエポック')
    total_epochs = models.IntegerField(default=0, verbose_name='総エポック数')
    current_step = models.IntegerField(default=0, verbose_name='現在のステップ')
    total_steps = models.IntegerField(default=0, verbose_name='総ステップ数')
    train_loss = models.FloatField(null=True, blank=True, verbose_name='Train Loss')
    eval_loss = models.FloatField(null=True, blank=True, verbose_name='Eval Loss')
    accuracy = models.FloatField(null=True, blank=True, verbose_name='Accuracy')
    gpu_name = models.CharField(max_length=100, blank=True, verbose_name='GPU')
    gpu_memory_used = models.FloatField(null=True, blank=True, verbose_name='VRAM使用量(GB)')
    gpu_memory_total = models.FloatField(null=True, blank=True, verbose_name='VRAM合計(GB)')
    training_config = models.JSONField(default=dict, blank=True, verbose_name='設定')
    log_tail = models.TextField(blank=True, verbose_name='最新ログ')
    error_message = models.TextField(blank=True, verbose_name='エラー')
    pending_command = models.CharField(max_length=20, choices=COMMAND_CHOICES, default='none', verbose_name='コマンド')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='開始日時')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完了日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='最終更新')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    api_key = models.CharField(max_length=64, unique=True, verbose_name='APIキー')

    class Meta:
        verbose_name = 'トレーニングセッション'
        verbose_name_plural = 'トレーニングセッション'
        ordering = ['-updated_at']

    def save(self, *args, **kwargs):
        if not self.api_key:
            self.api_key = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.machine_name} - {self.status} ({self.model_name})"

    @property
    def progress_percent(self):
        if self.total_steps > 0:
            return min(int(self.current_step / self.total_steps * 100), 100)
        if self.total_epochs > 0:
            return int(self.current_epoch / self.total_epochs * 100)
        return 0

    @property
    def is_active(self):
        from django.utils import timezone
        from datetime import timedelta
        if self.status in ('training', 'loading', 'saving'):
            return self.updated_at >= timezone.now() - timedelta(minutes=5)
        return False
