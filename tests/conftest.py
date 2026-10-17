"""Conftest compartilhado dos testes da ARIS (regras de ambiente globais)."""

import pytest


@pytest.fixture(autouse=True)
def _eyes_bridge_off(monkeypatch):
    """Nenhum teste pode subir os olhos de verdade nem tocar no socket.

    Sem isso, testes que exercitam o caminho REAL da ponte (ex.:
    ``test_face_matrix`` chamando ``_sync_hardware_state`` de verdade)
    tentariam enviar comandos, falhariam e spawnariam a janela dos olhos
    durante a suíte — o que já aconteceu uma vez. O kill-switch total
    (``ARIS_EYES=0``) torna ``set_state`` um no-op imediato.

    Os testes da própria ponte (``test_eyes_bridge.py``) removem essas
    variáveis na fixture deles para testar o caminho ligado.
    """
    monkeypatch.setenv("ARIS_EYES", "0")
    monkeypatch.setenv("ARIS_EYES_AUTOLAUNCH", "0")
