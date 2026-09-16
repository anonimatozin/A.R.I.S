"""Testes para o módulo de planejamento multi-intent.

Testa o pipeline completo: segmentação, parsing, dependências,
temporal e execução.
"""

import pytest
from core.planner import (
    create_planner,
    ExecutionPlan,
    PlanAction,
    ActionType,
    ActionStatus,
    PlanStatus,
    RelationType,
    TemporalInfo,
    Segmenter,
    TextSegment,
    parse_temporal,
    classify_action_type,
    analyze_dependencies,
)


class TestSegmenter:
    """Testes para o segmentador de texto."""

    def setup_method(self):
        self.segmenter = Segmenter()

    def test_single_action(self):
        segments = self.segmenter.segment("abre o spotify")
        assert len(segments) == 1
        assert "spotify" in segments[0].text.lower()

    def test_two_actions_with_e(self):
        segments = self.segmenter.segment("abre spotify e discord")
        assert len(segments) == 2
        texts = [s.text.lower() for s in segments]
        assert any("spotify" in t for t in texts)
        assert any("discord" in t for t in texts)

    def test_two_actions_with_depois(self):
        segments = self.segmenter.segment("abre o navegador depois pesquisa minecraft")
        assert len(segments) == 2

    def test_schedule_actions(self):
        segments = self.segmenter.segment("desliga o pc as 15 e liga as 16:30")
        assert len(segments) == 2
        assert any("15" in s.text for s in segments)
        assert any("16:30" in s.text for s in segments)

    def test_conditional_action(self):
        segments = self.segmenter.segment("desliga as 15 e quando ligar abre spotify")
        assert len(segments) == 2
        conditional = [s for s in segments if s.is_conditional]
        assert len(conditional) == 1
        assert "spotify" in conditional[0].text.lower()

    def test_empty_text(self):
        segments = self.segmenter.segment("")
        assert len(segments) == 0

    def test_connector_preserved(self):
        segments = self.segmenter.segment("abre spotify e discord")
        assert len(segments) == 2
        assert segments[1].connector == "e"


class TestTemporalParser:
    """Testes para o parser temporal."""

    def test_exact_time(self):
        t = parse_temporal("desliga as 15:30")
        assert t is not None
        assert t.time_str == "15:30"
        assert t.is_relative is False

    def test_hour_only(self):
        t = parse_temporal("desliga as 23h")
        assert t is not None
        assert t.time_str == "23:00"

    def test_relative_hours(self):
        t = parse_temporal("daqui 2 horas")
        assert t is not None
        assert t.is_relative is True
        assert t.relative_hours == 2.0

    def test_relative_minutes(self):
        t = parse_temporal("daqui 30 minutos")
        assert t is not None
        assert t.is_relative is True
        assert t.relative_minutes == 30.0

    def test_tomorrow(self):
        t = parse_temporal("amanha as 7")
        assert t is not None
        assert t.time_str == "07:00"
        assert t.is_relative is False

    def test_no_time(self):
        t = parse_temporal("abre o spotify")
        assert t is None


class TestActionClassification:
    """Testes para classificação de ações."""

    def test_shutdown(self):
        assert classify_action_type("desliga o pc") == ActionType.SHUTDOWN

    def test_schedule_shutdown(self):
        assert classify_action_type("desliga as 15") == ActionType.SCHEDULE_SHUTDOWN

    def test_wake(self):
        assert classify_action_type("liga o pc") == ActionType.WAKE

    def test_schedule_wake(self):
        assert classify_action_type("liga as 16:30") == ActionType.SCHEDULE_WAKE

    def test_open_app(self):
        assert classify_action_type("abre o spotify") == ActionType.OPEN_APP

    def test_open_browser(self):
        assert classify_action_type("abre o navegador") == ActionType.OPEN_BROWSER

    def test_search(self):
        assert classify_action_type("pesquisa minecraft") == ActionType.SEARCH_WEB

    def test_known_app_name_only(self):
        assert classify_action_type("discord") == ActionType.OPEN_APP
        assert classify_action_type("spotify") == ActionType.OPEN_APP

    def test_lock(self):
        assert classify_action_type("trava o pc") == ActionType.LOCK

    def test_restart(self):
        assert classify_action_type("reinicia o pc") == ActionType.RESTART


