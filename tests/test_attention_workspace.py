"""Testes do Attention Engine (níveis, scoring, agregação) e Cognitive Workspace.

Cobre:
- Níveis de atenção (CRITICAL, HIGH, NORMAL, LOW, IGNORE)
- Scoring com novos fatores (importance, novelty, repetition)
- Agregação de eventos repetitivos
- Cognitive Workspace (snapshot, integração com NeuralCore)
"""

import pytest

from core.commands import CommandRegistry
from core.memory import MemoryManager
from core.neural.attention.attention_engine import (
    AggregatedEvent,
    AttentionEngine,
    AttentionLevel,
    AttentionScore,
)
from core.neural.core import NeuralCore
from core.neural.event_bus import EventBus
from core.neural.events import (
    EVENT_SYSTEM_ALERT,
    EVENT_USER_MESSAGE,
    EVENT_VISION_ERROR_DETECTED,
    EVENT_VISION_SCREEN_ANALYZED,
    EVENT_VOICE_COMMAND,
    Event,
)
from core.neural.memory.working_memory import WorkingMemory
from core.neural.state import GlobalState
from core.neural.workspace import CognitiveWorkspace, WorkspaceSnapshot, ComputationalBudget
from utils.logger import Logger


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def engine():
    return AttentionEngine.with_defaults()


@pytest.fixture
def state():
    return GlobalState()


@pytest.fixture
def working():
    return WorkingMemory()


@pytest.fixture
def workspace(state, working, engine):
    return CognitiveWorkspace(state=state, working=working, attention=engine)


@pytest.fixture
def logger(tmp_path):
    return Logger(name="test-attention-ws", level="CRITICAL")


@pytest.fixture
def memory_manager(tmp_path, logger):
    return MemoryManager(logger=logger, memory_root=tmp_path / "memory")


@pytest.fixture
def registry():
    reg = CommandRegistry()

    @reg.register_intent("sys", "sistema")
    def _sys(action, params, **ctx):
        return "CPU 10% | RAM 20%"

    return reg


@pytest.fixture
def neural(memory_manager, registry, logger):
    return NeuralCore.build(
        command_registry=registry,
        memory_manager=memory_manager,
        logger=logger,
    )


def _make_event(event_type=EVENT_USER_MESSAGE, text="hello", priority=50,
                confidence=0.8, source="test"):
    return Event(
        event_type=event_type,
        source=source,
        payload={"text": text, "query": text},
        priority=priority,
        confidence=confidence,
    )


# ── Testes de Níveis de Atenção ────────────────────────────

class TestAttentionLevels:
    def test_critical_level(self, engine):
        event = _make_event(EVENT_SYSTEM_ALERT, priority=100)
        score, level = engine.classify(event)
        assert level == AttentionLevel.CRITICAL
        assert score.score >= 0.75

    def test_high_level(self, engine):
        event = _make_event(EVENT_USER_MESSAGE, priority=80)
        score, level = engine.classify(event)
        assert level in (AttentionLevel.CRITICAL, AttentionLevel.HIGH)
        assert score.score >= 0.60

    def test_normal_level(self, engine):
        event = _make_event(EVENT_VISION_SCREEN_ANALYZED, priority=50)
        score, level = engine.classify(event)
        assert level in (AttentionLevel.NORMAL, AttentionLevel.HIGH)

    def test_low_level(self, engine):
        event = _make_event(EVENT_VISION_SCREEN_ANALYZED, priority=30, confidence=0.3)
        score, level = engine.classify(event)
        assert level in (AttentionLevel.LOW, AttentionLevel.IGNORE)

    def test_ignore_level(self, engine):
        event = _make_event(EVENT_VISION_SCREEN_ANALYZED, priority=1, confidence=0.05)
        score, level = engine.classify(event)
        assert level == AttentionLevel.IGNORE

    def test_level_thresholds_complete(self, engine):
        assert engine.level(0.9) == AttentionLevel.CRITICAL
        assert engine.level(0.7) == AttentionLevel.HIGH
        assert engine.level(0.5) == AttentionLevel.NORMAL
        assert engine.level(0.3) == AttentionLevel.LOW
        assert engine.level(0.1) == AttentionLevel.IGNORE


# ── Testes de Scoring com Novos Fatores ─────────────────────

