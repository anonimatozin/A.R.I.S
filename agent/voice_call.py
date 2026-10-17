"""
A.R.I.S. Voice Call — Janela Python no PC
Captura microfone, envia audio ao Dashboard, recebe e toca audio.
Wake word: "Aris" + pergunta/comando
"""
import sys
import json
import threading
import queue
import time
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pyaudio
import numpy as np
import websocket

# ── Config ────────────────────────────────────────────────
LISTENER_URL = "ws://127.0.0.1:8770/ws/audio"
SAMPLE_RATE = 16000
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
WAKE_WORD = "aris"

# ── State ─────────────────────────────────────────────────
connected = False
in_call = False
ws = None
audio_queue = queue.Queue()
pya = None
stream_in = None
stream_out = None


def log(msg):
    print(f"[Call] {msg}", flush=True)


# ── Audio Capture ─────────────────────────────────────────
def audio_callback(in_data, frame_count, time_info, status):
    """Callback do microfone — coloca audio na queue."""
    if in_call:
        audio_queue.put(in_data)
    return (None, pyaudio.paContinue)


def start_capture():
    global stream_in, pya
    if pya is None:
        pya = pyaudio.PyAudio()
    stream_in = pya.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE,
        stream_callback=audio_callback,
    )
    stream_in.start_stream()
    log("Microfone aberto")


def stop_capture():
    global stream_in
    if stream_in:
        stream_in.stop_stream()
        stream_in.close()
        stream_in = None
        log("Microfone fechado")


# ── Audio Playback ────────────────────────────────────────
def play_audio(data: bytes):
    """Toca audio recebido do Dashboard."""
    global stream_out, pya
    if pya is None:
        pya = pyaudio.PyAudio()
    try:
        stream_out = pya.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            output=True,
            frames_per_buffer=CHUNK_SIZE,
        )
        # Converter bytes numpy int16
        audio_np = np.frombuffer(data, dtype=np.int16)
        stream_out.write(audio_np.tobytes())
        stream_out.stop_stream()
        stream_out.close()
        stream_out = None
    except Exception as e:
        log(f"Erro ao tocar: {e}")


# ── Wake Word Detection (simples — busca substring) ──────
def check_wake_word(text: str) -> bool:
    """Verifica se o texto contém a wake word 'aris'."""
    return WAKE_WORD in text.lower().strip()


# ── WebSocket ─────────────────────────────────────────────
def on_message(ws, message):
    """Recebe mensagem do PC Listener."""
    global in_call
    try:
        data = json.loads(message)
        msg_type = data.get("type", "")

        if msg_type == "call_started":
            in_call = True
            start_capture()
            log("Call iniciada!")

        elif msg_type == "call_ended":
            in_call = False
            stop_capture()
            log("Call encerrada")

        elif msg_type == "audio":
            # Audio do Dashboard para tocar
            import base64
            audio_data = base64.b64decode(data["data"])
            threading.Thread(target=play_audio, args=(audio_data,), daemon=True).start()

        elif msg_type == "transcript":
            # Texto reconhecido do Dashboard
            text = data.get("text", "")
            log(f"Dashboard disse: {text}")
            if check_wake_word(text):
                log("Wake word detectada! Processando...")
                # Enviar comando para LLM via PC Listener
                process_command(text)

        elif msg_type == "error":
            log(f"Erro: {data.get('message', 'desconhecido')}")

    except Exception as e:
        log(f"Erro ao processar mensagem: {e}")


def on_open(ws):
    global connected
    connected = True
    log("Conectado ao PC Listener")
    # Enviar identificacao
    ws.send(json.dumps({
        "type": "register",
        "client": "pc_window"
    }))


def on_close(ws, close_status_code, close_msg):
    global connected, in_call
    connected = False
    in_call = False
    stop_capture()
    log("Desconectado do PC Listener")


def on_error(ws, error):
    log(f"WebSocket error: {error}")


def connect_ws():
    """Conecta ao PC Listener via WebSocket."""
    global ws
    while True:
        try:
            ws = websocket.WebSocketApp(
                LISTENER_URL,
                on_open=on_open,
                on_message=on_message,
                on_close=on_close,
                on_error=on_error,
            )
            log(f"Conectando a {LISTENER_URL}...")
            ws.run_forever()
        except Exception as e:
            log(f"Erro de conexao: {e}")
        log("Reconectando em 5s...")
        time.sleep(5)


def process_command(text: str):
    """Envia comando para LLM via PC Listener HTTP."""
    import urllib.request
    try:
        # Remover wake word do texto
        clean = text.lower().replace(WAKE_WORD, "").strip()
        if not clean:
            return

        payload = json.dumps({
            "messages": [{"role": "user", "content": clean}],
            "model": "openai/gpt-oss-120b"
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8770/api/llm",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            if body.get("ok"):
                reply = body.get("response", "")
                log(f"Resposta: {reply}")
                # Enviar resposta para Dashboard via WebSocket
                if ws:
                    ws.send(json.dumps({
                        "type": "text",
                        "text": reply
                    }))
    except Exception as e:
        log(f"Erro LLM: {e}")


# ── Main ──────────────────────────────────────────────────
if __name__ == "__main__":
    log("=== A.R.I.S. Voice Call ===")
    log(f"Wake word: '{WAKE_WORD}'")
    log(f"Servidor: {LISTENER_URL}")
    log("Pressione Ctrl+C para sair")
    print(flush=True)
    connect_ws()
