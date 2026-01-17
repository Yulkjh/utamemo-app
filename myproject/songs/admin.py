from django.contrib import admin
from .models import Song, Lyrics, Like, Favorite, Comment, UploadedImage


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = ('title', 'artist', 'created_by', 'genre', 'is_public', 'likes_count', 'created_at')
    list_filter = ('genre', 'is_public', 'created_at', 'created_by')
    search_fields = ('title', 'artist', 'created_by__username')
    ordering = ('-created_at',)


@admin.register(Lyrics)
class LyricsAdmin(admin.ModelAdmin):
    list_display = ('song', 'created_at')
    search_fields = ('song__title', 'content')
    ordering = ('-created_at',)


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ('user', 'song', 'created_at')
    list_filter = ('created_at',)
    ordering = ('-created_at',)


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'song', 'created_at')
    list_filter = ('created_at',)
    ordering = ('-created_at',)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('user', 'song', 'content', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('content', 'user__username', 'song__title')
    ordering = ('-created_at',)


@admin.register(UploadedImage)
class UploadedImageAdmin(admin.ModelAdmin):
    list_display = ('user', 'processed', 'created_at')
    list_filter = ('processed', 'created_at')
    ordering = ('-created_at',)
