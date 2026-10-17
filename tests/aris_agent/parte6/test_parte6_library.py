"""Testes da SkillLibrary: varredura, prioridade, reload e traversal (Parte 6)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.protocols import SkillCatalog
from aris_agent.skills import SkillError, SkillLibrary, project_skills_dir

_PADRAO = "Descricao generica de teste, valida o bastante para o catalogo."


def _skill(
    raiz: Path,
    nome: str,
    descricao: str = _PADRAO,
    corpo: str = "## Objetivo\n\nfaz a coisa certa.\n",
    extras: str = "",
) -> Path:
    """Cria uma pasta de skill com SKILL.md válido."""
    pasta = raiz / nome
    pasta.mkdir(parents=True, exist_ok=True)
    texto = f"---\nname: {nome}\ndescription: {descricao}\n{extras}---\n\n{corpo}"
    (pasta / "SKILL.md").write_text(texto, encoding="utf-8")
    return pasta


def _mtime(md: Path, delta_ns: int = 5_000_000_000) -> None:
    """Alterna a data de modificação para simular edição."""
    st = md.stat()
    os.utime(md, ns=(st.st_atime_ns + delta_ns, st.st_mtime_ns + delta_ns))


def test_satisfaz_o_protocolo_skill_catalog(tmp_path) -> None:
    _skill(tmp_path, "minha-skill")
    lib = SkillLibrary([tmp_path])
    assert isinstance(lib, SkillCatalog)
    assert isinstance(lib, SkillLibrary)
    assert len(lib) == 1 and "minha-skill" in lib


def test_nomes_e_catalog_prompt_compacto(tmp_path) -> None:
    _skill(tmp_path, "zeta-skill", descricao="Usa para zeta.")
    _skill(tmp_path, "alfa-skill", descricao="Usa para alfa.")
    lib = SkillLibrary([tmp_path])
    assert lib.names() == ["alfa-skill", "zeta-skill"]
    assert lib.catalog_prompt() == (
        "- alfa-skill: Usa para alfa.\n- zeta-skill: Usa para zeta."
    )


def test_catalog_prompt_vazio_quando_nao_ha_skills(tmp_path) -> None:
    lib = SkillLibrary([tmp_path / "nao-existe"])
    assert lib.names() == []
    assert lib.catalog_prompt() == ""


def test_load_devolve_corpo_e_recursos(tmp_path) -> None:
    pasta = _skill(tmp_path, "minha-skill")
    (pasta / "references").mkdir()
    (pasta / "references" / "guia.md").write_text("# Guia\n", encoding="utf-8")
    (pasta / "scripts").mkdir()
    (pasta / "scripts" / "rodar.py").write_text("print(1)\n", encoding="utf-8")
    lib = SkillLibrary([tmp_path])

    texto = lib.load("minha-skill")
    assert texto.startswith("# Skill: minha-skill")
    assert "Descrição:" in texto
    assert "faz a coisa certa." in texto
    assert "- references/guia.md" in texto
    assert "- scripts/rodar.py" in texto
    assert lib.resources("minha-skill") == ["scripts/rodar.py", "references/guia.md"]
    assert lib.skill_dir("minha-skill") == pasta


def test_load_sem_recursos_avisa(tmp_path) -> None:
    _skill(tmp_path, "minha-skill")
    texto = SkillLibrary([tmp_path]).load("minha-skill")
    assert "- (nenhum recurso adicional)" in texto


def test_load_desconhecida_levanta_keyerror(tmp_path) -> None:
    _skill(tmp_path, "minha-skill")
    lib = SkillLibrary([tmp_path])
    with pytest.raises(KeyError, match="outra-skill"):
        lib.load("outra-skill")
    with pytest.raises(KeyError):
        lib.resources("outra-skill")
    with pytest.raises(KeyError):
        lib.skill_dir("outra-skill")


def test_skill_invalida_ignorada_sem_derrubar_as_demais(tmp_path, caplog) -> None:
    _skill(tmp_path, "boa-skill")
    quebrada = tmp_path / "quebrada"
    quebrada.mkdir()
    (quebrada / "SKILL.md").write_text("sem frontmatter nenhum\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="aris.agent.skills.library"):
        lib = SkillLibrary([tmp_path])
    assert lib.names() == ["boa-skill"]
    assert any("quebrada" in r.getMessage() for r in caplog.records)


def test_skill_com_nome_diferente_da_pasta_ignorada(tmp_path, caplog) -> None:
    pasta = tmp_path / "pasta-x"
    pasta.mkdir()
    (pasta / "SKILL.md").write_text(
        "---\nname: outro-nome\ndescription: nao bate com a pasta.\n---\n", encoding="utf-8"
    )
    with caplog.at_level("WARNING", logger="aris.agent.skills.library"):
        lib = SkillLibrary([tmp_path])
    assert lib.names() == []
    assert any("difere da pasta" in r.getMessage() for r in caplog.records)


def test_pasta_sem_skill_md_ignorada(tmp_path) -> None:
    (tmp_path / "so-pasta").mkdir()
    (tmp_path / "arquivo.solto").write_text("x", encoding="utf-8")
    lib = SkillLibrary([tmp_path])
    assert lib.names() == []


def test_prioridade_do_usuario_sobre_o_projeto(tmp_path) -> None:
    usuario = tmp_path / "usuario"
    projeto = tmp_path / "projeto"
    _skill(usuario, "duplicada", descricao="versao do usuario")
    _skill(projeto, "duplicada", descricao="versao do projeto")
    lib = SkillLibrary([usuario, projeto])
    assert lib.names() == ["duplicada"]
    assert "versao do usuario" in lib.catalog_prompt()
    assert "versao do projeto" not in lib.catalog_prompt()


def test_dirs_repetidos_nao_duplicam_skill(tmp_path) -> None:
    _skill(tmp_path, "minha-skill")
    lib = SkillLibrary([tmp_path, tmp_path])
    assert lib.names() == ["minha-skill"]


def test_reload_detecta_nova_alterada_e_removida(tmp_path) -> None:
    lib = SkillLibrary([tmp_path])
    assert lib.reload() == []

    _skill(tmp_path, "nova-skill")
    assert lib.reload() == ["+ nova-skill"]
    assert lib.names() == ["nova-skill"]

    md = tmp_path / "nova-skill" / "SKILL.md"
    md.write_text(
        "---\nname: nova-skill\ndescription: editada depois.\n---\n\n## Objetivo\n\noutra coisa\n",
        encoding="utf-8",
    )
    _mtime(md)
    assert lib.reload() == ["~ nova-skill (alterada)"]
    assert "editada depois" in lib.catalog_prompt()
    assert "outra coisa" in lib.load("nova-skill")

    shutil.rmtree(tmp_path / "nova-skill")
    assert lib.reload() == ["- nova-skill (removida)"]
    assert lib.names() == []


def test_reload_apaga_skill_invalidada(tmp_path) -> None:
    _skill(tmp_path, "minha-skill")
    lib = SkillLibrary([tmp_path])
    assert lib.names() == ["minha-skill"]
    (tmp_path / "minha-skill" / "SKILL.md").write_text("quebrou\n", encoding="utf-8")
    assert lib.reload() == ["- minha-skill (removida)"]


def test_read_resource_ok(tmp_path) -> None:
    pasta = _skill(tmp_path, "minha-skill")
    (pasta / "references").mkdir()
    arquivo = pasta / "references" / "guia.md"
    arquivo.write_text("# Guia\nconteudo\n", encoding="utf-8")
    lib = SkillLibrary([tmp_path])
    assert lib.read_resource("minha-skill", "references/guia.md") == "# Guia\nconteudo\n"
    assert lib.read_resource("minha-skill", "references\\guia.md") == "# Guia\nconteudo\n"


@pytest.mark.parametrize(
    "rel",
    [
        "../fora.txt",
        "..\\fora.txt",
        "../../fora.txt",
        "references/../../fora.txt",
        "./references/../../../fora.txt",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "C:\\Windows\\win.ini",
        "\\\\servidor\\compartilhado\\x.md",
        "~\\x.md",
    ],
)
def test_read_resource_bloqueia_traversal(tmp_path, rel: str) -> None:
    (tmp_path / "fora.txt").write_text("segredo", encoding="utf-8")
    pasta = _skill(tmp_path, "minha-skill")
    (pasta / "references").mkdir()
    (pasta / "references" / "guia.md").write_text("ok", encoding="utf-8")
    lib = SkillLibrary([tmp_path])
    with pytest.raises(SkillError):
        lib.read_resource("minha-skill", rel)


def test_read_resource_bloqueia_link_simbolico(tmp_path) -> None:
    fora = tmp_path / "fora.txt"
    fora.write_text("segredo do usuario", encoding="utf-8")
    pasta = _skill(tmp_path, "minha-skill")
    (pasta / "references").mkdir()
    link = pasta / "references" / "link.md"
    try:
        link.symlink_to(fora)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"sem permissão para criar link simbólico: {exc}")
    lib = SkillLibrary([tmp_path])
    with pytest.raises(SkillError, match="fora da pasta"):
        lib.read_resource("minha-skill", "references/link.md")


def test_read_resource_rejeita_vazio_e_inexistente(tmp_path) -> None:
    _skill(tmp_path, "minha-skill")
    lib = SkillLibrary([tmp_path])
    with pytest.raises(SkillError, match="obrigatório"):
        lib.read_resource("minha-skill", "   ")
    with pytest.raises(SkillError, match="não encontrado"):
        lib.read_resource("minha-skill", "references/nao-existe.md")
    with pytest.raises(SkillError):
        lib.read_resource("minha-skill", ".")


def test_read_resource_limita_tamanho(tmp_path) -> None:
    pasta = _skill(tmp_path, "minha-skill")
    (pasta / "references").mkdir()
    grande = pasta / "references" / "grande.md"
    grande.write_text("x" * 5000, encoding="utf-8")
    lib = SkillLibrary([tmp_path], max_resource_bytes=2048)
    with pytest.raises(SkillError, match="grande demais"):
        lib.read_resource("minha-skill", "references/grande.md")
    assert lib.max_resource_bytes == 2048


def test_read_resource_nao_texto_utf8(tmp_path) -> None:
    pasta = _skill(tmp_path, "minha-skill")
    (pasta / "assets").mkdir()
    binario = pasta / "assets" / "foto.jpg"
    binario.write_bytes(b"\xff\xfe\x00\x01")
    lib = SkillLibrary([tmp_path])
    with pytest.raises(SkillError, match="UTF-8"):
        lib.read_resource("minha-skill", "assets/foto.jpg")


def test_from_config_prioriza_pasta_do_usuario(tmp_path) -> None:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    _skill(cfg.data_dir / "skills", "pesquisa-web", descricao="versao do usuario do arquivo")
    lib = SkillLibrary.from_config(cfg)
    # a skill embutida do projeto também existe; a do usuário deve vencer
    assert "versao do usuario do arquivo" in lib.catalog_prompt()
    assert lib.entry("pesquisa-web").directory == cfg.data_dir / "skills" / "pesquisa-web"


def test_from_config_aceita_dirs_extras(tmp_path) -> None:
    extra = tmp_path / "extra"
    _skill(extra, "extra-skill", descricao="vem do diretorio extra.")
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    cfg.sections["skills"] = {"dirs": [str(extra)]}
    lib = SkillLibrary.from_config(cfg)
    assert "extra-skill" in lib.names()
    assert "pesquisa-web" in lib.names()  # padrão continua presente


def test_from_config_padroes_dois_diretorios(tmp_path) -> None:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    _skill(cfg.data_dir / "skills", "do-usuario", descricao="skill so do usuario.")
    lib = SkillLibrary.from_config(cfg)
    assert lib.max_resource_bytes == 200_000
    # varre data_dir/skills (usuário) e aris_skills/ (projeto)
    assert "do-usuario" in lib.names()
    assert "pesquisa-web" in lib.names()
    assert project_skills_dir().is_dir()


def test_repr_e_descriptions(tmp_path) -> None:
    _skill(tmp_path, "minha-skill", descricao="Usa para teste.")
    lib = SkillLibrary([tmp_path])
    assert lib.descriptions() == {"minha-skill": "Usa para teste."}
    assert "minha-skill" in repr(lib)
