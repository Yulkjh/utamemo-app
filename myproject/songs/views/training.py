from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.db.models import Q, F

from ..models import Song, TrainingSession, PromptTemplate, TrainingData
import json
import logging

logger = logging.getLogger(__name__)

# トレーニング監視ダッシュボード
# =============================================================================

@staff_member_required
def training_data_viewer(request):
    """学習データ確認・編集ページ（管理者のみ）"""
    import json
    import re
    from django.utils import timezone as _tz
    from users.models import StaffReviewObligation

    # --- スタッフレビュー義務: 初回アクセス記録（スーパーユーザーは対象外） ---
    today = _tz.localdate()
    obligation = None
    if request.user.is_superuser:
        # スーパーユーザーの古いObligationレコードがあれば削除
        StaffReviewObligation.objects.filter(user=request.user).delete()
    else:
        obligation, created = StaffReviewObligation.objects.get_or_create(
            user=request.user,
            defaults={
                'first_access_date': today,
                'pending_reviews': 0,
                'last_checked_date': today,
            },
        )

        # --- 日次ノルマ加算（Cron不要: アクセス時にチェック） ---
        if not created and obligation.last_checked_date < today:
            from django.db.models import F as _F_ob
            days_missed = (today - obligation.last_checked_date).days
            increment = days_missed * 5  # 1日あたり+5
            StaffReviewObligation.objects.filter(pk=obligation.pk).update(
                pending_reviews=_F_ob('pending_reviews') + increment,
                last_checked_date=today,
            )
            obligation.refresh_from_db()
            # 35以上でロック
            if obligation.pending_reviews >= 35 and not obligation.is_review_locked:
                obligation.is_review_locked = True
                obligation.save(update_fields=['is_review_locked'])
                logger.warning(
                    f'Staff review lock: {request.user.username} '
                    f'(pending={obligation.pending_reviews})'
                )

    from ..models import TrainingData
    data_records = TrainingData.objects.all()
    records = [r.to_dict() for r in data_records]

    # ジャンル抽出
    genre_counts = {}
    for r in records:
        m = re.search(r'から(\w+)ジャンルの歌詞', r.get('instruction', ''))
        g = m.group(1) if m else 'other'
        genre_counts[g] = genre_counts.get(g, 0) + 1

    # レビュー済みマップ生成: { data_hash: [username, ...] }
    from users.models import TrainingDataReview, make_data_hash
    reviews_qs = TrainingDataReview.objects.select_related('reviewer').all()
    reviewed_map = {}  # hash -> [usernames]
    trained_hashes = set()
    for rv in reviews_qs:
        key = rv.data_hash or str(rv.data_index)  # 旧データはdata_indexフォールバック
        reviewed_map.setdefault(key, []).append(rv.reviewer.username)
        if rv.trained_at is not None:
            trained_hashes.add(key)

    # 未レビュー件数を算出 (レビュー済みハッシュに含まれないレコード)
    reviewed_hashes = set(reviewed_map.keys())
    all_hashes = {r['_hash'] for r in records}
    unreviewed_count = len(all_hashes - reviewed_hashes)

    return render(request, 'songs/training_data_viewer.html', {
        'records_json': json.dumps(records, ensure_ascii=False),
        'total_count': len(records),
        'genre_counts': json.dumps(genre_counts, ensure_ascii=False),
        'page_title': '学習データ管理',
        'pending_reviews': obligation.pending_reviews if obligation else 0,
        'is_review_locked': obligation.is_review_locked if obligation else False,
        'is_superuser': request.user.is_superuser,
        'reviewed_map_json': json.dumps(reviewed_map, ensure_ascii=False),
        'trained_hashes_json': json.dumps(sorted(trained_hashes)),
        'current_username': request.user.username,
        'unreviewed_count': unreviewed_count,
        'reviewed_count': len(reviewed_hashes),
    })


