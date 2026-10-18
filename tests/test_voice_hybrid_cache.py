"""Melhorias de TTS do HybridVoice: cache em disco e streaming por frase.

Sem rede e sem áudio: exercitam só os helpers puros
(_frases_para_falar, _dir_cache_tts, _arquivo_cache_tts, _podar_cache_tts).
"""

import os
import time

from utils.voice_hybrid import HybridVoice


def _hibrido_sem_init() -> HybridVoice:
    """Instância sem rodar __init__ (que tocaria em microfone/pyttsx3)."""
    return HybridVoice.__new__(HybridVoice)


# ─── Streaming por frase ───


def test_divide_em_frases_por_pontuacao():
    frases = HybridVoice._frases_para_falar("Pronto. Abrindo o navegador agora!")
    assert frases == ["Pronto.", "Abrindo o navegador agora!"]


def test_frase_unica_passa_integra():
    assert HybridVoice._frases_para_falar("Tudo certo por aqui.") == ["Tudo certo por aqui."]


def test_texto_sem_pontuacao_final_vai_inteiro():
    texto = "abre o navegador"
    assert HybridVoice._frases_para_falar(texto) == [texto]


def test_vazio_nao_quebra():
    assert HybridVoice._frases_para_falar("") == [""]


# ─── Cache em disco ───


def test_cache_usa_xdg_e_cria_o_diretorio(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIS_TTS_CACHE", "1")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    dir_cache = _hibrido_sem_init()._dir_cache_tts()
    assert dir_cache == os.path.join(str(tmp_path), "aris", "tts")
    assert os.path.isdir(dir_cache)


def test_cache_desligado_por_env(monkeypatch):
    monkeypatch.setenv("ARIS_TTS_CACHE", "0")
    assert _hibrido_sem_init()._dir_cache_tts() is None


def test_frase_longa_nao_entra_no_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIS_TTS_CACHE", "1")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    longa = "A" * 121
    assert _hibrido_sem_init()._arquivo_cache_tts(longa, "pt-BR-FranciscaNeural") is None


def test_frase_curta_gera_caminho_estavel(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIS_TTS_CACHE", "1")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    voice = "pt-BR-FranciscaNeural"
    h = _hibrido_sem_init()
    a = h._arquivo_cache_tts("Pronto!", voice)
    b = h._arquivo_cache_tts("Pronto!", voice)
    assert a == b and a.endswith(".mp3")
    # voz diferente → arquivo diferente (nunca trocar voz por acaso)
    assert h._arquivo_cache_tts("Pronto!", "pt-BR-AndreNeural") != a


def test_podar_cache_remove_os_mais_antigos(tmp_path):
    dir_cache = tmp_path / "tts"
    dir_cache.mkdir()
    antigos = []
    for i in range(5):
        arquivo = dir_cache / f"{i}.mp3"
        arquivo.write_bytes(b"\x00")
        os.utime(arquivo, (time.time() - (100 - i), time.time() - (100 - i)))
        antigos.append(arquivo)

    HybridVoice._podar_cache_tts(str(dir_cache), max_arquivos=3)

    restantes = sorted(p.name for p in dir_cache.iterdir())
    assert restantes == ["2.mp3", "3.mp3", "4.mp3"]  # os 3 mais novos


def test_podar_cache_tolera_diretorio_inexistente(tmp_path):
    HybridVoice._podar_cache_tts(str(tmp_path / "nao_existe"))  # não levanta
