"""Cenas de ambiente da ARIS nos olhos — Spotify, fone, bateria, ESP32 e sono.

O aris_eyes ganhou cenas prontas (Parte 1). Este módulo cuida do que é
"ambiente": o que acontece FORA da conversa e pode ser mostrado sozinho,
numa thread daemon com ciclo (padrão 3 s), timeout em TODO subprocess e
nenhuma exceção subindo para quem chamou.

REGRA DE PRECEDÊNCIA (a mais importante): estados da ARIS (listening,
thinking/executing, speaking, warning, error, offline...) SEMPRE passam na
frente. Enquanto a ARIS está ocupada, o ambiente apenas GUARDA a cena na
ponte (``eyes_bridge.set_ambient_scene``); quando o estado volta a ``idle``
a própria ponte envia ``scene <ambiente>`` no lugar do mood ocioso.
Ver ``utils/eyes_bridge.py``.

Precedência DENTRO do ambiente (maior primeiro):
    1. bateria fraca (< 15% e descarregando)  -> scene bateria
    2. ESP32 conectado (evento, transitório)   -> scene conectado
    3. tarefa grande concluída (evento)        -> scene comemorar
    4. música tocando (+ fone)                 -> scene spotify [+ prop headphones on]
    5. fone de ouvido só                       -> scene fone
    6. ocioso há muito tempo à noite           -> scene dormir
    7. nada                                     -> None (comportamento normal)

Fontes dos sinais:
    Música   playerctl (preferido); sem ele, MPRIS direto por busctl ou
             dbus-send; sem nenhum dos três, o recurso desliga UMA vez no
             log. Pausa usa histerese de 3 s (não pisca). A cor da capa
             vira ``accent #rrggbb`` (baixada em thread, timeout 3 s, no
             máximo 2 MB, só a cor — título/faixa NUNCA sai da máquina).
    Fone     pactl (porta ativa headphones/headset ou saída bluez_*); sem
             pactl, ``wpctl status`` (PipeWire); sem os dois, desliga.
    Bateria  psutil.sensors_battery(); desktop sem bateria = recurso mudo.
    ESP32    notificar_esp32_conectado(), chamado pelo listener de eventos
             do Mini Deck (core/aris.py::_on_deck_event).
    Sono     ociosidade observada pela ponte (registrar_observador) + hora.
    Sucesso  observador do estado "success" (cena transitória comemorar).

Variáveis de ambiente:
    ARIS_EYES_AMBIENT=0            desliga o módulo inteiro (kill-switch)
    ARIS_EYES_AMBIENT_PLAYERS      players MPRIS (padrão "spotify")
    ARIS_EYES_AMBIENT_INTERVAL     ciclo em segundos (padrão 3)
    ARIS_EYES_AMBIENT_IDLE_DORMIR  minutos de ociosidade p/ scene dormir (padrão 15)
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime

from . import eyes_bridge

log = logging.getLogger("aris.eyes_ambient")

# ── Ajustes (env lida em tempo de execução para os testes não recarregarem) ──

_OFF = ("0", "false", "no", "off")


def _habilitado() -> bool:
    return os.getenv("ARIS_EYES_AMBIENT", "1").strip().lower() not in _OFF


def _intervalo() -> float:
    try:
        return max(0.5, float(os.getenv("ARIS_EYES_AMBIENT_INTERVAL", "3")))
    except ValueError:
        return 3.0


def _players() -> tuple:
    bruto = os.getenv("ARIS_EYES_AMBIENT_PLAYERS", "spotify")
    return tuple(p.strip() for p in bruto.split(",") if p.strip()) or ("spotify",)


def _min_dormir() -> float:
    try:
        return max(1.0, float(os.getenv("ARIS_EYES_AMBIENT_IDLE_DORMIR", "15")))
    except ValueError:
        return 15.0


# ── Constantes de comportamento ──

_HISTERESE_PAUSA_S = 3.0      # pausa não tira a cena antes disso (anti-piscar)
_CONECTADO_S = 3.5            # scene conectado dura 2,8 s; mantém o alvo um pouco além
_COMEMORAR_S = 4.5            # scene comemorar dura 4 s
_BATERIA_LIMITE = 15.0        # % de bateria que liga a cena bateria
_NOITE_INICIO, _NOITE_FIM = 22, 6   # 22h..6h
_BRIGHTNESS_MIN = 70          # brilho mínimo do accent (0..255)
_CAPA_LIMITE = 2 * 1024 * 1024       # 2 MB no máximo na capa
_CAPA_TIMEOUT_S = 3.0

# ── Estado do ambiente (tudo sob _lock; nenhum outro lock) ──

_lock = threading.Lock()
_thread: threading.Thread | None = None
_parar = threading.Event()

_status_player: str | None = None   # Playing | Paused | Stopped | None
_pausa_desde: float | None = None
_musica: bool = False                  # música vale agora (pausa ainda dentro da histerese)
_url_capa: str | None = None        # última URL de capa já processada
_accent: str | None = None          # cor da capa atual (#rrggbb)
_accent_enviado: str | None = None  # cor que já está nos olhos
_bateria_baixa: bool | None = None
_fone: bool | None = None
_esp32_ate: float | None = None
_comemorar_ate: float | None = None
_ocioso_desde: float | None = None
_desligados: set = set()               # recursos desligados (log uma vez)
_capa_cache: dict = {}                 # url -> #rrggbb


def _agora() -> float:
    """Relógio monotônico (função separada para os testes congelarem o tempo)."""
    return time.monotonic()


def reset_para_testes() -> None:
    """Zera todo o estado do ambiente (usado apenas em testes)."""
    global _thread
    global _status_player, _pausa_desde, _musica, _url_capa, _accent, _accent_enviado
    global _bateria_baixa, _fone, _esp32_ate, _comemorar_ate, _ocioso_desde
    with _lock:
        _thread = None
        _status_player = None
        _pausa_desde = None
        _musica = False
        _url_capa = None
        _accent = None
        _accent_enviado = None
        _bateria_baixa = None
        _fone = None
        _esp32_ate = None
        _comemorar_ate = None
        _ocioso_desde = None
        _desligados.clear()
        _capa_cache.clear()
    _parar.clear()


# ── Subprocessos (timeout sempre; nunca levanta) ──

def _rodar(cmd: list, timeout: float = 2.0) -> str | None:
    """Roda um comando; stdout em sucesso, None em qualquer falha. Nunca levanta."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout or ""


