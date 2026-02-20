from django import template
import re
from datetime import timedelta

register = template.Library()


@register.filter
def remove_asterisks(value):
    """歌詞から米印(*)を除外するフィルター"""
    if not value:
        return value
    
    lines = value.split('\n')
    filtered_lines = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith('*'):
            cleaned_line = re.sub(r'\*+', '', line)
            filtered_lines.append(cleaned_line)
    
    return '\n'.join(filtered_lines)


@register.filter
def remove_circled_numbers(value):
    """歌詞から丸数字・囲み数字・特殊番号記号を除去するフィルター
    
    教材画像由来の ❶❷❸ ①②③ 等を表示から削除する。
    """
    if not value:
        return value
    
    circled_pattern = re.compile(
        r'[\u2460-\u2473'   # ① - ⑳
        r'\u2474-\u2487'    # ⑴ - ⒇
        r'\u2488-\u249B'    # ⒈ - ⒛
        r'\u24EA-\u24FF'    # ⓪ 等
        r'\u2776-\u277F'    # ❶ - ❿
        r'\u2780-\u2789'    # ➀ - ➉
        r'\u278A-\u2793'    # ➊ - ➓
        r'\u3251-\u325F'    # ㉑ - ㉟
        r'\u32B1-\u32BF'    # ㊱ - ㊿
        r'\u24B6-\u24E9'    # Ⓐ - ⓩ
        r']'
    )
    value = circled_pattern.sub('', value)
    
    # 余分なスペースを整理
    lines = value.split('\n')
    cleaned_lines = []
    for line in lines:
        line = re.sub(r'  +', ' ', line).strip()
        cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)


@register.filter
def get_item(dictionary, key):
    """辞書から指定したキーの値を取得するフィルター"""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def format_duration(value):
    """DurationFieldを分:秒形式でフォーマットするフィルター
    
    例: 0:03:09.270000 → 3:09
    """
    if not value:
        return ""
    
    # timedeltaオブジェクトの場合
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
    else:
        # 文字列の場合（"0:03:09.270000"形式）
        try:
            parts = str(value).split(':')
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                total_seconds = hours * 3600 + minutes * 60 + int(seconds)
            else:
                return str(value)
        except (ValueError, IndexError):
            return str(value)
    
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


# ジャンル翻訳辞書
GENRE_TRANSLATIONS = {
    # 日本語 → 英語, 中国語
    'ポップ': {'en': 'Pop', 'zh': '流行'},
    'ロック': {'en': 'Rock', 'zh': '摇滚'},
    'バラード': {'en': 'Ballad', 'zh': '抒情'},
    'ラップ': {'en': 'Rap', 'zh': '说唱'},
    'ヒップホップ': {'en': 'Hip Hop', 'zh': '嘻哈'},
    'エレクトロニック': {'en': 'Electronic', 'zh': '电子'},
    '電子音楽': {'en': 'Electronic', 'zh': '电子'},
    'ジャズ': {'en': 'Jazz', 'zh': '爵士'},
    'クラシック': {'en': 'Classical', 'zh': '古典'},
    'R&B': {'en': 'R&B', 'zh': 'R&B'},
    'カントリー': {'en': 'Country', 'zh': '乡村'},
    'フォーク': {'en': 'Folk', 'zh': '民谣'},
    'レゲエ': {'en': 'Reggae', 'zh': '雷鬼'},
    'ブルース': {'en': 'Blues', 'zh': '蓝调'},
    'メタル': {'en': 'Metal', 'zh': '金属'},
    'パンク': {'en': 'Punk', 'zh': '朋克'},
    'ソウル': {'en': 'Soul', 'zh': '灵魂'},
    'ファンク': {'en': 'Funk', 'zh': '放克'},
    'ディスコ': {'en': 'Disco', 'zh': '迪斯科'},
    'アンビエント': {'en': 'Ambient', 'zh': '氛围'},
    'ダンス': {'en': 'Dance', 'zh': '舞曲'},
    'J-POP': {'en': 'J-Pop', 'zh': 'J-Pop'},
    'K-POP': {'en': 'K-Pop', 'zh': 'K-Pop'},
    'アニソン': {'en': 'Anime', 'zh': '动漫'},
    'ボカロ': {'en': 'Vocaloid', 'zh': 'V家'},
    'auto': {'en': 'Auto', 'zh': '自动'},
    'Auto': {'en': 'Auto', 'zh': '自动'},
    # 英語のままのものも追加
    'pop': {'en': 'Pop', 'zh': '流行', 'ja': 'ポップ'},
    'rock': {'en': 'Rock', 'zh': '摇滚', 'ja': 'ロック'},
    'ballad': {'en': 'Ballad', 'zh': '抒情', 'ja': 'バラード'},
    'rap': {'en': 'Rap', 'zh': '说唱', 'ja': 'ラップ'},
    'hip hop': {'en': 'Hip Hop', 'zh': '嘻哈', 'ja': 'ヒップホップ'},
    'electronic': {'en': 'Electronic', 'zh': '电子', 'ja': 'エレクトロニック'},
    'jazz': {'en': 'Jazz', 'zh': '爵士', 'ja': 'ジャズ'},
    'classical': {'en': 'Classical', 'zh': '古典', 'ja': 'クラシック'},
    'dance': {'en': 'Dance', 'zh': '舞曲', 'ja': 'ダンス'},
}


