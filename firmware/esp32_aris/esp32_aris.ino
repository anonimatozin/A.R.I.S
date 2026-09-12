/*
 * A.R.I.S. ESP32 Firmware
 * 
 * Comunicação WebSocket com o PC.
 * Controla 2 LEDs RGB + 1 botão com debounce.
 * 
 * Hardware:
 *   LED Esquerdo: R=13, G=12, B=14
 *   LED Direito:  R=27, G=26, B=33
 *   Botão:        GPIO 32
 * 
 * Protocolo JSON:
 *   PC → ESP32: {"tipo":"led","target":"left","r":255,"g":0,"b":0,"brightness":100}
 *   ESP32 → PC: {"tipo":"button","action":"single_click"}
 */

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>

// ── Configuração de rede ───────────────────────────────────
// Credenciais não são versionadas: copie `credentials.h.example`
// para `credentials.h` e preencha com seus dados (ver .gitignore).
#include "credentials.h"
const int WS_PORT = 8766;

// ── Pinos GPIO ─────────────────────────────────────────────
// LED Esquerdo
#define LED_LEFT_R  13
#define LED_LEFT_G  12
#define LED_LEFT_B  14

// LED Direito
#define LED_RIGHT_R 27
#define LED_RIGHT_G 26
#define LED_RIGHT_B 33

// Botão
#define BUTTON_PIN  32

// ── Constantes ─────────────────────────────────────────────
#define DEBOUNCE_MS       50
#define MULTI_CLICK_MS    300
#define LONG_PRESS_MS     1000
#define HEARTBEAT_MS      5000
#define RECONNECT_MS      5000
#define PWM_FREQ          5000
#define PWM_RESOLUTION    8

// ── Variáveis globais ──────────────────────────────────────
WebSocketsClient webSocket;

// Estado dos LEDs
struct LEDState {
  uint8_t r, g, b, brightness;
};
LEDState leftLED = {0, 0, 0, 80};
LEDState rightLED = {0, 0, 0, 80};

// Botão
enum ButtonAction {
  NONE,
  SINGLE_CLICK,
  DOUBLE_CLICK,
  TRIPLE_CLICK,
  QUAD_CLICK,
  LONG_PRESS
};

struct ButtonState {
  bool pressed;
  bool lastState;
  unsigned long pressStart;
  unsigned long lastClick;
  int clickCount;
  bool longPressTriggered;
};
ButtonState button = {false, HIGH, 0, 0, 0, false};

// Heartbeat
unsigned long lastHeartbeat = 0;
unsigned long lastServerHeartbeat = 0;

// Reconexão
unsigned long lastReconnect = 0;
bool connected = false;

// ── Funções de LED ─────────────────────────────────────────

void setLED(int pinR, int pinG, int pinB, uint8_t r, uint8_t g, uint8_t b, uint8_t brightness) {
  float factor = brightness / 255.0;
  ledcWrite(pinR, (uint8_t)(r * factor));
  ledcWrite(pinG, (uint8_t)(g * factor));
  ledcWrite(pinB, (uint8_t)(b * factor));
}

void setLeftLED(uint8_t r, uint8_t g, uint8_t b, uint8_t brightness) {
  leftLED = {r, g, b, brightness};
  setLED(LED_LEFT_R, LED_LEFT_G, LED_LEFT_B, r, g, b, brightness);
}

void setRightLED(uint8_t r, uint8_t g, uint8_t b, uint8_t brightness) {
  rightLED = {r, g, b, brightness};
  setLED(LED_RIGHT_R, LED_RIGHT_G, LED_RIGHT_B, r, g, b, brightness);
}

void setBothLEDs(uint8_t r, uint8_t g, uint8_t b, uint8_t brightness) {
  setLeftLED(r, g, b, brightness);
  setRightLED(r, g, b, brightness);
}

void turnOffLEDs() {
  setBothLEDs(0, 0, 0, 0);
}

// ── Efeitos ────────────────────────────────────────────────

enum Effect { NONE_EFFECT, BLINK, PULSE, FLASH };
Effect currentEffect = NONE_EFFECT;
unsigned long effectStart = 0;
bool effectState = false;

void startEffect(const char* effectName) {
  effectStart = millis();
  effectState = false;
  
  if (strcmp(effectName, "blink") == 0) {
    currentEffect = BLINK;
  } else if (strcmp(effectName, "pulse") == 0) {
    currentEffect = PULSE;
  } else if (strcmp(effectName, "flash") == 0) {
    currentEffect = FLASH;
    setBothLEDs(255, 255, 255, 100);
  } else {
    currentEffect = NONE_EFFECT;
  }
}