@staff_member_required
@require_POST
def training_data_api(request):
    """学習データの編集・削除・追加API（管理者のみ）"""
    import json
    from django.db.models import F as _F
    from users.models import StaffReviewObligation
    from ..models import TrainingData

    def _decrement_pending(user):
        """編集/削除1回ごとに pending_reviews を -1（下限0）"""
        updated = StaffReviewObligation.objects.filter(
            user=user, pending_reviews__gt=0
        ).update(pending_reviews=_F('pending_reviews') - 1)
        if updated:
            # ロック解除判定（35未満になったら解除）
            StaffReviewObligation.objects.filter(
                user=user, pending_reviews__lt=35, is_review_locked=True
            ).update(is_review_locked=False)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    action = body.get('action')

    if action == 'update':
        data_hash = body.get('data_hash')
        index = body.get('index')
        if not data_hash:
            return JsonResponse({'error': 'data_hash required'}, status=400)

        try:
            record = TrainingData.objects.get(data_hash=data_hash)
        except TrainingData.DoesNotExist:
            return JsonResponse({'error': f'Record not found: {data_hash}'}, status=404)

        new_input = body.get('input')
        new_output = body.get('output')
        new_instruction = body.get('instruction')

        if new_input is not None:
            record.input_text = new_input
        if new_output is not None:
            record.output_text = new_output
        if new_instruction is not None:
            record.instruction = new_instruction
        record.save()

        _decrement_pending(request.user)
        obligation = StaffReviewObligation.objects.filter(user=request.user).first()
        pending = obligation.pending_reviews if obligation else 0
        display_idx = (index + 1) if isinstance(index, int) else '?'
        return JsonResponse({'ok': True, 'message': f'#{display_idx} を更新しました', 'pending_reviews': pending})

    elif action == 'delete':
        data_hash = body.get('data_hash')
        index = body.get('index')
        if not data_hash:
            return JsonResponse({'error': 'data_hash required'}, status=400)

        deleted_count, _ = TrainingData.objects.filter(data_hash=data_hash).delete()
        if deleted_count == 0:
            return JsonResponse({'error': f'Record not found: {data_hash}'}, status=404)

        _decrement_pending(request.user)
        obligation = StaffReviewObligation.objects.filter(user=request.user).first()
        pending = obligation.pending_reviews if obligation else 0
        total = TrainingData.objects.count()
        display_idx = (index + 1) if isinstance(index, int) else '?'
        return JsonResponse({'ok': True, 'message': f'#{display_idx} を削除しました', 'total': total, 'pending_reviews': pending})

    elif action == 'reload':
        records = [r.to_dict() for r in TrainingData.objects.all()]
        return JsonResponse({'ok': True, 'records': records, 'total': len(records)})

    elif action == 'mark_reviewed':
        data_hash = body.get('data_hash')
        index = body.get('index')
        if not data_hash:
            return JsonResponse({'error': 'data_hash required'}, status=400)
        from users.models import TrainingDataReview
        # ソフトデリート済みのレコードがあれば復元、なければ新規作成
        existing = TrainingDataReview.all_objects.filter(
            data_hash=data_hash,
            reviewer=request.user,
        ).first()
        if existing:
            if existing.is_deleted:
                existing.restore()
                created = True
            else:
                created = False
            if isinstance(index, int):
                existing.data_index = index
                existing.save(update_fields=['data_index'])
        else:
            TrainingDataReview.all_objects.create(
                data_hash=data_hash,
                reviewer=request.user,
                data_index=index if isinstance(index, int) else 0,
            )
            created = True
        _decrement_pending(request.user)
        obligation = StaffReviewObligation.objects.filter(user=request.user).first()
        pending = obligation.pending_reviews if obligation else 0
        reviews = list(TrainingDataReview.objects.filter(data_hash=data_hash).select_related('reviewer').values_list('reviewer__username', flat=True))
        display_idx = (index + 1) if isinstance(index, int) else '?'
        return JsonResponse({
            'ok': True,
            'message': f'#{display_idx} を確認済みにしました' if created else f'#{display_idx} は既に確認済みです',
            'pending_reviews': pending,
            'reviewers': reviews,
            'data_hash': data_hash,
        })

    elif action == 'unmark_reviewed':
        data_hash = body.get('data_hash')
        index = body.get('index')
        if not data_hash:
            return JsonResponse({'error': 'data_hash required'}, status=400)
        from users.models import TrainingDataReview
        # ソフトデリート（復元可能）
        from django.utils import timezone as tz
        soft_deleted = TrainingDataReview.objects.filter(
            data_hash=data_hash,
            reviewer=request.user,
        ).update(is_deleted=True, deleted_at=tz.now())
        reviews = list(TrainingDataReview.objects.filter(data_hash=data_hash).select_related('reviewer').values_list('reviewer__username', flat=True))
        display_idx = (index + 1) if isinstance(index, int) else '?'
        return JsonResponse({
            'ok': True,
            'message': f'#{display_idx} の確認を取り消しました',
            'reviewers': reviews,
            'data_hash': data_hash,
        })

    else:
        return JsonResponse({'error': f'Unknown action: {action}'}, status=400)


