"""Tests for BLOCO 3 — Path Traversal prevention."""

import pytest
from pathlib import Path

from core.security.shell import safe_resolve, PathTraversalError


class TestSafeResolve:
    def test_valid_relative_path(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("ok")
        result = safe_resolve(tmp_path, "src/main.py")
        assert result.exists()

    def test_valid_absolute_within_base(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file.txt").write_text("ok")
        result = safe_resolve(tmp_path, str(tmp_path / "sub" / "file.txt"))
        assert result.exists()

    def test_traversal_dotdot_rejected(self, tmp_path):
        with pytest.raises(PathTraversalError):
            safe_resolve(tmp_path, "../../etc/passwd")

    def test_traversal_dotdot_backslash_rejected(self, tmp_path):
        with pytest.raises(PathTraversalError):
            safe_resolve(tmp_path, "..\\..\\Windows\\System32")

    def test_absolute_outside_base_rejected(self, tmp_path):
        with pytest.raises(PathTraversalError):
            safe_resolve(tmp_path / "sub", "/etc/passwd")

    def test_symlink_traversal_rejected(self, tmp_path):
        """Symlink pointing outside base should be rejected."""
        link = tmp_path / "link"
        try:
            link.symlink_to("/etc")
        except OSError:
            pytest.skip("Symlinks not supported")
        with pytest.raises(PathTraversalError):
            safe_resolve(tmp_path, "link/passwd")

    def test_same_dir_ok(self, tmp_path):
        (tmp_path / "test.txt").write_text("ok")
        result = safe_resolve(tmp_path, "test.txt")
        assert result.exists()


class TestTurboModePathTraversal:
    def test_analyze_file_rejects_traversal(self):
        from modules.turbo_mode import TurboMode
        tm = TurboMode()
        result = tm.analyze_file("../../etc/passwd")
        assert "acesso negado" in result.lower() or "fora do diretório" in result.lower()

    def test_analyze_file_accepts_valid_path(self):
        from modules.turbo_mode import TurboMode
        tm = TurboMode()
        # Use a path within the project (the turbo_mode.py file itself)
        result = tm.analyze_file("modules/turbo_mode.py")
        # Should succeed or give analysis — not a traversal error
        assert "acesso negado" not in result.lower()

    def test_analyze_directory_rejects_traversal(self):
        from modules.turbo_mode import TurboMode
        tm = TurboMode()
        result = tm.analyze_directory("../../Windows")
        assert "acesso negado" in result.lower() or "fora do diretório" in result.lower()


class TestDesktopAwarenessPathTraversal:
    def test_extract_text_rejects_traversal(self):
        from modules.desktop_awareness import DesktopAwareness
        da = DesktopAwareness()
        result = da.extract_text_from_image("../../etc/passwd")
        assert "acesso negado" in result.lower() or "fora do diretório" in result.lower()
