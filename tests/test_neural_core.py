"""Testes do Neural Core do A.R.I.S.

Cobre Event, EventBus, Attention, WorkingMemory, Memória (episódica/
procedural/persistência), Context, Reasoning Router, Decision,
Security Gate, Action, Feedback, Experience Store, Planner e a
integração via NeuralCore.
"""

import pytest

from core.commands import CommandRegistry
from core.memory import MemoryManager
from core.neural.actions.action_engine import ActionEngine, ActionResult
from core.neural.attention.attention_engine import AttentionEngine
from core.neural.context.context_engine import ContextEngine
from core.neural.core import NeuralCore
from core.neural.decision.decision_engine import Decision, DecisionEngine
from core.neural.event_bus import EventBus
from core.neural.events import (
    EVENT_SYSTEM_ALERT,
    EVENT_USER_MESSAGE,
    EVENT_VOICE_COMMAND,
    Event,
)
from core.neural.feedback.feedback_engine import FeedbackEngine
from core.neural.learning.experience import ExperienceStore
from core.neural.memory.system import (
    EpisodicMemory,
    Experience,
    MemorySystem,
    ProceduralMemory,
    Procedure,
)
from core.neural.memory.working_memory import WorkingMemory
from core.neural.planning.planner import Plan, Planner
from core.neural.reasoning.reasoning_router import (
    DeterministicEngine,
    ReasoningMode,
    ReasoningRouter,
)
from core.neural.security.security_gate import GateOutcome, SecurityGate
from core.neural.state import GlobalState
from utils.logger import Logger

# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def logger(tmp_path):
    return Logger(name="test-neural", level="CRITICAL")


@pytest.fixture
def memory_manager(tmp_path, logger):
    return MemoryManager(logger=logger, memory_root=tmp_path / "memory")


@pytest.fixture
def registry():
    reg = CommandRegistry()

    @reg.register_intent("sys", "sistema")
    def _sys(action, params, **ctx):
        return "CPU 10% | RAM 20%"

    @reg.register_intent("weather", "clima")
    def _weather(action, params, **ctx):
        return "Sol, 25C"

    return reg


@pytest.fixture
def neural(memory_manager, registry, logger):
    return NeuralCore.build(
        command_registry=registry,
        memory_manager=memory_manager,
        logger=logger,
    )


# ── Event ───────────────────────────────────────────────────

class TestEvent:
    def test_defaults(self):
        e = Event(event_type=EVENT_USER_MESSAGE, source="test")
        assert e.event_id
        assert e.timestamp
        assert e.confidence == 1.0
        assert e.priority == 50

    def test_text_from_payload(self):
        e = Event(event_type=EVENT_USER_MESSAGE, source="test",
                  payload={"text": "olá"})
        assert e.text == "olá"

    def test_to_dict(self):
        e = Event(event_type=EVENT_SYSTEM_ALERT, source="test")
        d = e.to_dict()
        assert d["event_type"] == "system_alert"
        assert d["event_id"] == e.event_id


# ── EventBus ────────────────────────────────────────────────

class TestEventBus:
    def test_publish_delivers(self):
        bus = EventBus()
        got = []
        bus.subscribe("x", lambda e: got.append(e))
        bus.publish(Event(event_type="x", source="s"))
        assert len(got) == 1

    def test_wildcard(self):
        bus = EventBus()
        got = []
        bus.subscribe("*", lambda e: got.append(e.event_type))
        bus.publish(Event(event_type="a", source="s"))
        bus.publish(Event(event_type="b", source="s"))
        assert got == ["a", "b"]

    def test_handler_error_does_not_break(self):
        bus = EventBus()
        def boom(e):
            raise RuntimeError("x")
        bus.subscribe("x", boom)
        bus.subscribe("x", lambda e: results.append(True))
        results = []
        bus.publish(Event(event_type="x", source="s"))
        assert results == [True]
        assert bus.get_stats()["errors"] == 1

    def test_unsubscribe(self):
        bus = EventBus()
        def h(e):
            pass
        bus.subscribe("x", h)
        assert bus.subscriber_count("x") == 1
        assert bus.unsubscribe("x", h)
        assert bus.subscriber_count("x") == 0