# ── プロンプト設定（DB管理） ──

_DEFAULT_INSTRUCTION_TEMPLATE = (
    "あなたは暗記学習用の歌詞作成の専門家です。以下の学習テキストから{genre}ジャンルの歌詞を作成してください。\n"
    "\n"
    "スタイルの参考: エグスプロージョンの「本能寺の変」のようなノリ。\n"
    "ただし「本能寺の変」よりは学習内容の情報量を多めにしてください。\n"
    "重要な用語・人物名・年号を歌詞に織り込みつつ、気楽に聞ける曲にしてください。\n"
    "\n"
    "【重要なルール】\n"
    "- 「ぱっと気楽に聞ける」ことが最優先。聴いていて疲れる歌詞はNG。\n"
    "- 1行は10〜20文字程度。自然に口ずさめるリズム感を大事に。\n"
    "- 「○○は○○ ○○は○○ ○○は○○」のような事実の羅列は絶対にしない。ストーリーや流れを作る。\n"
    "- 「暗記しよう」「覚えよう」「チェケラ」「Peace out」等のメタ的フレーズは入れない。\n"
    "- (Hey!) (Ho!) (Yo!) (What's up?) 等の意味のない合いの手は使わない。\n"
    "- 韻を踏んでキャッチーに。ユーモアもOK。\n"
    "出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。"
)

_GENRES = ["pop", "rock", "hip-hop", "EDM", "jazz", "R&B", "folk", "J-pop", "K-pop"]


def _get_instruction_template():
    """DB からプロンプトテンプレートを取得（なければデフォルト）"""
    from ..models import PromptTemplate
    return PromptTemplate.get_template('lyrics_instruction', _DEFAULT_INSTRUCTION_TEMPLATE)


def _get_instruction_template_with_meta():
    """DB からプロンプトテンプレートと編集者情報を取得"""
    from ..models import PromptTemplate
    try:
        obj = PromptTemplate.objects.get(key='lyrics_instruction')
        return {
            'instruction_template': obj.content,
            'updated_by': obj.updated_by.username if obj.updated_by else None,
            'updated_at': obj.updated_at.isoformat() if obj.updated_at else None,
        }
    except PromptTemplate.DoesNotExist:
        return {
            'instruction_template': _DEFAULT_INSTRUCTION_TEMPLATE,
            'updated_by': None,
            'updated_at': None,
        }


