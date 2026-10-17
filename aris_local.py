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

    logger = Logger(name="aris_local", log_dir=ROOT_DIR / "logs", level="INFO")
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