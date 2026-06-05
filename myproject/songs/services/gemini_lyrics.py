"""Gemini 歌詞生成モジュール"""
import re
import time
import logging

from django.conf import settings

from .cache import _get_cache_key, _get_cached_response, _set_cached_response
from .text_processing import (
    GEMINI_SAFETY_SETTINGS,
    _safe_get_response_text,
    _get_gemini_model,
    _build_importance_instruction_block,
    _is_explosive_lyrics_mode,
    remove_circled_numbers,
)
from .hiragana import convert_lyrics_to_hiragana_with_context

logger = logging.getLogger(__name__)


class GeminiLyricsGenerator:
    """Gemini を使用した歌詞生成クラス"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'GEMINI_API_KEY', None)
        self.model = _get_gemini_model()
    
    def generate_lyrics(self, extracted_text, title="", genre="pop", language_mode="japanese", custom_request=""):
        """抽出されたテキストから歌詞を生成（漢字のまま返す）
        
        最適化: 同一入力に対するレスポンスをキャッシュ（1時間有効）
        
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
        
        # キャッシュキーを生成（全パラメータを含む）
        cache_input = f"{extracted_text}|{genre}|{language_mode}|{custom_request}"
        cache_key = _get_cache_key(cache_input, 'lyrics')
        
        # キャッシュをチェック
        cached = _get_cached_response(cache_key)
        if cached:
            logger.info("GeminiLyricsGenerator: Returning cached lyrics")
            return cached
        
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
            
            response = self.model.generate_content(prompt, safety_settings=GEMINI_SAFETY_SETTINGS)
            
            raw_lyrics = _safe_get_response_text(response)
            
            if raw_lyrics:
                
                lyrics = self._extract_clean_lyrics(raw_lyrics)
                
                logger.info(f"Gemini lyrics generation successful! Generated {len(lyrics)} characters")
                
                # キャッシュに保存（1時間有効 - 再生成を妨げないため短めに）
                _set_cached_response(cache_key, lyrics, ttl=3600)
                
                return lyrics
            else:
                logger.error("Failed to generate lyrics")
                raise Exception("Failed to generate lyrics")
                
        except Exception as e:
            logger.info(f"Gemini lyrics generation error: {e}")
            raise

    def generate_lyrics_from_images(self, images, title="", genre="pop", language_mode="japanese", custom_request="", extracted_text=""):
        """画像を直接Geminiに渡して歌詞を生成（OCR+歌詞生成を一発で行う）
        
        OCRを挟まず画像から直接歌詞を生成することで:
        - OCR段階での情報ロスを防ぐ
        - 強調表現・図表・レイアウトをGeminiが直接理解できる
        - APIコール数が半減する（OCR+生成 → 生成のみ）
        
        Args:
            images: PIL.Image のリスト
            extracted_text: 既にOCRで抽出済みのテキスト（補助情報として使用、空でもOK）
            title, genre, language_mode, custom_request: 従来と同じ
        
        Returns:
            str: 生成された歌詞
        """
        if not self.model:
            raise Exception("Gemini APIが設定されていません。管理者に連絡してください。")
        
        if not images:
            raise Exception("画像が指定されていません。")
        
        try:
            # 言語モード別のプロンプトを取得
            # extracted_textに画像参照指示を追加
            image_instruction = "（※ 添付画像の内容を直接読み取って歌詞を作成してください。画像内で一部の語句だけが下線・太字・マーカー・色付き（赤字・青字等）で他と異なる見た目になっている場合、それは強調された重要語句です。必ず歌詞に含めてください。全体が同じ色やスタイルの場合は強調ではありません。）"
            
            if extracted_text:
                combined_text = f"{image_instruction}\n\n■ 画像から事前に抽出されたテキスト（参考）\n{extracted_text}"
            else:
                combined_text = image_instruction
            
            if language_mode == "english_vocab":
                prompt = self._get_english_vocab_prompt(combined_text, genre, custom_request)
            elif language_mode == "english":
                prompt = self._get_english_prompt(combined_text, genre, custom_request)
            elif language_mode == "chinese":
                prompt = self._get_chinese_prompt(combined_text, genre, custom_request)
            elif language_mode == "chinese_vocab":
                prompt = self._get_chinese_vocab_prompt(combined_text, genre, custom_request)
            else:
                prompt = self._get_japanese_prompt(combined_text, genre, custom_request)
            
            # プロンプト + 画像リストをGeminiに一括送信
            content_parts = [prompt] + list(images)
            
            logger.info(f"generate_lyrics_from_images: Sending {len(images)} image(s) + prompt to Gemini")
            
            # リトライロジック（最大3回）
            max_retries = 3
            last_error = None
            for attempt in range(max_retries):
                try:
                    response = self.model.generate_content(
                        content_parts,
                        safety_settings=GEMINI_SAFETY_SETTINGS,
                    )
                    
                    raw_lyrics = _safe_get_response_text(response)
                    
                    if raw_lyrics:
                        lyrics = self._extract_clean_lyrics(raw_lyrics)
                        logger.info(f"generate_lyrics_from_images: Success! Generated {len(lyrics)} chars (attempt {attempt + 1})")
                        return lyrics
                    
                    last_error = "Empty response"
                    logger.warning(f"generate_lyrics_from_images: Empty response on attempt {attempt + 1}")
                    
                except Exception as api_error:
                    last_error = str(api_error)
                    logger.warning(f"generate_lyrics_from_images: API error on attempt {attempt + 1}: {api_error}")
                
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
            
            # 全リトライ失敗 → テキストベースにフォールバック
            if extracted_text:
                logger.warning("generate_lyrics_from_images: All image attempts failed, falling back to text-based generation")
                return self.generate_lyrics(extracted_text, title=title, genre=genre, language_mode=language_mode, custom_request=custom_request)
            
            raise Exception(f"画像からの歌詞生成に失敗しました: {last_error}")
            
        except Exception as e:
            logger.error(f"generate_lyrics_from_images error: {e}")
            raise

    def _get_english_vocab_prompt(self, extracted_text, genre, custom_request=""):
        """日本語で英単語を覚えるためのプロンプト"""
        custom_section = ""
        if custom_request:
            custom_section = f"""
■ ユーザーからの追加リクエスト（重要！必ず反映してください）
{custom_request}
"""
        return f"""あなたはエグスプロージョン（「本能寺の変」で有名）のように、英単語をノリノリのリズムに乗せて覚えさせるプロの作詞家です。
聴いた人が思わず口ずさんでしまい、気づいたら英単語を覚えているような、キャッチーで中毒性のある{genre}ジャンルの日本語歌詞を作成してください。

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

【★ 楽曲スタイル要件（最重要）】
・エグスプロージョンの「本能寺の変」のようにテンポよく畳みかけるリズム感
・日本語がメインで、英単語が自然に混ざる
・ラップ調・語呂合わせ・掛け合いも積極活用
・一度聞いたら頭から離れないキャッチーなフレーズ
・堅苦しさゼロ — 楽しい歌として成立させる
・全体として約180秒（3分）相当の分量（歌詞行数40〜60行を目安に）
・韻を踏むことを意識する

■ 出力フォーマット（厳守 — 3分の楽曲に十分な量を書くこと）
[Verse 1]
（英単語と日本語訳を含む歌詞、6〜10行）

[Chorus]
（最重要英単語を繰り返す、4〜6行）

[Verse 2]
（歌詞、6〜10行）

[Chorus]
（繰り返し）

[Verse 3]
（さらに英単語を追加、6〜10行）

[Bridge]
（補足、4〜6行）

[Chorus]
（最終）

■ 厳守事項
・歌詞のみを出力すること
・説明文、コメント、解説は一切書かない
・丸数字（①②③、❶❷❸など）や番号記号は絶対に使わない
・元テキストにある番号記号は歌詞に含めず、内容だけを使う
・「歌で覚えよう」「覚えよう」「覚えちゃおう」「暗記しよう」「マスターしよう」など、学習行為を促すメタ的な表現は使わない。学習内容そのものを歌詞にすること。
・「全てが大事」「忘れずに」「大切だよ」「しっかり覚えて」「ポイントだ」「テストに出る」など、学習への心構えや励ましのフレーズも使わない。
"""

    def _get_english_prompt(self, extracted_text, genre, custom_request=""):
        """English mode - Pure English lyrics for native English speakers"""
        custom_section = ""
        if custom_request:
            custom_section = f"""

■ ADDITIONAL USER REQUEST (IMPORTANT! Must be reflected in the lyrics)
{custom_request}
"""
        return f"""You are an expert songwriter who turns textbook content into irresistibly catchy, viral-worthy songs — think Schoolhouse Rock ("Conjunction Junction"), Animaniacs ("Yakko's World"), or the rhythm and energy of educational rap battles. Your songs make people sing along without even trying, and before they know it, the content is stuck in their head forever.

Create {genre} style lyrics in PURE ENGLISH from the following text.

■ Text Content
{extracted_text}
{custom_section}
■ ABSOLUTE REQUIREMENT
・Write 100% in English - NO Japanese, Chinese, or any other language
・Every word must be English
・This is for native English speakers to memorize personal information

■ Songwriting Techniques for Memory

【★ MAKE IT ADDICTIVELY CATCHY (TOP PRIORITY)】
・Think Schoolhouse Rock energy — fun, fast-paced, impossible not to sing along
・Use rhyming patterns aggressively (AABB, ABAB) — every line should rhyme or near-rhyme
・Create hooks so catchy they get stuck in your head for days
・Use rap-style rhythmic flow, call-and-response, wordplay, and clever phrasing
・The Chorus must be an earworm — a short, punchy, repeatable chant
・Zero textbook vibes — it should feel like a real hit song that happens to teach you something

【Key Information Focus】
・Turn facts into singable lines
・Make numbers and dates rhythmic
・Include terms wrapped in 【】brackets (these are emphasized/highlighted/colored terms) as highest priority
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
・About 180 seconds (3 minutes) length (aim for 40-60 lyric lines total)
・Repeat keywords 2-4 times
・Clear pronunciation and ear-catching phrases
・Use rhyming patterns to make lines memorable

■ Output Format (Strict — write enough for a 3-minute song)
[Verse 1]
(English lyrics, 6-10 lines)

[Chorus]
(catchy hook with key info repeated, 4-6 lines)

[Verse 2]
(continue the story, 6-10 lines)

[Chorus]
(repeat the hook)

[Verse 3]
(deeper content or additional info, 6-10 lines)

[Bridge]
(summary or twist, 4-6 lines)

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
・Do NOT use meta-phrases like "let's memorize", "let's learn", "let's study", "time to learn", "remember this". Just present the actual content as lyrics.
・Do NOT use filler encouragement like "everything matters", "don't forget", "this is important", "key point", "it'll be on the test". Only concrete facts, terms, and definitions.
"""

    def _get_chinese_prompt(self, extracted_text, genre, custom_request=""):
        """Chinese mode - Pure Chinese lyrics for native Chinese speakers"""
        custom_section = ""
        if custom_request:
            custom_section = f"""

■ 用户额外要求（重要！必须在歌词中体现）
{custom_request}
"""
        return f"""你是一位像"凤凰传奇"或"洗脑神曲"风格的天才作词人，擅长把教科书内容变成让人听一遍就忘不掉的洗脑歌曲。
你的歌词节奏感强、朗朗上口、有魔性般的感染力。听众会不自觉地跟唱，在不知不觉中就记住了所有内容。
请创作{genre}风格的纯中文歌词。

■ 文本内容
{extracted_text}
{custom_section}
■ 绝对要求
・100%使用中文 - 绝对不能混入日语、英语或其他语言
・每一个字都必须是中文
・这是为中文母语者记忆个人信息而设计的

■ 记忆歌词创作技巧

【★ 洗脑级别的上头感（最重要）】
・像"凤凰传奇"一样节奏鲜明、一听就上头
・大量使用押韵 — 每一行都要押韵或近似押韵
・说唱节奏、顺口溜、对口相声式的节奏感都可以用
・副歌必须是一个魔性的、可以无限循环的洗脑段落
・零教科书感 — 必须是一首好听的歌，只是恰好教了你知识
・小学生到大学生都能不自觉地跟着唱

【关键信息聚焦】
・将事实转化为可唱的歌词
・让数字和日期有节奏感
・文本中用【】括起来的词语（即下划线、粗体、荧光笔标记、彩色文字的重点内容）必须优先包含在歌词中
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
・约180秒（3分钟）长度（歌词行数40-60行为目标）
・关键词重复2-4次
・发音清晰，短语令人印象深刻
・注意押韵以增强记忆效果

■ 输出格式（严格遵守 — 写出足够3分钟歌曲的内容）
[Verse 1]
（中文歌词，意义单位之间留空格，6-10行）

[Chorus]
（带有重复关键信息的朗朗上口的钩子，4-6行）

[Verse 2]
（继续故事，6-10行）

[Chorus]
（重复钩子）

[Verse 3]
（更深入的内容或补充信息，6-10行）

[Bridge]
（总结或转折，4-6行）

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
・禁止使用「用歌来记住吧」「记住吧」「学习吧」「背下来吧」等促进学习行为的元表达。只将学习内容本身写入歌词。
・禁止使用「都很重要」「别忘了」「很重要哦」「好好记住」「考试会考」等鼓励性空话。只写具体的事实、术语和定义。
"""

    def _get_chinese_vocab_prompt(self, extracted_text, genre, custom_request=""):
        """Chinese vocabulary mode - Pure Chinese lyrics for native Chinese speakers"""
        custom_section = ""
        if custom_request:
            custom_section = f"""

■ 用户额外要求（重要！必须在歌词中体现）
{custom_request}
"""
        return f"""你是一位像"凤凰传奇"或"洗脑神曲"风格的天才作词人，擅长把词汇内容变成让人听一遍就忘不掉的洗脑歌曲。
你的歌词节奏感强、朗朗上口、有魔性般的感染力。请创作{genre}风格的纯中文歌词，帮助记忆词汇和内容。

■ 文本内容
{extracted_text}
{custom_section}
■ 绝对要求
・100%使用中文 - 绝对不能混入日语、英语或其他语言
・每一个字都必须是中文
・这是为中文母语者记忆个人信息而设计的

■ 记忆歌词创作技巧

【★ 洗脑级别的上头感（最重要）】
・像"凤凰传奇"一样节奏鲜明、一听就上头
・大量使用押韵、说唱节奏、顺口溜
・副歌必须是魔性的洗脑段落
・零教科书感 — 必须是好听的歌
・使用自然的中文节奏和韵律

【词汇强调】
・重要词汇在副歌中重复3次以上
・使用容易记忆的短语
・关键概念要反复出现
・文本中用【】括起来的词语（即下划线、粗体、荧光笔标记、彩色文字的重点内容）必须优先包含在歌词中
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
・约180秒（3分钟）长度（歌词行数40-60行为目标）
・关键词重复2-4次
・发音清晰，短语令人印象深刻
・注意押韵以增强记忆效果

■ 输出格式（严格遵守 — 写出足够3分钟歌曲的内容）
[Verse 1]
（纯中文歌词，意义单位之间留空格，6-10行）

[Chorus]
（重复最重要的词汇 - 纯中文，4-6行）

[Verse 2]
（纯中文歌词，6-10行）

[Chorus]
（重复 - 纯中文）

[Verse 3]
（更深入的内容 - 纯中文，6-10行）

[Bridge]
（总结 - 纯中文，4-6行）

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
・禁止使用「用歌来记住吧」「记住吧」「学习吧」「背下来吧」等促进学习行为的元表达。只将学习内容本身写入歌词。
・禁止使用「都很重要」「别忘了」「很重要哦」「好好记住」「考试会考」等鼓励性空话。只写具体的事实、术语和定义。
"""

    def _get_japanese_prompt(self, extracted_text, genre, custom_request=""):
        """日本語モード（従来）のプロンプト"""
        custom_section = ""
        if custom_request:
            custom_section = f"""
■ ユーザーからの追加リクエスト（重要！必ず反映してください）
{custom_request}
"""
        importance_block = _build_importance_instruction_block(extracted_text)
        explosive_block = ""
        if _is_explosive_lyrics_mode(custom_request):
            explosive_block = """
【エグスプロージョン風スタイル（追加要件）】
・各Verseに1箇所以上、短い掛け声（例:「ハイ！」「ドン！」）を入れる
・コール&レスポンス（問い→即答）を2セット以上含める
・最重要語句は語感を揃えて反復し、体で覚えられるリズムを優先する
・奇抜さは維持しつつ、事実関係・用語の正確性は絶対に崩さない
"""
        return f"""あなたはエグスプロージョン（「本能寺の変」で有名）のように、教科書の内容をノリノリのリズムに乗せて歌にするプロの作詞家です。
聴いた人が思わず口ずさんでしまい、気づいたら内容を覚えているような、キャッチーで中毒性のある{genre}ジャンルの歌詞を作成してください。

■ テキスト内容
{extracted_text}
{custom_section}
{importance_block}
{explosive_block}

■ 歌詞の書き方ルール

【表記ルール】
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

【★ 歌としてのクオリティ（最重要）】
・エグスプロージョンの「本能寺の変」のように、テンポよく畳みかけるリズム感
・韻を踏むことを強く意識する（行末の母音を揃える）
・リズムに乗せやすいテンポ感を最重視 — ラップ調・語呂合わせ・掛け合いも積極活用
・口ずさみやすく、一度聞いたら頭から離れないキャッチーなフレーズ
・Chorusは「本能寺の変！本能寺の変！」のような中毒性のあるリフレインに
・小学生〜中学生でも思わずノリノリで口ずさめる楽しさ重視
・堅苦しさゼロ、教科書感ゼロ — あくまで「楽しい歌」として成立させる

【テキスト情報の取り込み】
・テキスト内で【】で囲まれた語句（下線・太字・マーカー・色付き文字で強調された内容）は最重要として必ず歌詞に含める
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
・テキストに書かれている情報のみを使用
・事実関係・用語の意味を正確に
・要点を過不足なく含める
・人物名・地名・用語の読み方を調べて正確に

【楽曲スタイル要件】
・キーワードを2〜4回繰り返す
・耳に残りやすいフレーズと明瞭な発音
・全体として約180秒（3分）相当の適切な分量
・歌詞行数は40〜60行を目安にする

■ 出力フォーマット（厳守 — 3分の楽曲に十分な量を書くこと）
[Verse 1]
（歌詞のみ、単語間にスペースを入れる、6〜10行）

[Chorus]
（最重要単語を繰り返すキャッチーな歌詞のみ、4〜6行）

[Verse 2]
（歌詞のみ、6〜10行）

[Chorus]
（最重要単語を再度繰り返す歌詞のみ）

[Verse 3]
（さらに深い内容や追加情報、6〜10行）

[Bridge]
（補足・まとめ・対比の歌詞のみ、4〜6行）

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
・「歌で覚えよう」「覚えよう」「覚えちゃおう」「暗記しよう」「マスターしよう」「学ぼう」「勉強しよう」など、学習行為そのものを促すメタ的な表現は使わない。学習内容そのものを歌詞にすること。
・「全てが大事」「忘れずに」「大切だよ」「しっかり覚えて」「ポイントだ」「テストに出る」など、学習への心構えや励ましのフレーズも使わない。具体的な事実・用語・定義だけを歌詞にすること。
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
            
            response = self.model.generate_content(prompt, safety_settings=GEMINI_SAFETY_SETTINGS)
            
            tags_text = _safe_get_response_text(response)
            if tags_text:
                tags = [tag.strip() for tag in tags_text.split(',') if tag.strip()]
                tags = list(dict.fromkeys(tags))[:10]
                logger.info(f"Generated tags: {tags}")
                return tags
            else:
                return []
                
        except Exception as e:
            logger.info(f"Tag generation error: {e}")
            return []
    
    def _extract_clean_lyrics(self, raw_text):
        """AIのレスポンスから純粋な歌詞部分だけを抽出"""
        
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
