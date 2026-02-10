"""
カスタムコンテキストプロセッサ - 全テンプレートで使用可能な変数を提供
"""

def user_usage_context(request):
    """ユーザーの利用回数情報をテンプレートに提供"""
    if not request.user.is_authenticated:
        return {}
    
    user = request.user
    remaining = user.get_remaining_model_usage()
    limits = user.get_model_limits()
    
    # 合計の残り回数を計算（無制限の場合は-1）
    if user.plan == 'pro' or user.is_staff or user.is_superuser:
        total_remaining = -1  # 無制限
        total_limit = -1
    else:
        total_remaining = sum(v for v in remaining.values() if v != -1)
        total_limit = sum(v for v in limits.values() if v != -1)
    
    return {
        'user_remaining_usage': remaining,
        'user_usage_limits': limits,
        'user_total_remaining': total_remaining,
        'user_total_limit': total_limit,
        'user_plan': user.plan,
        'user_is_pro': user.is_pro,
    }


# 対応言語リスト
AVAILABLE_LANGUAGES = [
    {'code': 'ja', 'name': '日本語'},
    {'code': 'en', 'name': 'English'},
    {'code': 'zh', 'name': '中文'},
    {'code': 'es', 'name': 'Español'},
    {'code': 'de', 'name': 'Deutsch'},
    {'code': 'pt', 'name': 'Português'},
]

VALID_LANG_CODES = {'ja', 'en', 'zh', 'es', 'de', 'pt'}

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
        'is_spanish': app_language == 'es',
        'is_german': app_language == 'de',
        'is_portuguese': app_language == 'pt',
        'available_languages': AVAILABLE_LANGUAGES,
        'current_language': current_language,
    }
