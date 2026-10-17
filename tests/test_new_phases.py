"""Tests for Mode System, Capabilities, Tools, and Agent Loop."""

import time
import pytest
from unittest.mock import MagicMock


# ── Phase A: Mode System ──────────────────────────────────────

class TestARISMode:
    def test_mode_enum_values(self):
        from core.neural.mode import ARISMode
        assert ARISMode.EDGE == "edge"
        assert ARISMode.PRIMARY == "primary"
        assert ARISMode.TRANSITIONING == "transitioning"
        assert ARISMode.UNKNOWN == "unknown"

    def test_mode_manager_default(self):
        from core.neural.mode import ModeManager
        mm = ModeManager()
        assert mm.mode.value == "unknown"

    def test_mode_manager_heartbeat_online(self):
        from core.neural.mode import ModeManager, ARISMode
        mm = ModeManager()
        result = mm.update_heartbeat(pc_online=True)
        assert result == ARISMode.PRIMARY
        assert mm.mode == ARISMode.PRIMARY

    def test_mode_manager_heartbeat_offline_3_failures(self):
        from core.neural.mode import ModeManager, ARISMode
        mm = ModeManager()
        mm.update_heartbeat(pc_online=True)
        assert mm.mode == ARISMode.PRIMARY
        mm.update_heartbeat(pc_online=False)
        mm.update_heartbeat(pc_online=False)
        result = mm.update_heartbeat(pc_online=False)
        assert result == ARISMode.EDGE
        assert mm.mode == ARISMode.EDGE

    def test_mode_manager_transitioning(self):
        from core.neural.mode import ModeManager, ARISMode
        mm = ModeManager()
        mm.update_heartbeat(pc_online=True)
        assert mm.mode == ARISMode.PRIMARY
        result = mm.update_heartbeat(pc_online=False)
        assert result == ARISMode.TRANSITIONING

    def test_mode_manager_reconnect(self):
        from core.neural.mode import ModeManager, ARISMode
        mm = ModeManager()
        mm.update_heartbeat(pc_online=True)
        mm.update_heartbeat(pc_online=False)
        mm.update_heartbeat(pc_online=False)
        mm.update_heartbeat(pc_online=False)
        assert mm.mode == ARISMode.EDGE
        result = mm.update_heartbeat(pc_online=True)
        assert result == ARISMode.PRIMARY
        assert mm.consecutive_failures == 0

    def test_mode_snapshot(self):
        from core.neural.mode import ModeManager
        mm = ModeManager()
        snap = mm.snapshot()
        assert "mode" in snap
        assert "pc_online" in snap
        assert "consecutive_failures" in snap

    def test_mode_transition_log(self):
        from core.neural.mode import ModeManager
        mm = ModeManager()
        mm.update_heartbeat(pc_online=True)
        mm.update_heartbeat(pc_online=False)
        assert len(mm.transitions) >= 1

    def test_mode_listener(self):
        from core.neural.mode import ModeManager
        mm = ModeManager()
        changes = []
        mm.on_transition(lambda old, new: changes.append((old, new)))
        mm.update_heartbeat(pc_online=True)
        assert len(changes) >= 1

    def test_mode_force(self):
        from core.neural.mode import ModeManager, ARISMode
        mm = ModeManager()
        mm.force_mode(ARISMode.PRIMARY)
        assert mm.mode == ARISMode.PRIMARY

    def test_mode_describe(self):
        from core.neural.mode import ModeManager
        mm = ModeManager()
        desc = mm.describe()
        assert isinstance(desc, str)
        assert len(desc) > 0


# ── Phase B: Capabilities ─────────────────────────────────────

