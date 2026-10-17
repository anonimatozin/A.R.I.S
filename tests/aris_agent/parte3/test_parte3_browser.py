"""Parte 3: navegador controlado — snapshots numerados, anti-stale e ferramentas browser_*.

Sem rede e sem Chromium: a lógica é testada com um FakePage; o teste live (marcado)
é quem realmente abre o navegador.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest
from test_parte3_utils import local_server, make_ctx

from aris_agent.tools.web import browser as browser_mod
from aris_agent.tools.web.browser import (
    BrowserError,
    BrowserSession,
    browser_click,
    browser_close,
    browser_open,
    browser_press,
    browser_screenshot,
    browser_snapshot,
    browser_type,
)
from aris_agent.tools.web.settings import WebSettings

ELEMS = [
    {"idx": 0, "role": "button", "name": "Entrar"},
    {"idx": 1, "role": "textbox", "name": "E-mail"},
]


class FakeLocator:
    def __init__(self, page: FakePage) -> None:
        self._page = page
        self._index: int | None = None

    def nth(self, index: int) -> FakeLocator:
        self._index = index
        return self

    def click(self, timeout=None) -> None:
        self._page.click_log.append(self._index)

    def fill(self, text: str) -> None:
        if self._page.on_fill is not None:
            self._page.on_fill(text)
        self._page.fill_log.append((self._index, text))

    def press(self, key: str, timeout=None) -> None:
        self._page.press_log.append((self._index, key))


class FakeKeyboard:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    def press(self, key: str) -> None:
        self._page.key_log.append(key)

    def insert_text(self, text: str) -> None:
        self._page.insert_log.append(text)


class FakePage:
    """Página mínima com a mesma superfície usada por BrowserSession."""

    def __init__(self, elements=None, url="http://127.0.0.1:9/pagina", title="Página de Teste"):
        self.elements = [dict(e) for e in (elements if elements is not None else ELEMS)]
        self.url = url
        self.title_text = title
        self.visible_text = "Bem-vindo ao formulário."
        self.click_log: list = []
        self.fill_log: list = []
        self.press_log: list = []
        self.key_log: list = []
        self.insert_log: list = []
        self.on_fill = None
        self.keyboard = FakeKeyboard(self)

    def evaluate(self, _js, _sel):
        return [dict(e) for e in self.elements]

    def inner_text(self, _sel, timeout=None):
        return self.visible_text

    def title(self):
        return self.title_text

    def locator(self, _sel):
        return FakeLocator(self)

    def wait_for_load_state(self, _state, timeout=None):
        pass

    def screenshot(self, path, full_page=False):
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")


def _sessao(tmp_path, allow_local=True) -> BrowserSession:
    ctx = make_ctx(tmp_path, allow_local=allow_local)
    return BrowserSession(WebSettings(test_allow_local=allow_local), ctx.config.data_dir,
                          ctx.config.workspace_dir)


# ------------------------------------------------------------------ sem sessão


def test_snapshot_sem_navegador_aberto(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser_mod, "_SESSION", None)
    result = browser_snapshot.run({}, make_ctx(tmp_path))
    assert result.ok is False
    assert "browser_open" in (result.error or "")
    assert "nenhum navegador aberto" in (result.error or "")


def test_close_sem_sessao_e_idempotente(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser_mod, "_SESSION", None)
    result = browser_close.run({}, make_ctx(tmp_path))
    assert result.ok is True
    assert result.data == {"closed": False}
    assert "Nenhum navegador aberto" in result.content


def test_open_valida_url_antes_de_ligar_o_navegador(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser_mod, "_SESSION", None)
    ctx = make_ctx(tmp_path, allow_local=False)
    result = browser_open.run({"url": "http://127.0.0.1:8000/"}, ctx)
    assert result.ok is False
    assert "política de rede" in (result.error or "")
    sessao = browser_mod._SESSION
    assert sessao is not None and sessao.active is False, "Chromium não deve ter sido ligado"

    result2 = browser_open.run({"url": "file:///C:/Windows/win.ini"}, ctx)
    assert result2.ok is False
    assert browser_mod._SESSION.active is False


def test_open_url_invalida(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser_mod, "_SESSION", None)
    result = browser_open.run({"url": "  "}, make_ctx(tmp_path))
    assert result.ok is False
    assert "obrigatório" in (result.error or "")


def test_playwright_import_preguicoso_com_erro_util(tmp_path, monkeypatch) -> None:
    real_import = builtins.__import__

    def sem_playwright(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("playwright ausente (simulado)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sem_playwright)
    sessao = _sessao(tmp_path)
    with pytest.raises(BrowserError) as exc:
        sessao._ensure_started()
    assert "playwright install chromium" in str(exc.value)
    assert sessao.active is False


# ------------------------------------------------------------ sessão + FakePage


def test_snapshot_numera_elementos(tmp_path) -> None:
    sessao = _sessao(tmp_path)
    sessao._page = FakePage()
    texto, url = sessao.snapshot()
    assert url == "http://127.0.0.1:9/pagina"
    assert 'URL: http://127.0.0.1:9/pagina' in texto
    assert "Título: Página de Teste" in texto
    assert "Bem-vindo ao formulário." in texto
    assert "Elementos interativos (2):" in texto
    assert '[1] botão "Entrar"' in texto
    assert '[2] campo "E-mail"' in texto
    assert len(sessao.elements or []) == 2
    sessao.close()


def test_click_usa_indice_do_dom(tmp_path) -> None:
    sessao = _sessao(tmp_path)
    page = FakePage()
    sessao._page = page
    sessao.snapshot()
    elemento = sessao.click(1)
    assert elemento.role == "button"
    assert page.click_log == [0], "botão é o primeiro elemento do DOM"
    sessao.type_text(2, "vinicius@example.com")
    assert page.fill_log == [(1, "vinicius@example.com")]
    sessao.press("Enter")
    assert page.key_log == ["Enter"]
    sessao.press("Tab", number=1)
    assert page.press_log == [(0, "Tab")]
    sessao.close()


def test_elemento_inexistente_fora_do_range(tmp_path) -> None:
    sessao = _sessao(tmp_path)
    sessao._page = FakePage()
    sessao.snapshot()
    with pytest.raises(BrowserError) as exc:
        sessao.click(99)
    assert "inexistente" in str(exc.value)
    with pytest.raises(BrowserError):
        sessao.click(0)
    sessao.close()


def test_acao_sem_snapshot_pede_browser_snapshot(tmp_path) -> None:
    sessao = _sessao(tmp_path)
    sessao._page = FakePage()
    with pytest.raises(BrowserError) as exc:
        sessao.click(1)
    assert str(exc.value) == "nenhum snapshot ativo; chame browser_snapshot"
    sessao.close()


def test_snapshot_desatualizado_quando_a_pagina_muda(tmp_path) -> None:
    sessao = _sessao(tmp_path)
    page = FakePage()
    sessao._page = page
    sessao.snapshot()
    page.elements[0]["name"] = "Login"  # a página mudou sob o pé do agente
    with pytest.raises(BrowserError) as exc:
        sessao.click(1)
    assert str(exc.value) == "snapshot desatualizado, chame browser_snapshot"
    assert sessao.elements is None, "snapshot inválido deve ser descartado"
    with pytest.raises(BrowserError) as exc2:
        sessao.click(1)
    assert str(exc2.value) == "nenhum snapshot ativo; chame browser_snapshot"
    sessao.close()


def test_type_atualiza_nome_sem_invalidar(tmp_path) -> None:
    sessao = _sessao(tmp_path)
    page = FakePage()
    sessao._page = page
    sessao.snapshot()
    # o nome de um elemento muda enquanto digitamos (ex.: contador/estado);
    # browser_type aceita mudança de nome e revalida a assinatura
    page.on_fill = lambda _text: page.elements[0].update(name="Entrar (carregando)")
    sessao.type_text(2, "texto")
    assert page.fill_log == [(1, "texto")]
    assert sessao.elements is not None, "nome pode mudar durante digitação"
    assert sessao.elements[0].name == "Entrar (carregando)"
    sessao.close()


def test_screenshot_grava_png(tmp_path) -> None:
    sessao = _sessao(tmp_path)
    sessao._page = FakePage()
    caminho = sessao.screenshot()
    assert caminho.exists()
    assert caminho.parent == Path(tmp_path) / "ws" / "browser"
    assert caminho.suffix == ".png"
    caminho2 = sessao.screenshot(full_page=True)
    assert caminho2 != caminho, "segundo screenshot não sobrescreve o primeiro"
    sessao.close()


def test_perfil_fica_no_data_dir() -> None:
    sessao = BrowserSession(WebSettings(), Path("/dados"), Path("/trabalho"))
    assert sessao.profile_dir == Path("/dados") / "browser_profile"
    assert sessao.active is False


# ------------------------------------------------------------------ ferramentas


def test_ferramentas_de_leitura_e_acao_com_sessao_fake(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    sessao = BrowserSession(WebSettings(test_allow_local=True), ctx.config.data_dir,
                            ctx.config.workspace_dir)
    page = FakePage()
    sessao._page = page
    monkeypatch.setattr(browser_mod, "_SESSION", sessao)

    snap = browser_snapshot.run({}, ctx)
    assert snap.ok, snap.error
    assert "AVISO:" in snap.content
    assert '[1] botão "Entrar"' in snap.content
    assert snap.data["elements"] == 2

    click = browser_click.run({"element": 1}, ctx)
    assert click.ok, click.error
    assert "Clicado em [1]" in click.content
    assert click.data == {"element": 1, "role": "button", "name": "Entrar"}

    escrito = browser_type.run({"element": 2, "text": "oi@exemplo.com"}, ctx)
    assert escrito.ok, escrito.error
    assert escrito.data == {"element": 2, "chars": len("oi@exemplo.com")}

    tecla = browser_press.run({"key": "Enter"}, ctx)
    assert tecla.ok, tecla.error
    assert tecla.data == {"key": "Enter", "element": None}

    shot = browser_screenshot.run({}, ctx)
    assert shot.ok, shot.error
    assert Path(shot.data["path"]).exists()
    assert shot.artifacts == [shot.data["path"]]

    fechar = browser_close.run({}, ctx)
    assert fechar.ok and fechar.data == {"closed": True}
    assert browser_mod._SESSION is None


def test_ferramenta_click_com_argumento_invalido(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    sessao = BrowserSession(WebSettings(), ctx.config.data_dir, ctx.config.workspace_dir)
    sessao._page = FakePage()
    monkeypatch.setattr(browser_mod, "_SESSION", sessao)
    for args in ({"element": "abc"}, {"element": None}):
        result = browser_click.run(args, ctx)
        assert result.ok is False
        assert "inteiro" in (result.error or "")


def test_ferramenta_press_sem_tecla(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    sessao = BrowserSession(WebSettings(), ctx.config.data_dir, ctx.config.workspace_dir)
    sessao._page = FakePage()
    monkeypatch.setattr(browser_mod, "_SESSION", sessao)
    result = browser_press.run({}, ctx)
    assert result.ok is False
    assert "obrigatório" in (result.error or "")
    sem_snapshot = browser_press.run({"key": "Tab", "element": 1}, ctx)
    assert sem_snapshot.ok is False
    assert "nenhum snapshot ativo" in (sem_snapshot.error or "")


def test_ferramenta_type_sem_snapshot(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    sessao = BrowserSession(WebSettings(), ctx.config.data_dir, ctx.config.workspace_dir)
    sessao._page = FakePage()
    monkeypatch.setattr(browser_mod, "_SESSION", sessao)
    result = browser_type.run({"element": 1, "text": "x"}, ctx)
    assert result.ok is False
    assert "nenhum snapshot ativo" in (result.error or "")


def test_ferramenta_click_desatualizado_exige_mensagem_exata(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    sessao = BrowserSession(WebSettings(), ctx.config.data_dir, ctx.config.workspace_dir)
    page = FakePage()
    sessao._page = page
    monkeypatch.setattr(browser_mod, "_SESSION", sessao)
    assert browser_snapshot.run({}, ctx).ok
    page.elements[0]["name"] = "Mudou"
    result = browser_click.run({"element": 1}, ctx)
    assert result.ok is False
    assert result.error == "snapshot desatualizado, chame browser_snapshot"
    assert result.content == ""


def test_ferramenta_close_zera_a_sessao(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    sessao = BrowserSession(WebSettings(), ctx.config.data_dir, ctx.config.workspace_dir)
    sessao._page = FakePage()
    monkeypatch.setattr(browser_mod, "_SESSION", sessao)
    assert browser_close.run({}, ctx).data == {"closed": True}
    assert sessao.active is False
    assert browser_close.run({}, ctx).data == {"closed": False}


# ---------------------------------------------------------------------- live


PAGINA = """<!doctype html><html><head><meta charset="utf-8"><title>Página do Teste</title></head>
<body><h1>Página do Teste</h1>
<button onclick="document.getElementById('out').textContent='clicado!'">Clique aqui</button>
<input placeholder="Seu e-mail" oninput="document.getElementById('out').textContent=this.value">
<p id="out">inicial</p>
</body></html>"""


def _numero(snapshot_content: str, rotulo: str) -> int:
    import re

    for linha in snapshot_content.splitlines():
        achado = re.match(r"\[(\d+)\] (.*)$", linha.strip())
        if achado and rotulo in achado.group(2):
            return int(achado.group(1))
    raise AssertionError(f"elemento {rotulo!r} não aparece no snapshot")


@pytest.mark.live
def test_live_navegador_abre_clica_e_tira_foto(tmp_path) -> None:
    rotas = {"/": (200, {"Content-Type": "text/html; charset=utf-8"}, PAGINA.encode())}
    ctx = make_ctx(tmp_path)
    try:
        with local_server(rotas) as base:
            aberto = browser_open.run({"url": base + "/"}, ctx)
            assert aberto.ok, aberto.error
            assert "Página do Teste" in aberto.content

            snap = browser_snapshot.run({}, ctx)
            assert snap.ok, snap.error
            assert "inicial" in snap.content
            num_botao = _numero(snap.content, "Clique aqui")
            num_campo = _numero(snap.content, "Seu e-mail")

            click = browser_click.run({"element": num_botao}, ctx)
            assert click.ok, click.error

            depois = browser_snapshot.run({}, ctx)
            assert depois.ok and "clicado!" in depois.content

            escrito = browser_type.run(
                {"element": num_campo, "text": "vinicius@example.com"}, ctx
            )
            assert escrito.ok, escrito.error

            final = browser_snapshot.run({}, ctx)
            assert final.ok and "vinicius@example.com" in final.content

            shot = browser_screenshot.run({}, ctx)
            assert shot.ok, shot.error
            assert Path(shot.data["path"]).exists()
    finally:
        fechado = browser_close.run({}, ctx)
        assert fechado.ok