void updateEffect() {
  if (currentEffect == NONE_EFFECT) return;
  
  unsigned long elapsed = millis() - effectStart;
  
  switch (currentEffect) {
    case BLINK:
      if (elapsed % 500 < 250) {
        if (!effectState) {
          setBothLEDs(leftLED.r, leftLED.g, leftLED.b, leftLED.brightness);
          effectState = true;
        }
      } else {
        if (effectState) {
          turnOffLEDs();
          effectState = false;
        }
      }
      break;
      
    case PULSE: {
      float phase = (elapsed % 2000) / 2000.0;
      uint8_t brightness = (uint8_t)(128 + 127 * sin(phase * 2 * PI));
      setBothLEDs(leftLED.r, leftLED.g, leftLED.b, brightness);
      break;
    }
      
    case FLASH:
      if (elapsed > 300) {
        currentEffect = NONE_EFFECT;
        setBothLEDs(leftLED.r, leftLED.g, leftLED.b, leftLED.brightness);
      }
      break;
      
    default:
      break;
  }
}

// ── Botão ──────────────────────────────────────────────────

ButtonAction readButton() {
  bool currentState = digitalRead(BUTTON_PIN);
  ButtonAction action = NONE;
  unsigned long now = millis();
  
  // Detectar borda de descida (pressionado)
  if (currentState == LOW && button.lastState == HIGH) {
    button.pressed = true;
    button.pressStart = now;
    button.longPressTriggered = false;
  }
  
  // Detectar borda de subida (solto)
  if (currentState == HIGH && button.lastState == LOW && button.pressed) {
    unsigned long pressDuration = now - button.pressStart;
    button.pressed = false;
    
    if (!button.longPressTriggered && pressDuration < LONG_PRESS_MS) {
      // Contar cliques
      if (now - button.lastClick < MULTI_CLICK_MS) {
        button.clickCount++;
      } else {
        button.clickCount = 1;
      }
      button.lastClick = now;
    }
  }
  
  // Detectar long press
  if (button.pressed && !button.longPressTriggered) {
    if (now - button.pressStart >= LONG_PRESS_MS) {
      button.longPressTriggered = true;
      action = LONG_PRESS;
      button.clickCount = 0;
    }
  }
  
  // Processar cliques após janela de multi-click
  if (!button.pressed && button.clickCount > 0) {
    if (now - button.lastClick >= MULTI_CLICK_MS) {
      switch (button.clickCount) {
        case 1: action = SINGLE_CLICK; break;
        case 2: action = DOUBLE_CLICK; break;
        case 3: action = TRIPLE_CLICK; break;
        case 4: action = QUAD_CLICK; break;
        default: action = QUAD_CLICK; break;  // 5+ = quad
      }
      button.clickCount = 0;
    }
  }
  
  button.lastState = currentState;
  return action;
}

const char* actionToString(ButtonAction action) {
  switch (action) {
    case SINGLE_CLICK: return "single_click";
    case DOUBLE_CLICK: return "double_click";
    case TRIPLE_CLICK: return "triple_click";
    case QUAD_CLICK:   return "quad_click";
    case LONG_PRESS:   return "long_press";
    default:           return "";
  }
}

// ── WebSocket ──────────────────────────────────────────────

void sendJSON(const char* tipo, JsonDocument& doc) {
  if (!connected) return;
  doc["tipo"] = tipo;
  String output;
  serializeJson(doc, output);
  webSocket.sendTXT(output);
}

void sendButton(ButtonAction action) {
  const char* actionStr = actionToString(action);
  if (strlen(actionStr) == 0) return;
  
  StaticJsonDocument<128> doc;
  doc["action"] = actionStr;
  sendJSON("button", doc);
}

void sendHeartbeat() {
  StaticJsonDocument<64> doc;
  sendJSON("heartbeat", doc);
}

void sendConnected() {
  StaticJsonDocument<128> doc;
  doc["ip"] = WiFi.localIP().toString();
  doc["rssi"] = WiFi.RSSI();
  sendJSON("connected", doc);
}

void handleLEDCommand(JsonDocument& doc) {
  const char* target = doc["target"] | "both";
  uint8_t r = doc["r"] | 0;
  uint8_t g = doc["g"] | 0;
  uint8_t b = doc["b"] | 0;
  uint8_t brightness = doc["brightness"] | 80;
  
  if (strcmp(target, "left") == 0) {
    setLeftLED(r, g, b, brightness);
  } else if (strcmp(target, "right") == 0) {
    setRightLED(r, g, b, brightness);
  } else {
    setBothLEDs(r, g, b, brightness);
  }
}

