import argparse
import json
import re
from collections import Counter
from pathlib import Path


def extract_bracketed_terms(text):
    pattern = r'【([^】]+)】'
    return [m.strip() for m in re.findall(pattern, text) if m.strip()]


def normalize_term(term):
    cleaned = term.strip()
    cleaned = re.sub(r'^[\s\-・,、。:：;；\(\)\[\]「」『』【】]+', '', cleaned)
    cleaned = re.sub(r'[\s\-・,、。:：;；\(\)\[\]「」『』【】]+$', '', cleaned)
    if len(cleaned) < 2:
        return ''
    return cleaned


def score_keywords(text, max_keywords=20):
    scores = Counter()

    for term in extract_bracketed_terms(text):
        n = normalize_term(term)
        if n:
            scores[n] += 8

    plain = re.sub(r'[【】]', '', text)
    lines = [line.strip() for line in plain.splitlines() if line.strip()]

    heading_patterns = (
        r'^第[0-9一二三四五六七八九十]+',
        r'^[0-9]+[\.|\)]',
        r'^(ポイント|重要|要点|まとめ|公式|定義|用語)',
    )

    token_pattern = re.compile(
        r'[A-Za-z][A-Za-z0-9_\-\+\.]{1,}'
        r'|[0-9]{2,4}年'
        r'|[0-9]+(?:\.[0-9]+)?(?:%|℃|cm|mm|kg|g|m|km|L|ml|Hz|V|A)'
        r'|[ァ-ヴー]{2,}'
        r'|[一-龥]{2,}'
    )

    for line in lines:
        is_heading = any(re.search(p, line) for p in heading_patterns)
        for m in token_pattern.findall(line):
            n = normalize_term(m)
            if not n:
                continue
            if re.fullmatch(r'[ぁ-ん]{2,3}', n):
                continue
            scores[n] += 2 if is_heading else 1

    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:max_keywords]


def build_record(path, max_keywords=20):
    text = path.read_text(encoding='utf-8', errors='ignore')
    ranked = score_keywords(text, max_keywords=max_keywords)
    return {
        'source_file': str(path),
        'char_count': len(text),
        'highlighted_terms': extract_bracketed_terms(text),
        'ranked_keywords': [{'term': term, 'score': score} for term, score in ranked],
        'text': text,
    }


def main():
    parser = argparse.ArgumentParser(
        description='OCRテキスト群から重要語スコア付きJSONLデータセットを作成'
    )
    parser.add_argument('--input-dir', required=True, help='入力ディレクトリ（.txt再帰探索）')
    parser.add_argument('--output', required=True, help='出力JSONLファイル')
    parser.add_argument('--max-keywords', type=int, default=20, help='1ページあたり最大キーワード数')
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(input_dir.rglob('*.txt'))
    if not txt_files:
        raise SystemExit(f'No .txt files found under: {input_dir}')

    count = 0
    with output_path.open('w', encoding='utf-8') as f:
        for file_path in txt_files:
            rec = build_record(file_path, max_keywords=args.max_keywords)
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            count += 1

    print(f'Wrote {count} records to {output_path}')


if __name__ == '__main__':
    main()
