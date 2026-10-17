"""Testes de concorrência: várias threads gravando e lendo a mesma SqliteMemory (Parte 4)."""

from __future__ import annotations

import threading
import uuid

from aris_agent.memory import SqliteMemory

THREADS = 6
OP_PER_THREAD = 15


def test_threads_gravam_e_leem(tmp_path) -> None:
    memoria = SqliteMemory(tmp_path / "concorrente.sqlite3")
    erros: list[BaseException] = []

    def trabalhador(indice: int) -> None:
        try:
            for j in range(OP_PER_THREAD):
                # uuid impede a deduplicação de fundir registros distintos
                memoria.remember(
                    f"registro thread {indice} numero {j} {uuid.uuid4().hex}", kind="fact"
                )
                memoria.add_turn(f"s{indice}", "user", f"mensagem {indice}-{j}")
                memoria.recall(f"thread {indice}", k=3)
        except BaseException as exc:  # noqa: BLE001 - qualquer erro falha o teste
            erros.append(exc)

    threads = [
        threading.Thread(target=trabalhador, args=(indice,)) for indice in range(THREADS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "thread travou"

    assert not erros, f"erros em threads: {erros!r}"
    assert memoria.count() == THREADS * OP_PER_THREAD
    for indice in range(THREADS):
        assert len(memoria.recent_turns(f"s{indice}", 100)) == OP_PER_THREAD
    assert memoria.recall("registro thread", k=10)
    memoria.close()


def test_threads_deduplicam_texto_identico(tmp_path) -> None:
    memoria = SqliteMemory(tmp_path / "dedup_concorrente.sqlite3")
    erros: list[BaseException] = []
    barreira = threading.Barrier(THREADS)

    def gravador() -> None:
        try:
            barreira.wait(timeout=30)
            for _ in range(5):
                memoria.remember("texto idêntico gravado por todas as threads")
        except BaseException as exc:  # noqa: BLE001
            erros.append(exc)

    threads = [threading.Thread(target=gravador) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not erros, f"erros em threads: {erros!r}"
    assert memoria.count() == 1, "deduplicação deve segurar mesmo com várias threads"
    memoria.close()


def test_leitura_concorrente_com_exportacao(tmp_path) -> None:
    memoria = SqliteMemory(tmp_path / "export_concorrente.sqlite3")
    for index in range(30):
        memoria.remember(f"item {index} {uuid.uuid4().hex}")
        memoria.add_turn("s1", "user", f"turno {index}")
    erros: list[BaseException] = []

    def leitor() -> None:
        try:
            for _ in range(10):
                memoria.export_all()
                memoria.recall("item", k=5)
                memoria.recent_turns("s1", 5)
        except BaseException as exc:  # noqa: BLE001
            erros.append(exc)

    threads = [threading.Thread(target=leitor) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not erros, f"erros de leitura: {erros!r}"
    assert memoria.count() == 30
    memoria.close()


def test_threads_em_banco_em_memoria() -> None:
    memoria = SqliteMemory(":memory:")
    erros: list[BaseException] = []

    def trabalhador(indice: int) -> None:
        try:
            for j in range(10):
                memoria.remember(f"memoria {indice} {j} {uuid.uuid4().hex}")
                memoria.recall(f"memoria {indice}", k=3)
        except BaseException as exc:  # noqa: BLE001
            erros.append(exc)

    threads = [threading.Thread(target=trabalhador, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not erros, f"erros em threads: {erros!r}"
    assert memoria.count() == 40
    memoria.close()


def test_close_depois_das_threads(tmp_path) -> None:
    memoria = SqliteMemory(tmp_path / "fechando.sqlite3")
    erros: list[BaseException] = []

    def rapido() -> None:
        try:
            memoria.remember(f"rapido {uuid.uuid4().hex}")
        except BaseException as exc:  # noqa: BLE001
            erros.append(exc)

    threads = [threading.Thread(target=rapido) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not erros
    memoria.close()
    assert not memoria._connections, "close() deve fechar todas as conexões"
