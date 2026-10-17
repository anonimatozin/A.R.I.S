import urllib.request, json, os

CLL1_HOST = "192.168.0.106"
CLL1_HTTP_PORT = 8766

# Test login
data = json.dumps({"username": "admin", "password": "admin"}).encode("utf-8")
req = urllib.request.Request(f"http://{CLL1_HOST}:{CLL1_HTTP_PORT}/api/login", data=json.dumps({"username": "admin", "password": "admin"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
resp = urllib.request.urlopen(req, timeout=10)
result = json.loads(resp.read().decode("utf-8"))
TOKEN = result["session"]
print(f"Login OK: {TOKEN[:30]}...")

# Test file existence via /api/exec
print("\nTesting file existence...")
try:
    req = urllib.request.Request(f"http://{CLL1_HOST}:{CLL1_HTTP_PORT}/api/exec", data=json.dumps({"command": "ls -la /data/data/com.termux/files/home/cll1/data/users.json"}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=10)
    result = json.loads(resp.read().decode("utf-8"))
    print(f"LS result: {result}")
except Exception as e:
    print(f"LS error: {type(e).__name__}: {e}")

# Check if data directory exists
print("\nChecking data directory...")
try:
    req = urllib.request.Request(f"http://192.168.0.106:8766/api/exec", data=json.dumps({"command": "ls -la /data/data/com.termux/files/home/cll1/data"}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=10)
    result = json.loads(resp.read().decode("utf-8"))
    print(f"Data dir: {result}")
except Exception as e:
    print(f"Data dir error: {type(e).__name__}: {e}")