class TestCapabilityRegistry:
    def test_has_default_capabilities(self):
        from core.neural.capabilities import CapabilityRegistry
        cr = CapabilityRegistry()
        assert cr.get("chat") is not None
        assert cr.get("memory_add") is not None
        assert cr.get("cll1_status") is not None
        assert cr.get("pc_list_files") is not None

    def test_edge_mode_has_chat(self):
        from core.neural.capabilities import CapabilityRegistry
        from core.neural.mode import ARISMode
        cr = CapabilityRegistry()
        assert cr.is_available("chat", ARISMode.EDGE)

    def test_edge_mode_no_pc_files(self):
        from core.neural.capabilities import CapabilityRegistry
        from core.neural.mode import ARISMode
        cr = CapabilityRegistry()
        assert not cr.is_available("pc_list_files", ARISMode.EDGE)

    def test_primary_mode_has_all(self):
        from core.neural.capabilities import CapabilityRegistry
        from core.neural.mode import ARISMode
        cr = CapabilityRegistry()
        assert cr.is_available("chat", ARISMode.PRIMARY)
        assert cr.is_available("pc_list_files", ARISMode.PRIMARY)
        assert cr.is_available("cll1_status", ARISMode.PRIMARY)

    def test_permission_levels(self):
        from core.neural.capabilities import CapabilityRegistry, PermissionLevel
        cr = CapabilityRegistry()
        assert cr.get_permission("chat") == PermissionLevel.SAFE
        assert cr.get_permission("pc_run_command") == PermissionLevel.HIGH
        assert cr.get_permission("pc_shutdown") == PermissionLevel.CRITICAL

    def test_requires_confirmation(self):
        from core.neural.capabilities import CapabilityRegistry
        cr = CapabilityRegistry()
        assert cr.requires_confirmation("pc_shutdown")
        assert cr.requires_confirmation("wake_on_lan")
        assert not cr.requires_confirmation("chat")

    def test_available_in_mode(self):
        from core.neural.capabilities import CapabilityRegistry
        from core.neural.mode import ARISMode
        cr = CapabilityRegistry()
        edge_caps = cr.available_in_mode(ARISMode.EDGE)
        primary_caps = cr.available_in_mode(ARISMode.PRIMARY)
        assert len(edge_caps) < len(primary_caps)

    def test_by_category(self):
        from core.neural.capabilities import CapabilityRegistry
        cr = CapabilityRegistry()
        cats = cr.by_category()
        assert "core" in cats
        assert "cll1" in cats
        assert "pc" in cats

    def test_to_dict(self):
        from core.neural.capabilities import CapabilityRegistry
        from core.neural.mode import ARISMode
        cr = CapabilityRegistry()
        d = cr.to_dict(ARISMode.EDGE)
        assert "chat" in d
        assert "modes" in d["chat"]

    def test_unknown_capability(self):
        from core.neural.capabilities import CapabilityRegistry
        from core.neural.mode import ARISMode
        cr = CapabilityRegistry()
        assert not cr.is_available("nonexistent_tool", ARISMode.PRIMARY)


# ── Phase C: CLL1 Tools ───────────────────────────────────────

class TestCLL1Tools:
    def test_tool_registry_has_all(self):
        from core.tools.cll1_tools import CLL1_TOOLS
        expected = [
            "cll1_status", "cll1_system_info", "cll1_uptime",
            "cll1_disk", "cll1_memory", "cll1_cpu", "cll1_network",
            "cll1_process_list", "cll1_process_status", "cll1_process_stop",
            "cll1_service_list", "cll1_service_status", "cll1_service_restart",
            "cll1_list_files", "cll1_read_file", "cll1_write_file",
            "cll1_edit_file", "cll1_create_directory", "cll1_copy_file",
            "cll1_move_file", "cll1_search_files",
            "cll1_terminal", "cll1_logs", "cll1_logs_search",
        ]
        for name in expected:
            assert name in CLL1_TOOLS, f"Missing: {name}"

    def test_tool_has_permission(self):
        from core.tools.cll1_tools import CLL1_TOOLS
        for name, info in CLL1_TOOLS.items():
            assert "permission" in info, f"{name} missing permission"
            assert "fn" in info, f"{name} missing fn"

    def test_execute_unknown_tool(self):
        from core.tools.cll1_tools import execute_cll1_tool
        result = execute_cll1_tool("nonexistent")
        assert result["ok"] is False

    def test_tool_permissions_correct(self):
        from core.tools.cll1_tools import CLL1_TOOLS
        safe_tools = ["cll1_status", "cll1_uptime", "cll1_list_files", "cll1_read_file"]
        for t in safe_tools:
            assert CLL1_TOOLS[t]["permission"] == "safe", f"{t} should be safe"
        high_tools = ["cll1_terminal", "cll1_process_stop", "cll1_service_restart"]
        for t in high_tools:
            assert CLL1_TOOLS[t]["permission"] == "high", f"{t} should be high"