@register.filter
def translate_genre(genre, language='ja'):
    """ジャンルを指定した言語に翻訳するフィルター
    
    Usage: {{ song.genre|translate_genre:app_language }}
    """
    if not genre:
        return genre
    
    genre_lower = genre.lower().strip()
    genre_stripped = genre.strip()
    
    # 翻訳辞書から検索
    if genre_stripped in GENRE_TRANSLATIONS:
        translations = GENRE_TRANSLATIONS[genre_stripped]
        if language == 'en':
            return translations.get('en', genre)
        elif language == 'zh':
            return translations.get('zh', genre)
        else:
            return translations.get('ja', genre)
    
    # 小文字でも検索
    if genre_lower in GENRE_TRANSLATIONS:
        translations = GENRE_TRANSLATIONS[genre_lower]
        if language == 'en':
            return translations.get('en', genre)
        elif language == 'zh':
            return translations.get('zh', genre)
        else:
            return translations.get('ja', genre)
    
    # 見つからない場合はそのまま返す
    return genre


# エラーメッセージ翻訳辞書
ERROR_TRANSLATIONS = {
    # ユーザー名関連
    '同じユーザー名が既に登録済みです。': {
        'en': 'This username is already taken.',
        'zh': '该用户名已被注册。'
    },
    'この項目は必須です。': {
        'en': 'This field is required.',
        'zh': '此项为必填项。'
    },
    # パスワード関連
    'このパスワードは一般的すぎます。': {
        'en': 'This password is too common.',
        'zh': '此密码太常见了。'
    },
    'このパスワードは短すぎます。最低 8 文字以上必要です。': {
        'en': 'This password is too short. It must contain at least 8 characters.',
        'zh': '此密码太短，至少需要8个字符。'
    },
    'このパスワードは数字しか使われていません。': {
        'en': 'This password is entirely numeric.',
        'zh': '此密码不能全为数字。'
    },
    '確認用パスワードが一致しません。': {
        'en': 'The two password fields didn\'t match.',
        'zh': '两次输入的密码不一致。'
    },
    '2つのパスワードフィールドが一致しません。': {
        'en': 'The two password fields didn\'t match.',
        'zh': '两次输入的密码不一致。'
    },
    'このパスワードはユーザー名と似すぎています。': {
        'en': 'Your password can\'t be too similar to your username.',
        'zh': '密码与用户名过于相似。'
    },
    # ログインエラー
    '正しいユーザー名とパスワードを入力してください。どちらのフィールドも大文字と小文字は区別されます。': {
        'en': 'Please enter a correct username and password. Note that both fields may be case-sensitive.',
        'zh': '请输入正确的用户名和密码。请注意两个字段都区分大小写。'
    },
    'このアカウントは有効ではありません。': {
        'en': 'This account is inactive.',
        'zh': '此账户未激活。'
    },
}


@register.filter
def translate_error(error_message, language='ja'):
    """エラーメッセージを指定した言語に翻訳するフィルター
    
    Usage: {{ form.username.errors.0|translate_error:app_language }}
    """
    if not error_message:
        return error_message
    
    error_str = str(error_message).strip()
    
    # 翻訳辞書から検索
    if error_str in ERROR_TRANSLATIONS:
        translations = ERROR_TRANSLATIONS[error_str]
        if language == 'en':
            return translations.get('en', error_message)
        elif language == 'zh':
            return translations.get('zh', error_message)
        else:
            return error_message  # 日本語の場合はそのまま
    
    # 見つからない場合はそのまま返す
    return error_message
