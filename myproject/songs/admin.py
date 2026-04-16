from django.contrib import admin
from django.utils import timezone
from .models import (
    Song, Lyrics, Like, Favorite, Comment, UploadedImage,
    Tag, PlayHistory, Classroom, ClassroomMembership, ClassroomSong,
    FlashcardDeck, Flashcard, TrainingSession, PromptTemplate,
    TrainingData,
)


class LyricsInline(admin.StackedInline):
    """歌詞をSong詳細画面にインライン表示"""
    model = Lyrics
    extra = 0
    readonly_fields = ('created_at',)


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'share_id', 'title', 'artist', 'created_by', 'genre', 'vocal_style',
        'mureka_model', 'generation_status', 'is_public', 'is_encrypted',
        'likes_count', 'total_plays', 'retry_count',
        'karaoke_status', 'created_at',
    )
    list_display_links = ('id', 'title')
    list_filter = (
        'generation_status', 'is_public', 'is_encrypted', 'genre',
        'vocal_style', 'mureka_model', 'karaoke_status', 'created_at',
    )
    search_fields = ('title', 'artist', 'created_by__username', 'music_prompt', 'error_message', 'share_id')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    list_per_page = 30
    readonly_fields = ('share_id', 'created_at', 'updated_at', 'started_at', 'completed_at', 'likes_count', 'total_plays')
    raw_id_fields = ('created_by', 'source_image')
    inlines = [LyricsInline]
    
    fieldsets = (
        ('基本情報', {
            'fields': ('title', 'artist', 'genre', 'vocal_style', 'tags')
        }),
        ('AI生成設定', {
            'fields': ('mureka_model', 'music_prompt')
        }),
        ('音声・メディア', {
            'fields': ('audio_file', 'audio_url', 'cover_image', 'duration',
                       'karaoke_audio_url', 'karaoke_status')
        }),
        ('生成ステータス', {
            'fields': ('generation_status', 'queue_position', 'retry_count',
                       'error_message', 'started_at', 'completed_at')
        }),
        ('公開・暗号化', {
            'fields': ('is_public', 'is_encrypted', 'share_id', 'created_by', 'source_image')
        }),
        ('統計', {
            'fields': ('likes_count', 'total_plays')
        }),
        ('日時', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    actions = ['reset_failed_songs', 'make_public', 'make_private']
    
    @admin.action(description='選択した楽曲の生成失敗をリセットする')
    def reset_failed_songs(self, request, queryset):
        """失敗した楽曲のステータスをpendingに戻す"""
        count = queryset.filter(generation_status='failed').update(
            generation_status='pending',
            retry_count=0,
            error_message='',
            queue_position=0,
        )
        self.message_user(request, f'{count}件の楽曲をリセットしました。')
    
    @admin.action(description='選択した楽曲を公開にする')
    def make_public(self, request, queryset):
        count = queryset.filter(is_public=False).update(is_public=True)
        self.message_user(request, f'{count}件の楽曲を公開にしました。')
    
    @admin.action(description='選択した楽曲を非公開にする')
    def make_private(self, request, queryset):
        count = queryset.filter(is_public=True).update(is_public=False)
        self.message_user(request, f'{count}件の楽曲を非公開にしました。')


@admin.register(Lyrics)
class LyricsAdmin(admin.ModelAdmin):
    list_display = ('id', 'song', 'created_at')
    search_fields = ('song__title', 'content', 'original_text')
    ordering = ('-created_at',)
    list_per_page = 30
    readonly_fields = ('created_at',)
    raw_id_fields = ('song',)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'song_count', 'created_at')
    search_fields = ('name',)
    ordering = ('name',)
    list_per_page = 50
    
    def song_count(self, obj):
        return obj.songs.count()
    song_count.short_description = '楽曲数'


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'song', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'song__title')
    ordering = ('-created_at',)
    list_per_page = 50
    raw_id_fields = ('user', 'song')


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'song', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'song__title')
    ordering = ('-created_at',)
    list_per_page = 50
    raw_id_fields = ('user', 'song')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'song', 'content_short', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('content', 'user__username', 'song__title')
    ordering = ('-created_at',)
    list_per_page = 30
    raw_id_fields = ('user', 'song')
    
    def content_short(self, obj):
        return obj.content[:80] + '...' if len(obj.content) > 80 else obj.content
    content_short.short_description = 'コメント'


