# Wake word e voz (STT/TTS)

Como a ARIS decide que você falou com ela, o que acontece depois e o que
dá para configurar. Código: `core/perception/wake_engine.py` +
`core/perception/continuous_voice_sensor.py` (STT) e
`utils/voice_hybrid.py` (TTS).

## O problema de antes

O sensor de voz contínua rodava o STT (faster-whisper/Vosk) em **todo**
trecho de fala e só depois procurava a wake word no texto. Consequências:

- CPU alta o tempo todo, mesmo com a TV ligada ou conversa alheia;
- tudo que era falado perto do microfone era transcrito (privacidade);
- o falso positivo por substring ("Paris" acordava) — corrigido por
  `matches_wake_word` (palavra inteira, sem depender de acento) + fuzzy
  ≤1 edição com a mesma letra inicial ("Ares" acorda — o whisper ouve o
  próprio nome assim —; "varis", "Paris" e "arisco" não).

## Os dois modos (`ARIS_WAKE_ENGINE`)

| Modo | O que faz | Padrão |
|---|---|---|
| `transcript` | O comportamento antigo: VAD → STT → `matches_wake_word`. É o modo de compatibilidade e continua sendo o **padrão**. | ✅ |
| `openwakeword` | Motor dedicado openWakeWord (offline, ONNX) olhando o áudio direto. **Nada é transcrito antes de acordar** — fala alheia/TV nunca chega ao STT. | ❌ |

Ligue com:

```bash
export ARIS_WAKE_ENGINE=openwakeword
export ARIS_WAKE_MODEL=/caminho/para/aris.onnx   # modelo treinado p/ a Áris
export ARIS_WAKE_THRESHOLD=0.5                   # limiar 0..1
```

Sem o `openwakeword` instalado (dependência opcional em
`requirements-optional.txt`), o sistema avisa uma vez e permanece no modo
transcript. **Instalação no Linux + Python 3.12** (o pacote declara
`tflite-runtime`, que não tem wheel para py3.12): `pip install --no-deps
openwakeword && pip install onnxruntime` — o backend ONNX é suficiente
para os modelos `.onnx`. Fluxo com o motor dedicado: acordou no áudio → **bip**
(`assets/sounds/wake.wav`, regenerável com
`python assets/sounds/gerar_bip_wake.py`) → estado `listening` nos olhos →
captura do comando por VAD → **só esse trecho** é transcrito e entregue.
Enquanto a ARIS está falando, o limiar sobe +0.2 (a própria voz não
re-acorda).

## Modelo do openWakeWord

- API confirmada na documentação oficial (v0.6.0): `from openwakeword.model import Model`;
  `Model(wakeword_models=[caminho.onnx])`; `predict(frame)` recebe PCM16
  16 kHz (múltiplos de 80 ms recomendados) e devolve `{nome: score}`.
- Os **modelos pré-treinados são em inglês** ("hey jarvis" etc.) — servem
  só para testar o pipeline end-to-end.
- Para a voz da Áris em português, **treine um modelo próprio** (o projeto
  treina em <1 h com um Colab fornecido por eles): colete ~500 frases
  positivas (com "aris"/"arís" no meio de frases reais) + horas de áudio
  negativo (rádio/podcast em pt-BR), siga
  <https://github.com/dscripka/openWakeWord#training-new-models>, exporte
  o `.onnx` e aponte o `ARIS_WAKE_MODEL` para ele. **Não existem modelos
  pré-treinados em português.**

### Coletando as frases (script pronto)

```bash
python scripts/coletar_wake_word.py               # 30 frases positivas
python scripts/coletar_wake_word.py --rodadas 50  # mais frases
python scripts/coletar_wake_word.py --negativas   # fala SEM a wake word
```

O script mostra a frase na tela e grava pelo microfone (arecord no
Linux, pyaudio como fallback), salvando `.wav` 16 kHz em
`treino_wake/` (pasta local, fora do git). Grave num cômodo silencioso
variando entonação e distância. Falta só você fornecer as horas de áudio
negativo (rádio/podcast em pt-BR) e rodar o Colab do projeto para
treinar e exportar o `.onnx`.

## Eco da própria voz (limitação conhecida)

O microfone escuta o que os caixas de som reproduzem. O openWakeWord tem
VAD embutido (`vad_threshold`) que reduz o problema, e o limiar +0.2
durante o TTS ajuda, mas **não há supressão de eco/cancelamento de eco
implementado** — sugestões: usar fone de ouvido, baixar o volume dos
caixas ou treinar o modelo com a voz do próprio TTS nos negativos. O
barge-in atual (parar o TTS quando você fala) continua valendo como antes.

## STT — o que mudou

- `language="pt"` fixo (nunca detecção de idioma);
- `vad_filter=True`: o próprio faster-whisper corta trechos sem fala
  antes do modelo (menos CPU, menos alucinação);
- `initial_prompt` com o vocabulário da ARIS ("Aris", "Áris", verbetes
  frequentes) — guia o modelo em português;
- `beam_size=1`, `best_of=1`, `temperature=0.0` (leve, determinístico);
- **tempo por comando** no log: `STT: 850ms de áudio em 240ms (wake word)`
  — é o número para comparar antes/depois de qualquer troca de modelo.

### Medindo CPU (aceite "CPU menor no modo dedicado")

1. No modo `transcript`, fale/não fale com a TV ligada: veja no log que
   `STT: ...ms de áudio` aparece para TODO trecho de fala (inclusive sem
   wake word) — cada linha é CPU de inferência gasta à toa.
2. No modo `openwakeword` com o mesmo cenário: nenhuma linha de STT
   aparece antes do bip; o custo por frame do openWakeWord é ~ms em CPU
   (modelo ~3 MB) contra centos de ms por segmento do whisper.
3. Para números de processo, rode 60 s em cada modo com `top -p $(pgrep -f main.py)`.

## TTS (voz falada) — o que mudou

- **Cache em disco** das frases curtas (`~/.cache/aris/tts`, teto de 300
  arquivos, `ARIS_TTS_CACHE=0` desliga): "Pronto!", "Aviso!" e companhia
  tocam instantâneos, sem rede e sem síntese.
- **Streaming por frase**: respostas longas são sintetizadas FRASE A
  FRASE — a primeira sai ~1-2 s antes (antes o texto inteiro era
  sintetizado antes de qualquer som) e o stop responde entre frases.
- Fallback offline já existente e mantido: edge-tts (online) →
  **Piper** → espeak-ng → pyttsx3, com disjuntor automático quando a
  internet cai. (A avaliação pedida sobre Piper: já está implementado como
  primeira opção offline — use `ARIS_TTS_OFFLINE_ENGINE=piper` com um
  modelo pt-BR em `ARIS_PIPER_MODEL`.)

## Testes

- `tests/test_wake_word.py` — palavra inteira + acento (suite original da
  correção, mantida).
- `tests/test_wake_word_fuzzy.py` — fuzzy ≤1 com letra inicial.
- `tests/test_wake_engine.py` — Protocol, TranscriptWakeEngine, factory,
  envs inválidas, garantia de "nunca levanta exceção".
- `tests/test_voice_sensor_wake.py` — integração do motor no sensor com
  um motor FALSO (scores programados): bip, contexto de 1 s, gate de
  privacidade (nada transcrito antes de acordar), cooldown e limiar +0.2
  durante o TTS.
- `tests/test_voice_hybrid_cache.py` — cache de TTS e divisão por frases.

Sem microfone: todos os testes usam frames sintéticos/motores falsos.