@staff_member_required
@require_POST
def training_data_generate(request):
    """Gemini APIで学習データを5件生成"""
    from ..models import TrainingData
    try:
        import google.generativeai as genai
    except ImportError:
        return JsonResponse({'error': 'google-generativeai がインストールされていません'}, status=500)

    gemini_key = settings.GEMINI_API_KEY
    if not gemini_key:
        return JsonResponse({'error': 'GEMINI_API_KEY が未設定です'}, status=500)

    records = [r.to_dict() for r in TrainingData.objects.all()]

    # プロンプト設定をDBから読み込み
    instruction_template = _get_instruction_template()

    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel("gemini-2.5-pro")

    # 既存テーマリスト（重複回避）
    existing_summaries = []
    for r in records:
        inp = r.get("input", "")
        theme = inp.split(" ")[0] if inp else ""
        if theme:
            existing_summaries.append(theme)
    existing_list = "、".join(existing_summaries[-80:])

    subjects = [
        "日本史", "世界史", "生物", "化学", "物理",
        "地理", "数学", "英語文法", "公民", "地学",
    ]

    generated = []
    errors = []
    count = 5

    for i in range(count):
        genre = _GENRES[i % len(_GENRES)]
        prompt = (
            f"あなたは中学・高校の教育コンテンツと暗記用歌詞の生成AIです。\n"
            f"以下の教科からランダムに1つのテーマを選んでください:\n"
            f"教科: {', '.join(subjects)}\n\n"
            f"以下のテーマは既に生成済みなので、これら以外の新しいテーマを選んでください:\n"
            f"{existing_list}\n\n"
            f"以下のJSON形式で出力してください（JSON以外は出力しないでください）:\n"
            f'{{\n'
            f'  "subject": "教科名",\n'
            f'  "theme": "テーマ名（簡潔に）",\n'
            f'  "input": "テーマの学習テキスト（200文字程度、重要な事実・年号・人物名・公式を含む詳細な説明）",\n'
            f'  "keywords": ["重要キーワード1", "重要キーワード2", ...],\n'
            f'  "output": "{genre}ジャンルの暗記用歌詞。エグスプロージョンの本能寺の変よりは情報量多めだが、ぱっと気楽に聞けることが最優先。'
            f'1行10〜20文字。事実の羅列は絶対にしない。ストーリーや流れを作る。'
            f'「暗記しよう」等のメタ的フレーズや(Hey!)(Yo!)等の無意味な合いの手は入れない。'
            f'韻を踏んでキャッチーに。[Verse 1], [Chorus], [Verse 2]等のセクションラベル付き。"\n'
            f'}}'
        )
        try:
            response = model.generate_content(prompt, request_options={"timeout": 90})
            text = response.text.strip()

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            if not all(k in data for k in ("input", "output")):
                errors.append(f"[{i+1}] 必須フィールドなし")
                continue
            if "[Verse" not in data["output"] and "[Chorus" not in data["output"]:
                errors.append(f"[{i+1}] セクションラベルなし")
                continue

            instruction = instruction_template.format(genre=genre)
            record = {
                "instruction": instruction,
                "input": data["input"],
                "output": data["output"],
            }
            # DBに保存
            td = TrainingData.objects.create(
                instruction=instruction,
                input_text=data["input"],
                output_text=data["output"],
            )
            record['_hash'] = td.data_hash
            records.append(record)
            generated.append({
                'subject': data.get('subject', '?'),
                'theme': data.get('theme', data['input'][:30]),
                'genre': genre,
            })
            # 既存リストに追加（次の生成時の重複回避）
            existing_summaries.append(data["input"].split(" ")[0])
            existing_list = "、".join(existing_summaries[-80:])

        except Exception as e:
            errors.append(f"[{i+1}] {str(e)[:100]}")

    # 保存はDBに直接行われるため、ファイル書き込み不要

    return JsonResponse({
        'ok': True,
        'generated': generated,
        'generated_count': len(generated),
        'total': len(records),
        'errors': errors,
        'records': records,
    })


