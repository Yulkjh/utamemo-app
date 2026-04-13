import requests
import sys

API_KEY = sys.argv[1]
BASE_URL = "https://utamemo.onrender.com"
url = f"{BASE_URL}/api/training/reviewed/"

resp = requests.get(url, headers={"X-Training-Api-Key": API_KEY}, timeout=30)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    indices = data.get("reviewed_indices", [])
    print(f"Reviewed (untrained) indices: {len(indices)} records")
    print(f"Indices: {indices}")
else:
    print(f"Error: {resp.text}")
