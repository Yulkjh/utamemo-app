from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import CreateView, TemplateView, ListView, UpdateView, FormView
from django.contrib.auth.views import LoginView as AuthLoginView, LogoutView as AuthLogoutView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail
from datetime import timedelta
from .forms import UserRegistrationForm, ProfileEditForm
from .models import User
from songs.models import Song, Favorite, Like, Classroom
import json
import base64
from io import BytesIO
from PIL import Image


class RegisterView(CreateView):
    """ユーザー登録ビュー"""
    form_class = UserRegistrationForm
    template_name = 'users/register.html'
    success_url = reverse_lazy('users:login')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        app_language = self.request.session.get('app_language', 'ja')
        if app_language == 'en':
            messages.success(self.request, 'Account created! Please log in.')
        elif app_language == 'zh':
            messages.success(self.request, '账户已创建！请登录。')
        else:
            messages.success(self.request, 'アカウントが作成されました！ログインしてください。')
        return response


class LoginView(AuthLoginView):
    """ログインビュー"""
    template_name = 'users/login.html'
    redirect_authenticated_user = True
    
    def get_success_url(self):
        app_language = self.request.session.get('app_language', 'ja')
        if app_language == 'en':
            messages.success(self.request, 'Logged in successfully!')
        elif app_language == 'zh':
            messages.success(self.request, '登录成功！')
        else:
            messages.success(self.request, 'ログインしました！')
        return reverse_lazy('songs:home')


class LogoutView(AuthLogoutView):
    """ログアウトビュー"""
    next_page = reverse_lazy('songs:home')
    
    def dispatch(self, request, *args, **kwargs):
        app_language = request.session.get('app_language', 'ja')
        if app_language == 'en':
            messages.info(request, 'Logged out.')
        elif app_language == 'zh':
            messages.info(request, '已退出登录。')
        else:
            messages.info(request, 'ログアウトしました。')
        return super().dispatch(request, *args, **kwargs)


from django.db.models import Sum

class ProfileView(TemplateView):
    """プロフィールビュー"""
    template_name = 'users/profile.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        username = kwargs.get('username')
        user = get_object_or_404(User, username=username)
        
        context['profile_user'] = user
        
        # 自分のプロフィールの場合は全ての楽曲を表示、他人の場合は公開楽曲のみ
        if self.request.user.is_authenticated and self.request.user == user:
            # 自分のプロフィール: 全ての生成完了した楽曲
            context['user_songs'] = Song.objects.filter(
                created_by=user,
                generation_status='completed'
            ).order_by('-created_at')
        else:
            # 他人のプロフィール: 公開楽曲のみ
            context['user_songs'] = Song.objects.filter(
                created_by=user, 
                is_public=True,
                generation_status='completed'
            ).order_by('-created_at')
        
        # 総いいね数を計算（全ての楽曲のlikes_countを合計）
        total_likes = Song.objects.filter(
            created_by=user,
            generation_status='completed'
        ).aggregate(total=Sum('likes_count'))['total'] or 0
        context['total_likes'] = total_likes
        
        # ログイン中のユーザーがいいねしている楽曲のIDリストを取得
        if self.request.user.is_authenticated:
            user_liked_songs = set(Like.objects.filter(
                user=self.request.user,
                song__in=context['user_songs']
            ).values_list('song_id', flat=True))
            context['user_liked_songs'] = user_liked_songs
        else:
            context['user_liked_songs'] = set()
        
        # 自分のプロフィールの場合、参加中のクラスを表示
        if self.request.user.is_authenticated and self.request.user == user:
            # ホストしているクラス
            context['hosted_classrooms'] = Classroom.objects.filter(host=user, is_active=True)
            # 参加しているクラス（ホストを除く）
            context['joined_classrooms'] = user.joined_classrooms.filter(is_active=True).exclude(host=user)
        
        return context


class FavoritesView(LoginRequiredMixin, ListView):
    """お気に入り一覧ビュー"""
    template_name = 'users/favorites.html'
    context_object_name = 'favorites'
    paginate_by = 12
    
    def get_queryset(self):
        # 生成完了した楽曲のお気に入りのみ表示
        return Favorite.objects.filter(
            user=self.request.user,
            song__generation_status='completed'
        ).select_related('song', 'song__created_by').order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # ユーザーがいいねした楽曲のIDセットを追加
        if self.request.user.is_authenticated:
            from songs.models import Like
            context['user_liked_songs'] = set(
                Like.objects.filter(user=self.request.user).values_list('song_id', flat=True)
            )
        else:
            context['user_liked_songs'] = set()
        return context


