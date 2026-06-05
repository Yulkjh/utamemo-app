"""Gemini フラッシュカード抽出モジュール"""
import re
import logging

from PIL import Image
from django.conf import settings

from .cache import _get_cache_key, _get_cached_response, _set_cached_response
from .text_processing import (
    GEMINI_SAFETY_SETTINGS,
    _safe_get_response_text,
    _get_gemini_model,
    extract_bracketed_terms,
)

logger = logging.getLogger(__name__)


class GeminiFlashcardExtractor:
    """Gemini を使用してテキスト/画像から重要語句と定義を抽出するクラス"""
    
    def __init__(self):
        self.model = _get_gemini_model()
    
    def extract_terms_from_text(self, text):
        """テキストから重要語句と定義を抽出"""
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
        """画像から直接重要語句と定義を抽出"""
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
        """Geminiの応答からJSON配列をパース"""
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