# ── Phase D: Email Tools ──────────────────────────────────────

class TestEmailTools:
    def test_email_handler_status(self):
        from core.tools.email_tools import EmailHandler
        handler = EmailHandler()
        result = handler.status()
        assert result["ok"] is True
        assert "providers" in result

    def test_email_list_no_provider(self):
        from core.tools.email_tools import EmailHandler
        handler = EmailHandler()
        result = handler.list_emails(provider="nonexistent")
        assert result["ok"] is False

    def test_email_search_no_provider(self):
        from core.tools.email_tools import EmailHandler
        handler = EmailHandler()
        result = handler.search_emails(query="test", provider="nonexistent")
        assert result["ok"] is False

    def test_email_read_no_provider(self):
        from core.tools.email_tools import EmailHandler
        handler = EmailHandler()
        result = handler.read_email(email_id="123", provider="nonexistent")
        assert result["ok"] is False

    def test_execute_email_tool(self):
        from core.tools.email_tools import execute_email_tool
        result = execute_email_tool("email_status")
        assert result["ok"] is True

    def test_execute_unknown_email_tool(self):
        from core.tools.email_tools import execute_email_tool
        result = execute_email_tool("nonexistent")
        assert result["ok"] is False

    def test_email_credentials_storage(self):
        from core.tools.email_tools import EmailCredentials
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "creds.json")
            creds = EmailCredentials(path)
            creds.store("gmail", "test@gmail.com", {"access_token": "fake"})
            assert creds.has_provider("gmail")
            assert creds.get("gmail") is not None
            assert not creds.has_provider("outlook")
            creds.remove("gmail")
            assert not creds.has_provider("gmail")


# ── Phase E: Agent Loop ───────────────────────────────────────

class TestAgentLoop:
    def test_agent_task_creation(self):
        from core.neural.agent_loop import AgentTask
        task = AgentTask(objective="test task")
        assert task.objective == "test task"
        assert task.status.value == "pending"
        assert task.iteration == 0

    def test_agent_task_to_dict(self):
        from core.neural.agent_loop import AgentTask
        task = AgentTask(objective="test")
        d = task.to_dict()
        assert "task_id" in d
        assert "objective" in d
        assert "status" in d

    def test_tool_call_record(self):
        from core.neural.agent_loop import ToolCall, StepStatus
        tc = ToolCall(tool_name="test", parameters={"a": 1})
        tc.status = StepStatus.SUCCESS
        tc.started_at = time.time()
        tc.completed_at = tc.started_at + 0.5
        d = tc.to_dict()
        assert d["tool"] == "test"
        assert d["status"] == "success"

    def test_tool_call_redaction(self):
        from core.neural.agent_loop import _redact_params
        params = {"password": "secret123", "normal": "value", "token": "abc"}
        redacted = _redact_params(params)
        assert redacted["password"] == "***REDACTED***"
        assert redacted["token"] == "***REDACTED***"
        assert redacted["normal"] == "value"

    def test_agent_loop_basic(self):
        from core.neural.agent_loop import AgentLoop, TaskStatus

        def mock_tool(name, params):
            return {"ok": True, "result": f"executed {name}"}

        def mock_llm(messages):
            return '{"completed": true, "response": "Done!", "verification": "tested"}'

        loop = AgentLoop(tool_executor=mock_tool, llm_sender=mock_llm)
        task = loop.run("test objective")
        assert task.status == TaskStatus.COMPLETED
        assert "Done" in task.final_response

    def test_agent_loop_tool_call(self):
        from core.neural.agent_loop import AgentLoop, TaskStatus

        call_count = [0]

        def mock_tool(name, params):
            call_count[0] += 1
            return {"ok": True, "result": "ok"}

        def mock_llm(messages):
            if call_count[0] == 0:
                return '{"tool": "test_tool", "parameters": {"arg": 1}}'
            return '{"completed": true, "response": "Finished"}'

        loop = AgentLoop(tool_executor=mock_tool, llm_sender=mock_llm)
        task = loop.run("do something")
        assert task.status == TaskStatus.COMPLETED
        assert len(task.tool_calls) >= 1

    def test_agent_loop_error_handling(self):
        from core.neural.agent_loop import AgentLoop, TaskStatus

        def mock_tool(name, params):
            return {"ok": False, "error": "tool failed"}

        def mock_llm(messages):
            if not any("Resultados anteriores" in str(m.get("content", "")) for m in messages):
                return '{"tool": "failing_tool", "parameters": {}}'
            return '{"completed": true, "response": "Ack"}'

        loop = AgentLoop(tool_executor=mock_tool, llm_sender=mock_llm)
        task = loop.run("test errors")
        assert len(task.errors) > 0

    def test_agent_loop_cancellation(self):
        from core.neural.agent_loop import AgentLoop, AgentTask, TaskStatus

        def mock_tool(name, params):
            return {"ok": True}

        def mock_llm(messages):
            return '{"tool": "x", "parameters": {}}'

        loop = AgentLoop(tool_executor=mock_tool, llm_sender=mock_llm)
        task = loop.create_task("cancel me")
        task.status = TaskStatus.RUNNING
        assert loop.cancel_task(task.task_id)
        assert task.status == TaskStatus.CANCELLED

    def test_agent_loop_list_tasks(self):
        from core.neural.agent_loop import AgentLoop
        def mock_tool(n, p): return {"ok": True}
        def mock_llm(m): return '{"completed": true, "response": "ok"}'
        loop = AgentLoop(tool_executor=mock_tool, llm_sender=mock_llm)
        loop.run("task 1")
        loop.run("task 2")
        tasks = loop.list_tasks()
        assert len(tasks) == 2


