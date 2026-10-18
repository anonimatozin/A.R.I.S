"""Coleta de frases pelo microfone p/ treinar o modelo de wake word da Áris.

O openWakeWord não tem modelo pré-treinado em português — para a ARIS
acordar com "aris" de verdade é preciso treinar um .onnx (fluxo com Colab
em docs/WAKE_WORD.md, <1 h). Este script faz a parte chata: gravar as
frases POSITIVAS (com a wake word no meio de frases naturais) e, se
quiser, áudio NEGATIVO (fala sem a wake word).

Uso:
    python scripts/coletar_wake_word.py                 # 30 frases positivas
    python scripts/coletar_wake_word.py --rodadas 50    # mais frases
    python scripts/coletar_wake_word.py --negativas     # fala SEM a wake word
    python scripts/coletar_wake_word.py --segundos 5    # janela maior

Cada gravação vira um .wav 16 kHz mono 16-bit em treino_wake/ (pasta
local, não versionada — está no .gitignore). Captura via `arecord`
(Linux) ou pyaudio, se disponível. Dica: grave num cômodo silencioso e
varie entonação/distância do microfone entre as frases.
"""

from __future__ import annotations

import argparse
import random
import shutil
import subprocess
import sys
import wave
from pathlib import Path

PASTA_TREINO = Path(__file__).resolve().parents[1] / "treino_wake"

#: Frases naturais com a wake word NO MEIO (o modelo aprende a achar "aris"
#: dentro de fala real, não só isolada). Português do Brasil, variações de
#: entonação implícitas na lista.
FRASES_POSITIVAS = [
    "Arís, que horas são?",
    "ei Aris, tudo bem por aí?",
    "Aris abre o navegador pra mim",
    "ô Aris, toca aquela música de novo",
    "Arís você está me ouvindo?",
    "deixa eu ver, Aris, que dia é amanhã",
    "Aris, lembra mim da reunião às quatorze",
    "Aris fica quietinha um pouquinho",
    "peraí Aris, preciso pensar",
    "Arís, como é que se soletra borboleta",
    "Aris boa noite, durmo agora",
    "sabe uma coisa Aris, gosto de você",
    "Aris aumenta o volume aí",
    "com licença Aris, me ajuda com uma conta",
    "Aris que clima bom hoje hein",
    "Arís desliga a luz do quarto",
    "Aris faz um resumo do meu dia",
    "eu tava conversando com a Aris sobre isso",
    "a Arís é minha assistente pessoal",
    "manda salve pra Aris",
    "Aris me diz se chove hoje",
    "fala sério Aris, é sério isso?",
    "Arís primeiro abre o terminal",
    "aqui quem fala é o dono da Aris",
    "Aris anota: leite, café e pão",
    "Arís encerra a sessão de estudo",
    "cala a boca Aris, agora eu falo",
    "Aris me dá uma ideia de jantar",
    "que que você acha Aris?",
    "Arís confirma o agendamento de amanhã",
    "Aris bom dia, dormiu bem?",
    "vou sair agora Aris, fica em casa",
    "Arís toca um alarme daqui a vinte minutos",
    "aí Aris, me lembra do remédio",
    "Arís responde em português por favor",
    "oiê Aris, cheguei em casa",
    "Arís compara esse preço com o de ontem",
    "escuta Aris, tenho uma pergunta",
    "Arís finaliza a tarefa aí",
    "obrigado Aris, foi uma grande ajuda",
]

#: Negativos: fala normal SEM a wake word (o modelo aprende o que NÃO é).
FRASES_NEGATIVAS = [
    "o ônibus passa às sete da manhã",
    "eu gosto de café com leite",
    "ele disse que vem no fim da tarde",
    "a reunião foi adiada para sexta",
    "precisa comprar pão no mercado",
    "está muito calor hoje de manhã",
    "vamos ver o filme depois",
    "ela mora perto do centro",
    "eu preciso pensar melhor sobre isso",
    "o livro está na estante da sala",
    "ele trabalha de casa na segunda",
    "vou ligar para minha mãe agora",
    "a estrada estava bem vazia ontem",
    "isso mesmo, exatamente isso",
    "boa noite, até amanhã então",
]


