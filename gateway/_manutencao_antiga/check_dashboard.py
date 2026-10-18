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

# Read dashboard.html from Android device
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

resp = tcp_req({"type": "get_file", "path": "gateway/dashboard.html", "token": TOKEN})
print(f"Read ok: {resp.get('ok')}")
if resp.get('ok'):
    content_b64 = resp.get('content', '')
    content = base64.b64decode(content_b64).decode("utf-8")
    print(f"dashboard.html length: {len(content)}")
    # Check for duplicate fcPath
    fc_count = content.count("fcPath")
    if fc_count > 1:
        print(f"DUPLICATE fcPath: {fc_count} times")
    # Check for auth function
    if "async function auth()" in content:
        print("auth() function: YES")
    else:
        print("auth() function: NO")
    if "async function ccAuth()" in content:
        print("ccAuth() function: YES")
    else:
        print("ccAuth() function: NO")
    # Check for duplicate fcPath declaration
    idx = content.find("fcPath")
    if idx >= 0:
        # Find all occurrences
        count = 0
        pos = 0
        while True:
            pos = content.find("fcPath", pos)
            if pos == -1:
                break
            count += 1
            pos += 1
        print(f"fcPath occurrences: {count}")
    # Find auth function
    idx = content.find("async function auth()")
    if idx >= 0:
        print(f"auth() found at position {idx}")
    else:
        print("auth() NOT FOUND")
    # Find ccAuth function
    idx = content.find("async function ccAuth()")
    if idx >= 0:
        print(f"ccAuth() found at position {idx}")
    else:
        print("ccAuth() NOT FOUND")

sock.close()