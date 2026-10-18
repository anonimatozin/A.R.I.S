"""Gera o bip de wake word do A.R.I.S (assets/sounds/wake.wav).

Só stdlib (wave + math + struct), sem baixar nada: um seno de 880 Hz por
80 ms com envelope que decai até o silêncio (sem clique de corte).

Uso:
    python assets/sounds/gerar_bip_wake.py
"""

import math
import struct
import wave
from pathlib import Path

DESTINO = Path(__file__).resolve().parent / "wake.wav"
FREQUENCIA_HZ = 880.0     # "ding" curto e alto (fundo musical de A a A5)
DURACAO_S = 0.08          # 80 ms
VOLUME = 0.35             # discreto, não assusta
SAMPLE_RATE = 44100


def gerar(destino: Path = DESTINO) -> Path:
    """Escreve o bip no destino e devolve o caminho."""
    n = int(SAMPLE_RATE * DURACAO_S)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)        # mono
        w.setsampwidth(2)        # 16-bit
        w.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for i in range(n):
            envelope = 1.0 - (i / n)  # decai até o silêncio
            sample = VOLUME * envelope * math.sin(
                2 * math.pi * FREQUENCIA_HZ * i / SAMPLE_RATE
            )
            frames += struct.pack("<h", int(sample * 32767))
        w.writeframes(bytes(frames))
    return destino


if __name__ == "__main__":
    print(f"Bip gerado: {gerar()}")
