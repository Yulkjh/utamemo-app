from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST, require_http_methods
from django.http import JsonResponse, HttpResponse, Http404
from django.conf import settings
from django.db.models import Q, F

from ..models import Song, TrainingSession
import json
import logging

logger = logging.getLogger(__name__)

def quality_check(request):
    """曲のクオリティチェック用スタッフページ"""
    from django.db.models import Avg

    songs = Song.objects.filter(
        generation_status='completed',
    ).select_related('created_by', 'lyrics').prefetch_related('tags').order_by('-created_at')

    # フィルタ
    genre = request.GET.get('genre', '')
    vocal = request.GET.get('vocal', '')
    sort = request.GET.get('sort', '-created_at')
    q = request.GET.get('q', '')

    if genre:
        songs = songs.filter(genre__icontains=genre)
    if vocal:
        songs = songs.filter(vocal_style=vocal)
    if q:
        songs = songs.filter(
            Q(title__icontains=q) | Q(created_by__username__icontains=q)
        )

    allowed_sorts = {
        '-created_at': '-created_at',
        'created_at': 'created_at',
        '-total_plays': '-total_plays',
        '-likes_count': '-likes_count',
    }
    songs = songs.order_by(allowed_sorts.get(sort, '-created_at'))

    # 統計情報
    stats = Song.objects.filter(generation_status='completed').aggregate(
        total=Count('id'),
        avg_plays=Avg('total_plays'),
        avg_likes=Avg('likes_count'),
    )

    # ジャンル一覧（フィルタ用）
    genres = (
        Song.objects.filter(generation_status='completed')
        .exclude(genre='')
        .values_list('genre', flat=True)
        .distinct()
        .order_by('genre')
    )

    # ページネーション
    from django.core.paginator import Paginator
    paginator = Paginator(songs, 20)
    page = request.GET.get('page', 1)
    songs_page = paginator.get_page(page)

    context = {
        'songs': songs_page,
        'stats': stats,
        'genres': list(genres),
        'current_genre': genre,
        'current_vocal': vocal,
        'current_sort': sort,
        'current_q': q,
    }
    return render(request, 'songs/quality_check.html', context)


@staff_member_required
def llm_guide(request):
    """ローカルLLM学習プラットフォームの使い方ガイド（スタッフのみ）"""
    # ロック中のスタッフはレビューページに強制リダイレクト
    if not request.user.is_superuser:
        from users.models import StaffReviewObligation
        ob = StaffReviewObligation.objects.filter(
            user=request.user, is_review_locked=True
        ).first()
        if ob:
            from django.shortcuts import redirect
            return redirect('songs:training_data_viewer')
    return render(request, 'songs/llm_guide.html')


def _get_llm_base_url():
    """推論サーバーのベースURLをDBまたはsettingsから取得"""
    from ..models import TrainingSession
    session = TrainingSession.objects.filter(tunnel_url__gt='').order_by('-updated_at').first()
    if session and session.tunnel_url:
        return session.tunnel_url.rstrip('/')
    return (getattr(settings, 'LOCAL_LLM_URL', '') or '').rstrip('/')


@staff_member_required
def test_llm_page(request):
    """AI楽曲テストページ（LLM歌詞生成 + Mureka楽曲生成を統合）"""
    from ..models import TrainingSession
    from ..ai_services import MurekaAIGenerator
    inference_url = _get_llm_base_url()
    # トレーニング中かどうか確認
    active_training = TrainingSession.objects.filter(
        status__in=['training', 'generating']
    ).first()
    # Mureka API 設定確認
    generator = MurekaAIGenerator()
    api_configured = bool(generator.use_real_api and generator.api_key)
    return render(request, 'songs/test_llm.html', {
        'inference_url': inference_url,
        'is_training': bool(active_training),
        'training_status': active_training.status if active_training else None,
        'api_configured': api_configured,
    })