def _existe(binario: str) -> bool:
    try:
        return shutil.which(binario) is not None
    except Exception:
        return False


def _desligar_recurso(nome: str, motivo: str) -> None:
    """Desliga um recurso e registra UMA vez no log."""
    with _lock:
        if nome in _desligados:
            return
        _desligados.add(nome)
    log.warning("eyes_ambient: recurso '%s' desligado: %s", nome, motivo)


def _desligado(nome: str) -> bool:
    with _lock:
        return nome in _desligados


# ── Música (MPRIS) ──

def _status_spotify() -> tuple:
    """(status, artUrl) do primeiro player que responder; (None, None) sem player.

    playerctl é o caminho preferido; sem ele, busctl; depois dbus-send.
    Se nenhum dos três existir, desliga o recurso (uma vez no log).
    """
    if _desligado("spotify"):
        return None, None
    players = _players()
    tem_playerctl = _existe("playerctl")

    if tem_playerctl:
        for p in players:
            saida = _rodar(["playerctl", "-p", p, "status"], 1.5)
            if saida is None:
                continue                    # player ausente; tenta o próximo
            status = saida.strip() or None
            art = _rodar(["playerctl", "-p", p, "-f", "{{metadata:mpris:artUrl}}"], 1.5)
            url = (art or "").strip()
            if not url.startswith(("http://", "https://", "file://", "/")):
                url = ""
            return status, url or None
        return None, None                   # playerctl ok, ninguém tocando

    if not _existe("busctl") and not _existe("dbus-send"):
        _desligar_recurso("spotify", "sem playerctl, busctl nem dbus-send")
        return None, None

    if _existe("busctl"):
        for p in players:
            dest = "org.mpris.MediaPlayer2." + p
            saida = _rodar(["busctl", "--user", "get-property", dest,
                            "/org/mpris/MediaPlayer2",
                            "org.mpris.MediaPlayer2.Player", "Status"], 2.0)
            m = re.search(r'"(Playing|Paused|Stopped)"', saida or "")
            if m:
                return m.group(1), _arturl_busctl(dest)

    if _existe("dbus-send"):
        for p in players:
            saida = _rodar(["dbus-send", "--print-reply",
                            "--dest=org.mpris.MediaPlayer2." + p,
                            "/org/mpris/MediaPlayer2",
                            "org.freedesktop.DBus.Properties.Get",
                            "string:org.mpris.MediaPlayer2.Player",
                            "string:Status"], 2.0)
            m = re.search(r'"(Playing|Paused|Stopped)"', saida or "")
            if m:
                return m.group(1), None     # dbus-send: capa fica por conta do busctl
    return None, None


