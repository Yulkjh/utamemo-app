import os
import requests
from django.conf import settings
import time
import google.generativeai as genai
from PIL import Image
import re
import logging

# ロガー設定
logger = logging.getLogger(__name__)

# fugashiはオプショナル（ひらがな変換に使用）
try:
    from fugashi import Tagger
    FUGASHI_AVAILABLE = True
except ImportError:
    FUGASHI_AVAILABLE = False
    logger.warning("fugashiがインストールされていません。ひらがな変換が制限されます。")

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


def generate_lrc_timestamps(lyrics_text, duration_seconds):
    """
    Gemini AIを使って歌詞にタイムスタンプを推定し、LRC形式で返す
    
    Args:
        lyrics_text: 歌詞テキスト
        duration_seconds: 曲の長さ（秒）
    
    Returns:
        str: LRC形式のタイムスタンプ付き歌詞、失敗時はNone
    """
    model = _get_gemini_model()
    if not model:
        logger.warning("Gemini APIが利用できないため、LRC生成をスキップします")
        return None
    
    if not lyrics_text or not duration_seconds:
        return None
    
    # 丸数字を除去してからLRC生成
    lyrics_text = remove_circled_numbers(lyrics_text)
    
    # 歌詞の行を取得（空行やセクションラベルも含む）
    lines = lyrics_text.strip().split('\n')
    non_empty_lines = [l for l in lines if l.strip()]
    
    if len(non_empty_lines) == 0:
        return None
    
    minutes = int(duration_seconds) // 60
    seconds = int(duration_seconds) % 60
    
    prompt = f"""あなたは音楽のタイミング専門家です。以下の歌詞と曲の長さから、各行が歌われるタイミングをLRC形式で推定してください。

【曲の長さ】{minutes}分{seconds}秒（{int(duration_seconds)}秒）

【歌詞】
{lyrics_text}

【ルール】
1. LRC形式: [MM:SS.xx]歌詞テキスト （xxは100分の1秒）
2. 一般的なポップス/ロックの曲構成を想定してください
3. イントロ（曲の冒頭）は通常5〜15秒程度あります
4. 間奏（セクション間）は通常5〜10秒あります
5. アウトロ（曲の終わり）は通常5〜15秒程度あります
6. 空行やセクションラベル（[Verse]、[Chorus]など）は含めないでください
7. 歌詞の行のみにタイムスタンプを付けてください
8. 曲の長さ内に全ての行が収まるようにしてください
9. LRC行のみを出力し、他の説明は一切不要です

【出力例】
[00:12.00]最初の歌詞行
[00:16.50]2番目の歌詞行
[00:21.00]3番目の歌詞行
"""
    
    try:
        response = model.generate_content(prompt)
        if response and response.text:
            lrc_text = response.text.strip()
            
            # LRC行のみを抽出（不要なテキストを除去）
            lrc_lines = []
            for line in lrc_text.split('\n'):
                line = line.strip()
                # [MM:SS.xx] 形式の行のみを抽出
                if re.match(r'\[\d{2}:\d{2}\.\d{2}\]', line):
                    lrc_lines.append(line)
            
            if lrc_lines:
                result = '\n'.join(lrc_lines)
                logger.info(f"LRC生成成功: {len(lrc_lines)}行")
                return result
            else:
                logger.warning("LRC生成: 有効なLRC行が見つかりませんでした")
                return None
        
        return None
    except Exception as e:
        logger.error(f"LRC生成エラー: {e}")
        return None


