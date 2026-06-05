"""Ollama 歌詞生成モジュール"""
import logging
import requests

from django.conf import settings

from .cache import _get_cache_key, _get_cached_response, _set_cached_response
from .gemini_lyrics import GeminiLyricsGenerator
from .hiragana import convert_lyrics_to_hiragana_with_context

logger = logging.getLogger(__name__)


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
