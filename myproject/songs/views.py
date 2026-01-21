from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, CreateView, TemplateView
from django.views.generic.edit import FormView
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST
from django.db.models import Q, Count, F
from django.conf import settings
import json
import logging

from .models import Song, Like, Favorite, Comment, UploadedImage, Lyrics, PlayHistory, Tag
from .forms import SongCreateForm, ImageUploadForm, CommentForm, SongPrivacyForm
from .ai_services import GeminiLyricsGenerator, GeminiOCR, MurekaAIGenerator

# ロガー設定
logger = logging.getLogger(__name__)


def hiragana_to_katakana(text):
    """ひらがなをカタカナに変換"""
    return ''.join(
        chr(ord(char) + 96) if 'ぁ' <= char <= 'ゖ' else char
        for char in text
    )

def katakana_to_hiragana(text):
    """カタカナをひらがなに変換"""
    return ''.join(
        chr(ord(char) - 96) if 'ァ' <= char <= 'ヶ' else char
        for char in text
    )


class HomeView(TemplateView):
    """ホームページビュー"""
    template_name = 'songs/home.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            # 生成完了した公開楽曲のみ表示
            base_query = Song.objects.filter(
                is_public=True,
                generation_status='completed'
            ).select_related('created_by')
            
            context['recent_songs'] = base_query.order_by('-created_at')[:6]
            context['popular_songs'] = base_query.order_by('-likes_count', '-created_at')[:6]
        except Exception as e:
            logger.error(f"HomeView query error: {e}")
            context['recent_songs'] = []
            context['popular_songs'] = []
        return context


class SongListView(ListView):
    """楽曲一覧ビュー"""
    model = Song
    template_name = 'songs/song_list.html'
    context_object_name = 'songs'
    paginate_by = 12
    
    def get_queryset(self):
        # 生成完了した公開楽曲のみ表示
        queryset = Song.objects.filter(
            is_public=True,
            generation_status='completed'
        ).select_related('created_by').prefetch_related('tags')
        
        search_query = self.request.GET.get('q', '').strip()
        if search_query:
            # ひらがな・カタカナの両方で検索
            hiragana_query = katakana_to_hiragana(search_query)
            katakana_query = hiragana_to_katakana(search_query)
            
            queryset = queryset.filter(
                Q(title__icontains=search_query) |
                Q(title__icontains=hiragana_query) |
                Q(title__icontains=katakana_query) |
                Q(artist__icontains=search_query) |
                Q(artist__icontains=hiragana_query) |
                Q(artist__icontains=katakana_query) |
                Q(genre__icontains=search_query) |
                Q(tags__name__icontains=search_query) |
                Q(tags__name__icontains=hiragana_query) |
                Q(tags__name__icontains=katakana_query)
            ).distinct()
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        if user.is_authenticated:
            # ユーザーがいいねした曲のIDリスト
            context['user_liked_songs'] = list(
                user.likes.values_list('song_id', flat=True)
            )
            # ユーザーがお気に入りした曲のIDリスト
            context['user_favorite_songs'] = list(
                user.favorites.values_list('song_id', flat=True)
            )
        else:
            context['user_liked_songs'] = []
            context['user_favorite_songs'] = []
        
        return context


