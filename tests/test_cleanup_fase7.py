"""Testes de limpeza de logs (Fase 7).

1. Logger: sem ``propagate`` (senão mensagens duplicavam via logger raiz).
2. Módulo opcional ausente (ImportError, ex.: discord.py) loga INFO, não ERROR.
3. ``Aris.shutdown()`` idempotente (não duplica os logs de encerramento).
"""

import logging

from utils.logger import Logger


class TestLoggerNoPropagate:
    def test_propagate_false(self, tmp_path):
        log = Logger(name="test-fase7", log_dir=tmp_path, level="INFO")
        # Sem propagate: evita duplicação quando o root tem handler.
        assert log._logger.propagate is False

    def test_no_duplicate_with_root_handler(self, capsys, tmp_path):
        # Simula root com handler (o cenário que duplicava os logs).
        root = logging.getLogger()
        root.addHandler(logging.StreamHandler())
        try:
            log = Logger(name="test-fase7-dup", level="INFO")
            log.info("mensagem-unica-fase7")
            captured = capsys.readouterr().out
            # Não pode aparecer 2x.
            assert captured.count("mensagem-unica-fase7") == 1
        finally:
            root.handlers.clear()


class TestOptionalDependencyLogLevel:
    def test_import_error_logs_info_not_error(self, tmp_path):
        from core.module_manager import ModuleManager

        records = []

        class _RecLogger:
            def info(self, msg):
                records.append(("info", msg))

            def error(self, msg):
                records.append(("error", msg))

            def warning(self, msg):
                records.append(("warning", msg))

            def debug(self, msg):
                records.append(("debug", msg))

        # ModuleManager mínimo p/ chamar _create_module_instance.
        mm = ModuleManager.__new__(ModuleManager)
        mm._logger = _RecLogger()

        class _FakeModule:
            class DiscordBot:
                def __init__(self):
                    raise ImportError("discord.py nao esta instalado")

            def execute(self):  # pragma: no cover - nunca usado
                pass

        result = mm._create_module_instance(_FakeModule(), "discord_bot")
        assert result is None
        kinds = [k for k, _ in records]
        # ImportError (dependência opcional) => INFO, nunca ERROR.
        assert "error" not in kinds
        assert "info" in kinds

    def test_other_exception_still_error(self, tmp_path):
        from core.module_manager import ModuleManager

        records = []

        class _RecLogger:
            def info(self, msg):
                records.append(("info", msg))

            def error(self, msg):
                records.append(("error", msg))

            def warning(self, msg):
                records.append(("warning", msg))

            def debug(self, msg):
                records.append(("debug", msg))

        mm = ModuleManager.__new__(ModuleManager)
        mm._logger = _RecLogger()

        class _FakeModule:
            class BrokenMod:  # nome bate com class_name("broken_mod")
                def __init__(self):
                    raise RuntimeError("bug real")

            def execute(self):  # pragma: no cover
                pass

        mm._create_module_instance(_FakeModule(), "broken_mod")
        kinds = [k for k, _ in records]
        assert "error" in kinds  # exceção não-ImportError continua ERROR


class TestShutdownIdempotent:
    def test_second_shutdown_is_noop(self):
        # Com _shutdown_done True, shutdown() retorna no topo sem tocar em
        # nenhum atributo (não duplica logs nem repete a sequência).
        from core.aris import Aris

        stub = Aris.__new__(Aris)
        stub._shutdown_done = True
        stub._running = True
        # Se o corpo rodasse, estouraria AttributeError (sem _hardware etc.).
        stub.shutdown()
        # Não excepcionou e não mudou estado (saiu antes de `self._running = False`).
        assert stub._shutdown_done is True

    def test_first_shutdown_sets_flag(self):
        from core.aris import Aris

        stub = Aris.__new__(Aris)
        stub._shutdown_done = False
        stub._running = True
        # Fornece mínimos p/ o corpo não estourar antes da guarda ser útil.
        stub._logger = None

        class _Hw:
            connected = False

            def set_state(self, s):
                pass

            def stop(self):
                pass

        stub._hardware = _Hw()
        try:
            stub.shutdown()
        except AttributeError:
            # Algum atributo opcional faltou; ainda assim a guarda foi setada.
            pass
        assert stub._shutdown_done is True
