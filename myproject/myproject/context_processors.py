"""
カスタムコンテキストプロセッサ - 全テンプレートで使用可能な変数を提供
"""
from django.core.cache import cache


def user_usage_context(request):
    """ユーザーの利用回数情報をテンプレートに提供（60秒キャッシュ）"""
    if not request.user.is_authenticated:
        return {}
    
    user = request.user
    cache_key = f'user_usage_{user.pk}'
    cached = cache.get(cache_key)
    
    if cached is not None:
        return cached
    
    remaining = user.get_remaining_model_usage()
    limits = user.get_model_limits()
    
    # 合計の残り回数を計算（無制限の場合は-1）
    if user.plan == 'pro' or user.is_staff:
        total_remaining = -1  # 無制限
        total_limit = -1
    else:
        total_remaining = sum(v for v in remaining.values() if v != -1)
        total_limit = sum(v for v in limits.values() if v != -1)
    
    result = {
        'user_remaining_usage': remaining,
        'user_usage_limits': limits,
        'user_total_remaining': total_remaining,
        'user_total_limit': total_limit,
        'user_plan': user.plan,
        'user_is_pro': user.is_pro,
    }
    
    cache.set(cache_key, result, 60)  # 60秒キャッシュ
    return result


# 対応言語リスト
AVAILABLE_LANGUAGES = [
    {'code': 'ja', 'name': '日本語'},
    {'code': 'en', 'name': 'English'},
    {'code': 'zh', 'name': '中文'},
    {'code': 'es', 'name': 'Español'},
    {'code': 'de', 'name': 'Deutsch'},
    {'code': 'pt', 'name': 'Português'},
    {'code': 'nl', 'name': 'Nederlands'},
]

VALID_LANG_CODES = {'ja', 'en', 'zh', 'es', 'de', 'pt', 'nl'}

# 表示言語ごとの通貨（en=USD、zh=CNY、それ以外の欧州言語=EUR）
# 実際の決済（Stripe）は常に日本円。ここでの換算はあくまで目安表示用。
CURRENCY_BY_LANGUAGE = {
    'ja': 'JPY',
    'en': 'USD',
    'zh': 'CNY',
    'es': 'EUR',
    'de': 'EUR',
    'pt': 'EUR',
    'nl': 'EUR',
}

CURRENCY_SYMBOLS = {
    'JPY': '¥',
    'USD': '$',
    'EUR': '€',
    'CNY': 'CN¥',
}

# 1単位あたりの円換算レート（固定値・概算。実勢レートとズレるため定期的に見直すこと）
CURRENCY_RATES_JPY = {
    'JPY': 1,
    'USD': 150,
    'EUR': 160,
    'CNY': 21,
}

# 料金プラン（円建て、settings.STRIPE_PRICE_IDS のコメントと同じ金額）
PLAN_PRICES_JPY = {
    'free': 0,
    'starter': 780,
    'pro': 1900,
    'school': 450,
}


def _format_price(jpy_amount, currency):
    """円建て金額を指定通貨での目安表示用文字列に変換する（固定レート・概算）"""
    symbol = CURRENCY_SYMBOLS.get(currency, '¥')
    if currency == 'JPY' or jpy_amount == 0:
        amount = jpy_amount if currency == 'JPY' else round(jpy_amount / CURRENCY_RATES_JPY.get(currency, 1))
        return f'{symbol}{amount:,}'
    rate = CURRENCY_RATES_JPY.get(currency, 1)
    converted = jpy_amount / rate
    return f'{symbol}{converted:,.2f}'


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

    # 言語に対応する通貨で料金プランの目安金額を計算（実際の決済は常に日本円）
    current_currency = CURRENCY_BY_LANGUAGE.get(app_language, 'JPY')
    plan_prices = {
        key: {
            'display': _format_price(jpy_amount, current_currency),
            'jpy_display': _format_price(jpy_amount, 'JPY'),
        }
        for key, jpy_amount in PLAN_PRICES_JPY.items()
    }

    return {
        'app_language': app_language,
        'is_english': app_language == 'en',
        'is_japanese': app_language == 'ja',
        'is_chinese': app_language == 'zh',
        'is_spanish': app_language == 'es',
        'is_german': app_language == 'de',
        'is_portuguese': app_language == 'pt',
        'is_dutch': app_language == 'nl',
        'available_languages': AVAILABLE_LANGUAGES,
        'current_language': current_language,
        'current_currency': current_currency,
        'plan_prices': plan_prices,
    }
