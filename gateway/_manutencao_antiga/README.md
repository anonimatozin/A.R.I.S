# Manutenção antiga do gateway (arquivo)

Aqui estão os **45 scripts avulsos de manutenção/debug** que existiam soltos
no `gateway/` (`check_*`, `fix_*`, `add_*`, `apply_*`, `deploy*`, `show_*`,
`get_*`, `read_*`...). Ninguém os importa — foi verificado por import no
projeto inteiro, nos testes e dentro do próprio gateway antes da mudança.

**Nada foi apagado.** Foram apenas MOVIDOS para cá (histórico do git
preservado com `git mv`) para o `gateway/` ficar com só o que é código
vivo: `server`, `web`, `core`, `auth`, `audit`, `memory`, `monitor`,
`security`, `terminal`, `services`, `agent`, `filesystem`, `events`,
`health`, `backup`, `tunnel_*` e o `dashboard.html` (servido pelo
`web.py`). `models.py` ficou no pacote por ser modelo de dados, não
script.

Eram scripts de diagnóstico pontuais (testar um endpoint, aplicar um fix
uma vez, inspecionar um handler) escritos durante o desenvolvimento do
gateway. Se um deles for útil de novo, mova de volta para `gateway/` e
acerte o import.

Para apagar de vez (só se você pedir):

```bash
git rm -r gateway/_manutencao_antiga
```
