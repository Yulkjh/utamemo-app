"""楽曲生成フロー系ビュー（アップロード・OCR・歌詞生成・確認・再生成・ステータス確認）"""
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import TemplateView
from django.views.generic.edit import FormView
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.conf import settings
import json
import logging
from pathlib import Path

from ..models import Song, Lyrics, UploadedImage
from ..forms import ImageUploadForm
from ..ai_services import GeminiOCR, get_lyrics_generator
from ..content_filter import check_text_for_inappropriate_content

logger = logging.getLogger(__name__)


def validate_uploaded_file(file, app_language='ja'):
    """アップロードされたファイルを検証"""
    errors = []
    file_name = file.name.lower()
    
    # ファイルタイプの確認
    is_pdf = file_name.endswith('.pdf')
    is_image = any(file_name.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif'])
    
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
    allowed_image_types = getattr(settings, 'ALLOWED_IMAGE_TYPES', ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/heic', 'image/heif'])
    allowed_doc_types = getattr(settings, 'ALLOWED_DOCUMENT_TYPES', ['application/pdf'])
    
    if is_pdf and content_type not in allowed_doc_types:
        if app_language == 'en':
            errors.append(f'{file.name}: Invalid PDF file')
        elif app_language == 'zh':
            errors.append(f'{file.name}：无效的PDF文件')
        else:
            errors.append(f'{file.name}: 無効なPDFファイルです')
    elif is_image and content_type not in allowed_image_types:
        # スマホ（iOS Safari等）ではHEIC画像のMIMEタイプが空や
        # application/octet-streamで送信されることがあるため、
        # 拡張子で画像と判定済みの場合はMIMEタイプチェックをスキップ
        if content_type and content_type != 'application/octet-stream':
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

    def get(self, request, *args, **kwargs):
        # ?new=true で明示的に新規作成する場合はセッションをクリアしてそのまま表示
        if request.GET.get('new') == 'true':
            for key in ['extracted_texts', 'extracted_text', 'generated_lyrics',
                        'uploaded_image_ids', 'uploaded_image_id', 'custom_request']:
                request.session.pop(key, None)
            return super().get(request, *args, **kwargs)

        # 生成中の楽曲がある場合はその生成画面にリダイレクト
        in_progress_song = Song.objects.filter(
            created_by=request.user,
            generation_status__in=['pending', 'generating']
        ).order_by('-created_at').first()
        if in_progress_song:
            return redirect('songs:song_generating', pk=in_progress_song.pk)

        # 歌詞が既に生成済みでセッションにある場合は確認画面へ
        if request.session.get('generated_lyrics'):
            return redirect('songs:lyrics_confirmation')

        # 歌詞生成中（テキスト抽出済み）の場合は歌詞生成画面へ
        if request.session.get('extracted_texts'):
            return redirect('songs:lyrics_generating')

        return super().get(request, *args, **kwargs)

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
        
        # 10ファイル制限
        MAX_FILES = 10
        if len(files) > MAX_FILES:
            if app_language == 'en':
                messages.error(self.request, f'You can upload up to {MAX_FILES} files at a time.')
            elif app_language == 'zh':
                messages.error(self.request, f'一次最多可上传{MAX_FILES}个文件。')
            elif app_language == 'es':
                messages.error(self.request, f'Puedes subir hasta {MAX_FILES} archivos a la vez.')
            elif app_language == 'de':
                messages.error(self.request, f'Sie können maximal {MAX_FILES} Dateien gleichzeitig hochladen.')
            elif app_language == 'pt':
                messages.error(self.request, f'Você pode enviar até {MAX_FILES} arquivos por vez.')
            else:
                messages.error(self.request, f'一度にアップロードできるのは最大{MAX_FILES}ファイルです。')
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
        
        from ..ai_services import PDFTextExtractor
        
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
                        logger.warning(f"PDF extraction returned empty for {file.name}")
                else:
                    # 画像ファイルの処理
                    uploaded = UploadedImage.objects.create(user=user, image=file)
                    try:
                        ocr_processor = GeminiOCR()
                        logger.info(f"OCR starting for {file.name} (size={file.size}, type={file.content_type}, model={ocr_processor.model})")
                        extracted_text = ocr_processor.extract_text_from_image(uploaded.image)
                        uploaded.extracted_text = extracted_text or ''
                        uploaded.processed = True
                        uploaded.save()
                        if extracted_text:
                            extracted_texts.append(extracted_text)
                            logger.info(f"OCR success for {file.name}: {len(extracted_text)} chars")
                        else:
                            logger.warning(f"OCR returned empty for {file.name} (language_mode={language_mode})")
                        uploaded_image_ids.append(uploaded.id)
                    except Exception as e:
                        errors.append(f'{file.name}: OCR処理に失敗しました')
                        logger.error(f"OCR error for {file.name} (language_mode={language_mode}): {e}")
            except Exception as e:
                errors.append(f'{file.name}: 処理に失敗しました')
                logger.error(f"File processing error for {file.name}: {e}")
        
        self.request.session['extracted_texts'] = extracted_texts
        self.request.session['uploaded_image_ids'] = uploaded_image_ids
        
        # 不適切コンテンツのチェック
        combined_text = '\n'.join(extracted_texts)
        content_check = check_text_for_inappropriate_content(combined_text)
        
        if content_check['is_inappropriate']:
            # 不適切なコンテンツが検出された場合
            self.request.session['content_violation'] = True
            self.request.session['violation_message'] = content_check['message']
            self.request.session['detected_words'] = content_check['detected_words']
            logger.warning(f"Inappropriate content detected for user {user.id}: {content_check['detected_words']}")
            return redirect('songs:content_violation')
        
        if not extracted_texts:
            logger.warning(f"No text extracted from {len(valid_files)} files for user {user.id} (language_mode={language_mode})")
            if app_language == 'en':
                messages.warning(self.request, 'Could not extract text from the uploaded file. You can enter lyrics manually.')
            elif app_language == 'zh':
                messages.warning(self.request, '无法从上传的文件中提取文字。您可以手动输入歌词。')
            else:
                messages.warning(self.request, 'アップロードされたファイルからテキストを抽出できませんでした。手動で歌詞を入力できます。')
            return redirect(f"{reverse_lazy('songs:lyrics_confirmation')}?manual=true&lang={language_mode}")
        
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
        return reverse_lazy('songs:lyrics_generating')


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


class LyricsGeneratingView(LoginRequiredMixin, TemplateView):
    """歌詞生成中のローディング画面"""
    template_name = 'songs/lyrics_generating.html'
    
    def get(self, request, *args, **kwargs):
        # セッションに抽出テキストも生成済み歌詞もない場合はアップロード画面へ
        extracted_texts = request.session.get('extracted_texts', [])
        generated_lyrics = request.session.get('generated_lyrics')
        if not extracted_texts and not generated_lyrics:
            return redirect('songs:upload_image')
        return super().get(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        language_mode = self.request.session.get('language_mode', 'japanese')
        context['language_mode'] = language_mode
        
        # 歌詞が既に生成済みかどうかをテンプレートに渡す（JS側で即遷移用）
        context['lyrics_already_generated'] = bool(self.request.session.get('generated_lyrics'))
        
        extracted_texts = self.request.session.get('extracted_texts', [])
        if extracted_texts and isinstance(extracted_texts, list):
            text_length = sum(len(t) for t in extracted_texts)
        else:
            text_length = 0
        context['text_length'] = text_length
        return context


@login_required
def generate_lyrics_api(request):
    """歌詞生成API（AJAXで呼ばれる）
    
    画像がアップロードされている場合:
      → 画像+テキストを直接Geminiに渡して一発で歌詞生成（高品質）
    テキストのみの場合:
      → 従来のテキストベース歌詞生成
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST only'}, status=405)
    
    extracted_texts = request.session.get('extracted_texts', [])
    if extracted_texts and isinstance(extracted_texts, list):
        extracted_text = '\n\n'.join(extracted_texts)
    else:
        extracted_text = request.session.get('extracted_text', '')
    
    if not extracted_text:
        return JsonResponse({'success': False, 'error': 'No text found'})
    
    language_mode = request.session.get('language_mode', 'japanese')
    custom_request = request.session.get('custom_request', '')
    
    try:
        lyrics_generator = get_lyrics_generator()
        
        # 画像がある場合 → 画像直接生成パス（OCRの情報ロスを回避）
        uploaded_image_ids = request.session.get('uploaded_image_ids', [])
        generated_lyrics = None
        
        if uploaded_image_ids:
            try:
                from PIL import Image as PILImage
                from ..models import UploadedImage
                images = []
                for img_id in uploaded_image_ids:
                    try:
                        uploaded = UploadedImage.objects.get(id=img_id, user=request.user)
                        img = PILImage.open(uploaded.image.path)
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        images.append(img)
                    except Exception as img_err:
                        logger.warning(f"Could not load image {img_id}: {img_err}")
                
                if images:
                    logger.info(f"Using direct image-to-lyrics generation with {len(images)} image(s)")
                    generated_lyrics = lyrics_generator.generate_lyrics_from_images(
                        images,
                        language_mode=language_mode,
                        custom_request=custom_request,
                        extracted_text=extracted_text,
                    )
            except Exception as img_gen_err:
                logger.warning(f"Image-based generation failed, falling back to text: {img_gen_err}")
                generated_lyrics = None
        
        # 画像パスが使えない場合 → 従来のテキストベース生成
        if not generated_lyrics:
            generated_lyrics = lyrics_generator.generate_lyrics(
                extracted_text, 
                language_mode=language_mode, 
                custom_request=custom_request
            )
        
        if generated_lyrics:
            # セッションに保存（LyricsConfirmationViewで使う）
            request.session['generated_lyrics'] = generated_lyrics
            request.session['extracted_text'] = extracted_text
            logger.info(f"Lyrics generated via API: {len(generated_lyrics)} chars for user {request.user.id}")
            return JsonResponse({'success': True, 'length': len(generated_lyrics)})
        else:
            logger.warning(f"Lyrics generation returned empty for user {request.user.id}")
            return JsonResponse({'success': False, 'error': 'Generated lyrics was empty'})
    except Exception as e:
        logger.error(f"Lyrics generation API error: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'An error occurred during lyrics generation. Please try again.'})


@login_required
def reset_lyrics_session(request):
    """歌詞セッションデータをクリアしてアップロード画面に戻る"""
    keys_to_clear = [
        'generated_lyrics', 'extracted_text', 'extracted_texts',
        'uploaded_image_ids', 'custom_request',
    ]
    for key in keys_to_clear:
        request.session.pop(key, None)
    return redirect('songs:upload_image')


class LyricsConfirmationView(LoginRequiredMixin, TemplateView):
    """歌詞確認ビュー（AI生成または手動入力）"""
    template_name = 'songs/lyrics_confirmation.html'
    
    def get(self, request, *args, **kwargs):
        """セッションに歌詞データがない場合はアップロード画面へリダイレクト"""
        manual_mode = request.GET.get('manual', 'false') == 'true'
        if not manual_mode:
            has_lyrics = request.session.get('generated_lyrics')
            has_texts = request.session.get('extracted_texts') or request.session.get('extracted_text')
            if not has_lyrics and not has_texts:
                return redirect('songs:upload_image')
        return super().get(request, *args, **kwargs)
    
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
        
        # セッションから既存の歌詞を確認（再生成機能で保存されたもの）
        existing_lyrics = self.request.session.get('generated_lyrics', '')
        
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
        elif existing_lyrics:
            # ローディング画面や再生成機能でセッションに保存された歌詞をそのまま使用
            generated_lyrics = existing_lyrics
            context['manual_mode'] = False
            context['extracted_text'] = extracted_text
        elif extracted_text:
            # セッションに歌詞がない場合のみ歌詞生成呼び出し（直接アクセス時のフォールバック）
            try:
                lyrics_generator = get_lyrics_generator()
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
                    lyrics_generator = get_lyrics_generator()
                    new_lyrics = None
                    
                    # 画像がある場合 → 画像直接生成パス
                    uploaded_image_ids = request.session.get('uploaded_image_ids', [])
                    if uploaded_image_ids:
                        try:
                            from PIL import Image as PILImage
                            from ..models import UploadedImage
                            images = []
                            for img_id in uploaded_image_ids:
                                try:
                                    uploaded = UploadedImage.objects.get(id=img_id, user=request.user)
                                    img = PILImage.open(uploaded.image.path)
                                    if img.mode != 'RGB':
                                        img = img.convert('RGB')
                                    images.append(img)
                                except Exception:
                                    pass
                            
                            if images:
                                new_lyrics = lyrics_generator.generate_lyrics_from_images(
                                    images,
                                    language_mode=language_mode,
                                    custom_request=custom_request,
                                    extracted_text=extracted_text,
                                )
                        except Exception as img_err:
                            logger.warning(f"Regenerate image-based failed: {img_err}")
                            new_lyrics = None
                    
                    # フォールバック: テキストベース
                    if not new_lyrics:
                        new_lyrics = lyrics_generator.generate_lyrics(extracted_text, language_mode=language_mode, custom_request=custom_request)
                    
                    request.session['generated_lyrics'] = new_lyrics
                    return JsonResponse({
                        'success': True,
                        'lyrics': new_lyrics
                    })
                except Exception as e:
                    logger.error(f"Lyrics regeneration error: {e}", exc_info=True)
                    return JsonResponse({
                        'success': False,
                        'error': '歌詞生成に失敗しました。もう一度お試しください。'
                    })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'テキストが見つかりません'
                })
        
        return self.get(request, *args, **kwargs)


@login_required
def retry_song_generation(request, pk):
    """失敗した楽曲の再生成（1回目は無料、2回目以降は月間生成回数を消費）"""
    song = get_object_or_404(Song, pk=pk, created_by=request.user)
    app_language = request.session.get('app_language', 'ja')
    user = request.user
    
    if request.method == 'POST':
        # 2回目以降の再生成は月間生成回数を消費
        if song.retry_count >= 1:
            # モデルの残り回数をチェック
            # V8（プレミアム）としてカウント
            if not user.can_use_model('v8'):
                if app_language == 'en':
                    error_msg = 'Monthly generation limit reached. Upgrade your plan for more.'
                elif app_language == 'zh':
                    error_msg = '本月生成次数已用完。升级计划获取更多。'
                else:
                    error_msg = '今月の生成回数の上限に達しました。プランをアップグレードしてください。'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg})
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
                from ..queue_manager import queue_manager
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
                        'redirect_url': reverse_lazy('songs:song_generating', kwargs={'pk': song.pk})
                    })
                
                if app_language == 'en':
                    messages.success(request, 'Song regeneration started.')
                elif app_language == 'zh':
                    messages.success(request, '歌曲重新生成已开始。')
                else:
                    messages.success(request, '楽曲の再生成を開始しました。')
                return redirect('songs:song_generating', pk=song.pk)
                
            except Exception as e:
                logger.error(f"Retry generation error for song {song.pk}: {e}")
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': 'An error occurred. Please try again.'
                    })
                if app_language == 'en':
                    messages.error(request, 'Regeneration failed. Please try again.')
                elif app_language == 'zh':
                    messages.error(request, '重新生成失败。请重试。')
                else:
                    messages.error(request, '再生成に失敗しました。もう一度お試しください。')
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


@login_required
def song_generating(request, pk):
    """楽曲生成中のローディング画面"""
    song = get_object_or_404(Song, pk=pk)
    
    # 本人の楽曲のみアクセス可能
    if song.created_by != request.user:
        return redirect('songs:song_detail', pk=pk)
    
    # 既に完了している場合はsong_detailへ
    if song.generation_status == 'completed':
        return redirect('songs:song_detail', pk=pk)
    
    # フラッシュカード同時作成された場合のデッキ情報
    flashcard_deck_id = request.session.pop('created_flashcard_deck_id', None)
    flashcard_deck = None
    if flashcard_deck_id:
        from ..models import FlashcardDeck
        try:
            flashcard_deck = FlashcardDeck.objects.get(pk=flashcard_deck_id, user=request.user)
        except FlashcardDeck.DoesNotExist:
            pass
    
    return render(request, 'songs/song_generating.html', {
        'song': song,
        'flashcard_deck': flashcard_deck,
    })


def check_song_status(request, pk):
    """楽曲の生成状態をチェックするAPIエンドポイント（言語を変更しない）"""
    try:
        song = Song.objects.get(pk=pk)
        
        # 生成フェーズに基づく進捗率を計算
        progress = 0
        phase = 'waiting'
        
        if song.generation_status == 'pending':
            progress = 5
            phase = 'pending'
        elif song.generation_status == 'generating':
            # started_atからの経過時間で進捗を推定
            if song.started_at:
                from django.utils import timezone
                elapsed = (timezone.now() - song.started_at).total_seconds()
                # 典型的な生成時間は60-120秒
                # 0-10s: 歌詞処理(15-30%), 10-30s: API送信(30-50%), 30-90s: 生成中(50-85%), 90s+: 仕上げ(85-95%)
                if elapsed < 10:
                    progress = 15 + int(elapsed * 1.5)  # 15-30%
                    phase = 'lyrics_processing'
                elif elapsed < 30:
                    progress = 30 + int((elapsed - 10) * 1.0)  # 30-50%
                    phase = 'api_calling'
                elif elapsed < 90:
                    progress = 50 + int((elapsed - 30) * 0.58)  # 50-85%
                    phase = 'generating'
                else:
                    progress = min(85 + int((elapsed - 90) * 0.1), 95)  # 85-95%
                    phase = 'finalizing'
            else:
                progress = 20
                phase = 'starting'
        elif song.generation_status == 'completed':
            progress = 100
            phase = 'completed'
        elif song.generation_status == 'failed':
            progress = 0
            phase = 'failed'
        
        return JsonResponse({
            'success': True,
            'status': song.generation_status,
            'progress': progress,
            'phase': phase,
            'queue_position': song.queue_position,
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
