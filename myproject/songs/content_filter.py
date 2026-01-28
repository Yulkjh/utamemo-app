"""
不適切コンテンツフィルター

OCRで抽出されたテキストから不適切な用語を検出し、
利用規約違反を防止するためのモジュール
"""

import re
import logging

logger = logging.getLogger(__name__)


class ContentFilter:
    """不適切コンテンツを検出するフィルタークラス"""
    
    # 禁止ワードリスト（日本語）
    PROHIBITED_WORDS_JA = [
        # 差別・侮辱表現
        'バカ', 'ばか', '馬鹿', 'アホ', 'あほ', '阿呆',
        'クズ', 'くず', '屑', 'カス', 'かす', '粕',
        'ゴミ', 'ごみ', 'クソ', 'くそ', '糞',
        'ブス', 'ぶす', 'デブ', 'でぶ', 'ハゲ', 'はげ', '禿げ',
        'キモい', 'きもい', 'キモイ', 'ウザい', 'うざい', 'ウザイ',
        'きしょい', 'キショい', 'キショイ',
        
        # 暴力・脅迫表現
        '死ね', 'しね', '殺す', 'ころす', '殺してやる',
        '消えろ', 'きえろ', 'うせろ', 'ウセロ',
        
        # 性的表現
        'エロ', 'えろ', 'セックス', 'オナニー',
        
        # 差別用語
        'チョン', 'シナ', 'ニガー', '土人',
        '障害者', 'ガイジ', 'がいじ', '池沼',
        'メンヘラ', 'めんへら',
        
        # いじめ関連
        'いじめ', 'イジメ', '虐め',
        'ハブ', 'はぶ', 'ハブる', 'はぶる',
        '無視しろ', '仲間外れ',
    ]
    
    # 禁止ワードリスト（英語）
    PROHIBITED_WORDS_EN = [
        # Slurs and insults
        'fuck', 'shit', 'bitch', 'asshole', 'bastard',
        'damn', 'crap', 'dick', 'cock', 'pussy',
        'whore', 'slut', 'retard', 'retarded',
        'idiot', 'moron', 'stupid',
        
        # Hate speech
        'nigger', 'nigga', 'faggot', 'fag',
        'chink', 'spic', 'kike',
        
        # Violence
        'kill', 'murder', 'die', 'death threat',
        
        # Sexual content
        'porn', 'sex', 'nude', 'naked',
    ]
    
    # 禁止ワードリスト（中国語）
    PROHIBITED_WORDS_ZH = [
        '傻逼', '他妈的', '操你妈', '混蛋',
        '白痴', '笨蛋', '蠢货', '废物',
        '去死', '杀了你',
    ]
    
    # 禁止パターン（正規表現）
    PROHIBITED_PATTERNS = [
        r'死ね+',           # 「死ねええ」など
        r'きも+い',         # 「きもーい」など
        r'うざ+い',         # 「うざーい」など
        r'ころ+す',         # 「ころーす」など
        r'f+u+c+k+',        # 「fuuuck」など
        r's+h+i+t+',        # 「shiiiit」など
    ]
    
    def __init__(self):
        """フィルターの初期化"""
        # すべての禁止ワードを小文字で統合
        self.prohibited_words = set()
        
        for word in self.PROHIBITED_WORDS_JA:
            self.prohibited_words.add(word.lower())
            # ひらがな/カタカナ変換も追加
            self.prohibited_words.add(self._hiragana_to_katakana(word).lower())
            self.prohibited_words.add(self._katakana_to_hiragana(word).lower())
        
        for word in self.PROHIBITED_WORDS_EN:
            self.prohibited_words.add(word.lower())
        
        for word in self.PROHIBITED_WORDS_ZH:
            self.prohibited_words.add(word.lower())
        
        # 正規表現パターンをコンパイル
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.PROHIBITED_PATTERNS
        ]
    
    def _hiragana_to_katakana(self, text):
        """ひらがなをカタカナに変換"""
        return ''.join(
            chr(ord(char) + 96) if 'ぁ' <= char <= 'ゖ' else char
            for char in text
        )
    
    def _katakana_to_hiragana(self, text):
        """カタカナをひらがなに変換"""
        return ''.join(
            chr(ord(char) - 96) if 'ァ' <= char <= 'ヶ' else char
            for char in text
        )
    
    def check_content(self, text):
        """
        テキストに不適切なコンテンツが含まれているかチェック
        
        Args:
            text: チェックするテキスト
            
        Returns:
            dict: {
                'is_inappropriate': bool,  # 不適切かどうか
                'detected_words': list,    # 検出された禁止ワード
                'message': str             # ユーザー向けメッセージ
            }
        """
        if not text:
            return {
                'is_inappropriate': False,
                'detected_words': [],
                'message': ''
            }
        
        detected_words = []
        text_lower = text.lower()
        
        # 禁止ワードのチェック
        for word in self.prohibited_words:
            if word in text_lower:
                detected_words.append(word)
        
        # 正規表現パターンのチェック
        for pattern in self.compiled_patterns:
            matches = pattern.findall(text_lower)
            detected_words.extend(matches)
        
        # 重複を除去
        detected_words = list(set(detected_words))
        
        if detected_words:
            logger.warning(f"Inappropriate content detected: {detected_words}")
            return {
                'is_inappropriate': True,
                'detected_words': detected_words,
                'message': self._get_violation_message(detected_words)
            }
        
        return {
            'is_inappropriate': False,
            'detected_words': [],
            'message': ''
        }
    
    def _get_violation_message(self, detected_words, language='ja'):
        """違反メッセージを生成"""
        messages = {
            'ja': (
                '利用規約違反のコンテンツが検出されました。\n\n'
                '不適切な表現（悪口、差別用語、暴力的な表現など）を含むコンテンツは'
                '楽曲生成に使用できません。\n\n'
                '利用規約に同意の上、適切なコンテンツでご利用ください。'
            ),
            'en': (
                'Content that violates our Terms of Service has been detected.\n\n'
                'Content containing inappropriate expressions (insults, discriminatory language, '
                'violent expressions, etc.) cannot be used for song generation.\n\n'
                'Please agree to the Terms of Service and use appropriate content.'
            ),
            'zh': (
                '检测到违反使用条款的内容。\n\n'
                '包含不当表达（侮辱、歧视性语言、暴力表达等）的内容'
                '不能用于歌曲生成。\n\n'
                '请同意使用条款并使用适当的内容。'
            ),
            'es': (
                'Se ha detectado contenido que viola nuestros Términos de Servicio.\n\n'
                'El contenido que contiene expresiones inapropiadas (insultos, lenguaje discriminatorio, '
                'expresiones violentas, etc.) no se puede usar para la generación de canciones.\n\n'
                'Por favor, acepte los Términos de Servicio y use contenido apropiado.'
            ),
            'de': (
                'Es wurde Inhalt erkannt, der gegen unsere Nutzungsbedingungen verstößt.\n\n'
                'Inhalte mit unangemessenen Ausdrücken (Beleidigungen, diskriminierende Sprache, '
                'gewalttätige Ausdrücke usw.) können nicht für die Songgenerierung verwendet werden.\n\n'
                'Bitte stimmen Sie den Nutzungsbedingungen zu und verwenden Sie angemessene Inhalte.'
            ),
            'pt': (
                'Foi detectado conteúdo que viola nossos Termos de Serviço.\n\n'
                'Conteúdo contendo expressões inadequadas (insultos, linguagem discriminatória, '
                'expressões violentas, etc.) não pode ser usado para geração de músicas.\n\n'
                'Por favor, aceite os Termos de Serviço e use conteúdo apropriado.'
            ),
        }
        return messages.get(language, messages['ja'])
    
    def get_violation_message_by_language(self, language='ja'):
        """言語に応じた違反メッセージを取得"""
        return self._get_violation_message([], language)


# シングルトンインスタンス
content_filter = ContentFilter()


def check_text_for_inappropriate_content(text):
    """
    テキストの不適切コンテンツをチェックする便利関数
    
    Args:
        text: チェックするテキスト
        
    Returns:
        dict: チェック結果
    """
    return content_filter.check_content(text)
