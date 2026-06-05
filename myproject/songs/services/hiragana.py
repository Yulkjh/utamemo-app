"""ひらがな変換モジュール"""
import logging

from .text_processing import GEMINI_SAFETY_SETTINGS, _safe_get_response_text, _get_gemini_model

logger = logging.getLogger(__name__)


def convert_lyrics_to_hiragana_with_context(lyrics):
    """Gemini AIを使って文脈を考慮しながら歌詞をひらがなに変換

    漢字の読みを正確にするために、文脈を考慮して変換する。
    例: 「今日」→「きょう」vs「こんにち」、「明日」→「あした」vs「あす」
    """
    model = _get_gemini_model()

    if not model:
        # Geminiが使えない場合はそのまま返す
        logger.warning("Gemini not available for hiragana conversion")
        return lyrics

    try:
        prompt = f"""以下の日本語の歌詞を、漢字を全てひらがなに変換してください。

1. 文脈を考慮して、正しい読み方を選んでください
   - 「今日」→ 歌詞では通常「きょう」
   - 「明日」→ 歌詞では通常「あした」または「あす」（文脈による）
   - 「明後日」→ 歌詞では通常「あさって」
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

2. 外国の地名・国名は現代の一般的な読み方を使用（漢文読みにしない！）
   - 「台北」→「たいぺい」（×「だいほく」は不可）
   - 「台湾」→「たいわん」
   - 「北京」→「ぺきん」（×「ほくけい」は不可）
   - 「上海」→「しゃんはい」
   - 「南京」→「なんきん」
   - 「香港」→「ほんこん」
   - 「韓国」→「かんこく」
   - 「朝鮮」→「ちょうせん」
   - 外国地名は日本語として定着している現代の読みを優先すること

3. 数字は日本語の読みに変換
   - 「1」→「いち」、「2」→「に」、「10」→「じゅう」、「100」→「ひゃく」

4. 化学式・元素記号はアルファベットを1文字ずつ読む
   - 「Na」→「えぬえー」（ナトリウムが後に続く場合：「えぬえー ナトリウム」）
   - 「Cl」→「しーえる」
   - 「NaCl」→「えぬえー しーえる」
   - 「CO2」→「しーおーつー」
   - 「H2O」→「えいちつーおー」
   - 「O2」→「おーつー」
   - 「Fe」→「えふいー」
   - 「Ca」→「しーえー」
   - 「Mg」→「えむじー」
   - 「Cu」→「しーゆー」
   - 「NaOH」→「えぬえー おーえいち」
   - 「HCl」→「えいちしーえる」
   - 「C6H12O6」→「しーろく えいちじゅうに おーろく」
   - 化学式中の数字は日本語読み（「2」→「つー」ではなく文脈による：化学式では「つー」、年号では「に」）
   - 元素記号の後にカタカナの元素名が続く場合、両方そのまま読む
     例：「Na ナトリウム」→「えぬえー ナトリウム」

5. 助詞の発音変換（重要！歌の発音に合わせる）
   - 助詞の「は」→「わ」に変換（例：「私は」→「わたしわ」、「それは」→「それわ」）
   - 助詞の「へ」→「え」に変換（例：「海へ」→「うみえ」、「空へ」→「そらえ」）
   - 助詞の「を」→「お」に変換（例：「夢を」→「ゆめお」）
   ※ 助詞以外の「は」「へ」「を」はそのまま（例：「はな」→「はな」、「へや」→「へや」）

6. セクションラベル（[Verse], [Chorus], [Bridge]など）はそのまま保持

7. 英語の一般的な単語はそのまま保持（化学式・元素記号は上記ルールで変換）

8. 改行や空行は忠実に保持

9. カタカナはそのまま保持

10. 出力は変換後の歌詞のみ（説明や前置きは不要）

【変換する歌詞】
{lyrics}

【出力】（変換後の歌詞のみを出力）"""

        response = model.generate_content(prompt, safety_settings=GEMINI_SAFETY_SETTINGS)

        text = _safe_get_response_text(response)
        if text:
            converted = text.strip()
            # 余計な説明を除去
            if converted.startswith('```'):
                lines = converted.split('\n')
                converted = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])

            logger.info(f"Gemini hiragana conversion successful: {len(lyrics)} -> {len(converted)} chars")
            return converted
        else:
            logger.warning("Gemini returned empty response for hiragana conversion")
            return lyrics

    except Exception as e:
        logger.error(f"Gemini hiragana conversion error: {e}")
        return lyrics
