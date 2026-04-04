from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import User
from songs.content_filter import check_username_for_inappropriate_content
import re


def _validate_username_content(username):
    """ユーザー名の不適切コンテンツをチェックする共通バリデーション"""
    result = check_username_for_inappropriate_content(username)
    if result['is_inappropriate']:
        raise ValidationError(
            'このユーザー名は使用できません。別のユーザー名を選んでください。'
            ' / This username is not allowed. Please choose a different one.'
        )


def _validate_username_not_email(username):
    """ユーザー名にメールアドレスが使われていないかチェック（@xxx.xxx形式）"""
    if re.search(r'@.+\..+', username):
        raise ValidationError(
            'メールアドレスはユーザー名に使用できません。下のメールアドレス欄に入力してください。'
            ' / Email addresses cannot be used as a username. Please enter it in the email field below.'
        )


class UserRegistrationForm(UserCreationForm):
    """ユーザー登録フォーム（メールアドレス必須）"""
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'placeholder': 'example@email.com'
        })
    )
    
    birth_date = forms.DateField(
        required=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'YYYY-MM-DD',
            'pattern': r'\d{4}-\d{2}-\d{2}',
            'inputmode': 'numeric',
            'autocomplete': 'bday',
            'maxlength': '10',
        }),
        input_formats=['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y'],
        error_messages={
            'required': '生年月日を入力してください。 / Please enter your date of birth.',
            'invalid': '正しい日付を入力してください（例: 2000-01-15）。 / Please enter a valid date (e.g. 2000-01-15).',
        },
    )
    
    agree_tos = forms.BooleanField(
        required=True,
        error_messages={
            'required': '利用規約とプライバシーポリシーへの同意が必要です。'
                        ' / You must agree to the Terms of Service and Privacy Policy.',
        },
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'birth_date', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={
                'placeholder': 'ユーザー名'
            })
        }
        help_texts = {
            'username': '半角英数字、アンダースコア、ハイフンが使用できます（150文字以内）'
        }
    
    def clean_birth_date(self):
        from datetime import date
        birth_date = self.cleaned_data.get('birth_date')
        if birth_date:
            today = date.today()
            # 未来の日付チェック
            if birth_date > today:
                raise ValidationError(
                    '未来の日付は入力できません。 / Date cannot be in the future.'
                )
            # 不合理な過去の日付チェック（120歳以上）
            age = today.year - birth_date.year - (
                (today.month, today.day) < (birth_date.month, birth_date.day)
            )
            if age > 120:
                raise ValidationError(
                    '正しい生年月日を入力してください。 / Please enter a valid date of birth.'
                )
        return birth_date
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username:
            _validate_username_not_email(username)
            _validate_username_content(username)
        return username


class AccountDeleteForm(forms.Form):
    """アカウント削除確認フォーム"""
    
    confirm_username = forms.CharField(
        required=True,
        error_messages={
            'required': 'ユーザー名を入力してください。 / Please enter your username.',
        },
    )
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
    
    def clean_confirm_username(self):
        confirm_username = self.cleaned_data.get('confirm_username')
        if self.user and confirm_username != self.user.username:
            raise ValidationError(
                'ユーザー名が一致しません。 / Username does not match.'
            )
        return confirm_username


class ProfileEditForm(forms.ModelForm):
    """プロフィール編集フォーム"""
    
    birth_date = forms.DateField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'YYYY-MM-DD',
            'class': 'form-control',
            'pattern': r'\d{4}-\d{2}-\d{2}',
            'inputmode': 'numeric',
            'autocomplete': 'bday',
            'maxlength': '10',
        }),
        input_formats=['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y'],
        label='生年月日 / Date of Birth',
    )
    
    class Meta:
        model = User
        fields = ('profile_image', 'bio', 'birth_date')
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
    
    def clean_birth_date(self):
        from datetime import date
        birth_date = self.cleaned_data.get('birth_date')
        if birth_date:
            today = date.today()
            if birth_date > today:
                raise ValidationError(
                    '未来の日付は入力できません。 / Date cannot be in the future.'
                )
            age = today.year - birth_date.year - (
                (today.month, today.day) < (birth_date.month, birth_date.day)
            )
            if age > 120:
                raise ValidationError(
                    '正しい生年月日を入力してください。 / Please enter a valid date of birth.'
                )
        return birth_date