class TestAttentionScoring:
    def test_importance_factor_high_alert(self, engine):
        alert = _make_event(EVENT_SYSTEM_ALERT, priority=100)
        normal = _make_event(EVENT_USER_MESSAGE, priority=100)
        s_alert = engine.score(alert)
        s_normal = engine.score(normal)
        assert s_alert.factors["importance"] >= s_normal.factors["importance"]

    def test_novelty_factor_first_event(self, engine):
        event = _make_event(text="unique_event_123")
        score = engine.score(event)
        assert score.factors["novelty"] == 1.0

    def test_novelty_factor_repeated_event(self, engine):
        event = _make_event(text="repeated_text")
        engine.observe(engine.score(event))
        engine.observe(engine.score(event))
        engine.observe(engine.score(event))
        score = engine.score(event)
        assert score.factors["novelty"] < 1.0

    def test_repetition_penalty_exact_repeat(self, engine):
        event = _make_event(text="exact_repeat")
        engine.observe(engine.score(event))
        score = engine.score(event)
        assert score.factors["repetition"] == 0.0

    def test_repetition_no_penalty_different_text(self, engine):
        e1 = _make_event(text="text_aaa")
        e2 = _make_event(text="text_bbb")
        engine.observe(engine.score(e1))
        score = engine.score(e2)
        assert score.factors["repetition"] == 1.0

    def test_score_range_0_to_1(self, engine):
        for priority in [0, 10, 30, 50, 70, 90, 100]:
            for conf in [0.1, 0.5, 0.9, 1.0]:
                event = _make_event(priority=priority, confidence=conf)
                score = engine.score(event)
                assert 0.0 <= score.score <= 1.0, f"Score {score.score} out of range"

    def test_user_message_high_score(self, engine):
        event = _make_event(EVENT_USER_MESSAGE, text="olá", priority=80)
        score = engine.score(event)
        assert score.score >= 0.6

    def test_voice_command_high_score(self, engine):
        event = _make_event(EVENT_VOICE_COMMAND, text="comando", priority=90)
        score = engine.score(event)
        assert score.score >= 0.6

    def test_weights_sum_near_one(self, engine):
        weights = engine.get_weights()
        total = sum(weights.values())
        assert 0.9 <= total <= 1.1


# ── Testes de Agregação ─────────────────────────────────────

class TestEventAggregation:
    def test_single_event_no_aggregation(self, engine):
        events = [_make_event(text="unique")]
        agg = engine.aggregate_events(events)
        assert len(agg) == 1
        assert agg[0].count == 1

    def test_identical_events_aggregated(self, engine):
        e1 = _make_event(text="same_text")
        e2 = _make_event(text="same_text")
        e3 = _make_event(text="same_text")
        agg = engine.aggregate_events([e1, e2, e3])
        assert len(agg) == 1
        assert agg[0].count == 3
        assert len(agg[0].events) == 3

    def test_different_events_not_aggregated(self, engine):
        e1 = _make_event(text="alpha")
        e2 = _make_event(text="beta")
        e3 = _make_event(text="gamma")
        agg = engine.aggregate_events([e1, e2, e3])
        assert len(agg) == 3
        for a in agg:
            assert a.count == 1

    def test_mixed_events_partial_aggregation(self, engine):
        e1 = _make_event(text="dup_a")
        e2 = _make_event(text="dup_a")
        e3 = _make_event(text="unique_b")
        agg = engine.aggregate_events([e1, e2, e3])
        assert len(agg) == 2
        counts = sorted([a.count for a in agg])
        assert counts == [1, 2]

    def test_different_types_not_aggregated(self, engine):
        e1 = _make_event(EVENT_USER_MESSAGE, text="same")
        e2 = _make_event(EVENT_VISION_SCREEN_ANALYZED, text="same")
        agg = engine.aggregate_events([e1, e2])
        assert len(agg) == 2

    def test_aggregated_representative_is_highest_priority(self, engine):
        e1 = _make_event(text="same", priority=30)
        e2 = _make_event(text="same", priority=90)
        agg = engine.aggregate_events([e1, e2])
        assert len(agg) == 1
        assert agg[0].representative.priority == 90

    def test_empty_events(self, engine):
        agg = engine.aggregate_events([])
        assert agg == []

    def test_aggregated_level_based_on_best(self, engine):
        e1 = _make_event(EVENT_SYSTEM_ALERT, text="alert", priority=100)
        e2 = _make_event(EVENT_SYSTEM_ALERT, text="alert", priority=100)
        agg = engine.aggregate_events([e1, e2])
        assert len(agg) == 1
        assert agg[0].level in (AttentionLevel.CRITICAL, AttentionLevel.HIGH)

    def test_aggregated_score_populated(self, engine):
        e1 = _make_event(text="scored")
        e2 = _make_event(text="scored")
        agg = engine.aggregate_events([e1, e2])
        assert agg[0].score is not None
        assert agg[0].score.score > 0