class TestPlanner:
    """Testes para o planner completo."""

    def setup_method(self):
        self.planner = create_planner()

    def test_single_shutdown(self):
        plan = self.planner.parse("desliga o pc")
        assert len(plan.actions) == 1
        assert plan.actions[0].action_type == ActionType.SHUTDOWN

    def test_schedule_shutdown_and_wake(self):
        plan = self.planner.parse("desliga o pc as 15 e liga as 16:30")
        assert len(plan.actions) == 2
        types = [a.action_type for a in plan.actions]
        assert ActionType.SCHEDULE_SHUTDOWN in types
        assert ActionType.SCHEDULE_WAKE in types
        # Verificar horários
        times = [a.temporal.time_str for a in plan.actions if a.temporal]
        assert "15:00" in times
        assert "16:30" in times

    def test_open_two_apps(self):
        plan = self.planner.parse("abre spotify e discord")
        assert len(plan.actions) == 2
        assert all(a.action_type == ActionType.OPEN_APP for a in plan.actions)

    def test_browser_and_search(self):
        plan = self.planner.parse("abre o navegador e pesquisa minecraft")
        assert len(plan.actions) == 2
        types = [a.action_type for a in plan.actions]
        assert ActionType.OPEN_BROWSER in types
        assert ActionType.SEARCH_WEB in types
        # Pesquisa depende de navegador
        search_action = [a for a in plan.actions if a.action_type == ActionType.SEARCH_WEB][0]
        assert len(search_action.depends_on) > 0

    def test_conditional_on_system_start(self):
        plan = self.planner.parse("desliga as 15 e quando ligar abre spotify")
        assert len(plan.actions) == 2
        open_action = [a for a in plan.actions if a.action_type == ActionType.OPEN_APP][0]
        assert open_action.trigger is not None
        assert open_action.trigger.trigger_event == "system_start"

    def test_plan_summary(self):
        plan = self.planner.parse("desliga as 15 e liga as 16:30")
        summary = plan.to_human_summary()
        assert "15:00" in summary
        assert "16:30" in summary

    def test_plan_status(self):
        plan = self.planner.parse("abre spotify")
        assert plan.status == PlanStatus.VALIDATED

    def test_empty_text(self):
        plan = self.planner.parse("")
        assert plan.status == PlanStatus.FAILED

    def test_multiple_actions_count(self):
        # Teste com muitas ações
        plan = self.planner.parse(
            "abre spotify e discord e vscode e navegador"
        )
        assert len(plan.actions) >= 3

    def test_plan_to_dict(self):
        plan = self.planner.parse("abre spotify")
        d = plan.to_dict()
        assert "plan_id" in d
        assert "actions" in d
        assert len(d["actions"]) == 1


class TestPlanExecution:
    """Testes para execução de planos (sem execução real)."""

    def test_plan_action_model(self):
        action = PlanAction(
            action_type=ActionType.OPEN_APP,
            description="Abrir Spotify",
            parameters={"app": "Spotify"},
        )
        assert action.status == ActionStatus.PENDING
        d = action.to_dict()
        assert d["action_type"] == "open_app"
        assert d["status"] == "pending"

    def test_execution_plan_ordering(self):
        plan = ExecutionPlan()
        a1 = PlanAction(id="1", action_type=ActionType.OPEN_BROWSER)
        a2 = PlanAction(id="2", action_type=ActionType.SEARCH_WEB, depends_on=["1"])
        a3 = PlanAction(id="3", action_type=ActionType.OPEN_APP)
        plan.add_action(a1)
        plan.add_action(a2)
        plan.add_action(a3)

        order = plan.get_sequential_order()
        # a1 e a3 devem vir antes de a2
        ids = [a.id for a in order]
        assert ids.index("1") < ids.index("2")
        assert ids.index("3") < ids.index("2")

    def test_get_ready_actions(self):
        plan = ExecutionPlan()
        a1 = PlanAction(id="1", action_type=ActionType.OPEN_BROWSER, status=ActionStatus.COMPLETED)
        a2 = PlanAction(id="2", action_type=ActionType.SEARCH_WEB, depends_on=["1"])
        a3 = PlanAction(id="3", action_type=ActionType.OPEN_APP)
        plan.add_action(a1)
        plan.add_action(a2)
        plan.add_action(a3)

        ready = plan.get_ready_actions()
        ready_ids = [a.id for a in ready]
        assert "2" in ready_ids  # Depende de 1 que está completo
        assert "3" in ready_ids  # Sem dependências

    def test_is_complete(self):
        plan = ExecutionPlan()
        a1 = PlanAction(id="1", status=ActionStatus.COMPLETED)
        a2 = PlanAction(id="2", status=ActionStatus.SKIPPED)
        plan.add_action(a1)
        plan.add_action(a2)
        assert plan.is_complete() is True

    def test_has_failures(self):
        plan = ExecutionPlan()
        a1 = PlanAction(id="1", status=ActionStatus.COMPLETED)
        a2 = PlanAction(id="2", status=ActionStatus.FAILED)
        plan.add_action(a1)
        plan.add_action(a2)
        assert plan.has_failures() is True
