"""Interruptor de emergência (KillSwitch).

Dispara por: método Python (``engage()``), arquivo-sentinela ``data_dir/STOP``
e atalho global opcional via biblioteca ``keyboard`` (**opcional**, desligada
por padrão e importada de forma preguiçosa — pode exigir permissões).
"""

from __future__ import annotations

import logging
import threading
import weakref
from pathlib import Path

log = logging.getLogger("aris.agent.safety.killswitch")


class KillSwitch:
    """Bloqueia novas chamadas e cancela as tarefas em andamento."""

    def __init__(
        self,
        data_dir: Path | str,
        *,
        sentinel_name: str = "STOP",
        enable_hotkey: bool = False,
        hotkey: str = "ctrl+alt+F12",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.sentinel_path = self.data_dir / sentinel_name
        self.hotkey = hotkey
        self._enable_hotkey = enable_hotkey
        self._flag = threading.Event()
        self._reason = ""
        self._lock = threading.Lock()
        self._cancels: weakref.WeakSet = weakref.WeakSet()
        self._hotkey_started = False

    # ---------------------------------------------------------------- estado

    @property
    def engaged(self) -> bool:
        return self._flag.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    # ------------------------------------------------------------- ações

    def register(self, cancel: threading.Event) -> None:
        """Associa o ``cancel`` de uma tarefa; se já houver engage, cancela na hora."""
        try:
            self._cancels.add(cancel)
        except TypeError:  # pragma: no cover - Event sem weakref (não ocorre)
            log.debug("não consegui registrar o cancel da tarefa")
        if self._flag.is_set():
            cancel.set()

    def engage(self, reason: str) -> bool:
        """Ativa o interruptor; devolve ``True`` se esta chamada foi quem ativou."""
        with self._lock:
            if self._flag.is_set():
                return False
            self._reason = str(reason)
            self._flag.set()
        log.critical("KILL SWITCH ativado: %s", self._reason)
        for cancel in list(self._cancels):
            cancel.set()
        return True

    def reset(self) -> None:
        """Desativa o interruptor e remove o arquivo-sentinela (melhor esforço)."""
        with self._lock:
            self._flag.clear()
            self._reason = ""
        try:
            if self.sentinel_path.exists():
                self.sentinel_path.unlink()
        except OSError as exc:
            log.warning("não consegui remover %s: %s", self.sentinel_path, exc)
        log.warning("kill switch reiniciado")

    def check_sentinel(self) -> bool:
        """Se ``data_dir/STOP`` existir, ativa o interruptor. Devolve o estado."""
        if self._flag.is_set():
            return True
        try:
            exists = self.sentinel_path.exists()
        except OSError:  # pragma: no cover - defensivo
            exists = False
        if exists:
            self.engage(f"arquivo-sentinela {self.sentinel_path}")
            return True
        return False

    def start_hotkey(self) -> bool:
        """Registra o atalho global; ``False`` se a biblioteca ``keyboard`` faltar.

        A biblioteca é **opcional e não instalada por padrão**: import preguiçoso
        com aviso, sem derrubar nada quando ausente.
        """
        if self._hotkey_started:
            return True
        if not self._enable_hotkey:
            return False
        try:
            import keyboard  # type: ignore[import-not-found]  # opcional
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira aviso
            log.warning(
                "atalho global de emergência indisponível (biblioteca `keyboard` "
                "ausente ou bloqueada): %s. Defina enable_hotkey=false para silenciar.",
                exc,
            )
            return False
        try:
            keyboard.add_hotkey(self.hotkey, lambda: self.engage(f"atalho global {self.hotkey}"))
        except Exception as exc:  # noqa: BLE001 - pode exigir permissões de admin
            log.warning("não consegui registrar o atalho %s: %s", self.hotkey, exc)
            return False
        self._hotkey_started = True
        log.warning(
            "atalho global %s registrado (a biblioteca keyboard pode exigir "
            "permissões de administrador no Windows)",
            self.hotkey,
        )
        return True
