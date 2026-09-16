import subprocess
import sys

packages = ['discord.py', 'openai']
for pkg in packages:
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', pkg],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            print(f'OK: {pkg}')
        else:
            print(f'FALHA: {pkg}')
    except Exception as e:
        print(f'ERRO: {pkg}: {e}')
