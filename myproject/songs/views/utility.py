"""ユーティリティ系ビュー（言語切替・音声プロキシ・違反ページ・API状態・デバッグ）"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.conf import settings
import json
import logging

from ..models import Song
from ..ai_services import GeminiLyricsGenerator, GeminiOCR, MurekaAIGenerator

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


def set_language(request, lang):
    """アプリの言語を切り替える"""
    supported_languages = {'ja', 'en', 'zh', 'es', 'de', 'pt'}
    if lang in supported_languages:
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


def audio_proxy(request, pk):
    """外部音声URLをプロキシして返す（CORS対策）"""
    from django.http import StreamingHttpResponse, HttpResponse
    from urllib.parse import urlparse
    import requests as req
    import time
    
    song = get_object_or_404(Song, pk=pk)
    
    # 非公開楽曲はオーナーのみアクセス可能
    if not song.is_public:
        if not request.user.is_authenticated:
            return HttpResponse('Unauthorized', status=401)
        if request.user != song.created_by and not request.user.is_staff:
            logger.warning(f"Audio proxy access denied: user {request.user.id} tried to access private song {pk}")
            return HttpResponse('Forbidden', status=403)
    
    # 音声URLを取得
    audio_url = song.audio_url
    if not audio_url:
        return HttpResponse('No audio URL', status=404)
    
    # ドメインホワイトリスト（SSRF防止）
    ALLOWED_AUDIO_DOMAINS = {
        'cdn.mureka.ai',
        'api.mureka.ai',
        'mureka-public.s3.amazonaws.com',
        'storage.googleapis.com',
    }
    parsed = urlparse(audio_url)
    if parsed.hostname not in ALLOWED_AUDIO_DOMAINS:
        logger.warning(f"Audio proxy blocked unauthorized domain: {parsed.hostname} for song {pk}")
        return HttpResponse('Forbidden', status=403)
    
    # リトライロジック（最大3回）
    max_retries = 3
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # ストリーミングで外部URLから音声を取得
            response = req.get(
                audio_url,
                timeout=(10, 120),  # (connect_timeout, read_timeout)
                stream=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; UtamemoProxy/1.0)',
                    'Accept': 'audio/*,*/*',
                }
            )
            response.raise_for_status()
            
            # レスポンスヘッダーを設定
            content_type = response.headers.get('Content-Type', 'audio/mpeg')
            content_length = response.headers.get('Content-Length')
            
            # ストリーミングレスポンスを作成
            def stream_content():
                try:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk
                finally:
                    response.close()
            
            streaming_response = StreamingHttpResponse(
                stream_content(),
                content_type=content_type,
            )
            
            # 必要なヘッダーを設定
            if content_length:
                streaming_response['Content-Length'] = content_length
            streaming_response['Accept-Ranges'] = 'bytes'
            streaming_response['Cache-Control'] = 'public, max-age=3600'
            streaming_response['Access-Control-Allow-Origin'] = '*'
            
            return streaming_response
            
        except req.exceptions.Timeout as e:
            last_error = e
            logger.warning(f'Audio proxy timeout (attempt {attempt + 1}/{max_retries}): {e}')
            if attempt < max_retries - 1:
                time.sleep(1)
        except req.exceptions.ConnectionError as e:
            last_error = e
            logger.warning(f'Audio proxy connection error (attempt {attempt + 1}/{max_retries}): {e}')
            if attempt < max_retries - 1:
                time.sleep(2)
        except req.exceptions.HTTPError as e:
            # HTTPエラー（404、403等）はリトライしない
            logger.error(f'Audio proxy HTTP error: {e}')
            status_code = e.response.status_code if e.response else 502
            
            # 音声URLが期限切れ・無効の場合のメッセージ
            if status_code in (403, 404, 410, 424):
                return HttpResponse(
                    'Audio expired or unavailable',
                    status=410  # Gone
                )
            return HttpResponse(
                f'Audio source returned error: {status_code}',
                status=502
            )
        except Exception as e:
            last_error = e
            logger.error(f'Audio proxy unexpected error (attempt {attempt + 1}/{max_retries}): {e}')
            if attempt < max_retries - 1:
                time.sleep(1)
    
    # 全リトライ失敗
    logger.error(f'Audio proxy failed after {max_retries} retries for song {pk}: {last_error}')
    return HttpResponse(
        'Audio temporarily unavailable. Please try again.',
        status=504
    )


@login_required
def content_violation_view(request):
    """利用規約違反ページ"""
    app_language = request.session.get('app_language', 'ja')
    
    # セッションから違反情報を取得
    is_violation = request.session.get('content_violation', False)
    violation_message = request.session.get('violation_message', '')
    detected_words = request.session.get('detected_words', [])
    
    # セッションをクリア
    if 'content_violation' in request.session:
        del request.session['content_violation']
    if 'violation_message' in request.session:
        del request.session['violation_message']
    if 'detected_words' in request.session:
        del request.session['detected_words']
    if 'extracted_texts' in request.session:
        del request.session['extracted_texts']
    if 'uploaded_image_ids' in request.session:
        del request.session['uploaded_image_ids']
    
    # 言語に応じたメッセージを設定
    if app_language == 'en':
        title = 'Terms of Service Violation'
        default_message = (
            'Content that violates our Terms of Service has been detected.\n\n'
            'Content containing inappropriate expressions (insults, discriminatory language, '
            'violent expressions, etc.) cannot be used for song generation.\n\n'
            'Please review our Terms of Service and use appropriate content.'
        )
        terms_link_text = 'View Terms of Service'
        back_link_text = 'Return to Upload Page'
    elif app_language == 'zh':
        title = '违反使用条款'
        default_message = (
            '检测到违反使用条款的内容。\n\n'
            '包含不当表达（侮辱、歧视性语言、暴力表达等）的内容'
            '不能用于歌曲生成。\n\n'
            '请查看使用条款并使用适当的内容。'
        )
        terms_link_text = '查看使用条款'
        back_link_text = '返回上传页面'
    elif app_language == 'es':
        title = 'Violación de los Términos de Servicio'
        default_message = (
            'Se ha detectado contenido que viola nuestros Términos de Servicio.\n\n'
            'El contenido que contiene expresiones inapropiadas no se puede usar '
            'para la generación de canciones.\n\n'
            'Por favor, revise nuestros Términos de Servicio y use contenido apropiado.'
        )
        terms_link_text = 'Ver Términos de Servicio'
        back_link_text = 'Volver a la página de carga'
    elif app_language == 'de':
        title = 'Verstoß gegen die Nutzungsbedingungen'
        default_message = (
            'Es wurde Inhalt erkannt, der gegen unsere Nutzungsbedingungen verstößt.\n\n'
            'Inhalte mit unangemessenen Ausdrücken können nicht für die '
            'Songgenerierung verwendet werden.\n\n'
            'Bitte überprüfen Sie unsere Nutzungsbedingungen und verwenden Sie angemessene Inhalte.'
        )
        terms_link_text = 'Nutzungsbedingungen anzeigen'
        back_link_text = 'Zurück zur Upload-Seite'
    elif app_language == 'pt':
        title = 'Violação dos Termos de Serviço'
        default_message = (
            'Foi detectado conteúdo que viola nossos Termos de Serviço.\n\n'
            'Conteúdo contendo expressões inadequadas não pode ser usado '
            'para geração de músicas.\n\n'
            'Por favor, revise nossos Termos de Serviço e use conteúdo apropriado.'
        )
        terms_link_text = 'Ver Termos de Serviço'
        back_link_text = 'Voltar à página de upload'
    else:
        title = '利用規約違反'
        default_message = (
            '利用規約に違反するコンテンツが検出されました。\n\n'
            '不適切な表現（悪口、差別用語、暴力的な表現など）を含むコンテンツは'
            '楽曲生成に使用できません。\n\n'
            '利用規約をご確認の上、適切なコンテンツでご利用ください。'
        )
        terms_link_text = '利用規約を確認する'
        back_link_text = 'アップロードページに戻る'
    
    context = {
        'title': title,
        'message': default_message,
        'detected_words': detected_words,
        'terms_link_text': terms_link_text,
        'back_link_text': back_link_text,
        'app_language': app_language,
    }
    
    return render(request, 'songs/content_violation.html', context)


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
    
    # ローカルLLMステータス
    from ..ai_services import LocalLLMLyricsGenerator, CloudLLMLyricsGenerator
    local_llm = LocalLLMLyricsGenerator()
    lyrics_backend = getattr(settings, 'LYRICS_BACKEND', 'gemini')
    local_llm_status = {
        'available': local_llm.is_available,
        'url': local_llm.base_url or '未設定',
        'backend': lyrics_backend,
        'status': '接続OK' if local_llm.is_available else ('未設定' if not local_llm.base_url else '接続不可'),
    }

    # クラウドLLMステータス
    cloud_llm = CloudLLMLyricsGenerator()
    cloud_llm_status = {
        'available': cloud_llm.is_available,
        'provider': cloud_llm.provider or '未設定',
        'model': cloud_llm.model_name or '未設定',
        'url': cloud_llm.api_url or '未設定',
        'api_key_set': bool(cloud_llm.api_key),
        'status': '有効' if cloud_llm.is_available else '未設定',
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
        'local_llm_status': local_llm_status,
        'cloud_llm_status': cloud_llm_status,
        'mureka_status': mureka_status,
        'queue_stats': queue_stats,
        'recent_errors': list(recent_errors),
        'stuck_jobs': list(stuck_jobs),
        'page_title': 'API統合状態 & システムヘルス'
    }
    
    return render(request, 'songs/api_status.html', context)


@staff_member_required
def mureka_api_debug(request):
    """Mureka APIのレスポンスフィールド調査用（スタッフのみ）"""
    
    from ..ai_services import MurekaAIGenerator
    
    mureka = MurekaAIGenerator()
    
    action = request.GET.get('action', 'endpoints')
    
    if action == 'endpoints':
        # 利用可能エンドポイントの調査
        results = mureka.list_api_endpoints()
        return JsonResponse({'action': 'endpoints', 'results': results})
    
    elif action == 'describe':
        # 特定の曲を分析（song_id省略時は最新の公開曲を使用）
        song_id = request.GET.get('song_id')
        if song_id:
            song = get_object_or_404(Song, pk=song_id)
        else:
            song = Song.objects.filter(audio_url__isnull=False).exclude(audio_url='').order_by('-created_at').first()
            if not song:
                return JsonResponse({'error': 'No song with audio found'}, status=400)
        
        audio_url = song.audio_url
        if not audio_url:
            return JsonResponse({'error': 'No audio URL'}, status=400)
        
        result = mureka.describe_song(audio_url)
        return JsonResponse({
            'action': 'describe',
            'song_id': song.pk,
            'song_title': str(song),
            'audio_url': audio_url[:100],
            'result': result
        })
    
    elif action == 'query_task':
        # タスクの全フィールドを確認（最近の生成タスクIDを指定）
        task_id = request.GET.get('task_id')
        if not task_id:
            # 最新の曲のtrace_idを使用
            return JsonResponse({'error': 'task_id required'}, status=400)
        
        import requests as req
        headers = {
            'Authorization': f'Bearer {mureka.api_key}',
            'Content-Type': 'application/json'
        }
        try:
            response = req.get(f"{mureka.base_url}/v1/song/query/{task_id}", headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return JsonResponse({'action': 'query_task', 'task_id': task_id, 'result': data})
            else:
                return JsonResponse({'action': 'query_task', 'status': response.status_code, 'body': response.text[:1000]})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    elif action == 'list_songs':
        # Mureka APIの曲リストを取得（GET & POST両方試す）
        import requests as req
        headers = {
            'Authorization': f'Bearer {mureka.api_key}',
            'Content-Type': 'application/json'
        }
        results = {}
        try:
            # GET
            response = req.get(f"{mureka.base_url}/v1/song/list", headers=headers, timeout=30)
            results['GET /v1/song/list'] = {'status': response.status_code, 'body': response.text[:500]}
        except Exception as e:
            results['GET /v1/song/list'] = {'error': str(e)}
        try:
            # POST
            response = req.post(f"{mureka.base_url}/v1/song/list", headers=headers, json={}, timeout=30)
            results['POST /v1/song/list'] = {'status': response.status_code, 'body': response.text[:500]}
        except Exception as e:
            results['POST /v1/song/list'] = {'error': str(e)}
        try:
            # POST with page
            response = req.post(f"{mureka.base_url}/v1/song/list", headers=headers, json={"page": 1, "page_size": 5}, timeout=30)
            results['POST /v1/song/list (paged)'] = {'status': response.status_code, 'body': response.text[:500]}
        except Exception as e:
            results['POST /v1/song/list (paged)'] = {'error': str(e)}
        return JsonResponse({'action': 'list_songs', 'results': results})
    
    elif action == 'recent_songs':
        # DB内の最近の曲とそのメタデータを一覧表示
        recent = Song.objects.filter(audio_url__isnull=False).exclude(audio_url='').order_by('-created_at')[:10]
        songs_data = []
        for s in recent:
            songs_data.append({
                'id': s.pk,
                'title': str(s),
                'created': s.created_at.isoformat() if s.created_at else None,
                'audio_url': s.audio_url[:80] if s.audio_url else None,
                'generation_status': s.generation_status if hasattr(s, 'generation_status') else None,
            })
        return JsonResponse({'action': 'recent_songs', 'songs': songs_data})
    
    return JsonResponse({'error': 'Unknown action. Use: endpoints, describe, query_task, list_songs, recent_songs'}, status=400)