class SongDetailView(DetailView):
    """楽曲詳細ビュー"""
    model = Song
    template_name = 'songs/song_detail.html'
    context_object_name = 'song'
    
    def get_queryset(self):
        return Song.objects.select_related('created_by', 'lyrics').prefetch_related('tags')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        song = self.object
        
        # 歌詞情報の安全な取得
        try:
            if hasattr(song, 'lyrics') and song.lyrics:
                context['lyrics_content'] = song.lyrics.content or ''
                context['original_text'] = song.lyrics.original_text or ''
                context['decrypted_lyrics'] = song.lyrics.content or ''
                context['decrypted_original_text'] = song.lyrics.original_text or ''
            else:
                context['lyrics_content'] = ''
                context['original_text'] = ''
                context['decrypted_lyrics'] = ''
                context['decrypted_original_text'] = ''
        except Exception:
            context['lyrics_content'] = ''
            context['original_text'] = ''
            context['decrypted_lyrics'] = ''
            context['decrypted_original_text'] = ''
        
        # 認証ユーザーの情報
        if self.request.user.is_authenticated:
            context['is_liked'] = Like.objects.filter(
                user=self.request.user, song=song
            ).exists()
            context['is_favorited'] = Favorite.objects.filter(
                user=self.request.user, song=song
            ).exists()
            # ユーザーの再生回数を取得
            try:
                play_history = PlayHistory.objects.get(user=self.request.user, song=song)
                context['my_play_count'] = play_history.play_count
            except PlayHistory.DoesNotExist:
                context['my_play_count'] = 0
        else:
            context['is_liked'] = False
            context['is_favorited'] = False
            context['my_play_count'] = 0
            
        context['comments'] = Comment.objects.filter(song=song).select_related('user')
        context['comment_form'] = CommentForm()
        
        # 関連楽曲を取得（同じタグまたは似た名前の公開楽曲）
        try:
            context['related_songs'] = self._get_related_songs(song)
        except Exception:
            context['related_songs'] = []
        
        return context
    
    def _get_related_songs(self, song):
        """関連楽曲を取得 - ジャンル、タグ、作成者で関連性を計算"""
        from django.db.models import Case, When, IntegerField, Value
        
        # 自分自身を除外し、公開済みの楽曲のみ
        related = Song.objects.filter(
            is_public=True,
            generation_status='completed'
        ).exclude(pk=song.pk)
        
        # スコアリングで関連度を計算
        song_tags = song.tags.all()
        tag_ids = list(song_tags.values_list('id', flat=True)) if song_tags.exists() else []
        
        # 同じジャンルかどうか
        genre_match = Case(
            When(genre=song.genre, then=Value(10)) if song.genre else When(pk__isnull=True, then=Value(0)),
            default=Value(0),
            output_field=IntegerField()
        )
        
        # 同じ作成者かどうか
        creator_match = Case(
            When(created_by=song.created_by, then=Value(5)),
            default=Value(0),
            output_field=IntegerField()
        )
        
        # タグの一致数
        if tag_ids:
            related = related.annotate(
                matching_tags=Count('tags', filter=Q(tags__id__in=tag_ids)),
                genre_score=genre_match,
                creator_score=creator_match
            ).annotate(
                relevance_score=F('matching_tags') * 3 + F('genre_score') + F('creator_score')
            ).order_by('-relevance_score', '-likes_count', '-created_at')
        else:
            # タグがない場合はジャンルと作成者でスコアリング
            related = related.annotate(
                genre_score=genre_match,
                creator_score=creator_match
            ).annotate(
                relevance_score=F('genre_score') + F('creator_score')
            ).order_by('-relevance_score', '-likes_count', '-created_at')
        
        return related.select_related('created_by')[:5]


class CreateSongView(LoginRequiredMixin, CreateView):
    """楽曲作成ビュー"""
    model = Song
    form_class = SongCreateForm
    template_name = 'songs/create_song.html'
    success_url = reverse_lazy('songs:song_list')
    
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
        
        # カスタム音楽プロンプトを取得
        music_prompt = self.request.POST.get('music_prompt', '').strip()
        form.instance.music_prompt = music_prompt
        
        # リファレンス曲を取得
        reference_song = self.request.POST.get('reference_song', '').strip()
        form.instance.reference_song = reference_song
        
        # AIモデルを取得
        mureka_model = self.request.POST.get('mureka_model', 'mureka-7.5').strip()
        valid_models = ['mureka-o2', 'mureka-7.6', 'mureka-7.5']
        if mureka_model not in valid_models:
            mureka_model = 'mureka-7.5'
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
            else:
                messages.error(self.request, '歌詞が入力されていません。')
            return redirect('songs:lyrics_confirmation')
        
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
        
        from .queue_manager import queue_manager
        
        queue_manager.add_to_queue(
            song_id=self.object.pk,
            lyrics_content=lyrics_content,
            title=title,
            genre=genre,
            vocal_style=vocal_style
        )
        
        # セッションからリファレンス音声情報をクリア
        if 'reference_audio_path' in self.request.session:
            del self.request.session['reference_audio_path']
        
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
            else:
                messages.success(
                    self.request, 
                    f'楽曲をキューに追加しました。現在{self.object.queue_position - 1}人待っています。順番に生成されます。'
                )
        else:
            if app_language == 'en':
                messages.success(self.request, 'Song generation started. Will be ready in 1-2 minutes. Please refresh the page when complete.')
            elif app_language == 'zh':
                messages.success(self.request, '歌曲生成已开始。1-2分钟后完成。完成后请刷新页面。')
            else:
                messages.success(self.request, '楽曲の生成を開始しました。1〜2分で完成します。完成したらページを更新してください。')
        
        if 'extracted_text' in self.request.session:
            del self.request.session['extracted_text']
        if 'generated_lyrics' in self.request.session:
            del self.request.session['generated_lyrics']
        if 'uploaded_image_id' in self.request.session:
            del self.request.session['uploaded_image_id']
        
        return response
    
    def get_success_url(self):
        return reverse_lazy('songs:song_detail', kwargs={'pk': self.object.pk})