# ── Phase F: PC Tools ─────────────────────────────────────────

class TestPCTools:
    def test_tool_registry(self):
        from core.tools.pc_tools import PC_TOOLS
        expected = [
            "pc_list_files", "pc_read_file", "pc_write_file",
            "pc_edit_file", "pc_create_directory", "pc_search_files",
            "pc_copy_file", "pc_move_file", "pc_delete_file",
            "pc_run_command", "pc_processes", "pc_services",
            "pc_logs", "pc_system_status",
        ]
        for name in expected:
            assert name in PC_TOOLS, f"Missing: {name}"

    def test_tool_permissions(self):
        from core.tools.pc_tools import PC_TOOLS
        safe = ["pc_list_files", "pc_read_file", "pc_search_files", "pc_processes"]
        for t in safe:
            assert PC_TOOLS[t]["permission"] == "safe"
        moderate = ["pc_write_file", "pc_edit_file", "pc_create_directory"]
        for t in moderate:
            assert PC_TOOLS[t]["permission"] == "moderate"
        high = ["pc_run_command", "pc_delete_file"]
        for t in high:
            assert PC_TOOLS[t]["permission"] == "high"

    def test_list_files(self):
        from core.tools.pc_tools import pc_list_files
        result = pc_list_files({"path": "."})
        assert result["ok"] is True
        assert "files" in result

    def test_read_file(self):
        from core.tools.pc_tools import pc_read_file
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            result = pc_read_file({"path": path})
            assert result["ok"] is True
            assert "hello world" in result["content"]
        finally:
            os.unlink(path)

    def test_write_file(self):
        from core.tools.pc_tools import pc_write_file
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            path = f.name
        try:
            result = pc_write_file({"path": path, "content": "test data"})
            assert result["ok"] is True
            with open(path) as f:
                assert f.read() == "test data"
        finally:
            os.unlink(path)

    def test_edit_file(self):
        from core.tools.pc_tools import pc_edit_file
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            result = pc_edit_file({"path": path, "old": "world", "new": "there"})
            assert result["ok"] is True
            with open(path) as f:
                assert "hello there" in f.read()
        finally:
            os.unlink(path)

    def test_create_directory(self):
        from core.tools.pc_tools import pc_create_directory
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = os.path.join(tmpdir, "newdir")
            result = pc_create_directory({"path": new_dir})
            assert result["ok"] is True
            assert os.path.isdir(new_dir)

    def test_search_files(self):
        from core.tools.pc_tools import pc_search_files
        result = pc_search_files({"path": ".", "pattern": "*.py"})
        assert result["ok"] is True
        assert result["count"] > 0

    def test_copy_file(self):
        from core.tools.pc_tools import pc_copy_file
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "src.txt")
            dst = os.path.join(tmpdir, "dst.txt")
            with open(src, "w") as f:
                f.write("copy me")
            result = pc_copy_file({"source": src, "destination": dst})
            assert result["ok"] is True
            assert os.path.exists(dst)

    def test_move_file(self):
        from core.tools.pc_tools import pc_move_file
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "src.txt")
            dst = os.path.join(tmpdir, "dst.txt")
            with open(src, "w") as f:
                f.write("move me")
            result = pc_move_file({"source": src, "destination": dst})
            assert result["ok"] is True
            assert os.path.exists(dst)
            assert not os.path.exists(src)

    def test_delete_file(self):
        from core.tools.pc_tools import pc_delete_file
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            path = f.name
        result = pc_delete_file({"path": path})
        assert result["ok"] is True
        assert not os.path.exists(path)

    def test_run_command(self):
        from core.tools.pc_tools import pc_run_command
        result = pc_run_command({"command": "echo hello"})
        assert result["ok"] is True
        assert "hello" in result["stdout"]

    def test_system_status(self):
        from core.tools.pc_tools import pc_system_status
        result = pc_system_status()
        assert result["ok"] is True

    def test_execute_unknown_tool(self):
        from core.tools.pc_tools import execute_pc_tool
        result = execute_pc_tool("nonexistent")
        assert result["ok"] is False


