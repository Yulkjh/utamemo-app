"""
管理画面 二段階認証（2FA）ビュー
"""

import logging
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from .security import (
    verify_2fa_code, mark_admin_2fa_verified, is_admin_2fa_verified,
    send_2fa_code, ADMIN_2FA_PENDING_KEY,
)

logger = logging.getLogger(__name__)


@login_required
@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_2fa_verify(request):
    """管理画面 二段階認証コード確認ビュー"""
    
    # 既に認証済みなら管理画面へ
    if is_admin_2fa_verified(request):
        return redirect('/admin/')
    
    error = None
    
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        action = request.POST.get('action', '')
        
        if action == 'resend':
            # コード再送信
            if request.user.email:
                send_2fa_code(request.user)
                request.session[ADMIN_2FA_PENDING_KEY] = True
                logger.info(f'Admin 2FA code resent: user={request.user.username}')
            return render(request, 'admin/admin_2fa_verify.html', {
                'resent': True,
                'email': _mask_email(request.user.email),
            })
        
        if code and verify_2fa_code(request.user.pk, code):
            mark_admin_2fa_verified(request)
            logger.info(f'Admin 2FA verified: user={request.user.username}')
            return redirect('/admin/')
        else:
            error = '認証コードが正しくないか、有効期限が切れています。'
            logger.warning(f'Admin 2FA failed: user={request.user.username}')
    
    return render(request, 'admin/admin_2fa_verify.html', {
        'error': error,
        'email': _mask_email(request.user.email),
    })


def _mask_email(email):
    """メールアドレスをマスク表示（例: h***4@gmail.com）"""
    if not email or '@' not in email:
        return '(未設定)'
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked = local[0] + '***'
    else:
        masked = local[0] + '***' + local[-1]
    return f'{masked}@{domain}'
