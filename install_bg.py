"""Instala dependências em background."""
import subprocess
import sys
import os


def main():
    """Instala dependências em background."""
    # Criar script de instalação
    script = '''#!/data/data/com.termux/files/usr/bin/sh
cd ~/cll1
pip install discord.py openai --quiet
echo "DEPENDENCIES_INSTALLED" >> ~/cll1/logs/install.log
'''
    
    script_path = os.path.expanduser("~/cll1/install_bg.sh")
    with open(script_path, "w") as f:
        f.write(script)
    
    os.chmod(script_path, 0o700)
    
    # Executar em background
    subprocess.Popen(
        ["sh", script_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    
    print("Instalação iniciada em background")
    print("Verifique: tail -f ~/cll1/logs/install.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