# ── Tool Executor ─────────────────────────────────────────────

class TestToolExecutor:
    def test_executor_registers_tools(self):
        from core.tools.executor import ToolExecutor
        executor = ToolExecutor()
        tools = executor.list_available_tools()
        assert "chat" in tools
        assert "cll1_status" in tools

    def test_executor_rejects_unknown(self):
        from core.tools.executor import ToolExecutor
        executor = ToolExecutor()
        result = executor.execute("nonexistent_tool")
        assert result["ok"] is False

    def test_executor_recent_calls(self):
        from core.tools.executor import ToolExecutor
        executor = ToolExecutor()
        executor.execute("nonexistent")
        calls = executor.get_recent_calls()
        assert len(calls) >= 1

    def test_executor_confirmation_required(self):
        from core.tools.executor import ToolExecutor
        executor = ToolExecutor()
        result = executor.execute("pc_shutdown")
        assert result.get("requires_confirmation") is True

    def test_executor_confirmation_proceeds(self):
        from core.tools.executor import ToolExecutor
        executor = ToolExecutor()
        result = executor.execute("pc_shutdown", {"_confirmed": True})
        assert "requires_confirmation" not in result


# ── Integration: ModeManager + Router ─────────────────────────

class TestModeIntegration:
    def test_mode_singleton(self):
        from core.neural.mode import get_mode_manager, ModeManager
        mm1 = get_mode_manager()
        mm2 = get_mode_manager()
        assert mm1 is mm2

    def test_capability_registry_singleton(self):
        from core.neural.capabilities import get_capability_registry, CapabilityRegistry
        cr1 = get_capability_registry()
        cr2 = get_capability_registry()
        assert cr1 is cr2

    def test_mode_affects_capabilities(self):
        from core.neural.mode import ModeManager, ARISMode
        from core.neural.capabilities import CapabilityRegistry
        mm = ModeManager()
        cr = CapabilityRegistry()
        mm.force_mode(ARISMode.EDGE)
        assert not cr.is_available("pc_list_files", mm.mode)
        mm.force_mode(ARISMode.PRIMARY)
        assert cr.is_available("pc_list_files", mm.mode)


# ── Phase G: Wake-on-LAN ─────────────────────────────────────

