"""Reinicia o gateway forçadamente."""
import os
import signal
import subprocess
import time


def main():
    """Mata processos gateway antigos e inicia um novo."""
    # Matar processos gateway antigos
    try:
        result = subprocess.run(
            ["pkill", "-f", "python gateway.py"],
            capture_output=True,
            text=True
        )
        print("Processos antigos mortos")
    except Exception as e:
        print(f"Aviso ao matar processos: {e}")
    
    time.sleep(2)
    
    # Iniciar novo gateway em background
    try:
        gateway_dir = os.path.expanduser("~/cll1")
        subprocess.Popen(
            ["python", "gateway.py"],
            cwd=gateway_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        print("Novo gateway iniciado")
    except Exception as e:
        print(f"Erro ao iniciar gateway: {e}")
        return 1
    
    time.sleep(3)
    print("Gateway reiniciado com sucesso")
    return 0


if __name__ == "__main__":
    exit(main())
