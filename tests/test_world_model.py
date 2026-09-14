"""Testes do World Model (Belief, User Model, Goals, Prospective, Follow-up).

Cobre:
- Belief: criar, atualizar (histórico), consultar
- User Model: preferências do usuário com proveniência
- Goals: criar com prazo, detectar atraso
- Prospective Reminders: criar lembrete recorrente
- Distinção comentário vs compromisso (heurística)
- Integração com WorkspaceSnapshot (current_goal, proposals)
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from core.memory_db import MemoryDB
from core.neural.world_model import (
    Belief,
    BeliefSource,
    Goal,
    GoalStatus,
    ProspectiveReminder,
    WorldModel,
    classify_commitment,
    estimate_goal_confidence,
)
from core.commands import CommandRegistry
from core.neural.attention.attention_engine import AttentionEngine
from core.neural.memory.working_memory import WorkingMemory
from core.neural.state import GlobalState
from core.neural.workspace import CognitiveWorkspace
from utils.logger import Logger


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    return MemoryDB(db_dir=tmp_path)


@pytest.fixture
def wm(db):
    return WorldModel(db=db)


@pytest.fixture
def state():
    return GlobalState()


@pytest.fixture
def working():
    return WorkingMemory()


@pytest.fixture
def engine():
    return AttentionEngine.with_defaults()


@pytest.fixture
def workspace(state, working, engine, wm):
    return CognitiveWorkspace(
        state=state,
        working=working,
        attention=engine,
        world_model=wm,
    )


# ── Belief ──────────────────────────────────────────────────


class TestBeliefCreation:
    def test_create_belief(self, wm):
        b = wm.create_belief("system", "pc.ram_gb", "16")
        assert b.category == "system"
        assert b.key == "pc.ram_gb"
        assert b.value == "16"
        assert b.source == BeliefSource.USER_PROVIDED
        assert b.confidence == 1.0
        assert b.revision == 1
        assert b.is_current()

    def test_create_belief_with_source(self, wm):
        b = wm.create_belief(
            "general", "clima.temp", "22°C",
            source=BeliefSource.OBSERVED, confidence=0.9,
        )
        assert b.source == BeliefSource.OBSERVED
        assert b.confidence == 0.9

    def test_get_belief(self, wm):
        wm.create_belief("system", "pc.os", "Windows 11")
        found = wm.get_belief("system", "pc.os")
        assert found is not None
        assert found.value == "Windows 11"

    def test_get_nonexistent_belief(self, wm):
        found = wm.get_belief("system", "nonexistent")
        assert found is None


class TestBeliefUpdate:
    def test_update_creates_revision(self, wm):
        b1 = wm.create_belief("system", "pc.ram_gb", "8")
        assert b1.revision == 1

        b2 = wm.update_belief("system", "pc.ram_gb", "16")
        assert b2.revision == 2
        assert b2.value == "16"

    def test_old_belief_archived(self, wm):
        b1 = wm.create_belief("system", "pc.ram_gb", "8")
        b2 = wm.update_belief("system", "pc.ram_gb", "16")

        current = wm.get_belief("system", "pc.ram_gb")
        assert current.id == b2.id
        assert current.value == "16"

    def test_history_preserved(self, wm):
        wm.create_belief("system", "pc.ram_gb", "8")
        wm.update_belief("system", "pc.ram_gb", "16")
        wm.update_belief("system", "pc.ram_gb", "32")

        history = wm.get_belief_history("system", "pc.ram_gb")
        assert len(history) == 3
        assert history[0].value == "32"  # mais recente primeiro
        assert history[1].value == "16"
        assert history[2].value == "8"

    def test_update_same_value_no_change(self, wm):
        b1 = wm.create_belief("system", "pc.ram_gb", "16")
        b2 = wm.update_belief("system", "pc.ram_gb", "16")
        assert b1.id == b2.id  # Sem mudança, retorna mesma instância

    def test_search_beliefs(self, wm):
        wm.create_belief("system", "pc.ram_gb", "16")
        wm.create_belief("system", "pc.cpu", "i5-3470")
        wm.create_belief("user_profile", "pref.cafe", "sim")

        results = wm.search_beliefs(category="system")
        assert len(results) == 2

        results = wm.search_beliefs(query="ram")
        assert len(results) == 1
        assert results[0].key == "pc.ram_gb"


# ── User Model ──────────────────────────────────────────────


class TestUserModel:
    def test_set_preference(self, wm):
        b = wm.set_user_preference("pref.cafe", "sim")
        assert b.category == "user_profile"
        assert b.key == "pref.cafe"
        assert b.value == "sim"
        assert b.source == BeliefSource.USER_PROVIDED

    def test_get_preference(self, wm):
        wm.set_user_preference("pref.cafe", "sim")
        val = wm.get_user_preference("pref.cafe")
        assert val == "sim"

    def test_get_nonexistent_preference(self, wm):
        val = wm.get_user_preference("pref.nonexistent")
        assert val is None

    def test_get_user_profile(self, wm):
        wm.set_user_preference("nome", "Vinicius")
        wm.set_user_preference("pref.cafe", "sim")
        wm.set_user_preference("sistema.os", "Windows")

        profile = wm.get_user_profile()
        assert profile["nome"] == "Vinicius"
        assert profile["pref.cafe"] == "sim"
        assert profile["sistema.os"] == "Windows"

    def test_preference_overwrite(self, wm):
        wm.set_user_preference("pref.cafe", "sim")
        wm.set_user_preference("pref.cafe", "não")

        val = wm.get_user_preference("pref.cafe")
        assert val == "não"

        history = wm.get_belief_history("user_profile", "pref.cafe")
        assert len(history) == 2
        assert history[0].value == "não"
        assert history[1].value == "sim"


# ── Goals ───────────────────────────────────────────────────


class TestGoals:
    def test_create_goal(self, wm):
        g = wm.create_goal("Terminar a ARIS", importance=8)
        assert g.description == "Terminar a ARIS"
        assert g.status == GoalStatus.ACTIVE
        assert g.importance == 8
        assert g.deadline is None

    def test_create_goal_with_deadline(self, wm):
        dl = (datetime.now() + timedelta(days=30)).isoformat()
        g = wm.create_goal("Deploy do projeto", deadline=dl)
        assert g.deadline is not None
        assert not g.is_overdue()

    def test_complete_goal(self, wm):
        g = wm.create_goal("Tarefa simples")
        completed = wm.complete_goal(g.id)
        assert completed.status == GoalStatus.COMPLETED
        assert completed.completed_at is not None

    def test_abandon_goal(self, wm):
        g = wm.create_goal("Tarefa abandonada")
        abandoned = wm.abandon_goal(g.id)
        assert abandoned.status == GoalStatus.ABANDONED

    def test_block_goal(self, wm):
        g = wm.create_goal("Tarefa bloqueada")
        blocked = wm.block_goal(g.id)
        assert blocked.status == GoalStatus.BLOCKED

    def test_get_active_goals(self, wm):
        wm.create_goal("Meta 1")
        wm.create_goal("Meta 2")
        g3 = wm.create_goal("Meta 3")
        wm.complete_goal(g3.id)

        active = wm.get_active_goals()
        assert len(active) == 2

    def test_overdue_goal_detected(self, wm):
        past = (datetime.now() - timedelta(days=5)).isoformat()
        g = wm.create_goal("Tarefa atrasada", deadline=past)
        overdue = wm.get_overdue_goals()
        assert len(overdue) == 1
        assert overdue[0].id == g.id
        assert g.is_overdue()

    def test_non_overdue_goal(self, wm):
        future = (datetime.now() + timedelta(days=30)).isoformat()
        g = wm.create_goal("Meta futura", deadline=future)
        overdue = wm.get_overdue_goals()
        assert len(overdue) == 0
        assert not g.is_overdue()

    def test_completed_goal_not_overdue(self, wm):
        past = (datetime.now() - timedelta(days=5)).isoformat()
        g = wm.create_goal("Já feita", deadline=past)
        wm.complete_goal(g.id)
        overdue = wm.get_overdue_goals()
        assert len(overdue) == 0

    def test_complete_nonexistent(self, wm):
        result = wm.complete_goal("nonexistent")
        assert result is None


# ── Prospective Reminders ───────────────────────────────────


class TestProspectiveReminders:
    def test_create_reminder(self, wm):
        r = wm.create_reminder("Reunião", "2026-09-20T10:00:00")
        assert r.text == "Reunião"
        assert r.is_active
        assert r.recurrence is None

    def test_create_recurring_reminder(self, wm):
        r = wm.create_reminder(
            "Aniversário", "2026-12-25T09:00:00", recurrence="yearly"
        )
        assert r.recurrence == "yearly"

    def test_should_trigger(self, wm):
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        r = wm.create_reminder("Lembrete", past)
        assert r.should_trigger()

    def test_should_not_trigger_future(self, wm):
        future = (datetime.now() + timedelta(days=1)).isoformat()
        r = wm.create_reminder("Lembrete", future)
        assert not r.should_trigger()

    def test_trigger_one_time(self, wm):
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        r = wm.create_reminder("Lembrete", past)
        triggered = wm.trigger_reminder(r.id)
        assert not triggered.is_active  # Desativado após trigger

    def test_trigger_recurring_advances(self, wm):
        now = datetime.now()
        r = wm.create_reminder(
            "Semanal", now.isoformat(), recurrence="weekly"
        )
        triggered = wm.trigger_reminder(r.id)
        assert triggered.is_active  # Ainda ativo
        assert triggered.remind_at > now.isoformat()

    def test_get_due_reminders(self, wm):
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        future = (datetime.now() + timedelta(days=1)).isoformat()
        wm.create_reminder("Agora", past)
        wm.create_reminder("Depois", future)

        due = wm.get_due_reminders()
        assert len(due) == 1
        assert due[0].text == "Agora"


# ── Heurística de confiança ─────────────────────────────────


class TestCommitmentClassification:
    def test_explicit_commitment(self):
        is_commit, is_remind, has_recur = classify_commitment(
            "quero terminar a ARIS em 2027"
        )
        assert is_commit
        assert not is_remind
        assert not has_recur

    def test_reminder_request(self):
        is_commit, is_remind, has_recur = classify_commitment(
            "me lembre disso daqui a duas semanas"
        )
        assert is_remind
        assert not has_recur

    def test_ambiguous_comment(self):
        is_commit, is_remind, has_recur = classify_commitment(
            "hoje está fazendo sol"
        )
        assert not is_commit
        assert not is_remind
        assert not has_recur

    def test_recurrence_pattern(self):
        is_commit, is_remind, has_recur = classify_commitment(
            "todo ano, dia 12, é meu aniversário"
        )
        assert has_recur
        assert not is_commit

    def test_deadline_detection(self):
        conf = estimate_goal_confidence("quero terminar em 3 meses")
        assert conf >= 0.6  # Compromisso + prazo

    def test_low_confidence_comment(self):
        conf = estimate_goal_confidence("talvez um dia eu faça isso")
        assert conf < 0.3


# ── Process user text ───────────────────────────────────────


class TestProcessUserText:
    def test_reminder_request_detected(self, wm):
        result = wm.process_user_text(
            "me lembre de ligar para o médico amanhã"
        )
        assert result is not None
        assert result["action"] == "reminder_request"

    def test_strong_commitment_creates_goal(self, wm):
        result = wm.process_user_text(
            "quero terminar a fase de memória até dezembro"
        )
        assert result is not None
        assert result["action"] == "goal_created"
        assert isinstance(result["goal"], Goal)
        assert result["confidence"] >= 0.6

    def test_ambiguous_returns_suggestion(self, wm):
        result = wm.process_user_text(
            "talvez eu implemente isso um dia"
        )
        if result is not None:
            assert result["action"] in ("ambiguous", "reminder_request")

    def test_recurrence_needs_clarification_when_incomplete(self, wm):
        result = wm.process_user_text(
            "todo ano, dia 12, é meu aniversário"
        )
        assert result is not None
        assert result["action"] == "needs_clarification"
        assert "mês" in result["suggestion"].lower()

    def test_recurrence_with_full_date_creates_reminder(self, wm):
        result = wm.process_user_text(
            "meu aniversário é dia 12 de outubro"
        )
        assert result is not None
        assert result["action"] == "reminder_created"
        rem = result["reminder"]
        assert rem.recurrence == "yearly"
        assert rem.is_active
        assert "10-12" in rem.remind_at  # outubro = month 10

    def test_neutral_returns_none(self, wm):
        result = wm.process_user_text("hoje o dia está bonito")
        assert result is None


# ── Follow-up ───────────────────────────────────────────────


class TestFollowUp:
    def test_overdue_generates_suggestion(self, wm):
        past = (datetime.now() - timedelta(days=3)).isoformat()
        wm.create_goal("Tarefa atrasada", deadline=past)
        suggestions = wm.check_follow_ups()
        assert len(suggestions) >= 1
        assert "atrasado" in suggestions[0] or "passou do prazo" in suggestions[0]

    def test_due_reminder_in_followup(self, wm):
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        wm.create_reminder("Lembrete pendente", past)
        suggestions = wm.check_follow_ups()
        assert any("Lembrete pendente" in s for s in suggestions)

    def test_no_followups_when_all_ok(self, wm):
        future = (datetime.now() + timedelta(days=30)).isoformat()
        wm.create_goal("Meta ok", deadline=future)
        suggestions = wm.check_follow_ups()
        assert len(suggestions) == 0


# ── Integração com Workspace ────────────────────────────────


class TestWorkspaceIntegration:
    def test_current_goal_from_world_model(self, wm, workspace, state):
        wm.create_goal("Meta ativa")
        snap = workspace.build()
        assert snap.current_goal == "Meta ativa"

    def test_goal_state_takes_precedence(self, wm, workspace, state):
        state.set_goal("Goal do estado")
        wm.create_goal("Meta do world model")
        snap = workspace.build()
        # State goal tem precedência
        assert snap.current_goal == "Goal do estado"

    def test_overdue_appears_in_proposals(self, wm, workspace):
        past = (datetime.now() - timedelta(days=1)).isoformat()
        wm.create_goal("Tarefa atrasada", deadline=past)
        snap = workspace.build()
        assert len(snap.proposals) >= 1
        assert any("atrasado" in p or "passou do prazo" in p for p in snap.proposals)

    def test_due_reminder_in_proposals(self, wm, workspace):
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        wm.create_reminder("Reunião agora", past)
        snap = workspace.build()
        assert any("Lembrete pendente" in p for p in snap.proposals)

    def test_no_proposals_when_all_ok(self, wm, workspace):
        future = (datetime.now() + timedelta(days=30)).isoformat()
        wm.create_goal("Meta ok", deadline=future)
        snap = workspace.build()
        assert len(snap.proposals) == 0

    def test_empty_world_model(self, workspace):
        snap = workspace.build()
        assert snap.current_goal is None
        assert snap.proposals == []
