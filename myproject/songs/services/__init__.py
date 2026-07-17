# songs/services/ — AI サービスモジュール
#
# ai_services.py (2,966行) を機能別に分割。
# 後方互換性のため ai_services.py からも re-export される。

from .cache import (
    GEMINI_CACHE_TTL,
    _get_cache_key,
    _get_cached_response,
    _set_cached_response,
)
from .text_processing import (
    extract_bracketed_terms,
    extract_importance_keywords,
    remove_circled_numbers,
    detect_lyrics_language,
    GEMINI_SAFETY_SETTINGS,
    _safe_get_response_text,
    _get_gemini_model,
    _normalize_keyword_term,
    _build_importance_instruction_block,
    _is_explosive_lyrics_mode,
)
from .song_generation import (
    SUPPORTED_SONG_PROVIDERS,
    get_default_song_generation_model,
    get_default_song_generation_provider,
    get_song_generator,
    normalize_song_provider,
)
from .lyria import LyriaAIGenerator
from .mureka import MurekaAIGenerator
from .pdf_extractor import PDFTextExtractor
from .gemini_ocr import GeminiOCR
from .gemini_lyrics import GeminiLyricsGenerator
from .ollama import OllamaLyricsGenerator
from .local_llm import LocalLLMLyricsGenerator, CloudLLMLyricsGenerator, get_lyrics_generator
from .hiragana import convert_lyrics_to_hiragana_with_context
from .flashcard_extractor import GeminiFlashcardExtractor

__all__ = [
    'GEMINI_CACHE_TTL',
    '_get_cache_key',
    '_get_cached_response',
    '_set_cached_response',
    'extract_bracketed_terms',
    'extract_importance_keywords',
    'remove_circled_numbers',
    'detect_lyrics_language',
    'GEMINI_SAFETY_SETTINGS',
    '_safe_get_response_text',
    '_get_gemini_model',
    '_normalize_keyword_term',
    '_build_importance_instruction_block',
    '_is_explosive_lyrics_mode',
    'SUPPORTED_SONG_PROVIDERS',
    'get_default_song_generation_model',
    'get_default_song_generation_provider',
    'get_song_generator',
    'normalize_song_provider',
    'LyriaAIGenerator',
    'MurekaAIGenerator',
    'PDFTextExtractor',
    'GeminiOCR',
    'GeminiLyricsGenerator',
    'OllamaLyricsGenerator',
    'LocalLLMLyricsGenerator',
    'CloudLLMLyricsGenerator',
    'get_lyrics_generator',
    'convert_lyrics_to_hiragana_with_context',
    'GeminiFlashcardExtractor',
]
