"""Remove all _meta.legacy_trained flags from training data (LLM reset)"""
import json
import os

data_path = os.path.join(os.path.dirname(__file__), "data", "lyrics_training_data.json")

with open(data_path, "r", encoding="utf-8") as f:
    data = json.load(f)

count = 0
for record in data:
    meta = record.get("_meta", {})
    if "legacy_trained" in meta:
        del meta["legacy_trained"]
        count += 1
    # Remove empty _meta
    if "_meta" in record and not record["_meta"]:
        del record["_meta"]

with open(data_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Removed legacy_trained from {count} records")
print(f"Total records: {len(data)}")
