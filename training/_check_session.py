import urllib.request, json

url = 'https://utamemo.com/api/training/update/'
api_key = 'fc07b6d36ebebc9141bf37a5ceb0e8fe5656f55cfa8a3f0b5b95f329eca6e12f'
payload = json.dumps({'poll': True, 'status': 'idle'}).encode()
req = urllib.request.Request(
    url,
    data=payload,
    headers={
        'Content-Type': 'application/json',
        'X-Training-Api-Key': api_key,
    },
    method='POST',
)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    print(resp.read().decode())
except Exception as e:
    print(f"Error: {e}")
