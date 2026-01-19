from django.shortcuts import render
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings


def terms(request):
    """利用規約ページ"""
    return render(request, 'legal/terms.html')


def privacy(request):
    """プライバシーポリシーページ"""
    return render(request, 'legal/privacy.html')


def contact(request):
    """お問い合わせページ"""
    if request.method == 'POST':
        name = request.POST.get('name', '')
        email = request.POST.get('email', '')
        subject = request.POST.get('subject', '')
        message = request.POST.get('message', '')
        
        # 件名の日本語変換
        subject_labels = {
            'general': '一般的なお問い合わせ',
            'bug': 'バグ報告',
            'feature': '機能リクエスト',
            'account': 'アカウントに関する問題',
            'billing': 'お支払いに関するご質問',
            'other': 'その他',
        }
        subject_text = subject_labels.get(subject, subject)
        
        # TODO: メール送信を実装する場合はここで send_mail を使用
        # 現在はメッセージを表示するだけ
        
        app_language = request.session.get('app_language', 'ja')
        if app_language == 'en':
            messages.success(request, 'Thank you for your message. We will get back to you soon.')
        else:
            messages.success(request, 'お問い合わせありがとうございます。内容を確認の上、ご連絡いたします。')
    
    return render(request, 'legal/contact.html')
