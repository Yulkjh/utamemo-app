"""ソーシャル機能ビュー（いいね・お気に入り・再生・コメント）"""
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import F
import logging

from ..models import Song, Like, Favorite, Comment, PlayHistory
from ..forms import CommentForm

logger = logging.getLogger(__name__)


@login_required
@require_POST
def like_song(request, pk):
    """楽曲いいね機能"""
    from django.db import transaction
    
    song = get_object_or_404(Song, pk=pk)
    
    with transaction.atomic():
        # select_for_updateでデッドロック防止
        song = Song.objects.select_for_update().get(pk=pk)
        like, created = Like.objects.get_or_create(user=request.user, song=song)
        
        if not created:
            like.delete()
            song.likes_count = max(0, song.likes_count - 1)
            liked = False
        else:
            song.likes_count += 1
            liked = True
        
        song.save()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'liked': liked,
            'likes_count': song.likes_count
        })
    
    return redirect('songs:song_detail', pk=pk)


@login_required
@require_POST
def favorite_song(request, pk):
    """楽曲お気に入り機能"""
    from django.db import transaction

    song = get_object_or_404(Song, pk=pk)
    
    with transaction.atomic():
        favorite, created = Favorite.objects.get_or_create(user=request.user, song=song)
        
        if not created:
            favorite.delete()
            favorited = False
        else:
            favorited = True
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'favorited': favorited})
    
    return redirect('songs:song_detail', pk=pk)


@require_POST
def record_play(request, pk):
    """再生回数を記録するAPI"""
    song = get_object_or_404(Song, pk=pk)
    
    # F()式でレースコンディション防止
    Song.objects.filter(pk=pk).update(total_plays=F('total_plays') + 1)
    song.refresh_from_db()
    
    # ログインユーザーの場合は個人の再生履歴も更新
    my_play_count = 0
    if request.user.is_authenticated:
        play_history, created = PlayHistory.objects.get_or_create(
            user=request.user,
            song=song,
            defaults={'play_count': 1}
        )
        
        if not created:
            PlayHistory.objects.filter(pk=play_history.pk).update(play_count=F('play_count') + 1)
            play_history.refresh_from_db()
        
        my_play_count = play_history.play_count
    
    return JsonResponse({
        'success': True,
        'total_plays': song.total_plays,
        'my_play_count': my_play_count
    })


@login_required
def add_comment(request, pk):
    """コメント追加機能"""
    song = get_object_or_404(Song, pk=pk)
    
    if request.method == 'POST':
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.user = request.user
            comment.song = song
            comment.save()
            app_language = request.session.get('app_language', 'ja')
            if app_language == 'en':
                messages.success(request, 'Comment posted!')
            elif app_language == 'zh':
                messages.success(request, '评论已发布！')
            else:
                messages.success(request, 'コメントを投稿しました！')
    
    return redirect('songs:song_detail', pk=pk)
