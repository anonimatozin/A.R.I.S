from aris_eyes.modes import DisplayController, Mode, parse_mode


class FakeWindow:
    def __init__(self):
        self.calls = []

    def present_fullscreen(self): self.calls.append("fullscreen")
    def present_mini(self): self.calls.append("mini")
    def present_hidden(self): self.calls.append("hidden")


def make():
    w, seen = FakeWindow(), []
    return w, DisplayController(w, seen.append), seen


def test_alternar_tela_cheia_e_miniatura():
    w, c, _ = make()
    c.toggle_fullscreen()
    c.toggle_fullscreen()
    c.toggle_fullscreen()
    assert w.calls == ["fullscreen", "mini", "fullscreen"]


def test_esconder_e_voltar_ao_ultimo_modo_visivel():
    w, c, _ = make()
    c.set_mode(Mode.MINI)
    c.toggle_hidden()
    assert c.mode is Mode.HIDDEN
    c.toggle_hidden()
    assert c.mode is Mode.MINI and w.calls == ["mini", "hidden", "mini"]
    c.set_mode(Mode.FULLSCREEN)
    c.toggle_hidden()
    c.show()
    assert c.mode is Mode.FULLSCREEN


def test_ciclo_completo():
    w, c, _ = make()
    c.set_mode(Mode.FULLSCREEN)
    c.cycle(); c.cycle(); c.cycle()
    assert w.calls == ["fullscreen", "mini", "hidden", "fullscreen"]


def test_mesmo_modo_nao_repete_nem_avisa_de_novo():
    w, c, seen = make()
    c.set_mode(Mode.MINI)
    c.set_mode(Mode.MINI)
    assert w.calls == ["mini"] and seen == [Mode.MINI]


def test_refresh_reaplica_o_modo_atual():
    w, c, _ = make()
    c.set_mode(Mode.MINI)
    c.refresh()
    assert w.calls == ["mini", "mini"]


def test_show_sem_modo_abre_tela_cheia():
    w, c, _ = make()
    c.show()
    assert w.calls == ["fullscreen"]


def test_parse_mode_com_apelidos():
    assert parse_mode("hide") is Mode.HIDDEN and parse_mode("miniatura") is Mode.MINI
    assert parse_mode("xyz") is None