class MurekaAIGenerator:
    """Mureka AI を使用した楽曲生成クラス"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'MUREKA_API_KEY', None)
        self.base_url = getattr(settings, 'MUREKA_API_URL', 'https://api.mureka.ai')
        self.use_real_api = getattr(settings, 'USE_MUREKA_API', False)
        
        if self.use_real_api and self.api_key:
            print("MurekaAIGenerator: Using Mureka API for song generation.")
        else:
            print("MurekaAIGenerator: API key not set or disabled.")
    
    def generate_song(self, lyrics, title="", genre="pop", vocal_style="female", model="mureka-v8", music_prompt="", reference_song=""):
        """歌詞から楽曲を生成（Mureka API使用）
        
        Args:
            lyrics: 歌詞テキスト
            title: 楽曲タイトル
            genre: ジャンル
            vocal_style: ボーカルスタイル (female/male)
            model: Murekaモデルバージョン (mureka-v8, mureka-o2, mureka-7.6)
            music_prompt: ユーザー指定の音楽スタイルプロンプト
            reference_song: リファレンス曲名（例：YOASOBIの夜に駆ける）
        """
        
        if not self.use_real_api or not self.api_key:
            raise Exception("Mureka API is not configured. Please set MUREKA_API_KEY and USE_MUREKA_API=True")
        
        return self._generate_with_mureka_api(lyrics, title, genre, vocal_style, model, music_prompt, reference_song)
    
    def _generate_with_mureka_api(self, lyrics, title, genre, vocal_style, model="mureka-v8", music_prompt="", reference_song=""):
        """Mureka APIを使用して楽曲を生成
        
        Args:
            lyrics: 歌詞テキスト
            title: 楽曲タイトル  
            genre: ジャンル
            vocal_style: ボーカルスタイル
            model: Murekaモデル (mureka-v8, mureka-o2, mureka-7.6)
            music_prompt: ユーザー指定の音楽スタイルプロンプト
            reference_song: リファレンス曲名
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
            print(f"Lyrics too long ({len(lyrics)} chars), truncating smartly...")
            # セクション単位で切り詰める（[Verse], [Chorus]などの区切りを維持）
            lyrics = self._truncate_lyrics_by_section(lyrics, max_lyrics_length)
            print(f"Truncated lyrics to {len(lyrics)} chars")
        
        # 歌詞が短すぎる場合のチェック
        if len(lyrics.strip()) < 50:
            raise Exception("Lyrics too short for song generation (minimum 50 characters)")
        
        # モデルバージョンの検証と設定
        # DB/UI上の値 → 実際のMureka APIモデル名にマッピング
        # Mureka APIの有効なモデル名: "auto", "mureka-6", "mureka-5.5" 等
        # "auto" は最新モデル（現在はV8）を自動選択する
        MODEL_API_MAPPING = {
            'mureka-v8': 'auto',       # V8 = 最新モデル → autoで自動選択
            'mureka-o2': 'mureka-o2',   # O2はそのまま送信
            'mureka-7.6': 'mureka-7.6', # 7.6はそのまま送信
        }
        valid_models = list(MODEL_API_MAPPING.keys())
        if model not in valid_models:
            logger.warning(f"Invalid model '{model}', defaulting to auto (V8)")
            model = 'mureka-v8'
        
        # APIに送信するモデル名に変換
        api_model = MODEL_API_MAPPING.get(model, 'auto')
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
        prompt_parts.append(vocal_style)
        if music_prompt_en:
            prompt_parts.append(music_prompt_en)
        full_prompt = ", ".join(prompt_parts)
        
        # リファレンス曲をプロンプトに追加（英語で）
        if reference_song and reference_song.strip():
            ref = reference_song.strip()
            # URLでない場合はプロンプトに追加
            if not ref.startswith('http://') and not ref.startswith('https://'):
                full_prompt = f"{full_prompt}, in the style of {ref}"
                logger.info(f"Reference song added to prompt: {ref}")
        
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
        print(f"[MUREKA] Full payload: {json.dumps(payload_log, ensure_ascii=False)}")
        
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
                
                print(f"Response status: {response.status_code}")
                print(f"Response text: {response.text[:500]}")
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"Mureka API response: {result}")
                    print(f"Mureka API task created! Task ID: {result.get('id')}")
                    
                    task_id = result.get('id')
                    if task_id:
                        return self._wait_for_mureka_completion(task_id, title, lyrics, genre)
                    else:
                        print("No task ID returned from Mureka API")
                        print(f"Full response: {result}")
                        raise Exception("Mureka API did not return a task ID")
                
                elif response.status_code == 429:
                    wait_time = base_wait_time * (attempt + 1)
                    logger.warning(f"Mureka API rate limit (429). Waiting {wait_time}s...")
                    print(f"Rate limit reached (429). Waiting {wait_time} seconds...")
                    
                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                        continue
                    else:
                        error_msg = f"Mureka API rate limit exceeded after {max_retries} attempts. しばらく待ってから再試行してください。"
                        print(f"{error_msg}")
                        raise Exception(error_msg)
                
                elif response.status_code == 400:
                    # Bad request - 歌詞の問題の可能性
                    error_msg = f"Mureka API bad request (400): {response.text}"
                    print(f"{error_msg}")
                    raise Exception(error_msg)
                
                elif response.status_code >= 500:
                    # サーバーエラー - リトライ
                    if attempt < max_retries - 1:
                        wait_time = base_wait_time * (attempt + 1)
                        print(f"Server error ({response.status_code}), retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise Exception(f"Mureka API server error: {response.status_code}")
                
                else:
                    error_msg = f"Mureka API error: {response.status_code} - {response.text}"
                    print(f"{error_msg}")
                    raise Exception(error_msg)
                    
            except requests.exceptions.Timeout:
                print(f"Mureka API timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    wait_time = base_wait_time
                    print(f"Retrying after {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception("Mureka API timeout after all retries")
                    
            except requests.exceptions.ConnectionError as e:
                print(f"Mureka API connection error: {e}")
                if attempt < max_retries - 1:
                    wait_time = base_wait_time * (2 ** attempt)
                    print(f"Retrying after {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception(f"Mureka API connection failed: {e}")
                    
            except requests.exceptions.RequestException as e:
                print(f"Mureka API request error: {e}")
                if attempt < max_retries - 1:
                    wait_time = base_wait_time * (2 ** attempt)
                    print(f"Retrying after {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise
    
    def _translate_prompt_to_english(self, text):
        """音楽スタイルプロンプトを英語に翻訳する（Gemini使用）
        
        既に英語の場合はそのまま返す。日本語や他言語の場合は英語に翻訳する。
        翻訳に失敗した場合は元のテキストをそのまま返す。
        """
        # ASCII文字が大部分なら既に英語と判定
        ascii_count = sum(1 for c in text if ord(c) < 128)
        if len(text) > 0 and ascii_count / len(text) > 0.8:
            return text
        
        try:
            model = _get_gemini_model()
            if not model:
                logger.warning("Gemini model not available for prompt translation, using original text")
                return text
            
            prompt = f"""Translate the following music style description to English. 
Keep it concise and natural for a music generation AI prompt. 
Only output the English translation, nothing else.

Text: {text}"""
            
            response = model.generate_content(prompt)
            translated = response.text.strip()
            
            # 翻訳結果が空や異常に長い場合は元テキストを使用
            if not translated or len(translated) > len(text) * 5:
                return text
            
            logger.info(f"Prompt translated: '{text}' → '{translated}'")
            return translated
            
        except Exception as e:
            logger.warning(f"Prompt translation failed: {e}, using original text")
            return text
    
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
                        print(f"Cancelling running task: {task_id} (status: {status})")
                        cancel_url = f"{self.base_url}/v1/song/cancel/{task_id}"
                        cancel_response = requests.post(cancel_url, headers=headers, timeout=10)
                        
                        if cancel_response.status_code == 200:
                            print(f"Task {task_id} cancelled successfully")
                        else:
                            print(f"Failed to cancel task {task_id}: {cancel_response.text}")
                        
                        time.sleep(1)
                
                if not tasks:
                    print("No running tasks found")
            else:
                print(f"Could not fetch task list: {response.status_code}")
        except Exception as e:
            print(f"Error checking/cancelling tasks: {e}")
    
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
                print(f"Checking task status: {query_url} (Attempt {attempt + 1}/{max_attempts})")
                
                response = requests.get(query_url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    consecutive_errors = 0  # リセット
                    result = response.json()
                    status = result.get('status')
                    
                    print(f"Task {task_id} status: {status}")
                    
                    if status in ['completed', 'succeeded']:
                        choices = result.get('choices', [])
                        print(f"Choices count: {len(choices) if choices else 0}")
                        
                        if choices and len(choices) > 0:
                            choice = choices[0]
                            audio_url = choice.get('url')
                            print(f"Song URL: {audio_url}")
                            
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
                                'lyrics_sections': choice.get('lyrics_sections', [])
                            }
                        else:
                            print("No choices returned from Mureka API")
                            raise Exception("Mureka API returned no song choices")
                            
                    elif status in ['failed', 'error', 'cancelled']:
                        error_msg = result.get('error', result.get('message', 'Unknown error'))
                        print(f"Task failed with status: {status}, error: {error_msg}")
                        raise Exception(f"Mureka generation failed: {error_msg}")
                        
                    else:
                        # まだ処理中 - 待機時間を調整
                        if attempt < 10:
                            wait_time = 3  # 最初は短く
                        elif attempt < 30:
                            wait_time = 4
                        else:
                            wait_time = 5  # 後半は長く
                        
                        print(f"Task still {status}, waiting {wait_time}s...")
                        time.sleep(wait_time)
                        attempt += 1
                        
                elif response.status_code == 404:
                    print(f"Task {task_id} not found")
                    raise Exception(f"Mureka task not found: {task_id}")
                    
                else:
                    consecutive_errors += 1
                    print(f"Query error: {response.status_code} (consecutive: {consecutive_errors})")
                    
                    if consecutive_errors >= max_consecutive_errors:
                        raise Exception(f"Too many consecutive errors checking task status")
                    
                    time.sleep(5)
                    attempt += 1
                    
            except requests.exceptions.Timeout:
                consecutive_errors += 1
                print(f"Query timeout (consecutive: {consecutive_errors})")
                
                if consecutive_errors >= max_consecutive_errors:
                    raise Exception("Too many timeouts checking task status")
                
                time.sleep(5)
                attempt += 1
                
            except requests.exceptions.RequestException as e:
                consecutive_errors += 1
                print(f"Query request error: {e} (consecutive: {consecutive_errors})")
                
                if consecutive_errors >= max_consecutive_errors:
                    raise Exception(f"Network error checking task status: {e}")
                
                time.sleep(5)
                attempt += 1
                
            except Exception as e:
                if "failed" in str(e).lower() or "error" in str(e).lower():
                    raise  # 明確な失敗は再スロー
                print(f"Error querying task: {e}")
                raise
        
        print(f"Timeout waiting for task {task_id}")
        raise Exception(f"Timeout waiting for Mureka task after {max_attempts * 4} seconds")


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
            
            print(f"PDF opened: {page_count} pages")
            
            for page_num in range(page_count):
                page = doc.load_page(page_num)
                text = page.get_text()
                if text.strip():
                    extracted_text.append(text.strip())
                    print(f"Page {page_num + 1}: Extracted {len(text)} chars")
            
            doc.close()
            
            result = '\n\n'.join(extracted_text)
            
            # テキストが取得できた場合
            if result.strip():
                print(f"PDF extraction successful! Extracted {len(result)} characters from {page_count} pages")
                return result
            
            # テキストが取得できない場合（スキャンPDFなど）はOCRで処理
            print("No text found in PDF, trying OCR...")
            return self._extract_with_ocr(pdf_file, pdf_bytes if 'pdf_bytes' in dir() else None)
            
        except ImportError as e:
            print(f"PyMuPDF not installed: {e}")
            return ""
        except Exception as e:
            print(f"PDF extraction error: {e}")
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
                print("Gemini model not available for OCR")
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
                prompt = """Extract ALL text contained in this image.
Preserve the line breaks and paragraph structure.
Output only the extracted text without any additional explanation."""
                
                try:
                    response = model.generate_content([prompt, img])
                    if response and response.text:
                        extracted_texts.append(response.text.strip())
                        print(f"OCR Page {page_num + 1}: Extracted {len(response.text)} chars")
                except Exception as e:
                    print(f"OCR error on page {page_num + 1}: {e}")
            
            doc.close()
            
            result = '\n\n'.join(extracted_texts)
            print(f"PDF OCR completed! Extracted {len(result)} characters")
            return result
            
        except Exception as e:
            print(f"PDF OCR extraction error: {e}")
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
            
            prompt = """この画像に含まれているテキストをすべて抽出してください。
改行や段落の構造も保持してください。"""
            
            logger.info("GeminiOCR: Calling Gemini API for OCR...")
            response = self.model.generate_content([prompt, img])
            
            if response and response.text:
                extracted_text = response.text.strip()
                logger.info(f"GeminiOCR: Success! Extracted {len(extracted_text)} characters")
                return extracted_text
            else:
                # レスポンスの詳細をログ
                if response:
                    logger.warning(f"GeminiOCR: Empty response. prompt_feedback={getattr(response, 'prompt_feedback', 'N/A')}, candidates={getattr(response, 'candidates', 'N/A')}")
                else:
                    logger.warning("GeminiOCR: Response is None")
                return ""
                
        except Exception as e:
            logger.error(f"GeminiOCR: OCR error: {e}", exc_info=True)
            return ""  # エラー時も空文字を返してクラッシュを防ぐ


class GeminiLyricsGenerator:
    """Gemini を使用した歌詞生成クラス"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'GEMINI_API_KEY', None)
        self.model = _get_gemini_model()
    
    def generate_lyrics(self, extracted_text, title="", genre="pop", language_mode="japanese", custom_request=""):
        """抽出されたテキストから歌詞を生成（漢字のまま返す）
        
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
            
            response = self.model.generate_content(prompt)
            
            if response and response.text:
                raw_lyrics = response.text.strip()
                
                lyrics = self._extract_clean_lyrics(raw_lyrics)
                
                print(f"Gemini lyrics generation successful! Generated {len(lyrics)} characters")
                return lyrics
            else:
                print("Failed to generate lyrics")
                raise Exception("Failed to generate lyrics")
                
        except Exception as e:
            print(f"Gemini lyrics generation error: {e}")
            raise

    def _get_english_vocab_prompt(self, extracted_text, genre, custom_request=""):
        """日本語で英単語を覚えるためのプロンプト"""
        custom_section = ""
        if custom_request:
            custom_section = f"""
■ ユーザーからの追加リクエスト（重要！必ず反映してください）
{custom_request}
"""
        return f"""あなたは英単語暗記用の歌詞作成の専門家です。以下の英語テキストから{genre}ジャンルの日本語歌詞を作成してください。

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

【楽曲スタイル要件】
・日本語がメインで、英単語が自然に混ざる
・リズムに乗せやすいシンプルな構成
・耳に残りやすいフレーズ

■ 出力フォーマット（厳守）
[Verse 1]
（英単語と日本語訳を含む歌詞）

[Chorus]
（最重要英単語を繰り返す）

[Verse 2]
（歌詞）

[Chorus]
（繰り返し）

[Bridge]
（補足）

[Chorus]
（最終）

■ 厳守事項
・歌詞のみを出力すること
・説明文、コメント、解説は一切書かない
・丸数字（①②③、❶❷❸など）や番号記号は絶対に使わない
・元テキストにある番号記号は歌詞に含めず、内容だけを使う
"""

    def _get_english_prompt(self, extracted_text, genre, custom_request=""):
        """English mode - Pure English lyrics for native English speakers"""
        custom_section = ""
        if custom_request:
            custom_section = f"""

■ ADDITIONAL USER REQUEST (IMPORTANT! Must be reflected in the lyrics)
{custom_request}
"""
        return f"""You are an expert songwriter creating catchy, memorable {genre} style lyrics in PURE ENGLISH. Create lyrics from the following text to help memorize personal content.

■ Text Content
{extracted_text}
{custom_section}
■ ABSOLUTE REQUIREMENT
・Write 100% in English - NO Japanese, Chinese, or any other language
・Every word must be English
・This is for native English speakers to memorize personal information

■ Songwriting Techniques for Memory

【Make It Catchy】
・Use rhyming patterns (AABB, ABAB)
・Create memorable hooks and phrases
・Use natural English rhythm and flow

【Key Information Focus】
・Turn facts into singable lines
・Make numbers and dates rhythmic
・Include terms that are underlined, bold, or highlighted in the text
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
・30-180 seconds length
・Repeat keywords 2-4 times
・Clear pronunciation and ear-catching phrases

■ Output Format (Strict)
[Verse 1]
(English lyrics with spaces between meaning units)

[Chorus]
(catchy hook with key info repeated)

[Verse 2]
(continue the story)

[Chorus]
(repeat the hook)

[Bridge]
(summary or twist)

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
"""

    def _get_chinese_prompt(self, extracted_text, genre, custom_request=""):
        """Chinese mode - Pure Chinese lyrics for native Chinese speakers"""
        custom_section = ""
        if custom_request:
            custom_section = f"""

■ 用户额外要求（重要！必须在歌词中体现）
{custom_request}
"""
        return f"""你是一位专业的作词人，擅长创作朗朗上口、令人难忘的{genre}风格纯中文歌词。请根据以下文本创作歌词，帮助记忆个人内容。

■ 文本内容
{extracted_text}
{custom_section}
■ 绝对要求
・100%使用中文 - 绝对不能混入日语、英语或其他语言
・每一个字都必须是中文
・这是为中文母语者记忆个人信息而设计的

■ 记忆歌词创作技巧

【使其朗朗上口】
・使用押韵模式
・创造令人难忘的钩子和短语
・使用自然的中文节奏和韵律

【关键信息聚焦】
・将事实转化为可唱的歌词
・让数字和日期有节奏感
・文本中有下划线、粗体、荧光笔标记的内容必须包含在歌词中
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
・30-180秒长度
・关键词重复2-4次
・发音清晰，短语令人印象深刻

■ 输出格式（严格遵守）
[Verse 1]
（中文歌词，意义单位之间留空格）

[Chorus]
（带有重复关键信息的朗朗上口的钩子）

[Verse 2]
（继续故事）

[Chorus]
（重复钩子）

[Bridge]
（总结或转折）

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
"""

    def _get_chinese_vocab_prompt(self, extracted_text, genre, custom_request=""):
        """Chinese vocabulary mode - Pure Chinese lyrics for native Chinese speakers"""
        custom_section = ""
        if custom_request:
            custom_section = f"""

■ 用户额外要求（重要！必须在歌词中体现）
{custom_request}
"""
        return f"""你是一位专业的作词人，擅长创作朗朗上口、令人难忘的{genre}风格纯中文歌词。请根据以下文本创作歌词，帮助记忆词汇和内容。

■ 文本内容
{extracted_text}
{custom_section}
■ 绝对要求
・100%使用中文 - 绝对不能混入日语、英语或其他语言
・每一个字都必须是中文
・这是为中文母语者记忆个人信息而设计的

■ 记忆歌词创作技巧

【使其朗朗上口】
・使用押韵模式
・创造令人难忘的钩子和短语
・使用自然的中文节奏和韵律

【词汇强调】
・重要词汇在副歌中重复3次以上
・使用容易记忆的短语
・关键概念要反复出现
・文本中有下划线、粗体、荧光笔标记的内容必须包含在歌词中
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
・30-180秒长度
・关键词重复2-4次
・发音清晰，短语令人印象深刻

■ 输出格式（严格遵守）
[Verse 1]
（纯中文歌词，意义单位之间留空格）

[Chorus]
（重复最重要的词汇 - 纯中文）

[Verse 2]
（纯中文歌词）

[Chorus]
（重复 - 纯中文）

[Bridge]
（总结 - 纯中文）

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
"""

    def _get_japanese_prompt(self, extracted_text, genre, custom_request=""):
        """日本語モード（従来）のプロンプト"""
        custom_section = ""
        if custom_request:
            custom_section = f"""
■ ユーザーからの追加リクエスト（重要！必ず反映してください）
{custom_request}
"""
        return f"""あなたは暗記学習用の歌詞作成の専門家です。以下のテキストから{genre}ジャンルの歌詞を作成してください。

■ テキスト内容
{extracted_text}
{custom_section}
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
・テキスト内で「下線」「太字」「マーカー」などで強調されている語句は必ず歌詞に含める
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
・小学生〜中学生でも口ずさみやすい音感を重視する
・テキストに書かれている情報のみを使用
・事実関係・用語の意味を正確に
・要点を過不足なく含める
・人物名・地名・用語の読み方を調べて正確に

【楽曲スタイル要件】
・キーワードを2〜4回繰り返す
・耳に残りやすいフレーズと明瞭な発音
・全体として30〜180秒相当の適切な分量

■ 出力フォーマット（厳守）
[Verse 1]
（歌詞のみ、単語間にスペースを入れる）

[Chorus]
（最重要単語を繰り返す歌詞のみ）

[Verse 2]
（歌詞のみ）

[Chorus]
（最重要単語を再度繰り返す歌詞のみ）

[Bridge]
（補足・まとめの歌詞のみ）

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
            
            response = self.model.generate_content(prompt)
            
            if response and response.text:
                tags_text = response.text.strip()
                tags = [tag.strip() for tag in tags_text.split(',') if tag.strip()]
                tags = list(dict.fromkeys(tags))[:10]
                print(f"Generated tags: {tags}")
                return tags
            else:
                return []
                
        except Exception as e:
            print(f"Tag generation error: {e}")
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


def number_to_japanese_reading(num_str):
    """数字を日本語の読み方に変換（例：35→さんじゅうご、350000→さんじゅうごまん）"""
    try:
        num = int(num_str)
    except ValueError:
        return num_str
    
    if num == 0:
        return 'ぜろ'
    
    # 基本の数字
    digits = ['', 'いち', 'に', 'さん', 'よん', 'ご', 'ろく', 'なな', 'はち', 'きゅう']
    
    # 特殊な読み方
    def get_digit(n, unit=''):
        if n == 0:
            return ''
        if n == 1:
            if unit in ['じゅう', 'ひゃく', 'せん']:
                return unit  # 一十、一百、一千は省略
            return 'いち' + unit
        if n == 3 and unit == 'ひゃく':
            return 'さんびゃく'
        if n == 6 and unit == 'ひゃく':
            return 'ろっぴゃく'
        if n == 8 and unit == 'ひゃく':
            return 'はっぴゃく'
        if n == 3 and unit == 'せん':
            return 'さんぜん'
        if n == 8 and unit == 'せん':
            return 'はっせん'
        return digits[n] + unit
    
    result = ''
    
    # 億（100,000,000）
    if num >= 100000000:
        oku = num // 100000000
        result += number_to_japanese_reading(str(oku)) + 'おく'
        num %= 100000000
    
    # 万（10,000）
    if num >= 10000:
        man = num // 10000
        result += number_to_japanese_reading(str(man)) + 'まん'
        num %= 10000
    
    # 千（1,000）
    if num >= 1000:
        sen = num // 1000
        result += get_digit(sen, 'せん')
        num %= 1000
    
    # 百（100）
    if num >= 100:
        hyaku = num // 100
        result += get_digit(hyaku, 'ひゃく')
        num %= 100
    
    # 十（10）
    if num >= 10:
        juu = num // 10
        result += get_digit(juu, 'じゅう')
        num %= 10
    
    # 一の位
    if num > 0:
        result += digits[num]
    
    return result


def kanji_and_numbers_to_hiragana(text):
    """漢字と数字をひらがなに変換（fugashiが利用可能な場合）
    改行や句読点を保持して、歌詞の構造を維持する
    """
    def num_to_hiragana(match):
        return number_to_japanese_reading(match.group())
    
    text = re.sub(r'[0-9]+', num_to_hiragana, text)
    
    if not FUGASHI_AVAILABLE:
        # fugashiがない場合は数字のみ変換して返す
        return text
    
    # 行ごとに処理して改行を保持
    lines = text.split('\n')
    converted_lines = []
    
    tagger = Tagger()
    
    for line in lines:
        if not line.strip():
            # 空行はそのまま保持
            converted_lines.append('')
            continue
            
        # セクションマーカー（[Verse], [Chorus]など）はそのまま保持
        if line.strip().startswith('[') and line.strip().endswith(']'):
            converted_lines.append(line)
            continue
        
        result = []
        for word in tagger(line):
            if re.match(r'[A-Za-zａ-ｚＡ-Ｚァ-ンー]', word.surface):
                result.append(word.surface)
            elif re.match(r'[一-龥]', word.surface):
                result.append(word.feature.kana or word.surface)
            else:
                result.append(word.surface)
        
        converted_lines.append(''.join(result))
    
    # 改行で結合して返す
    return '\n'.join(converted_lines)


def convert_lyrics_to_hiragana_with_context(lyrics):
    """Gemini AIを使って文脈を考慮しながら歌詞をひらがなに変換
    
    漢字の読みを正確にするために、文脈を考慮して変換する。
    例: 「今日」→「きょう」vs「こんにち」、「明日」→「あした」vs「あす」
    """
    model = _get_gemini_model()
    
    if not model:
        # Geminiが使えない場合はfallback
        logger.warning("Gemini not available, falling back to fugashi conversion")
        return kanji_and_numbers_to_hiragana(lyrics)
    
    try:
        prompt = f"""以下の日本語の歌詞を、漢字を全てひらがなに変換してください。

1. 文脈を考慮して、正しい読み方を選んでください
   - 「今日」→ 歌詞では通常「きょう」
   - 「明日」→ 歌詞では通常「あした」または「あす」（文脈による）
   - 「昨日」→ 歌詞では通常「きのう」
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

2. 数字は日本語の読みに変換
   - 「1」→「いち」、「2」→「に」、「10」→「じゅう」、「100」→「ひゃく」

3. 助詞の発音変換（重要！歌の発音に合わせる）
   - 助詞の「は」→「わ」に変換（例：「私は」→「わたしわ」、「これは」→「これわ」）
   - 助詞の「へ」→「え」に変換（例：「海へ」→「うみえ」、「空へ」→「そらえ」）
   - 助詞の「を」→「お」に変換（例：「夢を」→「ゆめお」）
   ※ 助詞以外の「は」「へ」「を」はそのまま（例：「はな」→「はな」、「へや」→「へや」）

4. セクションラベル（[Verse], [Chorus], [Bridge]など）はそのまま保持

5. 英語はそのまま保持

6. 改行や空行は必ず保持

7. カタカナはそのまま保持

8. 出力は変換後の歌詞のみ（説明や前置きは不要）

【変換する歌詞】
{lyrics}

【出力】（変換後の歌詞のみを出力）"""

        response = model.generate_content(prompt)
        
        if response and response.text:
            converted = response.text.strip()
            # 余計な説明を削除
            if converted.startswith('```'):
                lines = converted.split('\n')
                converted = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])
            
            logger.info(f"Gemini hiragana conversion successful: {len(lyrics)} -> {len(converted)} chars")
            return converted
        else:
            logger.warning("Gemini returned empty response, falling back to fugashi")
            return kanji_and_numbers_to_hiragana(lyrics)
            
    except Exception as e:
        logger.error(f"Gemini hiragana conversion error: {e}, falling back to fugashi")
        return kanji_and_numbers_to_hiragana(lyrics)
