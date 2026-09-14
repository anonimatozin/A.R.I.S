"""Neural Core do A.R.I.S.

Orquestrador dos subsistemas cognitivos:

    entrada → evento → atenção → working/estado → roteador
           → decisão → security gate → ação → feedback → aprendizado

O ``NeuralCore`` NÃO substitui o ``Aris``: é uma camada que torna o
pipeline explícito e testável enquanto mantém o comportamento atual
(handlers, registry, LLM, voz, scheduler).

Duas portas de entrada:
    - ``process(query)``        : pipeline completo determinístico.
    - ``execute(decision)``     : executa uma decisão (inclusive as
                                  vindas do LLM) e captura feedback.
"""

from __future__ import annotations

from typing import Any

from core.neural.actions.action_engine import ActionEngine, ActionResult
from core.neural.attention.attention_engine import AttentionEngine, AttentionScore
from core.neural.context.context_engine import ContextBundle, ContextEngine
from core.neural.decision.decision_engine import Decision, DecisionEngine
from core.neural.event_bus import EventBus
from core.neural.events import (
    EVENT_DECISION_APPROVED,
    EVENT_USER_MESSAGE,
    Event,
)
from core.neural.feedback.feedback_engine import FeedbackEngine
from core.neural.learning.experience import ExperienceStore
from core.neural.memory.system import MemorySystem
from core.neural.memory.working_memory import WorkingMemory
from core.neural.planning.planner import Planner
from core.neural.reasoning.reasoning_router import ReasoningRouter
from core.neural.security.security_gate import GateOutcome, SecurityGate
from core.neural.state import GlobalState
from core.neural.workspace import CognitiveWorkspace, WorkspaceSnapshot
from core.neural.world_model import WorldModel
from utils.logger import Logger as ArisLogger


