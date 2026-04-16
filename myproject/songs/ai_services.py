import os
import requests
from django.conf import settings
from django.core.cache import cache
import time
import google.generativeai as genai
from PIL import Image
import re
import logging
import hashlib
from collections import Counter

# ロガー設定
logger = logging.getLogger(__name__)

# ========================================
# APIキャッシュ設定
# ========================================
# キャッシュ有効期限（秒）- 同じ入力に対するレスポンスをキャッシュ
GEMINI_CACHE_TTL = 3600 * 24  # 24時間


def _get_cache_key(text, operation):
    """テキストと操作種別からキャッシュキーを生成
    
    Args:
        text: 入力テキスト
        operation: 操作種別（'lyrics', 'flashcard', 'ocr'等）
    
    Returns:
        str: キャッシュキー
    """
    text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    return f"gemini_{operation}_{text_hash}"


def _get_cached_response(cache_key):
    """キャッシュからレスポンスを取得"""
    try:
        cached = cache.get(cache_key)
        if cached:
            logger.info(f"Cache hit: {cache_key}")
            return cached
    except Exception as e:
        logger.warning(f"Cache get error: {e}")
    return None


def _set_cached_response(cache_key, response, ttl=None):
    """レスポンスをキャッシュに保存"""
    try:
        cache.set(cache_key, response, ttl or GEMINI_CACHE_TTL)
        logger.info(f"Cache set: {cache_key}")
    except Exception as e:
        logger.warning(f"Cache set error: {e}")


# ========================================
# フラッシュカード前処理（【】マーク抽出）
# ========================================
def extract_bracketed_terms(text):
    """テキストから【】で囲まれた語句を抽出（LLM不使用）
    
    OCRで抽出されたテキストの【重要語句】マークを正規表現で確実に抽出。
    LLMに頑らず、ローカルで処理することで見落としを防ぐ。
    
    Args:
        text: OCR抽出テキスト
    
    Returns:
        list[str]: 【】で囲まれた語句のリスト（重複なし）
    """
    if not text:
        return []
    
    # 【...】パターンを抽出
    pattern = r'【([^】]+)】'
    matches = re.findall(pattern, text)
    
    # 重複を除去しつつ順序を維持
    seen = set()
    unique_terms = []
    for term in matches:
        term = term.strip()
        if term and term not in seen:
            seen.add(term)
            unique_terms.append(term)
    
    return unique_terms


def _normalize_keyword_term(term):
    """重要語候補の正規化（前後の記号除去・長さチェック）"""
    if not term:
        return ""
    normalized = term.strip()
    normalized = re.sub(r'^[\s\-・,、。:：;；\(\)\[\]「」『』【】]+', '', normalized)
    normalized = re.sub(r'[\s\-・,、。:：;；\(\)\[\]「」『』【】]+$', '', normalized)
    if len(normalized) < 2:
        return ""
    return normalized


def extract_importance_keywords(text, max_keywords=12):
    """OCRテキストから重要語をスコア付きで抽出する（ルールベース）

    重要度の根拠:
    - 【語句】マーク（赤字/太字/下線/色付き由来）を最優先
    - 出現回数
    - 見出し/年号/英数字専門語
    """
    if not text:
        return []

    scores = Counter()

    # 1) OCRで強調判定された語句（最重要）
    for term in extract_bracketed_terms(text):
        normalized = _normalize_keyword_term(term)
        if normalized:
            scores[normalized] += 8

    plain_text = re.sub(r'[【】]', '', text)
    lines = [line.strip() for line in plain_text.splitlines() if line.strip()]

    # 2) 見出しらしい行は重みを上げる
    heading_patterns = (
        r'^第[0-9一二三四五六七八九十]+',
        r'^[0-9]+[\.|\)]',
        r'^(ポイント|重要|要点|まとめ|公式|定義|用語)',
    )

    token_pattern = re.compile(
        r'[A-Za-z][A-Za-z0-9_\-\+\.]{1,}'
        r'|[0-9]{2,4}年'
        r'|[0-9]+(?:\.[0-9]+)?(?:%|℃|cm|mm|kg|g|m|km|L|ml|Hz|V|A)'
        r'|[ァ-ヴー]{2,}'
        r'|[一-龥]{2,}'
    )

    for line in lines:
        is_heading = any(re.search(pattern, line) for pattern in heading_patterns)
        for match in token_pattern.findall(line):
            token = _normalize_keyword_term(match)
            if not token:
                continue
            # ひらがな2文字のみ等のノイズを除外
            if re.fullmatch(r'[ぁ-ん]{2,3}', token):
                continue
            scores[token] += 2 if is_heading else 1

    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    return ranked[:max_keywords]


def _build_importance_instruction_block(extracted_text, max_keywords=12):
    """重要語スコアをプロンプトへ埋め込むための説明ブロックを作成"""
    ranked = extract_importance_keywords(extracted_text, max_keywords=max_keywords)
    if not ranked:
        return ""

    lines = [f"・{term}（重要度:{score}）" for term, score in ranked]
    return (
        "\n■ 重要語句候補（OCR強調と出現頻度から算出）\n"
        + "\n".join(lines)
        + "\n・重要度が高い語句はChorusで優先的に反復してください\n"
    )


def _is_explosive_lyrics_mode(custom_request):
    """カスタム要求からエグスプロージョン風スタイル指定を検出"""
    if not custom_request:
        return False

    lowered = custom_request.lower()
    trigger_words = [
        'エグスプロージョン', 'explosion', '奇抜', '斬新', '覚えやすい',
        'インパクト', 'ネタ風', '振付', '掛け声', 'コール&レスポンス',
    ]
    return any(word in lowered for word in trigger_words)



# Gemini APIをグローバルに一度だけ設定
_GEMINI_CONFIGURED = False
_GEMINI_MODEL = None


def remove_circled_numbers(text):
    """丸数字・囲み数字・特殊番号記号を除去する
    
    教材画像に含まれる ❶❷❸ ①②③ ⑴⑵⑶ Ⅰ Ⅱ Ⅲ 等を歌詞から削除。
    除去後に残る余分なスペースも整理する。
    """
    if not text:
        return text
    
    # 丸数字・囲み数字のUnicode範囲を網羅的に除去
    # ① - ⑳ (U+2460 - U+2473)
    # ⑴ - ⒇ (U+2474 - U+2487)  括弧付き数字
    # ⒈ - ⒛ (U+2488 - U+249B)  ピリオド付き数字
    # ❶ - ❿ (U+2776 - U+277F)  黒丸数字(Dingbat)
    # ➀ - ➉ (U+2780 - U+2789)  二重丸数字
    # ➊ - ➓ (U+278A - U+2793)  黒二重丸数字
    # ㉑ - ㉟ (U+3251 - U+325F)  丸数字21-35
    # ㊱ - ㊿ (U+32B1 - U+32BF)  丸数字36-50
    # ⓪ - ⓿ (U+24EA - U+24FF)  その他の囲み数字
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
        r'\u24B6-\u24E9'    # Ⓐ - ⓩ（丸囲みアルファベット）
        r']'
    )
    text = circled_pattern.sub('', text)
    
    # 除去後の余分なスペースを整理（行頭/行末のスペース、連続スペース）
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # 連続スペースを1つに
        line = re.sub(r'  +', ' ', line)
        # 行頭・行末のスペースを除去
        line = line.strip()
        cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)


# Gemini安全性設定（全カテゴリでブロックなし）
GEMINI_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


def _safe_get_response_text(response):
    """Gemini APIレスポンスからテキストを安全に取得する。
    
    response.textは安全性フィルタでブロックされた場合にValueErrorを投げるため、
    candidatesを直接チェックする安全なアクセサ。
    
    Returns:
        str or None: 抽出されたテキスト、取得できない場合はNone
    """
    if not response:
        return None
    try:
        # まず直接 response.text を試す（正常レスポンスの場合最も速い）
        if response.text:
            return response.text.strip()
    except (ValueError, AttributeError):
        pass
    
    # candidatesから直接抽出を試みる
    try:
        if response.candidates:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                text = candidate.content.parts[0].text.strip()
                if text:
                    return text
    except (AttributeError, IndexError):
        pass
    
    return None


def _get_gemini_model():
    """Geminiモデルを取得（初回のみ設定）"""
    global _GEMINI_CONFIGURED, _GEMINI_MODEL
    
    if _GEMINI_CONFIGURED:
        return _GEMINI_MODEL
    
    api_key = getattr(settings, 'GEMINI_API_KEY', None)
    if api_key:
        try:
            genai.configure(api_key=api_key)
            # gemini-2.5-flash（安定版）を使用
            _GEMINI_MODEL = genai.GenerativeModel('gemini-2.5-flash')
            logger.info("Gemini APIの設定が完了しました (model: gemini-2.5-flash)")
        except Exception as e:
            logger.error(f"Gemini API設定エラー: {e}")
            _GEMINI_MODEL = None
    else:
        logger.warning("Gemini APIキーが設定されていません")
        _GEMINI_MODEL = None
    
    _GEMINI_CONFIGURED = True
    return _GEMINI_MODEL


def detect_lyrics_language(lyrics):
    """歌詞の主要言語を判定する
    
    ひらがな変換が必要なのは日本語のみ。
    それ以外の言語（中国語、英語、韓国語、スペイン語、ポルトガル語、
    ドイツ語、アラビア語、タイ語等）はすべてそのまま送信する。
    
    Returns:
        'ja' - 日本語（ひらがな・カタカナを含む → ひらがな変換する）
        'other' - 日本語以外（そのまま送信）
    """
    if not lyrics:
        return 'ja'
    
    # セクションラベルや空行を除去して歌詞本文のみ解析
    clean = re.sub(r'\[.*?\]', '', lyrics)
    clean = re.sub(r'\s+', '', clean)
    
    if not clean:
        return 'ja'
    
    hiragana_count = 0
    katakana_count = 0
    
    for char in clean:
        cp = ord(char)
        if 0x3040 <= cp <= 0x309F:
            hiragana_count += 1
        elif 0x30A0 <= cp <= 0x30FF:
            katakana_count += 1
    
    japanese_kana = hiragana_count + katakana_count
    
    # ひらがな・カタカナが含まれていれば日本語
    # （日本語の歌詞には必ず助詞やひらがな表記が含まれる）
    if japanese_kana > 0:
        return 'ja'
    
    # ひらがな・カタカナが一切ない場合は日本語以外
    # （中国語、英語、韓国語、スペイン語、ポルトガル語、ドイツ語、
    #   アラビア語、タイ語、ヒンディー語、フランス語など全て該当）
    return 'other'


