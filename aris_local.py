"""A.R.I.S. Local CLI — Assistente com voz real (TTS + Microfone contínuo).

Ponto de entrada para o A.R.I.S. local com capacidades de voz completas:
- TTS via edge-tts (pt-BR-AntonioNeural)
- Microfone contínuo: VAD + Wake word ("aris") + STT (faster-whisper/Vosk)
- Barge-in: interrompe TTS se usuário falar
- Indicadores visuais de estado
- Cores diferenciadas para usuário vs ARIS

Uso:
    python aris_local.py              # Inicia com voz ativa
    python aris_local.py --text-only  # Apenas texto (sem microfone)
    python aris_local.py --no-tts     # Microfone ativo, sem TTS
"""

import argparse
import fcntl
import os
import sys
from pathlib import Path

# Garante suporte a caracteres unicode
if sys.stdout and not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and not sys.stderr.isatty():
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Adiciona o diretório raiz ao path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Força variáveis de ambiente para voz ANTES de importar Settings
os.environ.setdefault("ARIS_CONTINUOUS_VOICE_ENABLED", "true")
os.environ.setdefault("ARIS_VOICE_RATE", "0")
os.environ.setdefault("ARIS_VOICE_VOLUME", "100")

from core.aris import Aris
from utils.logger import Logger

# fd do lock mantido vivo durante todo o processo (fecha = libera a trava)
_LOCK_FD: int | None = None


def _find_other_instance() -> int | None:
    """PID de OUTRA instância do aris_local.py em execução, se houver.

    Varre /proc para achar instâncias anteriores (lançadas antes de
    existir o lock de arquivo) — só processos Python com argv contendo
    um argumento exato 'aris_local.py' (wrappers bash/timeout só casam
    se também tiverem um argv python separado, que não têm).
    """
    my_pid = os.getpid()
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == my_pid:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        args = [a for a in raw.decode("utf-8", "replace").split("\0") if a]
        if not args:
            continue
        if not any(os.path.basename(a).startswith("python") for a in args):
            continue
        if any(Path(a).name == "aris_local.py" for a in args):
            return int(entry.name)
    return None


def _acquire_instance_lock() -> int | None:
    """Trava exclusiva por arquivo — impede duas instâncias simultâneas.

    Bug real medido (13:26): DUAS instâncias rodando ao mesmo tempo, cada
    uma com seu `arecord` disputando o dispositivo ALSA 'default' de
    captura (exclusivo) → uma delas fica surda e "às vezes não responde".
    O flock é liberado pelo kernel mesmo se o processo morrer com SIGKILL
    (sem lock obsoleto).

    Retorna None em sucesso; PID da instância que já segura a trava
    quando outra já está no ar (ou -1 se o PID não puder ser lido).
    """
    global _LOCK_FD
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    lock_path = Path(runtime) / f"aris-local-{os.getuid()}.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Outra instância segura a trava: o PID fica escrito no arquivo
        holder = -1
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            holder = int(os.read(fd, 32).decode().strip() or -1)
        except (OSError, ValueError):
            holder = -1
        os.close(fd)
        return holder
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
    except OSError:
        pass
    _LOCK_FD = fd
    return None


def _release_instance_lock() -> None:
    global _LOCK_FD
    if _LOCK_FD is not None:
        try:
            os.close(_LOCK_FD)
        except OSError:
            pass
        _LOCK_FD = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A.R.I.S. Local CLI com voz real",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python aris_local.py              # Inicia com voz completa (TTS + microfone contínuo)
  python aris_local.py --text-only  # Apenas modo texto (sem microfone)
  python aris_local.py --no-tts     # Microfone ativo, mas sem síntese de voz
  python aris_local.py --mic-off    # Inicia com microfone desligado (digite 'voz' para ativar)
        """,
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Modo apenas texto (desabilita microfone e TTS)",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Ativa microfone mas desabilita TTS (respostas apenas em texto)",
    )
    parser.add_argument(
        "--mic-off",
        action="store_true",
        help="Inicia com microfone desligado (pode ativar digitando 'voz')",
    )
    parser.add_argument(
        "--vad-level",
        type=int,
        choices=[0, 1, 2, 3],
        default=2,
        help="Nível de agressividade do VAD (0-3, padrão: 2)",
    )
    parser.add_argument(
        "--stt-model",
        choices=["tiny", "base", "small"],
        default="tiny",
        help="Modelo STT do faster-whisper (padrão: tiny)",
    )
    args = parser.parse_args()

    logger = Logger(name="aris_local", log_dir=ROOT_DIR / "logs", level="INFO")

    # Instância única (microfone ALSA 'default' é exclusivo — duas
    # instâncias brigam pela captura e uma fica surda). --text-only não
    # usa microfone, então não trava. ARIS_ALLOW_MULTI_INSTANCE=1 pula
    # o bloqueio (uso próprio/diagnóstico).
    if not args.text_only and os.environ.get("ARIS_ALLOW_MULTI_INSTANCE") != "1":
        other = _find_other_instance()
        if other is None:
            other = _acquire_instance_lock()
        if other is not None:
            _release_instance_lock()  # no-op se a trava não foi ganha
            pid_txt = str(other) if other > 0 else "desconhecido"
            print(
                f"A.R.I.S. ja esta em execucao (PID {pid_txt}).\n"
                "Duas instancias disputam o microfone e as respostas ficam\n"
                "intermitentes. Feche a outra janela antes de abrir uma nova."
            )
            logger.warning(
                f"Bloqueio de instância única: outra instância (PID {pid_txt}) já está no ar"
            )
            sys.exit(1)

    # Configura variáveis de ambiente baseadas nos argumentos
    if args.text_only:
        os.environ["ARIS_CONTINUOUS_VOICE_ENABLED"] = "false"
        os.environ["ARIS_VOICE_VOLUME"] = "0"
    elif args.no_tts:
        os.environ["ARIS_VOICE_VOLUME"] = "0"
    if args.mic_off:
        os.environ["ARIS_CONTINUOUS_VOICE_ENABLED"] = "false"

    # Configura VAD e STT
    os.environ["ARIS_VAD_AGGRESSIVENESS"] = str(args.vad_level)
    os.environ["ARIS_STT_MODEL"] = args.stt_model

    logger.info("Iniciando A.R.I.S. Local CLI com voz real")

    try:
        aris = Aris()
        # Se --mic-off, garantir que mic_mode comece False
        if args.mic_off:
            aris._mic_mode = False
        aris.start()
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Erro fatal: {e}")
        print(f"Erro fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()