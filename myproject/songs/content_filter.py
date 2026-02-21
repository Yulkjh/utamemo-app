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
    # 本当に悪質なもの（差別用語・ヘイト・直接的脅迫）のみ
    PROHIBITED_WORDS_JA = [
        # 直接的な脅迫表現
        '殺してやる', 'ころしてやる', '殺すぞ', 'ころすぞ',
        
        # 性的表現
        'セックス', 'オナニー',
        
        # 差別用語・ヘイトスピーチ
        'チョン', 'ニガー', '土人',
        'ガイジ', 'がいじ', '池沼',
    ]
    
    # 文脈に応じて判定する暴力系ワード（日本語）
    # 歴史・学術・文学的文脈では許可する
    ACADEMIC_CONTEXT_WORDS_JA = {
        '殺す': [],
        'ころす': [],
        '殺した': [],
        '殺される': [],
        '殺された': [],
    }
    
    # 学術的・歴史的文脈を示すキーワード（これらが同じテキストにあれば暴力系ワードを許可）
    ACADEMIC_CONTEXT_INDICATORS_JA = [
        # 歴史
        '時代', '世紀', '年代', '歴史', '戦国', '幕府', '明治', '大正', '昭和',
        '平成', '令和', '江戸', '鎌倉', '室町', '奈良', '平安', '縄文', '弥生',
        '天皇', '将軍', '武将', '大名', '藩', '城', '合戦', '戦い', '戦争',
        '革命', '維新', '開国', '条約', '改革',
        '信長', '秀吉', '家康', '義元', '光秀', '謙信', '信玄',
        '本能寺', '関ヶ原', '応仁', '壬申', '承久',
        # 人物・偉人
        'の変', 'の乱', 'の役', 'の戦い', 'の死',
        '暗殺', '討伐', '征伐', '滅亡', '崩御', '没',
        # 科学・医学
        '細胞', '生物', '化学', '実験', 'DNA', 'RNA',
        '医学', '解剖', '手術', '治療', '疾患', '病気',
        'アポトーシス', '壊死', '細胞死',
        # 文学
        '小説', '文学', '物語', '作品', '著者', '作者',
        '太宰治', '芥川', '夏目漱石', '三島由紀夫',
        # 教科書・学習
        '教科書', '問題', '試験', 'テスト', '学習', '勉強',
        '授業', '講義', '解説', 'ページ', '章',
    ]
    
    # 部分一致で誤検出しやすいワード（特別な処理が必要）
    # これらは前後の文字をチェックして、単独で使われている場合のみ検出
    CONTEXT_SENSITIVE_WORDS = {
        'エロ': ['ピエロ', 'ラファエロ', 'ミケランジェロ', 'エロイカ', 'エロス', 'エローラ', 'カメロ', 'ロメロ'],
        'えろ': ['ぴえろ', 'らふぁえろ'],
        'シナ': ['シナリオ', 'シナプス', 'シナモン', 'シナジー', 'シナノ', 'シナトラ'],
    }
    
    # 禁止ワードリスト（英語）
    # 本当に悪質なもの（ヘイト・直接的脅迫・性的コンテンツ）のみ
    PROHIBITED_WORDS_EN = [
        # Hate speech / Slurs
        'nigger', 'nigga', 'faggot', 'fag',
        'chink', 'spic', 'kike',
        
        # Direct threats
        'death threat',
        
        # Sexual content
        'porn', 'nude', 'naked',
    ]
    
    # 文脈に応じて判定する暴力系ワード（英語）
    ACADEMIC_CONTEXT_WORDS_EN = {
        'kill': [],
        'killed': [],
        'murder': [],
        'murdered': [],
        'die': [],
        'died': [],
        'death': [],
    }
    
    # 学術的・歴史的文脈を示すキーワード（英語）
    ACADEMIC_CONTEXT_INDICATORS_EN = [
        # History
        'century', 'era', 'period', 'history', 'historical', 'ancient',
        'medieval', 'dynasty', 'empire', 'kingdom', 'civilization',
        'war', 'battle', 'revolution', 'treaty', 'independence',
        'emperor', 'king', 'queen', 'ruler', 'general',
        'napoleon', 'caesar', 'lincoln', 'gandhi',
        # Science/Medicine
        'cell', 'biology', 'chemistry', 'experiment', 'species',
        'medical', 'disease', 'treatment', 'surgery', 'anatomy',
        'apoptosis', 'necrosis',
        # Literature
        'novel', 'literature', 'story', 'author', 'shakespeare',
        'chapter', 'textbook', 'lesson', 'study', 'exam',
    ]
    
    # 禁止ワードリスト（中国語）
    PROHIBITED_WORDS_ZH = [
        '傻逼', '他妈的', '操你妈', '混蛋',
        '白痴', '笨蛋', '蠢货', '废物',
        '去死', '杀了你',
    ]
    
    # 禁止パターン（正規表現）- 脅迫的な強調表現のみ
    PROHIBITED_PATTERNS = [
        r'死ね+',           # 「死ねええ」など
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
        
        # 禁止ワードのチェック（無条件でブロック）
        for word in self.prohibited_words:
            if word in text_lower:
                detected_words.append(word)
        
        # 文脈依存ワードのチェック（除外リストを考慮）
        for sensitive_word, exceptions in self.CONTEXT_SENSITIVE_WORDS.items():
            if sensitive_word.lower() in text_lower:
                # 除外リストに含まれる単語がテキストにあるかチェック
                is_exception = False
                for exception in exceptions:
                    if exception.lower() in text_lower:
                        is_exception = True
                        break
                
                if not is_exception:
                    detected_words.append(sensitive_word)
        
        # 学術的文脈チェック（暴力系ワードが含まれていても学術文脈なら許可）
        academic_detected = self._check_academic_context_words(text_lower)
        if academic_detected:
            # 学術的文脈の指標があるかチェック
            has_academic_context = self._has_academic_context(text_lower)
            if not has_academic_context:
                # 学術的文脈がないのに暴力系ワードがある → ブロック
                detected_words.extend(academic_detected)
        
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
    
    def _check_academic_context_words(self, text_lower):
        """テキストに学術文脈ワード（暴力系）が含まれるかチェック"""
        detected = []
        
        # 日本語
        for word in self.ACADEMIC_CONTEXT_WORDS_JA:
            if word in text_lower:
                detected.append(word)
        
        # 英語（単語境界でチェックして部分一致を防ぐ）
        for word in self.ACADEMIC_CONTEXT_WORDS_EN:
            pattern = r'\b' + re.escape(word) + r'\b'
            if re.search(pattern, text_lower):
                detected.append(word)
        
        return detected
    
    def _has_academic_context(self, text_lower):
        """テキストに学術的・歴史的文脈の指標があるかチェック"""
        # 日本語の文脈指標
        for indicator in self.ACADEMIC_CONTEXT_INDICATORS_JA:
            if indicator.lower() in text_lower:
                return True
        
        # 英語の文脈指標
        for indicator in self.ACADEMIC_CONTEXT_INDICATORS_EN:
            if indicator.lower() in text_lower:
                return True
        
        return False
    
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
