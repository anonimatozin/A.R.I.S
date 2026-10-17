import socket
import json
import struct
import sys
import os
import base64
import urllib.request

CLL1_HOST = "192.168.0.106"
CLL1_HTTP_PORT = 8766
CLL1_TCP_PORT = 8765
BASE = r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway"

with open(os.path.join(BASE, "dashboard.html"), "r", encoding="utf-8") as f:
    content = f.read()

# Login
data = json.dumps({"username": "admin", "password": "admin"}).encode("utf-8")
req = urllib.request.Request(f"http://{CLL1_HOST}:{CLL1_HTTP_PORT}/api/login", data=data, headers={"Content-Type": "application/json"}, method="POST")
resp = urllib.request.urlopen(req, timeout=10)
login_data = json.loads(resp.read().decode("utf-8"))
if not login_data.get("ok"):
    print(f"Login failed: {login_data}")
    sys.exit(1)
TOKEN = login_data["session"]
print(f"Logged in!")

# Connect TCP
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(15)
sock.connect((CLL1_HOST, CLL1_TCP_PORT))
print("Connected!")

def tcp_req(request):
    payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!Q", len(payload)))
    sock.sendall(payload)
    size_data = b""
    while len(size_data) < 8:
        chunk = sock.recv(8 - len(size_data))
        if not chunk: return None
        size_data += chunk
    size = struct.unpack("!Q", size_data)[0]
    data = b""
    while len(data) < size:
        chunk = sock.recv(min(65536, size - len(data)))
        if not chunk: break
        data += chunk
    return json.loads(data.decode("utf-8"))

# Deploy dashboard
print("Deploying dashboard.html...")
content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
resp = tcp_req({"type": "put_file", "path": "gateway/dashboard.html", "content": content_b64, "token": TOKEN})
print(f"Result: {resp}")

sock.close()
print("Done!")