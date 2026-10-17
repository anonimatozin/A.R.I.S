# OWNERS — quem é dono de quê

Ninguém edita arquivo de outra parte. Caminho fora desta tabela = não tocar.

| Caminho | Parte dona |
|---|---|
| `aris_agent/__init__.py` | 0 |
| `aris_agent/CONTRATO.md` | 0 |
| `aris_agent/OWNERS.md` | 0 |
| `aris_agent/config.py` | 0 |
| `aris_agent/fakes.py` | 0 |
| `aris_agent/contract/` (todo) | 0 |
| `aris_agent/tools/__init__.py` | 0 |
| `aris_agent/tools/registry.py` | 0 |
| `requirements/parte0.txt` | 0 |
| `tests/aris_agent/conftest.py` | 0 |
| `tests/aris_agent/parte0/` | 0 |
| `docs/agent/.gitkeep` | 0 |
| `docs/agent/pedidos/.gitkeep` | 0 |
| `aris_agent/llm/` | 1 |
| `requirements/parte1.txt` | 1 |
| `tests/aris_agent/parte1/` | 1 |
| `docs/agent/pedidos/parte1.md` | 1 |
| `aris_agent/tools/pc/` | 2 |
| `requirements/parte2.txt` | 2 |
| `tests/aris_agent/parte2/` | 2 |
| `docs/agent/pedidos/parte2.md` | 2 |
| `aris_agent/tools/web/` | 3 |
| `requirements/parte3.txt` | 3 |
| `tests/aris_agent/parte3/` | 3 |
| `docs/agent/pedidos/parte3.md` | 3 |
| `aris_agent/memory/` | 4 |
| `aris_agent/tools/memory_tools/` | 4 |
| `requirements/parte4.txt` | 4 |
| `tests/aris_agent/parte4/` | 4 |
| `docs/agent/pedidos/parte4.md` | 4 |
| `aris_agent/safety/` | 5 |
| `requirements/parte5.txt` | 5 |
| `tests/aris_agent/parte5/` | 5 |
| `docs/agent/pedidos/parte5.md` | 5 |
| `aris_agent/skills/` | 6 |
| `aris_agent/tools/skill_tools/` | 6 |
| `aris_skills/` (conteúdo) | 6 |
| `requirements/parte6.txt` | 6 |
| `tests/aris_agent/parte6/` | 6 |
| `docs/agent/pedidos/parte6.md` | 6 |
| `aris_agent/core/` | 7 |
| `requirements/parte7.txt` | 7 |
| `tests/aris_agent/parte7/` | 7 |
| `docs/agent/pedidos/parte7.md` | 7 |
| `requirements/parte8.txt` | 8 |
| `tests/aris_agent/parte8/` | 8 |
| `docs/agent/pedidos/parte8.md` | 8 |
| `aris_agent/evals/` | 9 |
| `requirements/parte9.txt` | 9 |
| `tests/aris_agent/parte9/` | 9 |
| `docs/agent/pedidos/parte9.md` | 9 |

Exceções:

- **Parte 0** cria os `__init__.py` dos subpacotes das outras partes (só com a
  docstring "Dono: Parte N"); a partir daí o dono é quem edita.
- **Parte 8** é a única que pode mexer em código antigo da ARIS (`core/`, `agent/`,
  `gateway/`...) e em `docs/agent/pedidos/parte8.md`.
- Pedidos de mudança no contrato vão em `docs/agent/pedidos/parteN.md` (arquivo do
  pedido), nunca em `contract/`.
