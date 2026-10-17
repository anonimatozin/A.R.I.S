"""Proactive Engine — ARIS comenta coisas sozinha ocasionalmente.

Conecta Vision Engine + WorldModel (Goals/Reminders) + Continuous Voice
para gerar comentários proativos sem esperar ser provocada.

Não cria mecanismo novo de proatividade — usa o que já existe:
- VisionEngine events (screen analyzed, errors detected, text detected)
- WorldModel (goals, reminders, follow-ups)
- ContinuousVoiceSensor (difficulty markers)
- Neural Core Event Bus + Attention Engine
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from core.neural.events import (
    Event,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    PRIORITY_HIGH,
)
from core.neural.world_model import WorldModel, EVENT_FOLLOWUP_SUGGESTION
from utils.logger import Logger


class ProactiveEngine:
    """Motor de proatividade do A.R.I.S.

    Executa em background (daemon thread). Periodicamente verifica:
    1. Vision Engine: erros na tela, apps novos, mudanças significativas
    2. WorldModel: goals atrasados, reminders vencidos, follow-ups
    3. Continuous Voice: marcadores de dificuldade (já emite eventos)
    4. Companion mode: comentários estilo JARVIS/FRIDAY (hora, dia, observações)

    Quando detecta algo relevante, emite evento EVENT_FOLLOWUP_SUGGESTION
    no Event Bus para o Neural Core processar e gerar comentário falável.
    """

    def __init__(
        self,
        event_bus: Any,
        world_model: WorldModel,
        vision_engine: Any = None,
        continuous_voice: Any = None,
        logger: Optional[Logger] = None,
        interval_seconds: float = 180.0,  # 3 minutos
        min_interval_seconds: float = 120.0,  # mínimo 2 min entre comentários
        companion_enabled: bool = True,  # novo: modo companhia JARVIS/FRIDAY
        companion_interval_seconds: float = 900.0,  # 15 min entre comentários de companhia
    ) -> None:
        self._event_bus = event_bus
        self._world_model = world_model
        self._vision = vision_engine
        self._continuous_voice = continuous_voice
        self._logger = logger
        self._interval = max(30.0, interval_seconds)
        self._min_interval = max(30.0, min_interval_seconds)
        self._companion_enabled = companion_enabled
        self._companion_interval = max(300.0, companion_interval_seconds)  # mínimo 5 min
        self._last_companion_time: float = 0.0

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_proactive_time: float = 0.0
        self._last_vision_check: float = 0.0
        self._last_world_check: float = 0.0

        # Templates de comentários proativos (funcionais)
        self._vision_comment_templates = [
            "Percebi algo na sua tela: {detail}. Quer que eu analise?",
            "Detectei {detail} na tela. Posso ajudar com isso?",
            "Notei {detail}. Quer mais detalhes?",
        ]

        self._goal_comment_templates = [
            "Lembrete: o objetivo '{goal}' está {days} dia(s) atrasado. Quer atualizar?",
            "O objetivo '{goal}' passou do prazo em {date}. O que devemos fazer?",
            "Meta pendente: '{goal}' (prazo: {date}). Continuamos?",
        ]

        self._reminder_comment_templates = [
            "Hora do lembrete: '{text}'. Agendado para {time}.",
            "Lembrete disparado: '{text}'.",
        ]

        self._system_comment_templates = [
            "Sistema: {detail}. Tudo bem por aqui?",
            "Notei {detail}. Precisa de alguma ação?",
        ]

        # Templates de companhia (estilo JARVIS/FRIDAY) — frequência controlada
        self._companion_greeting_templates = [
            "Bom dia, senhor. Como posso ajudar hoje?",
            "Boa tarde. Tudo correndo bem por aqui?",
            "Boa noite. Precisa de algo antes de encerrar?",
        ]

        self._companion_checkin_templates = [
            "Como foi seu dia até agora?",
            "Tudo tranquilo por aí?",
            "Precisa de uma pausa? Posso tocar algo relaxante.",
            "O café já acabou? ☕",
        ]

        self._companion_observation_templates = [
            "Notei que você está focado há um tempo. Quer que eu monitore algo?",
            "Sistema rodando liso. Alguma tarefa nova?",
            "Estou aqui se precisar de qualquer coisa.",
        ]

        self._companion_time_templates = {
            "morning": [
                "Bom dia. Dormiu bem?",
                "Manhã produtiva pela frente?",
            ],
            "afternoon": [
                "Boa tarde. Como anda a produtividade?",
                "Metade do dia passou. Tudo nos conformes?",
            ],
            "evening": [
                "Boa noite. Dia longo?",
                "Finalizando algo ou hora de relaxar?",
            ],
        }

    def start(self) -> None:
        """Inicia o motor proativo em daemon thread."""
        if self._running:
            return

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name="proactive-engine",
            daemon=True,
        )
        self._thread.start()

        if self._logger:
            self._logger.info(f"Proactive Engine iniciado (intervalo: {self._interval}s)")

    def stop(self) -> None:
        """Para o motor proativo de forma controlada."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        if self._logger:
            self._logger.info("Proactive Engine parado")

    def _loop(self) -> None:
        """Loop principal do motor proativo."""
        while self._running and not self._stop_event.is_set():
            try:
                now = time.time()

                # Modo foco / não-perturbe: silencia proatividade (extras20 #2/#18)
                try:
                    from modules.extras20 import should_stay_quiet
                    if should_stay_quiet():
                        self._stop_event.wait(60.0)
                        continue
                except Exception:
                    pass

                # Alerta de anomalia de sistema (extras20 #11, reaproveita este loop)
                try:
                    from modules.extras20 import system_anomaly_check
                    alert = system_anomaly_check()
                    if alert and now - self._last_proactive_time >= self._min_interval:
                        self._emit_proactive(trigger="system_anomaly", detail=alert,
                                             templates=["{detail}"], priority=PRIORITY_HIGH,
                                             confidence=0.9)
                except Exception:
                    pass

                # Respeitar intervalo mínimo entre comentários proativos
                if now - self._last_proactive_time < self._min_interval:
                    self._stop_event.wait(30.0)
                    continue

                # Verificar Vision Engine (a cada intervalo)
                if now - self._last_vision_check >= self._interval:
                    self._check_vision()
                    self._last_vision_check = now

                # Verificar WorldModel (goals/reminders) - mais frequente
                if now - self._last_world_check >= 60.0:  # a cada minuto
                    self._check_world_model()
                    self._last_world_check = now

                # Companion mode: comentários estilo JARVIS/FRIDAY (menos frequente)
                if self._companion_enabled and now - self._last_companion_time >= self._companion_interval:
                    self._check_companion(now)
                    self._last_companion_time = now

            except Exception as e:
                if self._logger:
                    self._logger.warning(f"Proactive Engine erro no loop: {e}")

            # Aguardar próximo ciclo
            self._stop_event.wait(30.0)

    def _check_vision(self) -> None:
        """Verifica Vision Engine por coisas interessantes na tela."""
        if not self._vision:
            return

        try:
            # Verificar erros detectados na tela
            errors = self._vision.detect_errors()
            if errors:
                for error in errors[:2]:  # máx 2 por ciclo
                    self._emit_proactive(
                        trigger="vision_error",
                        detail=f"possível erro '{error}' na tela",
                        templates=self._vision_comment_templates,
                        priority=PRIORITY_NORMAL,
                        confidence=0.7,
                    )

            # Verificar aplicativo ativo (mudança de contexto)
            # O VisionEngine já emite EVENT_VISION_APPLICATION_DETECTED
            # mas podemos fazer check ativo ocasionalmente
            if self._vision._config.vlm_enabled and self._vision._vlm.available:
                status = self._vision.get_status()
                if status.get("screen", {}).get("available"):
                    # Opcional: capturar e analisar se mudou muito
                    pass

        except Exception as e:
            if self._logger:
                self._logger.debug(f"Proactive vision check erro: {e}")

    def _check_world_model(self) -> None:
        """Verifica WorldModel por goals/reminders que precisam atenção."""
        try:
            # Goals atrasados
            overdue = self._world_model.get_overdue_goals()
            for goal in overdue[:1]:  # máx 1 por ciclo
                try:
                    dl = datetime.fromisoformat(goal.deadline)
                    days = (datetime.now() - dl).days
                    self._emit_proactive(
                        trigger="overdue_goal",
                        detail=f"meta '{goal.description}' {days} dia(s) atrasada",
                        templates=self._goal_comment_templates,
                        priority=PRIORITY_HIGH,
                        confidence=0.8,
                        extra={"goal": goal.to_dict()},
                    )
                except (ValueError, TypeError):
                    pass

            # Reminders vencidos
            due_reminders = self._world_model.get_due_reminders()
            for rem in due_reminders[:1]:  # máx 1 por ciclo
                self._emit_proactive(
                    trigger="due_reminder",
                    detail=f"lembrete '{rem.text}'",
                    templates=self._reminder_comment_templates,
                    priority=PRIORITY_HIGH,
                    confidence=0.9,
                    extra={"reminder": rem.to_dict()},
                )

            # Follow-ups automáticos
            followups = self._world_model.check_follow_ups()
            for suggestion in followups[:1]:  # máx 1 por ciclo
                self._emit_proactive(
                    trigger="followup",
                    detail=suggestion,
                    templates=[],  # usar texto direto
                    priority=PRIORITY_NORMAL,
                    confidence=0.75,
                    use_direct_text=True,
                )

        except Exception as e:
            if self._logger:
                self._logger.debug(f"Proactive world model check erro: {e}")

    def _check_companion(self, now: float) -> None:
        """Comentários estilo JARVIS/FRIDAY: saudação por horário, check-in, observações."""
        import random
        from datetime import datetime
        
        hour = datetime.fromtimestamp(now).hour
        
        # Determinar período do dia
        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 18:
            period = "afternoon"
        else:
            period = "evening"
        
        # Escolher tipo de comentário aleatoriamente
        comment_type = random.choice(["time", "checkin", "observation", "greeting"])
        
        if comment_type == "time" and period in self._companion_time_templates:
            templates = self._companion_time_templates[period]
        elif comment_type == "checkin":
            templates = self._companion_checkin_templates
        elif comment_type == "observation":
            templates = self._companion_observation_templates
        else:  # greeting
            templates = self._companion_greeting_templates
        
        if templates:
            self._emit_proactive(
                trigger=f"companion_{comment_type}",
                detail=random.choice(templates),
                templates=[],  # usar texto direto
                priority=PRIORITY_LOW,
                confidence=0.6,
                use_direct_text=True,
            )

    def _emit_proactive(
        self,
        trigger: str,
        detail: str,
        templates: list[str],
        priority: int,
        confidence: float,
        extra: dict[str, Any] | None = None,
        use_direct_text: bool = False,
    ) -> None:
        """Emite evento proativo no Event Bus."""
        now = time.time()
        if now - self._last_proactive_time < self._min_interval:
            return

        # Gerar texto do comentário
        if use_direct_text:
            comment = detail
        elif templates:
            template = random.choice(templates)
            comment = template.format(detail=detail)
        else:
            comment = detail

        # Adicionar variáveis extras se houver
        if extra:
            for key, value in extra.items():
                if isinstance(value, dict):
                    for k, v in value.items():
                        comment = comment.replace(f"{{{k}}}", str(v))
                else:
                    comment = comment.replace(f"{{{key}}}", str(value))

        if self._logger:
            self._logger.info(f"Proativo [{trigger}]: {comment[:80]}")

        # Emitir evento no Event Bus
        if self._event_bus:
            try:
                event = Event(
                    event_type=EVENT_FOLLOWUP_SUGGESTION,
                    source="proactive_engine",
                    payload={
                        "trigger": trigger,
                        "comment": comment,
                        "detail": detail,
                        "extra": extra or {},
                    },
                    priority=priority,
                    confidence=confidence,
                )
                self._event_bus.publish(event)
                self._last_proactive_time = now
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"Proactive emit erro: {e}")

    def trigger_now(self, trigger: str, comment: str, priority: int = PRIORITY_NORMAL) -> None:
        """Dispara um comentário proativo imediato (para uso externo)."""
        now = time.time()
        if now - self._last_proactive_time < self._min_interval:
            return

        if self._event_bus:
            try:
                event = Event(
                    event_type=EVENT_FOLLOWUP_SUGGESTION,
                    source="proactive_engine",
                    payload={
                        "trigger": trigger,
                        "comment": comment,
                        "detail": comment,
                    },
                    priority=priority,
                    confidence=0.9,
                )
                self._event_bus.publish(event)
                self._last_proactive_time = now
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"Proactive trigger_now erro: {e}")

    def snapshot(self) -> dict[str, Any]:
        """Estado atual do motor proativo."""
        return {
            "running": self._running,
            "interval_seconds": self._interval,
            "min_interval_seconds": self._min_interval,
            "last_proactive_ago": time.time() - self._last_proactive_time if self._last_proactive_time else None,
            "vision_available": self._vision is not None,
            "world_model_available": self._world_model is not None,
        }


def build_proactive_engine(
    aris_instance,
    interval_seconds: float = 180.0,
    min_interval_seconds: float = 120.0,
    companion_enabled: bool = True,
    companion_interval_seconds: float = 900.0,
) -> Optional[ProactiveEngine]:
    """Constrói o ProactiveEngine integrado ao Aris."""
    from utils.logger import Logger

    logger = Logger(name="proactive", log_dir="logs", level="INFO")

    engine = ProactiveEngine(
        event_bus=aris_instance._neural.event_bus if hasattr(aris_instance, "_neural") else None,
        world_model=aris_instance._neural.workspace._world if (
            hasattr(aris_instance, "_neural") and
            aris_instance._neural.workspace and
            aris_instance._neural.workspace._world
        ) else None,
        vision_engine=aris_instance._vision if hasattr(aris_instance, "_vision") else None,
        continuous_voice=aris_instance._continuous_voice if hasattr(aris_instance, "_continuous_voice") else None,
        logger=logger,
        interval_seconds=interval_seconds,
        min_interval_seconds=min_interval_seconds,
        companion_enabled=companion_enabled,
        companion_interval_seconds=companion_interval_seconds,
    )

    return engine