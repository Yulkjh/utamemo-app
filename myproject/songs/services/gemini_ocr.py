"""Gemini OCR モジュール"""
import logging

from PIL import Image
from django.conf import settings

from .text_processing import GEMINI_SAFETY_SETTINGS, _safe_get_response_text, _get_gemini_model

logger = logging.getLogger(__name__)


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
