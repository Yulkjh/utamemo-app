from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'users'

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('favorites/', views.FavoritesView.as_view(), name='favorites'),
    path('profile/edit/', views.ProfileEditView.as_view(), name='profile_edit'),
    path('profile/update-image/', views.update_profile_image, name='update_profile_image'),
    path('profile/delete-image/', views.delete_profile_image, name='delete_profile_image'),
    path('upgrade/', views.UpgradeView.as_view(), name='upgrade'),
    path('upgrade/checkout/', views.create_checkout_session, name='create_checkout'),
    path('upgrade/success/', views.upgrade_success, name='upgrade_success'),
    path('webhook/stripe/', views.stripe_webhook, name='stripe_webhook'),
    path('school-inquiry/', views.SchoolInquiryView.as_view(), name='school_inquiry'),
    path('school-inquiry/complete/', views.SchoolInquiryCompleteView.as_view(), name='school_inquiry_complete'),
    
    # パスワードリセット
    path('password-reset/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset/complete/', views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
    
    path('profile/<str:username>/', views.ProfileView.as_view(), name='profile'),
]