def validate_uploaded_file(file, app_language='ja'):
    """アップロードされたファイルを検証"""
    errors = []
    file_name = file.name.lower()
    
    # ファイルタイプの確認
    is_pdf = file_name.endswith('.pdf')
    is_image = any(file_name.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])
    
    if not is_pdf and not is_image:
        if app_language == 'en':
            errors.append(f'{file.name}: Unsupported file format')
        elif app_language == 'zh':
            errors.append(f'{file.name}：不支持的文件格式')
        else:
            errors.append(f'{file.name}: 対応していないファイル形式です')
        return errors
    
    # ファイルサイズの確認
    max_size = getattr(settings, 'MAX_PDF_SIZE', 25 * 1024 * 1024) if is_pdf else getattr(settings, 'MAX_IMAGE_SIZE', 10 * 1024 * 1024)
    max_size_mb = max_size // (1024 * 1024)
    
    if file.size > max_size:
        if app_language == 'en':
            errors.append(f'{file.name}: File too large (max {max_size_mb}MB)')
        elif app_language == 'zh':
            errors.append(f'{file.name}：文件过大（最大{max_size_mb}MB）')
        else:
            errors.append(f'{file.name}: ファイルサイズが大きすぎます（最大{max_size_mb}MB）')
    
    # MIMEタイプの確認（追加のセキュリティ）
    content_type = file.content_type
    allowed_image_types = getattr(settings, 'ALLOWED_IMAGE_TYPES', ['image/jpeg', 'image/png', 'image/gif', 'image/webp'])
    allowed_doc_types = getattr(settings, 'ALLOWED_DOCUMENT_TYPES', ['application/pdf'])
    
    if is_pdf and content_type not in allowed_doc_types:
        if app_language == 'en':
            errors.append(f'{file.name}: Invalid PDF file')
        elif app_language == 'zh':
            errors.append(f'{file.name}：无效的PDF文件')
        else:
            errors.append(f'{file.name}: 無効なPDFファイルです')
    elif is_image and content_type not in allowed_image_types:
        if app_language == 'en':
            errors.append(f'{file.name}: Invalid image file')
        elif app_language == 'zh':
            errors.append(f'{file.name}：无效的图片文件')
        else:
            errors.append(f'{file.name}: 無効な画像ファイルです')
    
    return errors


class UploadImageView(LoginRequiredMixin, FormView):
    template_name = 'songs/upload_image.html'
    form_class = ImageUploadForm

    def form_valid(self, form):
        files = self.request.FILES.getlist('images')
        
        app_language = self.request.session.get('app_language', 'ja')
        
        if not files:
            if app_language == 'en':
                messages.error(self.request, 'No file selected.')
            elif app_language == 'zh':
                messages.error(self.request, '未选择文件。')
            else:
                messages.error(self.request, 'ファイルが選択されていません。')
            return redirect('songs:upload_image')
        
        # ファイルの検証
        validation_errors = []
        valid_files = []
        for file in files:
            file_errors = validate_uploaded_file(file, app_language)
            if file_errors:
                validation_errors.extend(file_errors)
            else:
                valid_files.append(file)
        
        if validation_errors:
            for error in validation_errors:
                messages.error(self.request, error)
        
        if not valid_files:
            return redirect('songs:upload_image')
        
        user = self.request.user
        extracted_texts = []
        uploaded_image_ids = []
        errors = []
        
        # 言語モードをセッションに保存
        # フォームからの選択がある場合はそれを使用、なければアプリ言語から自動設定
        language_mode = self.request.POST.get('language_mode', '')
        if not language_mode:
            # アプリ言語設定から自動的に言語モードを設定
            app_language = self.request.session.get('app_language', 'ja')
            if app_language == 'zh':
                language_mode = 'chinese'
            elif app_language == 'en':
                language_mode = 'english'
            else:
                language_mode = 'japanese'
        self.request.session['language_mode'] = language_mode
        
        # カスタムリクエストをセッションに保存
        custom_request = self.request.POST.get('custom_request', '').strip()
        self.request.session['custom_request'] = custom_request
        
        from .ai_services import PDFTextExtractor
        
        for file in valid_files:
            file_name = file.name.lower()
            
            try:
                if file_name.endswith('.pdf'):
                    # PDFファイルの処理
                    pdf_extractor = PDFTextExtractor()
                    extracted_text = pdf_extractor.extract_text_from_pdf(file)
                    if extracted_text:
                        extracted_texts.append(extracted_text)
                else:
                    # 画像ファイルの処理
                    uploaded = UploadedImage.objects.create(user=user, image=file)
                    try:
                        ocr_processor = GeminiOCR()
                        extracted_text = ocr_processor.extract_text_from_image(uploaded.image)
                        uploaded.extracted_text = extracted_text or ''
                        uploaded.processed = True
                        uploaded.save()
                        if extracted_text:
                            extracted_texts.append(extracted_text)
                        uploaded_image_ids.append(uploaded.id)
                    except Exception as e:
                        errors.append(f'{file.name}: OCR処理に失敗しました')
                        logger.error(f"OCR error for {file.name}: {e}")
            except Exception as e:
                errors.append(f'{file.name}: 処理に失敗しました')
                logger.error(f"File processing error for {file.name}: {e}")
        
        self.request.session['extracted_texts'] = extracted_texts
        self.request.session['uploaded_image_ids'] = uploaded_image_ids
        
        if not extracted_texts:
            if app_language == 'en':
                messages.error(self.request, 'Could not extract text. Please try another file.')
            elif app_language == 'zh':
                messages.error(self.request, '无法提取文字。请尝试其他文件。')
            else:
                messages.error(self.request, 'テキストを抽出できませんでした。別のファイルを試してください。')
            return redirect('songs:upload_image')
        
        pdf_count = sum(1 for f in valid_files if f.name.lower().endswith('.pdf'))
        image_count = len(valid_files) - pdf_count
        
        if errors:
            if app_language == 'en':
                messages.warning(self.request, f'Some files had errors: {", ".join(errors)}')
            elif app_language == 'zh':
                messages.warning(self.request, f'部分文件出错：{", ".join(errors)}')
            else:
                messages.warning(self.request, f'一部のファイルでエラーが発生しました: {", ".join(errors)}')
        
        if pdf_count > 0 and image_count > 0:
            if app_language == 'en':
                messages.success(self.request, f'Text extracted from {image_count} images and {pdf_count} PDFs')
            elif app_language == 'zh':
                messages.success(self.request, f'从{image_count}张图片和{pdf_count}个PDF中提取了文字')
            else:
                messages.success(self.request, f'{image_count}枚の画像と{pdf_count}件のPDFからテキストを抽出しました')
        elif pdf_count > 0:
            if app_language == 'en':
                messages.success(self.request, f'Text extracted from {pdf_count} PDFs')
            elif app_language == 'zh':
                messages.success(self.request, f'从{pdf_count}个PDF中提取了文字')
            else:
                messages.success(self.request, f'{pdf_count}件のPDFからテキストを抽出しました')
        else:
            if app_language == 'en':
                messages.success(self.request, f'Text extracted from {image_count} images')
            elif app_language == 'zh':
                messages.success(self.request, f'从{image_count}张图片中提取了文字')
            else:
                messages.success(self.request, f'{image_count}枚の画像からテキストを抽出しました')
        
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('songs:lyrics_confirmation')


