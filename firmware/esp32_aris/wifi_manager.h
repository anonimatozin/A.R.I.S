/*
 * Wi-Fi do Mini Deck — portal de configuração + conexão + descoberta do PC.
 *
 * Estados (WifiModo):
 *   PORTAL      -> ponto de acesso próprio "ARIS-Deck-XXXX" + página de
 *                  configuração em http://192.168.4.1 (captive portal)
 *   CONECTANDO  -> tentando a rede salva (o portal continua vivo durante a
 *                  tentativa — nada fica bloqueado)
 *   CONECTADO   -> estação na rede; WebSocket para o PC
 *   DORMINDO    -> sem portal: retenta as credenciais salvas a cada 30 s
 *                  (caso "a rede caiu"; o portal só reabre no boot ou no
 *                  reset de fábrica de 10 s no botão)
 *
 * Credenciais: NVS (Preferences, namespace "deck"); NUNCA em log, Serial
 * ou mensagens WebSocket. Falha de conexão NÃO apaga credenciais.
 * Descoberta do PC: beacon UDP que o PC broadcast na porta 8767 — o deck
 * usa o IP de origem como alvo do WebSocket.
 */

#pragma once

#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <WiFiUdp.h>
#include <ArduinoJson.h>

#include "credentials.h"   // WIFI_SSID/WIFI_PASS/WS_HOST (legado, só fallback)

// ── Constantes ─────────────────────────────────────────────
#define WIFI_TENTATIVA_TIMEOUT_MS 20000UL                 // cada tentativa
#define WIFI_MAX_TENTATIVAS       3                       // antes do portal
#define WIFI_PORTAL_TIMEOUT_MS    (10UL * 60UL * 1000UL)  // AP fecha sem cliente
#define WIFI_PORTAL_JANELA_MS     60000UL                 // portal pós-conexão
#define WIFI_RETRY_LENTO_MS       30000UL                 // retenta sem portal
#define WIFI_RESET_PORTAL_MS      10000UL                 // botão 10 s = limpar
#define BEACON_PORT_UDP           8767

// Variável global do .ino usada aqui (declaração extern + definição no .ino).
extern bool connected;   // estado do WebSocket

// Implementadas no .ino (LEDs, efeitos e WebSocket ficam lá).
void setBothLEDs(uint8_t r, uint8_t g, uint8_t b, uint8_t brightness);
void startEffect(const char* effectName);
void iniciarWebSocket(const String& ip);
void enviarWifiStatus(const char* estado);

// Definida mais abaixo; usada pelas rotas do portal.
inline void iniciarTentativa(const String& ssid, const String& pass);

// ── Estado ─────────────────────────────────────────────────
enum WifiModo { PORTAL, CONECTANDO, CONECTADO, DORMINDO };

Preferences wifiPrefs;
WebServer portalServer(80);
DNSServer dnsServer;
WiFiUDP udpBeacon;

WifiModo wifiModo = PORTAL;
bool portalAtivo = false;
bool portalComErro = false;
bool tentativaSemPortal = false;   // true = falha vai dormir, não abre portal
String tentarSsid, tentarPass;
int tentativas = 0;
String ultimoErro;
String pcIp;                       // IP do PC (beacon UDP ou credentials.h)
unsigned long tentativaInicio = 0;
unsigned long portalSemClienteDesde = 0;
unsigned long portalJanelaAte = 0;
unsigned long dormiuEm = 0;