class ProfileEditView(LoginRequiredMixin, UpdateView):
    """プロフィール編集ビュー"""
    model = User
    form_class = ProfileEditForm
    template_name = 'users/profile_edit.html'
    
    def get_object(self):
        return self.request.user
    
    def form_valid(self, form):
        user = form.save(commit=False)
        
        # 画像がアップロードされた場合、Base64に変換して保存
        if 'profile_image' in self.request.FILES:
            image_file = self.request.FILES['profile_image']
            
            # PILで画像を開いてリサイズ（最大300x300）
            img = Image.open(image_file)
            img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            
            # RGBAの場合はRGBに変換
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Base64にエンコード
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            image_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            # data URI形式で保存
            user.profile_image_data = f"data:image/jpeg;base64,{image_data}"
        
        user.save()
        
        app_language = self.request.session.get('app_language', 'ja')
        if app_language == 'en':
            messages.success(self.request, 'Profile updated!')
        elif app_language == 'zh':
            messages.success(self.request, '个人资料已更新！')
        else:
            messages.success(self.request, 'プロフィールを更新しました！')
        
        return redirect(self.get_success_url())
    
    def get_success_url(self):
        return reverse_lazy('users:profile', kwargs={'username': self.request.user.username})


@login_required
@require_POST
def update_profile_image(request):
    """プロフィール画像をAJAXでアップロード"""
    if 'profile_image' in request.FILES:
        user = request.user
        # 古い画像があれば削除
        if user.profile_image:
            user.profile_image.delete(save=False)
        user.profile_image = request.FILES['profile_image']
        user.save()
        return JsonResponse({
            'success': True,
            'image_url': user.profile_image.url
        })
    return JsonResponse({'success': False, 'error': '画像がありません'}, status=400)


@login_required
@require_POST
def delete_profile_image(request):
    """プロフィール画像を削除"""
    user = request.user
    if user.profile_image_data or user.profile_image:
        user.profile_image_data = None
        if user.profile_image:
            user.profile_image.delete(save=False)
        user.save()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': '画像がありません'}, status=400)


class UpgradeView(TemplateView):
    """プランアップグレードビュー（ログインなしでも閲覧可能）"""
    template_name = 'users/upgrade.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            context['current_plan'] = self.request.user.plan
            context['is_pro'] = self.request.user.is_pro
        else:
            context['current_plan'] = None
            context['is_pro'] = False
        context['stripe_publishable_key'] = getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '')
        context['stripe_price_ids'] = getattr(settings, 'STRIPE_PRICE_IDS', {})
        return context


# テストモード: Trueの間は無料で即アップグレード、Falseで本番Stripe決済
FREE_UPGRADE_MODE = False


