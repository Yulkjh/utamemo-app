from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import User
from songs.content_filter import check_username_for_inappropriate_content


def _validate_username_content(username):
    """ユーザー名の不適切コンテンツをチェックする共通バリデーション"""
    result = check_username_for_inappropriate_content(username)
    if result['is_inappropriate']:
        raise ValidationError(
            'このユーザー名は使用できません。別のユーザー名を選んでください。'
            ' / This username is not allowed. Please choose a different one.'
        )


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
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username:
            _validate_username_content(username)
        return username


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