def _arturl_busctl(dest: str) -> str | None:
    saida = _rodar(["busctl", "--user", "get-property", dest,
                    "/org/mpris/MediaPlayer2",
                    "org.mpris.MediaPlayer2.Player", "Metadata"], 3.0)
    if not saida:
        return None
    m = re.search(r'"mpris:artUrl"\s+\S+\s+"([^"]+)"', saida)
    return m.group(1) if m else None


# ── Cor da capa → accent ──

def _ao_mudar_capa(url: str) -> None:
    """Processa a capa da música atual (thread; cache por URL). Nunca levanta."""
    global _url_capa, _accent
    try:
        with _lock:
            if url == _url_capa:
                return
            _url_capa = url
            cached = _capa_cache.get(url)
            if cached:
                _accent = cached
                return
        threading.Thread(target=_baixar_capa, args=(url,),
                         daemon=True, name="eyes-ambient-capa").start()
    except Exception:
        pass


def _baixar_capa(url: str) -> None:
    """Baixa a capa e extrai a cor; guarda no cache. Nunca levanta."""
    global _accent
    try:
        cor = _cor_da_capa(url)
        if not cor:
            return
        with _lock:
            _capa_cache[url] = cor
            if url == _url_capa:
                _accent = cor
    except Exception:
        pass


