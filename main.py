"""Ponto de entrada único do A.R.I.S.

    python main.py                 # voz completa (TTS + microfone contínuo)
    python main.py --text-only     # só texto
    python main.py --mic-off       # microfone desligado ('voz' para ativar)

Aceita as mesmas opções do ``aris_local.py`` (que continua funcionando).
No Linux, ``./aris.sh`` faz a mesma coisa já preparando PortAudio e X11.
"""

from __future__ import annotations


def main() -> None:
    # Import tardio: carregar o núcleo é pesado e `--help` deve responder rápido.
    from aris_local import main as _main

    _main()


if __name__ == "__main__":
    main()
