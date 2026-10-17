"""Parser de frontmatter do ``SKILL.md`` — próprio, sem PyYAML.

Formato aceito (simples, compatível com o formato aberto de Agent Skills):

* o arquivo começa com uma linha ``---`` e o frontmatter termina em outra ``---``;
* cada linha é ``chave: valor``; aspas simples/duplas nas pontas são removidas;
* linhas cujo conteúdo começa com ``#`` são comentários; em valor sem aspas,
  um `` #`` marca comentário de fim de linha;
* blocos aninhados (ex.: ``metadata:`` com chaves indentadas) são aceitos e
  preservados como ``dict``;
* campos extras são preservados na ordem em que aparecem.
"""

from __future__ import annotations

import re

__all__ = [
    "FrontmatterError",
    "parse_frontmatter",
    "validar_campos",
    "validar_descricao",
    "validar_nome",
]

_MAX_NOME = 64
_MAX_DESCRICAO = 1024

# minúsculas, números e hífen; sem hífen no começo/fim e sem hífen duplo.
_NOME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CHAVE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
_PAR_RE = re.compile(r"^(\s*)([A-Za-z0-9][A-Za-z0-9_.\-]*):(.*)$")


class FrontmatterError(ValueError):
    """Frontmatter ausente, malformado ou com campo inválido."""


def _limpar_valor(raw: str) -> str:
    """Remove comentários e aspas externas de um valor simples."""
    valor = raw.strip()
    if not valor:
        return ""
    if valor[0] in "\"'" and len(valor) >= 2 and valor[-1] == valor[0]:
        return valor[1:-1]
    if valor.startswith("#"):
        return ""
    corte = re.search(r"\s+#", valor)
    if corte:
        valor = valor[: corte.start()].rstrip()
    return valor


def parse_frontmatter(texto: str) -> tuple[dict[str, object], str]:
    """Separa ``SKILL.md`` em (campos, corpo).

    Levanta ``FrontmatterError`` se o frontmatter estiver ausente, aberto sem
    fechar ou com linha que não seja par ``chave: valor``.
    """
    if texto.startswith("\ufeff"):
        texto = texto[1:]
    linhas = texto.splitlines()
    if not linhas or linhas[0].strip() != "---":
        raise FrontmatterError("o arquivo deve começar com '---' (frontmatter)")

    campos: dict[str, object] = {}
    # pilha de (indentacao esperada, dict-alvo) para blocos aninhados
    pilha: list[tuple[int, dict[str, object]]] = [(0, campos)]
    fim: int | None = None

    for i in range(1, len(linhas)):
        linha = linhas[i]
        strip = linha.strip()
        if strip in ("---", "..."):
            fim = i
            break
        if not strip or strip.startswith("#"):
            continue
        par = _PAR_RE.match(linha)
        if par is None:
            raise FrontmatterError(f"linha {i + 1} inválida no frontmatter: {strip!r}")
        indent, chave, bruto = par.group(1), par.group(2), par.group(3)
        while len(pilha) > 1 and len(indent) < pilha[-1][0]:
            pilha.pop()
        alvo = pilha[-1][1]
        if not bruto.strip():
            filho: dict[str, object] = {}
            alvo[chave] = filho
            pilha.append((len(indent) + 2, filho))
        else:
            alvo[chave] = _limpar_valor(bruto)

    if fim is None:
        raise FrontmatterError("frontmatter não terminado: falta o '---' de fechamento")
    corpo = "\n".join(linhas[fim + 1 :]).lstrip("\n")
    return campos, corpo


def validar_nome(nome: object) -> str:
    """Valida o campo ``name`` e devolve o valor em ``str``."""
    if not isinstance(nome, str) or not nome.strip():
        raise FrontmatterError("campo 'name' ausente ou vazio")
    nome = nome.strip()
    if len(nome) > _MAX_NOME:
        raise FrontmatterError(f"campo 'name' com {len(nome)} caracteres (máx. {_MAX_NOME})")
    if not _NOME_RE.match(nome):
        raise FrontmatterError(
            "campo 'name' inválido: use só minúsculas, números e hífens, "
            "sem hífen no começo/fim nem hífen duplo"
        )
    return nome


def validar_descricao(descricao: object) -> str:
    """Valida o campo ``description`` e devolve o valor em ``str``."""
    if not isinstance(descricao, str) or not descricao.strip():
        raise FrontmatterError("campo 'description' ausente ou vazio")
    descricao = descricao.strip()
    if len(descricao) > _MAX_DESCRICAO:
        raise FrontmatterError(
            f"campo 'description' com {len(descricao)} caracteres (máx. {_MAX_DESCRICAO})"
        )
    return descricao


def validar_campos(campos: dict[str, object]) -> tuple[str, str]:
    """Valida ``name`` e ``description``; devolve a tupla (nome, descrição)."""
    for chave in campos:
        if not _CHAVE_RE.match(str(chave)):
            raise FrontmatterError(f"chave de frontmatter inválida: {chave!r}")
    return validar_nome(campos.get("name")), validar_descricao(campos.get("description"))
