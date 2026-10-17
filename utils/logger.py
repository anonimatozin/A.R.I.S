"""Sistema de logs do A.R.I.S.

Gerencia registro de eventos com suporte a rotação de arquivos.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class Logger:
    """Gerenciador de logs centralizado.

    Args:
        name: Nome do logger.
        log_dir: Diretório para armazenar os arquivos de log.
        level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        max_size_mb: Tamanho máximo do arquivo de log em MB.
    """

    def __init__(
        self,
        name: str = "aris",
        log_dir: Path | None = None,
        level: str = "INFO",
        max_size_mb: int = 10,
    ) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        self._logger.handlers.clear()
        # Sem propagate: senão mensagens sobem pro logger raiz e saem
        # DUPLICADAS quando o root tem handler (ex.: basicConfig).
        self._logger.propagate = False

        self._setup_console_handler()
        if log_dir is not None:
            self._setup_file_handler(log_dir, max_size_mb)

    def _setup_console_handler(self) -> None:
        """Configura o handler de saída no console."""
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

    def _setup_file_handler(self, log_dir: Path | str, max_size_mb: int) -> None:
        """Configura o handler de arquivo com rotação."""
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "aris.log"

        handler = RotatingFileHandler(
            log_file,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

    def debug(self, message: str) -> None:
        """Registra mensagem de nível DEBUG."""
        self._logger.debug(message)

    def info(self, message: str) -> None:
        """Registra mensagem de nível INFO."""
        self._logger.info(message)

    def warning(self, message: str) -> None:
        """Registra mensagem de nível WARNING."""
        self._logger.warning(message)

    def error(self, message: str) -> None:
        """Registra mensagem de nível ERROR."""
        self._logger.error(message)

    def critical(self, message: str) -> None:
        """Registra mensagem de nível CRITICAL."""
        self._logger.critical(message)