class MurekaAIGenerator:
    """Mureka AI を使用した楽曲生成クラス"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'MUREKA_API_KEY', None)
        self.base_url = getattr(settings, 'MUREKA_API_URL', 'https://api.mureka.ai')
        self.use_real_api = getattr(settings, 'USE_MUREKA_API', False)
        
        if self.use_real_api and self.api_key:
            logger.info("MurekaAIGenerator: Using Mureka API for song generation.")
        else:
            logger.info("MurekaAIGenerator: API key not set or disabled.")
    
    def generate_song(self, lyrics, title="", genre="pop", vocal_style="female", model="mureka-v8", music_prompt=""):
        """歌詞から楽曲を生成（Mureka API使用）
        
        Args:
            lyrics: 歌詞テキスト
            title: 楽曲タイトル
            genre: ジャンル
            vocal_style: ボーカルスタイル (female/male)
            model: Murekaモデルバージョン (mureka-v8, mureka-o2, mureka-7.6)
            music_prompt: ユーザー指定の音楽スタイルプロンプト
        """
        
        if not self.use_real_api or not self.api_key:
            raise Exception("Mureka API is not configured. Please set MUREKA_API_KEY and USE_MUREKA_API=True")
        
        return self._generate_with_mureka_api(lyrics, title, genre, vocal_style, model, music_prompt)
    
    def _generate_with_mureka_api(self, lyrics, title, genre, vocal_style, model="mureka-v8", music_prompt=""):
        """Mureka APIを使用して楽曲を生成
        
        Args:
            lyrics: 歌詞テキスト
            title: 楽曲タイトル  
            genre: ジャンル
            vocal_style: ボーカルスタイル
            model: Murekaモデル (mureka-v8, mureka-o2, mureka-7.6)
            music_prompt: ユーザー指定の音楽スタイルプロンプト
        """
        import requests
        import time
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        # 注意: 以前は_cancel_running_tasksで前のタスクをキャンセルしていたが、
        # これが他ユーザーの生成中タスクもキャンセルしてしまう問題があったため削除。
        # キューマネージャーが1曲ずつ順番に処理するため、並行タスクの心配は不要。
        logger.info("Preparing to send song generation request...")
        
        # 「auto」または空の場合はジャンルを指定しない（AIに自動選択させる）
        is_auto_genre = not genre or genre.strip() == "" or genre.strip().lower() == "auto" or genre.strip() in ["おまかせ", "自动"]
        if is_auto_genre:
            genre = ""  # ジャンル指定なし
        
        # 歌詞の長さを制限（Mureka APIの制限対策）
        # 注意: ひらがな変換後は文字数が増えるため、余裕を持った制限を設定
        max_lyrics_length = 2500
        if len(lyrics) > max_lyrics_length:
            logger.info(f"Lyrics too long ({len(lyrics)} chars), truncating smartly...")
            # セクション単位で切り詰める（[Verse], [Chorus]などの区切りを維持）
            lyrics = self._truncate_lyrics_by_section(lyrics, max_lyrics_length)
            logger.info(f"Truncated lyrics to {len(lyrics)} chars")
        
        # 歌詞が短すぎる場合のチェック
        if len(lyrics.strip()) < 50:
            raise Exception("Lyrics too short for song generation (minimum 50 characters)")
        
        # モデルバージョンの検証と設定
        # V8のみ使用 — Mureka APIの "auto" は最新モデルを自動選択する
        if model != 'mureka-v8':
            logger.warning(f"Invalid model '{model}', defaulting to mureka-v8")
            model = 'mureka-v8'
        
        api_model = 'auto'  # V8 = 最新モデル → autoで自動選択
        logger.info(f"Model mapping: DB='{model}' → API='{api_model}'")
        
        # ジャンルを英語に変換（Mureka APIは英語プロンプトのほうが精度が高い）
        GENRE_TO_ENGLISH = {
            # 日本語
            'ポップ': 'Pop', 'ロック': 'Rock', 'バラード': 'Ballad',
            'ラップ': 'Rap', '電子音楽': 'Electronic', 'クラシック': 'Classical',
            'ジャズ': 'Jazz', 'おまかせ': '',
            # 中国語
            '流行': 'Pop', '摇滚': 'Rock', '抒情': 'Ballad',
            '说唱': 'Rap', '电子': 'Electronic', '古典': 'Classical', '爵士': 'Jazz',
            '自动': '',
            # スペイン語
            'Balada': 'Ballad', 'Electrónica': 'Electronic', 'Clásica': 'Classical',
            # ドイツ語
            'Ballade': 'Ballad', 'Elektronisch': 'Electronic', 'Klassik': 'Classical',
            # ポルトガル語
            'Eletrônica': 'Electronic', 'Clássica': 'Classical',
        }
        genre_en = GENRE_TO_ENGLISH.get(genre, genre)  # マッピングになければそのまま使用
        
        # music_prompt を英語に翻訳（日本語等の場合）
        music_prompt_en = ''
        if music_prompt and music_prompt.strip():
            music_prompt_en = self._translate_prompt_to_english(music_prompt.strip())
        
        # プロンプトを組み立て（すべて英語で）
        prompt_parts = []
        if genre_en:  # ジャンルが指定されている場合のみ追加
            prompt_parts.append(genre_en)
        
        # ボーカルスタイルの処理
        # 毎回異なる声質になるよう、ランダムな特徴を組み合わせる
        import random
        
        VOCAL_TONE_TRAITS = [
            'warm', 'bright', 'husky', 'clear', 'soft', 'powerful',
            'smooth', 'raspy', 'airy', 'rich', 'delicate', 'soulful',
            'silky', 'crisp', 'mellow', 'vibrant', 'breathy', 'deep',
        ]
        VOCAL_SINGING_STYLES = [
            'with natural vibrato', 'with gentle expression', 'with emotional delivery',
            'with dynamic range', 'with relaxed phrasing', 'with energetic performance',
            'with intimate tone', 'with lyrical flow', 'with passionate intensity',
            'with subtle nuance', 'with playful articulation', 'with steady control',
        ]
        VOCAL_AGE_RANGE = [
            'young adult', 'mature', 'youthful', 'seasoned',
        ]
        
        # スタイルごとの基本プロンプトとランダム特徴の組み合わせ
        FIXED_VOCAL_PROMPTS = {
            'vocaloid_female': 'high-pitched cute synthesized female vocal, Vocaloid-style electronic voice, bright and airy digital vocal tone',
            'vocaloid_male': 'synthesized male vocal, Vocaloid-style electronic voice, clear digital vocal tone with auto-tune effect',
            'duet': 'male and female duet vocal, harmonizing together, call and response singing',
            'choir': 'choral ensemble vocal, rich harmonies, layered group singing',
            'whisper': 'soft whispery vocal, intimate and breathy, ASMR-like gentle singing',
            'child': 'young child vocal, innocent and bright, youthful pure singing voice',
        }
        # ランダム特徴を付与するスタイル → (ベース性別, 追加特徴)
        RANDOM_VOCAL_BASE = {
            'female': ('female', ''),
            'female_cute': ('female', 'cute high-pitched sweet'),
            'female_cool': ('female', 'cool sophisticated alto'),
            'female_powerful': ('female', 'powerful belting strong'),
            'male': ('male', ''),
            'male_high': ('male', 'high-pitched tenor bright'),
            'male_low': ('male', 'deep low bass baritone'),
            'male_rough': ('male', 'rough gritty rock raspy'),
        }
        
        # music_promptに声・ボーカルに関する記述が含まれているか判定
        VOICE_KEYWORDS = [
            'vocal', 'voice', 'singer', 'singing', 'female', 'male',
            'soprano', 'alto', 'tenor', 'bass', 'baritone', 'husky',
            'breathy', 'raspy', 'falsetto', 'whisper', 'choir', 'duet',
        ]
        has_voice_in_prompt = False
        if music_prompt_en:
            prompt_lower = music_prompt_en.lower()
            has_voice_in_prompt = any(kw in prompt_lower for kw in VOICE_KEYWORDS)
        
        if has_voice_in_prompt:
            # ユーザーが声について指定済み → ランダム声質を付与しない
            logger.info(f"Voice description detected in music_prompt, skipping random vocal traits")
            if music_prompt_en:
                prompt_parts.append(music_prompt_en)
        else:
            if vocal_style in FIXED_VOCAL_PROMPTS:
                vocal_prompt = FIXED_VOCAL_PROMPTS[vocal_style]
            elif vocal_style in RANDOM_VOCAL_BASE:
                gender, extra = RANDOM_VOCAL_BASE[vocal_style]
                tone = random.choice(VOCAL_TONE_TRAITS)
                style = random.choice(VOCAL_SINGING_STYLES)
                age = random.choice(VOCAL_AGE_RANGE)
                base = f"{tone} {age} {gender} vocal {style}"
                vocal_prompt = f"{extra} {base}".strip() if extra else base
            else:
                vocal_prompt = vocal_style
            prompt_parts.append(vocal_prompt)
            if music_prompt_en:
                prompt_parts.append(music_prompt_en)
        
        full_prompt = ", ".join(prompt_parts)
        
        # イントロ・アウトロを短くする指示を追加
        full_prompt += ", short intro under 10 seconds, short outro under 10 seconds, start singing quickly, end shortly after vocals finish, no long instrumental sections"
        
        payload = {
            "lyrics": lyrics,
            "model": api_model,
            "prompt": full_prompt
        }
        
        logger.info(f"Using Mureka model: {api_model} (from DB: {model})")
        logger.info(f"Music prompt: {payload['prompt']}")
        logger.info(f"Lyrics length: {len(lyrics)} chars")
        
        # ペイロード全体をログに出力（デバッグ用）
        import json
        payload_log = {k: (v[:100] + '...' if k == 'lyrics' and len(v) > 100 else v) for k, v in payload.items()}
        logger.info(f"[MUREKA] Full payload: {json.dumps(payload_log, ensure_ascii=False)}")
        
        max_retries = 5
        base_wait_time = 10  # 10秒（30秒→10秒に短縮）
        # タイムアウトを設定から取得（デフォルト60秒）
        api_timeout = getattr(settings, 'MUREKA_API_TIMEOUT', 60)
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Sending request to Mureka API: {self.base_url}/v1/song/generate (Attempt {attempt + 1}/{max_retries})")
                response = requests.post(
                    f"{self.base_url}/v1/song/generate",
                    headers=headers,
                    json=payload,
                    timeout=api_timeout
                )
                
                logger.info(f"Response status: {response.status_code}")
                logger.info(f"Response text: {response.text[:500]}")
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Mureka API response: {result}")
                    logger.info(f"Mureka API task created! Task ID: {result.get('id')}")
                    
                    task_id = result.get('id')
                    if task_id:
                        return self._wait_for_mureka_completion(task_id, title, lyrics, genre)
                    else:
                        logger.warning("No task ID returned from Mureka API")
                        logger.info(f"Full response: {result}")
                        raise Exception("Mureka API did not return a task ID")
                
                elif response.status_code == 429:
                    wait_time = base_wait_time * (attempt + 1)
                    logger.warning(f"Mureka API rate limit (429). Waiting {wait_time}s...")
                    logger.info(f"Rate limit reached (429). Waiting {wait_time} seconds...")
                    
                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                        continue
                    else:
                        error_msg = f"Mureka API rate limit exceeded after {max_retries} attempts. しばらく待ってから再試行してください。"
                        logger.info(f"{error_msg}")
                        raise Exception(error_msg)
                
                elif response.status_code == 400:
                    # Bad request - 歌詞の問題の可能性
                    error_msg = f"Mureka API bad request (400): {response.text}"
                    logger.info(f"{error_msg}")
                    raise Exception(error_msg)
                
                elif response.status_code >= 500:
                    # サーバーエラー - リトライ
                    if attempt < max_retries - 1:
                        wait_time = base_wait_time * (attempt + 1)
                        logger.info(f"Server error ({response.status_code}), retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise Exception(f"Mureka API server error: {response.status_code}")
                
                else:
                    error_msg = f"Mureka API error: {response.status_code} - {response.text}"
                    logger.info(f"{error_msg}")
                    raise Exception(error_msg)
                    
            except requests.exceptions.Timeout:
                logger.info(f"Mureka API timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    wait_time = base_wait_time
                    logger.info(f"Retrying after {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception("Mureka API timeout after all retries")
                    
            except requests.exceptions.ConnectionError as e:
                logger.info(f"Mureka API connection error: {e}")
                if attempt < max_retries - 1:
                    wait_time = base_wait_time * (2 ** attempt)
                    logger.info(f"Retrying after {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception(f"Mureka API connection failed: {e}")
                    
            except requests.exceptions.RequestException as e:
                logger.info(f"Mureka API request error: {e}")
                if attempt < max_retries - 1:
                    wait_time = base_wait_time * (2 ** attempt)
                    logger.info(f"Retrying after {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise
    
    def _translate_prompt_to_english(self, text):
        """音楽スタイルプロンプトを英語に翻訳する（辞書ベース、LLM不使用）
        
        既に英語の場合はそのまま返す。日本語や他言語の場合は辞書で翻訳する。
        辞書にない語句はそのまま残す（Mureka APIは多少の非英語でも解釈可能）。
        """
        import re
        
        # ASCII文字が大部分なら既に英語と判定
        ascii_count = sum(1 for c in text if ord(c) < 128)
        if len(text) > 0 and ascii_count / len(text) > 0.8:
            return text
        
        # 音楽スタイル用の日本語→英語辞書（長い語句を先にマッチさせる）
        MUSIC_PROMPT_DICT = {
            # ジャンル・スタイル
            'ヒップホップ': 'hip-hop', 'シティポップ': 'city pop', 'ボサノバ': 'bossa nova',
            'アンビエント': 'ambient', 'オルタナティブ': 'alternative', 'プログレッシブ': 'progressive',
            'シンセウェーブ': 'synthwave', 'エレクトロニカ': 'electronica', 'トランス': 'trance',
            'テクノ': 'techno', 'ハウス': 'house', 'ドラムンベース': 'drum and bass',
            'レゲエ': 'reggae', 'スカ': 'ska', 'ファンク': 'funk', 'ソウル': 'soul',
            'ゴスペル': 'gospel', 'ブルース': 'blues', 'カントリー': 'country',
            'フォーク': 'folk', 'アコースティック': 'acoustic', 'オーケストラ': 'orchestral',
            'シンフォニック': 'symphonic', 'ケルト': 'celtic', 'ワールド': 'world',
            'ラテン': 'latin', 'サンバ': 'samba', 'タンゴ': 'tango',
            'ポップ': 'pop', 'ロック': 'rock', 'バラード': 'ballad',
            'ラップ': 'rap', 'ジャズ': 'jazz', 'クラシック': 'classical',
            '電子音楽': 'electronic', 'メタル': 'metal', 'パンク': 'punk',
            'アニソン': 'anime song', 'アニメ': 'anime style', 'ゲーム音楽': 'game music',
            'ボカロ': 'vocaloid style', 'アイドル': 'idol pop',
            'ローファイ': 'lo-fi', 'ロウファイ': 'lo-fi', 'ローファイビート': 'lo-fi beat',
            'R&B': 'R&B', 'EDM': 'EDM',
            # 中国語ジャンル
            '流行': 'pop', '摇滚': 'rock', '抒情': 'ballad', '说唱': 'rap',
            '电子': 'electronic', '古典': 'classical', '爵士': 'jazz',
            # テンポ・雰囲気
            'アップテンポ': 'upbeat tempo', 'スローテンポ': 'slow tempo',
            'ミドルテンポ': 'mid-tempo', 'テンポが速い': 'fast tempo',
            'テンポが遅い': 'slow tempo', 'テンポ': 'tempo',
            '速い': 'fast', '遅い': 'slow',
            '激しい': 'intense', '穏やか': 'calm', '静か': 'quiet',
            '明るい': 'bright', '暗い': 'dark', '切ない': 'melancholic',
            '悲しい': 'sad', '楽しい': 'fun', '爽やか': 'refreshing',
            'エモい': 'emotional', 'ノスタルジック': 'nostalgic',
            'ドラマチック': 'dramatic', '壮大': 'epic', '幻想的': 'dreamy',
            'ダーク': 'dark', 'ヘビー': 'heavy', 'ライト': 'light',
            'チル': 'chill', 'エモーショナル': 'emotional',
            'おしゃれ': 'stylish', 'かわいい': 'cute', 'かっこいい': 'cool',
            '元気': 'energetic', '力強い': 'powerful', '優しい': 'gentle',
            '繊細': 'delicate', '透明感': 'transparent ethereal',
            '重厚': 'heavy majestic', '軽快': 'light upbeat',
            # ボーカル・声
            '女性ボーカル': 'female vocal', '男性ボーカル': 'male vocal',
            '高い声': 'high-pitched voice', '低い声': 'low-pitched voice',
            'ハスキー': 'husky', 'ウィスパー': 'whisper',
            'ファルセット': 'falsetto', 'シャウト': 'shout',
            'ハモり': 'harmony', 'コーラス': 'chorus',
            'ラップ調': 'rap style', '語り': 'spoken word',
            # 楽器
            'ピアノ': 'piano', 'ギター': 'guitar', 'ドラム': 'drums',
            'ベース': 'bass', 'バイオリン': 'violin', 'チェロ': 'cello',
            'フルート': 'flute', 'サックス': 'saxophone', 'トランペット': 'trumpet',
            'シンセサイザー': 'synthesizer', 'シンセ': 'synth',
            'ストリングス': 'strings', 'ブラス': 'brass',
            'アコギ': 'acoustic guitar', 'エレキ': 'electric guitar',
            'ウクレレ': 'ukulele', 'ハープ': 'harp', 'オルガン': 'organ',
            'マリンバ': 'marimba', '三味線': 'shamisen', '琴': 'koto',
            '和楽器': 'Japanese traditional instruments', '和風': 'Japanese style',
            # 修飾
            '風': ' style', '調': ' style', '系': ' style', '的': '',
            '感じ': ' feel', 'っぽい': '-like',
        }
        
        result = text
        # 長い語句から順にマッチさせる（前後にスペースを付けて結合問題を防ぐ）
        for ja, en in sorted(MUSIC_PROMPT_DICT.items(), key=lambda x: len(x[0]), reverse=True):
            result = result.replace(ja, f' {en} ')
        
        # 残った日本語の助詞・接続詞を除去
        result = re.sub(r'[のでをがはにとも、。]+', ' ', result)
        # 連続スペースを整理
        result = re.sub(r'\s+', ' ', result).strip()
        # 空になった場合は元テキストを返す
        if not result:
            return text
        
        logger.info(f"Prompt translated (dict): '{text}' → '{result}'")
        return result
    
    def _truncate_lyrics_by_section(self, lyrics, max_length):
        """歌詞をセクション単位で切り詰める（完全なセクションで終わるように）"""
        import re
        
        if len(lyrics) <= max_length:
            return lyrics
        
        # セクションの区切りを検出（[Verse 1], [Chorus], [Bridge]など）
        section_pattern = r'\[(?:Verse|Chorus|Bridge|Intro|Outro)[^\]]*\]'
        section_matches = list(re.finditer(section_pattern, lyrics))
        
        if not section_matches:
            # セクションが見つからない場合は、行単位で切り詰め
            lines = lyrics.split('\n')
            result = []
            current_length = 0
            for line in lines:
                if current_length + len(line) + 1 > max_length:
                    break
                result.append(line)
                current_length += len(line) + 1
            return '\n'.join(result)
        
        # 最後の完全なセクションを含む位置を見つける
        truncated = lyrics
        
        # セクションの開始位置を逆順で確認
        for i in range(len(section_matches) - 1, -1, -1):
            section_start = section_matches[i].start()
            
            # 次のセクションの開始位置（または文字列の終端）
            if i + 1 < len(section_matches):
                section_end = section_matches[i + 1].start()
            else:
                section_end = len(lyrics)
            
            # このセクションまで含めるとmax_length以下になるか確認
            if section_end <= max_length:
                truncated = lyrics[:section_end].rstrip()
                break
            elif section_start <= max_length:
                # セクションの途中で切る場合は、前のセクションまでにする
                truncated = lyrics[:section_start].rstrip()
                break
        
        # 最低限の歌詞は残す
        if len(truncated) < 200 and len(lyrics) > 200:
            truncated = lyrics[:max_length]
        
        return truncated
    
    def _cancel_running_tasks(self, headers):
        """実行中のタスクをキャンセル"""
        import requests
        import time
        
        try:
            list_url = f"{self.base_url}/v1/song/list"
            response = requests.get(list_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                tasks = result.get('data', [])
                
                for task in tasks:
                    task_id = task.get('id')
                    status = task.get('status')
                    
                    if status in ['pending', 'running', 'queued', 'processing']:
                        logger.info(f"Cancelling running task: {task_id} (status: {status})")
                        cancel_url = f"{self.base_url}/v1/song/cancel/{task_id}"
                        cancel_response = requests.post(cancel_url, headers=headers, timeout=10)
                        
                        if cancel_response.status_code == 200:
                            logger.info(f"Task {task_id} cancelled successfully")
                        else:
                            logger.info(f"Failed to cancel task {task_id}: {cancel_response.text}")
                        
                        time.sleep(1)
                
                if not tasks:
                    logger.info("No running tasks found")
            else:
                logger.info(f"Could not fetch task list: {response.status_code}")
        except Exception as e:
            logger.info(f"Error checking/cancelling tasks: {e}")
    
    def _wait_for_mureka_completion(self, task_id, title, lyrics, genre):
        """Mureka APIのタスク完了を待つ"""
        import requests
        import time
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        max_attempts = 90  # 最大約5分待機
        attempt = 0
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while attempt < max_attempts:
            try:
                query_url = f"{self.base_url}/v1/song/query/{task_id}"
                logger.info(f"Checking task status: {query_url} (Attempt {attempt + 1}/{max_attempts})")
                
                response = requests.get(query_url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    consecutive_errors = 0  # リセット
                    result = response.json()
                    status = result.get('status')
                    
                    logger.info(f"Task {task_id} status: {status}")
                    
                    if status in ['completed', 'succeeded']:
                        choices = result.get('choices', [])
                        logger.info(f"Choices count: {len(choices) if choices else 0}")
                        
                        if choices and len(choices) > 0:
                            choice = choices[0]
                            audio_url = choice.get('url')
                            logger.info(f"Song URL: {audio_url}")
                            
                            # Mureka APIレスポンスの全フィールドをログ出力（LRC/タイミング情報の発見用）
                            import json
                            choice_keys = list(choice.keys())
                            logger.info(f"[MUREKA] Choice fields: {choice_keys}")
                            logger.info(f"[MUREKA] Choice fields: {choice_keys}")
                            # 各フィールドの値の型とサンプルをログ
                            for key in choice_keys:
                                val = choice[key]
                                val_type = type(val).__name__
                                val_preview = str(val)[:200] if val else 'None'
                                logger.info(f"[MUREKA] choice['{key}'] ({val_type}): {val_preview}")
                                logger.info(f"[MUREKA] choice['{key}'] ({val_type}): {val_preview}")
                            # result全体の追加フィールドも確認
                            result_keys = [k for k in result.keys() if k not in ('choices', 'status')]
                            if result_keys:
                                logger.info(f"[MUREKA] Additional result fields: {result_keys}")
                                for key in result_keys:
                                    val = result[key]
                                    val_preview = str(val)[:200] if val else 'None'
                                    logger.info(f"[MUREKA] result['{key}']: {val_preview}")
                                    logger.info(f"[MUREKA] result['{key}']: {val_preview}")
                            
                            if not audio_url:
                                raise Exception("Mureka API returned no audio URL")
                            
                            return {
                                'song_id': task_id,
                                'title': title or "AI Generated Song",
                                'artist': "Mureka AI",
                                'audio_url': audio_url,
                                'flac_url': choice.get('flac_url'),
                                'duration': choice.get('duration'),
                                'cover_image': choice.get('image_url'),
                                'lyrics': lyrics,
                                'genre': genre,
                                'status': 'completed',
                                'api_provider': 'mureka',
                                'trace_id': result.get('trace_id'),
                                'lyrics_sections': choice.get('lyrics_sections', []),
                            }
                        else:
                            logger.warning("No choices returned from Mureka API")
                            raise Exception("Mureka API returned no song choices")
                            
                    elif status in ['failed', 'error', 'cancelled']:
                        error_msg = result.get('error', result.get('message', 'Unknown error'))
                        logger.info(f"Task failed with status: {status}, error: {error_msg}")
                        raise Exception(f"Mureka generation failed: {error_msg}")
                        
                    else:
                        # まだ処理中 - 待機時間を調整
                        if attempt < 10:
                            wait_time = 3  # 最初は短く
                        elif attempt < 30:
                            wait_time = 4
                        else:
                            wait_time = 5  # 後半は長く
                        
                        logger.info(f"Task still {status}, waiting {wait_time}s...")
                        time.sleep(wait_time)
                        attempt += 1
                        
                elif response.status_code == 404:
                    logger.info(f"Task {task_id} not found")
                    raise Exception(f"Mureka task not found: {task_id}")
                    
                else:
                    consecutive_errors += 1
                    logger.info(f"Query error: {response.status_code} (consecutive: {consecutive_errors})")
                    
                    if consecutive_errors >= max_consecutive_errors:
                        raise Exception(f"Too many consecutive errors checking task status")
                    
                    time.sleep(5)
                    attempt += 1
                    
            except requests.exceptions.Timeout:
                consecutive_errors += 1
                logger.info(f"Query timeout (consecutive: {consecutive_errors})")
                
                if consecutive_errors >= max_consecutive_errors:
                    raise Exception("Too many timeouts checking task status")
                
                time.sleep(5)
                attempt += 1
                
            except requests.exceptions.RequestException as e:
                consecutive_errors += 1
                logger.info(f"Query request error: {e} (consecutive: {consecutive_errors})")
                
                if consecutive_errors >= max_consecutive_errors:
                    raise Exception(f"Network error checking task status: {e}")
                
                time.sleep(5)
                attempt += 1
                
            except Exception as e:
                if "failed" in str(e).lower() or "error" in str(e).lower():
                    raise  # 明確な失敗は再スロー
                logger.info(f"Error querying task: {e}")
                raise
        
        logger.error(f"Timeout waiting for task {task_id}")
        raise Exception(f"Timeout waiting for Mureka task after {max_attempts * 4} seconds")
    
    def describe_song(self, audio_url):
        """Mureka APIの楽曲分析エンドポイントを呼び出す
        
        /v1/song/describe に {"url": audio_url} を送信。
        instrument, genres, tags, description を返す。
        
        Args:
            audio_url: 分析対象の音声URL
            
        Returns:
            dict: APIレスポンス全体
        """
        import requests
        import json
        
        if not self.use_real_api or not self.api_key:
            logger.warning("Mureka API not configured for describe_song")
            return None
        
        endpoint = '/v1/song/describe'
        url = f"{self.base_url}{endpoint}"
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        payload = {"url": audio_url}
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            logger.info(f"[MUREKA] describe → {resp.status_code}")
            
            if resp.status_code == 200:
                result = resp.json()
                logger.info(f"[MUREKA] Describe keys: {list(result.keys())}")
                logger.info(f"[MUREKA] Describe full: {json.dumps(result, ensure_ascii=False)[:3000]}")
                return {
                    'status': 200,
                    'keys': list(result.keys()),
                    'data': result
                }
            else:
                return {
                    'status': resp.status_code,
                    'response': resp.text[:1000]
                }
        except Exception as e:
            logger.warning(f"[MUREKA] describe error: {e}")
            return {'error': str(e)}
    
    def list_api_endpoints(self):
        """利用可能なMureka APIエンドポイントを調査"""
        import requests
        
        if not self.use_real_api or not self.api_key:
            return None
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        # 既知のエンドポイント + 推測されるエンドポイントを試行
        endpoints_to_test = [
            ('GET', '/v1/song/list'),
            ('GET', '/v1/endpoints'),
            ('GET', '/v1/'),
            ('GET', '/v1/song/features'),
            ('POST', '/v1/song/describe'),
            ('POST', '/v1/song/lyrics'),
            ('POST', '/v1/song/transcribe'),
            ('POST', '/v1/lyrics/align'),
            ('POST', '/v1/lyrics/generate'),
        ]
        
        results = {}
        for method, endpoint in endpoints_to_test:
            try:
                url = f"{self.base_url}{endpoint}"
                if method == 'GET':
                    response = requests.get(url, headers=headers, timeout=10)
                else:
                    response = requests.post(url, headers=headers, json={}, timeout=10)
                
                results[endpoint] = {
                    'status': response.status_code,
                    'response': response.text[:200]
                }
                logger.info(f"[MUREKA] {method} {endpoint} → {response.status_code}: {response.text[:100]}")
                logger.info(f"[MUREKA] {method} {endpoint} → {response.status_code}: {response.text[:100]}")
                
            except Exception as e:
                results[endpoint] = {'status': 'error', 'response': str(e)[:100]}
        
        return results


class PDFTextExtractor:
    """PDFからテキストを抽出するクラス"""
    
    def extract_text_from_pdf(self, pdf_file):
        """PDFファイルからテキストを抽出
        

        まずPyMuPDFでテキスト抽出を試み、
        テキストが取得できない場合（スキャンPDFなど）はGemini OCRで画像として処理
        """
        try:
            import fitz  # PyMuPDF
            
            # ファイルポインタをリセット
            if hasattr(pdf_file, 'seek'):
                pdf_file.seek(0)
            
            # ファイルパスまたはファイルオブジェクトを処理
            if isinstance(pdf_file, str):
                doc = fitz.open(pdf_file)
            elif hasattr(pdf_file, 'path'):
                doc = fitz.open(pdf_file.path)
            elif hasattr(pdf_file, 'read'):
                pdf_bytes = pdf_file.read()
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            else:
                raise ValueError(f"Unsupported pdf_file type: {type(pdf_file)}")
            
            extracted_text = []
            page_count = len(doc)
            
            logger.info(f"PDF opened: {page_count} pages")
            
            for page_num in range(page_count):
                page = doc.load_page(page_num)
                text = page.get_text()
                if text.strip():
                    extracted_text.append(text.strip())
                    logger.info(f"Page {page_num + 1}: Extracted {len(text)} chars")
            
            doc.close()
            
            result = '\n\n'.join(extracted_text)
            
            # テキストが取得できた場合
            if result.strip():
                logger.info(f"PDF extraction successful! Extracted {len(result)} characters from {page_count} pages")
                return result
            
            # テキストが取得できない場合（スキャンPDFなど）はOCRで処理
            logger.info("No text found in PDF, trying OCR...")
            return self._extract_with_ocr(pdf_file, pdf_bytes if 'pdf_bytes' in dir() else None)
            
        except ImportError as e:
            logger.info(f"PyMuPDF not installed: {e}")
            return ""
        except Exception as e:
            logger.info(f"PDF extraction error: {e}")
            import traceback
            traceback.print_exc()
            return ""  # エラー時は空文字を返す
    
    def _extract_with_ocr(self, pdf_file, pdf_bytes=None):
        """PDFをページごとに画像に変換してOCRで処理"""
        try:
            import fitz
            from PIL import Image
            import io
            
            # PDF bytesを取得
            if pdf_bytes is None:
                if hasattr(pdf_file, 'seek'):
                    pdf_file.seek(0)
                if hasattr(pdf_file, 'read'):
                    pdf_bytes = pdf_file.read()
                elif isinstance(pdf_file, str):
                    with open(pdf_file, 'rb') as f:
                        pdf_bytes = f.read()
                else:
                    return ""
            
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            
            # Gemini OCRを使用
            model = _get_gemini_model()
            if not model:
                logger.warning("Gemini model not available for OCR")
                doc.close()
                return ""
            
            extracted_texts = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                # ページを画像に変換（解像度を上げる）
                mat = fitz.Matrix(2, 2)  # 2x zoom for better OCR
                pix = page.get_pixmap(matrix=mat)
                
                # PIL Imageに変換
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Geminiで OCR
                prompt = """この画像に含まれるテキストをすべて正確に書き起こしてください。

