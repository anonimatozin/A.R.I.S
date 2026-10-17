"""Testes das especificações das ferramentas da Parte 2 (registro e ToolSpec válidos)."""

from __future__ import annotations

import json

from aris_agent.contract.types import Risk
from aris_agent.tools import ToolRegistry, discover
from aris_agent.tools import pc as pacote_pc

ESPERADOS: dict[str, Risk] = {
    "pc_system_info": Risk.READ,
    "pc_list_processes": Risk.READ,
    "pc_list_windows": Risk.READ,
    "pc_list_dir": Risk.READ,
    "pc_read_file": Risk.READ,
    "pc_search_files": Risk.READ,
    "pc_write_file": Risk.WRITE,
    "pc_move_file": Risk.WRITE,
    "pc_delete_file": Risk.DESTRUCTIVE,
    "pc_open_app": Risk.EXEC,
    "pc_focus_window": Risk.EXEC,
    "pc_run_command": Risk.EXEC,
    "pc_python_run": Risk.EXEC,
    "calc": Risk.READ,
    "pc_clipboard_get": Risk.READ,
    "pc_clipboard_set": Risk.WRITE,
    "pc_screenshot": Risk.READ,
    "pc_ui_find": Risk.READ,
    "pc_ui_click": Risk.EXEC,
    "pc_ui_type": Risk.EXEC,
    "pc_keys": Risk.EXEC,
    "pc_mouse": Risk.EXEC,
}


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    pacote_pc.register(registry)
    return registry


def test_todas_as_ferramentas_registradas() -> None:
    registry = make_registry()
    nomes = {spec.name for spec in registry.specs()}
    assert nomes == set(ESPERADOS), f"faltando: {set(ESPERADOS) - nomes}; sobrando: {nomes - set(ESPERADOS)}"


def test_nomes_unicos_nao_levantam_erro() -> None:
    registry = make_registry()
    assert len(registry) == len(ESPERADOS)


def test_discover_encontra_o_pacote_pc() -> None:
    registry = ToolRegistry()
    processados = discover(registry)
    assert "pc" in processados
    assert set(ESPERADOS).issubset({spec.name for spec in registry.specs()})


def test_specs_completas_e_validas() -> None:
    registry = make_registry()
    for spec in registry.specs():
        assert spec.parameters.get("type") == "object", spec.name
        assert isinstance(spec.parameters.get("properties"), dict), spec.name
        assert spec.parameters.get("additionalProperties") is False, spec.name
        assert spec.description.strip(), spec.name
        assert spec.timeout_s > 0, spec.name
        assert "pc" in spec.tags, spec.name
        assert spec.risk == ESPERADOS[spec.name], spec.name
        json.dumps(spec.parameters)  # serializável para o LLM


def test_path_args_e_command_arg_apontam_para_parametros_existentes() -> None:
    registry = make_registry()
    for spec in registry.specs():
        props = spec.parameters["properties"]
        for path_arg in spec.path_args:
            assert path_arg in props, f"{spec.name}: path_arg {path_arg!r} fora do schema"
        if spec.command_arg:
            assert spec.command_arg in props, f"{spec.name}: command_arg ausente do schema"


def test_comandos_declarados_somente_onde_faz_sentido() -> None:
    registry = make_registry()
    por_nome = {spec.name: spec for spec in registry.specs()}
    assert por_nome["pc_run_command"].command_arg == "command"
    assert por_nome["pc_python_run"].command_arg == "code"
    assert por_nome["calc"].command_arg is None
    assert por_nome["pc_read_file"].command_arg is None


def test_path_args_dos_arquivos() -> None:
    registry = make_registry()
    por_nome = {spec.name: spec for spec in registry.specs()}
    assert por_nome["pc_read_file"].path_args == ("path",)
    assert por_nome["pc_write_file"].path_args == ("path",)
    assert por_nome["pc_search_files"].path_args == ("root",)
    assert por_nome["pc_move_file"].path_args == ("source", "destination")
    assert por_nome["pc_delete_file"].path_args == ("path",)
    assert por_nome["pc_run_command"].path_args == ("cwd",)
    # pc_open_app NÃO tem path_args: recebe nome, não caminho
    assert por_nome["pc_open_app"].path_args == ()


def test_saida_nao_confiavel_marcada_onde_le_conteudo_externo() -> None:
    registry = make_registry()
    por_nome = {spec.name: spec for spec in registry.specs()}
    assert por_nome["pc_read_file"].untrusted_output is True
    assert por_nome["pc_search_files"].untrusted_output is True
    assert por_nome["pc_clipboard_get"].untrusted_output is True
    assert por_nome["pc_write_file"].untrusted_output is False
    assert por_nome["pc_run_command"].untrusted_output is False