class NeuralCore:
    """Núcleo cognitivo do A.R.I.S."""

    def __init__(
        self,
        event_bus: EventBus,
        state: GlobalState,
        working: WorkingMemory,
        memory: MemorySystem,
        context: ContextEngine,
        attention: AttentionEngine,
        reasoning: ReasoningRouter,
        decision: DecisionEngine,
        security: SecurityGate,
        action: ActionEngine,
        feedback: FeedbackEngine,
        learning: ExperienceStore,
        planner: Planner,
        workspace: CognitiveWorkspace | None = None,
        logger: ArisLogger | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.state = state
        self.working = working
        self.memory = memory
        self.context = context
        self.attention = attention
        self.reasoning = reasoning
        self.decision = decision
        self.security = security
        self.action = action
        self.feedback = feedback
        self.learning = learning
        self.planner = planner
        self.workspace = workspace
        self._logger = logger
        self._ctx_provider = None

    def set_handler_context(self, provider) -> None:
        """Define um provedor de contexto de handler.

        O ARIS injeta ``_build_handler_context`` para que os handlers
        recebam suas instâncias (analyzer, scheduler, etc.) tanto no
        caminho determinístico quanto no caminho LLM.
        """
        self._ctx_provider = provider

    # ── Construção / fábrica ─────────────────────────────────

    @classmethod
    def build(
        cls,
        command_registry=None,
        memory_manager=None,
        logger: ArisLogger | None = None,
    ) -> NeuralCore:
        """Constrói o Neural Core completo sobre o ARIS atual.

        Usa as instâncias reais de ``CommandRegistry`` e
        ``MemoryManager`` para preservar o comportamento.
        """
        from core.memory_db import MemoryDB

        bus = EventBus(logger=logger)
        state = GlobalState()
        memory = MemorySystem.build(memory_manager, logger=logger)
        attention = AttentionEngine.with_defaults(logger=logger)
        reasoning = ReasoningRouter(command_registry=command_registry, logger=logger)
        decision = DecisionEngine(logger=logger)
        security = SecurityGate(command_registry=command_registry, logger=logger)
        action = ActionEngine(command_registry=command_registry, logger=logger)
        working = memory.working
        context = ContextEngine(state, working, memory, logger=logger)
        feedback = FeedbackEngine(working, memory, state, logger=logger)
        learning = ExperienceStore(logger=logger)
        planner = Planner(command_registry=command_registry, logger=logger)
        world_model = WorldModel(db=MemoryDB(), logger=logger)
        workspace = CognitiveWorkspace(
            state=state,
            working=working,
            attention=attention,
            world_model=world_model,
            logger=logger,
        )

        return cls(
            event_bus=bus,
            state=state,
            working=working,
            memory=memory,
            context=context,
            attention=attention,
            reasoning=reasoning,
            decision=decision,
            security=security,
            action=action,
            feedback=feedback,
            learning=learning,
            planner=planner,
            workspace=workspace,
            logger=logger,
        )

    def register_services(self, container) -> None:
        """Publica os serviços do Neural Core no container."""
        container.set("neural.event_bus", self.event_bus)
        container.set("neural.state", self.state)
        container.set("neural.working_memory", self.working)
        container.set("neural.memory", self.memory)
        container.set("neural.context", self.context)
        container.set("neural.attention", self.attention)
        container.set("neural.reasoning", self.reasoning)
        container.set("neural.decision", self.decision)
        container.set("neural.security", self.security)
        container.set("neural.action", self.action)
        container.set("neural.feedback", self.feedback)
        container.set("neural.learning", self.learning)
        container.set("neural.planner", self.planner)
        container.set("neural.workspace", self.workspace)
        if self.workspace and self.workspace._world:
            container.set("neural.world_model", self.workspace._world)

    # ── Ciclo de processamento ───────────────────────────────

    def _make_event(self, query: str) -> Event:
        return Event(
            event_type=EVENT_USER_MESSAGE,
            source="neural_core",
            payload={"query": query, "text": query},
            priority=80,
            confidence=1.0,
        )

    def _attention_score(self, event: Event) -> AttentionScore:
        score = self.attention.should_process(event)
        if self._logger:
            self._logger.debug(
                f"NeuralCore: atenção {event.event_type} = {score.score:.2f}"
            )
        return score

    def process(self, query: str) -> ActionResult | None:
        """Pipeline completo para consultas do operador.

        Returns:
            ``ActionResult`` se a consulta foi executada de forma
            determinística, ou ``None`` quando a consulta requer LLM
            (o Aris mantém o fluxo atual nesse caso).
        """
        # 1. Evento de entrada
        event = self._make_event(query)
        self.state.register_event(event)
        self.event_bus.publish(event)

        # 2. Atenção
        if not self._attention_score(event).should_process():
            return None

        # 3. Estado / working memory
        self.state.set_goal(query)
        self.working.start_task(goal=query, intent=query)

        # 4. Roteamento de raciocínio
        routing = self.reasoning.route(query, event)
        if routing.needs_llm:
            # 4b. Tentar Planner antes de cair no LLM
            if self.planner.can_plan(query):
                plan = self.planner.build(query)
                if plan.steps:
                    first = plan.next_step()
                    if first:
                        decision = self.decision.decide(
                            first.to_intent(),
                            goal=self.state.current_goal,
                            context=self.context.build(query, events=self.state.recent_events(5)),
                            source="planner",
                        )
                        return self.execute(decision)
            return None  # o Aris seguirá com o fluxo LLM atual

        # 5. Decisão
        decision = self.decision.decide(
            routing.intents[0],
            goal=self.state.current_goal,
            context=self.context.build(query, events=self.state.recent_events(5)),
            source="deterministic",
        )

        # 6. Execução (com security gate)
        return self.execute(decision)

    def execute(self, decision: Decision, ctx: dict[str, Any] | None = None) -> ActionResult:
        """Executa uma decisão aprovada pelo Security Gate.

        Define o caminho padrão tanto para decisões determinísticas
        quanto para decisões derivadas do LLM. ``ctx`` é o contexto
        de handler do ARIS (``_build_handler_context``) — opcional;
        se ausente, usa o provedor registrado via
        ``set_handler_context``.
        """
        if ctx is None and self._ctx_provider is not None:
            try:
                ctx = self._ctx_provider()
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"NeuralCore: falha ao montar ctx de handler ({e})")

        gate = self.security.approve(decision)
        decision_event = Event(
            event_type=EVENT_DECISION_APPROVED,
            source="security_gate",
            payload={
                "module": decision.module,
                "action": decision.action,
                "outcome": gate.outcome.value,
            },
            priority=50,
            confidence=decision.confidence,
        )
        self.state.register_event(decision_event)
        self.event_bus.publish(decision_event)

        if gate.outcome == GateOutcome.DENIED:
            return ActionResult(
                success=False,
                error=f"Segurança: {gate.reason}",
                module=decision.module,
                action=decision.action,
            )

        if gate.outcome == GateOutcome.REQUIRES_CONFIRMATION:
            # Confirmações críticas permanecem no CommandRegistry
            # (mecanismo de token + senha já existente).
            confirmation = Decision(
                module=decision.module,
                action=decision.action,
                parameters=decision.parameters,
                confidence=decision.confidence,
                risk=decision.risk,
                source=decision.source,
            )
            result = self.action.execute(confirmation, ctx)
        else:
            result = self.action.execute(decision, ctx)

        # 7. Feedback → aprendizado
        report = self.feedback.process(decision, result)
        self.learning.record(report)
        self._close_goal(result)

        return result

    def _close_goal(self, result: ActionResult) -> None:
        # FeedbackEngine já arquivou resultado/status na working memory.
        if result.success:
            self.state.clear_goal(reason="concluído")

    # ── Utilidades ───────────────────────────────────────────

    def get_context(self) -> ContextBundle:
        """Contexto atual (para diagnóstico/logs)."""
        return self.context.build(events=self.state.recent_events(5))

    def build_workspace(self, events: list[Event] | None = None) -> WorkspaceSnapshot:
        """Constrói um snapshot do workspace cognitivo sob demanda."""
        if self.workspace is None:
            return WorkspaceSnapshot()
        return self.workspace.build(events=events)

    def get_stats(self) -> dict[str, Any]:
        """Visão geral do estado do Neural Core."""
        wm_stats: dict[str, Any] = {}
        if self.workspace and self.workspace._world:
            wm = self.workspace._world
            wm_stats = {
                "active_goals": len(wm.get_active_goals()),
                "overdue_goals": len(wm.get_overdue_goals()),
                "due_reminders": len(wm.get_due_reminders()),
                "profile_keys": len(wm.get_user_profile()),
            }
        return {
            "state": self.state.snapshot(),
            "attention": self.attention.get_weights(),
            "decision": self.decision.get_stats(),
            "security": self.security.get_stats(),
            "action": self.action.get_stats(),
            "feedback": self.feedback.get_stats(),
            "learning": self.learning.to_dict(),
            "planner": self.planner.get_stats(),
            "memory": self.memory.snapshot(),
            "context": self.context.get_stats(),
            "reasoning": self.reasoning.get_stats(),
            "workspace": self.build_workspace().to_dict(),
            "world_model": wm_stats,
        }