class TestWakeOnLan:
    def test_wol_configured(self):
        import os
        os.environ["WOL_MAC_ADDRESS"] = "AA:BB:CC:DD:EE:FF"
        try:
            from core.tools.wol import WakeOnLan
            wol = WakeOnLan()
            assert wol.configured
        finally:
            del os.environ["WOL_MAC_ADDRESS"]

    def test_wol_not_configured(self):
        import os
        os.environ.pop("WOL_MAC_ADDRESS", None)
        try:
            from core.tools.wol import WakeOnLan
            wol = WakeOnLan()
            assert not wol.configured
        finally:
            pass

    def test_wol_parse_mac(self):
        from core.tools.wol import WakeOnLan
        wol = WakeOnLan()
        result = wol._parse_mac("AA:BB:CC:DD:EE:FF")
        assert result == b"\xaa\xbb\xcc\xdd\xee\xff"

    def test_wol_parse_mac_dashes(self):
        from core.tools.wol import WakeOnLan
        wol = WakeOnLan()
        result = wol._parse_mac("AA-BB-CC-DD-EE-FF")
        assert result == b"\xaa\xbb\xcc\xdd\xee\xff"

    def test_wol_build_magic_packet(self):
        from core.tools.wol import WakeOnLan
        wol = WakeOnLan()
        mac = bytes.fromhex("aabbccddeeff")
        packet = wol._build_magic_packet(mac)
        assert len(packet) == 102  # 6 + 16*6
        assert packet[:6] == b"\xff" * 6
        assert packet[6:12] == mac

    def test_wol_requires_mac(self):
        import os
        os.environ.pop("WOL_MAC_ADDRESS", None)
        try:
            from core.tools.wol import WakeOnLan
            wol = WakeOnLan()
            result = wol.send_magic_packet()
            assert result["ok"] is False
            assert "MAC" in result["error"]
        finally:
            pass

    def test_wol_status(self):
        from core.tools.wol import WakeOnLan
        wol = WakeOnLan()
        status = wol.status()
        assert "configured" in status
        assert "broadcast" in status
        assert "port" in status

    def test_wol_execute(self):
        import os
        os.environ["WOL_MAC_ADDRESS"] = "AA:BB:CC:DD:EE:FF"
        try:
            from core.tools.wol import execute_wol
            result = execute_wol({})
            assert result["ok"] is True
            assert result["sent"] > 0
        finally:
            del os.environ["WOL_MAC_ADDRESS"]

    def test_wol_execute_with_custom_mac(self):
        from core.tools.wol import execute_wol
        result = execute_wol({"mac": "11:22:33:44:55:66"})
        assert result["ok"] is True

    def test_wol_gemini(self):
        from core.tools.wol import WakeOnLan
        wol = WakeOnLan()
        wol._mac_address = "AA:BB:CC:DD:EE:FF"
        assert wol.configured

    def test_wol_singleton(self):
        from core.tools.wol import get_wol
        w1 = get_wol()
        w2 = get_wol()
        assert w1 is w2


# ── Phase H: PC Control ──────────────────────────────────────

