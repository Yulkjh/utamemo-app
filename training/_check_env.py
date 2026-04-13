import os
import json

# Check API key
api_key = os.getenv("UTAMEMO_TRAINING_API_KEY", "")
print(f"API_KEY set: {bool(api_key)}")

# Check CUDA
try:
    import torch
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB")
except ImportError:
    print("torch not installed")

# Check reviewed data count
data_path = os.path.join(os.path.dirname(__file__), "data", "lyrics_training_data.json")
with open(data_path, "r", encoding="utf-8") as f:
    data = json.load(f)
total = len(data)
legacy = sum(1 for x in data if x.get("_meta", {}).get("legacy_trained"))
print(f"Total records: {total}")
print(f"Legacy trained: {legacy}")
print(f"Non-legacy (new): {total - legacy}")
