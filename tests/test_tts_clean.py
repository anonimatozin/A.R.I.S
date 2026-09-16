"""Testes da limpeza de texto para TTS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.voice_hybrid import HybridVoice


def test_clean_bold():
    assert HybridVoice._clean_for_tts("**hello** world") == "hello world"


def test_clean_italic():
    assert HybridVoice._clean_for_tts("*hello* world") == "hello world"


def test_clean_inline_code():
    assert HybridVoice._clean_for_tts("use `pip install` here") == "use pip install here"


def test_clean_code_block():
    text = "```python\nprint('hi')\n```"
    assert "print" not in HybridVoice._clean_for_tts(text)


def test_clean_links():
    assert HybridVoice._clean_for_tts("[click](https://example.com)") == "click"


def test_clean_urls():
    result = HybridVoice._clean_for_tts("visit https://google.com ok")
    assert "https" not in result
    assert "ok" in result


def test_clean_headers():
    assert HybridVoice._clean_for_tts("## Title") == "Title"


def test_clean_lists():
    assert HybridVoice._clean_for_tts("- item one") == "item one"
    assert HybridVoice._clean_for_tts("1. first") == "first"


def test_clean_mixed():
    text = "**Olá!** Visite [meu site](https://x.com) para mais `info`."
    result = HybridVoice._clean_for_tts(text)
    assert "**" not in result
    assert "https" not in result
    assert "`" not in result
    assert "Olá" in result
    assert "info" in result


def test_clean_empty():
    assert HybridVoice._clean_for_tts("") == ""
    assert HybridVoice._clean_for_tts(None) == ""


if __name__ == "__main__":
    test_clean_bold()
    test_clean_italic()
    test_clean_inline_code()
    test_clean_code_block()
    test_clean_links()
    test_clean_urls()
    test_clean_headers()
    test_clean_lists()
    test_clean_mixed()
    test_clean_empty()
    print("Todos passaram!")
