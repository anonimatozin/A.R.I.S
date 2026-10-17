# `aris_agent.tools.web` — ferramentas de web (Parte 3)

11 ferramentas de pesquisa, leitura, download e navegação controlada. Toda saída é
conteúdo **não confiável**: passa por `wrap_untrusted` (bloco
`<conteudo_nao_confiavel>`) e truncamento (`max_tool_chars`).

## Ferramentas

| Ferramenta | Risco | O que faz |
| --- | --- | --- |
| `web_search` | READ | Busca na web (backends em cascata) e devolve título/URL/trecho |
| `web_fetch` | READ | Baixa uma URL e devolve o texto principal da página |
| `web_extract_links` | READ | Lista links relevantes (mesmo domínio primeiro) |
| `web_download` | WRITE | Baixa um arquivo para `workspace/downloads` (nunca executa) |
| `browser_open` | EXEC | Abre a URL no Chromium com perfil dedicado |
| `browser_snapshot` | READ | Texto visível + elementos interativos numerados (`[1] botão "Entrar"`) |
| `browser_click` | EXEC | Clica no elemento pelo número do último snapshot |
| `browser_type` | EXEC | Preenche o campo pelo número do último snapshot |
| `browser_press` | EXEC | Pressiona uma tecla (Enter, Tab...), opcionalmente em um elemento |
| `browser_screenshot` | READ | Salva um PNG em `workspace/browser` e devolve o caminho |
| `browser_close` | EXEC | Fecha o navegador e libera a memória |

Regras do laço do agente: `browser_snapshot` **antes** de qualquer `browser_click/type/press`;
se a página mudou, o erro é exatamente `snapshot desatualizado, chame browser_snapshot`.

## Instalação (já feita no ambiente deste projeto)

```bash
pip install -r requirements/parte3.txt      # trafilatura, ddgs, bs4, requests, playwright
playwright install chromium                 # baixa o Chromium (~130-160 MB)
```

Playwright e Chromium só são necessários para `browser_*`; busca e leitura
(`web_search`, `web_fetch`, `web_extract_links`, `web_download`) funcionam sem eles.
O import do Playwright é preguiçoso: sem ele, as ferramentas de navegador falham com
instrução de instalação e o resto segue funcionando.

## Chaves de ambiente (opcionais)

| Variável | Backend | Observação |
| --- | --- | --- |
| (nenhuma) | `ddgs` | DuckDuckGo sem chave — backend padrão |
| `BRAVE_API_KEY` | `brave` | Brave Search API |
| `TAVILY_API_KEY` | `tavily` | Tavily |
| `SERPER_API_KEY` | `serper` | Serper.dev (Google) |

Ordem dos backends: `search_backends` na seção `web` do `aris_agent.json`
(padrão `ddgs,brave,tavily,serper`). Backends sem chave são pulados; se todos
falharem, `web_search` devolve `ok=False` com o motivo (sem segredos).

## Seção `web` da configuração

```jsonc
{
  "web": {
    "timeout_s": 20,                 // leitura por requisição (mín 1)
    "connect_timeout_s": 10,         // conexão por requisição (mín 1)
    "max_download_bytes": 5242880,   // 5 MB por resposta (mín 1024)
    "max_redirects": 5,              // cada salto é revalidado anti-SSRF (máx 20)
    "max_chars": 6000,               // texto devolvido (padrão e teto; mín 200)
    "search_backends": "ddgs,brave,tavily,serper",
    "search_max_results": 5,         // teto 10
    "browser_idle_s": 300,           // fecha o navegador após 5 min ocioso (mín 10)
    "browser_headless": true,
    "user_agent": "ArisAgent/0.1 (ferramentas de web)",
    "test_allow_local": false        // SOMENTE TESTES — ver abaixo
  }
}
```

## Segurança

- **Anti-SSRF**: só `http`/`https`; sem usuário/senha na URL; bloqueia `localhost`,
  `127.0.0.0/8`, `169.254.0.0/16` (inclusive metadados de nuvem), redes privadas,
  IPv6 local/multicast/reservado — inclusive quando o nome resolve para esses
  intervalos (DNS) e **inclusive após redirecionamento**. Falha de DNS também bloqueia.
- **`test_allow_local`**: chave de configuração **só para testes** (desligada por
  padrão); libera **apenas loopback** para os testes usarem um servidor HTTP local.
  Nunca ligue em produção: 169.254/16 e redes privadas continuam bloqueadas.
- **Limites rígidos**: timeout 20 s, 5 MB por resposta, 5 redirecionamentos,
  6000 caracteres; downloads vão para `workspace/downloads` com nome sanitizado.
- **Navegador**: perfil isolado em `data_dir/browser_profile` (nunca o perfil real
  do usuário), headless por padrão, fecha por ociosidade, e cada requisição da
  página passa pela mesma validação anti-SSRF.
- Erros passam por `redact_secrets`; chaves de API nunca entram em log nem em saída.

## Testes

```bash
python -m pytest tests/aris_agent/parte3 -q -p no:cacheprovider --tb=short
python -m ruff check aris_agent/tools/web tests/aris_agent/parte3
# com internet/chave (opcional):
ARIS_TEST_LIVE=1 python -m pytest tests/aris_agent/parte3 -q -p no:cacheprovider -m live
```
