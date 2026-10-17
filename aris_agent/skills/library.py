"""Catálogo de skills: varre diretórios, valida ``SKILL.md`` e implementa ``SkillCatalog``.

Prioridade dos diretórios (quem vem primeiro vence em caso de nome igual):

1. ``sections.skills.dirs`` do ``aris_agent.json`` (ordem declarada);
2. ``data_dir/skills/`` do usuário;
3. ``aris_skills/`` na raiz do projeto.

``reload()`` revarre tudo e detecta skills novas/alteradas/removidas pela data
de modificação e o tamanho do ``SKILL.md`` (conteúdo já lido é reaproveitado).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .frontmatter import FrontmatterError, parse_frontmatter, validar_campos

if TYPE_CHECKING:
    from ..config import AgentConfig

log = logging.getLogger("aris.agent.skills.library")

__all__ = ["SkillEntry", "SkillError", "SkillLibrary", "project_skills_dir"]

_MAX_RECURSOS = 200
_MAX_RESOURCE_BYTES_PADRAO = 200_000
_PASTAS_RECURSO = ("scripts", "references", "assets")


class SkillError(ValueError):
    """Problema ao ler uma skill ou recurso (caminho inválido, arquivo grande demais...)."""


def project_skills_dir() -> Path:
    """Pasta ``aris_skills/`` na raiz do projeto (skills embutidas)."""
    return Path(__file__).resolve().parents[2] / "aris_skills"


@dataclass
class SkillEntry:
    """Skill já validada e pronta para uso."""

    name: str
    description: str
    fields: dict[str, object]  # campos extras do frontmatter, preservados
    directory: Path
    skill_md: Path
    mtime_ns: int
    size: int
    body: str
    resources: tuple[str, ...]  # caminhos relativos (posix) em scripts/ references/ assets/


class SkillLibrary:
    """Biblioteca de skills que implementa o protocolo ``SkillCatalog``."""

    def __init__(self, dirs: list[Path] | tuple[Path, ...], *,
                 max_resource_bytes: int = _MAX_RESOURCE_BYTES_PADRAO) -> None:
        self._dirs = _dirs_unicos(dirs)
        try:
            self.max_resource_bytes = max(1024, int(max_resource_bytes))
        except (TypeError, ValueError):
            self.max_resource_bytes = _MAX_RESOURCE_BYTES_PADRAO
        self._lock = threading.RLock()
        self._entries: dict[str, SkillEntry] = {}
        self._cache: dict[Path, SkillEntry] = {}
        self.reload()

    # ------------------------------------------------------------------ criação

    @classmethod
    def from_config(cls, cfg: AgentConfig) -> SkillLibrary:
        """Monta a biblioteca a partir da configuração (seção ``skills`` + padrões)."""
        section = cfg.section("skills")
        dirs: list[Path] = []
        bruto = section.get("dirs", [])
        if isinstance(bruto, (list, tuple)):
            dirs.extend(Path(str(item)).expanduser() for item in bruto if str(item).strip())
        dirs.append(Path(cfg.data_dir) / "skills")
        dirs.append(project_skills_dir())
        return cls(dirs, max_resource_bytes=section.get("max_resource_bytes",
                                                       _MAX_RESOURCE_BYTES_PADRAO))

    # ------------------------------------------------------------------ leitura

    def names(self) -> list[str]:
        """Nomes das skills, em ordem alfabética."""
        with self._lock:
            return sorted(self._entries)

    def catalog_prompt(self) -> str:
        """Lista compacta ``- nome: descrição`` para o prompt do sistema."""
        with self._lock:
            entries = list(self._entries.values())
        entries.sort(key=lambda e: e.name)
        return "\n".join(f"- {e.name}: {e.description}" for e in entries)

    def descriptions(self) -> dict[str, str]:
        """Mapa nome → descrição (para ferramentas escolherem a skill certa)."""
        with self._lock:
            return {name: e.description for name, e in sorted(self._entries.items())}

    def load(self, name: str) -> str:
        """Corpo do ``SKILL.md`` + lista de recursos. Levanta ``KeyError`` se não existir."""
        entrada = self._pega(name)
        linhas = [
            f"# Skill: {entrada.name}",
            "",
            f"Descrição: {entrada.description}",
            "",
            entrada.body.strip(),
            "",
            "## Recursos disponíveis (ler com skill_read_resource)",
        ]
        if entrada.resources:
            linhas.extend(f"- {rel}" for rel in entrada.resources)
        else:
            linhas.append("- (nenhum recurso adicional)")
        return "\n".join(linhas) + "\n"

    def resources(self, name: str) -> list[str]:
        """Caminhos relativos dos recursos da skill (scripts/, references/, assets/)."""
        return list(self._pega(name).resources)

    def skill_dir(self, name: str) -> Path:
        """Pasta da skill. Levanta ``KeyError`` se não existir."""
        return self._pega(name).directory

    def entry(self, name: str) -> SkillEntry:
        """Entrada completa da skill. Levanta ``KeyError`` se não existir."""
        return self._pega(name)

    def __contains__(self, name: object) -> bool:
        with self._lock:
            return name in self._entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"<SkillLibrary {self.names()}>"

    # ------------------------------------------------------------------ recursos

    def read_resource(self, name: str, relative_path: str) -> str:
        """Lê um arquivo da pasta da skill com bloqueio de ``path traversal``.

        Levanta ``KeyError`` (skill desconhecida) ou ``SkillError`` (caminho
        fora da skill, arquivo inexistente ou grande demais).
        """
        entrada = self._pega(name)
        alvo = _resolver(entrada.directory, relative_path)
        if not alvo.is_file():
            raise SkillError(f"recurso não encontrado: {relative_path}")
        try:
            tamanho = alvo.stat().st_size
        except OSError as exc:
            raise SkillError(f"não consegui medir {relative_path}: {exc}") from exc
        if tamanho > self.max_resource_bytes:
            raise SkillError(
                f"recurso grande demais: {tamanho} bytes (máx. {self.max_resource_bytes})"
            )
        try:
            return alvo.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SkillError(f"recurso não é texto UTF-8: {relative_path}") from exc
        except OSError as exc:
            raise SkillError(f"não consegui ler {relative_path}: {exc}") from exc

    # ------------------------------------------------------------------ recarga

    def reload(self) -> list[str]:
        """Revarre os diretórios; devolve as mudanças detectadas (``+``/``~``/``-``)."""
        novo: dict[str, SkillEntry] = {}
        cache = dict(self._cache)
        for raiz in self._dirs:
            if not raiz.is_dir():
                log.debug("pasta de skills inexistente: %s", raiz)
                continue
            try:
                filhas = sorted((p for p in raiz.iterdir() if p.is_dir()), key=lambda p: p.name)
            except OSError as exc:
                log.warning("não consegui listar %s: %s", raiz, exc)
                continue
            for pasta in filhas:
                if pasta.name in novo:
                    log.debug(
                        "skill %r duplicada em %s; mantendo a primeira", pasta.name, raiz
                    )
                    continue
                md = pasta / "SKILL.md"
                if not md.is_file():
                    log.debug("pasta sem SKILL.md ignorada: %s", pasta)
                    continue
                try:
                    st = md.stat()
                except OSError as exc:
                    log.warning("não consegui stat %s: %s", md, exc)
                    continue
                entrada = cache.get(md)
                if (
                    entrada is not None
                    and entrada.directory == pasta
                    and entrada.mtime_ns == st.st_mtime_ns
                    and entrada.size == st.st_size
                    and entrada.name == pasta.name
                ):
                    novo[entrada.name] = entrada
                    continue
                entrada = self._carregar(pasta, md, st.st_mtime_ns, st.st_size)
                if entrada is not None:
                    novo[entrada.name] = entrada

        with self._lock:
            antigas = self._entries
            mudancas = _compara(antigas, novo)
            self._entries = novo
            self._cache = {e.skill_md: e for e in novo.values()}
        for mudanca in mudancas:
            log.info("reload de skills: %s", mudanca)
        if not mudancas:
            log.debug("reload de skills: nenhuma mudança (%d skills)", len(novo))
        return mudancas

    # ------------------------------------------------------------------ internos

    def _pega(self, name: str) -> SkillEntry:
        chave = name.strip() if isinstance(name, str) else name
        with self._lock:
            entrada = self._entries.get(chave)
        if entrada is None:
            raise KeyError(f"skill desconhecida: {name}")
        return entrada

    def _carregar(self, pasta: Path, md: Path, mtime_ns: int, size: int) -> SkillEntry | None:
        """Lê e valida um ``SKILL.md``; devolve ``None`` (com aviso) se inválido."""
        try:
            texto = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("ignorando skill em %s: %s", pasta, exc)
            return None
        try:
            campos, corpo = parse_frontmatter(texto)
            nome, descricao = validar_campos(campos)
        except FrontmatterError as exc:
            log.warning("skill inválida em %s: %s", pasta, exc)
            return None
        if nome != pasta.name:
            log.warning(
                "skill inválida em %s: frontmatter name=%r difere da pasta %r",
                pasta, nome, pasta.name,
            )
            return None
        extras = {k: v for k, v in campos.items() if k not in ("name", "description")}
        return SkillEntry(
            name=nome,
            description=descricao,
            fields=extras,
            directory=pasta,
            skill_md=md,
            mtime_ns=mtime_ns,
            size=size,
            body=corpo,
            resources=self._recursos(pasta),
        )

    def _recursos(self, pasta: Path) -> tuple[str, ...]:
        """Lista (ordenada) dos arquivos em scripts/, references/ e assets/."""
        achados: list[str] = []
        for sub in _PASTAS_RECURSO:
            raiz = pasta / sub
            if not raiz.is_dir():
                continue
            try:
                for arquivo in sorted(raiz.rglob("*")):
                    if arquivo.is_file():
                        rel = arquivo.relative_to(pasta).as_posix()
                        achados.append(rel)
            except OSError as exc:
                log.warning("não consegui listar recursos de %s: %s", pasta, exc)
            if len(achados) >= _MAX_RECURSOS:
                log.warning("skill %s com recursos demais; lista truncada em %d",
                            pasta.name, _MAX_RECURSOS)
                break
        return tuple(achados[:_MAX_RECURSOS])


def _dirs_unicos(dirs: list[Path] | tuple[Path, ...]) -> tuple[Path, ...]:
    """Expande e deduplica preservando a ordem (primeiro = prioridade)."""
    vistos: set[str] = set()
    saida: list[Path] = []
    for item in dirs:
        caminho = Path(item).expanduser()
        chave = str(caminho).lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(caminho)
    return tuple(saida)


def _resolver(base: Path, relative_path: str) -> Path:
    """Resolve ``relative_path`` dentro de ``base`` bloqueando traversal e links."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise SkillError("parâmetro 'relative_path' obrigatório e não vazio")
    rel = relative_path.strip().replace("\\", "/")
    if rel.startswith("/") or rel.startswith("~"):
        raise SkillError(f"caminho absoluto não é permitido: {relative_path!r}")
    if len(rel) >= 2 and rel[1] == ":":
        raise SkillError(f"caminho absoluto não é permitido: {relative_path!r}")
    caminho = Path(rel)
    if caminho.is_absolute():
        raise SkillError(f"caminho absoluto não é permitido: {relative_path!r}")
    if any(parto == ".." for parto in caminho.parts):
        raise SkillError(f"'..' não é permitido: {relative_path!r}")
    try:
        base_res = base.resolve()
        alvo = (base_res / caminho).resolve()
    except (OSError, ValueError) as exc:
        raise SkillError(f"não consegui resolver {relative_path!r}: {exc}") from exc
    if not alvo.is_relative_to(base_res):
        raise SkillError(f"caminho fora da pasta da skill: {relative_path!r}")
    return alvo


def _compara(antigas: dict[str, SkillEntry], novas: dict[str, SkillEntry]) -> list[str]:
    """Lista legível das mudanças entre duas varreduras."""
    mudancas: list[str] = []
    for nome in sorted(set(antigas) | set(novas)):
        if nome not in novas:
            mudancas.append(f"- {nome} (removida)")
        elif nome not in antigas:
            mudancas.append(f"+ {nome}")
        elif antigas[nome].mtime_ns != novas[nome].mtime_ns:
            mudancas.append(f"~ {nome} (alterada)")
    return mudancas
