"""Testes da matriz de LED 8x8 (ESP32 + MAX7219).

Cobrem: config por env var, cliente HTTP não-bloqueante com falha
silenciosa, mapeamento dos estados do Event Bus para os 5 estados do
sketch e o comando "mostra <algo> na matriz".
"""

from __future__ import annotations

import random
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlparse

import pytest

from core.commands import registry
from core.handlers import _SAFETY_LEVELS, handle_matrix
from core.neural.event_bus import EventBus
from core.neural.events import Event
from core.neural.reasoning.reasoning_router import DeterministicEngine
from modules.face_matrix import (
    FACE_STATES,
    HUD_STATES,
    STATE_MAP,
    FaceMatrixClient,
)

# ── Infra: servidor HTTP falso que grava as requisições ─────


@contextmanager
def fake_matrix():
    """Servidor local no lugar do ESP32; devolve (ip, lista de requisições)."""
    requests: list[tuple[str, dict[str, str]]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            requests.append((parsed.path, dict(parse_qsl(parsed.query))))
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silencia o http.server
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()


def wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def make_client(ip: str, **kwargs) -> FaceMatrixClient:
    params = dict(
        timeout=1.0,
        content_hold=0.4,
        happy_hold=0.3,
        spontaneous_interval=0,  # desliga o feliz espontâneo nos testes
        rng=random.Random(7),
    )
    params.update(kwargs)
    client = FaceMatrixClient(ip=ip, **params)
    client.start()
    return client


@pytest.fixture
def matrix():
    with fake_matrix() as (ip, requests):
        client = make_client(ip)
        try:
            # descarta o "idle" de boot para os testes partirem limpos
            wait_for(lambda: len(requests) >= 1)
            requests.clear()
            yield client, requests
        finally:
            client.stop()


def states(requests) -> list[str]:
    return [q["state"] for p, q in requests if p == "/face"]


# ── Configuração ────────────────────────────────────────────


def test_ip_vem_da_env_var(monkeypatch):
    from config.settings import Settings

    monkeypatch.setenv("ARIS_FACE_MATRIX_IP", "10.0.0.9")
    assert Settings().FACE_MATRIX_IP == "10.0.0.9"


def test_ip_vazio_desativa(monkeypatch):
    from config.settings import Settings

    monkeypatch.delenv("ARIS_FACE_MATRIX_IP", raising=False)
    assert Settings().FACE_MATRIX_IP == ""


def test_states_map_cover_todos_os_states_do_hud():
    assert set(STATE_MAP) == set(HUD_STATES)


def test_states_do_sketch_sao_so_os_cinco():
    assert FACE_STATES == ("idle", "listen", "think", "speak", "happy")


def test_estado_sem_mapa_nao_vira_estado_novo():
    # success/warning/offline existem no ESP32 do carrinho, não aqui
    for hud_state in ("success", "warning", "offline", "error", "initializing"):
        assert hud_state not in STATE_MAP
        assert hud_state not in FACE_STATES


# ── Cliente desativado ──────────────────────────────────────


def test_sem_ip_nada_e_enviado():
    client = FaceMatrixClient(ip="")
    assert client.enabled is False
    assert client.start() is False
    assert client.set_state("listening") is False
    assert client.show_text("oi") is False
    assert client.show_number(42) is False
    assert client.show_content("42") is None
    assert client.maybe_happy(probability=1.0) is False
    client.handle_event(Event(event_type="aris_status", source="t",
                              payload={"state": "listening"}))
    client.stop()


# ── Event Bus → firmware ────────────────────────────────────


def test_evento_de_estado_vai_para_o_firmware(matrix):
    client, requests = matrix
    client.handle_event(Event(
        event_type="aris_status", source="aris", payload={"state": "listening"}
    ))
    assert wait_for(lambda: states(requests) == ["listen"])


def test_mapeamento_dos_quatro_estados(matrix):
    client, requests = matrix
    for hud_state, sketch_state in (
        ("listening", "listen"),
        ("thinking", "think"),
        ("executing", "think"),
        ("speaking", "speak"),
        ("idle", "idle"),
    ):
        client.handle_event(Event(
            event_type="aris_status", source="aris", payload={"state": hud_state}
        ))
        assert wait_for(lambda ss=sketch_state: ss in states(requests)), hud_state
        time.sleep(0.05)


def test_estado_fora_do_vocabulario_ignorado(matrix):
    client, requests = matrix
    for hud_state in ("success", "warning", "offline"):
        client.handle_event(Event(
            event_type="aris_status", source="aris", payload={"state": hud_state}
        ))
    time.sleep(0.4)
    assert states(requests) == []


def test_mic_status_ativo_vira_listening(matrix):
    client, requests = matrix
    client.handle_event(Event(
        event_type="mic_status", source="aris", payload={"active": True}
    ))
    assert wait_for(lambda: states(requests) == ["listen"])


def test_mic_status_inativo_nao_muda_estado(matrix):
    client, requests = matrix
    client.handle_event(Event(
        event_type="mic_status", source="aris", payload={"active": False}
    ))
    time.sleep(0.3)
    assert states(requests) == []


def test_evento_malformado_nao_quebra(matrix):
    client, _ = matrix
    client.handle_event(None)
    client.handle_event(object())
    client.handle_event(Event(
        event_type="aris_status", source="t", payload=None
    ))
    assert client.running is True


def test_assinatura_via_event_bus(matrix):
    """O ARIS assina o bus; o cliente recebe os eventos publicados."""
    client, requests = matrix
    bus = EventBus()
    bus.subscribe("aris_status", client.handle_event)
    bus.publish(Event(event_type="aris_status", source="aris",
                      payload={"state": "speaking"}))
    assert wait_for(lambda: states(requests) == ["speak"])


def test_estado_repetido_envia_uma_vez_somente(matrix):
    client, requests = matrix
    for _ in range(5):
        client.set_state("thinking")
    assert wait_for(lambda: states(requests) == ["think"])
    time.sleep(0.3)
    assert states(requests) == ["think"]


# ── Texto e número ──────────────────────────────────────────


def test_texto_usa_endpoint_text(matrix):
    client, requests = matrix
    assert client.show_text("ARIS") is True
    assert wait_for(lambda: ("/text", {"msg": "ARIS"}) in requests)


def test_numero_usa_endpoint_num(matrix):
    client, requests = matrix
    assert client.show_number(42) is True
    assert wait_for(lambda: ("/num", {"value": "42"}) in requests)


def test_numero_invalido_rejeitado(matrix):
    client, _ = matrix
    assert client.show_number("abc") is False
    assert client.show_number(10**9) is False


def test_show_content_interpreta_como_um_humano(matrix):
    client, requests = matrix
    assert client.show_content("42") == "número 42"
    assert client.show_content("número 7") == "número 7"
    assert client.show_content("feliz") == "estado happy"
    assert client.show_content("OI") == "texto OI"
    assert client.show_content("   ") is None
    assert wait_for(lambda: ("/num", {"value": "42"}) in requests)
    assert wait_for(lambda: ("/text", {"msg": "OI"}) in requests)
    assert wait_for(lambda: ("/face", {"state": "happy"}) in requests)


def test_estado_pedido_por_comando_nao_e_derrubado_por_evento(matrix):
    client, requests = matrix
    assert client.show_content("feliz") == "estado happy"
    assert wait_for(lambda: states(requests) == ["happy"])
    # durante a janela do pedido, o Event Bus não sobrescreve
    assert client.set_state("idle") is False
    assert client.set_state("speaking") is False
    time.sleep(0.2)
    assert states(requests) == ["happy"]


def test_conteudo_expira_e_o_estado_volta(matrix):
    client, requests = matrix
    client.show_text("OI")
    assert wait_for(lambda: any(p == "/text" for p, _ in requests))
    assert client.set_state("idle") is False  # bloqueado pelo conteúdo
    assert wait_for(
        lambda: states(requests)[-1:] == ["idle"], timeout=2.0
    ), "o estado deve voltar depois que o conteúdo expira"


# ── Feliz (aleatório / a pedido) ────────────────────────────


def test_maybe_happy_com_certeza(matrix):
    client, requests = matrix
    assert client.maybe_happy(probability=1.0, hold=0.3) is True
    assert wait_for(lambda: states(requests) == ["happy"])


def test_maybe_happy_nunca(matrix):
    client, requests = matrix
    assert client.maybe_happy(probability=0.0) is False
    time.sleep(0.3)
    assert states(requests) == []


def test_feliz_espontaneo_enquanto_ocioso():
    with fake_matrix() as (ip, requests):
        client = make_client(
            ip,
            spontaneous_interval=0.15,
            spontaneous_probability=1.0,
            happy_hold=0.2,
        )
        try:
            wait_for(lambda: len(requests) >= 1)
            assert wait_for(lambda: "happy" in states(requests), timeout=3.0)
        finally:
            client.stop()


# ── Falha de conexão: silenciosa e não-bloqueante ───────────


class SpyLogger:
    def __init__(self):
        self.debugs: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def debug(self, msg):
        self.debugs.append(str(msg))

    def info(self, msg):
        self.debugs.append(str(msg))

    def warning(self, msg):
        self.warnings.append(str(msg))

    def error(self, msg):
        self.errors.append(str(msg))


def test_host_inacessivel_nao_bloqueia_nem_quebra():
    spy = SpyLogger()
    # porta 9 (discard) recusa conexão imediatamente
    client = make_client("127.0.0.1:9", timeout=0.3, logger=spy)
    try:
        started = time.perf_counter()
        assert client.set_state("listening") is True
        assert client.show_text("oi") is True
        assert client.show_number(42) is True
        elapsed = time.perf_counter() - started
        assert elapsed < 0.5, f"chamadas bloquearam a thread por {elapsed:.2f}s"

        time.sleep(0.6)  # deixa o worker falhar algumas vezes
        assert client.running is True
        # o worker continua vivo: nova tentativa segue funcionando
        assert client.set_state("thinking") is True

        assert spy.errors == [], "falha de rede não pode virar error"
        assert spy.warnings == [], "falha de rede não pode virar warning"
        assert spy.debugs, "a falha deve ir para logger.debug"
    finally:
        client.stop()


def test_stop_e_idempotente():
    with fake_matrix() as (ip, _):
        client = make_client(ip)
        client.stop()
        client.stop()
        assert client.running is False
        assert client.set_state("idle") is False
        assert client.show_text("x") is False


# ── Comando "mostra <algo> na matriz" ───────────────────────


@pytest.fixture(scope="module")
def engine():
    return DeterministicEngine()


@pytest.mark.parametrize(
    "phrase,content",
    [
        ("mostra 42 na matriz", "42"),
        ("mostra feliz na matriz", "feliz"),
        ("mostra OI na matriz", "OI"),
        ("me mostra 100 na matriz", "100"),
        ("aris, mostra 2026 na matriz", "2026"),
        ("pode mostrar feliz na matriz", "feliz"),
        ("matriz: 7", "7"),
    ],
)
def test_regra_deterministica_reconhece_o_comando(engine, phrase, content):
    intents = engine.parse(phrase)
    assert intents, f"não reconheceu: {phrase}"
    intent = intents[0]
    assert intent.module == "matrix"
    assert intent.action == "show"
    assert intent.params["content"] == content


@pytest.mark.parametrize(
    "phrase",
    [
        "pesquisa python",
        "abre o discord",
        "status do sistema",
        "pesquisa e mostra o resultado na matriz",
    ],
)
def test_regra_nao_sequestra_outros_comandos(engine, phrase):
    intents = engine.parse(phrase)
    assert not intents or intents[0].module != "matrix"


def test_comando_ta_no_registry_com_safety_safe():
    assert registry.has_intent("matrix") is True
    assert _SAFETY_LEVELS["matrix"] == 1
    assert registry._get_safety_level("matrix") == 1


def test_handler_mostra_na_matriz(matrix):
    client, requests = matrix
    response = registry.execute_intent(
        "matrix", "show", {"content": "42"}, face_matrix=client
    )
    assert "42" in response
    assert wait_for(lambda: ("/num", {"value": "42"}) in requests)


def test_handler_sem_matriz_configurada():
    response = handle_matrix("show", {"content": "42"}, face_matrix=None)
    assert "ARIS_FACE_MATRIX_IP" in response


def test_handler_estado_invalido(matrix):
    client, _ = matrix
    response = registry.execute_intent(
        "matrix", "state", {"state": "triste"}, face_matrix=client
    )
    assert "não existe" in response


def test_handler_estado_valido(matrix):
    client, requests = matrix
    response = registry.execute_intent(
        "matrix", "state", {"state": "speak"}, face_matrix=client
    )
    assert "speak" in response
    assert wait_for(lambda: states(requests) == ["speak"])


def test_handler_sem_conteudo(matrix):
    client, _ = matrix
    response = handle_matrix("show", {"content": ""}, face_matrix=client)
    assert "Mostrei" not in response


# ── ARIS publica os estados no Event Bus ────────────────────


def _fake_aris(last: str = "idle", face=None):
    from types import SimpleNamespace

    from core.aris import Aris

    bus = EventBus()
    received: list[str] = []
    bus.subscribe("aris_status", lambda e: received.append(e.payload["state"]))
    fake = SimpleNamespace(
        _neural=SimpleNamespace(event_bus=bus),
        _hardware=SimpleNamespace(connected=False),
        _last_aris_status=last,
        _face_matrix=face,
    )
    # o ARIS encadeia: _sync_hardware_state → _publish_aris_status
    fake._publish_aris_status = lambda state: Aris._publish_aris_status(fake, state)
    # e assina o cliente no mesmo bus (feito no __init__ do Aris)
    if face is not None and hasattr(face, "handle_event"):
        bus.subscribe("aris_status", face.handle_event)
    return fake, received


def test_transicao_de_estado_vai_para_o_bus():
    from core.aris import Aris
    from modules.esp32_hardware import SystemState

    fake, received = _fake_aris()
    # caminho real: todo _sync_hardware_state também publica
    Aris._sync_hardware_state(fake, SystemState.THINKING)
    Aris._sync_hardware_state(fake, SystemState.SPEAKING)
    Aris._sync_hardware_state(fake, SystemState.IDLE)
    assert received == ["thinking", "speaking", "idle"]


def test_estados_fora_do_vocabulario_do_hud_nao_sao_publicados():
    from core.aris import Aris
    from modules.esp32_hardware import SystemState

    fake, received = _fake_aris()
    for state in (SystemState.WARNING, SystemState.OFFLINE, SystemState.ERROR):
        Aris._publish_aris_status(fake, state)
    assert received == []


def test_estados_textuais_tambem_sao_publicados():
    from core.aris import Aris

    fake, received = _fake_aris()
    Aris._publish_aris_status(fake, "executing")
    assert received == ["executing"]


class _StubFace:
    def __init__(self):
        self.happy: list[tuple[float, float]] = []

    def maybe_happy(self, probability: float = 0.06, hold: float = 1.5) -> bool:
        self.happy.append((probability, hold))
        return True


def test_ao_voltar_ao_repouso_pode_ficar_feliz():
    from core.aris import Aris

    face = _StubFace()
    fake, _ = _fake_aris(last="speaking", face=face)
    Aris._publish_aris_status(fake, "idle")
    assert face.happy and face.happy[0][0] == 0.06


def test_sem_mudanca_de_estado_nao_happy():
    from core.aris import Aris

    face = _StubFace()
    fake, _ = _fake_aris(last="idle", face=face)
    Aris._publish_aris_status(fake, "idle")
    assert face.happy == []


def test_comando_executado_pode_ficar_feliz():
    from core.aris import Aris

    face = _StubFace()
    fake, _ = _fake_aris(face=face)
    Aris._face_command_happy(fake)
    assert face.happy and face.happy[0][0] == 0.5


def test_comando_do_terminal_conecta_matriz_e_bus():
    """De ponta a ponta: frase → intent → handler → firmware."""
    from core.aris import Aris

    with fake_matrix() as (ip, requests):
        client = make_client(ip)
        try:
            wait_for(lambda: len(requests) >= 1)
            requests.clear()

            intents = DeterministicEngine().parse("mostra 42 na matriz")
            intent = intents[0]
            response = registry.execute_intent(
                intent.module, intent.action, intent.params, face_matrix=client
            )
            assert "42" in response
            assert wait_for(lambda: ("/num", {"value": "42"}) in requests)

            # espera o conteúdo pedido expirar para o estado voltar a reagir
            time.sleep(0.6)
            requests.clear()

            # e o mesmo cliente espelha o estado publicado pelo ARIS
            fake, received = _fake_aris(face=client)
            Aris._publish_aris_status(fake, "speaking")
            assert received == ["speaking"]
            assert wait_for(lambda: "speak" in states(requests))
        finally:
            client.stop()