@login_required
@require_POST
def create_checkout_session(request):
    """Stripeチェックアウトセッションを作成"""
    try:
        import json
        data = json.loads(request.body)
        plan = data.get('plan', 'starter')  # デフォルトはスターター
        
        user = request.user
        domain = request.build_absolute_uri('/')[:-1]
        
        # 有効なプランか確認
        valid_plans = ['starter', 'pro', 'school']
        if plan not in valid_plans:
            return JsonResponse({'error': 'Invalid plan'}, status=400)
        
        # テストモード: 無料で即アップグレード
        if FREE_UPGRADE_MODE:
            user.plan = plan
            user.plan_expires_at = timezone.now() + timedelta(days=30)
            user.save()
            return JsonResponse({'checkout_url': f'{domain}/users/upgrade/success/?free_upgrade=1&plan={plan}'})
        
        # 本番モード: Stripe決済
        import stripe
        stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        
        if not stripe.api_key:
            return JsonResponse({'error': 'Stripe is not configured'}, status=500)
        
        # プランに対応する価格IDを取得
        price_ids = getattr(settings, 'STRIPE_PRICE_IDS', {})
        price_id = price_ids.get(plan, '')
        
        if not price_id:
            return JsonResponse({'error': f'Price not configured for {plan} plan'}, status=500)
        
        if not user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=user.email if user.email else None,
                metadata={'user_id': user.id, 'username': user.username}
            )
            user.stripe_customer_id = customer.id
            user.save()
        
        checkout_session = stripe.checkout.Session.create(
            customer=user.stripe_customer_id,
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription',
            success_url=f'{domain}/users/upgrade/success/?session_id={{CHECKOUT_SESSION_ID}}&plan={plan}',
            cancel_url=f'{domain}/users/upgrade/',
            metadata={'user_id': user.id, 'plan': plan}
        )
        
        return JsonResponse({'checkout_url': checkout_session.url})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def upgrade_success(request):
    """アップグレード成功後のコールバック"""
    free_upgrade = request.GET.get('free_upgrade')
    session_id = request.GET.get('session_id')
    plan = request.GET.get('plan', 'starter')
    
    app_language = request.session.get('app_language', 'ja')
    
    plan_names = {
        'starter': {'ja': 'スターター', 'en': 'Starter', 'zh': '入门'},
        'pro': {'ja': 'プロ', 'en': 'Pro', 'zh': '专业'},
        'school': {'ja': 'スクール', 'en': 'School', 'zh': '学校'},
    }
    plan_name = plan_names.get(plan, plan_names['starter']).get(app_language, plan)
    
    if free_upgrade:
        # テストモード: 無料アップグレード済み
        if app_language == 'en':
            messages.success(request, f'Welcome to {plan_name}! Your plan has been activated.')
        elif app_language == 'zh':
            messages.success(request, f'欢迎加入{plan_name}！您的计划已激活。')
        else:
            messages.success(request, f'{plan_name}プランへようこそ！プランが有効になりました。')
    
    elif session_id:
        # 本番モード: Stripe決済後
        try:
            import stripe
            stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
            session = stripe.checkout.Session.retrieve(session_id)
            
            if session.payment_status == 'paid':
                user = request.user
                # メタデータからプランを取得（フォールバックはURLパラメータ）
                actual_plan = session.metadata.get('plan', plan)
                user.plan = actual_plan
                user.stripe_subscription_id = session.subscription
                user.plan_expires_at = timezone.now() + timedelta(days=30)
                user.save()
                
                plan_name = plan_names.get(actual_plan, plan_names['starter']).get(app_language, actual_plan)
                
                if app_language == 'en':
                    messages.success(request, f'Welcome to {plan_name}! Your plan has been activated.')
                elif app_language == 'zh':
                    messages.success(request, f'欢迎加入{plan_name}！您的计划已激活。')
                else:
                    messages.success(request, f'{plan_name}プランへようこそ！プランが有効になりました。')
        except Exception as e:
            print(f"Error processing payment success: {e}")
    
    return redirect('users:upgrade')


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Stripeウェブフックを処理"""
    import stripe
    stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
    
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session.get('metadata', {}).get('user_id')
        plan = session.get('metadata', {}).get('plan', 'starter')  # メタデータからプランを取得
        if user_id:
            try:
                user = User.objects.get(id=user_id)
                user.plan = plan  # 正しいプランを設定
                user.stripe_subscription_id = session.get('subscription')
                user.plan_expires_at = timezone.now() + timedelta(days=30)
                user.save()
            except User.DoesNotExist:
                pass
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        try:
            user = User.objects.get(stripe_subscription_id=subscription['id'])
            user.plan = 'free'
            user.stripe_subscription_id = None
            user.plan_expires_at = None
            user.save()
        except User.DoesNotExist:
            pass
    
    elif event['type'] == 'invoice.paid':
        invoice = event['data']['object']
        subscription_id = invoice.get('subscription')
        if subscription_id:
            try:
                user = User.objects.get(stripe_subscription_id=subscription_id)
                user.plan_expires_at = timezone.now() + timedelta(days=30)
                user.save()
            except User.DoesNotExist:
                pass
    
    return HttpResponse(status=200)


class SchoolInquiryView(TemplateView):
    """教育機関向けプランお問い合わせビュー"""
    template_name = 'users/school_inquiry.html'
    
    def post(self, request, *args, **kwargs):
        """フォーム送信処理"""
        organization_name = request.POST.get('organization_name', '')
        contact_name = request.POST.get('contact_name', '')
        email = request.POST.get('email', '')
        phone = request.POST.get('phone', '')
        student_count = request.POST.get('student_count', '')
        start_date = request.POST.get('start_date', '')
        message = request.POST.get('message', '')
        
        # メール本文を作成
        email_body = f"""
【UTAMEMOスクールプランお問い合わせ】

■ 学校・教育機関名
{organization_name}

■ ご担当者名
{contact_name}

■ メールアドレス
{email}

■ 電話番号
{phone}

■ 導入予定人数
{student_count}

■ 導入希望時期
{start_date}

■ お問い合わせ内容
{message}

---
このメールはUTAMEMOお問い合わせフォームから自動送信されています。
"""
        
        # 管理者にメール送信
        try:
            admin_email = 'hope47284@gmail.com'
            send_mail(
                subject=f'【UTAMEMOスクールプラン】{organization_name}様からのお問い合わせ',
                message=email_body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@utamemo.com'),
                recipient_list=[admin_email],
                fail_silently=True,
            )
        except Exception as e:
            # メール送信失敗してもエラーにはしない（ログに記録）
            print(f"Email send error: {e}")
        
        messages.success(request, 'お問い合わせを送信しました。担当者より折り返しご連絡いたします。')
        return redirect('users:school_inquiry_complete')


class SchoolInquiryCompleteView(TemplateView):
    """お問い合わせ完了ビュー"""
    template_name = 'users/school_inquiry_complete.html'


# ========================================
# パスワードリセット関連ビュー
# ========================================
from django.contrib.auth.views import (
    PasswordResetView, 
    PasswordResetDoneView, 
    PasswordResetConfirmView, 
    PasswordResetCompleteView
)


class CustomPasswordResetView(PasswordResetView):
    """パスワードリセット要求ビュー"""
    template_name = 'users/password_reset.html'
    email_template_name = 'users/password_reset_email.html'
    subject_template_name = 'users/password_reset_subject.txt'
    success_url = reverse_lazy('users:password_reset_done')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class CustomPasswordResetDoneView(PasswordResetDoneView):
    """パスワードリセットメール送信完了ビュー"""
    template_name = 'users/password_reset_done.html'


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    """パスワードリセット確認ビュー"""
    template_name = 'users/password_reset_confirm.html'
    success_url = reverse_lazy('users:password_reset_complete')


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    """パスワードリセット完了ビュー"""
    template_name = 'users/password_reset_complete.html'

