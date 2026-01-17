from django.urls import path
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
    path('profile/<str:username>/', views.ProfileView.as_view(), name='profile'),
]