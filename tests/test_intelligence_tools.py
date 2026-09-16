"""Testes das Intelligence Tools (Fase 3)."""

import pytest
from core.tools.intelligence_tools import (
    IntelSearch, IntelResearch, IntelVerify, IntelCompare, IntelLatest,
    INTELLIGENCE_TOOLS, execute_intel_tool,
)


class TestIntelSearch:
    def test_basic_search(self):
        s = IntelSearch()
        r = s.execute("python programming")
        assert r["ok"] is True
        assert r["query"] == "python programming"
        assert r["count"] >= 0

    def test_empty_query(self):
        s = IntelSearch()
        r = s.execute("")
        assert r["ok"] is False

    def test_results_structure(self):
        s = IntelSearch()
        r = s.execute("test query")
        assert "results" in r
        assert isinstance(r["results"], list)


class TestIntelResearch:
    def test_basic_research(self):
        r = IntelResearch().execute("machine learning")
        assert r["ok"] is True
        assert r["depth"] >= 1
        assert "findings" in r

    def test_empty_query(self):
        r = IntelResearch().execute("")
        assert r["ok"] is False

    def test_depth_limit(self):
        r = IntelResearch().execute("AI", depth=10)
        assert r["depth"] <= 3

    def test_queries_used(self):
        r = IntelResearch().execute("quantum computing", depth=2)
        assert len(r["queries_used"]) >= 1

    def test_summary(self):
        r = IntelResearch().execute("test")
        assert "summary" in r
        assert isinstance(r["summary"], str)


class TestIntelVerify:
    def test_basic_verify(self):
        r = IntelVerify().execute("the earth is round")
        assert r["ok"] is True
        assert "confidence" in r
        assert "verdict" in r

    def test_empty_claim(self):
        r = IntelVerify().execute("")
        assert r["ok"] is False

    def test_sources_checked(self):
        r = IntelVerify().execute("water boils at 100C")
        assert r["sources_checked"] >= 0

    def test_confidence_range(self):
        r = IntelVerify().execute("test claim")
        assert 0.0 <= r["confidence"] <= 1.0

    def test_verdict_levels(self):
        r = IntelVerify().execute("test")
        assert r["verdict"] in [
            "Alta confianca — provavelmente verdadeiro",
            "Confianca media — requer verificacao adicional",
            "Baixa confianca — informacao inconclusiva",
        ]


class TestIntelCompare:
    def test_basic_compare(self):
        r = IntelCompare().execute("python", "javascript")
        assert r["ok"] is True
        assert r["item_a"] == "python"
        assert r["item_b"] == "javascript"

    def test_empty_items(self):
        r = IntelCompare().execute("", "javascript")
        assert r["ok"] is False

    def test_with_aspect(self):
        r = IntelCompare().execute("python", "javascript", aspect="performance")
        assert r["aspect"] == "performance"

    def test_direct_comparison(self):
        r = IntelCompare().execute("A", "B")
        assert "direct_comparison" in r


class TestIntelLatest:
    def test_basic_latest(self):
        r = IntelLatest().execute("AI news")
        assert r["ok"] is True
        assert r["topic"] == "AI news"

    def test_empty_topic(self):
        r = IntelLatest().execute("")
        assert r["ok"] is False

    def test_results_count(self):
        r = IntelLatest().execute("technology")
        assert r["count"] >= 0


class TestToolDefinitions:
    def test_all_tools_registered(self):
        assert len(INTELLIGENCE_TOOLS) == 5

    def test_tool_has_required_fields(self):
        for name, info in INTELLIGENCE_TOOLS.items():
            assert "description" in info, f"{name} missing description"
            assert "permission" in info, f"{name} missing permission"
            assert "category" in info, f"{name} missing category"

    def test_execute_intel_tool_dispatch(self):
        r = execute_intel_tool("intel_search", {"query": "test"})
        assert r["ok"] is True

    def test_execute_intel_tool_unknown(self):
        r = execute_intel_tool("intel_unknown", {})
        assert r["ok"] is False

    def test_execute_research(self):
        r = execute_intel_tool("intel_research", {"query": "AI", "depth": 2})
        assert r["ok"] is True

    def test_execute_verify(self):
        r = execute_intel_tool("intel_verify", {"claim": "test claim"})
        assert r["ok"] is True

    def test_execute_compare(self):
        r = execute_intel_tool("intel_compare", {"item_a": "A", "item_b": "B"})
        assert r["ok"] is True

    def test_execute_latest(self):
        r = execute_intel_tool("intel_latest", {"topic": "tech"})
        assert r["ok"] is True
