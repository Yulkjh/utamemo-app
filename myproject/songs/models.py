from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinLengthValidator

User = get_user_model()


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
        max_length=20,
        choices=[
            ('female', '女性ボーカル'),
            ('male', '男性ボーカル'),
        ],
        default='female',
        verbose_name='ボーカルスタイル'
    )
    mureka_model = models.CharField(
        max_length=20,
        choices=[
            ('mureka-7.5', 'V7.5 - クリアボーカル・安定'),
            ('mureka-7.6', 'V7.6 - 高品質・細かい調整可'),
            ('mureka-o2', 'O2 - 最高品質・プロ向け'),
        ],
        default='mureka-7.5',
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
