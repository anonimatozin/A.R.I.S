"""Teste de vozes do A.R.I.S.
Roda este script para ouvir cada voz e escolher a melhor.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_tts

VOZES = [
    ("pt-BR-ThalitaMultilingualNeural", "Thalita (Multilingual, Feminina)"),
    ("pt-BR-FranciscaNeural", "Francisca (Feminina)"),
    ("pt-BR-AntonioNeural", "Antonio (Masculina)"),
]

FRASE = "Oi! Eu sou a ARIS, sua assistente pessoal. Posso te ajudar com várias coisas. Como posso te ajudar hoje?"


async def gerar_e_tocar(voice_id: str, nome: str):
    print(f"\n  [{nome}]")
    print(f"  Voz: {voice_id}")
    print("  Falando...")

    tmp = os.path.join(tempfile.gettempdir(), f"test_voice_{voice_id}.mp3")
    communicate = edge_tts.Communicate(FRASE, voice_id)
    await communicate.save(tmp)

    # Tocar com pygame se disponível, senão MCI
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(tmp)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)
        pygame.mixer.quit()
    except ImportError:
        try:
            import ctypes
            import time
            ctypes.windll.winmm.mciSendStringW(
                f'open "{tmp}" type mpegvideo alias test_voice', None, 0, None
            )
            length_buf = ctypes.create_unicode_buffer(64)
            ctypes.windll.winmm.mciSendStringW(
                "status test_voice length", length_buf, 64, None
            )
            try:
                total_ms = int(length_buf.value)
            except (ValueError, TypeError):
                total_ms = 5000
            max_s = (total_ms / 1000.0 + 1.0) if total_ms > 0 else 10.0

            ctypes.windll.winmm.mciSendStringW("play test_voice", None, 0, None)
            started = time.monotonic()
            while time.monotonic() - started < max_s:
                mode_buf = ctypes.create_unicode_buffer(64)
                ctypes.windll.winmm.mciSendStringW(
                    "status test_voice mode", mode_buf, 64, None
                )
                if mode_buf.value.strip().lower() != "playing":
                    break
                time.sleep(0.25)
            ctypes.windll.winmm.mciSendStringW("close test_voice", None, 0, None)
        except Exception as e:
            print(f"  Erro ao tocar: {e}")

    try:
        os.remove(tmp)
    except Exception:
        pass

    print("  Pronto!")


async def main():
    print("=" * 50)
    print("  TESTE DE VOZES - A.R.I.S.")
    print("=" * 50)
    print(f"\n  Frase de teste: \"{FRASE}\"")
    print("\n  Vozes disponíveis:")

    for i, (vid, nome) in enumerate(VOZES, 1):
        print(f"  {i}. {nome} ({vid})")

    print("\n  Pressione Enter após cada voz para continuar...")
    print("  Anote qual voz você prefere!")

    for i, (vid, nome) in enumerate(VOZES, 1):
        print(f"\n{'─' * 50}")
        input(f"\n  Pressione Enter para ouvir a voz {i}...")
        await gerar_e_tocar(vid, nome)

    print(f"\n{'=' * 50}")
    print("  Todas as vozes foram testadas!")
    print("  Edite VOZES no arquivo voice_hybrid.py")
    print("  e coloque a voz que você mais gostou.")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
