import urllib.request, json, socket, struct, base64, os

CLL1_HOST = "192.168.0.106"
CLL1_HTTP_PORT = 8766
CLL1_TCP_PORT = 8765

# Test login
data = json.dumps({"username": "admin", "password": "admin"}).encode("utf-8")
req = urllib.request.Request(f"http://{CLL1_HOST}:{CLL1_HTTP_PORT}/api/login", data=json.dumps({"username": "admin", "password": "admin"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
resp = urllib.request.urlopen(req, timeout=10)
result = json.loads(resp.read().decode("utf-8"))
TOKEN = result["session"]
print(f"Login OK: {TOKEN[:30]}...")

# Read web.py from Android device
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(15)
sock.connect((CLL1_HOST, 8765))

def tcp_req(request):
    payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!Q", len(payload)) + payload)
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

resp = tcp_req({"type": "get_file", "path": "gateway/web.py", "token": TOKEN})
print(f"Read ok: {resp.get('ok')}")
if resp.get('ok'):
    content_b64 = resp.get('content', '')
    content = base64.b64decode(content_b64).decode("utf-8")
    print(f"web.py length: {len(content)}")
    if 'with open("debug_create_user.log"' in content:
        print('Fix present: YES')
    else:
        print('Fix present: NO')
    if 'try:' in content and 'create_user(token, username, password, role, expires_at)' in content:
        print('Try/except block: YES')
    else:
        print('Try/except block: NO')

sock.close()