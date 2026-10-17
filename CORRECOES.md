# Correções na ARIS — revisão de 17/10/2026

Como aplicar: copie o conteúdo desta pasta por cima do repositório (mesmos caminhos) e rode
`python -m pytest tests -q`. Os arquivos estão completos (não são trechos) e mantêm os finais
de linha originais de cada arquivo.

## Bugs corrigidos

| # | Arquivo | Problema | Correção |
|---|---|---|---|
| 1 | `core/memcore/paths.py`, `core/memory_db.py` | No Linux, `Path("D:/ARIS_MEMORY")` é um caminho relativo: o `mkdir` criava uma pasta literal `D:` dentro de onde a ARIS fosse iniciada e dizia que o "drive principal" estava disponível. A memória mudava de lugar conforme o diretório atual. | Caminhos de unidade do Windows são ignorados fora do Windows; padrão vira `<projeto>/data/memory`. |
| 2 | `edge/edge_config.py` | `Path("~/cll1/data")` não expande o `~`: `EdgeConfig()` criava uma pasta literal `~` no diretório atual (aconteceu ao rodar os testes). | `.expanduser()` nos padrões. |
| 3 | `core/tools/pc_tools.py` | `pc_system_status`, `pc_processes`, `pc_services`, `pc_logs` só existiam para Windows (powershell/tasklist/net start). | Versões Linux (psutil, `ps`, `systemctl`, `journalctl`). Windows inalterado. |
| 4 | `core/tools/pc_tools.py` | **Segurança:** `pc_logs` colocava o parâmetro `log` direto num comando PowerShell (`"Application; <comando>"` executaria). | Nome validado (`[A-Za-z0-9 ._-]`), `count` convertido para inteiro e limitado a 500. |
| 5 | `core/tools/pc_control.py` | Desligar/reiniciar/bloquear/suspender só tinham versão PowerShell. | Backends Linux: `systemctl poweroff/reboot/suspend`, `loginctl lock-session`, `shutdown +N`. As travas (confirmação obrigatória e `_real_execution=False` por padrão) continuam iguais. |
| 6 | `core/tools/pc_control.py` | No Windows, `force=True` gerava `Stop-Computer -Force/f` (PowerShell inválido) e `-Force` era aplicado mesmo sem pedir. | `-Force` só quando `force=True`; `shutdown /s [/f] /t N` correto. |
| 7 | `aris_agent/tools/pc/apps.py` | `pc_open_app` exigia `os.startfile` (só Windows): no Linux nenhum app abria. | Linux/macOS: executa o binário cadastrado ou usa `xdg-open`/`open` para URLs e documentos, sem shell. |
| 8 | `core/security/shell.py` | `safe_resolve("..\\..\\Windows")` não era barrado no Linux (barra invertida tratada como letra do nome). | `\` vira `/` fora do Windows antes da checagem. |
| 9 | `tests/conftest.py` (novo) | `test_distributed.py` deixava a ARIS em modo EDGE e `test_executor_confirmation_required` falhava dependendo da ordem. | Fixture que zera o ModeManager entre testes. |
| 10 | `tests/test_new_phases.py` | Mock de PCControl só cobria `_run_ps`. | Mock também de `_run_argv`. |

## Arquivos de projeto
- `main.py` (novo): README e `pyproject.toml` já mandavam rodar `python main.py`, mas o arquivo não existia.
- `aris.bat`: caminho fixo `C:\Users\Administrator\...` trocado por `%~dp0`.
- `.env.example`: `ARIS_MEMORY_ROOT` fixo da máquina antiga virou comentário com exemplos Windows/Linux.
- `README.md`: seção "Como Executar" (inclui `./aris.sh`).
- `requirements-optional.txt` (novo): `discord.py`, `websockets`, `numpy`, `opencv-python`, `mediapipe`, `vosk` eram importados e não estavam declarados em lugar nenhum; inclui os pacotes `apt` que o código chama no Linux.

## Testes
`tests/test_linux_compat.py` (novo, 29 testes): cada um falha no código antigo e passa no novo.
Suíte completa: 2091 passam / 5 falham — as 5 restantes não são causadas por estas mudanças:
- `test_https_passes`, `test_http_passes`: precisam resolver `example.com` (sem rede no ambiente de teste).
- `test_espeak_binary_present_on_this_host`: precisa de `espeak-ng` instalado no sistema.
- `test_write_em_area_protegida_negado[pasta_users]`: assume que `$HOME` está em `/home/usuario`.
- `test_conversation_returns_none`: ver "Decisão pendente" abaixo.

## Decisão pendente (não alterei)
`try_nlu_fast_path("oi")` agora responde uma saudação fixa localmente (`"Boa noite! Tudo bem?"`)
em vez de devolver `None` para o LLM responder. O teste ainda espera `None`. Se a intenção é a
ARIS responder conversa casual com a personalidade/LLM, é regressão; se a resposta local é
proposital, basta atualizar o teste.

## Não coberto
- Interface gráfica (`aris_eyes`, HUD, `gesture_trainer`): precisa de tela/câmera, não rodei.
- Voz (microfone/TTS) e ESP32: dependem de hardware.
- Chamadas reais a Groq/Gemini/Ollama.
