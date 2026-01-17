from django.http import FileResponse, Http404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db import models
import os
import mimetypes


@login_required
def serve_protected_media(request, path):
    """
    ログインユーザーのみがアクセスできる保護されたメディアファイル配信
    セキュリティ:
    - パストラバーサル攻撃を防止
    - ファイル所有権をチェック
    - 公開設定をチェック
    """
    # パス正規化でトラバーサル攻撃を防止
    # まず絶対パスに解決
    media_root = os.path.abspath(settings.MEDIA_ROOT)
    requested_path = os.path.abspath(os.path.join(media_root, path))
    
    # MEDIA_ROOTの外側へのアクセスをブロック
    if not requested_path.startswith(media_root):
        raise Http404("Access denied")
    
    if not os.path.exists(requested_path):
        raise Http404("File not found")
    
    if not os.path.isfile(requested_path):
        raise Http404("Not a file")
    
    # ファイルタイプに応じたパーミッションチェック
    if 'uploaded_images' in path:
        # アップロード画像: 所有者のみアクセス可能
        from songs.models import UploadedImage
        filename = os.path.basename(requested_path)
        uploaded_image = UploadedImage.objects.filter(
            image__endswith=filename,
            user=request.user
        ).first()
        
        if not uploaded_image:
            raise Http404("Access denied")
            
    elif 'songs/' in path or 'covers/' in path:
        # 楽曲ファイル/カバー画像: 所有者または公開設定の場合のみアクセス可能
        from songs.models import Song
        filename = os.path.basename(requested_path)
        
        # 楽曲を検索（ファイル名で）
        song = Song.objects.filter(
            models.Q(audio_file__endswith=filename) | 
            models.Q(cover_image__endswith=filename)
        ).first()
        
        if song:
            # 所有者または公開楽曲のみアクセス許可
            if song.created_by != request.user and not song.is_public:
                raise Http404("Access denied")
        else:
            # 楽曲に紐付いていないファイルはアクセス拒否
            raise Http404("Access denied")
            
    elif 'profile_images/' in path:
        # プロフィール画像: 認証済みユーザーなら誰でも閲覧可能
        pass
    else:
        # その他のファイルはアクセス拒否
        raise Http404("Access denied")
    
    # Content-Typeを自動検出
    content_type, _ = mimetypes.guess_type(requested_path)
    if not content_type:
        content_type = 'application/octet-stream'
    
    # ファイル名を取得（Content-Disposition用）
    filename = os.path.basename(requested_path)
    
    # FileResponseを使用（ストリーミング対応、メモリ効率良い）
    try:
        response = FileResponse(
            open(requested_path, 'rb'),
            content_type=content_type
        )
        
        # Content-Dispositionを設定
        # 画像・音声はインライン表示、その他はダウンロード
        if content_type.startswith('image/') or content_type.startswith('audio/'):
            disposition = 'inline'
        else:
            disposition = 'attachment'
        
        # RFC 5987形式でUTF-8ファイル名をエンコード
        from urllib.parse import quote
        encoded_filename = quote(filename)
        response['Content-Disposition'] = f"{disposition}; filename*=UTF-8''{encoded_filename}"
        
        # キャッシュ制御（認証済みユーザー向けなのでprivate）
        response['Cache-Control'] = 'private, max-age=3600'
        
        return response
    except Exception:
        raise Http404("Error reading file")