@staff_member_required
def training_prompt_api(request):
    """プロンプト設定の取得・更新（DB管理）"""
    from ..models import PromptTemplate

    if request.method == 'GET':
        meta = _get_instruction_template_with_meta()
        return JsonResponse({'ok': True, **meta})

    elif request.method == 'POST':
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        instruction_template = body.get('instruction_template', '').strip()
        if not instruction_template:
            return JsonResponse({'error': 'プロンプトが空です'}, status=400)
        if '{genre}' not in instruction_template:
            return JsonResponse({'error': 'プロンプトに {genre} プレースホルダーが必要です'}, status=400)

        # DBに保存（編集者情報も記録）
        obj = PromptTemplate.set_template(
            key='lyrics_instruction',
            content=instruction_template,
            user=request.user,
        )

        # generate_history_data.py のINSTRUCTION_TEMPLATEも同期（ローカル開発用）
        _sync_prompt_to_script(instruction_template)

        return JsonResponse({
            'ok': True,
            'message': 'プロンプトを保存しました',
            'updated_by': request.user.username,
            'updated_at': obj.updated_at.isoformat(),
        })

    return JsonResponse({'error': 'Method not allowed'}, status=405)


def _sync_prompt_to_script(instruction_template):
    """generate_history_data.pyのINSTRUCTION_TEMPLATEを同期更新"""
    import re
    script_path = Path(__file__).resolve().parent.parent.parent / 'training' / 'generate_history_data.py'
    if not script_path.exists():
        return
    try:
        content = script_path.read_text(encoding='utf-8')
        # INSTRUCTION_TEMPLATE = ( ... ) のブロックを置換
        pattern = r'INSTRUCTION_TEMPLATE\s*=\s*\(.*?\)\s*\n'
        # エスケープしてPython文字列に
        escaped = instruction_template.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        replacement = f'INSTRUCTION_TEMPLATE = (\n    "{escaped}"\n)\n'
        new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        if new_content != content:
            script_path.write_text(new_content, encoding='utf-8')
    except Exception as e:
        logger.warning(f"INSTRUCTION_TEMPLATE同期失敗: {e}")


@staff_member_required
def training_dashboard(request):
    """LLMトレーニング監視ダッシュボード（管理者のみ）"""
    from ..models import TrainingSession

    sessions = TrainingSession.objects.all()[:20]
    active_sessions = [s for s in sessions if s.is_active]

    return render(request, 'songs/training_dashboard.html', {
        'sessions': sessions,
        'active_sessions': active_sessions,
        'page_title': 'LLM Training Monitor',
    })


