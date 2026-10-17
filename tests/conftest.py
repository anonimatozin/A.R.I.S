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


@pytest.fixture(autouse=True)
def _isola_modo_da_aris():
    """Zera o ModeManager global entre testes.

    Antes, tests/test_distributed.py deixava a ARIS em modo EDGE e
    test_new_phases.py::test_executor_confirmation_required falhava só quando
    rodava depois dele ("Tool 'pc_shutdown' not available in edge mode").
    """
    try:
        from core.neural.mode import reset_mode_manager
    except Exception:  # pragma: no cover - núcleo não importável neste ambiente
        yield
        return
    reset_mode_manager()
    yield
    reset_mode_manager()
