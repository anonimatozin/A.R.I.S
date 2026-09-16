import sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()
import subprocess

code = "import urllib.request; print(urllib.request.urlopen('https://httpbin.org/ip', timeout=10).read().decode())"
r = subprocess.run(['python', 'cll1_control.py', 'exec', code], capture_output=True, text=True, timeout=20)
print('stdout:', r.stdout[:300])
print('stderr:', r.stderr[:200] if r.stderr else '')
