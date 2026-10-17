"""Eventos do agente → falas curtas da voz (Parte 8).

Transforma ``AgentEvent`` em frases como "pesquisando...", sem repetir a
mesma frase em sequência. Só ``tool_call`` vira fala: plano, resultado e
resposta final são tratados pelo chamador.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger("aris.agent.bridge.eventos")

# Nome da ferramenta → fala curta (pt-BR, sem pontuação final pesada).
FRASES_DE_FERRAMENTA = {
    "web_search": "pesquisando na web...",
    "web_fetch": "lendo a página...",
    "web_extract_links": "pegando os links da página...",
    "web_download": "baixando o arquivo...",
    "browser_open": "abrindo o navegador...",
    "browser_click": "clicando na página...",
    "browser_type": "digitando na página...",
    "browser_press": "apertando tecla...",
    "browser_snapshot": "olhando a página...",
    "browser_screenshot": "tirando um print...",
    "browser_close": "fechando o navegador...",
    "pc_list_dir": "listando os arquivos...",
    "pc_read_file": "lendo o arquivo...",
    "pc_write_file": "escrevendo o arquivo...",
    "pc_move_file": "movendo o arquivo...",
    "pc_delete_file": "apagando o arquivo...",
    "pc_search_files": "procurando arquivos...",
    "pc_run_command": "rodando o comando...",
    "pc_python_run": "rodando o código...",
    "pc_system_info": "olhando o status do sistema...",
    "pc_list_processes": "vendo os processos...",
    "pc_list_windows": "vendo as janelas...",
    "pc_focus_window": "focando a janela...",
    "pc_open_app": "abrindo o aplicativo...",
    "pc_screenshot": "olhando a tela...",
    "pc_clipboard_get": "lendo a área de transferência...",
    "pc_clipboard_set": "copiando para a área de transferência...",
    "memory_remember": "guardando na memória...",
    "memory_recall": "buscando na memória...",
    "memory_forget": "apagando da memória...",
    "skill_load": "carregando a skill...",
    "skill_read_resource": "lendo o recurso da skill...",
    "calc": "calculando...",
}


class FaladorDeEventos:
    """``EventSink``: fala o status de cada ferramenta, sem repetir em sequência."""

    def __init__(self, falar: Callable[..., None], *, logger=None) -> None:
        self._falar = falar
        self._log = logger or log
        self._ultima: str | None = None
        self.total_falado = 0

    def reset(self) -> None:
        """Esquece a última frase (chamado a cada novo pedido do usuário)."""
        self._ultima = None

    def __call__(self, evento) -> None:
        """Recebe um ``AgentEvent``; fala só para ``tool_call`` conhecida."""
        try:
            if getattr(evento, "type", "") != "tool_call":
                return
            nome = str((evento.data or {}).get("name") or "")
            frase = FRASES_DE_FERRAMENTA.get(nome)
            if not frase or frase == self._ultima:
                return  # desconhecida: silêncio; repetida: não enche o ouvido
            self._ultima = frase
            self._falar(frase)
            self.total_falado += 1
        except Exception as exc:  # noqa: BLE001 - evento nunca derruba a tarefa
            self._log.warning("fala de evento falhou: %s", exc)
