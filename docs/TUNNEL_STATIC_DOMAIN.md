# Domínio estático pro túnel do dashboard — passo manual do dono

Situação atual: o dashboard (`192.168.0.106:8766`) é exposto por um
**quick Tunnel sem conta** (`cloudflared tunnel --url ...`, ver
`iniciar_site_publico.bat`). Cada reinício gera uma URL nova
(`*.trycloudflare.com`). O watcher (`gateway/tunnel_watcher.py`) cobre
isso avisando no Discord a cada troca — mas o ideal é um endereço fixo.

> Nada abaixo foi executado: trocar o túnel exige login na conta do dono
> (ngrok ou Cloudflare). Quando confirmar qual prefere, eu aplico.

## Opção A (preferencial se já usa ngrok): domínio estático grátis ngrok

1. Entrar em https://dashboard.ngrok.com/ → **Domains** → **New Domain**
   (plano gratuito dá 1 domínio estático, ex. `aris-painel.ngrok-free.app`).
2. Instalar o authtoken na máquina (UMA vez, no terminal):
   `ngrok config add-authtoken SEU_TOKEN`
3. Trocar o comando do túnel para fixar o domínio:
   `ngrok http --domain=aris-painel.ngrok-free.app 192.168.0.106:8766`
   (e apontar `iniciar_site_publico.bat` / watcher pra esse comando).
4. Me avisar o domínio reivindicado pra eu travar no `tunnel_config.py`.

## Opção B (recomendada se ficar no cloudflared): Named Tunnel

1. `cloudflared tunnel login` (abre o navegador, autoriza a conta Cloudflare).
2. `cloudflared tunnel create aris-painel` (gera ID + credencial).
3. Criar CNAME `painel.SEU-DOMINIO` → `<TUNNEL-ID>.cfargotunnel.com` no DNS.
4. Rodar `cloudflared tunnel run aris-painel` com config apontando pra
   `http://192.168.0.106:8766`.
5. Me passar o hostname pra eu atualizar o watcher (vira URL fixa; o
   aviso no Discord continua como rede de segurança).

## Regras que valem pras duas opções

- O túnel encaminha **SÓ a porta 8766** (dashboard). A porta **8780**
  (scheduler) nunca entra no túnel — é LAN/local por decisão explícita.
- O watcher continua rodando de qualquer forma (60s): se a URL mudar por
  qualquer motivo, o Discord é avisado.