@staff_member_required
def test_llm_health(request):
    """推論サーバーのヘルスチェック（プロキシ）"""
    import requests as http_requests
    from ..models import TrainingSession

    # トレーニング中かどうかチェック
    active_training = TrainingSession.objects.filter(
        status__in=['training', 'generating']
    ).first()

    # start_serve コマンドが既に送信済みかチェック
    serve_starting = TrainingSession.objects.filter(
        pending_command='start_serve'
    ).exists()

    def _auto_request_serve():
        """オフライン＆学習中でない場合、自動で start_serve コマンドを送信"""
        if active_training or serve_starting:
            return False
        session = TrainingSession.objects.filter(
            pending_command='none',
            status__in=['idle', 'completed', 'failed'],
        ).first()
        if session:
            session.pending_command = 'start_serve'
            session.save(update_fields=['pending_command'])
            return True
        return False

    base_url = _get_llm_base_url()
    if not base_url:
        if active_training:
            return JsonResponse({
                'online': False, 'training': True,
                'training_status': active_training.status,
                'error': 'GPU学習中のため推論サーバーは停止中',
            })
        requested = _auto_request_serve() or serve_starting
        return JsonResponse({
            'online': False,
            'starting': requested,
            'error': '推論サーバー起動リクエスト送信済み' if requested else '推論サーバーURL が未設定',
        })
    try:
        resp = http_requests.get(f"{base_url}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            data['online'] = True
            return JsonResponse(data)
        if active_training:
            return JsonResponse({
                'online': False, 'training': True,
                'training_status': active_training.status,
                'error': 'GPU学習中のため推論サーバーは停止中',
            })
        requested = _auto_request_serve() or serve_starting
        return JsonResponse({
            'online': False,
            'starting': requested,
            'error': f'Status {resp.status_code}',
        })
    except Exception as e:
        if active_training:
            return JsonResponse({
                'online': False, 'training': True,
                'training_status': active_training.status,
                'error': 'GPU学習中のため推論サーバーは停止中',
            })
        requested = _auto_request_serve() or serve_starting
        return JsonResponse({
            'online': False,
            'starting': requested,
            'error': str(e),
        })


@staff_member_required
@require_POST
def test_llm_generate(request):
    """推論テスト: ローカルLLM or Gemini で歌詞生成"""
    import requests as http_requests
    import time

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    text = data.get('text', '').strip()
    if not text:
        return JsonResponse({'success': False, 'error': 'テキストが空です'}, status=400)

    genre = data.get('genre', 'pop')
    language_mode = data.get('language_mode', 'japanese')
    custom_request = data.get('custom_request', '')
    backend = data.get('backend', 'local')

    start_time = time.time()

    if backend == 'gemini':
        # Gemini で比較生成
        try:
            generator = GeminiLyricsGenerator()
            lyrics = generator.generate_lyrics(
                text, title='', genre=genre,
                language_mode=language_mode,
                custom_request=custom_request,
            )
            elapsed = round(time.time() - start_time, 1)
            return JsonResponse({
                'success': True,
                'lyrics': lyrics,
                'generation_time': elapsed,
                'backend': 'Gemini',
            })
        except Exception as e:
            logger.error(f"Test LLM (Gemini) error: {e}")
            return JsonResponse({'success': False, 'error': str(e)})
    else:
        # ローカルLLM
        base_url = _get_llm_base_url()
        api_key = getattr(settings, 'LOCAL_LLM_API_KEY', '')
        timeout = getattr(settings, 'LOCAL_LLM_TIMEOUT', 120)

        if not base_url:
            return JsonResponse({'success': False, 'error': '推論サーバーURL が未設定です'})

        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        payload = {
            'text': text,
            'genre': genre,
            'language_mode': language_mode,
            'custom_request': custom_request,
        }

        try:
            resp = http_requests.post(
                f"{base_url}/generate",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            result = resp.json()
            elapsed = round(time.time() - start_time, 1)

            if result.get('status') == 'success':
                return JsonResponse({
                    'success': True,
                    'lyrics': result.get('lyrics', ''),
                    'generation_time': elapsed,
                    'backend': 'Local LLM',
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': result.get('error', 'Unknown error'),
                })
        except http_requests.exceptions.Timeout:
            return JsonResponse({'success': False, 'error': f'タイムアウト ({timeout}秒)'})
        except http_requests.exceptions.ConnectionError:
            return JsonResponse({'success': False, 'error': '推論サーバーに接続できません'})
        except Exception as e:
            logger.error(f"Test LLM (Local) error: {e}")
            return JsonResponse({'success': False, 'error': str(e)})


# ═══════════════════════════════════════════════════════════════════
# Mureka 楽曲生成テストページ（スタッフのみ）
# ═══════════════════════════════════════════════════════════════════

@staff_member_required
def test_mureka_page(request):
    """旧Murekaテストページ → 統合テストページにリダイレクト"""
    from django.shortcuts import redirect
    return redirect('songs:test_llm')


@staff_member_required
@require_POST
def test_mureka_submit(request):
    """Mureka API へ楽曲生成リクエストを送信（タスクID返却）"""
    import requests as http_requests

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    lyrics = data.get('lyrics', '').strip()
    if not lyrics or len(lyrics) < 30:
        return JsonResponse({'success': False, 'error': '歌詞が短すぎます（30文字以上）'}, status=400)

    genre = data.get('genre', 'pop')
    vocal_style = data.get('vocal_style', 'female')
    music_prompt = data.get('music_prompt', '')
    title = data.get('title', 'Test Song')

    api_key = getattr(settings, 'MUREKA_API_KEY', None)
    base_url = getattr(settings, 'MUREKA_API_URL', 'https://api.mureka.ai')
    use_api = getattr(settings, 'USE_MUREKA_API', False)

    if not use_api or not api_key:
        return JsonResponse({'success': False, 'error': 'Mureka API が未設定です'})

    from ..ai_services import MurekaAIGenerator
    generator = MurekaAIGenerator()

    # プロンプト構築（_generate_with_mureka_api と同じロジックの一部）
    import random
    is_auto_genre = not genre or genre.strip().lower() in ('', 'auto', 'おまかせ')
    genre_en = genre if not is_auto_genre else ''

    prompt_parts = []
    if genre_en:
        prompt_parts.append(genre_en)
    if vocal_style:
        prompt_parts.append(f'{vocal_style} vocal')
    if music_prompt:
        translated = generator._translate_prompt_to_english(music_prompt)
        prompt_parts.append(translated)

    full_prompt = ', '.join(prompt_parts)
    full_prompt += ', short intro under 10 seconds, short outro under 10 seconds, start singing quickly'

    # Mureka API に送信
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'lyrics': lyrics[:2500],
        'model': 'auto',
        'prompt': full_prompt,
    }

    try:
        resp = http_requests.post(
            f'{base_url}/v1/song/generate',
            headers=headers,
            json=payload,
            timeout=60,
        )
        logger.info(f'[TEST-MUREKA] Submit status={resp.status_code} body={resp.text[:300]}')

        if resp.status_code == 200:
            result = resp.json()
            task_id = result.get('id')
            if task_id:
                return JsonResponse({
                    'success': True,
                    'task_id': task_id,
                    'prompt_used': full_prompt,
                })
            return JsonResponse({'success': False, 'error': 'タスクIDが返りませんでした'})
        elif resp.status_code == 429:
            return JsonResponse({'success': False, 'error': 'レート制限中です。しばらく待ってください。'})
        else:
            return JsonResponse({'success': False, 'error': f'API Error {resp.status_code}: {resp.text[:200]}'})

    except http_requests.exceptions.Timeout:
        return JsonResponse({'success': False, 'error': 'Mureka API タイムアウト（60秒）'})
    except Exception as e:
        logger.error(f'[TEST-MUREKA] Submit error: {e}')
        return JsonResponse({'success': False, 'error': str(e)})


@staff_member_required
def test_mureka_poll(request):
    """Mureka タスクステータスをポーリング"""
    import requests as http_requests

    task_id = request.GET.get('task_id')
    if not task_id:
        return JsonResponse({'error': 'task_id required'}, status=400)

    api_key = getattr(settings, 'MUREKA_API_KEY', None)
    base_url = getattr(settings, 'MUREKA_API_URL', 'https://api.mureka.ai')

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    try:
        resp = http_requests.get(
            f'{base_url}/v1/song/query/{task_id}',
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            result = resp.json()
            status = result.get('status', 'unknown')

            if status in ('completed', 'succeeded'):
                choices = result.get('choices', [])
                if choices:
                    choice = choices[0]
                    return JsonResponse({
                        'status': 'completed',
                        'audio_url': choice.get('url'),
                        'duration': choice.get('duration'),
                        'image_url': choice.get('image_url'),
                    })
                return JsonResponse({'status': 'failed', 'error': '楽曲データがありません'})

            elif status in ('failed', 'error', 'cancelled'):
                return JsonResponse({
                    'status': 'failed',
                    'error': result.get('error', result.get('message', status)),
                })
            else:
                return JsonResponse({'status': status})
        elif resp.status_code == 404:
            return JsonResponse({'status': 'failed', 'error': 'タスクが見つかりません'})
        else:
            return JsonResponse({'status': 'error', 'error': f'HTTP {resp.status_code}'})

    except Exception as e:
        logger.error(f'[TEST-MUREKA] Poll error: {e}')
        return JsonResponse({'status': 'error', 'error': str(e)})


# =============================================================================
# スタッフ活動監視（スーパーユーザー専用）
# =============================================================================

def superuser_required(view_func):
    """スーパーユーザーのみアクセス可能"""
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            from django.http import Http404
            raise Http404
        return view_func(request, *args, **kwargs)
    return wrapper


@superuser_required
def staff_monitor(request):
    """スタッフの学習データ活動を監視するページ（スーパーユーザー専用）"""
    from users.models import (
        User, StaffReviewObligation, TrainingDataReview,
        TrainingDataEditLog,
    )
    from django.db.models import Max, Count, F as _F_mon
    from django.utils import timezone as _tz_mon

    today = _tz_mon.localdate()

    # --- 全スタッフのノルマを最新化（表示用に計算するだけ、DBは更新しない） ---
    # 実際の加算は各スタッフがtraining-dataにアクセスした時のみ行う

    staff_users = User.objects.filter(is_staff=True).exclude(is_superuser=True)

    staff_data = []
    for user in staff_users:
        obligation = StaffReviewObligation.objects.filter(user=user).first()
        review_count = TrainingDataReview.objects.filter(reviewer=user).count()
        edit_count = TrainingDataEditLog.objects.filter(editor=user).count()
        last_review = TrainingDataReview.objects.filter(reviewer=user).aggregate(
            last=Max('reviewed_at'))['last']
        last_edit = TrainingDataEditLog.objects.filter(editor=user).aggregate(
            last=Max('edited_at'))['last']

        last_activity = None
        if last_review and last_edit:
            last_activity = max(last_review, last_edit)
        else:
            last_activity = last_review or last_edit

        # 表示用: まだ加算されてない分を計算
        projected_pending = 0
        pending_extra = 0
        if obligation:
            projected_pending = obligation.pending_reviews
            if obligation.last_checked_date < today:
                days_missed = (today - obligation.last_checked_date).days
                pending_extra = days_missed * 5
                projected_pending += pending_extra

        staff_data.append({
            'user': user,
            'obligation': obligation,
            'review_count': review_count,
            'edit_count': edit_count,
            'last_activity': last_activity,
            'projected_pending': projected_pending,
            'pending_extra': pending_extra,
        })

    # 非スタッフユーザー一覧（スタッフ昇格用）
    non_staff_users = User.objects.filter(
        is_staff=False, is_active=True
    ).exclude(is_superuser=True).order_by('username')

    return render(request, 'songs/staff_monitor.html', {
        'staff_data': staff_data,
        'non_staff_users': non_staff_users,
        'page_title': 'スタッフ活動監視',
    })


@superuser_required
@require_POST
def staff_monitor_api(request):
    """スタッフのノルマ調整・ロック解除API（スーパーユーザー専用）"""
    import json
    from users.models import User, StaffReviewObligation

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    action = body.get('action')
    username = body.get('username')

    # reset_all はusername不要
    if action == 'reset_all':
        from django.utils import timezone as _tz_api
        today_api = _tz_api.localdate()
        updated = StaffReviewObligation.objects.filter(
            user__is_staff=True, user__is_active=True
        ).update(
            pending_reviews=0,
            is_review_locked=False,
            last_checked_date=today_api,
        )
        logger.info(f'[STAFF-MONITOR] Reset ALL ({updated} records) by {request.user.username}')
        return JsonResponse({
            'ok': True,
            'message': f'全スタッフ（{updated}名）のノルマをリセットしました',
        })

    if not username:
        return JsonResponse({'ok': False, 'error': 'username required'}, status=400)

    try:
        user = User.objects.get(username=username, is_staff=True)
    except User.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'User not found'}, status=404)

    ob = StaffReviewObligation.objects.filter(user=user).first()
    if not ob:
        return JsonResponse({'ok': False, 'error': 'Obligation not found'}, status=404)

    if action == 'unlock':
        ob.is_review_locked = False
        ob.save(update_fields=['is_review_locked'])
        logger.info(f'[STAFF-MONITOR] Unlocked {username} by {request.user.username}')
        return JsonResponse({
            'ok': True,
            'message': f'{username} のロックを解除しました',
            'is_locked': False,
            'pending': ob.pending_reviews,
        })

    elif action == 'set_pending':
        value = body.get('value')
        if value is None:
            return JsonResponse({'ok': False, 'error': 'value required'}, status=400)
        try:
            value = int(value)
        except (ValueError, TypeError):
            return JsonResponse({'ok': False, 'error': 'value must be integer'}, status=400)
        if value < 0:
            value = 0
        ob.pending_reviews = value
        # 35未満になったらロック解除
        if value < 35 and ob.is_review_locked:
            ob.is_review_locked = False
        # 35以上になったらロック
        if value >= 35 and not ob.is_review_locked:
            ob.is_review_locked = True
        ob.save(update_fields=['pending_reviews', 'is_review_locked'])
        logger.info(
            f'[STAFF-MONITOR] Set {username} pending={value} '
            f'locked={ob.is_review_locked} by {request.user.username}'
        )
        return JsonResponse({
            'ok': True,
            'message': f'{username} のノルマを {value} に設定しました',
            'is_locked': ob.is_review_locked,
            'pending': ob.pending_reviews,
        })

    elif action == 'reset':
        ob.pending_reviews = 0
        ob.is_review_locked = False
        ob.save(update_fields=['pending_reviews', 'is_review_locked'])
        logger.info(f'[STAFF-MONITOR] Reset {username} by {request.user.username}')
        return JsonResponse({
            'ok': True,
            'message': f'{username} のノルマをリセットしました',
            'is_locked': False,
            'pending': 0,
        })

    else:
        return JsonResponse({'ok': False, 'error': f'Unknown action: {action}'}, status=400)