class TextExtractionResultView(LoginRequiredMixin, TemplateView):
    """テキスト抽出結果表示ビュー"""
    template_name = 'songs/text_extraction_result.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        extracted_text = self.request.session.get('extracted_text', '')
        uploaded_image_id = self.request.session.get('uploaded_image_id', None)
        
        context['extracted_text'] = extracted_text
        
        if uploaded_image_id:
            try:
                uploaded_image = UploadedImage.objects.get(id=uploaded_image_id, user=self.request.user)
                context['uploaded_image'] = uploaded_image
            except UploadedImage.DoesNotExist:
                pass
        
        return context


class LyricsConfirmationView(LoginRequiredMixin, TemplateView):
    """歌詞確認ビュー（AI生成または手動入力）"""
    template_name = 'songs/lyrics_confirmation.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        manual_mode = self.request.GET.get('manual', 'false') == 'true'
        
        # 言語モードを取得（URLパラメータ > セッション > デフォルト）
        language_mode = self.request.GET.get('lang', self.request.session.get('language_mode', 'japanese'))
        self.request.session['language_mode'] = language_mode
        context['language_mode'] = language_mode
        
        # カスタムリクエストを取得
        custom_request = self.request.session.get('custom_request', '')
        context['custom_request'] = custom_request
        
        # セッションから抽出されたテキストを取得（複数画像対応）
        extracted_texts = self.request.session.get('extracted_texts', [])
        if extracted_texts and isinstance(extracted_texts, list):
            extracted_text = '\n\n'.join(extracted_texts)
        else:
            extracted_text = self.request.session.get('extracted_text', '')
        
        if manual_mode:
            generated_lyrics = ""
            context['manual_mode'] = True
            context['extracted_text'] = ""
        elif extracted_text:
            try:
                lyrics_generator = GeminiLyricsGenerator()
                generated_lyrics = lyrics_generator.generate_lyrics(extracted_text, language_mode=language_mode, custom_request=custom_request)
                context['manual_mode'] = False
                context['extracted_text'] = extracted_text
                self.request.session['generated_lyrics'] = generated_lyrics
                self.request.session['extracted_text'] = extracted_text
            except Exception as e:
                # AI生成失敗時は手動モードにフォールバック
                logger.error(f"Lyrics generation error: {e}")
                generated_lyrics = ""
                context['manual_mode'] = True
                context['extracted_text'] = extracted_text
                context['generation_error'] = '歌詞の自動生成に失敗しました。手動で入力してください。'
        else:
            generated_lyrics = ""
            context['manual_mode'] = True
            context['extracted_text'] = ""
        
        context['generated_lyrics'] = generated_lyrics
        
        return context
    
    def post(self, request, *args, **kwargs):
        """POST処理: 歌詞再生成やフォーム送信"""
        action = request.POST.get('action')
        
        if action == 'regenerate':
            extracted_texts = request.session.get('extracted_texts', [])
            if extracted_texts and isinstance(extracted_texts, list):
                extracted_text = '\n\n'.join(extracted_texts)
            else:
                extracted_text = request.session.get('extracted_text', '')
            
            language_mode = request.session.get('language_mode', 'japanese')
            custom_request = request.session.get('custom_request', '')
            
            if extracted_text:
                try:
                    lyrics_generator = GeminiLyricsGenerator()
                    new_lyrics = lyrics_generator.generate_lyrics(extracted_text, language_mode=language_mode, custom_request=custom_request)
                    return JsonResponse({
                        'success': True,
                        'lyrics': new_lyrics
                    })
                except Exception as e:
                    return JsonResponse({
                        'success': False,
                        'error': f'歌詞生成に失敗しました: {str(e)}'
                    })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'テキストが見つかりません'
                })
        
        return self.get(request, *args, **kwargs)