class TestPCControl:
    def _mock_ctrl(self):
        """Cria PCControl com _run_ps mockado (NUNCA executa de verdade)."""
        from core.tools.pc_control import PCControl
        ctrl = PCControl()
        ctrl._run_ps = lambda cmd, timeout=10: {"ok": True, "stdout": "mocked"}
        # No Linux o PCControl usa _run_argv (systemctl/loginctl) em vez do PowerShell.
        ctrl._run_argv = lambda argv, timeout=10: {"ok": True, "stdout": "mocked"}
        return ctrl

    def test_pc_control_singleton(self):
        from core.tools.pc_control import get_pc_control
        c1 = get_pc_control()
        c2 = get_pc_control()
        assert c1 is c2

    def test_pc_status_safe(self):
        ctrl = self._mock_ctrl()
        result = ctrl.pc_status()
        assert result["ok"] is True

    def test_pc_shutdown_requires_confirmation(self):
        ctrl = self._mock_ctrl()
        result = ctrl.pc_shutdown()
        assert result["ok"] is False
        assert result.get("requires_confirmation") is True

    def test_pc_shutdown_with_confirmation_mock(self):
        ctrl = self._mock_ctrl()
        result = ctrl.pc_shutdown({"_confirmed": True})
        assert result["ok"] is True

    def test_pc_restart_requires_confirmation(self):
        ctrl = self._mock_ctrl()
        result = ctrl.pc_restart()
        assert result["ok"] is False
        assert result.get("requires_confirmation") is True

    def test_pc_lock_requires_confirmation(self):
        ctrl = self._mock_ctrl()
        result = ctrl.pc_lock()
        assert result["ok"] is False
        assert result.get("requires_confirmation") is True

    def test_pc_sleep_requires_confirmation(self):
        ctrl = self._mock_ctrl()
        result = ctrl.pc_sleep()
        assert result["ok"] is False
        assert result.get("requires_confirmation") is True

    def test_pc_lock_with_confirmation_mock(self):
        ctrl = self._mock_ctrl()
        result = ctrl.pc_lock({"_confirmed": True})
        assert result["ok"] is True

    def test_pc_sleep_with_confirmation_mock(self):
        ctrl = self._mock_ctrl()
        result = ctrl.pc_sleep({"_confirmed": True})
        assert result["ok"] is True

    def test_pc_control_status(self):
        ctrl = self._mock_ctrl()
        ctrl.pc_lock({"_confirmed": True})
        status = ctrl.status()
        assert status["last_action"] == "lock"

    def test_real_execution_disabled_by_default(self):
        from core.tools.pc_control import PCControl
        ctrl = PCControl()
        assert ctrl._real_execution is False
        result = ctrl._run_ps("echo test")
        assert result["ok"] is False
        assert "disabled" in result["error"]


# ── Executor integration with G/H ─────────────────────────────

class TestExecutorGHDangerous:
    def test_executor_wol_in_edge(self):
        import os
        from core.tools.executor import ToolExecutor
        from core.neural.mode import get_mode_manager, ARISMode
        mm = get_mode_manager()
        mm.force_mode(ARISMode.EDGE)
        executor = ToolExecutor()
        os.environ["WOL_MAC_ADDRESS"] = "AA:BB:CC:DD:EE:FF"
        try:
            result = executor.execute("wake_on_lan")
            assert result["ok"] is True
        finally:
            del os.environ["WOL_MAC_ADDRESS"]
            mm.force_mode(ARISMode.UNKNOWN)

    def test_executor_pc_shutdown_requires_confirmation(self):
        from core.tools.executor import ToolExecutor
        from core.neural.mode import get_mode_manager, ARISMode
        mm = get_mode_manager()
        mm.force_mode(ARISMode.PRIMARY)
        executor = ToolExecutor()
        result = executor.execute("pc_shutdown")
        assert result.get("requires_confirmation") is True
        mm.force_mode(ARISMode.UNKNOWN)

    def test_executor_pc_shutdown_no_real_exec(self):
        """pc_shutdown via executor must NEVER actually shut down PC."""
        from core.tools.executor import ToolExecutor
        from core.neural.mode import get_mode_manager, ARISMode
        mm = get_mode_manager()
        mm.force_mode(ARISMode.PRIMARY)
        executor = ToolExecutor()
        # Without _confirmed — should require confirmation
        result = executor.execute("pc_shutdown")
        assert result.get("requires_confirmation") is True
        # With _confirmed but _real_execution=False — still safe
        result = executor.execute("pc_shutdown", {"_confirmed": True})
        # Should fail because _real_execution is False
        assert result["ok"] is False
        mm.force_mode(ARISMode.UNKNOWN)

    def test_executor_pc_shutdown_requires_confirmation(self):
        from core.tools.executor import ToolExecutor
        from core.neural.mode import get_mode_manager, ARISMode
        mm = get_mode_manager()
        mm.force_mode(ARISMode.PRIMARY)
        executor = ToolExecutor()
        result = executor.execute("pc_shutdown")
        assert result.get("requires_confirmation") is True
        mm.force_mode(ARISMode.UNKNOWN)
