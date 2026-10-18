import urllib.request, json

CLL1_HOST='192.168.0.106'
CLL1_HTTP_PORT=8766

# Test login
data = json.dumps({"username": "admin", "password": "admin"}).encode()
req = urllib.request.Request(f"http://{CLL1_HOST}:{CLL1_HTTP_PORT}/api/login", data=json.dumps({"username": "admin", "password": "admin"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
resp = urllib.request.urlopen(req, timeout=10)
result = json.loads(resp.read().decode())
TOKEN = result["session"]
print("Login OK:", TOKEN[:30]+"...")

# Check available endpoints
endpoints = ['/api/status', '/api/metrics', '/api/users', '/api/files', '/api/chat', '/api/exec', '/api/status', '/api/health', '/api/capabilities', '/api/users/cleanup']
for ep in endpoints:
    try:
        req = urllib.request.Request(f'http://192.168.0.106:8766{ep}', headers={"Authorization": f"Bearer {TOKEN}"})
        resp = urllib.request.urlopen(req, timeout=5)
        result = json.loads(resp.read().decode())
        print(f'{ep}: OK - {result.get("ok", "?")}')
    except Exception as e:
        print(f'{ep}: ERROR - {type(e).__name__}: {e}')