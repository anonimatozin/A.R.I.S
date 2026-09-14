"""Tests for BLOCO 5 (Safety Gate integration) + BLOCO 6 (pbkdf2 credentials)."""

import pytest
from pathlib import Path


class TestSecurityGateIntegration:
    def test_gate_uses_safety_manager_danger_level(self):
        from core.neural.security.security_gate import SecurityGate, GateOutcome
        from core.neural.decision.decision_engine import Decision
        from modules.safety import SafetyManager

        safety = SafetyManager()
        gate = SecurityGate(safety_manager=safety)

        # Create a Decision with low risk, but action is DANGER in SafetyManager
        decision = Decision(
            module="desktop", action="close_app", parameters={"app_name": "test"},
            confidence=0.9, risk=1, source="test",
        )
        # Registry check will fail (module not in capabilities) — so use a known module
        # Actually, without a registry, all modules are unknown. Let's use a mock.
        class FakeRegistry:
            def list_intents(self):
                return [("desktop", "desc")]
        gate._registry = FakeRegistry()

        result = gate.approve(decision)
        # close_app is DANGER → risk should be raised to 3 → DANGER
        assert result.is_allowed
        assert result.audit_required

    def test_gate_deny_unknown_module(self):
        from core.neural.security.security_gate import SecurityGate, GateOutcome
        from core.neural.decision.decision_engine import Decision

        gate = SecurityGate()
        decision = Decision(
            module="nonexistent_module", action="foo", parameters={},
            confidence=1.0, risk=1, source="test",
        )
        result = gate.approve(decision)
        assert result.outcome == GateOutcome.DENIED

    def test_gate_security_log_recorded(self):
        from core.neural.security.security_gate import SecurityGate
        from core.neural.decision.decision_engine import Decision

        gate = SecurityGate()
        decision = Decision(
            module="exit", action="quit", parameters={},
            confidence=1.0, risk=1, source="test",
        )
        gate.approve(decision)
        log = gate.get_security_log()
        assert len(log) >= 1
        assert log[-1]["action"] == "approved"

    def test_gate_stats_include_security_log(self):
        from core.neural.security.security_gate import SecurityGate
        from core.neural.decision.decision_engine import Decision

        gate = SecurityGate()
        decision = Decision(
            module="exit", action="quit", parameters={},
            confidence=1.0, risk=1, source="test",
        )
        gate.approve(decision)
        stats = gate.get_stats()
        assert "security_log_entries" in stats


class TestSafetyManagerPbkdf2:
    def test_set_password_rejects_empty(self):
        from modules.safety import SafetyManager
        sm = SafetyManager()
        result = sm.set_master_password("")
        assert "curta" in result.lower() or "mínimo" in result.lower()

    def test_set_password_rejects_short(self):
        from modules.safety import SafetyManager
        sm = SafetyManager()
        result = sm.set_master_password("ab")
        assert "curta" in result.lower()

    def test_set_password_accepts_valid(self):
        from modules.safety import SafetyManager
        sm = SafetyManager()
        result = sm.set_master_password("secure_password_123")
        assert "definida" in result.lower()

    def test_check_password_rejects_empty_when_hash_exists(self):
        from modules.safety import SafetyManager
        sm = SafetyManager()
        sm.set_master_password("secure_password_123")
        assert sm.check_password("") is False

    def test_check_password_accepts_correct(self):
        from modules.safety import SafetyManager
        sm = SafetyManager()
        sm.set_master_password("secure_password_123")
        assert sm.check_password("secure_password_123") is True

    def test_check_password_rejects_incorrect(self):
        from modules.safety import SafetyManager
        sm = SafetyManager()
        sm.set_master_password("secure_password_123")
        assert sm.check_password("wrong_password") is False

    def test_no_hash_allows_everything(self):
        from modules.safety import SafetyManager
        sm = SafetyManager()
        assert sm.check_password("anything") is True

    def test_can_execute_critical_requires_password(self):
        from modules.safety import SafetyManager
        sm = SafetyManager()
        sm.set_master_password("master_key")
        ok, msg = sm.can_execute("shutdown", password="wrong")
        assert not ok
        ok, msg = sm.can_execute("shutdown", password="master_key")
        assert ok

    def test_legacy_sha256_hash_accepted(self):
        """Password set with old SHA-256 (no salt) still works."""
        import hashlib
        from modules.safety import SafetyManager
        sm = SafetyManager()
        # Simulate legacy: directly set SHA-256 hash without salt
        sm._password_hash = hashlib.sha256("old_password".encode()).hexdigest()
        sm._password_salt = ""  # No salt = legacy format
        assert sm.check_password("old_password") is True
        assert sm.check_password("wrong_password") is False

    def test_legacy_hash_upgraded_on_login(self):
        """After legacy SHA-256 login, hash is upgraded to pbkdf2."""
        import hashlib
        from modules.safety import SafetyManager
        sm = SafetyManager()
        # Simulate legacy
        sm._password_hash = hashlib.sha256("old_password".encode()).hexdigest()
        sm._password_salt = ""
        # Login triggers rehash
        assert sm.check_password("old_password") is True
        # Now salt exists (proof that pbkdf2 was used, not legacy path)
        assert sm._password_salt != ""
        assert len(sm._password_salt) == 32  # 16 bytes hex = 32 chars
        # Second login uses pbkdf2 path (not legacy fallback)
        assert sm.check_password("old_password") is True
