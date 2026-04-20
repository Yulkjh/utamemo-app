"""楽曲CRUD系ビュー（作成・一覧・削除・タイトル更新・公開設定・タグ・再作成）"""
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, CreateView, TemplateView
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.db.models import Q, Count, Sum, F
import json
import logging

from ..models import Song, Lyrics, UploadedImage, Tag, PlayHistory, Like, Favorite
from ..forms import SongCreateForm, SongPrivacyForm
from ..content_filter import check_text_for_inappropriate_content, check_name_for_inappropriate_content

logger = logging.getLogger(__name__)


class CreateSongView(LoginRequiredMixin, CreateView):

    """楽曲作成ビュー"""
    model = Song
    form_class = SongCreateForm
    template_name = 'songs/create_song.html'
    success_url = reverse_lazy('songs:my_songs')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # モデル別の残り使用可能回数を取得
        model_remaining = self.request.user.get_remaining_model_usage()
        context['model_remaining'] = model_remaining
        
        # 次月1日のリセット日を計算
        from django.utils import timezone
        import calendar
        now = timezone.now()
        _, last_day = calendar.monthrange(now.year, now.month)
        if now.month == 12:
            next_reset = now.replace(year=now.year + 1, month=1, day=1)
        else:
            next_reset = now.replace(month=now.month + 1, day=1)
        days_until_reset = (next_reset.date() - now.date()).days
        context['next_reset_date'] = next_reset
        context['days_until_reset'] = days_until_reset
        
        user = self.request.user
        # V8の残りで判定（全プラン共通）
        v8_remaining = model_remaining.get('v8', 0)
        context['free_plan_remaining'] = v8_remaining
        context['free_plan_limit_reached'] = v8_remaining == 0
        context['paid_plan_all_exhausted'] = v8_remaining == 0
        
        # セッションからプリフィルデータを取得（再生成時）
        context['prefill_music_prompt'] = self.request.session.pop('prefill_music_prompt', '')
        
        return context
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        
        extracted_text = self.request.session.get('extracted_text', '')
        
        if self.request.method == 'POST':
            generated_lyrics = self.request.POST.get('generated_lyrics', '')
            if not generated_lyrics:
                generated_lyrics = self.request.session.get('generated_lyrics', '')
            if generated_lyrics:
                kwargs['generated_lyrics'] = generated_lyrics
        
        kwargs['extracted_text'] = extracted_text
        return kwargs
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.artist = self.request.user.username  # アーティスト名をユーザー名に設定
        form.instance.is_public = False
        form.instance.is_encrypted = False
        form.instance.generation_status = 'pending'
        
        generating_count = Song.objects.filter(
            generation_status__in=['pending', 'generating']
        ).count()
        form.instance.queue_position = generating_count + 1
        
        original_text = form.cleaned_data.get('original_text', '')
        title = form.cleaned_data.get('title', '')
        genre = form.cleaned_data.get('genre', 'ポップ')
        vocal_style = form.cleaned_data.get('vocal_style', 'female')
        
        # タイトルの不適切コンテンツチェック
        title_check = check_text_for_inappropriate_content(title)
        if title_check['is_inappropriate']:
            app_language = self.request.session.get('app_language', 'ja')
            self.request.session['content_violation'] = True
            self.request.session['violation_message'] = title_check['message']
            self.request.session['detected_words'] = title_check['detected_words']
            logger.warning(f"Inappropriate title detected for user {self.request.user.id}: {title_check['detected_words']}")
            return redirect('songs:content_violation')
        
        # カスタム音楽プロンプトを取得
        music_prompt = self.request.POST.get('music_prompt', '').strip()
        form.instance.music_prompt = music_prompt
        
        # AIモデルはV8（プレミアム）に固定
        mureka_model = 'mureka-v8'
        
        # 使用制限のチェック
        if not self.request.user.can_use_model('v8'):
            app_language = self.request.session.get('app_language', 'ja')
            if app_language == 'en':
                messages.error(self.request, 'You have reached your monthly song creation limit.')
            elif app_language == 'zh':
                messages.error(self.request, '您已达到本月歌曲创建上限。')
            else:
                messages.error(self.request, '今月の楽曲作成上限に達しました。')
            return redirect('users:upgrade')
        
        form.instance.mureka_model = mureka_model
        
        generated_lyrics = self.request.POST.get('generated_lyrics', '')
        if not generated_lyrics:
            generated_lyrics = self.request.session.get('generated_lyrics', '')
        
        # 歌詞をそのまま使用（AI変換しない）
        if not generated_lyrics or len(generated_lyrics.strip()) == 0:
            app_language = self.request.session.get('app_language', 'ja')
            if app_language == 'en':
                messages.error(self.request, 'Lyrics are empty.')
            elif app_language == 'zh':
                messages.error(self.request, '歌词为空。')
            elif app_language == 'es':
                messages.error(self.request, 'Las letras están vacías.')
            elif app_language == 'de':
                messages.error(self.request, 'Der Liedtext ist leer.')
            else:
                messages.error(self.request, '歌詞が入力されていません。')
            return redirect('songs:lyrics_confirmation')
        
        # 歌詞の不適切コンテンツチェック
        content_check = check_text_for_inappropriate_content(generated_lyrics)
        if content_check['is_inappropriate']:
            app_language = self.request.session.get('app_language', 'ja')
            self.request.session['content_violation'] = True
            self.request.session['violation_message'] = content_check['message']
            self.request.session['detected_words'] = content_check['detected_words']
            logger.warning(f"Inappropriate lyrics detected for user {self.request.user.id}: {content_check['detected_words']}")
            return redirect('songs:content_violation')
        
        lyrics_content = generated_lyrics
        
        response = super().form_valid(form)
        
        Lyrics.objects.create(
            song=self.object,
            content=lyrics_content,
            original_text=original_text or ''
        )
        
        # アップロード画像をSongに関連付け（生成完了後に削除するため）
        uploaded_image_id = self.request.session.get('uploaded_image_id')
        if uploaded_image_id:
            try:
                uploaded_image = UploadedImage.objects.get(id=uploaded_image_id, user=self.request.user)
                self.object.source_image = uploaded_image
                self.object.save(update_fields=['source_image'])
            except UploadedImage.DoesNotExist:
                pass
        
        from ..queue_manager import queue_manager
        
        queue_manager.add_to_queue(
            song_id=self.object.pk,
            lyrics_content=lyrics_content,
            title=title,
            genre=genre,
            vocal_style=vocal_style
        )
        
        # フラッシュカード同時作成
        create_flashcards = self.request.POST.get('create_flashcards') == 'true'
        if create_flashcards:
            self._create_flashcards_from_session(original_text, title)
        
        app_language = self.request.session.get('app_language', 'ja')
        
        if self.object.queue_position and self.object.queue_position > 1:
            if app_language == 'en':
                messages.success(
                    self.request, 
                    f'Song added to queue. Currently {self.object.queue_position - 1} people ahead. Will be generated in order.'
                )
            elif app_language == 'zh':
                messages.success(
                    self.request, 
                    f'歌曲已加入队列。当前排在第{self.object.queue_position - 1}位。将按顺序生成。'
                )
            elif app_language == 'es':
                messages.success(
                    self.request, 
                    f'Canción añadida a la cola. Actualmente hay {self.object.queue_position - 1} personas delante. Se generará en orden.'
                )
            elif app_language == 'de':
                messages.success(
                    self.request, 
                    f'Lied zur Warteschlange hinzugefügt. Derzeit {self.object.queue_position - 1} Personen vor Ihnen. Wird der Reihe nach generiert.'
                )
            else:
                messages.success(
                    self.request, 
                    f'楽曲をキューに追加しました。現在{self.object.queue_position - 1}人待っています。順番に生成されます。'
                )
        else:
            if app_language == 'en':
                messages.success(self.request, 'Song generation started. Will be ready in 1-2 minutes.')
            elif app_language == 'zh':
                messages.success(self.request, '歌曲生成已开始。1-2分钟后完成。')
            elif app_language == 'es':
                messages.success(self.request, 'La generación de la canción ha comenzado. Estará lista en 1-2 minutos.')
            elif app_language == 'de':
                messages.success(self.request, 'Liederstellung gestartet. In 1-2 Minuten fertig.')
            else:
                messages.success(self.request, '楽曲の生成を開始しました。1〜2分で完成します。')
        
        # セッションから楽曲作成関連データをすべてクリア
        keys_to_clear = [
            'extracted_text', 'extracted_texts', 'generated_lyrics',
            'uploaded_image_id', 'uploaded_image_ids', 'custom_request',
        ]
        for key in keys_to_clear:
            self.request.session.pop(key, None)
        
        return response
    
    def get_success_url(self):
        return reverse_lazy('songs:song_generating', kwargs={'pk': self.object.pk})
    
    def _create_flashcards_from_session(self, original_text, song_title):
        """セッションの画像/テキストからフラッシュカードデッキを作成"""
        from ..models import FlashcardDeck, Flashcard, UploadedImage as UImage
        from ..ai_services import GeminiFlashcardExtractor, GeminiOCR
        
        try:
            extractor = GeminiFlashcardExtractor()
            all_terms = []
            source_image_obj = None
            source_text = original_text or ''
            
            # 1. 画像がある場合 → 画像から直接抽出を試みる
            uploaded_image_ids = self.request.session.get('uploaded_image_ids', [])
            if uploaded_image_ids:
                for img_id in uploaded_image_ids:
                    try:
                        uploaded = UImage.objects.get(id=img_id, user=self.request.user)
                        if source_image_obj is None:
                            source_image_obj = uploaded
                        terms = extractor.extract_terms_from_image(uploaded.image)
                        if terms:
                            all_terms.extend(terms)
                    except Exception as img_err:
                        logger.warning(f"Flashcard image extraction error: {img_err}")
            
            # 画像ID が1つの場合のフォールバック
            if not uploaded_image_ids:
                single_id = self.request.session.get('uploaded_image_id')
                if single_id:
                    try:
                        uploaded = UImage.objects.get(id=single_id, user=self.request.user)
                        source_image_obj = uploaded
                        terms = extractor.extract_terms_from_image(uploaded.image)
                        if terms:
                            all_terms.extend(terms)
                    except Exception as img_err:
                        logger.warning(f"Flashcard single image error: {img_err}")
            
            # 2. 画像から取れなかった場合 → テキストから抽出
            if not all_terms and source_text:
                terms = extractor.extract_terms_from_text(source_text)
                if terms:
                    all_terms.extend(terms)
            
            if not all_terms:
                logger.info("Flashcard: No terms extracted, skipping deck creation")
                return
            
            # 重複除去
            seen = set()
            unique_terms = []
            for t in all_terms:
                key = t['term'].strip().lower()
                if key not in seen:
                    seen.add(key)
                    unique_terms.append(t)
            
            # デッキ作成
            deck_title = f'{song_title} の暗記カード' if song_title else 'テスト対策カード'
            deck = FlashcardDeck.objects.create(
                user=self.request.user,
                title=deck_title,
                source_song=self.object,
                source_image=source_image_obj,
                source_text=source_text[:5000] if source_text else '',
            )
            
            # カードを作成（highはデフォルト選択、選択画面へ誘導）
            for i, t in enumerate(unique_terms):
                importance = t.get('importance', 'normal')
                Flashcard.objects.create(
                    deck=deck,
                    term=t['term'],
                    definition=t['definition'],
                    importance=importance,
                    is_selected=(importance == 'high'),
                    order=i,
                )
            
            deck.update_card_count()
            
            # セッションにデッキIDを保存（song_generating画面で選択画面へのリンク表示用）
            self.request.session['created_flashcard_deck_id'] = deck.pk
            
            logger.info(f"Flashcard deck created: '{deck_title}' with {deck.card_count} cards for user {self.request.user.id}")
            
        except Exception as e:
            logger.error(f"Flashcard creation error: {e}", exc_info=True)
            # フラッシュカード作成失敗しても楽曲生成は続行


