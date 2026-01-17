from django import forms
from .models import Song, UploadedImage, Comment


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = [single_file_clean(data, initial)]
        return result


class SongCreateForm(forms.ModelForm):
    """楽曲作成フォーム"""
    original_text = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 6,
            'placeholder': '楽曲にしたいテキストを入力してください...'
        }),
        label='元テキスト',
        required=False
    )
    
    class Meta:
        model = Song
        fields = ['title', 'genre', 'vocal_style']
        widgets = {
            'title': forms.TextInput(attrs={
                'placeholder': '楽曲のタイトルを入力してください'
            }),
            'genre': forms.TextInput(attrs={
                'placeholder': 'ジャンル（例：ポップ、ロック、クラシック）'
            }),
            'vocal_style': forms.RadioSelect()
        }
        labels = {
            'vocal_style': 'ボーカルスタイル'
        }
    
    def __init__(self, *args, **kwargs):
        extracted_text = kwargs.pop('extracted_text', None)
        generated_lyrics = kwargs.pop('generated_lyrics', None)
        super().__init__(*args, **kwargs)
        
        if extracted_text:
            self.fields['original_text'].initial = extracted_text
        
        self.generated_lyrics = generated_lyrics


class ImageUploadForm(forms.Form):
    """画像/PDFアップロードフォーム（バリデーション付き）"""
    images = MultipleFileField(
        required=False,
        widget=MultipleFileInput(attrs={
            'accept': 'image/*,.pdf,application/pdf',
            'class': 'form-control',
            'style': 'display: none !important;',
            'multiple': 'multiple'
        }),
        error_messages={
            'required': 'ファイルを選択してください。',
            'invalid': '有効なファイルを選択してください。'
        }
    )
    
    def clean_images(self):
        """ファイルサイズとタイプのバリデーション"""
        from django.conf import settings
        from django.core.exceptions import ValidationError
        
        files = self.cleaned_data.get('images', [])
        if not files:
            return files
        
        max_image_size = getattr(settings, 'MAX_IMAGE_SIZE', 10 * 1024 * 1024)
        max_pdf_size = getattr(settings, 'MAX_PDF_SIZE', 25 * 1024 * 1024)
        allowed_image_types = getattr(settings, 'ALLOWED_IMAGE_TYPES', 
            ['image/jpeg', 'image/png', 'image/gif', 'image/webp'])
        allowed_doc_types = getattr(settings, 'ALLOWED_DOCUMENT_TYPES', 
            ['application/pdf'])
        
        errors = []
        for f in files:
            content_type = getattr(f, 'content_type', '')
            file_size = getattr(f, 'size', 0)
            file_name = getattr(f, 'name', 'file')
            
            # タイプチェック
            if content_type in allowed_image_types:
                if file_size > max_image_size:
                    size_mb = max_image_size / (1024 * 1024)
                    errors.append(f'{file_name}: 画像は{size_mb:.0f}MB以下にしてください')
            elif content_type in allowed_doc_types:
                if file_size > max_pdf_size:
                    size_mb = max_pdf_size / (1024 * 1024)
                    errors.append(f'{file_name}: PDFは{size_mb:.0f}MB以下にしてください')
            else:
                errors.append(f'{file_name}: サポートされていないファイル形式です')
        
        if errors:
            raise ValidationError(errors)
        
        return files


class LyricsForm(forms.Form):
    """歌詞入力フォーム（長さバリデーション付き）"""
    lyrics = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 10,
            'placeholder': '歌詞を入力してください...',
            'class': 'form-control'
        }),
        label='歌詞'
    )
    
    def clean_lyrics(self):
        """歌詞の長さをバリデーション"""
        from django.conf import settings
        from django.core.exceptions import ValidationError
        
        lyrics = self.cleaned_data.get('lyrics', '')
        min_length = getattr(settings, 'MIN_LYRICS_LENGTH', 50)
        max_length = getattr(settings, 'MAX_LYRICS_LENGTH', 5000)
        
        if len(lyrics.strip()) < min_length:
            raise ValidationError(f'歌詞は{min_length}文字以上必要です')
        
        if len(lyrics) > max_length:
            raise ValidationError(f'歌詞は{max_length}文字以下にしてください')
        
        return lyrics


class CommentForm(forms.ModelForm):
    """コメントフォーム"""
    
    class Meta:
        model = Comment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'コメントを入力してください...',
                'class': 'form-control'
            })
        }
        labels = {
            'content': ''
        }


class SongPrivacyForm(forms.ModelForm):
    """楽曲プライバシー設定フォーム"""
    is_public = forms.BooleanField(
        required=False,
        initial=False,
        label='この楽曲を公開しますか？',
        help_text='公開すると、他のユーザーも楽曲を聴くことができるようになります。',
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )
    
    class Meta:
        model = Song
        fields = ['is_public']