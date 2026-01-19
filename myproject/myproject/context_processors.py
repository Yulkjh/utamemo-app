"""
カスタムコンテキストプロセッサ - 全テンプレートで使用可能な変数を提供
"""

# 対応言語リスト
AVAILABLE_LANGUAGES = [
    {'code': 'ja', 'name': '日本語'},
    {'code': 'en', 'name': 'English'},
    {'code': 'zh', 'name': '中文'},
]

VALID_LANG_CODES = {'ja', 'en', 'zh'}

def language_context(request):
    """言語設定をテンプレートに提供"""
    # セッションから言語を取得
    app_language = request.session.get('app_language', 'ja')
    
    # URLパラメータで言語が指定されている場合はそれを優先
    url_lang = request.GET.get('_lang', '')
    if url_lang in VALID_LANG_CODES:
        app_language = url_lang
        # セッションも更新
        request.session['app_language'] = app_language
        request.session.modified = True
    
    # 無効な値の場合はデフォルトに戻す
    if app_language not in VALID_LANG_CODES:
        app_language = 'ja'
    
    # 現在の言語情報を取得
    current_language = next(
        (lang for lang in AVAILABLE_LANGUAGES if lang['code'] == app_language),
        AVAILABLE_LANGUAGES[0]  # デフォルトは日本語
    )
    
    return {
        'app_language': app_language,
        'is_english': app_language == 'en',
        'is_japanese': app_language == 'ja',
        'is_chinese': app_language == 'zh',
        'available_languages': AVAILABLE_LANGUAGES,
        'current_language': current_language,
    }