# ── Attention ───────────────────────────────────────────────

class TestAttention:
    def test_voice_command_high_score(self):
        attn = AttentionEngine.with_defaults()
        score = attn.score(Event(event_type=EVENT_VOICE_COMMAND, source="t",
                                 priority=100, confidence=1.0))
        assert score.score >= 0.8
        assert score.should_process()

    def test_low_priority_background(self):
        attn = AttentionEngine.with_defaults()
        score = attn.score(Event(event_type="screen_changed", source="t",
                                 priority=10, confidence=0.2))
        assert not score.should_process(threshold=0.3)


# ── Working Memory ──────────────────────────────────────────

class TestWorkingMemory:
    def test_start_task(self):
        wm = WorkingMemory()
        wm.start_task(goal="monitorar", intent="sys")
        assert wm.current().goal == "monitorar"
        assert wm.current().status == "pending"

    def test_complete_task(self):
        wm = WorkingMemory()
        wm.start_task(goal="g")
        wm.complete_current_task(result="ok", success=True)
        assert wm.current().status == "success"

    def test_notes(self):
        wm = WorkingMemory()
        wm.remember("k", "v")
        assert wm.recall("k") == "v"

    def test_history(self):
        wm = WorkingMemory()
        wm.start_task(goal="a")
        wm.complete_current_task()
        wm.start_task(goal="b")
        hist = wm.history()
        assert hist[0]["goal"] == "a"


# ── Memória Episódica / Procedural / Persistência ───────────

class TestEpisodicMemory:
    def test_record_relevant(self, tmp_path, logger):
        ep = EpisodicMemory(memory_root=tmp_path, logger=logger)
        assert ep.record(Experience(event="sys falhou", success=False,
                                    importance=0.8)) is not None
        assert ep.total() == 1

    def test_record_below_floor_ignored(self, tmp_path, logger):
        ep = EpisodicMemory(memory_root=tmp_path, logger=logger)
        assert ep.record(Experience(event="nada", importance=0.1)) is None
        assert ep.total() == 0

    def test_persistence_across_instances(self, tmp_path, logger):
        ep1 = EpisodicMemory(memory_root=tmp_path, logger=logger)
        ep1.record(Experience(event="x", success=True))
        ep2 = EpisodicMemory(memory_root=tmp_path, logger=logger)
        assert ep2.total() == 1


class TestProceduralMemory:
    def test_save_and_get(self, tmp_path, logger):
        pm = ProceduralMemory(memory_root=tmp_path, logger=logger)
        pm.save_procedure(Procedure(name="abrir chrome", steps=["chrome"]))
        assert pm.has("abrir chrome")
        assert pm.get("abrir chrome")["name"] == "abrir chrome"

    def test_persistence_across_instances(self, tmp_path, logger):
        pm1 = ProceduralMemory(memory_root=tmp_path, logger=logger)
        pm1.save_procedure(Procedure(name="p1", steps=["s"]))
        pm2 = ProceduralMemory(memory_root=tmp_path, logger=logger)
        assert pm2.total() == 1
        assert pm2.delete("p1") and pm2.total() == 0


class TestMemorySystem:
    def test_build_and_snapshot(self, memory_manager, logger, tmp_path):
        system = MemorySystem.build(memory_manager, logger=logger,
                                    memory_root=tmp_path)
        snap = system.snapshot()
        assert "episodic_total" in snap
        assert "procedural_total" in snap


# ── Context Engine ──────────────────────────────────────────

class TestContextEngine:
    def test_build(self, memory_manager, logger, tmp_path):
        memory = MemorySystem.build(memory_manager, logger=logger,
                                    memory_root=tmp_path)
        state = GlobalState()
        ctx = ContextEngine(state, memory.working, memory, logger=logger)
        bundle = ctx.build("qual uso da cpu")
        assert bundle.user_input == "qual uso da cpu"
        assert bundle.to_prompt_str()


