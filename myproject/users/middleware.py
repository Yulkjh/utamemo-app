"""
ユーザーBAN（アカウント停止）ミドルウェア

BANされたユーザーがアクセスした場合、強制ログアウトしてBAN通知ページへリダイレクトする。
"""

from django.shortcuts import redirect
from django.contrib.auth import logout
from django.contrib import messages
from django.urls import reverse
import logging

logger = logging.getLogger(__name__)


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
