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
    # 歴史・学術・文学的文脈、および歌詞・詩的文脈では許可する
    ACADEMIC_CONTEXT_WORDS_JA = {
        '殺す': [],
        'ころす': [],
        '殺した': [],
        '殺される': [],
        '殺された': [],
        '殺せ': [],
        '死にたい': [],
        '死ぬ': [],
        '死んだ': [],
        '死んで': [],
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
        # 歌詞・詩的文脈（歌詞中の比喩的・詩的表現を許可する）
        '歌', 'うた', 'メロディ', 'サビ', 'コーラス',
        '夢', 'ゆめ', '涙', 'なみだ', '心', 'こころ',
        '愛', 'あい', '恋', 'こい', '想い', 'おもい',
        '空', 'そら', '海', 'うみ', '風', 'かぜ',
        '光', 'ひかり', '闇', 'やみ', '影', 'かげ',
        '花', 'はな', '星', 'ほし', '月', 'つき', '太陽', 'たいよう',
        '翼', 'つばさ', '羽', 'はね',
        '明日', 'あした', '未来', 'みらい', '過去', 'かこ',
        '記憶', 'きおく', '約束', 'やくそく',
        '届け', 'とどけ', '叫び', 'さけび', '祈り', 'いのり',
        '痛み', 'いたみ', '傷', 'きず', '孤独', 'こどく',
        '世界', 'せかい', '永遠', 'えいえん',
        '瞳', 'ひとみ', '声', 'こえ', '手', 'て',
        '強く', 'つよく', '優しく', 'やさしく',
        '走る', 'はしる', '飛ぶ', 'とぶ', '泣く', 'なく',
        '笑う', 'わらう', '信じる', 'しんじる',
        '最後', 'さいご', '始まり', 'はじまり',
        '旅', 'たび', '道', 'みち', '扉', 'とびら',
        # 歌詞でよく使われる人称・感情表現
        '君', 'きみ', '僕', 'ぼく', 'あなた', 'わたし', '私',
        '好き', 'すき', '嫌い', 'きらい', '寂しい', 'さみしい',
        '切ない', 'せつない', '悲しい', 'かなしい', '嬉しい', 'うれしい',
        '会いたい', 'あいたい', '忘れない', 'わすれない',
        '抱きしめ', 'だきしめ', '離さない', 'はなさない',
        '生きる', 'いきる', '生きて', 'いきて',
        # セクションラベル（歌詞構造）
        '[verse', '[chorus', '[bridge', '[intro', '[outro',
        'verse', 'chorus', 'bridge', 'intro', 'outro',
    ]
    
    # 部分一致で誤検出しやすいワード（特別な処理が必要）
    # これらは前後の文字をチェックして、単独で使われている場合のみ検出
    CONTEXT_SENSITIVE_WORDS = {
        'エロ': ['ピエロ', 'ラファエロ', 'ミケランジェロ', 'エロイカ', 'エロス', 'エローラ', 'カメロ', 'ロメロ'],
        'えろ': ['ぴえろ', 'らふぁえろ'],
        'シナ': ['シナリオ', 'シナプス', 'シナモン', 'シナジー', 'シナノ', 'シナトラ'],
    }
    
    # 禁止ワードリスト（英語）
    # 本当に悪質なもの（ヘイト・直接的脅迫・性的コンテンツ・卑語）のみ
    PROHIBITED_WORDS_EN = [
        # Hate speech / Slurs
        'nigger', 'nigga', 'faggot', 'fag',
        'chink', 'spic', 'kike',
        'retard', 'retarded',
        
        # Profanity / Vulgar language
        'fuck', 'fucking', 'fucked', 'fucker', 'motherfucker',
        'fuck you', 'fuck off', 'wtf',
        'shit', 'shitty', 'bullshit',
        'bitch', 'bitches',
        'asshole', 'ass hole',
        'cunt', 'dick', 'cock', 'pussy',
        'bastard',
        'damn you', 'goddamn',
        'stfu', 'gtfo',
        
        # Direct threats
        'death threat',
        'i will kill you', 'gonna kill you',
        
        # Sexual content
        'porn', 'porno', 'pornography',
        'nude', 'xxx',
        'hentai', 'blowjob', 'handjob',
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
        # Song/Lyrics/Poetry context
        'song', 'melody', 'chorus', 'verse', 'bridge', 'intro', 'outro',
        'dream', 'tears', 'heart', 'soul', 'love', 'hope',
        'sky', 'ocean', 'wind', 'light', 'shadow', 'darkness',
        'flower', 'star', 'moon', 'sun',
        'wings', 'fly', 'rain', 'fire',
        'tomorrow', 'forever', 'memory', 'promise',
        'pain', 'wound', 'lonely', 'loneliness',
        'world', 'eternity', 'destiny', 'fate',
        'eyes', 'voice', 'hands', 'arms',
        'strong', 'gentle', 'brave',
        'run', 'cry', 'smile', 'believe',
        'last', 'begin', 'end', 'journey', 'road', 'door',
        # Common lyrical pronouns and emotions
        'you', 'your', 'mine', 'baby', 'darling', 'tonight',
        'miss', 'hold', 'never', 'always', 'away',
        'alive', 'live', 'breathe', 'free', 'freedom',
        'broken', 'falling', 'rising', 'fading',
        'thousand', 'million', 'hundred',
        '[verse', '[chorus', '[bridge', '[intro', '[outro',
    ]
    
    # 禁止ワードリスト（中国語）
    PROHIBITED_WORDS_ZH = [
        '傻逼', '他妈的', '操你妈', '混蛋',
        '白痴', '笨蛋', '蠢货', '废物',
        '去死', '杀了你',
    ]
    
    # 禁止パターン（正規表現）- 脅迫的な強調表現のみ
    PROHIBITED_PATTERNS = [
        r'死ねえ+',         # 「死ねええ」など脅迫的な伸ばし表現のみ
        r'f+u+c+k+',       # 「fuuuck」など伸ばし表現
    ]
    
    # ユーザー名用の禁止ワードリスト
    # スラー、差別用語、卑語のバリエーション（リートスピーク・回避パターン含む）
    # 長い単語は部分一致でチェック
    PROHIBITED_USERNAME_WORDS = [
        # 人種差別スラー + バリエーション
        'nigger', 'nigga', 'nigg', 'n1gga', 'n1gger', 'niga', 'nigar',
        'n!gga', 'n!gger', 'niqqer', 'niqqa', 'niqqah',
        'negro', 'negr0',
        'chink', 'ch1nk',
        'wetback', 'beaner',
        'cracker',
        'honky', 'honkey',
        'gringo',
        'darkie', 'darky',
        
        # 性差別・LGBTQ差別
        'faggot', 'f4ggot', 'fagg0t',
        'tranny', 'tr4nny',
        
        # 障害者差別
        'retard', 'r3tard', 'ret4rd',
        'ガイジ', 'がいじ', '池沼',
        
        # 卑語・猥褻語（長い語は部分一致OK）
        'fucker', 'motherfucker', 'phuck', 'phuk',
        'bitch', 'b1tch', 'b!tch', 'biatch',
        'cunt', 'c_nt', 'c*nt',
        'pussy', 'pu$$y', 'pus5y',
        'asshole', 'a$$hole', 'assh0le',
        'bastard', 'b4stard',
        'whore', 'wh0re',
        'slut', 'sl*t',
        'porn', 'p0rn',
        'hentai',
        
        # 日本語差別用語
        'チョン', 'ちょん',
        'ニガー', 'にがー',
        '土人', 'どじん',
        'きちがい', 'キチガイ', '基地外',
        'くたばれ', 'クタバレ',
        'しね', 'シネ',
        
        # 中国語差別用語
        '傻逼', '他妈的', '操你妈',
        
        # ナチス・ヘイトシンボル
        'nazi', 'n4zi', 'naz1',
        'hitler', 'h1tler',
        'heil',
        'whitepower', 'whitepow3r',
        '卍卍',
        'ss88', '1488', '14words',
    ]
    
    # 短い禁止ワード（4文字以下）は誤検出しやすいため、除外リスト付きで個別チェック
    # { 'word': ['除外ワード（これを含むユーザー名はOK）'] }
    PROHIBITED_USERNAME_SHORT_WORDS = {
        'fuck': ['fuchsia'],
        'fck': [],
        'fuk': [],
        'fuc': ['fuchsia', 'fuchsin'],
        'f_ck': [],
        'f.ck': [],
        'f*ck': [],
        'shit': [],
        'sh1t': [],
        'sh!t': [],
        'dick': ['dickens'],
        'd1ck': [],
        'd!ck': [],
        'cock': ['cocktail', 'hancock', 'peacock', 'woodcock', 'cockpit', 'cockroach'],
        'c0ck': [],
        'jap': ['japan', 'japanese'],
        'fag': ['fagan'],
        'f4g': [],
        'spic': ['spice', 'spicy'],
        'sp1c': [],
        'kike': [],
        'k1ke': [],
        'gook': [],
        'g00k': [],
        'coon': ['raccoon', 'cocoon', 'tycoon'],
        'c00n': [],
        'paki': ['pakistan'],
        'dyke': [],
        'dyk3': [],
        'gaijin': [],
        'hoe': ['shoes', 'shoe', 'phoenix', 'hoek'],
        'h0e': [],
        'kkk': [],
    }
    
    # ユーザー名用の禁止パターン（正規表現）
    PROHIBITED_USERNAME_PATTERNS = [
        r'n+[i1!]+g+[a4@]+[rhz]*',  # nigga/niga系のバリエーション
        r'f+[u\*]+c+k+',             # fuck系のバリエーション
        r'sh+[i1!]+t+',              # shit系のバリエーション
        r'b+[i1!]+t+ch+',            # bitch系のバリエーション
    ]
    
    # 有名人・著名人の名前（権利侵害防止）
    # 現代の芸能人・アーティスト・政治家・スポーツ選手等
    # ※歴史上の人物は ACADEMIC_CONTEXT_INDICATORS に含まれ、学術文脈で許可される
    CELEBRITY_NAMES = [
        # 日本の芸能人・アーティスト
        '米津玄師', 'よねづけんし', 'ヨネヅケンシ',
        'YOASOBI', 'yoasobi', 'ヨアソビ',
        'Ado', 'ado', 'アド',
        '藤井風', 'ふじいかぜ',
        'あいみょん', 'アイミョン',
        'ヒゲダン', 'Official髭男dism',
        'King Gnu', 'キングヌー',
        'ARASHI',
        'SMAP', 'スマップ',
        '宇多田ヒカル', 'うただひかる',
        '浜崎あゆみ', 'はまさきあゆみ',
        '安室奈美恵', 'あむろなみえ',
        'Mr.Children', 'ミスチル',
        'B\'z', 'ビーズ',
        'サザンオールスターズ', 'サザン',
        '桑田佳祐', 'くわたけいすけ',
        'back number', 'バックナンバー',
        'Mrs. GREEN APPLE', 'ミセスグリーンアップル',
        'Creepy Nuts', 'クリーピーナッツ',
        'TWICE', 'トゥワイス',
        'BTS', 'ビーティーエス', '防弾少年団',
        'BLACKPINK', 'ブラックピンク',
        'NiziU', 'ニジュー',
        'ジャニーズ',
        '乃木坂46', '乃木坂',
        '櫻坂46', '欅坂46',
        'AKB48', 'AKB',
        
        # 日本の俳優・タレント
        '大谷翔平', 'おおたにしょうへい',
        '木村拓哉', 'きむらたくや', 'キムタク',
        '松本人志', 'まつもとひとし',
        '明石家さんま', 'あかしやさんま',
        'ビートたけし', '北野武',
        'タモリ',
        
        # 日本の政治家
        '岸田文雄', 'きしだふみお',
        '安倍晋三', 'あべしんぞう',
        '菅義偉', 'すがよしひで',
        '小泉進次郎', 'こいずみしんじろう',
        '石破茂', 'いしばしげる',
        
        # 海外アーティスト
        'Taylor Swift', 'テイラースウィフト', 'テイラー・スウィフト',
        'Beyonce', 'ビヨンセ',
        'Ariana Grande', 'アリアナグランデ', 'アリアナ・グランデ',
        'Ed Sheeran', 'エドシーラン', 'エド・シーラン',
        'Billie Eilish', 'ビリーアイリッシュ', 'ビリー・アイリッシュ',
        'Drake', 'ドレイク',
        'Justin Bieber', 'ジャスティンビーバー', 'ジャスティン・ビーバー',
        'Lady Gaga', 'レディーガガ', 'レディー・ガガ',
        'Bruno Mars', 'ブルーノマーズ', 'ブルーノ・マーズ',
        'The Weeknd', 'ザウィークエンド',
        'Dua Lipa', 'デュアリパ', 'デュア・リパ',
        'Olivia Rodrigo', 'オリヴィアロドリゴ',
        'Bad Bunny', 'バッドバニー',
        'Eminem', 'エミネム',
        'Kanye West', 'カニエウェスト', 'カニエ・ウェスト',
        'Rihanna', 'リアーナ',
        'Adele', 'アデル',
        
        # 海外俳優
        'Tom Cruise', 'トムクルーズ', 'トム・クルーズ',
        'Leonardo DiCaprio', 'レオナルドディカプリオ',
        'Brad Pitt', 'ブラッドピット', 'ブラッド・ピット',
        'Johnny Depp', 'ジョニーデップ', 'ジョニー・デップ',
        
        # 海外政治家
        'Donald Trump', 'ドナルドトランプ', 'トランプ大統領',
        'Joe Biden', 'ジョーバイデン', 'バイデン大統領',
        'Barack Obama', 'バラクオバマ', 'オバマ大統領',
        'Elon Musk', 'イーロンマスク', 'イーロン・マスク',
        
        # 韓国芸能人
        'BLACKPINK', '블랙핑크',
        '손흥민', 'ソンフンミン',
        
        # 中国芸能人
        '周杰伦', 'ジェイチョウ',
        '成龙', 'ジャッキーチェン', 'ジャッキー・チェン', 'Jackie Chan',
    ]
    
    def __init__(self):
        """フィルターの初期化"""
        # 日本語・中国語の禁止ワード（部分一致でチェック）
        self.prohibited_words_substring = set()
        
        for word in self.PROHIBITED_WORDS_JA:
            self.prohibited_words_substring.add(word.lower())
            # ひらがな/カタカナ変換も追加
            self.prohibited_words_substring.add(self._hiragana_to_katakana(word).lower())
            self.prohibited_words_substring.add(self._katakana_to_hiragana(word).lower())
        
        for word in self.PROHIBITED_WORDS_ZH:
            self.prohibited_words_substring.add(word.lower())
        
        # 英語の禁止ワード（単語境界でチェック → 部分一致を防ぐ）
        self.prohibited_words_en_patterns = []
        for word in self.PROHIBITED_WORDS_EN:
            # スペースを含むフレーズはそのまま、単語は\bで囲む
            if ' ' in word:
                pattern = re.compile(re.escape(word.lower()), re.IGNORECASE)
            else:
                pattern = re.compile(r'\b' + re.escape(word.lower()) + r'\b', re.IGNORECASE)
            self.prohibited_words_en_patterns.append((word.lower(), pattern))
        
        # 有名人名を小文字でセット化
        self.celebrity_names = set()
        for name in self.CELEBRITY_NAMES:
            self.celebrity_names.add(name.lower())
        
        # 正規表現パターンをコンパイル
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.PROHIBITED_PATTERNS
        ]
        
        # ユーザー名用禁止ワードを小文字でセット化
        self.prohibited_username_words = set()
        for word in self.PROHIBITED_USERNAME_WORDS:
            self.prohibited_username_words.add(word.lower())
            # 日本語の場合はひらがな/カタカナ変換も追加
            if not word.isascii():
                self.prohibited_username_words.add(self._hiragana_to_katakana(word).lower())
                self.prohibited_username_words.add(self._katakana_to_hiragana(word).lower())
        
        # ユーザー名用短い禁止ワード（除外リスト付き）を初期化
        self.prohibited_username_short_words = {}
        for word, exceptions in self.PROHIBITED_USERNAME_SHORT_WORDS.items():
            self.prohibited_username_short_words[word.lower()] = [e.lower() for e in exceptions]
        
        # ユーザー名用正規表現パターンをコンパイル
        self.compiled_username_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.PROHIBITED_USERNAME_PATTERNS
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
        
        # 日本語・中国語の禁止ワードチェック（部分一致・無条件でブロック）
        for word in self.prohibited_words_substring:
            if word in text_lower:
                detected_words.append(word)
        
        # 英語の禁止ワードチェック（単語境界で判定・部分一致を防ぐ）
        for word, pattern in self.prohibited_words_en_patterns:
            if pattern.search(text_lower):
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
        
        # 有名人・著名人の名前チェック
        celebrity_detected = self._check_celebrity_names(text_lower)
        if celebrity_detected:
            detected_words.extend(celebrity_detected)
        
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
    
    def _check_celebrity_names(self, text_lower):
        """テキストに有名人・著名人の名前が含まれるかチェック"""
        detected = []
        for name in self.celebrity_names:
            if len(name) <= 2:
                # 短い名前（2文字以下）は単語境界チェック（誤検出防止）
                # 日本語の場合は前後の文字を考慮
                idx = text_lower.find(name)
                if idx >= 0:
                    # 英字の場合は単語境界チェック
                    if name.isascii():
                        pattern = r'\b' + re.escape(name) + r'\b'
                        if re.search(pattern, text_lower):
                            detected.append(name)
                    # 日本語2文字の場合はスキップ（誤検出が多い）
            else:
                if name in text_lower:
                    detected.append(name)
        return detected
    
    def _get_violation_message(self, detected_words, language='ja'):
        """違反メッセージを生成"""
        # 有名人名が検出されたかチェック
        has_celebrity = any(w in self.celebrity_names for w in detected_words)
        
        if has_celebrity:
            return self._get_celebrity_violation_message(language)
        
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
    
    def _get_celebrity_violation_message(self, language='ja'):
        """有名人名検出時の違反メッセージを生成"""
        messages = {
            'ja': (
                '著名人・有名人の名前が検出されました。\n\n'
                '実在する人物の名前を含むコンテンツは、肖像権・パブリシティ権の'
                '侵害となる可能性があるため、楽曲生成に使用できません。\n\n'
                '人物名を含まないコンテンツでご利用ください。'
            ),
            'en': (
                'Celebrity or public figure names have been detected.\n\n'
                'Content containing names of real people cannot be used for song generation '
                'due to potential violations of personality rights and publicity rights.\n\n'
                'Please use content that does not include personal names.'
            ),
            'zh': (
                '检测到名人姓名。\n\n'
                '包含真实人物姓名的内容可能侵犯肖像权和公开权，'
                '不能用于歌曲生成。\n\n'
                '请使用不包含人物姓名的内容。'
            ),
            'es': (
                'Se han detectado nombres de celebridades o figuras públicas.\n\n'
                'El contenido que contiene nombres de personas reales no se puede usar para la generación '
                'de canciones debido a posibles violaciones de derechos de imagen.\n\n'
                'Por favor, use contenido que no incluya nombres personales.'
            ),
            'de': (
                'Es wurden Namen von Prominenten oder öffentlichen Personen erkannt.\n\n'
                'Inhalte mit Namen realer Personen können aufgrund möglicher Verletzungen von '
                'Persönlichkeitsrechten nicht für die Songgenerierung verwendet werden.\n\n'
                'Bitte verwenden Sie Inhalte ohne Personennamen.'
            ),
            'pt': (
                'Foram detectados nomes de celebridades ou figuras públicas.\n\n'
                'Conteúdo contendo nomes de pessoas reais não pode ser usado para geração de músicas '
                'devido a possíveis violações de direitos de imagem.\n\n'
                'Por favor, use conteúdo que não inclua nomes pessoais.'
            ),
        }
        return messages.get(language, messages['ja'])
    
    def get_violation_message_by_language(self, language='ja'):
        """言語に応じた違反メッセージを取得"""
        return self._get_violation_message([], language)
    
    def check_username(self, username):
        """
        ユーザー名に不適切な語句が含まれていないかチェック
        
        ユーザー名は学術文脈がないため、禁止ワードは無条件でブロック。
        リートスピーク（数字・記号での代替）パターンも検出。
        
        Args:
            username: チェックするユーザー名
            
        Returns:
            dict: {
                'is_inappropriate': bool,
                'detected_words': list,
                'message': str
            }
        """
        if not username:
            return {
                'is_inappropriate': False,
                'detected_words': [],
                'message': ''
            }
        
        detected_words = []
        username_lower = username.lower().strip()
        
        # スペース・アンダースコア・ハイフン・ドットを除去して連結版も作成
        username_stripped = re.sub(r'[\s_\-\.]+', '', username_lower)
        
        # 禁止ワードチェック（長い語 - 部分一致でOK）
        for word in self.prohibited_username_words:
            if word in username_lower or word in username_stripped:
                detected_words.append(word)
        
        # 短い禁止ワードチェック（除外リスト付き）
        for word, exceptions in self.prohibited_username_short_words.items():
            if word in username_lower or word in username_stripped:
                # 除外リストに該当する場合はスキップ
                is_exception = False
                for exc in exceptions:
                    if exc in username_lower:
                        is_exception = True
                        break
                if not is_exception:
                    detected_words.append(word)
        
        # 正規表現パターンチェック
        for compiled in self.compiled_username_patterns:
            if compiled.search(username_lower) or compiled.search(username_stripped):
                detected_words.append(f'pattern:{compiled.pattern}')
        
        # 重複除去
        detected_words = list(set(detected_words))
        
        if detected_words:
            logger.warning(f"Inappropriate username detected: '{username}' -> {detected_words}")
            return {
                'is_inappropriate': True,
                'detected_words': detected_words,
                'message': 'このユーザー名は使用できません。'
            }
        
        return {
            'is_inappropriate': False,
            'detected_words': [],
            'message': ''
        }


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


def check_username_for_inappropriate_content(username):
    """
    ユーザー名の不適切コンテンツをチェックする便利関数
    
    Args:
        username: チェックするユーザー名
        
    Returns:
        dict: チェック結果
    """
    return content_filter.check_username(username)