void handleEffectCommand(JsonDocument& doc) {
  const char* target = doc["target"] | "both";
  const char* efeito = doc["efeito"] | "blink";
  
  startEffect(efeito);
}

void handleWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      connected = false;
      Serial.println("[ESP32] Desconectado do servidor");
      break;
      
    case WStype_CONNECTED:
      connected = true;
      lastServerHeartbeat = millis();
      Serial.println("[ESP32] Conectado ao servidor");
      sendConnected();
      break;
      
    case WStype_TEXT: {
      lastServerHeartbeat = millis();
      
      StaticJsonDocument<256> doc;
      DeserializationError error = deserializeJson(doc, payload, length);
      
      if (error) {
        Serial.print("[ESP32] JSON inválido: ");
        Serial.println(error.c_str());
        return;
      }
      
      const char* tipo = doc["tipo"] | "";
      
      if (strcmp(tipo, "led") == 0) {
        handleLEDCommand(doc);
      } else if (strcmp(tipo, "efeito") == 0) {
        handleEffectCommand(doc);
      } else if (strcmp(tipo, "heartbeat") == 0) {
        // Responder ao heartbeat
        sendHeartbeat();
      } else if (strcmp(tipo, "heartbeat_ack") == 0) {
        // Ack do servidor
      }
      break;
    }
    
    default:
      break;
  }
}

// ── Setup ──────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  Serial.println("[ESP32] A.R.I.S. Hardware iniciando...");
  
  // Configurar PWM para LEDs (API nova do ESP32 Arduino Core 3.x)
  ledcAttach(LED_LEFT_R, PWM_FREQ, PWM_RESOLUTION);
  ledcAttach(LED_LEFT_G, PWM_FREQ, PWM_RESOLUTION);
  ledcAttach(LED_LEFT_B, PWM_FREQ, PWM_RESOLUTION);
  ledcAttach(LED_RIGHT_R, PWM_FREQ, PWM_RESOLUTION);
  ledcAttach(LED_RIGHT_G, PWM_FREQ, PWM_RESOLUTION);
  ledcAttach(LED_RIGHT_B, PWM_FREQ, PWM_RESOLUTION);
  
  // Configurar botão
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  
  // LEDs de inicialização
  setBothLEDs(0, 0, 255, 50);  // Azul fraco = iniciando
  
  // Conectar WiFi
  Serial.print("[ESP32] Conectando ao WiFi...");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print("[ESP32] WiFi conectado: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("[ESP32] Falha ao conectar WiFi");
    setBothLEDs(255, 0, 0, 50);  // Vermelho = erro
    return;
  }
  
  // Configurar WebSocket
  webSocket.begin(WS_HOST, WS_PORT, "/");
  webSocket.onEvent(handleWebSocketEvent);
  webSocket.setReconnectInterval(5000);
  
  // Estado idle
  setBothLEDs(0, 50, 100, 80);  // Azul escuro = idle
  
  Serial.println("[ESP32] Pronto para conexão WebSocket");
}

// ── Loop ───────────────────────────────────────────────────

void loop() {
  webSocket.loop();
  
  // Heartbeat
  unsigned long now = millis();
  if (now - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = now;
    if (connected) {
      sendHeartbeat();
    }
  }
  
  // Verificar timeout do servidor
  if (connected && (now - lastServerHeartbeat > 15000)) {
    Serial.println("[ESP32] Timeout do servidor");
    connected = false;
    setBothLEDs(255, 0, 0, 50);  // Vermelho = desconectado
  }
  
  // Reconexão automática
  if (!connected && WiFi.status() == WL_CONNECTED) {
    if (now - lastReconnect >= RECONNECT_MS) {
      lastReconnect = now;
      Serial.println("[ESP32] Tentando reconectar ao servidor...");
      webSocket.begin(WS_HOST, WS_PORT, "/");
    }
  }
  
  // Ler botão
  ButtonAction action = readButton();
  if (action != NONE) {
    Serial.print("[ESP32] Botão: ");
    Serial.println(actionToString(action));
    sendButton(action);
    
    // Flash visual ao pressionar
    if (!effectState) {
      setBothLEDs(255, 255, 255, 50);
      delay(50);
      setBothLEDs(leftLED.r, leftLED.g, leftLED.b, leftLED.brightness);
    }
  }
  
  // Atualizar efeitos
  updateEffect();
}