@login_required
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
def favorite_song(request, pk):
    """楽曲お気に入り機能"""
    song = get_object_or_404(Song, pk=pk)
    favorite, created = Favorite.objects.get_or_create(user=request.user, song=song)
    
    if not created:
        favorite.delete()
        favorited = False
    else:
        favorited = True
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'favorited': favorited})
    
    return redirect('songs:song_detail', pk=pk)


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


@require_POST
def record_play(request, pk):
    """再生回数を記録するAPI"""
    song = get_object_or_404(Song, pk=pk)
    
    # 総再生回数を更新（誰でも）
    song.total_plays += 1
    song.save(update_fields=['total_plays'])
    
    # ログインユーザーの場合は個人の再生履歴も更新
    my_play_count = 0
    if request.user.is_authenticated:
        play_history, created = PlayHistory.objects.get_or_create(
            user=request.user,
            song=song,
            defaults={'play_count': 1}
        )
        
        if not created:
            play_history.play_count += 1
            play_history.save()
        
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
        from django.db.models import Count, Sum, Q
        
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
def toggle_song_privacy(request, pk):
    """楽曲の公開/非公開を切り替え"""
    song = get_object_or_404(Song, pk=pk, created_by=request.user)
    app_language = request.session.get('app_language', 'ja')
    
    if request.method == 'POST':
        import json
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                data = json.loads(request.body)
                song.is_public = data.get('is_public', not song.is_public)
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
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })
        else:
            song.is_public = not song.is_public
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
        context['song'] = self.get_object()
        context['form'] = SongPrivacyForm(instance=context['song'])
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


