"""
セキュリティ対策モジュール

1. ログイン試行回数制限（アカウントロック）
2. 管理画面アクセス制限
3. 不審IPアドレスのレート制限
"""

import logging
import hashlib
from datetime import timedelta
from django.core.cache import cache
from django.http import HttpResponseForbidden, HttpResponse
from django.shortcuts import redirect
from django.contrib import messages as django_messages
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

# ========================================
# ログイン試行回数制限
# ========================================
MAX_LOGIN_ATTEMPTS = 10  # 最大試行回数
LOCKOUT_DURATION = 30 * 60  # ロックアウト時間（秒）= 30分
LOGIN_ATTEMPT_TIMEOUT = 60 * 60  # 試行回数リセット時間（秒）= 1時間


def get_client_ip(request):
    """リクエストからクライアントIPを取得"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '0.0.0.0')
    return ip


def get_login_attempt_cache_key(identifier):
    """ログイン試行回数のキャッシュキーを生成"""
    # ユーザー名またはIPベースのキー
    hashed = hashlib.md5(identifier.encode()).hexdigest()
    return f'login_attempts_{hashed}'


def get_lockout_cache_key(identifier):
    """ロックアウトのキャッシュキーを生成"""
    hashed = hashlib.md5(identifier.encode()).hexdigest()
    return f'login_lockout_{hashed}'


def is_locked_out(identifier):
    """指定されたidentifier（ユーザー名またはIP）がロックアウト中か確認"""
    lockout_key = get_lockout_cache_key(identifier)
    return cache.get(lockout_key) is not None


def get_login_attempts(identifier):
    """現在の試行回数を取得"""
    attempt_key = get_login_attempt_cache_key(identifier)
    return cache.get(attempt_key, 0)


def record_failed_login(username, ip_address):
    """ログイン失敗を記録"""
    for identifier in [username, ip_address]:
        attempt_key = get_login_attempt_cache_key(identifier)
        attempts = cache.get(attempt_key, 0) + 1
        cache.set(attempt_key, attempts, LOGIN_ATTEMPT_TIMEOUT)
        
        if attempts >= MAX_LOGIN_ATTEMPTS:
            lockout_key = get_lockout_cache_key(identifier)
            cache.set(lockout_key, True, LOCKOUT_DURATION)
            logger.warning(
                f'アカウントロック: identifier={identifier}, '
                f'attempts={attempts}, lockout={LOCKOUT_DURATION}s'
            )


def clear_login_attempts(username, ip_address):
    """ログイン成功時に試行回数をクリア"""
    for identifier in [username, ip_address]:
        attempt_key = get_login_attempt_cache_key(identifier)
        lockout_key = get_lockout_cache_key(identifier)
        cache.delete(attempt_key)
        cache.delete(lockout_key)


# ========================================
# レート制限ミドルウェア
# ========================================
# 同一IPからの短時間の大量リクエストを制限
RATE_LIMIT_REQUESTS = 100  # 最大リクエスト数
RATE_LIMIT_WINDOW = 60  # ウィンドウ（秒）


def get_rate_limit_cache_key(ip_address, path_prefix):
    """レート制限のキャッシュキーを生成"""
    hashed = hashlib.md5(f'{ip_address}:{path_prefix}'.encode()).hexdigest()
    return f'rate_limit_{hashed}'


class SecurityMiddleware:
    """
    セキュリティミドルウェア
    - ログインエンドポイントへのレート制限
    - 管理画面へのアクセス制限
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # 管理画面アクセス許可IPリスト（環境変数から取得）
        allowed_ips_str = getattr(settings, 'ADMIN_ALLOWED_IPS', '')
        if isinstance(allowed_ips_str, str) and allowed_ips_str:
            self.admin_allowed_ips = [ip.strip() for ip in allowed_ips_str.split(',') if ip.strip()]
        elif isinstance(allowed_ips_str, list):
            self.admin_allowed_ips = allowed_ips_str
        else:
            self.admin_allowed_ips = []
    
    def __call__(self, request):
        ip_address = get_client_ip(request)
        path = request.path
        
        # ========================================
        # 管理画面アクセス制限
        # ========================================
        if path.startswith('/admin/'):
            # 本番環境で管理画面へのアクセスを制限
            if getattr(settings, 'PRODUCTION', False):
                # ADMIN_ALLOWED_IPSが設定されている場合、IP制限を適用
                if self.admin_allowed_ips and ip_address not in self.admin_allowed_ips:
                    logger.warning(f'管理画面アクセス拒否: IP={ip_address}')
                    return self._styled_error_response(403, 'アクセスが拒否されました', 'このページへのアクセスは許可されていません。')
            
            # 管理画面ログインへのレート制限（POST時のみ）
            if request.method == 'POST' and 'login' in path:
                if self._is_rate_limited(ip_address, '/admin/login/'):
                    logger.warning(f'管理画面ログイン レート制限: IP={ip_address}')
                    return self._styled_error_response(429, 'リクエスト制限', 'リクエストが多すぎます。しばらくしてからお試しください。')
        
        # ========================================
        # ユーザーログインへのレート制限
        # ========================================
        if path == '/users/login/' and request.method == 'POST':
            # IPベースのロックアウトチェック
            if is_locked_out(ip_address):
                logger.warning(f'ロックアウト中のアクセス: IP={ip_address}')
                django_messages.error(request, 'ログイン試行回数の上限に達しました。30分後にもう一度お試しください。')
                return redirect('/users/login/')
            
            # レート制限チェック
            if self._is_rate_limited(ip_address, '/users/login/'):
                django_messages.error(request, 'リクエストが多すぎます。しばらくしてからお試しください。')
                return redirect('/users/login/')
        
        response = self.get_response(request)
        return response
    
    def _is_rate_limited(self, ip_address, path_prefix):
        """レート制限チェック"""
        cache_key = get_rate_limit_cache_key(ip_address, path_prefix)
        requests_count = cache.get(cache_key, 0)
        
        if requests_count >= RATE_LIMIT_REQUESTS:
            return True
        
        cache.set(cache_key, requests_count + 1, RATE_LIMIT_WINDOW)
        return False
    
    def _styled_error_response(self, status_code, title, message):
        """UTAMEMOのデザインに合わせたエラーページを返す"""
        html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{status_code} - UTAMEMO</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0a0a1a 0%, #1a1a3e 50%, #0a0a1a 100%);
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .error-container {{
            text-align: center;
            padding: 3rem 2rem;
            max-width: 500px;
        }}
        .error-code {{
            font-size: 5rem;
            font-weight: 800;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            line-height: 1;
            margin-bottom: 1rem;
        }}
        .error-title {{
            font-size: 1.5rem;
            color: #fff;
            margin-bottom: 1rem;
        }}
        .error-message {{
            color: #a0a0b0;
            margin-bottom: 2rem;
            line-height: 1.6;
        }}
        .back-link {{
            display: inline-block;
            padding: 0.75rem 2rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
            text-decoration: none;
            border-radius: 12px;
            font-weight: 600;
            transition: opacity 0.2s;
        }}
        .back-link:hover {{ opacity: 0.8; }}
    </style>
</head>
<body>
    <div class="error-container">
        <div class="error-code">{status_code}</div>
        <h1 class="error-title">{title}</h1>
        <p class="error-message">{message}</p>
        <a href="/" class="back-link">トップページへ戻る</a>
    </div>
</body>
</html>'''
        return HttpResponse(html, status=status_code)