@superuser_required
@require_http_methods(["GET"])
def staff_monitor_refresh(request):
    """スタッフ監視データをJSONで返す（リアルタイム更新用）"""
    from users.models import (
        User, StaffReviewObligation, TrainingDataReview,
        TrainingDataEditLog,
    )
    from django.db.models import Max
    from django.utils import timezone as _tz_ref

    today = _tz_ref.localdate()
    staff_users = User.objects.filter(is_staff=True).exclude(is_superuser=True)

    staff_list = []
    locked_count = 0
    total_reviews = 0

    for user in staff_users:
        obligation = StaffReviewObligation.objects.filter(user=user).first()
        review_count = TrainingDataReview.objects.filter(reviewer=user).count()
        edit_count = TrainingDataEditLog.objects.filter(editor=user).count()
        last_review = TrainingDataReview.objects.filter(reviewer=user).aggregate(
            last=Max('reviewed_at'))['last']
        last_edit = TrainingDataEditLog.objects.filter(editor=user).aggregate(
            last=Max('edited_at'))['last']

        last_activity = None
        if last_review and last_edit:
            last_activity = max(last_review, last_edit)
        else:
            last_activity = last_review or last_edit

        projected_pending = 0
        pending_extra = 0
        is_locked = False
        has_obligation = False

        if obligation:
            has_obligation = True
            projected_pending = obligation.pending_reviews
            is_locked = obligation.is_review_locked
            if obligation.last_checked_date < today:
                days_missed = (today - obligation.last_checked_date).days
                pending_extra = days_missed * 5
                projected_pending += pending_extra

        if is_locked:
            locked_count += 1
        total_reviews += review_count

        staff_list.append({
            'username': user.username,
            'has_obligation': has_obligation,
            'pending': obligation.pending_reviews if obligation else 0,
            'projected_pending': projected_pending,
            'pending_extra': pending_extra,
            'is_locked': is_locked,
            'review_count': review_count,
            'edit_count': edit_count,
            'last_activity': last_activity.isoformat() if last_activity else None,
        })

    return JsonResponse({
        'ok': True,
        'staff': staff_list,
        'locked_count': locked_count,
        'total_reviews': total_reviews,
    })