def _gravar_arecord(destino: Path, segundos: float) -> bool:
    """Grava via arecord (Linux/PulseAudio). True se gravou."""
    exe = shutil.which("arecord")
    if not exe:
        return False
    proc = subprocess.run(
        [
            exe, "-q", "-f", "S16_LE", "-r", "16000", "-c", "1",
            "-d", str(max(1, round(segundos))), str(destino),
        ],
        capture_output=True,
    )
    return proc.returncode == 0 and destino.exists()


def _gravar_pyaudio(destino: Path, segundos: float) -> bool:
    """Grava via pyaudio (fallback, se instalado). True se gravou."""
    try:
        import pyaudio
    except ImportError:
        return False
    pa = pyaudio.PyAudio()
    stream = None
    try:
        stream = pa.open(
            format=pyaudio.paInt16, channels=1, rate=16000,
            input=True, frames_per_buffer=1600,
        )
        frames = []
        for _ in range(int(16000 / 1600 * segundos)):
            frames.append(stream.read(1600, exception_on_overflow=False))
        with wave.open(str(destino), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"".join(frames))
        return destino.exists()
    except Exception as exc:  # pragma: no cover - depende do hardware
        print(f"  (pyaudio falhou: {exc})")
        return False
    finally:
        if stream:
            stream.stop_stream()
            stream.close()
        pa.terminate()


def _gravar(destino: Path, segundos: float) -> bool:
    return _gravar_arecord(destino, segundos) or _gravar_pyaudio(destino, segundos)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rodadas", type=int, default=30, help="n° de frases (padrão 30)")
    parser.add_argument("--segundos", type=float, default=4.0, help="duração de cada gravação")
    parser.add_argument("--negativas", action="store_true",
                        help="gravar fala SEM a wake word (áudio negativo)")
    args = parser.parse_args()

    if not shutil.which("arecord"):
        try:
            import pyaudio  # noqa: F401
        except ImportError:
            print("Precisa de arecord (Linux) ou pyaudio instalado para gravar.")
            return 1

    frases = list(FRASES_NEGATIVAS if args.negativas else FRASES_POSITIVAS)
    random.shuffle(frases)
    pasta = PASTA_TREINO / ("negativas" if args.negativas else "positivas")
    pasta.mkdir(parents=True, exist_ok=True)
    ja_tem = len(list(pasta.glob("*.wav")))

    modo = "NEGATIVAS (sem a wake word)" if args.negativas else "POSITIVAS (com a wake word)"
    print(f"Coleta de frases {modo} — {args.rodadas} gravações em {pasta}")
    print("Dica: cômodo silencioso, variando entonação e distância.\n")

    gravadas = 0
    infinitas = frases * (args.rodadas // len(frases) + 1)
    for i, frase in enumerate(infinitas):
        if i >= args.rodadas:
            break
        entrada = input(f"[{i + 1}/{args.rodadas}] Fale: {frase}\n  Enter grava ({args.segundos:.0f}s) | 'p' pula | 'q' sai: ").strip().lower()
        if entrada == "q":
            break
        if entrada == "p":
            continue
        destino = pasta / f"fala_{ja_tem + gravadas:04d}.wav"
        print("  ...gravando")
        if _gravar(destino, args.segundos):
            gravadas += 1
            print(f"  ✓ {destino.name}")
        else:
            print("  ✗ falhou a gravação (arecord/pyaudio)")

    print(f"\nPronto: {gravadas} gravações novas em {pasta} ({ja_tem} já existiam).")
    print("Próximo passo: seguir docs/WAKE_WORD.md (Colab do openWakeWord) "
          "com a pasta positivas/ + horas de áudio negativo de rádio/podcast.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
