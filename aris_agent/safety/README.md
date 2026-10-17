# `aris_agent/safety` — segurança, permissões e executor de ferramentas (Parte 5)

Todo `tool.run()` do agente passa por aqui. O `SafeExecutor` implementa o
protocolo `ToolExecutor` do contrato:

```
kill switch → ferramenta no registry → validação de schema → política →
proteções de laço (repetição/limites) → confirmação (timeout = negar) →
execução com timeout/cancel → redação + truncamento + wrap_untrusted →
taint → auditoria JSONL → ToolResult
```

Nenhuma exceção escapa para o laço do agente: tudo vira `ToolResult(ok=False, error=...)`.

## Tabela de política

| Risco | `strict` (padrão) | `balanced` | `readonly` |
|---|---|---|---|
| `READ` | automático, **exceto** caminhos sensíveis (negados) | igual | automático (exceto sensíveis) |
| `WRITE` | automático só se **todos** os `path_args` resolvidos ficarem dentro de `allowed_roots`; fora disso, confirmação | igual | **negado** |
| `EXEC` | confirmação, exceto lista de permissões (`safety.exec_allowlist`: `dir`, `git status`, `python --version`, ferramentas nomeadas como `pc_open_app`...) | confirmação, exceto lista de permissões **e** comandos de verbo seguro com todos os alvos dentro das raízes (`python` só com script `.py`, nunca `-c`) | **negado** |
| `DESTRUCTIVE` | **sempre** confirmação forte (`hard_confirm=True`) com prévia de alvos resolvidos e contagem de arquivos | igual | **negado** |
| Ação em lote (≥ `batch_path_threshold` caminhos, curinga `*`/`?`, args "todos..."/`select_all`) | **sempre** confirmação forte; alvos protegidos são **negados** direto | igual | negado (lote) ou negado por risco |
| Depois de saída não confiável (`ctx.taint`) | `EXEC`, `DESTRUCTIVE` e ferramentas com `url_args` (envio p/ fora) exigem **confirmação forte**, mesmo na lista de permissões; a pergunta avisa "esta ação veio depois de ler conteúdo externo" | igual | — (EXEC/DESTRUCTIVE já negados) |

Regras que valem em **todos** os modos:

- **Negação absoluta** (abaixo): sem opção de confirmar.
- Modo `readonly` não desliga negações absolutas; nenhuma configuração desliga.
- `allowed_roots` é comparado por **partes de caminho** após `Path.resolve()`
  (nunca por prefixo de string: `C:\ws` não contém `C:\ws_evil`).
- `..`, links simbólicos e caixa são resolvidos **antes** da comparação.

## Negações absolutas (sem confirmação)

**Comandos** (normalizados antes de comparar: caixa, aspas, carets `^`, crases,
variáveis `%x%`/`$env:x`, wrappers `cmd /c`, `powershell -c/-enc`, `start`,
encadeamentos `& ; | &&`):

