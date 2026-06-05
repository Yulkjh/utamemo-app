"""APIレスポンスキャッシュ"""
import hashlib
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

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
