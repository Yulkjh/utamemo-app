import json, re, sys

d = json.load(open('training/data/lyrics_training_data.json', 'r', encoding='utf-8'))

n = int(sys.argv[1]) if len(sys.argv) > 1 else 5

print(f'合計: {len(d)}件 / 最新{n}件を表示\n')

for i, x in enumerate(d[-n:]):
    idx = len(d) - n + i + 1
    inst = x.get('instruction', '')
    m = re.search(r'から(\w+)ジャンルの歌詞', inst)
    genre = m.group(1) if m else '?'
    print(f'{"="*60}')
    print(f'# {idx}件目 (ジャンル: {genre})')
    print(f'{"="*60}')
    print(f'\n【学習テーマ (input)】')
    print(x.get('input', '')[:300])
    print(f'\n【生成歌詞 (output)】')
    print(x.get('output', ''))
    print()