class MySongsView(LoginRequiredMixin, ListView):
    """MY楽曲一覧ビュー"""
    model = Song
    template_name = 'songs/my_songs.html'
    context_object_name = 'songs'
    paginate_by = 12
    
    def get_queryset(self):
        return Song.objects.filter(
            created_by=self.request.user
        ).exclude(
            generation_status='failed'
        ).select_related('created_by').prefetch_related('tags').order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 一度のクエリで統計情報を取得（最適化）
        stats = Song.objects.filter(
            created_by=self.request.user
        ).exclude(
            generation_status='failed'
        ).aggregate(
            total_count=Count('id'),
            public_count=Count('id', filter=Q(is_public=True)),
            private_count=Count('id', filter=Q(is_public=False))
        )
        
        context['total_count'] = stats['total_count']
        context['public_count'] = stats['public_count']
        context['private_count'] = stats['private_count']
        
        # 再生履歴を辞書として取得（一度のクエリ、必要なフィールドのみ）
        play_histories = {
            h.song_id: {'play_count': h.play_count, 'last_played_at': h.last_played_at}
            for h in PlayHistory.objects.filter(user=self.request.user).only('song_id', 'play_count', 'last_played_at')
        }
        context['play_histories'] = play_histories
        
        # 総再生回数
        total_plays = PlayHistory.objects.filter(user=self.request.user).aggregate(total=Sum('play_count'))
        context['total_play_count'] = total_plays['total'] or 0
        
        return context