ルール:
・改行や段落構造をそのまま保つ
・一部の語句だけが下線・太字・マーカー・色付き（赤字・青字等）で強調されている場合、その語句を【】で囲む（例: 【重要語句】）
・ただし文章全体が同じ色やスタイルの場合は強調ではないので【】で囲まない
・テキストのみを出力し、説明や補足は一切書かない"""
                
                try:
                    response = model.generate_content([prompt, img], safety_settings=GEMINI_SAFETY_SETTINGS)
                    text = _safe_get_response_text(response)
                    if text:
                        extracted_texts.append(text)
                        logger.info(f"OCR Page {page_num + 1}: Extracted {len(text)} chars")
                except Exception as e:
                    logger.info(f"OCR error on page {page_num + 1}: {e}")
            
            doc.close()
            
            result = '\n\n'.join(extracted_texts)
            logger.info(f"PDF OCR completed! Extracted {len(result)} characters")
            return result
            
        except Exception as e:
            logger.info(f"PDF OCR extraction error: {e}")
            import traceback
            traceback.print_exc()
            return ""


class GeminiOCR:
    """Gemini を使用したOCRクラス"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'GEMINI_API_KEY', None)
        self.model = _get_gemini_model()
    
    def extract_text_from_image(self, image_file):
        """画像ファイルからテキストを抽出"""
        
        if not self.model:
            logger.error("GeminiOCR: Gemini API not configured (model is None)")
            return ""  # APIが設定されていない場合は空文字を返す
        
        try:
            import io
            
            # 画像を読み込む（複数の方法を試行）
            img = None
            if isinstance(image_file, str):
                logger.info(f"GeminiOCR: Opening image from path string: {image_file}")
                img = Image.open(image_file)
            elif hasattr(image_file, 'path'):
                try:
                    logger.info(f"GeminiOCR: Opening image from file path: {image_file.path}")
                    img = Image.open(image_file.path)
                except (FileNotFoundError, OSError) as path_error:
                    logger.warning(f"GeminiOCR: path access failed ({path_error}), trying .open()")
                    # path でファイルが見つからない場合、ストレージの .open() を使用
                    if hasattr(image_file, 'open'):
                        image_file.open('rb')
                        img = Image.open(image_file)
                    elif hasattr(image_file, 'read'):
                        image_file.seek(0)
                        img = Image.open(image_file)
            elif hasattr(image_file, 'read'):
                logger.info("GeminiOCR: Opening image from file-like object")
                img = Image.open(image_file)
            else:
                logger.error(f"GeminiOCR: Unsupported image_file type: {type(image_file)}")
                return ""
            
            if img is None:
                logger.error("GeminiOCR: Failed to open image (img is None)")
                return ""
            
            logger.info(f"GeminiOCR: Image opened successfully. Size: {img.size}, Mode: {img.mode}")
            
            # MPO形式（iPhoneの写真など）をRGBに変換してJPEG互換にする
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 画像をJPEG形式でメモリに保存し直す（MPO対策）
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', quality=95)
            img_buffer.seek(0)
            img = Image.open(img_buffer)
            
            prompt = """この画像に含まれるテキストをすべて正確に書き起こしてください。

ルール:
・改行や段落構造をそのまま保つ
・縦書きは上→下、右→左の順序で読む
・横書きは上→下、左→右の順序で読む
・見出し、本文、注釈、キャプションをすべて含める
・手書き文字も可能な限り正確に読み取る
・一部の語句だけが下線・太字・マーカー・色付き（赤字・青字等）で強調されている場合、その語句を【】で囲む（例: 【重要語句】）
・ただし文章全体が同じ色やスタイルの場合は強調ではないので【】で囲まない
・透かし、ページ番号、装飾は無視する
・テキストのみを出力し、説明や補足は一切書かない"""
            
            # リトライロジック（最大3回）
            max_retries = 3
            last_error = None
            for attempt in range(max_retries):
                try:
                    logger.info(f"GeminiOCR: Calling Gemini API for OCR (attempt {attempt + 1}/{max_retries})...")
                    response = self.model.generate_content(
                        [prompt, img],
                        safety_settings=GEMINI_SAFETY_SETTINGS,
                    )
                    
                    extracted_text = _safe_get_response_text(response)
                    if extracted_text:
                        logger.info(f"GeminiOCR: Success! Extracted {len(extracted_text)} characters")
                        return extracted_text
                    
                    # テキストが取得できなかった場合の詳細ログ
                    block_reason = getattr(getattr(response, 'prompt_feedback', None), 'block_reason', None)
                    finish_reason = None
                    if response and response.candidates:
                        finish_reason = getattr(response.candidates[0], 'finish_reason', None)
                    
                    logger.warning(f"GeminiOCR: Empty response on attempt {attempt + 1}. block_reason={block_reason}, finish_reason={finish_reason}")
                    last_error = f"Empty response (block_reason={block_reason}, finish_reason={finish_reason})"
                    
                except Exception as api_error:
                    last_error = str(api_error)
                    logger.warning(f"GeminiOCR: API error on attempt {attempt + 1}: {api_error}")
                
                # リトライ前に少し待つ
                if attempt < max_retries - 1:
                    import time as _time
                    _time.sleep(2 * (attempt + 1))
            
            logger.error(f"GeminiOCR: All {max_retries} attempts failed. Last error: {last_error}")
            return ""
                
        except Exception as e:
            logger.error(f"GeminiOCR: OCR error: {e}", exc_info=True)
            return ""  # エラー時も空文字を返してクラッシュを防ぐ


