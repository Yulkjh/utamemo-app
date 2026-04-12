"""
ユーザー制御ミドルウェア

- BanCheckMiddleware: BANされたユーザーを強制ログアウト
- StaffReviewLockMiddleware: レビュー未達成スタッフのアクセスを制限
"""

from django.shortcuts import redirect
from django.contrib.auth import logout
from django.contrib import messages
from django.urls import reverse
import logging

logger = logging.getLogger(__name__)


class StaffReviewLockMiddleware:
    """
    レビュー義務ロック状態のスタッフを学習データページに制限するミドルウェア。
    
    StaffReviewObligation.is_review_locked == True のスタッフは
    training-data 関連のページとログアウト以外アクセスできない。
    """
    
    ALLOWED_PATHS = [
        '/staff/training-data/',
        '/staff/training-history/',
        '/api/training/data/',
        '/static/',
        '/media/',
        '/accounts/logout/',
        '/users/logout/',
        '/admin/',
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        if request.user.is_authenticated and getattr(request.user, 'is_staff', False):
            path = request.path
            if not any(path.startswith(allowed) for allowed in self.ALLOWED_PATHS):
                try:
                    from users.models import StaffReviewObligation
                    obligation = StaffReviewObligation.objects.filter(
                        user=request.user
                    ).first()
                    if obligation and obligation.is_review_locked:
                        logger.warning(
                            'レビューロック中スタッフがアクセス: user=%s, path=%s',
                            request.user.username, path
                        )
                        messages.warning(
                            request,
                            '罰金3000円又は脱退でぇーす♡ '
                            '学習データページでレビューを完了してください。'
                        )
                        return redirect('/staff/training-data/')
                except Exception:
                    logger.exception('StaffReviewLockMiddleware でエラー')
        
        response = self.get_response(request)
        return response


class BanCheckMiddleware:
    """BANされたユーザーを強制ログアウトさせるミドルウェア"""
    
    # BANチェックをスキップするパス（ログアウト・静的ファイル等）
    EXEMPT_PATHS = [
        '/admin/',
        '/static/',
        '/media/',
        '/accounts/logout/',
        '/users/logout/',
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # 認証済みユーザーのみチェック
        if request.user.is_authenticated:
            # 除外パスはスキップ
            path = request.path
            if not any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS):
                # BANされているかチェック
                if getattr(request.user, 'is_banned', False):
                    logger.warning(
                        f'BANユーザーがアクセス: user={request.user.username}, '
                        f'path={path}'
                    )
                    logout(request)
                    messages.error(
                        request,
                        'アカウントが停止されています。利用規約違反が確認されたため、'
                        'このアカウントは使用できません。'
                        ' / Your account has been suspended due to a violation of '
                        'our Terms of Service.'
                    )
                    return redirect('users:login')
        
        response = self.get_response(request)
        return response
