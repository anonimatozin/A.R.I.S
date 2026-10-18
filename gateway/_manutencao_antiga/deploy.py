import urllib.request
import json
import socket
import struct
import base64
import os

CLL1_HOST = "192.168.0.106"
CLL1_HTTP_PORT = 8766
CLL1_TCP_PORT = 8765

BASE = r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway"
WEB_PATH = r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py"
DASH_PATH = r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\dashboard.html"

# Read files
with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    web_content = f.read()

with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\dashboard.html", "r", encoding="utf-8") as f:
    dash_content = f.read()

# Login
data = json.dumps({"username": "admin", "password": "admin"}).encode("utf-8")
req = urllib.request.Request(f"http://192.168.0.106:8766/api/login", data=json.dumps({"username": "admin", "password": "admin"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
resp = urllib.request.urlopen(req, timeout=10)
login_result = json.loads(resp.read().decode("utf-8"))
TOKEN = login_result["session"]
print(f"Login OK: {TOKEN[:30]}...")

# Deploy web.py
print("Deploying web.py...")
web_b64 = base64.b64encode(web_content.encode("utf-8")).decode("ascii")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(15)
sock.connect(("192.168.0.106", 8765))

def tcp_req(request):
    payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!Q", len(payload)))
    sock.sendall(payload)
    size_data = b""
    while len(size_data) < 8:
        chunk = sock.recv(8 - len(size_data))
        if not chunk:
            return None
        size_data += chunk
    size = struct.unpack("!Q", size_data)[0]
    data = b""
    while len(data) < size:
        chunk = sock.recv(min(65536, size - len(data)))
        if not chunk:
            break
        data += chunk
    return json.loads(data.decode("utf-8"))

# Deploy web.py
print("Deploying web.py...")
web_b64 = base64.b64encode(open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8").read().encode("utf-8")).decode("ascii")
resp = None
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(15)
sock.connect(("192.168.0.106", 8765))

def tcp_req(request):
    payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!Q", len(payload)))
    sock.sendall(payload)
    size_data = b""
    while len(size_data) < 8:
        chunk = sock.recv(8 - len(size_data))
        if not chunk:
            return None
        size_data += chunk
    size = struct.unpack("!Q", size_data)[0]
    data = b""
    while len(data) < size:
        chunk = sock.recv(min(65536, size - len(data)))
        if not chunk:
            break
        data += chunk
    return json.loads(data.decode("utf-8"))

resp = tcp_req({"type": "put_file", "path": "gateway/web.py", "content": base64.b64encode(open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8").read().encode("utf-8")).decode("ascii"), "token": TOKEN})
print(f"web.py deploy: {resp}")

# Deploy dashboard.html
print("Deploying dashboard.html...")
dash_b64 = base64.b64encode(open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\dashboard.html", "r", encoding="utf-8").read().encode("utf-8")).decode("ascii")
resp = tcp_req({"type": "put_file", "path": "gateway/dashboard.html", "content": dash_b64, "token": TOKEN})
print(f"dashboard.html deploy: {resp}")

sock.close()
print("Deploy complete!")