| Categoria | Exemplos barrados |
|---|---|
| Formatar/particionar | `format`, `Format-Volume`, `diskpart`, `bcdedit`, `initialize-disk`, `clear-disk`, `new-partition` |
| Registro HKLM | `reg delete HKLM\...`, `Remove-Item HKLM:...` |
| Remoção em área protegida | `rd`/`rmdir`/`Remove-Item -Recurse`/`del` apontando para raiz de disco, `C:\Windows` & pastas de sistema, pasta do usuário inteira, raiz de compartilhamento UNC |
| Ofuscação | `-EncodedCommand`/`-enc <base64>`, `FromBase64String` + `iex` |
| Baixar-e-executar | `iwr/irm/curl/wget \| iex`, `curl \| sh/bash/python` |
| Defender/firewall | `Set-MpPreference -Disable*`, `sc/net stop windefend`, `netsh advfirewall ... off`, `Set-NetFirewallProfile -Enabled False`, `DisableAntiSpyware` |
| Política de execução global | `Set-ExecutionPolicy` sem `-Scope Process/CurrentUser` |
| Cofres de credenciais | `cmdkey`, `vaultcmd`, `mimikatz`/`sekurlsa` |
| Cofres em **caminhos** (qualquer risco) | `.ssh`, `.aws`, `.azure`, `.gnupg`, `.kube`, `.env`/`.env.*`, `id_rsa`/`id_ed25519`, `.pfx/.p12/.ppk/.kdbx/.pem/.key`, perfis de Chrome/Edge/Firefox/Brave (`User Data`, `Profiles`), `Microsoft\Credentials|Vault|Protect`, `System32\config\SAM|SECURITY`, `NTUSER.DAT` |
| Caminhos inválidos | nomes reservados (`CON`, `NUL`, `PRN`, `AUX`, `COM1`..., com ou sem extensão), namespace `\\.\` |
| Área protegida (escrita/destruição/lote) | raiz de disco (`C:\`), raiz de UNC (`\\server\share`), `C:\Windows`, `System32`, `Program Files`, `ProgramData`, pasta do usuário inteira, `C:\Users` |

## Proteções de laço

- Mesma chamada (ferramenta + argumentos idênticos) **3 vezes seguidas** → erro
  explicativo pedindo outra estratégia (`safety.repeat_limit`).
- `EXEC`/`DESTRUCTIVE`: `safety.exec_per_minute` (padrão 10) por minuto e
  `safety.exec_per_task` (padrão 40) por tarefa/sessão.
- Confirmação sem resposta em `confirm_timeout_s` → **negar** (`cli_confirm` e
  o próprio executor aplicam o timeout).
- Ferramenta com `spec.timeout_s` estourado ou `ctx.cancel` setado → erro e
  abandono da chamada (a thread da ferramenta é abandonada, ver limitações).

## KillSwitch

`KillSwitch(data_dir)` ativa por: `engage()` (método Python), arquivo
`data_dir/STOP` (verificado a cada chamada e durante execuções) e atalho global
opcional (`safety.enable_hotkey`, biblioteca `keyboard` **opcional**, import
preguiçoso com aviso — não instalada neste projeto). Ao ativar, seta o `cancel`
de todas as tarefas registradas e bloqueia novas chamadas até `reset()` (que
remove o arquivo `STOP`).

## Auditoria

Arquivo JSONL em `config.audit_log_path` (rotação por tamanho,
`safety.audit_max_bytes`, backup `.1`). Por linha: `ts`, `session_id`, `tool`,
`args` **redigidos**, `risk`, `decision`, `reason`, `confirmed`, `duration_ms`,
`ok`, `error` (redigido), `resumo` (status + contagem de caracteres, **nunca o
conteúdo do arquivo**), `taint`, `mode`, `injection` (padrões de prompt
injection detectados na saída — o texto **não** é removido).
`safety.audit_preview=true` adiciona os primeiros 200 caracteres da saída
redigidos (desligado por padrão).

## Limitações conhecidas (sendo franco)

1. **A detecção de comandos não é barreira perfeita.** Ela normaliza o texto
   (caixa, aspas, carets, variáveis, wrappers) para dificultar contornos
   simples, mas um modelo suficientemente motivado (ou um binário reescrito em
   base64/PowerShell com concatenação em tempo de execução, `Start-Process` de
   um helper, script em arquivo que faz o sujo, etc.) pode escapar. Ferramentas
   também podem ignorar a política se escreverem código próprio — por isso a
   Parte 5 depende de **todas** as chamadas passarem por aqui.
2. **Não é sandbox.** Rodamos o mesmo processo do usuário; ferramenta maliciosa
   ou bugada pode ler/escrever qualquer coisa o OS permite. A contenção real
   (AppContainer, job objects, VM) fica fora do escopo.
3. **Threads não são mortas.** No timeout/cancel, a thread da ferramenta é
   abandonada (daemon): um subprocesso pendurado pode continuar em segundo
   plano. Cabe à ferramenta (Parte 2) respeitar `ctx.cancel` e matar filhos.
4. **Falso positivo em negações absolutas:** `.env.example`, `chave.pem` de
   certificado público, `Set-MpPreference -Disable... $false` (reativar) são
   negados por segurança. Remova a necessidade via configuração, não via código.
5. **`url_args` como proxy de "envio para fora":** não há como saber se a
   ferramenta faz GET ou POST; qualquer ferramenta com `url_args` após `taint`
   exige confirmação forte — pesquisas longas na web vão pedir confirmação após
   a primeira página não confiável. É proposital (exfiltração via URL é o
   vetor clássico), mas é inconveniente.
6. **Só Windows testado.** Caminhos UNC com host inexistente demoram ~1 s para
   resolver (tentativa de SMB); nomes reservados e `\\?\` dependem do
   comportamento do `pathlib` no Windows.
7. **`keyboard` não instalada**: o atalho global só funciona se o usuário
   instalar a lib e ligar `enable_hotkey`; pode exigir admin.
8. **Confirmação por linha de comando** usa `input()` em thread: no timeout a
   thread pode ficar esperando (daemon) e capturar um input posterior se o
   usuário digitar tarde demais.

## Configuração (`aris_agent.json` → `sections.safety`)

```json
{
  "sections": {
    "safety": {
      "mode": "strict",
      "exec_allowlist": ["dir", "git status", "python --version", "pc_open_app"],
      "exec_per_minute": 10,
      "exec_per_task": 40,
      "repeat_limit": 3,
      "batch_path_threshold": 10,
      "audit_max_bytes": 2000000,
      "audit_preview": false,
      "confirm_timeout_s": 30,
      "enable_hotkey": false,
      "hotkey": "ctrl+alt+F12"
    }
  }
}
```

Sem dependências externas (stdlib apenas) — ver `requirements/parte5.txt`.