# ── Testes do Cognitive Workspace ────────────────────────────

class TestCognitiveWorkspace:
    def test_empty_workspace(self, workspace):
        snap = workspace.build()
        assert isinstance(snap, WorkspaceSnapshot)
        assert snap.focus == "idle"
        assert snap.recent_events == []
        assert snap.active_entities == []
        assert snap.current_goal is None
        assert snap.current_task == ""

    def test_workspace_with_goal(self, workspace, state):
        state.set_goal("monitorar sistema")
        snap = workspace.build()
        assert snap.current_goal == "monitorar sistema"
        assert snap.focus == "monitorar sistema"

    def test_workspace_with_task(self, workspace, working):
        working.start_task(goal="analisar cpu", intent="cpu")
        snap = workspace.build()
        assert snap.current_task == "analisar cpu"

    def test_workspace_with_events(self, workspace, state):
        e1 = _make_event(EVENT_USER_MESSAGE, text="hello", priority=80)
        e2 = _make_event(EVENT_VISION_SCREEN_ANALYZED, text="screen", priority=50)
        state.register_event(e1)
        state.register_event(e2)
        snap = workspace.build()
        assert len(snap.recent_events) >= 1

    def test_workspace_filters_ignore_events(self, workspace, state):
        for _ in range(5):
            e = _make_event(EVENT_VISION_SCREEN_ANALYZED, text="noise", priority=5, confidence=0.1)
            state.register_event(e)
        snap = workspace.build()
        for ev in snap.recent_events:
            assert ev["level"] != "IGNORE"

    def test_budget_has_values(self, workspace):
        snap = workspace.build()
        assert isinstance(snap.budget, ComputationalBudget)
        assert snap.budget.cpu_percent >= 0
        assert snap.budget.ram_percent >= 0

    def test_snapshot_to_dict(self, workspace):
        snap = workspace.build()
        d = snap.to_dict()
        assert "focus" in d
        assert "recent_events" in d
        assert "active_entities" in d
        assert "current_goal" in d
        assert "current_task" in d
        assert "budget" in d

    def test_snapshot_to_prompt_str(self, workspace):
        snap = workspace.build()
        s = snap.to_prompt_str()
        assert isinstance(s, str)
        assert len(s) > 0

    def test_workspace_rebuildable(self, workspace, state):
        snap1 = workspace.build()
        state.set_goal("new goal")
        snap2 = workspace.build()
        assert snap1.current_goal is None
        assert snap2.current_goal == "new goal"

    def test_workspace_with_custom_events(self, workspace):
        e1 = _make_event(EVENT_USER_MESSAGE, text="custom", priority=90)
        snap = workspace.build(events=[e1])
        assert len(snap.recent_events) >= 1


# ── Testes de Integração com NeuralCore ──────────────────────

class TestNeuralCoreWorkspace:
    def test_neural_core_has_workspace(self, neural):
        assert neural.workspace is not None

    def test_build_workspace_returns_snapshot(self, neural):
        snap = neural.build_workspace()
        assert isinstance(snap, WorkspaceSnapshot)

    def test_workspace_in_stats(self, neural):
        stats = neural.get_stats()
        assert "workspace" in stats
        assert "focus" in stats["workspace"]

    def test_process_updates_workspace(self, neural, registry):
        snap_before = neural.build_workspace()
        result = neural.process("teste cpu")
        snap_after = neural.build_workspace()
        assert snap_after.focus != "idle" or snap_before.focus != snap_after.focus

    def test_workspace_snapshot_frozen(self, workspace):
        snap = workspace.build()
        with pytest.raises(AttributeError):
            snap.focus = "changed"