@admin.register(UploadedImage)
class UploadedImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'processed', 'has_text', 'created_at')
    list_filter = ('processed', 'created_at')
    search_fields = ('user__username', 'extracted_text')
    ordering = ('-created_at',)
    list_per_page = 30
    readonly_fields = ('created_at',)
    raw_id_fields = ('user',)
    
    def has_text(self, obj):
        return bool(obj.extracted_text)
    has_text.boolean = True
    has_text.short_description = 'テキスト抽出済'


@admin.register(PlayHistory)
class PlayHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'song', 'play_count', 'last_played_at', 'created_at')
    list_filter = ('last_played_at',)
    search_fields = ('user__username', 'song__title')
    ordering = ('-last_played_at',)
    list_per_page = 50
    readonly_fields = ('last_played_at', 'created_at')
    raw_id_fields = ('user', 'song')


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code', 'host', 'is_active', 'member_count', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'code', 'host__username')
    ordering = ('-created_at',)
    list_per_page = 30
    readonly_fields = ('created_at',)
    raw_id_fields = ('host',)
    
    def member_count(self, obj):
        return obj.members.count()
    member_count.short_description = 'メンバー数'


@admin.register(ClassroomMembership)
class ClassroomMembershipAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'classroom', 'joined_at')
    list_filter = ('joined_at',)
    search_fields = ('user__username', 'classroom__name')
    ordering = ('-joined_at',)
    list_per_page = 50
    readonly_fields = ('joined_at',)
    raw_id_fields = ('user', 'classroom')


@admin.register(ClassroomSong)
class ClassroomSongAdmin(admin.ModelAdmin):
    list_display = ('id', 'classroom', 'song', 'shared_by', 'shared_at')
    list_filter = ('shared_at',)
    search_fields = ('classroom__name', 'song__title', 'shared_by__username')
    ordering = ('-shared_at',)
    list_per_page = 50
    readonly_fields = ('shared_at',)
    raw_id_fields = ('classroom', 'song', 'shared_by')


class FlashcardInline(admin.TabularInline):
    """フラッシュカードをデッキ詳細画面にインライン表示"""
    model = Flashcard
    extra = 0
    readonly_fields = ('created_at',)
    fields = ('term', 'definition', 'is_selected', 'mastery_level', 'order', 'created_at')


@admin.register(FlashcardDeck)
class FlashcardDeckAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'user', 'card_count', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('title', 'user__username')
    ordering = ('-updated_at',)
    list_per_page = 30
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('user', 'source_song')
    inlines = [FlashcardInline]
    
    def card_count(self, obj):
        return obj.flashcards.count()
    card_count.short_description = 'カード数'


@admin.register(Flashcard)
class FlashcardAdmin(admin.ModelAdmin):
    list_display = ('id', 'term', 'definition_short', 'deck', 'is_selected', 'mastery_level', 'created_at')
    list_filter = ('is_selected', 'mastery_level', 'created_at')
    search_fields = ('term', 'definition', 'deck__title')
    ordering = ('-created_at',)
    list_per_page = 50
    readonly_fields = ('created_at',)
    raw_id_fields = ('deck',)
    
    def definition_short(self, obj):
        return obj.definition[:80] + '...' if len(obj.definition) > 80 else obj.definition
    definition_short.short_description = '定義'


@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'machine_name', 'status', 'model_name', 'current_epoch', 'total_epochs', 'train_loss', 'eval_loss', 'updated_at')
    list_filter = ('status', 'machine_name')
    search_fields = ('machine_name', 'model_name')
    readonly_fields = ('api_key', 'created_at', 'updated_at')
    ordering = ('-updated_at',)
    list_per_page = 20


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ('key', 'get_key_display', 'updated_by', 'updated_at')
    list_display_links = ('key',)
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('updated_by',)
    ordering = ('key',)
    list_per_page = 20

    def get_key_display(self, obj):
        return obj.get_key_display()
    get_key_display.short_description = '名前'


@admin.register(TrainingData)
class TrainingDataAdmin(admin.ModelAdmin):
    list_display = ('id', 'data_hash', 'short_input', 'created_at', 'updated_at')
    search_fields = ('input_text', 'output_text', 'data_hash')
    readonly_fields = ('data_hash', 'created_at', 'updated_at')
    list_per_page = 50
    ordering = ('id',)

    def short_input(self, obj):
        return obj.input_text[:60] + '...' if len(obj.input_text) > 60 else obj.input_text
    short_input.short_description = 'Input'
