"""PDF テキスト抽出モジュール"""
import logging

from django.conf import settings

from .text_processing import GEMINI_SAFETY_SETTINGS, _safe_get_response_text, _get_gemini_model

logger = logging.getLogger(__name__)


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