def _cor_da_capa(url: str,
                 timeout: float = _CAPA_TIMEOUT_S,
                 limite: int = _CAPA_LIMITE) -> str | None:
    """Média dos pixels mais saturados (ignorando escuros/cinzados) como #rrggbb.

    Baixa no máximo ``limite`` bytes com ``timeout``; falha = None.
    Título/nome de faixa não são lidos nem enviados a lugar nenhum.
    """
    try:
        if url.startswith("/"):
            with open(url, "rb") as fh:
                dados = fh.read(limite + 1)
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "ARIS/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                dados = resp.read(limite + 1)
        if len(dados) > limite:
            return None
        from PIL import Image  # noqa: PLC0415 — import tardio (Pillow só aqui)

        img = Image.open(io.BytesIO(dados)).convert("RGB")
        img.thumbnail((32, 32))
        pixels = list(img.getdata())
        if not pixels:
            return None
        # croma (saturação) por pixel; fica com os mais saturados
        com_croma = []
        for r, g, b in pixels:
            mx, mn = max(r, g, b), min(r, g, b)
            if mx < 40:
                continue                    # muito escuro/cinzento
            croma = (mx - mn) / mx
            if croma >= 0.20:
                com_croma.append((croma, r, g, b))
        if com_croma:
            com_croma.sort(key=lambda t: -t[0])
            n = max(1, len(com_croma) // 4)
            escolhidos = [(r, g, b) for _, r, g, b in com_croma[:n]]
        else:                               # sem cor: usa os mais claros
            claros = sorted(pixels, key=lambda p: -(p[0] + p[1] + p[2]))
            escolhidos = [p for p in claros[:max(1, len(claros) // 4)] if max(p) >= 40]
            escolhidos = escolhidos or [claros[0]]
        r = sum(p[0] for p in escolhidos) / len(escolhidos)
        g = sum(p[1] for p in escolhidos) / len(escolhidos)
        b = sum(p[2] for p in escolhidos) / len(escolhidos)
        mx = max(r, g, b)                   # garante brilho mínimo
        if mx < _BRIGHTNESS_MIN and mx > 0:
            fator = min(_BRIGHTNESS_MIN / mx, 255.0 / max(mx, 1))
            r, g, b = min(255, r * fator), min(255, g * fator), min(255, b * fator)
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    except Exception:
        return None


def _sincronizar_accent(cena_alvo: str | None, ocioso: bool,
                        cena_foi_aplicada: bool) -> None:
    """Manda/refresha o accent quando a cena alvo é spotify. Nunca levanta."""
    global _accent_enviado
    try:
        with _lock:
            cor = _accent
            if cena_alvo != "spotify":
                if _accent_enviado is not None:
                    _accent_enviado = None   # próxima vez que a música voltar, reenvia
                return
            if not ocioso:
                _accent_enviado = None       # cena será (re)enviada depois: accent junto
                return
            if cor is None:
                return                       # sem capa: verde padrão da cena
            if cor == _accent_enviado and not cena_foi_aplicada:
                return
        resposta = eyes_bridge.enviar_comando(f"accent {cor}")
        if resposta is not None:
            with _lock:
                _accent_enviado = cor
    except Exception:
        pass


# ── Fone de ouvido ──

def _fone_ativo() -> bool | None:
    """True/False = fone conectado; None = recurso indisponível/desligado."""
    if _desligado("fone"):
        return None
    if _existe("pactl"):
        default = (_rodar(["pactl", "get-default-sink"], 1.5) or "").strip()
        saida = _rodar(["pactl", "list", "sinks"], 3.0)
        if saida and default:
            return _parse_pactl(saida, default)
    if _existe("wpctl"):
        saida = _rodar(["wpctl", "status"], 2.5)
        if saida:
            if _parse_wpctl(saida):         # a descrição do sink já denuncia
                return True
            # PipeWire puro: as propriedades do sink padrão dizem a verdade
            # (bluetooth, form_factor, ícone de fone) — ver fixtures.
            info = _rodar(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"], 2.5)
            if info is None:
                return False
            return _parse_wpctl_inspect(info)
    _desligar_recurso("fone", "sem pactl (e wpctl sem saída)")
    return None


def _parse_pactl(listing: str, default_sink: str) -> bool:
    """True se o sink padrão sai por fone (porta/headphone ou bluez)."""
    for bloco in re.split(r"\n(?=Sink #\d)", listing):
        if not re.search(rf"^\s*Name:\s*{re.escape(default_sink)}\s*$",
                         bloco, re.M):
            continue
        if re.search(r"^\s*Active Port:\s*\S*(headphone|headset)",
                     bloco, re.I | re.M):
            return True
        if re.search(r"^\s*device\.form_factor:\s*\"?(headphone|headset)",
                     bloco, re.I | re.M):
            return True
        return default_sink.startswith("bluez_")
    return False


def _parse_wpctl(status: str) -> bool:
    """True se o sink padrão do wpctl (linha com *) parece fone/BT."""
    m = re.search(r"Sinks:\s*\n(.*?)(?=\n\s*[├└]─)", status, re.S)
    if not m:
        return False
    for linha in m.group(1).splitlines():
        if "*" not in linha:
            continue
        baixo = linha.lower()
        return any(chave in baixo
                   for chave in ("headphone", "headset", "headphones", "bluez"))
    return False


def _parse_wpctl_inspect(inspect: str) -> bool:
    """True se ``wpctl inspect @DEFAULT_AUDIO_SINK@`` descreve fone/BT."""
    baixo = inspect.lower()
    if "device.bus" in baixo and "bluetooth" in baixo:
        return True
    if "bluez" in baixo:
        return True
    m = re.search(r'device\.icon-name\s*=\s*"([^"]+)"', baixo)
    if m and m.group(1) in ("audio-headphones", "audio-headset"):
        return True
    if re.search(r'device\.form_factor\s*=\s*"?(headphone|headset)"?', baixo):
        return True
    m = re.search(r'device\.profile\.name\s*=\s*"([^"]+)"', baixo)
    return bool(m and any(k in m.group(1) for k in ("headphone", "headset")))


# ── Bateria, ESP32, sucesso, sono ──

def _bateria_fraca() -> bool | None:
    """True = abaixo do limite e descarregando; None = sem bateria/erro."""
    try:
        import psutil  # noqa: PLC0415 — import tardio (só os ciclos de bateria)

        bat = psutil.sensors_battery()
    except Exception:
        return None
    if bat is None or bat.percent is None:
        return None                         # desktop sem bateria: recurso mudo
    return bool(bat.percent < _BATERIA_LIMITE and not bat.power_plugged)


def notificar_esp32_conectado() -> None:
    """Mini Deck conectou ao Wi-Fi → scene conectado (transitória). Nunca levanta."""
    global _esp32_ate
    try:
        if not _habilitado():
            return
        with _lock:
            _esp32_ate = _agora() + _CONECTADO_S
    except Exception:
        pass


def notificar_tarefa_ok() -> None:
    """Tarefa grande concluída → scene comemorar (transitória). Nunca levanta."""
    global _comemorar_ate
    try:
        if not _habilitado():
            return
        with _lock:
            _comemorar_ate = _agora() + _COMEMORAR_S
    except Exception:
        pass


def _on_estado_ponte(estado: str) -> None:
    """Observador registrado na ponte: ociosidade (sono) e success (confete)."""
    global _ocioso_desde
    try:
        agora = _agora()
        if estado == "success":
            notificar_tarefa_ok()
        ocioso = estado in eyes_bridge.OCIOSOS_AMBIENT
        with _lock:
            if ocioso:
                if _ocioso_desde is None:
                    _ocioso_desde = agora
            else:
                _ocioso_desde = None
    except Exception:
        pass


def _hora_noite() -> bool:
    hora = datetime.now().hour
    return hora >= _NOITE_INICIO or hora < _NOITE_FIM


# ── Ciclo ──

def _coletar_sinais(agora: float) -> None:
    """Atualiza o estado dos sinais (música com histerese, capa, fone, bateria)."""
    global _status_player, _pausa_desde, _musica, _fone, _bateria_baixa, _url_capa

    status, art = _status_spotify()
    with _lock:
        _status_player = status
        if status == "Playing":
            _pausa_desde = None
        elif status in ("Paused", "Stopped"):
            if _pausa_desde is None:
                _pausa_desde = agora
        else:
            _pausa_desde = None
        musica_vale = (
            status == "Playing"
            or (status in ("Paused", "Stopped") and _pausa_desde is not None
                and (agora - _pausa_desde) < _HISTERESE_PAUSA_S)
        )
        _musica = musica_vale
    if status == "Playing" and art:
        _ao_mudar_capa(art)
    elif status != "Playing":
        with _lock:
            _url_capa = None                 # nova execução da música: reprocessa a capa

    fone = _fone_ativo()
    with _lock:
        if fone is not None:
            _fone = bool(fone)
    bat = _bateria_fraca()
    with _lock:
        if bat is not None:
            _bateria_baixa = bool(bat)


def _calcular_alvo(agora: float) -> tuple:
    """Cena alvo do ambiente pela precedência (None = nada a mostrar)."""
    with _lock:
        if _bateria_baixa:
            return "bateria", ()
        if _esp32_ate is not None and agora < _esp32_ate:
            return "conectado", ()
        if _comemorar_ate is not None and agora < _comemorar_ate:
            return "comemorar", ()
        if _musica:
            return ("spotify", ("headphones",)) if _fone else ("spotify", ())
        if _fone:
            return "fone", ()
        if (_ocioso_desde is not None
                and (agora - _ocioso_desde) >= _min_dormir() * 60.0
                and _hora_noite()):
            return "dormir", ()
        return None, ()


def reconciliar() -> tuple | None:
    """Calcula a cena alvo e sincroniza com a ponte. Retorna o alvo.

    Nunca lança exceção (kill-switch, olhos parados, subprocess quebrado —
    tudo vira None e o próximo ciclo tenta de novo).
    """
    if not _habilitado():
        return None
    try:
        agora = _agora()
        _coletar_sinais(agora)
        alvo, props = _calcular_alvo(agora)
        resultado = eyes_bridge.set_ambient_scene(alvo, props)
        aplicado = resultado in ("aplicado", "igual")
        ocioso = eyes_bridge.ocioso_para_ambiente()
        _sincronizar_accent(alvo, ocioso and aplicado, resultado == "aplicado")
        return (alvo, props) if alvo else None
    except Exception:
        log.debug("eyes_ambient: ciclo falhou (próximo ciclo tenta de novo)",
                  exc_info=True)
        return None


def _loop() -> None:
    while not _parar.is_set():
        reconciliar()
        _parar.wait(_intervalo())


# ── Liga/desliga ──

def iniciar() -> None:
    """Sobe a thread daemon do ambiente (idempotente; respeita o kill-switch)."""
    global _thread
    if not _habilitado():
        log.info("eyes_ambient: desligado (ARIS_EYES_AMBIENT=0)")
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _parar.clear()
        _thread = threading.Thread(target=_loop, daemon=True, name="eyes-ambient")
        thread = _thread
    eyes_bridge.registrar_observador(_on_estado_ponte)
    thread.start()


def parar(timeout: float = 2.0) -> None:
    """Pede para a thread parar (desligamento limpo da ARIS). Nunca levanta."""
    try:
        _parar.set()
        with _lock:
            thread = _thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
    except Exception:
        pass