@login_required
@require_POST
def delete_song(request, pk):
    """楽曲削除機能"""
    song = get_object_or_404(Song, pk=pk)
    
    # 作成者のみ削除可能
    if song.created_by != request.user:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': '削除権限がありません'}, status=403)
        messages.error(request, '削除権限がありません')
        return redirect('songs:my_songs')
    
    try:
        song_title = song.title
        song.delete()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        
        messages.success(request, f'「{song_title}」を削除しました')
        return redirect('songs:my_songs')
    except Exception as e:
        logger.error(f"Song delete error: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': '削除に失敗しました'}, status=500)
        messages.error(request, '削除に失敗しました')
        return redirect('songs:my_songs')


@login_required
def toggle_song_privacy(request, pk):
    """楽曲の公開/非公開を切り替え"""
    song = get_object_or_404(Song, pk=pk, created_by=request.user)
    app_language = request.session.get('app_language', 'ja')
    
    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                data = json.loads(request.body)
                new_is_public = data.get('is_public', not song.is_public)
                
                # 無料ユーザーは公開設定を許可しない
                if new_is_public and not request.user.is_starter:
                    return JsonResponse({
                        'success': False,
                        'error': 'Public sharing is available for paid plans only.'
                    }, status=403)
                
                song.is_public = new_is_public
                song.save()
                if app_language == 'en':
                    status = "public" if song.is_public else "private"
                    msg = f'Song "{song.title}" set to {status}.'
                elif app_language == 'zh':
                    status = "公开" if song.is_public else "私密"
                    msg = f'歌曲「{song.title}」已设为{status}。'
                else:
                    status = "公開" if song.is_public else "プライベート"
                    msg = f'楽曲「{song.title}」を{status}に設定しました。'
                return JsonResponse({
                    'success': True,
                    'is_public': song.is_public,
                    'message': msg
                })
            except Exception as e:
                logger.error(f"Toggle privacy error for song {song.pk}: {e}")
                return JsonResponse({
                    'success': False,
                    'error': 'An error occurred. Please try again.'
                })
        else:
            new_is_public = not song.is_public
            
            # 無料ユーザーは公開設定を許可しない
            if new_is_public and not request.user.is_starter:
                if app_language == 'en':
                    messages.error(request, 'Public sharing is available for paid plans only.')
                elif app_language == 'zh':
                    messages.error(request, '公开分享仅限付费用户使用。')
                else:
                    messages.error(request, '楽曲の公開は有料プラン限定の機能です。')
                return redirect('songs:my_songs')
            
            song.is_public = new_is_public
            song.save()
            if app_language == 'en':
                messages.success(request, f'Privacy settings for "{song.title}" updated.')
            elif app_language == 'zh':
                messages.success(request, f'「{song.title}」的隐私设置已更改。')
            else:
                messages.success(request, f'楽曲「{song.title}」の公開設定を変更しました。')
    return redirect('songs:my_songs')


class SongPrivacyView(LoginRequiredMixin, TemplateView):
    """楽曲プライバシー設定ビュー"""
    template_name = 'songs/song_privacy.html'
    
    def get_object(self):
        return get_object_or_404(Song, pk=self.kwargs['pk'], created_by=self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        song = self.get_object()
        context['song'] = song
        context['form'] = SongPrivacyForm(instance=song)
        return context
    
    def post(self, request, *args, **kwargs):
        song = self.get_object()
        form = SongPrivacyForm(request.POST, instance=song)
        if form.is_valid():
            form.save()
            app_language = request.session.get('app_language', 'ja')
            if app_language == 'en':
                messages.success(request, 'Song settings updated.')
            elif app_language == 'zh':
                messages.success(request, '歌曲设置已更新。')
            else:
                messages.success(request, f'楽曲の設定を更新しました。')
            return redirect('songs:song_detail', pk=song.pk)
        context = self.get_context_data(**kwargs)
        context['form'] = form
        return self.render_to_response(context)


@login_required
def add_tag_to_song(request, pk):
    """楽曲にタグを追加"""
    import html
    import re
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=400)
    
    song = get_object_or_404(Song, pk=pk)
    
    if request.user != song.created_by:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    
    try:
        tag_name = data.get('tag_name', '').strip()
        
        if not tag_name:
            return JsonResponse({'success': False, 'error': 'Tag name is required'})
        
        # サニタイズ：HTMLエスケープ、危険な文字を削除
        tag_name = html.escape(tag_name)
        tag_name = re.sub(r'[<>"\'/\\;]', '', tag_name)
        
        # 長さ制限
        if len(tag_name) > 50:
            return JsonResponse({'success': False, 'error': 'Tag name too long (max 50 characters)'})
        
        tag, created = Tag.objects.get_or_create(name=tag_name)
        
        song.tags.add(tag)
        
        return JsonResponse({
            'success': True,
            'tag_id': tag.id,
            'tag_name': tag.name
        })
    
    except Exception as e:
        logger.error(f"Error adding tag to song {pk}: {e}")
        return JsonResponse({'success': False, 'error': 'An error occurred.'}, status=500)


@login_required
def remove_tag_from_song(request, pk):
    """楽曲からタグを削除"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=400)
    
    song = get_object_or_404(Song, pk=pk)
    
    if request.user != song.created_by:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    try:
        data = json.loads(request.body)
        tag_id = data.get('tag_id')
        
        if not tag_id:
            return JsonResponse({'success': False, 'error': 'Tag ID is required'})
        
        tag = get_object_or_404(Tag, id=tag_id)
        song.tags.remove(tag)
        
        return JsonResponse({'success': True})
    
    except Exception as e:
        logger.error(f"Error removing tag from song {pk}: {e}")
        return JsonResponse({'success': False, 'error': 'An error occurred.'}, status=500)


@login_required
def update_song_title(request, pk):
    """楽曲のタイトルを更新"""
    import html
    import re
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=400)
    
    song = get_object_or_404(Song, pk=pk)
    
    if request.user != song.created_by:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    
    try:
        new_title = data.get('title', '').strip()
        
        if not new_title:
            return JsonResponse({'success': False, 'error': 'Title is required'})
        
        if len(new_title) > 200:
            return JsonResponse({'success': False, 'error': 'Title is too long (max 200 characters)'})
        
        # サニタイズ：HTMLエスケープ、危険な文字を削除
        new_title = html.escape(new_title)
        new_title = re.sub(r'[<>\"\\;]', '', new_title)
        
        song.title = new_title
        song.save()
        
        return JsonResponse({
            'success': True,
            'title': new_title
        })
    
    except Exception as e:
        logger.error(f"Error updating title for song {pk}: {e}")
        return JsonResponse({'success': False, 'error': 'An error occurred.'}, status=500)


@login_required
def recreate_with_lyrics(request, pk):
    """同じ歌詞で新しい楽曲を作成（歌詞をセッションに保存して作成画面へ遷移）"""
    song = get_object_or_404(Song, pk=pk)
    
    # 歌詞を取得
    lyrics = song.lyrics
    if not lyrics:
        app_language = request.session.get('app_language', 'ja')
        if app_language == 'en':
            messages.error(request, 'This song has no lyrics.')
        elif app_language == 'zh':
            messages.error(request, '这首歌曲没有歌词。')
        else:
            messages.error(request, 'この楽曲には歌詞がありません。')
        return redirect('songs:song_detail', pk=pk)
    
    # 歌詞とプロンプトをセッションに保存
    request.session['generated_lyrics'] = lyrics.content
    request.session['extracted_text'] = ''  # 元テキストはクリア
    request.session['prefill_music_prompt'] = song.music_prompt or ''
    
    # 楽曲作成画面にリダイレクト（歌詞確認画面をスキップ）
    return redirect('songs:lyrics_confirmation')