@staff_member_required
def api_status_view(request):
    """API統合状態を確認する管理者用ビュー（ヘルスチェック機能付き）"""
    import time
    from django.db.models import Count, Avg
    from django.utils import timezone
    from datetime import timedelta
    
    # Gemini OCRステータス
    ocr_gen = GeminiOCR()
    gemini_ocr_status = {
        'available': bool(ocr_gen.model),
        'api_key_set': bool(ocr_gen.api_key),
        'status': '有効' if ocr_gen.model else '未設定',
        'health': 'unknown'
    }
    
    # Gemini歌詞生成ステータス
    lyrics_gen = GeminiLyricsGenerator()
    gemini_lyrics_status = {
        'available': bool(lyrics_gen.model),
        'api_key_set': bool(lyrics_gen.api_key),
        'status': '有効' if lyrics_gen.model else '未設定',
        'health': 'unknown'
    }
    
    # Murekaステータス
    mureka_gen = MurekaAIGenerator()
    mureka_status = {
        'available': mureka_gen.use_real_api,
        'api_key_set': bool(mureka_gen.api_key),
        'api_url': mureka_gen.base_url,
        'status': '有効' if mureka_gen.use_real_api else '未設定',
        'health': 'unknown'
    }
    
    # キュー統計
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)
    
    queue_stats = {
        'pending': Song.objects.filter(generation_status='pending').count(),
        'generating': Song.objects.filter(generation_status='generating').count(),
        'completed_24h': Song.objects.filter(
            generation_status='completed',
            completed_at__gte=last_24h
        ).count(),
        'failed_24h': Song.objects.filter(
            generation_status='failed',
            updated_at__gte=last_24h
        ).count(),
        'total_completed': Song.objects.filter(generation_status='completed').count(),
        'total_failed': Song.objects.filter(generation_status='failed').count(),
    }
    
    # 最近のエラー
    recent_errors = Song.objects.filter(
        generation_status='failed',
        error_message__isnull=False
    ).exclude(error_message='').order_by('-updated_at')[:10].values(
        'id', 'title', 'error_message', 'updated_at', 'retry_count'
    )
    
    # スタックしたジョブの検出（30分以上生成中のもの）
    stuck_threshold = now - timedelta(minutes=30)
    stuck_jobs = Song.objects.filter(
        generation_status='generating',
        started_at__lt=stuck_threshold
    ).values('id', 'title', 'started_at')
    
    context = {
        'gemini_ocr_status': gemini_ocr_status,
        'gemini_lyrics_status': gemini_lyrics_status,
        'mureka_status': mureka_status,
        'queue_stats': queue_stats,
        'recent_errors': list(recent_errors),
        'stuck_jobs': list(stuck_jobs),
        'page_title': 'API統合状態 & システムヘルス'
    }
    
    return render(request, 'songs/api_status.html', context)


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
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


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
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


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
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def retry_song_generation(request, pk):
    """失敗した楽曲の再生成（設定された回数まで許可）"""
    from django.conf import settings
    
    song = get_object_or_404(Song, pk=pk, created_by=request.user)
    max_retries = getattr(settings, 'MAX_GENERATION_RETRIES', 3)
    app_language = request.session.get('app_language', 'ja')
    
    if request.method == 'POST':
        # 再生成回数をチェック
        if song.retry_count >= max_retries:
            if app_language == 'en':
                error_msg = f'Retry limit is {max_retries} times'
            elif app_language == 'zh':
                error_msg = f'重试次数上限为{max_retries}次'
            else:
                error_msg = f'再生成は{max_retries}回までです'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': error_msg
                })
            messages.error(request, error_msg)
            return redirect('songs:song_detail', pk=song.pk)
        
        # 失敗した曲のみ再生成可能
        if song.generation_status == 'failed':
            try:
                # ステータスをpendingに戻し、再生成回数を増やす
                song.generation_status = 'pending'
                song.queue_position = None
                song.retry_count += 1
                song.error_message = None  # エラーメッセージをクリア
                song.started_at = None
                song.completed_at = None
                song.save()
                
                # キューに追加
                from .queue_manager import queue_manager
                queue_manager.add_to_queue(
                    song_id=song.id,
                    lyrics_content=song.lyrics.content if song.lyrics else '',
                    title=song.title,
                    genre=song.genre,
                    vocal_style=song.vocal_style
                )
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    if app_language == 'en':
                        msg = 'Song regeneration started'
                    elif app_language == 'zh':
                        msg = '歌曲重新生成已开始'
                    else:
                        msg = '楽曲の再生成を開始しました'
                    return JsonResponse({
                        'success': True,
                        'message': msg,
                        'redirect_url': reverse_lazy('songs:song_detail', kwargs={'pk': song.pk})
                    })
                
                if app_language == 'en':
                    messages.success(request, 'Song regeneration started.')
                elif app_language == 'zh':
                    messages.success(request, '歌曲重新生成已开始。')
                else:
                    messages.success(request, '楽曲の再生成を開始しました。')
                return redirect('songs:song_detail', pk=song.pk)
                
            except Exception as e:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': str(e)
                    })
                if app_language == 'en':
                    messages.error(request, f'Regeneration failed: {e}')
                elif app_language == 'zh':
                    messages.error(request, f'重新生成失败：{e}')
                else:
                    messages.error(request, f'再生成に失敗しました: {e}')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                if app_language == 'en':
                    error_msg = 'This song cannot be regenerated'
                elif app_language == 'zh':
                    error_msg = '此歌曲无法重新生成'
                else:
                    error_msg = 'この楽曲は再生成できません'
                return JsonResponse({
                    'success': False,
                    'error': error_msg
                })
            if app_language == 'en':
                messages.error(request, 'This song cannot be regenerated.')
            elif app_language == 'zh':
                messages.error(request, '此歌曲无法重新生成。')
            else:
                messages.error(request, 'この楽曲は再生成できません。')
    
    return redirect('songs:song_detail', pk=song.pk)




def set_language(request, lang):
    """アプリの言語を切り替える"""
    if lang in ['ja', 'en', 'zh']:
        # セッションに言語を保存
        request.session['app_language'] = lang
        request.session.modified = True
        
        # セッションを確実に保存
        try:
            request.session.save()
        except Exception as e:
            logger.error(f"Session save error: {e}")
    
    # リファラーがあればそこに戻る、なければホームに
    referer = request.META.get('HTTP_REFERER')
    if referer:
        # キャッシュ防止のためタイムスタンプを追加
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        import time
        parsed = urlparse(referer)
        query_params = parse_qs(parsed.query)
        query_params['_t'] = [str(int(time.time() * 1000))]
        query_params['_lang'] = [lang]  # 言語パラメータも追加
        new_query = urlencode(query_params, doseq=True)
        new_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        response = redirect(new_url)
    else:
        response = redirect('songs:home')
    
    # キャッシュを無効化するヘッダーを追加
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    response['Vary'] = 'Cookie'
    return response


