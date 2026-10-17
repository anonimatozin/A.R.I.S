import json

from aris_eyes.config import DEFAULT_SHORTCUTS, Config


def test_cria_arquivo_com_padroes(tmp_path):
    path = tmp_path / "sub" / "config.json"
    cfg = Config.load(path)
    assert path.exists()
    assert cfg.start_mode == "fullscreen" and cfg.shortcuts == DEFAULT_SHORTCUTS
    assert json.loads(path.read_text())["always_on_top"] is True


def test_mescla_atalhos_e_ignora_chave_desconhecida(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"shortcuts": {"hide": "Ctrl+Alt+H"}, "chave_inventada": 1, "mini_width": 400}))
    cfg = Config.load(path)
    assert cfg.shortcuts["hide"] == "Ctrl+Alt+H"
    assert cfg.shortcuts["quit"] == DEFAULT_SHORTCUTS["quit"]      # os nao citados continuam padrao
    assert cfg.mini_width == 400


def test_valores_invalidos_voltam_ao_padrao(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"start_mode": "voando", "eye_color": "azul", "fps_mini": "rapido",
                                "mini_width": 99999, "mini_position": [1], "always_on_top": "sim"}))
    cfg = Config.load(path)
    assert cfg.start_mode == "fullscreen"
    assert cfg.eye_color == "#2f9bff"
    assert cfg.fps_mini == 30
    assert cfg.mini_width == 1200            # limitado ao maximo
    assert cfg.mini_position is None
    assert cfg.always_on_top is True


def test_json_quebrado_nao_derruba(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{isso nao e json")
    assert Config.load(path).start_mode == "fullscreen"


def test_salvar_e_recarregar(tmp_path):
    path = tmp_path / "c.json"
    cfg = Config.load(path)
    cfg.mini_position = [10, 20]
    cfg.mini_width = 333
    cfg.save()
    again = Config.load(path)
    assert again.mini_position == [10, 20] and again.mini_width == 333
