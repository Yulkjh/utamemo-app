"""ローカル / クラウド LLM 歌詞生成モジュール"""
import logging
import requests

from django.conf import settings

from .cache import _get_cache_key, _get_cached_response, _set_cached_response
from .hiragana import convert_lyrics_to_hiragana_with_context

logger = logging.getLogger(__name__)


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
        """画像からの歌詞生成 — ローカルLLMは画像処理非対応のためGeminiにデリゲート"""
        from .gemini_lyrics import GeminiLyricsGenerator
        logger.info("LocalLLM: 画像ベース生成はGeminiにデリゲート")
        gemini = GeminiLyricsGenerator()
        return gemini.generate_lyrics_from_images(
            images, title=title, genre=genre,
            language_mode=language_mode, custom_request=custom_request,
            extracted_text=extracted_text,
        )

    def convert_to_hiragana(self, lyrics):
        """歌詞の漢字をひらがなに変換 — Geminiにデリゲート"""
        return convert_lyrics_to_hiragana_with_context(lyrics)

    @property
    def model(self):
        """GeminiLyricsGeneratorとの互換性のため (ダッシュボード表示用)"""
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
        from .gemini_lyrics import GeminiLyricsGenerator
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
    from .gemini_lyrics import GeminiLyricsGenerator
    from .ollama import OllamaLyricsGenerator

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
