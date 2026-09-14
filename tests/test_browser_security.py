"""Tests for BLOCO 2 — JS execution disabled + SSRF on browser navigate."""

import pytest


class TestBrowserEvaluateDisabled:
    def test_evaluate_returns_disabled_message(self):
        from modules.browser_automation import BrowserAutomation
        ba = BrowserAutomation()
        # evaluate() should be blocked even if page exists
        result = ba.run_async(ba.evaluate("document.cookie"))
        assert "desativada" in result.lower() or "segurança" in result.lower()

    def test_evaluate_does_not_execute_js(self):
        from modules.browser_automation import BrowserAutomation
        ba = BrowserAutomation()
        result = ba.run_async(ba.evaluate("require('child_process').execSync('whoami')"))
        assert "desativada" in result.lower()


class TestBrowserNavigateSSRF:
    def test_navigate_rejects_localhost(self):
        from modules.browser_automation import BrowserAutomation
        ba = BrowserAutomation()
        # navigate without a page returns "not started" — but URL validation
        # happens first, so we test the validation directly
        from core.security.shell import validate_url, InputValidationError
        with pytest.raises(InputValidationError):
            validate_url("http://localhost:8080")

    def test_navigate_rejects_private_ip(self):
        from core.security.shell import validate_url, InputValidationError
        with pytest.raises(InputValidationError):
            validate_url("http://192.168.1.1/admin")

    def test_navigate_rejects_metadata_endpoint(self):
        from core.security.shell import validate_url, InputValidationError
        with pytest.raises(InputValidationError):
            validate_url("http://169.254.169.254/latest/meta-data/")

    def test_navigate_rejects_file_scheme(self):
        from core.security.shell import validate_url, InputValidationError
        with pytest.raises(InputValidationError):
            validate_url("file:///etc/passwd")
