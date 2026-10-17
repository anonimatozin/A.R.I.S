# Pedidos da Parte 8

## 1. `requirements/parte7.txt` — linha 4 sem comentário (para a Parte 7)

A linha

```
Sem dependências externas: o laço usa só a biblioteca padrão do Python 3.12
```

não começa com `#`, então `pip install -r requirements/parte7.txt` falha com
`Invalid requirement`. Corrigir adicionando `# ` no início. **Não editei por
regra** (arquivo de outra parte); registrado aqui.

## 2. Bug do CLL1 em `core/aris.py:1734` (fora de escopo, reiterado)

A chamada passa `message_callback=` onde o construtor da instância CLL1
espera provavelmente `on_message=`. É bug **pré-existente** (a camada CLL1
está desabilitada) e mexer nele muda comportamento sem teste de cobertura —
a Parte 8 deliberadamente **não tocou**, conforme anunciado na paridade.
Quem assumir a CLL1 deve corrigir com teste de regressão.

## 3. `pyproject.toml` — script `aris` quebrado (para quem mantém o packaging)

```toml
[project.scripts]
aris = "main:main"
```

Não existe `main.py` na raiz → `pip install -e .` gera um comando `aris`
que explode. O launcher real é `aris.sh` (Linux) / `aris.bat` (Windows aponta
para `agent/aris_cli.py`, que é outro programa). Corrigir o entry point para
o módulo verdadeiro ou removê-lo.

## 4. Observação de UX da confirmação (sem pedido de código)

Com o microfone desligado a confirmação lê do **teclado** com timeout
(`Confirmar (sim/não): `); se o terminal não estiver focado, o timeout
estoura e a ação é **negada** (comportamento seguro, mas pode frustrar).
Se um dia existir atalho/atalho de janela, dá para acrescentar um canal de
confirmação sem tocar na política (o `ConfirmFn` é injetado pela ponte).