# ── Reasoning Router ────────────────────────────────────────

class TestReasoningRouter:
    def test_deterministic_sys(self, logger):
        router = ReasoningRouter(logger=logger)
        d = router.route("qual uso da cpu")
        assert d.mode == ReasoningMode.DETERMINISTIC
        assert d.intents[0].module == "sys"

    def test_direct_command(self, registry, logger):
        router = ReasoningRouter(command_registry=registry, logger=logger)
        d = router.route("weather")
        assert d.mode == ReasoningMode.DETERMINISTIC

    def test_unknown_goes_llm(self, logger):
        router = ReasoningRouter(logger=logger)
        d = router.route("explique por que meu pc está lento")
        assert d.needs_llm

    def test_deterministic_engine_injection_blocked(self, logger):
        engine = DeterministicEngine(logger=logger)
        assert not engine.can_handle("__import__('os').system('x')")


# ── Decision Engine ─────────────────────────────────────────

class TestDecisionEngine:
    def test_decide_desktop(self):
        eng = DecisionEngine()
        from core.advanced_interpreter import Intent
        d = eng.decide(Intent(module="desktop", action="open_app",
                              params={"app": "chrome"}))
        assert d.risk == 2
        assert d.module == "desktop"

    def test_decide_exit_critical(self):
        eng = DecisionEngine()
        from core.advanced_interpreter import Intent
        d = eng.decide(Intent(module="exit", action="execute", params={}))
        assert d.risk >= 4


# ── Security Gate ───────────────────────────────────────────

class TestSecurityGate:
    def test_unknown_capability_denied(self, logger, registry):
        gate = SecurityGate(command_registry=registry, logger=logger)
        result = gate.approve(Decision(module="hacker_module", action="x"))
        assert result.outcome == GateOutcome.DENIED

    def test_sys_approved(self, logger, registry):
        gate = SecurityGate(command_registry=registry, logger=logger)
        result = gate.approve(Decision(module="sys", action="analyze",
                                       risk=1, source="deterministic"))
        assert result.outcome == GateOutcome.APPROVED

    def test_exit_always_allowed(self, logger, registry):
        gate = SecurityGate(command_registry=registry, logger=logger)
        result = gate.approve(Decision(module="exit", action="execute",
                                       risk=4))
        assert result.outcome == GateOutcome.APPROVED

    def test_critical_requires_confirmation(self, logger, registry):
        gate = SecurityGate(command_registry=registry, logger=logger)
        result = gate.approve(Decision(module="sys", action="format",
                                       risk=4))
        assert result.outcome == GateOutcome.REQUIRES_CONFIRMATION

    def test_oversized_param_denied(self, logger, registry):
        gate = SecurityGate(command_registry=registry, logger=logger)
        result = gate.approve(Decision(module="sys", action="x",
                                       parameters={"p": "a" * 5000}))
        assert result.outcome == GateOutcome.DENIED


# ── Action Engine ───────────────────────────────────────────

class TestActionEngine:
    def test_execute_ok(self, registry, logger):
        eng = ActionEngine(command_registry=registry, logger=logger)
        result = eng.execute(Decision(module="sys", action="analyze",
                                      risk=1, source="test"))
        assert isinstance(result, ActionResult)
        assert result.success

    def test_execute_unknown(self, registry, logger):
        eng = ActionEngine(command_registry=registry, logger=logger)
        result = eng.execute(Decision(module="nope", action="x"))
        assert not result.success

    def test_capabilities(self, registry, logger):
        eng = ActionEngine(command_registry=registry, logger=logger)
        caps = eng.capabilities()
        assert "sys" in caps and "weather" in caps


# ── Feedback ────────────────────────────────────────────────