@csrf_exempt
@require_POST
def training_api_update(request):
    """トレーニングスクリプトから進捗を受信するAPIエンドポイント"""
    from ..models import TrainingSession
    from django.utils import timezone
    import hmac

    api_key = request.headers.get('X-Training-Api-Key', '')
    if not api_key:
        return JsonResponse({'error': 'API key required'}, status=401)

    try:
        session = TrainingSession.objects.get(api_key=api_key)
    except TrainingSession.DoesNotExist:
        return JsonResponse({'error': 'Invalid API key'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    allowed_fields = {
        'status', 'machine_name', 'machine_ip', 'model_name',
        'current_epoch', 'total_epochs', 'train_loss', 'eval_loss',
        'accuracy', 'gpu_name', 'gpu_memory_used', 'gpu_memory_total',
        'training_config', 'log_tail', 'error_message', 'training_type',
        'current_step', 'total_steps', 'tunnel_url', 'eta_seconds',
    }

    for field, value in data.items():
        if field in allowed_fields:
            setattr(session, field, value)

    # エラーでないステータスに変わったらerror_messageを自動クリア
    if data.get('status') in ('idle', 'training', 'generating', 'completed'):
        if 'error_message' not in data:
            session.error_message = ''

    # idle/completed/failedではETAをクリア
    if data.get('status') in ('idle', 'completed', 'failed'):
        session.eta_seconds = None

    if data.get('status') == 'training' and not session.started_at:
        session.started_at = timezone.now()
    if data.get('status') in ('completed', 'failed') and not session.completed_at:
        session.completed_at = timezone.now()

    session.save()

    # コマンドがあれば返して消す（poll=Trueの場合のみ = エージェントからのポーリング）
    command = 'none'
    if data.get('poll'):
        command = session.pending_command
        if command != 'none':
            session.pending_command = 'none'
            session.save(update_fields=['pending_command'])

    return JsonResponse({'ok': True, 'session_id': session.id, 'command': command, 'training_type': session.training_type})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def training_reviewed_indices(request):
    """レビュー済み（未学習）データインデックスを返すAPIエンドポイント（APIキー認証）

    trained_at が null のもののみ返す → 二重学習防止。
    POST で indices を送ると学習済みマークを付ける (mark_trained)。
    """
    from ..models import TrainingSession
    from users.models import TrainingDataReview

    api_key = request.headers.get('X-Training-Api-Key', '')
    if not api_key:
        return JsonResponse({'error': 'API key required'}, status=401)

    try:
        TrainingSession.objects.get(api_key=api_key)
    except TrainingSession.DoesNotExist:
        return JsonResponse({'error': 'Invalid API key'}, status=403)

    # POST: 学習完了後に trained_at をセット
    if request.method == 'POST':
        import json as _json
        from django.utils import timezone
        try:
            body = _json.loads(request.body)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        # リセットモード: trained_at を null に戻す
        if body.get('action') == 'reset':
            reset_count = TrainingDataReview.objects.filter(
                trained_at__isnull=False,
            ).update(trained_at=None)
            logger.info('学習済みマーク全リセット: %d 件', reset_count)
            return JsonResponse({'ok': True, 'reset': reset_count})

        # ハッシュベース (推奨)
        trained_hashes = body.get('trained_hashes', [])
        if trained_hashes and isinstance(trained_hashes, list):
            now = timezone.now()
            updated = TrainingDataReview.objects.filter(
                data_hash__in=trained_hashes,
                trained_at__isnull=True,
            ).update(trained_at=now)
            logger.info('学習済みマーク(hash): %d 件 (hashes=%s)', updated, trained_hashes)
            return JsonResponse({'ok': True, 'marked': updated})

        # 後方互換: インデックスベース (非推奨)
        indices = body.get('trained_indices', [])
        if isinstance(indices, list) and indices:
            now = timezone.now()
            updated = TrainingDataReview.objects.filter(
                data_index__in=indices,
                trained_at__isnull=True,
            ).update(trained_at=now)
            logger.info('学習済みマーク(index, 非推奨): %d 件 (indices=%s)', updated, indices)
            return JsonResponse({'ok': True, 'marked': updated})

        return JsonResponse({'error': 'trained_hashes or trained_indices required'}, status=400)

    # GET: レビュー済み かつ 未学習 のハッシュ+インデックスを返す
    reviewed_qs = TrainingDataReview.objects.filter(
        trained_at__isnull=True,
    ).values('data_hash', 'data_index').distinct()
    reviewed_hashes = sorted(set(r['data_hash'] for r in reviewed_qs if r['data_hash']))
    reviewed_indices = sorted(set(r['data_index'] for r in reviewed_qs))
    return JsonResponse({
        'ok': True,
        'reviewed_hashes': reviewed_hashes,
        'reviewed_indices': reviewed_indices,  # 後方互換
    })


@csrf_exempt
@require_http_methods(["GET"])
def training_data_download(request):
    """学習データJSON全件をダウンロードするAPI（APIキー認証）

    学校PC / 自宅PC から学習前に最新データを取得するためのエンドポイント。
    GET /api/training/data/download/
    Header: X-Training-Api-Key: <api_key>
    Response: 学習データJSON配列 + プロンプトテンプレート
    """
    from ..models import TrainingSession, PromptTemplate, TrainingData

    api_key = request.headers.get('X-Training-Api-Key', '')
    if not api_key:
        return JsonResponse({'error': 'API key required'}, status=401)

    try:
        TrainingSession.objects.get(api_key=api_key)
    except TrainingSession.DoesNotExist:
        return JsonResponse({'error': 'Invalid API key'}, status=403)

    records = [r.to_dict() for r in TrainingData.objects.all()]

    # プロンプトテンプレートも返す
    prompt = PromptTemplate.get_template('lyrics_instruction')

    return JsonResponse({
        'ok': True,
        'total': len(records),
        'records': records,
        'prompt_template': prompt or '',
    })


@csrf_exempt
@require_POST
def training_data_upload(request):
    """GPUマシンからサーバーへ学習データをアップロード（マージ）するAPI

    POST /api/training/data/upload/
    Header: X-Training-Api-Key: <api_key>
    Body: {"records": [...], "mode": "merge"|"replace"}

    mode:
      - "merge" (デフォルト): 新規レコードのみ追加（input の先頭50文字で重複判定）
      - "replace": サーバー側を完全に置き換え（危険 - 管理者専用）
    """
    from ..models import TrainingSession, TrainingData
    from users.models import make_data_hash
    from django.db import transaction

    api_key = request.headers.get('X-Training-Api-Key', '')
    if not api_key:
        return JsonResponse({'error': 'API key required'}, status=401)

    try:
        session = TrainingSession.objects.get(api_key=api_key)
    except TrainingSession.DoesNotExist:
        return JsonResponse({'error': 'Invalid API key'}, status=403)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    upload_records = body.get('records', [])
    mode = body.get('mode', 'merge')

    if not isinstance(upload_records, list):
        return JsonResponse({'error': 'records must be a list'}, status=400)

    if not upload_records:
        return JsonResponse({'error': 'records is empty'}, status=400)

    # バリデーション: 各レコードに必須キーがあるか
    for i, rec in enumerate(upload_records):
        if not isinstance(rec, dict):
            return JsonResponse({'error': f'records[{i}] is not an object'}, status=400)
        if 'input' not in rec or 'output' not in rec:
            return JsonResponse({'error': f'records[{i}] に input/output がありません'}, status=400)

    if mode == 'replace':
        # 完全置き換え
        with transaction.atomic():
            TrainingData.objects.all().delete()
            for rec in upload_records:
                TrainingData.objects.create(
                    instruction=rec.get('instruction', ''),
                    input_text=rec.get('input', ''),
                    output_text=rec.get('output', ''),
                )
        added = len(upload_records)
        total = added
        logger.info('学習データ置換: %d 件 (by session %s)', added, session.machine_name)
    else:
        # マージ: data_hash で重複判定
        existing_hashes = set(TrainingData.objects.values_list('data_hash', flat=True))
        new_records = []
        for rec in upload_records:
            h = make_data_hash(rec.get('input', ''))
            if h not in existing_hashes:
                new_records.append(rec)
                existing_hashes.add(h)

        added = len(new_records)
        if added == 0:
            total = TrainingData.objects.count()
            return JsonResponse({
                'ok': True,
                'message': '新規データなし（すべて既存と重複）',
                'added': 0,
                'total': total,
            })

        with transaction.atomic():
            for rec in new_records:
                TrainingData.objects.create(
                    instruction=rec.get('instruction', ''),
                    input_text=rec.get('input', ''),
                    output_text=rec.get('output', ''),
                )
        total = TrainingData.objects.count()
        logger.info('学習データマージ: +%d 件 (合計 %d, by session %s)',
                     added, total, session.machine_name)

    return JsonResponse({
        'ok': True,
        'message': f'{added} 件追加しました',
        'added': added,
        'total': total,
    })


@staff_member_required
@require_POST
def training_send_command(request):
    """ダッシュボードからトレーニングコマンドを送信"""
    from ..models import TrainingSession

    session_id = request.POST.get('session_id')
    command = request.POST.get('command', '')
    if command not in ('start', 'stop', 'start_serve', 'wol'):
        return JsonResponse({'error': 'Invalid command'}, status=400)

    try:
        session = TrainingSession.objects.get(id=session_id)
    except TrainingSession.DoesNotExist:
        return JsonResponse({'error': 'Session not found'}, status=404)

    # WoLコマンド: マジックパケット送信してPCを起こす
    if command == 'wol':
        result = _send_wol_packet(session)
        return JsonResponse(result)

    session.pending_command = command
    if command == 'start':
        training_type = request.POST.get('training_type', 'lyrics')
        if training_type in ('lyrics', 'importance'):
            session.training_type = training_type
            session.save(update_fields=['pending_command', 'training_type'])
        else:
            session.save(update_fields=['pending_command'])
    else:
        session.save(update_fields=['pending_command'])
    return JsonResponse({'ok': True, 'command': command})


def _send_wol_packet(session):
    """Wake-on-LANマジックパケットを送信"""
    import re as re_mod
    import socket
    import struct

    mac = session.wol_mac_address.strip()
    target = session.wol_target_host.strip()

    if not mac:
        return {'ok': False, 'error': 'MACアドレスが未設定です (Adminで設定してください)'}

    # MACアドレスの検証・正規化
    mac_clean = re_mod.sub(r'[:\-]', '', mac)
    if not re_mod.match(r'^[0-9A-Fa-f]{12}$', mac_clean):
        return {'ok': False, 'error': f'無効なMACアドレス: {mac}'}

    # マジックパケット構築: FF x 6 + MAC x 16
    mac_bytes = bytes.fromhex(mac_clean)
    magic_packet = b'\xff' * 6 + mac_bytes * 16

    try:
        # ブロードキャスト送信 (ローカルネットワーク or ルーター経由)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(5)

        if target:
            # DDNSホスト名/グローバルIP → ルーターのWoLポートフォワード先へ送信
            dest = (target, 9)
        else:
            # ローカルブロードキャスト
            dest = ('255.255.255.255', 9)

        sock.sendto(magic_packet, dest)
        sock.close()

        logger.info(f"WoL packet sent to {mac} via {dest[0]}:{dest[1]}")
        return {'ok': True, 'message': f'WoLパケットを {mac} に送信しました'}
    except Exception as e:
        logger.error(f"WoL send failed: {e}")
        return {'ok': False, 'error': f'送信失敗: {str(e)}'}


@staff_member_required
def training_api_status_json(request):
    """ダッシュボードのAuto-refresh用 JSON API"""
    from ..models import TrainingSession

    sessions = TrainingSession.objects.all()[:20]
    result = []
    for s in sessions:
        result.append({
            'id': s.id,
            'machine_name': s.machine_name,
            'status': s.status,
            'model_name': s.model_name,
            'current_epoch': s.current_epoch,
            'total_epochs': s.total_epochs,
            'current_step': s.current_step,
            'total_steps': s.total_steps,
            'progress_percent': s.progress_percent,
            'train_loss': s.train_loss,
            'eval_loss': s.eval_loss,
            'accuracy': s.accuracy,
            'gpu_name': s.gpu_name,
            'gpu_memory_used': s.gpu_memory_used,
            'gpu_memory_total': s.gpu_memory_total,
            'log_tail': s.log_tail,
            'error_message': s.error_message,
            'eta_seconds': s.eta_seconds,
            'is_active': s.is_active,
            'pending_command': s.pending_command,
            'training_type': s.training_type,
            'wol_mac_address': s.wol_mac_address,
            'started_at': s.started_at.isoformat() if s.started_at else None,
            'completed_at': s.completed_at.isoformat() if s.completed_at else None,
            'updated_at': s.updated_at.isoformat(),
        })
    return JsonResponse({'sessions': result})