def check_song_status(request, pk):
    """楽曲の生成状態をチェックするAPIエンドポイント（言語を変更しない）"""
    try:
        song = Song.objects.get(pk=pk)
        return JsonResponse({
            'success': True,
            'status': song.generation_status,
            'audio_url': song.audio_url if song.audio_url else None,
            'completed': song.generation_status == 'completed',
            'failed': song.generation_status == 'failed',
            'error_message': song.error_message if song.generation_status == 'failed' else None
        })
    except Song.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Song not found'
        }, status=404)


# ========== クラス機能 ==========

from .models import Classroom, ClassroomMembership, ClassroomSong
import random
import string


def generate_classroom_code():
    """ユニークなクラスコードを生成"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Classroom.objects.filter(code=code).exists():
            return code


@login_required
def classroom_list(request):
    """参加中のクラス一覧"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    # ホストしているクラス
    hosted_classrooms = Classroom.objects.filter(host=request.user, is_active=True)
    # 参加しているクラス
    joined_classrooms = request.user.joined_classrooms.filter(is_active=True).exclude(host=request.user)
    
    return render(request, 'songs/classroom_list.html', {
        'hosted_classrooms': hosted_classrooms,
        'joined_classrooms': joined_classrooms,
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
def classroom_join(request):
    """クラスに参加"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        
        if not code:
            if is_english:
                messages.error(request, 'Please enter a class code.')
            elif is_chinese:
                messages.error(request, '请输入班级代码。')
            else:
                messages.error(request, 'クラスコードを入力してください。')
            return redirect('songs:classroom_join')
        
        try:
            classroom = Classroom.objects.get(code=code, is_active=True)
            
            # 既に参加しているか確認
            if ClassroomMembership.objects.filter(user=request.user, classroom=classroom).exists():
                if is_english:
                    messages.info(request, 'You are already a member of this class.')
                elif is_chinese:
                    messages.info(request, '您已经是该班级的成员。')
                else:
                    messages.info(request, '既にこのクラスに参加しています。')
            else:
                ClassroomMembership.objects.create(user=request.user, classroom=classroom)
                if is_english:
                    messages.success(request, f'You have joined "{classroom.name}"!')
                elif is_chinese:
                    messages.success(request, f'已加入"{classroom.name}"！')
                else:
                    messages.success(request, f'「{classroom.name}」に参加しました！')
            
            return redirect('songs:classroom_detail', pk=classroom.pk)
            
        except Classroom.DoesNotExist:
            if is_english:
                messages.error(request, 'Invalid class code.')
            elif is_chinese:
                messages.error(request, '无效的班级代码。')
            else:
                messages.error(request, '無効なクラスコードです。')
    
    return render(request, 'songs/classroom_join.html', {
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
def classroom_create(request):
    """クラスを作成（先生用）"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        
        if not name:
            if is_english:
                messages.error(request, 'Please enter a class name.')
            elif is_chinese:
                messages.error(request, '请输入班级名称。')
            else:
                messages.error(request, 'クラス名を入力してください。')
            return redirect('songs:classroom_create')
        
        code = generate_classroom_code()
        classroom = Classroom.objects.create(
            name=name,
            description=description,
            code=code,
            host=request.user
        )
        # ホスト自身もメンバーとして追加
        ClassroomMembership.objects.create(user=request.user, classroom=classroom)
        
        if is_english:
            messages.success(request, f'Class created! Share code: {code}')
        elif is_chinese:
            messages.success(request, f'班级已创建！分享代码：{code}')
        else:
            messages.success(request, f'クラスを作成しました！参加コード: {code}')
        
        return redirect('songs:classroom_detail', pk=classroom.pk)
    
    return render(request, 'songs/classroom_create.html', {
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
def classroom_detail(request, pk):
    """クラス詳細（楽曲一覧）"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    classroom = get_object_or_404(Classroom, pk=pk, is_active=True)
    
    # メンバーかホストのみアクセス可能
    is_member = ClassroomMembership.objects.filter(user=request.user, classroom=classroom).exists()
    is_host = classroom.host == request.user
    
    if not is_member and not is_host:
        if is_english:
            messages.error(request, 'You do not have access to this class.')
        elif is_chinese:
            messages.error(request, '您没有访问该班级的权限。')
        else:
            messages.error(request, 'このクラスにアクセスする権限がありません。')
        return redirect('songs:classroom_join')
    
    # クラス内の共有楽曲
    shared_songs = ClassroomSong.objects.filter(classroom=classroom).select_related('song', 'shared_by')
    
    # メンバー一覧
    members = ClassroomMembership.objects.filter(classroom=classroom).select_related('user')
    
    return render(request, 'songs/classroom_detail.html', {
        'classroom': classroom,
        'shared_songs': shared_songs,
        'members': members,
        'is_host': is_host,
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
def classroom_share_song(request, pk):
    """楽曲をクラスに共有"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    classroom = get_object_or_404(Classroom, pk=pk, is_active=True)
    
    # メンバーかホストのみ
    is_member = ClassroomMembership.objects.filter(user=request.user, classroom=classroom).exists()
    if not is_member:
        if is_english:
            messages.error(request, 'You are not a member of this class.')
        elif is_chinese:
            messages.error(request, '您不是该班级的成员。')
        else:
            messages.error(request, 'このクラスのメンバーではありません。')
        return redirect('songs:classroom_list')
    
    if request.method == 'POST':
        song_id = request.POST.get('song_id')
        try:
            song = Song.objects.get(pk=song_id, created_by=request.user)
            
            # 既に共有されているか確認
            if ClassroomSong.objects.filter(classroom=classroom, song=song).exists():
                if is_english:
                    messages.info(request, 'This song is already shared.')
                elif is_chinese:
                    messages.info(request, '这首歌曲已被分享。')
                else:
                    messages.info(request, 'この楽曲は既に共有されています。')
            else:
                ClassroomSong.objects.create(
                    classroom=classroom,
                    song=song,
                    shared_by=request.user
                )
                if is_english:
                    messages.success(request, 'Song shared to class!')
                elif is_chinese:
                    messages.success(request, '歌曲已分享到班级！')
                else:
                    messages.success(request, 'クラスに楽曲を共有しました！')
            
            return redirect('songs:classroom_detail', pk=pk)
            
        except Song.DoesNotExist:
            if is_english:
                messages.error(request, 'Song not found.')
            elif is_chinese:
                messages.error(request, '歌曲未找到。')
            else:
                messages.error(request, '楽曲が見つかりません。')
    
    # 自分の楽曲一覧
    my_songs = Song.objects.filter(
        created_by=request.user, 
        generation_status='completed'
    ).exclude(
        classroom_shares__classroom=classroom
    )
    
    return render(request, 'songs/classroom_share_song.html', {
        'classroom': classroom,
        'my_songs': my_songs,
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
def classroom_leave(request, pk):
    """クラスから退出"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    classroom = get_object_or_404(Classroom, pk=pk)
    
    # ホストは退出できない
    if classroom.host == request.user:
        if is_english:
            messages.error(request, 'Host cannot leave the class. Please delete the class instead.')
        elif is_chinese:
            messages.error(request, '主持人不能退出班级。请删除班级。')
        else:
            messages.error(request, 'ホストはクラスから退出できません。クラスを削除してください。')
        return redirect('songs:classroom_detail', pk=pk)
    
    membership = ClassroomMembership.objects.filter(user=request.user, classroom=classroom).first()
    if membership:
        membership.delete()
        if is_english:
            messages.success(request, 'You have left the class.')
        elif is_chinese:
            messages.success(request, '您已退出班级。')
        else:
            messages.success(request, 'クラスから退出しました。')
    
    return redirect('songs:classroom_list')


@login_required
def classroom_delete(request, pk):
    """クラスを削除（ホストのみ）"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    classroom = get_object_or_404(Classroom, pk=pk)
    
    if classroom.host != request.user:
        if is_english:
            messages.error(request, 'Only the host can delete the class.')
        elif is_chinese:
            messages.error(request, '只有主持人可以删除班级。')
        else:
            messages.error(request, 'ホストのみがクラスを削除できます。')
        return redirect('songs:classroom_detail', pk=pk)
    
    if request.method == 'POST':
        classroom.is_active = False
        classroom.save()
        if is_english:
            messages.success(request, 'Class has been deleted.')
        elif is_chinese:
            messages.success(request, '班级已删除。')
        else:
            messages.success(request, 'クラスを削除しました。')
        return redirect('songs:classroom_list')
    
    return redirect('songs:classroom_detail', pk=pk)


def audio_proxy(request, pk):
    """外部音声URLをプロキシして返す（CORS対策）"""
    from django.http import HttpResponse
    import requests as req
    
    song = get_object_or_404(Song, pk=pk)
    
    # 音声URLを取得
    audio_url = song.audio_url
    if not audio_url:
        return HttpResponse('No audio URL', status=404)
    
    try:
        # 外部URLから音声をダウンロード
        response = req.get(audio_url, timeout=30)
        response.raise_for_status()
        
        # Content-Typeを取得
        content_type = response.headers.get('Content-Type', 'audio/mpeg')
        
        return HttpResponse(
            response.content,
            content_type=content_type
        )
    except Exception as e:
        logger.error(f'Audio proxy error: {e}')
        return HttpResponse(f'Error: {e}', status=500)