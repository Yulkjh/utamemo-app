import json
import sys

f = open('data/lyrics_training_data.json', 'r', encoding='utf-8')
data = json.load(f)
f.close()

print(f"Total examples: {len(data)}")
for i, d in enumerate(data):
    topic = d["input"][:25]
    if "pop" in d["instruction"]:
        genre = "pop"
    elif "rock" in d["instruction"]:
        genre = "rock"
    else:
        genre = "hiphop"
    print(f"  {i+1}. [{genre}] {topic}...")
print("All OK!")
