"""Integration tests for gateway modules."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from gateway.audit import get_recent, log_operation
from gateway.auth import authenticate, get_token, init_auth
from gateway.backup import create_backup, list_backups, restore_backup
from gateway.memory import MemoryDB
from gateway.monitor import get_metrics
from gateway.security import CommandInjectionError, PathTraversalError, safe_path, validate_command


class TestAuth:
    def test_init_auth_with_env_var(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CLL1_TOKEN": "test_token_123"}):
                init_auth(tmpdir)
                assert get_token() == "test_token_123"

    def test_authenticate_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CLL1_TOKEN": "test_token_123"}):
                init_auth(tmpdir)
                assert authenticate({"token": "test_token_123"}) is True

    def test_authenticate_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CLL1_TOKEN": "test_token_123"}):
                init_auth(tmpdir)
                assert authenticate({"token": "wrong"}) is False

    def test_authenticate_missing_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CLL1_TOKEN": "test_token_123"}):
                init_auth(tmpdir)
                assert authenticate({}) is False


class TestAudit:
    def test_log_operation(self):
        log_operation("test_op", target="test_target", result="ok")
        entries = get_recent(10)
        assert len(entries) > 0
        last = entries[-1]
        assert last["op"] == "test_op"
        assert last["target"] == "test_target"

    def test_log_with_duration(self):
        log_operation("exec", target="ls", result="ok", duration_ms=150)
        entries = get_recent(10)
        last = entries[-1]
        assert last["ms"] == 150

    def test_log_with_detail(self):
        log_operation("read", target="file.txt", result="ok", detail="some detail here")
        entries = get_recent(10)
        last = entries[-1]
        assert last["detail"] == "some detail here"


class TestSecurity:
    def test_safe_path_valid(self):
        result = safe_path("file.txt", "/tmp/test")
        assert result.endswith("file.txt")

    def test_safe_path_subdir(self):
        result = safe_path("sub/dir/file.txt", "/tmp/test")
        assert result.endswith("sub/dir/file.txt") or result.endswith("sub\\dir\\file.txt")

    def test_safe_path_traversal_dotdot(self):
        with pytest.raises(PathTraversalError):
            safe_path("../../../etc/passwd", "/tmp/test")

    def test_safe_path_absolute(self):
        with pytest.raises(PathTraversalError):
            safe_path("/etc/passwd", "/tmp/test")

    def test_validate_command_safe(self):
        result = validate_command("ls -la")
        assert result == "ls -la"

    def test_validate_command_injection_semicolon_rm(self):
        with pytest.raises(CommandInjectionError):
            validate_command("ls; rm -rf /")

    def test_validate_command_injection_backtick(self):
        with pytest.raises(CommandInjectionError):
            validate_command("`rm -rf /`")

    def test_validate_command_with_allowlist(self):
        result = validate_command("ls -la", allowlist=["ls", "cat"])
        assert result == "ls -la"

    def test_validate_command_not_in_allowlist(self):
        with pytest.raises(CommandInjectionError):
            validate_command("rm -rf /", allowlist=["ls", "cat"])


class TestMemory:
    def test_add_and_get_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = MemoryDB(os.path.join(tmpdir, "test.db"))
            result = db.add_memory("test content", category="test", importance=8)
            assert result["ok"] is True
            memories = db.get_memories(limit=10)
            assert len(memories) == 1
            assert memories[0]["content"] == "test content"
            db.close()

    def test_set_and_get_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = MemoryDB(os.path.join(tmpdir, "test.db"))
            db.set_state("last_boot", "2026-01-01")
            result = db.get_state("last_boot")
            assert result is not None
            assert result["value"] == "2026-01-01"
            db.close()

    def test_get_state_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = MemoryDB(os.path.join(tmpdir, "test.db"))
            result = db.get_state("nonexistent")
            assert result is None
            db.close()

    def test_search_memories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = MemoryDB(os.path.join(tmpdir, "test.db"))
            db.add_memory("python is great", category="tech")
            db.add_memory("cooking recipe", category="food")
            results = db.search_memories("python")
            assert len(results) == 1
            assert "python" in results[0]["content"]
            db.close()


class TestMonitor:
    def test_get_metrics_structure(self):
        metrics = get_metrics()
        assert "timestamp" in metrics
        assert "uptime" in metrics
        assert "memory" in metrics
        assert "disk" in metrics
        assert "cpu" in metrics


class TestBackup:
    def test_create_and_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "cll1"))
            with open(os.path.join(tmpdir, "cll1", "test.py"), "w") as f:
                f.write("print('test')")
            result = create_backup(tmpdir, "test_backup")
            assert result["ok"] is True
            backups = list_backups(tmpdir)
            assert len(backups) == 1
            assert backups[0]["name"] == "test_backup"

    def test_restore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "cll1"))
            with open(os.path.join(tmpdir, "cll1", "test.py"), "w") as f:
                f.write("print('test')")
            create_backup(tmpdir, "test_backup")
            result = restore_backup(tmpdir, "test_backup")
            assert result["ok"] is True

    def test_list_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backups = list_backups(tmpdir)
            assert backups == []
