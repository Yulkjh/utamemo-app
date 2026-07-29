import logging

from django.shortcuts import render
from django.contrib import messages
from django.core.mail import EmailMessage
from django.conf import settings

logger = logging.getLogger(__name__)


def terms(request):
    """利用規約ページ"""
    return render(request, 'legal/terms.html')


def privacy(request):
    """プライバシーポリシーページ"""
    return render(request, 'legal/privacy.html')


def tokushoho(request):
    """特定商取引法に基づく表記ページ"""
    return render(request, 'legal/tokushoho.html')


def contact(request):
    """お問い合わせページ"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()
        app_language = request.session.get('app_language', 'ja')

        if not (name and email and subject and message):
            if app_language == 'en':
                messages.error(request, 'Please fill in all fields.')
            else:
                messages.error(request, 'すべての項目を入力してください。')
            return render(request, 'legal/contact.html')

        # 件名の日本語変換
        subject_labels = {
            'general': '一般的なお問い合わせ',
            'bug': 'バグ報告',
            'feature': '機能リクエスト',
            'copyright': '著作権侵害の報告',
            'account': 'アカウントに関する問題',
            'billing': 'お支払いに関するご質問',
            'other': 'その他',
        }
        subject_text = subject_labels.get(subject, subject)

        admin_email = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', 'hope47284@gmail.com')
        mail_subject = f'【UTAMEMO お問い合わせ】{subject_text}'
        mail_body = (
            f'お名前: {name}\n'
            f'メールアドレス: {email}\n'
            f'件名: {subject_text}\n'
            f'\n'
            f'{message}\n'
        )

        try:
            EmailMessage(
                subject=mail_subject,
                body=mail_body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@utamemo.com'),
                to=[admin_email],
                reply_to=[email] if email else None,
            ).send(fail_silently=False)
        except Exception:
            logger.exception('Failed to send contact form email (subject=%s)', subject)
            if app_language == 'en':
                messages.error(
                    request,
                    'Sorry, something went wrong while sending your message. '
                    'Please email us directly at hope47284@gmail.com instead.'
                )
            else:
                messages.error(
                    request,
                    'メッセージの送信中にエラーが発生しました。お手数ですが hope47284@gmail.com へ直接メールでご連絡ください。'
                )
        else:
            if app_language == 'en':
                messages.success(request, 'Thank you for your message. We will get back to you soon.')
            else:
                messages.success(request, 'お問い合わせありがとうございます。内容を確認の上、ご連絡いたします。')

    return render(request, 'legal/contact.html')
