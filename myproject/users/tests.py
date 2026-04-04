from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

User = get_user_model()


class UserModelTest(TestCase):
    """Userモデルの基本テスト"""
    
    def test_default_plan_is_free(self):
        """新規ユーザーのデフォルトプランがfreeであること"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        self.assertEqual(user.plan, 'free')
    
    def test_free_user_is_not_pro(self):
        """無料ユーザーがPro判定されないこと"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        self.assertFalse(user.is_pro)
    
    def test_starter_user_is_pro(self):
        """Starterプランユーザーが有効期限内ならPro判定されること"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        user.plan = 'starter'
        user.plan_expires_at = timezone.now() + timedelta(days=30)
        user.save()
        self.assertTrue(user.is_pro)
    
    def test_expired_starter_is_not_pro(self):
        """期限切れStarterプランユーザーがPro判定されないこと"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        user.plan = 'starter'
        user.plan_expires_at = timezone.now() - timedelta(days=1)
        user.save()
        self.assertFalse(user.is_pro)
    
    def test_staff_user_is_always_pro(self):
        """スタッフユーザーが常にPro判定されること"""
        user = User.objects.create_user(username='staffuser', password='testpass123', is_staff=True)
        self.assertTrue(user.is_pro)
    
    def test_superuser_is_always_pro(self):
        """スーパーユーザーが常にPro判定されること"""
        user = User.objects.create_superuser(username='admin', password='testpass123')
        self.assertTrue(user.is_pro)


class UserPlanLimitsTest(TestCase):
    """プラン別制限のテスト"""
    
    def test_free_monthly_limit(self):
        """無料プランに月間制限があること"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        limit = user.get_monthly_song_limit()
        self.assertGreater(limit, 0)
    
    def test_pro_unlimited(self):
        """Proプランに月間制限がないこと"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        user.plan = 'pro'
        user.plan_expires_at = timezone.now() + timedelta(days=30)
        user.save()
        limit = user.get_monthly_song_limit()
        self.assertEqual(limit, -1)
    
    def test_starter_limit(self):
        """Starterプランに月間制限があること"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        user.plan = 'starter'
        user.plan_expires_at = timezone.now() + timedelta(days=30)
        user.save()
        limit = user.get_monthly_song_limit()
        self.assertGreater(limit, 0)
    
    def test_staff_unlimited(self):
        """スタッフユーザーに制限がないこと"""
        user = User.objects.create_user(username='staffuser', password='testpass123', is_staff=True)
        limit = user.get_monthly_song_limit()
        self.assertEqual(limit, -1)
    
    def test_free_model_limits(self):
        """無料プランのモデル制限を取得できること"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        limits = user.get_model_limits()
        self.assertIsInstance(limits, dict)
        self.assertIn('v8', limits)
    
    def test_free_user_can_use_v8(self):
        """無料ユーザーがv8モデルを使用できること"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        self.assertTrue(user.can_use_model('v8'))
    
    def test_remaining_usage_no_songs(self):
        """曲未生成ユーザーの残り使用回数が正しいこと"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        remaining = user.get_remaining_model_usage()
        limits = user.get_model_limits()
        self.assertEqual(remaining['v8'], limits['v8'])


class BannedUserTest(TestCase):
    """BAN機能のテスト"""
    
    def test_user_default_not_banned(self):
        """新規ユーザーがデフォルトでBANされていないこと"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        self.assertFalse(user.is_banned)
    
    def test_ban_user(self):
        """ユーザーをBANできること"""
        user = User.objects.create_user(username='testuser', password='testpass123')
        user.is_banned = True
        user.save()
        user.refresh_from_db()
        self.assertTrue(user.is_banned)


class UserRegistrationTest(TestCase):
    """ユーザー登録・ログインのテスト"""
    
    def setUp(self):
        self.client = Client()
    
    def test_register_page_loads(self):
        """登録ページが読み込めること"""
        response = self.client.get(reverse('users:register'))
        self.assertEqual(response.status_code, 200)
    
    def test_register_creates_user(self):
        """ユーザー登録が成功すること"""
        response = self.client.post(reverse('users:register'), {
            'username': 'newuser',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
            'email': 'test@example.com',
            'birth_date': '2000-01-15',
            'agree_tos': True,
        })
        self.assertTrue(User.objects.filter(username='newuser').exists())
    
    def test_login_page_loads(self):
        """ログインページが読み込めること"""
        response = self.client.get(reverse('users:login'))
        self.assertEqual(response.status_code, 200)
    
    def test_login_success(self):
        """正しい認証情報でログインできること"""
        User.objects.create_user(username='testuser', password='testpass123')
        response = self.client.post(reverse('users:login'), {
            'username': 'testuser',
            'password': 'testpass123',
        })
        self.assertEqual(response.status_code, 302)
    
    def test_login_failure(self):
        """誤った認証情報でログインできないこと"""
        User.objects.create_user(username='testuser', password='testpass123')
        response = self.client.post(reverse('users:login'), {
            'username': 'testuser',
            'password': 'wrongpassword',
        })
        self.assertEqual(response.status_code, 200)
