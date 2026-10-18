import urllib.request, json

CLL1_HOST = "192.168.0.106"
CLL1_HTTP_PORT = 8766

data = json.dumps({"username": "admin", "password": "admin"}).encode("utf-8")
req = urllib.request.Request(f"http://{CLL1_HOST}:{CLL1_HTTP_PORT}/api/login", data=data, headers={"Content-Type": "application/json"}, method="POST")
resp = urllib.request.urlopen(req, timeout=10)
result = json.loads(resp.read().decode("utf-8"))
TOKEN = result["session"]
print(f"Login OK: {TOKEN[:30]}...")

req = urllib.request.Request(f"http://{CLL1_HOST}:{CLL1_HTTP_PORT}/api/exec", data=json.dumps({"command": "cat /data/data/com.termux/files/home/cll1/data/users.json"}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}, method="POST")
resp = urllib.request.urlopen(req, timeout=10)
result = json.loads(resp.read().decode("utf-8"))
print(f"Users.json: {result}")