class TestFeedbackEngine:
    def test_success_records_episode(self, memory_manager, logger, tmp_path):
        memory = MemorySystem.build(memory_manager, logger=logger,
                                    memory_root=tmp_path)
        state = GlobalState()
        eng = FeedbackEngine(memory.working, memory, state, logger=logger)
        result = ActionResult(success=True, output="ok", module="sys",
                              action="analyze")
        report = eng.process(Decision(module="sys", action="analyze"), result)
        assert report.outcome == "success"
        assert memory.episodic.total() == 1

    def test_failure_tracked_in_state(self, memory_manager, logger, tmp_path):
        memory = MemorySystem.build(memory_manager, logger=logger,
                                    memory_root=tmp_path)
        state = GlobalState()
        eng = FeedbackEngine(memory.working, memory, state, logger=logger)
        result = ActionResult(success=False, error="boom", module="sys",
                              action="analyze")
        eng.process(Decision(module="sys", action="analyze"), result)
        assert state.failure_history


# ── Experience Store ────────────────────────────────────────

class TestExperienceStore:
    def test_record_and_counter(self, tmp_path, logger):
        store = ExperienceStore(logger=logger,
                                file_path=tmp_path / "stats.json")
        from core.neural.events import EVENT_ACTION_COMPLETED
        from core.neural.feedback.feedback_engine import FeedbackReport
        ev = Event(event_type=EVENT_ACTION_COMPLETED, source="nc",
                   payload={"module": "sys", "success": True})
        store.record(FeedbackReport(outcome="success", event=ev))
        assert store.counter()["sys"]["success"] == 1

    def test_concerning_modules(self, tmp_path, logger):
        store = ExperienceStore(logger=logger,
                                file_path=tmp_path / "stats.json")
        from core.neural.events import EVENT_ACTION_COMPLETED
        from core.neural.feedback.feedback_engine import FeedbackReport
        ev = Event(event_type=EVENT_ACTION_COMPLETED, source="nc",
                   payload={"module": "sys", "success": False})
        for _ in range(3):
            store.record(FeedbackReport(outcome="failure", event=ev))
        assert "sys" in store.concerning_modules()

    def test_persistence(self, tmp_path, logger):
        path = tmp_path / "stats.json"
        s1 = ExperienceStore(logger=logger, file_path=path)
        from core.neural.events import EVENT_ACTION_COMPLETED
        from core.neural.feedback.feedback_engine import FeedbackReport
        ev = Event(event_type=EVENT_ACTION_COMPLETED, source="nc",
                   payload={"module": "sys", "success": True})
        s1.record(FeedbackReport(outcome="success", event=ev))
        s2 = ExperienceStore(logger=logger, file_path=path)
        assert s2.counter()["sys"]["success"] == 1


# ── Planner ─────────────────────────────────────────────────

class TestPlanner:
    def test_template_plan(self, registry, logger):
        plan = Planner(command_registry=registry, logger=logger)
        p = plan.build("quero monitorar %cpu")
        assert isinstance(p, Plan)
        assert p.steps and p.steps[0].module == "sys"

    def test_no_plan(self, logger):
        plan = Planner(logger=logger)
        p = plan.build("algo totalmente fora do padrão")
        assert p.steps == []


# ── Integração (NeuralCore) ─────────────────────────────────

class TestNeuralCore:
    def test_deterministic_process(self, neural):
        result = neural.process("qual uso da cpu")
        assert result is not None
        assert result.success

    def test_llm_fallback_process(self, neural):
        result = neural.process("explique por que minha vida é complicada")
        assert result is None

    def test_execute_respects_security(self, neural):
        decision = Decision(module="desconhecido_x", action="y", risk=2)
        result = neural.execute(decision)
        assert not result.success
        assert "Segurança" in result.error

    def test_state_updates(self, neural):
        neural.process("qual uso da cpu")
        # Objetivo é limpo após conclusão; eventos e estatísticas refletem o ciclo
        assert neural.state.event_history
        assert neural.decision.get_stats()["decisions_made"] == 1
        assert "sys" in neural.learning.counter()

    def test_get_stats(self, neural):
        stats = neural.get_stats()
        assert stats["state"]["current_mode"] == "idle"
        assert "security" in stats
