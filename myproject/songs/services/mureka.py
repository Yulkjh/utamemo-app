"""Mureka AI 楽曲生成クラス"""
import logging
import re
import time
import json
import random

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


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
        """歌詞から楽曲を生成（Mureka API使用）"""
        if not self.use_real_api or not self.api_key:
            raise Exception("Mureka API is not configured. Please set MUREKA_API_KEY and USE_MUREKA_API=True")
        return self._generate_with_mureka_api(lyrics, title, genre, vocal_style, model, music_prompt)

    def _generate_with_mureka_api(self, lyrics, title, genre, vocal_style, model="mureka-v8", music_prompt=""):
        """Mureka APIを使用して楽曲を生成"""
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        logger.info("Preparing to send song generation request...")

        # 「auto」または空の場合はジャンルを指定しない
        is_auto_genre = not genre or genre.strip() == "" or genre.strip().lower() == "auto" or genre.strip() in ["おまかせ", "自动"]
        if is_auto_genre:
            genre = ""

        # 歌詞の長さを制限
        max_lyrics_length = 2500
        if len(lyrics) > max_lyrics_length:
            logger.info(f"Lyrics too long ({len(lyrics)} chars), truncating smartly...")
            lyrics = self._truncate_lyrics_by_section(lyrics, max_lyrics_length)
            logger.info(f"Truncated lyrics to {len(lyrics)} chars")

        if len(lyrics.strip()) < 50:
            raise Exception("Lyrics too short for song generation (minimum 50 characters)")

        # モデルバージョンの検証
        if model != 'mureka-v8':
            logger.warning(f"Invalid model '{model}', defaulting to mureka-v8")
            model = 'mureka-v8'

        api_model = 'auto'
        logger.info(f"Model mapping: DB='{model}' → API='{api_model}'")

        # ジャンルを英語に変換
        GENRE_TO_ENGLISH = {
            'ポップ': 'Pop', 'ロック': 'Rock', 'バラード': 'Ballad',
            'ラップ': 'Rap', '電子音楽': 'Electronic', 'クラシック': 'Classical',
            'ジャズ': 'Jazz', 'おまかせ': '',
            '流行': 'Pop', '摇滚': 'Rock', '抒情': 'Ballad',
            '说唱': 'Rap', '电子': 'Electronic', '古典': 'Classical', '爵士': 'Jazz',
            '自动': '',
            'Balada': 'Ballad', 'Electrónica': 'Electronic', 'Clásica': 'Classical',
            'Ballade': 'Ballad', 'Elektronisch': 'Electronic', 'Klassik': 'Classical',
            'Eletrônica': 'Electronic', 'Clássica': 'Classical',
        }
        genre_en = GENRE_TO_ENGLISH.get(genre, genre)

        # music_prompt を英語に翻訳
        music_prompt_en = ''
        if music_prompt and music_prompt.strip():
            music_prompt_en = self._translate_prompt_to_english(music_prompt.strip())

        # プロンプトを組み立て
        prompt_parts = []
        if genre_en:
            prompt_parts.append(genre_en)

        # ボーカルスタイルの処理
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

        FIXED_VOCAL_PROMPTS = {
            'vocaloid_female': 'high-pitched cute synthesized female vocal, Vocaloid-style electronic voice, bright and airy digital vocal tone',
            'vocaloid_male': 'synthesized male vocal, Vocaloid-style electronic voice, clear digital vocal tone with auto-tune effect',
            'duet': 'male and female duet vocal, harmonizing together, call and response singing',
            'choir': 'choral ensemble vocal, rich harmonies, layered group singing',
            'whisper': 'soft whispery vocal, intimate and breathy, ASMR-like gentle singing',
            'child': 'young child vocal, innocent and bright, youthful pure singing voice',
        }
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
            logger.info("Voice description detected in music_prompt, skipping random vocal traits")
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
        full_prompt += ", short intro under 10 seconds, short outro under 10 seconds, start singing quickly, end shortly after vocals finish, no long instrumental sections"

        payload = {
            "lyrics": lyrics,
            "model": api_model,
            "prompt": full_prompt
        }

        logger.info(f"Using Mureka model: {api_model} (from DB: {model})")
        logger.info(f"Music prompt: {payload['prompt']}")
        logger.info(f"Lyrics length: {len(lyrics)} chars")

        payload_log = {k: (v[:100] + '...' if k == 'lyrics' and len(v) > 100 else v) for k, v in payload.items()}
        logger.info(f"[MUREKA] Full payload: {json.dumps(payload_log, ensure_ascii=False)}")

        max_retries = 5
        base_wait_time = 10
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
                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                        continue
                    else:
                        error_msg = f"Mureka API rate limit exceeded after {max_retries} attempts. しばらく待ってから再試行してください。"
                        raise Exception(error_msg)

                elif response.status_code == 400:
                    error_msg = f"Mureka API bad request (400): {response.text}"
                    raise Exception(error_msg)

                elif response.status_code >= 500:
                    if attempt < max_retries - 1:
                        wait_time = base_wait_time * (attempt + 1)
                        logger.info(f"Server error ({response.status_code}), retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise Exception(f"Mureka API server error: {response.status_code}")

                else:
                    error_msg = f"Mureka API error: {response.status_code} - {response.text}"
                    raise Exception(error_msg)

            except requests.exceptions.Timeout:
                logger.info(f"Mureka API timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(base_wait_time)
                    continue
                else:
                    raise Exception("Mureka API timeout after all retries")

            except requests.exceptions.ConnectionError as e:
                logger.info(f"Mureka API connection error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(base_wait_time * (2 ** attempt))
                    continue
                else:
                    raise Exception(f"Mureka API connection failed: {e}")

            except requests.exceptions.RequestException as e:
                logger.info(f"Mureka API request error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(base_wait_time * (2 ** attempt))
                    continue
                else:
                    raise

    def _translate_prompt_to_english(self, text):
        """音楽スタイルプロンプトを英語に翻訳する（辞書ベース、LLM不使用）"""
        # ASCII文字が大部分なら既に英語と判定
        ascii_count = sum(1 for c in text if ord(c) < 128)
        if len(text) > 0 and ascii_count / len(text) > 0.8:
            return text

        MUSIC_PROMPT_DICT = {
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
            '流行': 'pop', '摇滚': 'rock', '抒情': 'ballad', '说唱': 'rap',
            '电子': 'electronic', '古典': 'classical', '爵士': 'jazz',
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
            '女性ボーカル': 'female vocal', '男性ボーカル': 'male vocal',
            '高い声': 'high-pitched voice', '低い声': 'low-pitched voice',
            'ハスキー': 'husky', 'ウィスパー': 'whisper',
            'ファルセット': 'falsetto', 'シャウト': 'shout',
            'ハモり': 'harmony', 'コーラス': 'chorus',
            'ラップ調': 'rap style', '語り': 'spoken word',
            'ピアノ': 'piano', 'ギター': 'guitar', 'ドラム': 'drums',
            'ベース': 'bass', 'バイオリン': 'violin', 'チェロ': 'cello',
            'フルート': 'flute', 'サックス': 'saxophone', 'トランペット': 'trumpet',
            'シンセサイザー': 'synthesizer', 'シンセ': 'synth',
            'ストリングス': 'strings', 'ブラス': 'brass',
            'アコギ': 'acoustic guitar', 'エレキ': 'electric guitar',
            'ウクレレ': 'ukulele', 'ハープ': 'harp', 'オルガン': 'organ',
            'マリンバ': 'marimba', '三味線': 'shamisen', '琴': 'koto',
            '和楽器': 'Japanese traditional instruments', '和風': 'Japanese style',
            '風': ' style', '調': ' style', '系': ' style', '的': '',
            '感じ': ' feel', 'っぽい': '-like',
        }

        result = text
        for ja, en in sorted(MUSIC_PROMPT_DICT.items(), key=lambda x: len(x[0]), reverse=True):
            result = result.replace(ja, f' {en} ')

        result = re.sub(r'[のでをがはにとも、。]+', ' ', result)
        result = re.sub(r'\s+', ' ', result).strip()
        if not result:
            return text

        logger.info(f"Prompt translated (dict): '{text}' → '{result}'")
        return result

    def _truncate_lyrics_by_section(self, lyrics, max_length):
        """歌詞をセクション単位で切り詰める"""
        if len(lyrics) <= max_length:
            return lyrics

        section_pattern = r'\[(?:Verse|Chorus|Bridge|Intro|Outro)[^\]]*\]'
        section_matches = list(re.finditer(section_pattern, lyrics))

        if not section_matches:
            lines = lyrics.split('\n')
            result = []
            current_length = 0
            for line in lines:
                if current_length + len(line) + 1 > max_length:
                    break
                result.append(line)
                current_length += len(line) + 1
            return '\n'.join(result)

        truncated = lyrics
        for i in range(len(section_matches) - 1, -1, -1):
            section_start = section_matches[i].start()
            if i + 1 < len(section_matches):
                section_end = section_matches[i + 1].start()
            else:
                section_end = len(lyrics)

            if section_end <= max_length:
                truncated = lyrics[:section_end].rstrip()
                break
            elif section_start <= max_length:
                truncated = lyrics[:section_start].rstrip()
                break

        if len(truncated) < 200 and len(lyrics) > 200:
            truncated = lyrics[:max_length]

        return truncated

    def _cancel_running_tasks(self, headers):
        """実行中のタスクをキャンセル"""
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
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        max_attempts = 90
        attempt = 0
        consecutive_errors = 0
        max_consecutive_errors = 5

        while attempt < max_attempts:
            try:
                query_url = f"{self.base_url}/v1/song/query/{task_id}"
                logger.info(f"Checking task status: {query_url} (Attempt {attempt + 1}/{max_attempts})")

                response = requests.get(query_url, headers=headers, timeout=30)

                if response.status_code == 200:
                    consecutive_errors = 0
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

                            choice_keys = list(choice.keys())
                            logger.info(f"[MUREKA] Choice fields: {choice_keys}")
                            for key in choice_keys:
                                val = choice[key]
                                val_type = type(val).__name__
                                val_preview = str(val)[:200] if val else 'None'
                                logger.info(f"[MUREKA] choice['{key}'] ({val_type}): {val_preview}")
                            result_keys = [k for k in result.keys() if k not in ('choices', 'status')]
                            if result_keys:
                                logger.info(f"[MUREKA] Additional result fields: {result_keys}")
                                for key in result_keys:
                                    val = result[key]
                                    val_preview = str(val)[:200] if val else 'None'
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
                            raise Exception("Mureka API returned no song choices")

                    elif status in ['failed', 'error', 'cancelled']:
                        error_msg = result.get('error', result.get('message', 'Unknown error'))
                        raise Exception(f"Mureka generation failed: {error_msg}")

                    else:
                        if attempt < 10:
                            wait_time = 3
                        elif attempt < 30:
                            wait_time = 4
                        else:
                            wait_time = 5
                        logger.info(f"Task still {status}, waiting {wait_time}s...")
                        time.sleep(wait_time)
                        attempt += 1

                elif response.status_code == 404:
                    raise Exception(f"Mureka task not found: {task_id}")

                else:
                    consecutive_errors += 1
                    logger.info(f"Query error: {response.status_code} (consecutive: {consecutive_errors})")
                    if consecutive_errors >= max_consecutive_errors:
                        raise Exception("Too many consecutive errors checking task status")
                    time.sleep(5)
                    attempt += 1

            except requests.exceptions.Timeout:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    raise Exception("Too many timeouts checking task status")
                time.sleep(5)
                attempt += 1

            except requests.exceptions.RequestException as e:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    raise Exception(f"Network error checking task status: {e}")
                time.sleep(5)
                attempt += 1

            except Exception as e:
                if "failed" in str(e).lower() or "error" in str(e).lower():
                    raise
                logger.info(f"Error querying task: {e}")
                raise

        logger.error(f"Timeout waiting for task {task_id}")
        raise Exception(f"Timeout waiting for Mureka task after {max_attempts * 4} seconds")

    def describe_song(self, audio_url):
        """Mureka APIの楽曲分析エンドポイントを呼び出す"""
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
                return {'status': 200, 'keys': list(result.keys()), 'data': result}
            else:
                return {'status': resp.status_code, 'response': resp.text[:1000]}
        except Exception as e:
            logger.warning(f"[MUREKA] describe error: {e}")
            return {'error': str(e)}

    def list_api_endpoints(self):
        """利用可能なMureka APIエンドポイントを調査"""
        if not self.use_real_api or not self.api_key:
            return None

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

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
                results[endpoint] = {'status': response.status_code, 'response': response.text[:200]}
                logger.info(f"[MUREKA] {method} {endpoint} → {response.status_code}: {response.text[:100]}")
            except Exception as e:
                results[endpoint] = {'status': 'error', 'response': str(e)[:100]}

        return results
