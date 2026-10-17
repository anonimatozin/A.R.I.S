import sys, os
sys.path.insert(0, r"C:\Users\Administrator\Documents\Default Project\ARIS")
os.chdir(r"C:\Users\Administrator\Documents\Default Project\ARIS")

import urllib.request, json

CLL1_HOST = "192.168.0.106"
CLL1_HTTP_PORT = 8766

# Test login
data = json.dumps({"username": "admin", "password": "admin"}).encode("utf-8")
req = urllib.request.Request(f"http://{CLL1_HOST}:{CLL1_HTTP_PORT}/api/login", data=data, headers={"Content-Type": "application/json"}, method="POST")
resp = urllib.request.urlopen(req, timeout=10)
result = json.loads(resp.read().decode("utf-8"))
TOKEN = result["session"]
print(f"Login OK: {TOKEN[:30]}...")

# Test with detailed error capture
print("\nTesting user creation with detailed error capture...")
user_data = json.dumps({"action": "create", "username": "test_debug", "password": "pass123", "role": "operador"}).encode("utf-8")
req = urllib.request.Request(f"http://{CLL1_HOST}:{CLL1_HTTP_PORT}/api/users", data=user_data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}, method="POST")

try:
    resp = urllib.request.urlopen(req, timeout=10)
    result = json.loads(resp.read().decode("utf-8"))
    print(f"Create user: {result}")
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.read().decode()}")
except urllib.error.URLError as e:
    print(f"URL Error: {e.reason}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")

# Also test with a short timeout to see if it's hanging
print("\nTesting with short timeout...")
try:
    req = urllib.request.Request(f"http://192.168.0.106:8766/api/users", data=json.dumps({"action": "create", "username": "test2", "password": "pass"}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=3)
    result = json.loads(resp.read().decode("utf-8"))
    print(f"Create user: {result}")
except urllib.error.URLError as e:
    print(f"URL Error (timeout?): {e.reason}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")