class LocalLLMLyricsGenerator:
    """ローカルLLM (学校GPU) を使用した歌詞生成クラス
    
    学校のGPU PCで動作する推論サーバー (serve.py) にHTTPリクエストを送る。
    settings.py の LOCAL_LLM_URL と LOCAL_LLM_API_KEY で設定。
    
    Geminiの代替として使用可能。設定がない場合やサーバーがダウンしている場合は
    GeminiLyricsGenerator にフォールバックする。
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'LOCAL_LLM_URL', None)
        self.api_key = getattr(settings, 'LOCAL_LLM_API_KEY', '')
        self.timeout = getattr(settings, 'LOCAL_LLM_TIMEOUT', 60)
    
    @property
    def is_available(self):
        """ローカルLLMが利用可能かチェック"""
        if not self.base_url:
            return False
        try:
            resp = requests.get(
                f"{self.base_url}/health",
                timeout=5
            )
            return resp.status_code == 200
        except Exception:
            return False
    
    def generate_lyrics(self, extracted_text, title="", genre="pop", language_mode="japanese", custom_request=""):
        """ローカルLLMで歌詞を生成"""
        if not self.base_url:
            raise Exception("LOCAL_LLM_URL が設定されていません")
        
        # キャッシュチェック
        cache_input = f"local|{extracted_text}|{genre}|{language_mode}|{custom_request}"
        cache_key = _get_cache_key(cache_input, 'lyrics')
        cached = _get_cached_response(cache_key)
        if cached:
            logger.info("LocalLLM: Returning cached lyrics")
            return cached
        
        try:
            response = requests.post(
                f"{self.base_url}/generate",
                json={
                    "text": extracted_text,
                    "genre": genre,
                    "language_mode": language_mode,
                    "custom_request": custom_request,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            data = response.json()
            if data.get("status") == "success" and data.get("lyrics"):
                lyrics = data["lyrics"]
                _set_cached_response(cache_key, lyrics, ttl=3600)
                logger.info(f"LocalLLM: 歌詞生成成功 ({len(lyrics)} 文字, {data.get('generation_time', '?')}秒)")
                return lyrics
            else:
                raise Exception(f"LocalLLM error: {data.get('error', 'Unknown error')}")
                
        except requests.exceptions.Timeout:
            logger.warning("LocalLLM: タイムアウト")
            raise Exception("ローカルLLMサーバーがタイムアウトしました")
        except requests.exceptions.ConnectionError:
            logger.warning("LocalLLM: 接続エラー")
            raise Exception("ローカルLLMサーバーに接続できません")
        except Exception as e:
            logger.error(f"LocalLLM: エラー: {e}")
            raise

    def generate_lyrics_from_images(self, images, title="", genre="pop", language_mode="japanese", custom_request="", extracted_text=""):
        """画像からの歌詞生成 — ローカルLLMは画像処理非対応のためGeminiにデリゲート
        
        ローカルLLMはテキスト→歌詞の変換に特化。
        画像→歌詞はGemini(Vision対応)に常にフォールバックする。
        """
        logger.info("LocalLLM: 画像ベース生成はGeminiにデリゲート")
        gemini = GeminiLyricsGenerator()
        return gemini.generate_lyrics_from_images(
            images, title=title, genre=genre,
            language_mode=language_mode, custom_request=custom_request,
            extracted_text=extracted_text,
        )

    def convert_to_hiragana(self, lyrics):
        """歌詞の漢字をひらがなに変換 — Geminiにデリゲート
        
        ひらがな変換はLlama 3では精度が不十分なため、常にGeminiを使う。
        """
        return convert_lyrics_to_hiragana_with_context(lyrics)

    @property
    def model(self):
        """GeminiLyricsGeneratorとの互換性のため (ダッシュボード表示用)
        
        ローカルLLMが利用可能なら True 相当の値を返す。
        """
        return self.is_available


class CloudLLMLyricsGenerator:
    """クラウドLLMサービスを使用した歌詞生成クラス
    
    OpenAI互換APIを持つクラウドLLMプロバイダーに対応:
      - Together AI    (https://api.together.xyz)
      - Fireworks AI   (https://api.fireworks.ai)
      - Groq           (https://api.groq.com/openai)
      - OpenRouter     (https://openrouter.ai/api)
      - vLLM self-host (https://your-server.com)
      - Any OpenAI-compatible endpoint
    
    settings.py で設定:
      CLOUD_LLM_PROVIDER = 'together'  # プロバイダー名 (ログ表示用)
      CLOUD_LLM_URL = 'https://api.together.xyz/v1/chat/completions'
      CLOUD_LLM_API_KEY = 'xxx'
      CLOUD_LLM_MODEL = 'meta-llama/Meta-Llama-3-8B-Instruct-Turbo'
    """

    # プロバイダー別のデフォルトURL
    PROVIDER_URLS = {
        'together':  'https://api.together.xyz/v1/chat/completions',
        'fireworks': 'https://api.fireworks.ai/inference/v1/chat/completions',
        'groq':      'https://api.groq.com/openai/v1/chat/completions',
        'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
    }

    # プロバイダー別のおすすめモデル
    PROVIDER_DEFAULT_MODELS = {
        'together':  'meta-llama/Meta-Llama-3-8B-Instruct-Turbo',
        'fireworks': 'accounts/fireworks/models/llama-v3-8b-instruct',
        'groq':      'llama3-8b-8192',
        'openrouter': 'meta-llama/llama-3-8b-instruct',
    }

    # 言語モード別システムプロンプト (serve.py と統一)
    SYSTEM_PROMPTS = {
        "japanese": (
            "あなたは暗記学習用の歌詞を作成する専門AIです。"
            "与えられた学習テキストから、韻を踏んでキャッチーで覚えやすい日本語の歌詞を生成します。"
            "重要な用語・人物名・年号・化学式などは必ず正確に歌詞に含めます。"
            "「歌で覚えよう」「覚えよう」「暗記しよう」等の学習行為を促すメタ的な表現は使わず、学習内容そのものを歌詞にしてください。"
            "「全てが大事」「忘れずに」「大切だよ」「テストに出る」等の励ましや心構えのフレーズも禁止です。"
        ),
        "english_vocab": (
            "You are an expert AI that creates study song lyrics for memorization. "
            "Given English vocabulary or text, create Japanese lyrics that help memorize English words. "
            "Include the English words directly in the lyrics with Japanese meanings. "
            "Format: 'English word 日本語の意味' pattern for easy memorization."
        ),
        "english": (
            "You are an expert AI that creates study song lyrics in English for memorization. "
            "Given study material, create catchy English lyrics with rhymes. "
            "Include key terms, names, dates, and formulas accurately in the lyrics."
        ),
        "chinese": (
            "你是一位专业的学习歌词创作AI。"
            "根据给定的学习文本，创作押韵、朗朗上口、便于记忆的中文歌词。"
            "重要的术语、人名、年份、化学式等必须准确地包含在歌词中。"
        ),
        "chinese_vocab": (
            "你是一位专业的学习歌词创作AI。"
            "根据给定的中文词汇，创作帮助记忆中文单词的日语歌词。"
            "在歌词中直接使用中文词汇并附上日语解释。"
        ),
    }

    def __init__(self):
        self.provider = getattr(settings, 'CLOUD_LLM_PROVIDER', '')
        self.api_key = getattr(settings, 'CLOUD_LLM_API_KEY', '')
        self.timeout = getattr(settings, 'CLOUD_LLM_TIMEOUT', 90)

        # URLの解決: 明示的指定 > プロバイダー別デフォルト
        explicit_url = getattr(settings, 'CLOUD_LLM_URL', '')
        if explicit_url:
            self.api_url = explicit_url
        else:
            self.api_url = self.PROVIDER_URLS.get(self.provider, '')

        # モデルの解決: 明示的指定 > プロバイダー別デフォルト
        explicit_model = getattr(settings, 'CLOUD_LLM_MODEL', '')
        if explicit_model:
            self.model_name = explicit_model
        else:
            self.model_name = self.PROVIDER_DEFAULT_MODELS.get(self.provider, '')

    @property
    def is_available(self):
        """クラウドLLMが利用可能か (APIキーとURLが設定済みか)"""
        return bool(self.api_url and self.api_key and self.model_name)

    @property
    def model(self):
        """ダッシュボード互換"""
        return self.is_available

    def _build_user_prompt(self, study_text, genre, language_mode, custom_request=""):
        """言語モード別ユーザープロンプト生成"""
        custom_section = ""
        if custom_request:
            custom_section = f"\n\n■ ユーザーからの追加リクエスト（重要！必ず反映してください）\n{custom_request}"

        if language_mode == "english_vocab":
            return (
                f"以下の英語テキストから{genre}ジャンルの日本語歌詞を作成してください。\n"
                f"英単語をそのまま歌詞に入れ、直後に日本語の意味を添えてください。\n"
                f"例：「apple りんご」「beautiful 美しい」\n"
                f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。\n\n"
                f"■ 学習テキスト\n{study_text}{custom_section}"
            )
        elif language_mode == "english":
            return (
                f"Create {genre} genre study song lyrics in English from the following text.\n"
                f"Make it rhyme, catchy and easy to memorize.\n"
                f"Include key terms, names, dates accurately.\n"
                f"Output only lyrics with section labels [Verse 1], [Chorus], [Verse 2] etc.\n\n"
                f"■ Study Text\n{study_text}{custom_section}"
            )
        elif language_mode == "chinese":
            return (
                f"请根据以下学习文本创作{genre}风格的中文歌词。\n"
                f"要押韵、朗朗上口、便于记忆。\n"
                f"重要术语、人名、年份必须准确包含。\n"
                f"输出格式：[Verse 1], [Chorus], [Verse 2] 等。\n\n"
                f"■ 学习文本\n{study_text}{custom_section}"
            )
        elif language_mode == "chinese_vocab":
            return (
                f"以下の中国語テキストから{genre}ジャンルの日本語歌詞を作成してください。\n"
                f"中国語の単語をそのまま歌詞に入れ、日本語の意味を添えてください。\n"
                f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。\n\n"
                f"■ 学習テキスト\n{study_text}{custom_section}"
            )
        else:  # japanese
            return (
                f"以下の学習テキストから{genre}ジャンルの歌詞を作成してください。\n"
                f"韻を踏み、キャッチーで覚えやすい歌詞にしてください。\n"
                f"重要な用語・人物名・年号は必ず歌詞に含めてください。\n"
                f"「歌で覚えよう」「覚えよう」等の学習を促す表現は使わず、学習内容そのものを歌詞にしてください。\n"
                f"出力は [Verse 1], [Chorus], [Verse 2] 等のセクションラベル付きの歌詞のみにしてください。\n\n"
                f"■ 学習テキスト\n{study_text}{custom_section}"
            )

    def generate_lyrics(self, extracted_text, title="", genre="pop", language_mode="japanese", custom_request=""):
        """クラウドLLMで歌詞を生成 (OpenAI互換API)"""
        if not self.is_available:
            raise Exception("クラウドLLM設定が不完全です (CLOUD_LLM_URL / CLOUD_LLM_API_KEY / CLOUD_LLM_MODEL)")

        # キャッシュ
        cache_input = f"cloud|{self.provider}|{extracted_text}|{genre}|{language_mode}|{custom_request}"
        cache_key = _get_cache_key(cache_input, 'lyrics')
        cached = _get_cached_response(cache_key)
        if cached:
            logger.info(f"CloudLLM ({self.provider}): Returning cached lyrics")
            return cached

        system_prompt = self.SYSTEM_PROMPTS.get(language_mode, self.SYSTEM_PROMPTS["japanese"])
        user_prompt = self._build_user_prompt(extracted_text, genre, language_mode, custom_request)

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 1024,
            "temperature": 0.7,
            "top_p": 0.9,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # OpenRouter requires extra headers
        if self.provider == 'openrouter':
            headers["HTTP-Referer"] = "https://utamemo.com"
            headers["X-Title"] = "UTAMEMO"

        try:
            import time as _time
            start = _time.time()

            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                raise Exception(f"CloudLLM ({self.provider}): No choices in response")

            lyrics = choices[0].get("message", {}).get("content", "").strip()
            if not lyrics:
                raise Exception(f"CloudLLM ({self.provider}): Empty response")

            elapsed = _time.time() - start
            _set_cached_response(cache_key, lyrics, ttl=3600)
            logger.info(
                f"CloudLLM ({self.provider}): 歌詞生成成功 "
                f"({len(lyrics)} 文字, {elapsed:.1f}秒, model={self.model_name})"
            )
            return lyrics

        except requests.exceptions.Timeout:
            logger.warning(f"CloudLLM ({self.provider}): タイムアウト ({self.timeout}秒)")
            raise Exception(f"クラウドLLM ({self.provider}) がタイムアウトしました")
        except requests.exceptions.ConnectionError:
            logger.warning(f"CloudLLM ({self.provider}): 接続エラー — {self.api_url}")
            raise Exception(f"クラウドLLM ({self.provider}) に接続できません")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else '?'
            body = e.response.text[:200] if e.response else ''
            logger.error(f"CloudLLM ({self.provider}): HTTP {status} — {body}")
            raise Exception(f"クラウドLLM ({self.provider}) エラー: HTTP {status}")
        except Exception as e:
            logger.error(f"CloudLLM ({self.provider}): {e}")
            raise

    def generate_lyrics_from_images(self, images, title="", genre="pop", language_mode="japanese", custom_request="", extracted_text=""):
        """画像からの歌詞生成 — クラウドLLMはテキスト専用のためGeminiにデリゲート"""
        logger.info(f"CloudLLM ({self.provider}): 画像ベース生成はGeminiにデリゲート")
        gemini = GeminiLyricsGenerator()
        return gemini.generate_lyrics_from_images(
            images, title=title, genre=genre,
            language_mode=language_mode, custom_request=custom_request,
            extracted_text=extracted_text,
        )

    def convert_to_hiragana(self, lyrics):
        """ひらがな変換 — Geminiにデリゲート"""
        return convert_lyrics_to_hiragana_with_context(lyrics)


def get_lyrics_generator():
    """歌詞生成エンジンを取得
    
    settings.LYRICS_BACKEND で切り替え:
      - "gemini": Geminiのみ (デフォルト)
      - "cloud":  クラウドLLM (Together AI / Groq 等) のみ
      - "local":  ローカルLLM (自前GPU) のみ
      - "ollama": Ollama (ローカル推論) のみ
      - "auto":   cloud → ollama → local → gemini の順にフォールバック
    """
    backend = getattr(settings, 'LYRICS_BACKEND', 'gemini')

    if backend == 'cloud':
        return CloudLLMLyricsGenerator()
    elif backend == 'local':
        return LocalLLMLyricsGenerator()
    elif backend == 'ollama':
        return OllamaLyricsGenerator()
    elif backend == 'auto':
        # 1. クラウドLLM
        cloud = CloudLLMLyricsGenerator()
        if cloud.is_available:
            logger.info("歌詞生成: クラウドLLMを使用")
            return cloud
        # 2. Ollama
        ollama = OllamaLyricsGenerator()
        if ollama.is_available:
            logger.info("歌詞生成: Ollamaを使用")
            return ollama
        # 3. ローカルLLM
        local = LocalLLMLyricsGenerator()
        if local.is_available:
            logger.info("歌詞生成: ローカルLLMを使用")
            return local
        # 4. Gemini
        logger.info("歌詞生成: cloud/ollama/local 不可、Geminiにフォールバック")
        return GeminiLyricsGenerator()
    else:
        return GeminiLyricsGenerator()


class GeminiLyricsGenerator:
    """Gemini を使用した歌詞生成クラス"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'GEMINI_API_KEY', None)
        self.model = _get_gemini_model()
    
    def generate_lyrics(self, extracted_text, title="", genre="pop", language_mode="japanese", custom_request=""):
        """抽出されたテキストから歌詞を生成（漢字のまま返す）
        
        最適化: 同一入力に対するレスポンスをキャッシュ（1時間有効）
        
        language_mode:
        - "japanese": 日本語モード（従来の動作）
        - "english_vocab": 日本語で英単語を覚えるモード
        - "english": 英語モード（英語の意味に集中）
        - "chinese": 中国語モード
        - "chinese_vocab": 中国語で単語を覚えるモード
        
        custom_request:
        - ユーザーからの追加リクエスト（例：文法を強調、特定のフレーズを入れるなど）
        """
        
        if not self.model:
            raise Exception("Gemini APIが設定されていません。管理者に連絡してください。")
        
        # キャッシュキーを生成（全パラメータを含む）
        cache_input = f"{extracted_text}|{genre}|{language_mode}|{custom_request}"
        cache_key = _get_cache_key(cache_input, 'lyrics')
        
        # キャッシュをチェック
        cached = _get_cached_response(cache_key)
        if cached:
            logger.info("GeminiLyricsGenerator: Returning cached lyrics")
            return cached
        
        try:
            if language_mode == "english_vocab":
                prompt = self._get_english_vocab_prompt(extracted_text, genre, custom_request)
            elif language_mode == "english":
                prompt = self._get_english_prompt(extracted_text, genre, custom_request)
            elif language_mode == "chinese":
                prompt = self._get_chinese_prompt(extracted_text, genre, custom_request)
            elif language_mode == "chinese_vocab":
                prompt = self._get_chinese_vocab_prompt(extracted_text, genre, custom_request)
            else:
                prompt = self._get_japanese_prompt(extracted_text, genre, custom_request)
            
            response = self.model.generate_content(prompt, safety_settings=GEMINI_SAFETY_SETTINGS)
            
            raw_lyrics = _safe_get_response_text(response)
            
            if raw_lyrics:
                
                lyrics = self._extract_clean_lyrics(raw_lyrics)
                
                logger.info(f"Gemini lyrics generation successful! Generated {len(lyrics)} characters")
                
                # キャッシュに保存（1時間有効 - 再生成を妨げないため短めに）
                _set_cached_response(cache_key, lyrics, ttl=3600)
                
                return lyrics
            else:
                logger.error("Failed to generate lyrics")
                raise Exception("Failed to generate lyrics")
                
        except Exception as e:
            logger.info(f"Gemini lyrics generation error: {e}")
            raise

    def generate_lyrics_from_images(self, images, title="", genre="pop", language_mode="japanese", custom_request="", extracted_text=""):
        """画像を直接Geminiに渡して歌詞を生成（OCR+歌詞生成を一発で行う）
        
        OCRを挟まず画像から直接歌詞を生成することで:
        - OCR段階での情報ロスを防ぐ
        - 強調表現・図表・レイアウトをGeminiが直接理解できる
        - APIコール数が半減する（OCR+生成 → 生成のみ）
        
        Args:
            images: PIL.Image のリスト
            extracted_text: 既にOCRで抽出済みのテキスト（補助情報として使用、空でもOK）
            title, genre, language_mode, custom_request: 従来と同じ
        
        Returns:
            str: 生成された歌詞
        """
        if not self.model:
            raise Exception("Gemini APIが設定されていません。管理者に連絡してください。")
        
        if not images:
            raise Exception("画像が指定されていません。")
        
        try:
            # 言語モード別のプロンプトを取得
            # extracted_textに画像参照指示を追加
            image_instruction = "（※ 添付画像の内容を直接読み取って歌詞を作成してください。画像内で一部の語句だけが下線・太字・マーカー・色付き（赤字・青字等）で他と異なる見た目になっている場合、それは強調された重要語句です。必ず歌詞に含めてください。全体が同じ色やスタイルの場合は強調ではありません。）"
            
            if extracted_text:
                combined_text = f"{image_instruction}\n\n■ 画像から事前に抽出されたテキスト（参考）\n{extracted_text}"
            else:
                combined_text = image_instruction
            
            if language_mode == "english_vocab":
                prompt = self._get_english_vocab_prompt(combined_text, genre, custom_request)
            elif language_mode == "english":
                prompt = self._get_english_prompt(combined_text, genre, custom_request)
            elif language_mode == "chinese":
                prompt = self._get_chinese_prompt(combined_text, genre, custom_request)
            elif language_mode == "chinese_vocab":
                prompt = self._get_chinese_vocab_prompt(combined_text, genre, custom_request)
            else:
                prompt = self._get_japanese_prompt(combined_text, genre, custom_request)
            
            # プロンプト + 画像リストをGeminiに一括送信
            content_parts = [prompt] + list(images)
            
            logger.info(f"generate_lyrics_from_images: Sending {len(images)} image(s) + prompt to Gemini")
            
            # リトライロジック（最大3回）
            max_retries = 3
            last_error = None
            for attempt in range(max_retries):
                try:
                    response = self.model.generate_content(
                        content_parts,
                        safety_settings=GEMINI_SAFETY_SETTINGS,
                    )
                    
                    raw_lyrics = _safe_get_response_text(response)
                    
                    if raw_lyrics:
                        lyrics = self._extract_clean_lyrics(raw_lyrics)
                        logger.info(f"generate_lyrics_from_images: Success! Generated {len(lyrics)} chars (attempt {attempt + 1})")
                        return lyrics
                    
                    last_error = "Empty response"
                    logger.warning(f"generate_lyrics_from_images: Empty response on attempt {attempt + 1}")
                    
                except Exception as api_error:
                    last_error = str(api_error)
                    logger.warning(f"generate_lyrics_from_images: API error on attempt {attempt + 1}: {api_error}")
                
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
            
            # 全リトライ失敗 → テキストベースにフォールバック
            if extracted_text:
                logger.warning("generate_lyrics_from_images: All image attempts failed, falling back to text-based generation")
                return self.generate_lyrics(extracted_text, title=title, genre=genre, language_mode=language_mode, custom_request=custom_request)
            
            raise Exception(f"画像からの歌詞生成に失敗しました: {last_error}")
            
        except Exception as e:
            logger.error(f"generate_lyrics_from_images error: {e}")
            raise

    def _get_english_vocab_prompt(self, extracted_text, genre, custom_request=""):
        """日本語で英単語を覚えるためのプロンプト"""
        custom_section = ""
        if custom_request:
            custom_section = f"""
■ ユーザーからの追加リクエスト（重要！必ず反映してください）
{custom_request}
"""
        return f"""あなたはエグスプロージョン（「本能寺の変」で有名）のように、英単語をノリノリのリズムに乗せて覚えさせるプロの作詞家です。
聴いた人が思わず口ずさんでしまい、気づいたら英単語を覚えているような、キャッチーで中毒性のある{genre}ジャンルの日本語歌詞を作成してください。

■ テキスト内容
{extracted_text}
{custom_section}
■ 英単語暗記のための絶対条件

【最重要：英単語と日本語訳のセット】
・英単語をそのまま歌詞に入れ、直後に日本語の意味を添える
・例：「apple りんご」「beautiful 美しい」「remember 思い出す」
・発音しやすいように英単語をカタカナで補助してもOK
・例：「アップル apple りんご」

【繰り返しで定着】
・重要な英単語はChorusで3回以上繰り返す
・「英単語 → 意味 → 英単語」のパターンで記憶定着
・例：「important 大切な important」

【例文フレーズも活用】
・単語だけでなく、簡単な例文も歌詞に組み込む
・例：「I have a pen ペンを持ってる」

【品詞や用法のヒント】
・動詞、名詞、形容詞などを自然に歌詞で説明
・例：「run 走る 動詞だよ」「happy 幸せ 形容詞」

【★ 楽曲スタイル要件（最重要）】
・エグスプロージョンの「本能寺の変」のようにテンポよく畳みかけるリズム感
・日本語がメインで、英単語が自然に混ざる
・ラップ調・語呂合わせ・掛け合いも積極活用
・一度聞いたら頭から離れないキャッチーなフレーズ
・堅苦しさゼロ — 楽しい歌として成立させる
・全体として約180秒（3分）相当の分量（歌詞行数40〜60行を目安に）
・韻を踏むことを意識する

■ 出力フォーマット（厳守 — 3分の楽曲に十分な量を書くこと）
[Verse 1]
（英単語と日本語訳を含む歌詞、6〜10行）

[Chorus]
（最重要英単語を繰り返す、4〜6行）

[Verse 2]
（歌詞、6〜10行）

[Chorus]
（繰り返し）

[Verse 3]
（さらに英単語を追加、6〜10行）

[Bridge]
（補足、4〜6行）

[Chorus]
（最終）

■ 厳守事項
・歌詞のみを出力すること
・説明文、コメント、解説は一切書かない
・丸数字（①②③、❶❷❸など）や番号記号は絶対に使わない
・元テキストにある番号記号は歌詞に含めず、内容だけを使う
・「歌で覚えよう」「覚えよう」「覚えちゃおう」「暗記しよう」「マスターしよう」など、学習行為を促すメタ的な表現は使わない。学習内容そのものを歌詞にすること。
・「全てが大事」「忘れずに」「大切だよ」「しっかり覚えて」「ポイントだ」「テストに出る」など、学習への心構えや励ましのフレーズも使わない。
"""

    def _get_english_prompt(self, extracted_text, genre, custom_request=""):
        """English mode - Pure English lyrics for native English speakers"""
        custom_section = ""
        if custom_request:
            custom_section = f"""

■ ADDITIONAL USER REQUEST (IMPORTANT! Must be reflected in the lyrics)
{custom_request}
"""
        return f"""You are an expert songwriter who turns textbook content into irresistibly catchy, viral-worthy songs — think Schoolhouse Rock ("Conjunction Junction"), Animaniacs ("Yakko's World"), or the rhythm and energy of educational rap battles. Your songs make people sing along without even trying, and before they know it, the content is stuck in their head forever.

Create {genre} style lyrics in PURE ENGLISH from the following text.

■ Text Content
{extracted_text}
{custom_section}
■ ABSOLUTE REQUIREMENT
・Write 100% in English - NO Japanese, Chinese, or any other language
・Every word must be English
・This is for native English speakers to memorize personal information

■ Songwriting Techniques for Memory

【★ MAKE IT ADDICTIVELY CATCHY (TOP PRIORITY)】
・Think Schoolhouse Rock energy — fun, fast-paced, impossible not to sing along
・Use rhyming patterns aggressively (AABB, ABAB) — every line should rhyme or near-rhyme
・Create hooks so catchy they get stuck in your head for days
・Use rap-style rhythmic flow, call-and-response, wordplay, and clever phrasing
・The Chorus must be an earworm — a short, punchy, repeatable chant
・Zero textbook vibes — it should feel like a real hit song that happens to teach you something

【Key Information Focus】
・Turn facts into singable lines
・Make numbers and dates rhythmic
・Include terms wrapped in 【】brackets (these are emphasized/highlighted/colored terms) as highest priority
・Right after important terms, explain their meaning/definition/characteristics
・Include as many technical terms, names, dates, places, concepts as possible from the text

【FORBIDDEN Filler Words】
・Do NOT use: "so", "well", "you see", "that is", "in other words", "basically"
・Minimize: "it is", "there is", "this is"
・Connect terms and explanations directly
・Keep it simple: term + explanation format

【Content Rules】
・Do NOT add information not in the original text
・Only facts and data - no decorative expressions
・Do NOT include common knowledge or obvious things
・Do NOT abbreviate or paraphrase proper nouns

【Repetition is Key】
・Repeat the most important info in the Chorus (at least 2-3 times)
・Use call-and-response patterns
・Make the hook unforgettable

【Structure for Memory】
・Chorus: Concentrate the most important terms and their explanations
・Verse: Clearly state terms, definitions, characteristics, and differences
・Bridge: Add comparisons or supplementary explanations of related terms

【Natural English Flow】
・Use contractions (don't, won't, gonna, wanna)
・Keep it conversational and natural
・Sound like a real pop/rock song

【Song Style】
・About 180 seconds (3 minutes) length (aim for 40-60 lyric lines total)
・Repeat keywords 2-4 times
・Clear pronunciation and ear-catching phrases
・Use rhyming patterns to make lines memorable

■ Output Format (Strict — write enough for a 3-minute song)
[Verse 1]
(English lyrics, 6-10 lines)

[Chorus]
(catchy hook with key info repeated, 4-6 lines)

[Verse 2]
(continue the story, 6-10 lines)

[Chorus]
(repeat the hook)

[Verse 3]
(deeper content or additional info, 6-10 lines)

[Bridge]
(summary or twist, 4-6 lines)

[Chorus]
(final memorable hook)

■ STRICT RULES
・Output lyrics ONLY
・100% English - absolutely no other languages
・No explanations, no comments, no bullet points
・Do NOT use circled numbers (①②③, ❶❷❸, etc.) or any special numbering symbols
・If the source text has numbering symbols, use only the content, not the symbols
・Sound like a professional English pop song
・Only use information from the provided text
・Do NOT use meta-phrases like "let's memorize", "let's learn", "let's study", "time to learn", "remember this". Just present the actual content as lyrics.
・Do NOT use filler encouragement like "everything matters", "don't forget", "this is important", "key point", "it'll be on the test". Only concrete facts, terms, and definitions.
"""

    def _get_chinese_prompt(self, extracted_text, genre, custom_request=""):
        """Chinese mode - Pure Chinese lyrics for native Chinese speakers"""
        custom_section = ""
        if custom_request:
            custom_section = f"""

■ 用户额外要求（重要！必须在歌词中体现）
{custom_request}
"""
        return f"""你是一位像"凤凰传奇"或"洗脑神曲"风格的天才作词人，擅长把教科书内容变成让人听一遍就忘不掉的洗脑歌曲。
你的歌词节奏感强、朗朗上口、有魔性般的感染力。听众会不自觉地跟唱，在不知不觉中就记住了所有内容。
请创作{genre}风格的纯中文歌词。

■ 文本内容
{extracted_text}
{custom_section}
■ 绝对要求
・100%使用中文 - 绝对不能混入日语、英语或其他语言
・每一个字都必须是中文
・这是为中文母语者记忆个人信息而设计的

■ 记忆歌词创作技巧

【★ 洗脑级别的上头感（最重要）】
・像"凤凰传奇"一样节奏鲜明、一听就上头
・大量使用押韵 — 每一行都要押韵或近似押韵
・说唱节奏、顺口溜、对口相声式的节奏感都可以用
・副歌必须是一个魔性的、可以无限循环的洗脑段落
・零教科书感 — 必须是一首好听的歌，只是恰好教了你知识
・小学生到大学生都能不自觉地跟着唱

【关键信息聚焦】
・将事实转化为可唱的歌词
・让数字和日期有节奏感
・文本中用【】括起来的词语（即下划线、粗体、荧光笔标记、彩色文字的重点内容）必须优先包含在歌词中
・重要术语出现后，紧接着解释其含义、定义、特征
・尽可能多地包含文本中的专业术语、人名、年份、地名、概念

【禁止使用的过渡词】
・禁止使用：「那就是」「也就是说」「换句话说」「简单来说」「总之」
・尽量少用：「这是」「有」「是」
・术语和解释直接连接
・保持简洁：术语 + 解释的形式

【内容规则】
・不要添加原文中没有的信息
・只包含事实和数据 - 不要装饰性表达
・不要包含常识或显而易见的事情
・不要缩写或改写专有名词

【重复是关键】
・在副歌中重复最重要的信息（至少2-3次）
・使用呼应模式
・让钩子难以忘怀

【记忆结构】
・副歌：集中最重要的术语及其解释
・主歌：清楚说明术语、定义、特征和区别
・桥段：添加相关术语的对比或补充说明

【自然中文流畅度】
・使用日常口语表达
・保持对话式和自然的风格
・听起来像真正的中文流行歌曲

【歌曲风格】
・约180秒（3分钟）长度（歌词行数40-60行为目标）
・关键词重复2-4次
・发音清晰，短语令人印象深刻
・注意押韵以增强记忆效果

■ 输出格式（严格遵守 — 写出足够3分钟歌曲的内容）
[Verse 1]
（中文歌词，意义单位之间留空格，6-10行）

[Chorus]
（带有重复关键信息的朗朗上口的钩子，4-6行）

[Verse 2]
（继续故事，6-10行）

[Chorus]
（重复钩子）

[Verse 3]
（更深入的内容或补充信息，6-10行）

[Bridge]
（总结或转折，4-6行）

[Chorus]
（最终令人难忘的钩子）

■ 严格规则
・只输出歌词
・100%中文 - 绝对不能使用其他语言
・不要解释、不要评论、不要项目符号
・禁止使用圆圈数字（①②③、❶❷❸等）或任何特殊编号符号
・如果原文有编号符号，只使用内容，不要使用符号
・听起来像专业的中文流行歌曲
・只使用提供的文本中的信息
・禁止使用「用歌来记住吧」「记住吧」「学习吧」「背下来吧」等促进学习行为的元表达。只将学习内容本身写入歌词。
・禁止使用「都很重要」「别忘了」「很重要哦」「好好记住」「考试会考」等鼓励性空话。只写具体的事实、术语和定义。
"""

    def _get_chinese_vocab_prompt(self, extracted_text, genre, custom_request=""):
        """Chinese vocabulary mode - Pure Chinese lyrics for native Chinese speakers"""
        custom_section = ""
        if custom_request:
            custom_section = f"""

■ 用户额外要求（重要！必须在歌词中体现）
{custom_request}
"""
        return f"""你是一位像"凤凰传奇"或"洗脑神曲"风格的天才作词人，擅长把词汇内容变成让人听一遍就忘不掉的洗脑歌曲。
你的歌词节奏感强、朗朗上口、有魔性般的感染力。请创作{genre}风格的纯中文歌词，帮助记忆词汇和内容。

■ 文本内容
{extracted_text}
{custom_section}
■ 绝对要求
・100%使用中文 - 绝对不能混入日语、英语或其他语言
・每一个字都必须是中文
・这是为中文母语者记忆个人信息而设计的

■ 记忆歌词创作技巧

【★ 洗脑级别的上头感（最重要）】
・像"凤凰传奇"一样节奏鲜明、一听就上头
・大量使用押韵、说唱节奏、顺口溜
・副歌必须是魔性的洗脑段落
・零教科书感 — 必须是好听的歌
・使用自然的中文节奏和韵律

【词汇强调】
・重要词汇在副歌中重复3次以上
・使用容易记忆的短语
・关键概念要反复出现
・文本中用【】括起来的词语（即下划线、粗体、荧光笔标记、彩色文字的重点内容）必须优先包含在歌词中
・重要术语出现后，紧接着解释其含义、定义、特征

【禁止使用的过渡词】
・禁止使用：「那就是」「也就是说」「换句话说」「简单来说」「总之」
・尽量少用：「这是」「有」「是」
・术语和解释直接连接
・保持简洁：术语 + 解释的形式

【内容规则】
・不要添加原文中没有的信息
・只包含事实和数据 - 不要装饰性表达
・不要包含常识或显而易见的事情
・不要缩写或改写专有名词

【重复是关键】
・在副歌中重复最重要的信息（至少2-3次）
・使用呼应模式
・让钩子难以忘怀

【记忆结构】
・副歌：集中最重要的术语及其解释
・主歌：清楚说明术语、定义、特征和区别
・桥段：添加相关术语的对比或补充说明

【自然中文流畅度】
・使用日常口语表达
・保持对话式和自然的风格
・听起来像真正的中文流行歌曲

【歌曲风格】
・约180秒（3分钟）长度（歌词行数40-60行为目标）
・关键词重复2-4次
・发音清晰，短语令人印象深刻
・注意押韵以增强记忆效果

■ 输出格式（严格遵守 — 写出足够3分钟歌曲的内容）
[Verse 1]
（纯中文歌词，意义单位之间留空格，6-10行）

[Chorus]
（重复最重要的词汇 - 纯中文，4-6行）

[Verse 2]
（纯中文歌词，6-10行）

[Chorus]
（重复 - 纯中文）

[Verse 3]
（更深入的内容 - 纯中文，6-10行）

[Bridge]
（总结 - 纯中文，4-6行）

[Chorus]
（最终 - 纯中文）

■ 严格规则
・只输出歌词
・100%中文 - 绝对不能使用其他语言
・不要解释、不要评论、不要项目符号
・禁止使用圆圈数字（①②③、❶❷❸等）或任何特殊编号符号
・如果原文有编号符号，只使用内容，不要使用符号
・听起来像专业的中文流行歌曲
・只使用提供的文本中的信息
・禁止使用「用歌来记住吧」「记住吧」「学习吧」「背下来吧」等促进学习行为的元表达。只将学习内容本身写入歌词。
・禁止使用「都很重要」「别忘了」「很重要哦」「好好记住」「考试会考」等鼓励性空话。只写具体的事实、术语和定义。
"""

    def _get_japanese_prompt(self, extracted_text, genre, custom_request=""):
        """日本語モード（従来）のプロンプト"""
        custom_section = ""
        if custom_request:
            custom_section = f"""
■ ユーザーからの追加リクエスト（重要！必ず反映してください）
{custom_request}
"""
        importance_block = _build_importance_instruction_block(extracted_text)
        explosive_block = ""
        if _is_explosive_lyrics_mode(custom_request):
            explosive_block = """
【エグスプロージョン風スタイル（追加要件）】
・各Verseに1箇所以上、短い掛け声（例:「ハイ！」「ドン！」）を入れる
・コール&レスポンス（問い→即答）を2セット以上含める
・最重要語句は語感を揃えて反復し、体で覚えられるリズムを優先する
・奇抜さは維持しつつ、事実関係・用語の正確性は絶対に崩さない
"""
        return f"""あなたはエグスプロージョン（「本能寺の変」で有名）のように、教科書の内容をノリノリのリズムに乗せて歌にするプロの作詞家です。
聴いた人が思わず口ずさんでしまい、気づいたら内容を覚えているような、キャッチーで中毒性のある{genre}ジャンルの歌詞を作成してください。

■ テキスト内容
{extracted_text}
{custom_section}
{importance_block}
{explosive_block}

■ 歌詞の書き方ルール

【表記ルール】
・意味の区切りごとにスペースを入れる
・1行は短めに、7〜15文字程度を目安に
・助詞（の、を、が、は、に）の前後にもスペースを入れて区切る
・長い単語は途中で区切らず、単語の前後にスペースを入れる
・歴史人物・地名・専門用語は漢字のまま使用
・漢字をひらがなに変換しない
・数字や年号：「794年」はそのまま「794年」
・外来語・カタカナ語はそのまま使用

【つなぎ言葉の禁止】
・「それは」「それで」「これは」「つまり」「すなわち」「要するに」は使用禁止
・「〜とは」「〜である」「〜という」も最小限に
・用語と説明を直接つなげる
・シンプルに単語＋説明の形で並べる

【★ 歌としてのクオリティ（最重要）】
・エグスプロージョンの「本能寺の変」のように、テンポよく畳みかけるリズム感
・韻を踏むことを強く意識する（行末の母音を揃える）
・リズムに乗せやすいテンポ感を最重視 — ラップ調・語呂合わせ・掛け合いも積極活用
・口ずさみやすく、一度聞いたら頭から離れないキャッチーなフレーズ
・Chorusは「本能寺の変！本能寺の変！」のような中毒性のあるリフレインに
・小学生〜中学生でも思わずノリノリで口ずさめる楽しさ重視
・堅苦しさゼロ、教科書感ゼロ — あくまで「楽しい歌」として成立させる

【テキスト情報の取り込み】
・テキスト内で【】で囲まれた語句（下線・太字・マーカー・色付き文字で強調された内容）は最重要として必ず歌詞に含める
・最重要単語はChorusで最低2〜3回以上繰り返す
・重要な専門用語が出たら、その直後または次の行でその意味・定義・特徴を説明する
・「AはBである」形式ではなく「A B」のようにシンプルに並べる
・テキストに含まれる専門用語・人物名・年号・地名・概念をできるだけ多く含める
・固有名詞は原文のまま使用し、言い換えしない
・単語の省略は禁止
・当たり前のこと、一般常識は含めない
・装飾的な表現や余計なストーリーは不要
・テキストに書かれていない情報は一切追加しない
・事実とデータのみを歌詞にする

【構造と記憶定着】
・Chorusに最重要語句とその説明を集中させる
・Verseで用語とその定義・特徴・違いを明確に述べる
・Bridgeで関連用語の対比や補足説明を入れる
・テキストに書かれている情報のみを使用
・事実関係・用語の意味を正確に
・要点を過不足なく含める
・人物名・地名・用語の読み方を調べて正確に

【楽曲スタイル要件】
・キーワードを2〜4回繰り返す
・耳に残りやすいフレーズと明瞭な発音
・全体として約180秒（3分）相当の適切な分量
・歌詞行数は40〜60行を目安にする

■ 出力フォーマット（厳守 — 3分の楽曲に十分な量を書くこと）
[Verse 1]
（歌詞のみ、単語間にスペースを入れる、6〜10行）

[Chorus]
（最重要単語を繰り返すキャッチーな歌詞のみ、4〜6行）

[Verse 2]
（歌詞のみ、6〜10行）

[Chorus]
（最重要単語を再度繰り返す歌詞のみ）

[Verse 3]
（さらに深い内容や追加情報、6〜10行）

[Bridge]
（補足・まとめ・対比の歌詞のみ、4〜6行）

[Chorus]
（最終Chorusの歌詞のみ）

■ 厳守事項
・歌詞のみを出力すること
・説明文、コメント、解説は一切書かない
・「といった」「組み込み」「工夫」「意識」などの制作過程の言及は不要
・応答文（「はい」「承知しました」）も不要
・箇条書き（*や-で始まる行）は含めない
・丸数字（①②③、❶❷❸など）や番号記号は絶対に使わない
・元テキストにある番号記号は歌詞に含めず、内容だけを使う
・セクションラベルと歌詞本文のみを出力
・漢字は漢字のまま使用する（ひらがなに変換しない）
・専門用語・人物名・地名は漢字表記を維持
・必ず単語の区切りにスペースを入れて、聴き取りやすくする
・「歌で覚えよう」「覚えよう」「覚えちゃおう」「暗記しよう」「マスターしよう」「学ぼう」「勉強しよう」など、学習行為そのものを促すメタ的な表現は使わない。学習内容そのものを歌詞にすること。
・「全てが大事」「忘れずに」「大切だよ」「しっかり覚えて」「ポイントだ」「テストに出る」など、学習への心構えや励ましのフレーズも使わない。具体的な事実・用語・定義だけを歌詞にすること。
"""
    
    def convert_to_hiragana(self, lyrics):
        """歌詞の漢字と数字をひらがなに変換（Mureka API送信用）
        Gemini AIで文脈を考慮した正確な読みを生成"""
        return convert_lyrics_to_hiragana_with_context(lyrics)
    
    def generate_tags(self, extracted_text, lyrics_content):
        """抽出されたテキストと歌詞から自動的にハッシュタグを生成
        
        注意: 現在このメソッドは使用されていません。
        タグはユーザーが楽曲作成後に手動で追加します。
        """
        if not self.model:
            return []
        
        try:
            prompt = f"""以下のテキストと歌詞から、学習内容を表す適切なハッシュタグを5〜10個生成してください。

元のテキスト:
{extracted_text}

生成された歌詞:
{lyrics_content}

【タグ生成のルール】
1. 教科・科目名（例: 歴史、理科、英語、数学）
2. 具体的なトピック（例: 縄文時代、光合成、三角関数）
3. 重要な用語や概念（例: DNA、産業革命、関数）
4. 学習レベル（例: 中学生、高校生、大学受験）

【出力形式】
- 各タグは1〜3単語程度で簡潔に
- タグの前に「#」は付けない
- カンマ区切りで出力
- 例: 歴史, 縄文時代, 弥生時代, 日本史, 考古学, 中学生

タグのみを出力してください（説明や前置きは不要）:"""
            
            response = self.model.generate_content(prompt, safety_settings=GEMINI_SAFETY_SETTINGS)
            
            tags_text = _safe_get_response_text(response)
            if tags_text:
                tags = [tag.strip() for tag in tags_text.split(',') if tag.strip()]
                tags = list(dict.fromkeys(tags))[:10]
                logger.info(f"Generated tags: {tags}")
                return tags
            else:
                return []
                
        except Exception as e:
            logger.info(f"Tag generation error: {e}")
            return []
    
    def _extract_clean_lyrics(self, raw_text):
        """AIのレスポンスから純粋な歌詞部分だけを抽出"""
        import re
        
        # 丸数字・囲み数字・特殊記号を除去（教材画像由来の番号記号）
        raw_text = remove_circled_numbers(raw_text)
        
        first_section = re.search(r'\[(Verse|Chorus|Bridge|Intro|Outro)', raw_text)
        
        if first_section:
            cleaned = raw_text[first_section.start():]
        else:
            cleaned = raw_text
        
        unwanted_patterns = [
            r'はい.*?(?:承知|わかり|了解).*?(?:\n|。)',
            r'.*?(?:といった|このように|以上のように).*?(?:組み込み|取り入れ|表現|工夫).*?(?:\n|。)',
            r'.*?(?:工夫|意識|配慮|注意).*?(?:しています|しました|します).*?(?:\n|。)',
            r'^\s*\*+\s*.*?$',
            r'(?:^|\n)\s*\*+\s*.*?(?:\n|$)',
            r'---+',
            r'\*\*【.*?】\*\*',
            r'【.*?】',
            r'(?:^|\n)(?:説明|補足|注意|ポイント)[:：].*?(?:\n|$)',
            r'\*+',
        ]
        
        for pattern in unwanted_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE)
        
        sections = re.split(r'(\[(?:Verse|Chorus|Bridge|Intro|Outro)[^\]]*\])', cleaned)
        filtered_sections = []
        
        for i, section in enumerate(sections):
            if i % 2 == 0:
                lines = section.split('\n')
                lyrics_lines = []
                for line in lines:
                    line = line.strip()
                    if not line or (line and not any(word in line for word in ['といった', '組み込', '工夫', '意識', '表現して', 'ように'])):
                        lyrics_lines.append(line)
                filtered_sections.append('\n'.join(lyrics_lines))
            else:
                filtered_sections.append(section)
        
        cleaned = ''.join(filtered_sections)
        
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        
        cleaned = cleaned.strip()
        
        return cleaned


class OllamaLyricsGenerator(GeminiLyricsGenerator):
    """Ollama を使用した歌詞生成クラス

    ローカルで動作する Ollama サーバー (localhost:11434) に
    /api/chat エンドポイントでリクエストを送る。

    GeminiLyricsGenerator を継承し、リッチなプロンプト構築メソッド
    (_get_japanese_prompt, _get_english_prompt 等) をそのまま再利用する。
    generate_lyrics のみ Ollama API に差し替え。

    settings.py:
      OLLAMA_URL   = 'http://localhost:11434'   (デフォルト)
      OLLAMA_MODEL = 'llama3'                    (デフォルト)
      OLLAMA_TIMEOUT = 120                       (デフォルト)
    """

    def __init__(self):
        # GeminiLyricsGenerator.__init__ を呼ばず独自に初期化
        self.ollama_url = getattr(settings, 'OLLAMA_URL', 'http://localhost:11434')
        self.ollama_model = getattr(settings, 'OLLAMA_MODEL', 'llama3')
        self.timeout = getattr(settings, 'OLLAMA_TIMEOUT', 120)

    # --- Gemini 依存のプロパティをオーバーライド ---------------------------

    @property
    def model(self):
        """ダッシュボード互換 — Ollama が利用可能なら True 相当"""
        return self.is_available

    @property
    def is_available(self):
        """Ollama サーバーの稼働チェック"""
        try:
            resp = requests.get(
                f"{self.ollama_url}/api/tags",
                timeout=5,
            )
            if resp.status_code != 200:
                return False
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            # モデル名の完全一致 or "model:tag" 形式で先頭一致
            return any(
                m == self.ollama_model or m.startswith(f"{self.ollama_model}:")
                for m in models
            )
        except Exception:
            return False

    # --- 歌詞生成 --------------------------------------------------------

    def generate_lyrics(self, extracted_text, title="", genre="pop",
                        language_mode="japanese", custom_request=""):
        """Ollama /api/chat で歌詞を生成"""

        # キャッシュ
        cache_input = f"ollama|{self.ollama_model}|{extracted_text}|{genre}|{language_mode}|{custom_request}"
        cache_key = _get_cache_key(cache_input, 'lyrics')
        cached = _get_cached_response(cache_key)
        if cached:
            logger.info("Ollama: Returning cached lyrics")
            return cached

        # プロンプト構築 — 親クラス (GeminiLyricsGenerator) のメソッドを再利用
        if language_mode == "english_vocab":
            prompt = self._get_english_vocab_prompt(extracted_text, genre, custom_request)
        elif language_mode == "english":
            prompt = self._get_english_prompt(extracted_text, genre, custom_request)
        elif language_mode == "chinese":
            prompt = self._get_chinese_prompt(extracted_text, genre, custom_request)
        elif language_mode == "chinese_vocab":
            prompt = self._get_chinese_vocab_prompt(extracted_text, genre, custom_request)
        else:
            prompt = self._get_japanese_prompt(extracted_text, genre, custom_request)

        system_prompt = (
            "あなたは暗記学習用の歌詞を作成する専門AIです。"
            "与えられた指示に従い、セクションラベル付きの歌詞のみを出力してください。"
            "説明文やコメントは一切不要です。必ず日本語で出力してください。"
        )

        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 2048,
            },
        }

        try:
            import time as _time
            start = _time.time()

            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()
            raw_lyrics = data.get("message", {}).get("content", "").strip()
            if not raw_lyrics:
                raise Exception("Ollama: Empty response")

            lyrics = self._extract_clean_lyrics(raw_lyrics)
            elapsed = _time.time() - start

            _set_cached_response(cache_key, lyrics, ttl=3600)
            logger.info(
                f"Ollama: 歌詞生成成功 ({len(lyrics)} 文字, {elapsed:.1f}秒, "
                f"model={self.ollama_model})"
            )
            return lyrics

        except requests.exceptions.Timeout:
            logger.warning(f"Ollama: タイムアウト ({self.timeout}秒)")
            raise Exception("Ollama サーバーがタイムアウトしました")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Ollama: 接続エラー — {self.ollama_url}")
            raise Exception("Ollama サーバーに接続できません")
        except Exception as e:
            logger.error(f"Ollama: {e}")
            raise

    def generate_lyrics_from_images(self, images, title="", genre="pop",
                                    language_mode="japanese", custom_request="",
                                    extracted_text=""):
        """画像からの歌詞生成 — Ollama はテキスト専用のため Gemini にデリゲート"""
        logger.info("Ollama: 画像ベース生成はGeminiにデリゲート")
        gemini = GeminiLyricsGenerator()
        return gemini.generate_lyrics_from_images(
            images, title=title, genre=genre,
            language_mode=language_mode, custom_request=custom_request,
            extracted_text=extracted_text,
        )

    def convert_to_hiragana(self, lyrics):
        """ひらがな変換 — Gemini にデリゲート"""
        return convert_lyrics_to_hiragana_with_context(lyrics)





def convert_lyrics_to_hiragana_with_context(lyrics):
    """Gemini AIを使って文脈を考慮しながら歌詞をひらがなに変換

    漢字の読みを正確にするために、文脈を考慮して変換する。
    例: 「今日」→「きょう」vs「こんにち」、「明日」→「あした」vs「あす」
    """
    model = _get_gemini_model()

    if not model:
        # Geminiが使えない場合はそのまま返す
        logger.warning("Gemini not available for hiragana conversion")
        return lyrics

    try:
        prompt = f"""以下の日本語の歌詞を、漢字を全てひらがなに変換してください。

1. 文脈を考慮して、正しい読み方を選んでください
   - 「今日」→ 歌詞では通常「きょう」
   - 「明日」→ 歌詞では通常「あした」または「あす」（文脈による）
   - 「明後日」→ 歌詞では通常「あさって」
   - 「一人」→「ひとり」
   - 「二人」→「ふたり」
   - 「今」→「いま」
   - 「何」→ 「なに」または「なん」（文脈による）
   - 「風」→「かぜ」
   - 「空」→「そら」
   - 「海」→「うみ」
   - 「心」→「こころ」
   - 「夢」→「ゆめ」
   - 「愛」→「あい」
   - 「光」→「ひかり」
   - 「影」→「かげ」
   - 「声」→「こえ」
   - 「道」→「みち」
   - 「日」→ 日付は「にち」、日の光は「ひ」
   - 「私」→「わたし」
   - 「君」→「きみ」
   - 「僕」→「ぼく」

2. 外国の地名・国名は現代の一般的な読み方を使用（漢文読みにしない！）
   - 「台北」→「たいぺい」（×「だいほく」は不可）
   - 「台湾」→「たいわん」
   - 「北京」→「ぺきん」（×「ほくけい」は不可）
   - 「上海」→「しゃんはい」
   - 「南京」→「なんきん」
   - 「香港」→「ほんこん」
   - 「韓国」→「かんこく」
   - 「朝鮮」→「ちょうせん」
   - 外国地名は日本語として定着している現代の読みを優先すること

3. 数字は日本語の読みに変換
   - 「1」→「いち」、「2」→「に」、「10」→「じゅう」、「100」→「ひゃく」

4. 化学式・元素記号はアルファベットを1文字ずつ読む
   - 「Na」→「えぬえー」（ナトリウムが後に続く場合：「えぬえー ナトリウム」）
   - 「Cl」→「しーえる」
   - 「NaCl」→「えぬえー しーえる」
   - 「CO2」→「しーおーつー」
   - 「H2O」→「えいちつーおー」
   - 「O2」→「おーつー」
   - 「Fe」→「えふいー」
   - 「Ca」→「しーえー」
   - 「Mg」→「えむじー」
   - 「Cu」→「しーゆー」
   - 「NaOH」→「えぬえー おーえいち」
   - 「HCl」→「えいちしーえる」
   - 「C6H12O6」→「しーろく えいちじゅうに おーろく」
   - 化学式中の数字は日本語読み（「2」→「つー」ではなく文脈による：化学式では「つー」、年号では「に」）
   - 元素記号の後にカタカナの元素名が続く場合、両方そのまま読む
     例：「Na ナトリウム」→「えぬえー ナトリウム」

5. 助詞の発音変換（重要！歌の発音に合わせる）
   - 助詞の「は」→「わ」に変換（例：「私は」→「わたしわ」、「それは」→「それわ」）
   - 助詞の「へ」→「え」に変換（例：「海へ」→「うみえ」、「空へ」→「そらえ」）
   - 助詞の「を」→「お」に変換（例：「夢を」→「ゆめお」）
   ※ 助詞以外の「は」「へ」「を」はそのまま（例：「はな」→「はな」、「へや」→「へや」）

6. セクションラベル（[Verse], [Chorus], [Bridge]など）はそのまま保持

7. 英語の一般的な単語はそのまま保持（化学式・元素記号は上記ルールで変換）

8. 改行や空行は忠実に保持

9. カタカナはそのまま保持

10. 出力は変換後の歌詞のみ（説明や前置きは不要）

【変換する歌詞】
{lyrics}

【出力】（変換後の歌詞のみを出力）"""

        response = model.generate_content(prompt, safety_settings=GEMINI_SAFETY_SETTINGS)

        text = _safe_get_response_text(response)
        if text:
            converted = text.strip()
            # 余計な説明を除去
            if converted.startswith('```'):
                lines = converted.split('\n')
                converted = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])

            logger.info(f"Gemini hiragana conversion successful: {len(lyrics)} -> {len(converted)} chars")
            return converted
        else:
            logger.warning("Gemini returned empty response for hiragana conversion")
            return lyrics

    except Exception as e:
        logger.error(f"Gemini hiragana conversion error: {e}")
        return lyrics


