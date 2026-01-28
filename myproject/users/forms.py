from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User


class UserRegistrationForm(UserCreationForm):
    """ユーザー登録フォーム（メールアドレス必須）"""
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'placeholder': 'example@email.com'
        })
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={
                'placeholder': 'ユーザー名'
            })
        }
        help_texts = {
            'username': '半角英数字、アンダースコア、ハイフンが使用できます（150文字以内）'
        }


class ProfileEditForm(forms.ModelForm):
    """プロフィール編集フォーム"""
    
    class Meta:
        model = User
        fields = ('profile_image', 'bio')
        widgets = {
            'profile_image': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'profile-image-input',
            }),
            'bio': forms.Textarea(attrs={
                'placeholder': '自己紹介を入力...',
                'rows': 4,
                'maxlength': 500,
            })
        }
        labels = {
            'profile_image': 'プロフィール画像',
            'bio': '自己紹介',
        }