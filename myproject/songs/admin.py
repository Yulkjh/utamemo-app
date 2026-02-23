from django.contrib import admin
from .models import (
    Song, Lyrics, Like, Favorite, Comment, UploadedImage,
    Tag, PlayHistory, Classroom, ClassroomMembership, ClassroomSong,
)


class LyricsInline(admin.StackedInline):
    """歌詞をSong詳細画面にインライン表示"""
    model = Lyrics
    extra = 0
    readonly_fields = ('created_at',)


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'title', 'artist', 'created_by', 'genre', 'vocal_style',
        'mureka_model', 'generation_status', 'is_public', 'is_encrypted',
        'likes_count', 'total_plays', 'retry_count',
        'karaoke_status', 'created_at',
    )
    list_filter = (
        'generation_status', 'is_public', 'is_encrypted', 'genre',
        'vocal_style', 'mureka_model', 'karaoke_status', 'created_at',
    )
    search_fields = ('title', 'artist', 'created_by__username', 'music_prompt', 'error_message')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'started_at', 'completed_at', 'likes_count', 'total_plays')
    inlines = [LyricsInline]
    
    fieldsets = (
        ('基本情報', {
            'fields': ('title', 'artist', 'genre', 'vocal_style', 'tags')
        }),
        ('AI生成設定', {
            'fields': ('mureka_model', 'music_prompt', 'reference_song', 'reference_audio_url')
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
            'fields': ('is_public', 'is_encrypted', 'created_by', 'source_image')
        }),
        ('統計', {
            'fields': ('likes_count', 'total_plays')
        }),
        ('日時', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(Lyrics)
class LyricsAdmin(admin.ModelAdmin):
    list_display = ('id', 'song', 'has_lrc', 'created_at')
    search_fields = ('song__title', 'content', 'original_text')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    
    def has_lrc(self, obj):
        return bool(obj.lrc_data)
    has_lrc.boolean = True
    has_lrc.short_description = 'LRCデータ'


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'song_count', 'created_at')
    search_fields = ('name',)
    ordering = ('name',)
    
    def song_count(self, obj):
        return obj.songs.count()
    song_count.short_description = '楽曲数'


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'song', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'song__title')
    ordering = ('-created_at',)


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'song', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'song__title')
    ordering = ('-created_at',)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'song', 'content_short', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('content', 'user__username', 'song__title')
    ordering = ('-created_at',)
    
    def content_short(self, obj):
        return obj.content[:80] + '...' if len(obj.content) > 80 else obj.content
    content_short.short_description = 'コメント'


@admin.register(UploadedImage)
class UploadedImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'processed', 'has_text', 'created_at')
    list_filter = ('processed', 'created_at')
    search_fields = ('user__username', 'extracted_text')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    
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
    readonly_fields = ('last_played_at', 'created_at')


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code', 'host', 'is_active', 'member_count', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'code', 'host__username')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    
    def member_count(self, obj):
        return obj.members.count()
    member_count.short_description = 'メンバー数'


@admin.register(ClassroomMembership)
class ClassroomMembershipAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'classroom', 'joined_at')
    list_filter = ('joined_at',)
    search_fields = ('user__username', 'classroom__name')
    ordering = ('-joined_at',)
    readonly_fields = ('joined_at',)


@admin.register(ClassroomSong)
class ClassroomSongAdmin(admin.ModelAdmin):
    list_display = ('id', 'classroom', 'song', 'shared_by', 'shared_at')
    list_filter = ('shared_at',)
    search_fields = ('classroom__name', 'song__title', 'shared_by__username')
    ordering = ('-shared_at',)
    readonly_fields = ('shared_at',)