class GeminiFlashcardExtractor:
    """Gemini を使用してテキスト/画像から重要語句と定義を抽出するクラス"""
    
    def __init__(self):
        self.model = _get_gemini_model()
    
    def extract_terms_from_text(self, text):
        """テキストから重要語句と定義を抽出
        
        OCRで抽出されたテキスト（【】マーク付き）を解析し、
        学習用のterm-definitionペアを生成する。
        
        最適化:
        - 【】マークの語句は正規表現で事前抽出（LLMの見落とし防止）
        - 同一テキストへのレスポンスをキャッシュ（API呼び出し削減）
        
        Args:
            text: OCR抽出テキスト（【重要語句】マーク付きの場合あり）
            
        Returns:
            list[dict]: [{"term": "語句", "definition": "説明"}, ...]
        """
        if not self.model:
            logger.error("GeminiFlashcardExtractor: Gemini API not configured")
            return []
        
        if not text or not text.strip():
            return []
        
        # キャッシュをチェック
        cache_key = _get_cache_key(text, 'flashcard')
        cached = _get_cached_response(cache_key)
        if cached:
            return cached
        
        try:
            # 【】マークの語句を正規表現で事前抽出（LLMに頼らず確実に取得）
            pre_extracted_terms = extract_bracketed_terms(text)
            
            # 事前抽出した語句をプロンプトに明示的に含める
            pre_extracted_section = ""
            if pre_extracted_terms:
                terms_list = "、".join(pre_extracted_terms)
                pre_extracted_section = f"""
■ 必須キーワード（以下の語句は必ずimportance="high"で含めること）:
{terms_list}
"""
            
            prompt = f"""以下のテキストから、学習に重要な語句（キーワード）とその意味・定義のペアを抽出してください。
{pre_extracted_section}
ルール:
・上記の「必須キーワード」は必ず全て含め、importance を "high" にする
・それ以外にも、テスト・試験に出そうな重要語句を選ぶ（importance は "normal"）
・各キーワードに対して、簡潔でわかりやすい定義・説明を付ける
・定義はテキストの文脈に基づいて書くが、「テキストでは」「画像では」「本文では」のような出典への言及は絶対にしない
・定義は一般的な知識として完結する文で書く
・最低5個、最大20個のペアを抽出する
・同じ語句の重複は避ける

出力形式（JSON配列のみ出力。他の文章は一切書かないこと）:
[
  {{"term": "キーワード1", "definition": "定義・説明1", "importance": "high"}},
  {{"term": "キーワード2", "definition": "定義・説明2", "importance": "normal"}}
]

テキスト:
{text}"""
            
            max_retries = 3
            last_error = None
            for attempt in range(max_retries):
                try:
                    response = self.model.generate_content(
                        prompt,
                        safety_settings=GEMINI_SAFETY_SETTINGS,
                    )
                    raw_text = _safe_get_response_text(response)
                    if raw_text:
                        terms = self._parse_terms_json(raw_text)
                        if terms:
                            # 事前抽出した語句がすべて含まれているか確認
                            extracted_term_names = {t['term'] for t in terms}
                            for pre_term in pre_extracted_terms:
                                if pre_term not in extracted_term_names:
                                    # LLMが見落とした語句を追加（定義は後でユーザーが編集可能）
                                    terms.append({
                                        'term': pre_term,
                                        'definition': '（定義を追加してください）',
                                        'importance': 'high',
                                    })
                                    logger.info(f"GeminiFlashcardExtractor: Added missed term: {pre_term}")
                            
                            logger.info(f"GeminiFlashcardExtractor: Extracted {len(terms)} terms")
                            # キャッシュに保存
                            _set_cached_response(cache_key, terms)
                            return terms
                    last_error = "Empty or unparseable response"
                except Exception as api_error:
                    last_error = str(api_error)
                    logger.warning(f"GeminiFlashcardExtractor: API error attempt {attempt + 1}: {api_error}")
                
                if attempt < max_retries - 1:
                    import time as _time
                    _time.sleep(2 * (attempt + 1))
            
            logger.error(f"GeminiFlashcardExtractor: All attempts failed. Last error: {last_error}")
            return []
            
        except Exception as e:
            logger.error(f"GeminiFlashcardExtractor: Error: {e}", exc_info=True)
            return []
    
    def extract_terms_from_image(self, image_file):
        """画像から直接重要語句と定義を抽出
        
        画像をGeminiに渡し、OCR+キーワード抽出を一括で行う。
        
        Args:
            image_file: 画像ファイル（パス、FieldFile、またはfile-likeオブジェクト）
            
        Returns:
            list[dict]: [{"term": "語句", "definition": "説明"}, ...]
        """
        if not self.model:
            logger.error("GeminiFlashcardExtractor: Gemini API not configured")
            return []
        
        try:
            import io
            
            # 画像を読み込む
            img = None
            if isinstance(image_file, str):
                img = Image.open(image_file)
            elif hasattr(image_file, 'path'):
                try:
                    img = Image.open(image_file.path)
                except (FileNotFoundError, OSError):
                    if hasattr(image_file, 'open'):
                        image_file.open('rb')
                        img = Image.open(image_file)
                    elif hasattr(image_file, 'read'):
                        image_file.seek(0)
                        img = Image.open(image_file)
            elif hasattr(image_file, 'read'):
                img = Image.open(image_file)
            
            if img is None:
                logger.error("GeminiFlashcardExtractor: Failed to open image")
                return []
            
            # MPO形式対応
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', quality=95)
            img_buffer.seek(0)
            img = Image.open(img_buffer)
            
            prompt = """この画像に含まれるテキストを読み取り、学習に重要な語句（キーワード）とその意味・定義のペアを抽出してください。

ルール:
・下線・太字・マーカー・色付き（赤字・青字等）で強調されている語句は必ずキーワードとして含め、importance を "high" にする（ただし全体が同じ色なら強調ではない）
・強調されていなくても、テスト・試験に出そうな重要語句を選ぶ（importance は "normal"）
・各キーワードに対して、簡潔でわかりやすい定義・説明を付ける
・「画像では」「テキストでは」「本文では」「この図では」のような出典への言及は絶対にしない
・定義は一般的な知識として完結する文で書く
・最低5個、最大20個のペアを抽出する
・同じ語句の重複は避ける

出力形式（JSON配列のみ出力。他の文章は一切書かないこと）:
[
  {"term": "キーワード1", "definition": "定義・説明1", "importance": "high"},
  {"term": "キーワード2", "definition": "定義・説明2", "importance": "normal"}
]"""
            
            max_retries = 3
            last_error = None
            for attempt in range(max_retries):
                try:
                    response = self.model.generate_content(
                        [prompt, img],
                        safety_settings=GEMINI_SAFETY_SETTINGS,
                    )
                    raw_text = _safe_get_response_text(response)
                    if raw_text:
                        terms = self._parse_terms_json(raw_text)
                        if terms:
                            logger.info(f"GeminiFlashcardExtractor: Extracted {len(terms)} terms from image")
                            return terms
                    last_error = "Empty or unparseable response"
                except Exception as api_error:
                    last_error = str(api_error)
                    logger.warning(f"GeminiFlashcardExtractor: API error attempt {attempt + 1}: {api_error}")
                
                if attempt < max_retries - 1:
                    import time as _time
                    _time.sleep(2 * (attempt + 1))
            
            logger.error(f"GeminiFlashcardExtractor: All image attempts failed. Last error: {last_error}")
            return []
            
        except Exception as e:
            logger.error(f"GeminiFlashcardExtractor: Image error: {e}", exc_info=True)
            return []
    
    def _parse_terms_json(self, raw_text):
        """Geminiの応答からJSON配列をパース
        
        ```json ... ``` のコードブロックにも対応。
        """
        import json
        
        text = raw_text.strip()
        
        # コードブロックを除去
        if '```' in text:
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if match:
                text = match.group(1).strip()
        
        try:
            data = json.loads(text)
            if isinstance(data, list):
                # 各要素にtermとdefinitionがあるか検証
                valid_terms = []
                for item in data:
                    if isinstance(item, dict) and 'term' in item and 'definition' in item:
                        term = str(item['term']).strip()
                        definition = str(item['definition']).strip()
                        importance = str(item.get('importance', 'normal')).strip().lower()
                        if importance not in ('high', 'normal'):
                            importance = 'normal'
                        if term and definition:
                            valid_terms.append({
                                'term': term,
                                'definition': definition,
                                'importance': importance,
                            })
                return valid_terms
        except json.JSONDecodeError:
            logger.warning(f"GeminiFlashcardExtractor: JSON parse failed: {text[:200]}")
        
        return []
