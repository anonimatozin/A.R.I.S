# Mini Deck — firmware do A.R.I.S. (ESP32)

Firmware do **Mini Deck**: 2 LEDs RGB + 1 botão, com **portal de
configuração Wi-Fi** (não precisa editar código para configurar a rede).

Arquivos:

| Arquivo | O que é |
|---|---|
| `esp32_aris.ino` | LEDs, efeitos, botão, WebSocket e loop principal |
| `wifi_manager.h` | Wi-Fi: portal captive, NVS, beacon UDP e a máquina de estados |
| `platformio.ini` | Configuração do PlatformIO (board `esp32dev`) |
| `credentials.h` | **Não versionado.** Rede/PC legados (fallback + migração) |
| `credentials.h.example` | Modelo do `credentials.h` |

> O firmware compila com **Arduino-ESP32 3.x** (API nova `ledcAttach`).
> Por isso o `platformio.ini` usa a plataforma pioarduino — na primeira
> build o PlatformIO baixa a plataforma e a toolchain automaticamente.

## Instalar e gravar (VS Code + PlatformIO)

1. Plugar o deck no PC com um **cabo de dados** (não é cabo só de carga).
2. Abrir a pasta `esp32_aris` no VS Code (File → Open Folder).
3. Instalar a extensão **PlatformIO IDE** se ainda não estiver instalada.
4. Na barra lateral do PlatformIO, clicar em **✓ Build** (seta da
   esquerda → Projeto → `esp32dev`). Na primeira vez baixa ~centenas de
   MB de toolchain — é normal.
5. **→ Upload** para gravar (selecione a porta serial se pedir;
   normalmente `/dev/ttyUSB0` ou `/dev/ttyACM0` no Linux).
6. (Opcional) **Serial Monitor** a 115200 baud para acompanhar.

Alternativa (Arduino IDE 3.x): instalar a placa "esp32" (ESP32 Dev
Module) e as bibliotecas **WebSockets** (Links2004) e **ArduinoJson**,
depois abrir `esp32_aris.ino`.

> Permissão de porta no Linux: seu usuário precisa estar no grupo
> `dialout` (`sudo usermod -aG dialout $USER` e relogar).

## Como configurar o Wi-Fi (portal)

1. **Ligar o deck.** Sem rede salva, os LEDs ficam **azuis** = portal.
   O deck cria o ponto de acesso **`ARIS-Deck-XXXX`** (XXXX = final do
   MAC).
2. Conectar o computador/celular nessa rede (a senha do Wi-Fi do deck é
   aberta; o que protege é o portal só existir quando necessário).
3. Abrir `http://192.168.4.1` (normalmente o navegador abre sozinho —
   captive portal).
4. Informar **SSID** e **senha** → **Salvar e conectar**.
5. A página mostra o estado em tempo real (Conectando… / Conectado! IP …
   / Falha). O deck tenta 3 vezes; se falhar, o portal volta com o erro
   **e as credenciais ficam guardadas** (basta tentar de novo).

Credenciais ficam **só no NVS do deck** — nunca aparecem em log, no
Serial nem nas mensagens WebSocket.

## LEDs (significado)

| LED | Significado |
|---|---|
| Azul fraco | Inicializando / **portal de configuração** |
| Ciano pulsante | Conectando ao Wi-Fi |
| Azul escuro | Conectado, ocioso (idle) |
| Vermelho | Erro de Wi-Fi ou WebSocket caído |

## Botão

- Ações curtas (1×, 2×, 3×, 4×, long-press de 1 s) continuam indo para a
  ARIS no PC (voz, parar fala, turbo… — configuráveis via env `ESP32_BTN_*`).
- **Segurar 10 s** = limpar o Wi-Fi (apaga credenciais) e abrir o portal
  de novo. É o **único** jeito de apagar a senha.

## Comunicação com o PC

- **WebSocket** (o deck é cliente): o PC roda um servidor na porta
  **8766/tcp**. O IP do PC é descoberto por **beacon UDP broadcast** na
  porta **8767** que o PC envia a cada 3 s (protocolo novo do lado do
  PC; o `credentials.h` `WS_HOST` é o fallback).
- Mensagens novas (aditivas; tudo o mais permanece igual):

  ```json
  {"tipo": "wifi_status", "estado": "connecting", "ip": "192.168.0.115",
   "rssi": -58, "tentativa": 1}
  ```

  `estado` ∈ `portal | connecting | connected | failed` (e `erro` quando
  houver). Com isso a **ARIS no PC reage no rosto**: configurando
  (surprised) → conectando (thinking) → conectado (happy) → erro (error).

## Recuperação e comportamento de rede

- Falha de senha/rede: tenta 3×, reabre o portal. **Nunca apaga** as
  credenciais.
- Queda de rede depois de conectado: o deck tenta de novo sozinho (sem
  abrir portal); se a rede não voltar, dorme e retenta a cada 30 s.
- Portal aberto sem cliente por 10 min: o AP fecha sozinho (segurança);
  reabre no próximo boot ou com o botão 10 s.
- O PC pode estar no AP do deck durante a configuração (beacon+WS
  funcionam no link do AP) — aí o rosto reage em tempo real também.

## Limitações

- Configurando **pelo celular** (PC fora do AP do deck), os estados
  "configurando/conectando" não chegam ao rosto (não há caminho de
  rede); a página mostra o status e o "conectado" chega quando o deck
  entrar na rede da casa.
- Liberar portas no firewall, se houver: 8766/tcp e 8767/udp.