// ── Página do portal (PROGMEM) ─────────────────────────────
const char PAGINA_PORTAL[] PROGMEM = R"rawliteral(<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A.R.I.S. — Mini Deck</title>
<style>
:root{color-scheme:dark}
body{font-family:system-ui,sans-serif;background:#0b0f1a;color:#dbe4ff;margin:0;display:flex;justify-content:center}
.card{background:#141b2d;border:1px solid #26314d;border-radius:14px;margin:24px;padding:24px;max-width:420px;width:calc(100% - 48px)}
h1{font-size:20px;margin:0 0 4px}
.sub{color:#8aa0d0;font-size:13px;margin:0 0 18px}
label{display:block;font-size:13px;color:#8aa0d0;margin:12px 0 4px}
input{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #33405f;background:#0d1322;color:#dbe4ff;font-size:15px}
button{margin-top:18px;width:100%;padding:12px;border:0;border-radius:8px;background:#2f6df6;color:#fff;font-size:15px;font-weight:600;cursor:pointer}
#status{margin-top:16px;padding:10px;border-radius:8px;background:#0d1322;font-size:14px;min-height:20px}
.ok{color:#5ee08a}.err{color:#ff6b6b}.wait{color:#ffd166}
.note{color:#66739a;font-size:12px;margin-top:14px}
</style></head><body><div class="card">
<h1>A.R.I.S. — Mini Deck</h1>
<p class="sub">Conecte o deck à sua rede Wi-Fi</p>
<form method="POST" action="/save">
<label for="ssid">Nome da rede (SSID)</label>
<input name="ssid" id="ssid" autocomplete="off" required>
<label for="pass">Senha</label>
<input name="pass" id="pass" type="password" autocomplete="off" placeholder="(deixe vazio para manter a atual)">
<button type="submit">Salvar e conectar</button>
</form>
<div id="status">Estado: —</div>
<p class="note">A senha fica guardada só no deck e nunca é exibida.
Segure o botão por 10 s para limpar o Wi-Fi e reabrir este portal.</p>
</div>
<script>
var el=document.getElementById('status');
var campo=document.getElementById('ssid');
function poke(){
fetch('/status').then(function(r){return r.json()}).then(function(s){
  var mapa={
    portal:['Portal aberto — informe a rede','wait'],
    connecting:['Conectando… tentativa '+s.tentativa,'wait'],
    connected:['Conectado! IP '+s.ip,'ok'],
    failed:['Falha: '+(s.erro||'tente novamente'),'err']
  };
  var m=mapa[s.estado]||[s.estado,'wait'];
  el.textContent='Estado: '+m[0]; el.className=m[1];
  if(s.ssid && !campo.value) campo.value=s.ssid;
}).catch(function(){})}
poke(); setInterval(poke,2000);
</script>
</body></html>)rawliteral";

// ── Utilidades ─────────────────────────────────────────────

inline const char* wifiNomeEstado() {
  switch (wifiModo) {
    case PORTAL:     return portalComErro ? "failed" : "portal";
    case CONECTANDO: return "connecting";
    case CONECTADO:  return "connected";
    case DORMINDO:   return "failed";
  }
  return "portal";
}

inline String wifiApSsid() {
  char buf[24];
  snprintf(buf, sizeof(buf), "ARIS-Deck-%04X",
           (uint16_t)(ESP.getEfuseMac() >> 32));
  return String(buf);
}

// ── Portal (captive) ───────────────────────────────────────

inline void wifiRegistrarRotas() {
  portalServer.on("/", HTTP_GET, []() {
    portalServer.send_P(200, PSTR("text/html; charset=utf-8"), PAGINA_PORTAL);
  });

  portalServer.on("/save", HTTP_POST, []() {
    String ssid = portalServer.arg("ssid");
    String pass = portalServer.arg("pass");
    ssid.trim();
    if (ssid.length() == 0) {
      portalServer.send(400, "text/html; charset=utf-8",
                        "<h1>Informe o nome da rede</h1>");
      return;
    }
    if (pass.length() == 0) pass = tentarPass;   // vazio = mantém a salva
    wifiPrefs.putString("ssid", ssid);
    wifiPrefs.putString("pass", pass);           // NVS; nunca em log/Serial
    portalServer.send(200, "text/html; charset=utf-8",
                      "<h1>Salvo. Conectando...</h1>");
    tentativaSemPortal = false;                  // erro aqui abre o portal
    iniciarTentativa(ssid, pass);
  });

  portalServer.on("/status", HTTP_GET, []() {
    StaticJsonDocument<256> doc;
    doc["estado"] = wifiNomeEstado();
    doc["ssid"] = (wifiModo == PORTAL) ? tentarSsid : WiFi.SSID();
    doc["ip"] = WiFi.localIP().toString();
    doc["tentativa"] = tentativas;
    if (ultimoErro.length() > 0) doc["erro"] = ultimoErro;
    // NUNCA inclui a senha
    String out;
    serializeJson(doc, out);
    portalServer.send(200, "application/json", out);
  });

  // Captiva: qualquer host/hospédia vira a página de configuração
  portalServer.onNotFound([]() {
    portalServer.sendHeader("Location",
                            String("http://") + WiFi.softAPIP().toString() + "/",
                            true);
    portalServer.send(302, "text/plain", "");
  });
}

// ── Máquina de estados ─────────────────────────────────────

inline void iniciarTentativa(const String& ssid, const String& pass) {
  tentarSsid = ssid;
  tentarPass = pass;
  tentativas = 0;
  ultimoErro = "";
  wifiModo = CONECTANDO;
  tentativaInicio = millis();
  WiFi.mode(portalAtivo ? WIFI_AP_STA : WIFI_STA);
  WiFi.begin(tentarSsid.c_str(), tentarPass.c_str());
  setBothLEDs(0, 70, 130, 70);
  startEffect("pulse");                 // ciano pulsando = conectando
  Serial.printf("[WIFI] Conectando a \"%s\" (1/%d)\n",
                tentarSsid.c_str(), WIFI_MAX_TENTATIVAS);
  enviarWifiStatus("connecting");
}

inline void abrirPortal(bool comErro) {
  wifiModo = PORTAL;
  portalAtivo = true;
  portalComErro = comErro;
  WiFi.mode(WIFI_AP);
  WiFi.softAP(wifiApSsid().c_str());    // portal aberto, mas temporário
  dnsServer.start(53, "*", WiFi.softAPIP());
  wifiRegistrarRotas();
  portalSemClienteDesde = millis();
  Serial.print("[WIFI] Portal aberto: ");
  Serial.println(wifiApSsid());
  if (comErro) {
    setBothLEDs(255, 0, 0, 40);         // vermelho fraco = erro
  } else {
    setBothLEDs(0, 0, 255, 50);         // azul = configurando
  }
  enviarWifiStatus(comErro ? "failed" : "portal");
}

inline void fecharPortal() {
  if (!portalAtivo) return;
  portalAtivo = false;
  portalServer.stop();
  dnsServer.stop();
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  Serial.println("[WIFI] Portal fechado");
}

// Beacon UDP do PC: ele anuncia o próprio IP; o deck passa a usá-lo.
inline void wifiBeaconLoop() {
  if (udpBeacon.parsePacket() <= 0) return;
  String msg = udpBeacon.readString();
  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, msg)) return;
  const char* beacon = doc["beacon"] | "";
  if (strcmp(beacon, "aris") != 0) return;
  String ip = udpBeacon.remoteIP().toString();
  if (ip == pcIp && connected) return;  // já é o alvo e o WS está de pé
  pcIp = ip;
  wifiPrefs.putString("pc", pcIp);
  Serial.print("[WIFI] PC encontrado via beacon: ");
  Serial.println(pcIp);
  iniciarWebSocket(pcIp);
}

// ── API chamada pelo .ino ──────────────────────────────────

inline void wifiSetup() {
  WiFi.persistent(false);               // credenciais só no NVS nosso
  wifiPrefs.begin("deck", false);

  String ssid = wifiPrefs.getString("ssid", "");
  String pass = wifiPrefs.getString("pass", "");
  pcIp = wifiPrefs.getString("pc", "");
  if (pcIp.length() == 0 && strlen(WS_HOST) > 0) pcIp = WS_HOST;  // legado

  // Migração: credentials.h antigo vira NVS no primeiro boot
  if (ssid.length() == 0 && strcmp(WIFI_SSID, "SUA_REDE_WIFI") != 0) {
    ssid = WIFI_SSID;
    pass = WIFI_PASS;
    wifiPrefs.putString("ssid", ssid);
    wifiPrefs.putString("pass", pass);
    Serial.println("[WIFI] Credenciais migradas do credentials.h");
  }

  udpBeacon.begin(BEACON_PORT_UDP);     // escuta em STA e em AP

  if (ssid.length() > 0) {
    tentativaSemPortal = false;         // falha no boot abre o portal
    iniciarTentativa(ssid, pass);
  } else {
    abrirPortal(false);
  }
}

inline void wifiLoop() {
  switch (wifiModo) {
    case CONECTANDO:
      if (portalAtivo) {                // portal segue respondendo durante a tentativa
        dnsServer.processNextRequest();
        portalServer.handleClient();
      }
      if (WiFi.status() == WL_CONNECTED) {
        wifiModo = CONECTADO;
        ultimoErro = "";
        Serial.print("[WIFI] Conectado: ");
        Serial.println(WiFi.localIP());
        if (portalAtivo) {
          // janela para a página mostrar "Conectado" antes de fechar o AP
          portalJanelaAte = millis() + WIFI_PORTAL_JANELA_MS;
        } else {
          WiFi.mode(WIFI_STA);
        }
        setBothLEDs(0, 50, 100, 80);    // idle azul escuro (padrão original)
        iniciarWebSocket(pcIp);
        enviarWifiStatus("connected");
        break;
      }
      if (millis() - tentativaInicio >= WIFI_TENTATIVA_TIMEOUT_MS) {
        if (++tentativas < WIFI_MAX_TENTATIVAS) {
          WiFi.disconnect();
          WiFi.begin(tentarSsid.c_str(), tentarPass.c_str());
          tentativaInicio = millis();
          Serial.printf("[WIFI] Tentativa %d/%d\n",
                        tentativas + 1, WIFI_MAX_TENTATIVAS);
          enviarWifiStatus("connecting");
        } else if (tentativaSemPortal) {
          wifiModo = DORMINDO;
          dormiuEm = millis();
          WiFi.mode(WIFI_OFF);
          Serial.println("[WIFI] Sem resposta; dormindo antes de retentar");
        } else {
          ultimoErro = "Falha ao conectar (confira o nome e a senha)";
          Serial.println("[WIFI] Falhou; credenciais mantidas, portal reaberto");
          abrirPortal(true);
        }
      }
      break;

    case CONECTADO:
      wifiBeaconLoop();
      if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WIFI] Rede caiu; retentando (credenciais preservadas)");
        tentativaSemPortal = true;      // queda de rede não abre portal
        iniciarTentativa(tentarSsid, tentarPass);
        break;
      }
      if (portalAtivo && (long)(millis() - portalJanelaAte) >= 0) {
        fecharPortal();
      }
      break;

    case DORMINDO:
      if (tentarSsid.length() == 0) break;   // nada salvo: só boot/botão reabrem
      if (millis() - dormiuEm >= WIFI_RETRY_LENTO_MS) {
        WiFi.mode(WIFI_STA);
        tentativaSemPortal = true;
        iniciarTentativa(tentarSsid, tentarPass);
      }
      break;

    case PORTAL: {
      dnsServer.processNextRequest();
      portalServer.handleClient();
      wifiBeaconLoop();                 // PC no AP do deck já é alcançável
      if (WiFi.softAPgetStationNum() == 0) {
        if (millis() - portalSemClienteDesde >= WIFI_PORTAL_TIMEOUT_MS) {
          if (tentarSsid.length() > 0) {
            Serial.println("[WIFI] Portal sem cliente; dormindo e retentando as credenciais salvas");
            fecharPortal();
            tentativaSemPortal = true;
            iniciarTentativa(tentarSsid, tentarPass);
          } else {
            Serial.println("[WIFI] Portal sem cliente; AP fechado (boot ou botão 10 s reabre)");
            fecharPortal();
            wifiModo = DORMINDO;
            dormiuEm = millis();
          }
        }
      } else {
        portalSemClienteDesde = millis();
      }
      break;
    }
  }
}

// Reset de fábrica do Wi-Fi: botão segurado 10 s (único jeito de apagar).
inline void wifiChecaReset(bool segurando, unsigned long desde) {
  if (!segurando || millis() - desde < WIFI_RESET_PORTAL_MS) return;
  Serial.println("[WIFI] Botão 10 s: limpando Wi-Fi e reiniciando");
  setBothLEDs(255, 0, 0, 120);
  delay(150);
  setBothLEDs(0, 0, 0, 0);
  delay(150);
  wifiPrefs.remove("ssid");
  wifiPrefs.remove("pass");
  wifiPrefs.remove("pc");
  delay(300);
  ESP.restart();
}
