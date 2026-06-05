"""テキスト処理ユーティリティ・Gemini共通ヘルパー"""
import re
import logging
from collections import Counter

from django.conf import settings
import google.generativeai as genai

logger = logging.getLogger(__name__)


# ========================================
# フラッシュカード前処理（【】マーク抽出）
# ========================================
def extract_bracketed_terms(text):
    """テキストから【】で囲まれた語句を抽出（LLM不使用）

    OCRで抽出されたテキストの【重要語句】マークを正規表現で確実に抽出。
    LLMに頼らず、ローカルで処理することで見落としを防ぐ。

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


# ========================================
# Gemini APIグローバル設定
# ========================================
_GEMINI_CONFIGURED = False
_GEMINI_MODEL = None


def remove_circled_numbers(text):
    """丸数字・囲み数字・特殊番号記号を除去する

    教材画像に含まれる ❶❷❸ ①②③ ⑴⑵⑶ Ⅰ Ⅱ Ⅲ 等を歌詞から削除。
    除去後に残る余分なスペースも整理する。
    """
    if not text:
        return text

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

    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = re.sub(r'  +', ' ', line)
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
        if response.text:
            return response.text.strip()
    except (ValueError, AttributeError):
        pass

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
    それ以外の言語はすべてそのまま送信する。

    Returns:
        'ja' - 日本語（ひらがな・カタカナを含む → ひらがな変換する）
        'other' - 日本語以外（そのまま送信）
    """
    if not lyrics:
        return 'ja'

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

    if japanese_kana > 0:
        return 'ja'

    return 'other'
