"""
Regression tests for the /api/chat yb_ tool path in api/index.py.

These tests verify that:
  1. register_in_process_server() populates MCPClient.available_tools with the
     three yb_ tools from YugabyteMCPServer.
  2. MCPClient.execute_tool() routes yb_ calls directly to the in-process server
     (no HTTP required).
  3. The /api/chat route offers yb_ tools to the LLM and executes them when the
     stubbed LLM requests a tool call.

No live database or HTTP server is needed — everything is stubbed.
"""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub out optional heavy dependencies that may not be installed in all envs.
# These stubs must be in sys.modules BEFORE any module that imports them is
# loaded.  We use real ModuleType objects as namespace packages so that
# sub-module attribute look-ups (e.g. authlib.integrations.base_client) work.
# ---------------------------------------------------------------------------
import types as _types

def _stub_package(name: str):
    """Register a MagicMock as a module under the given dotted name, creating
    parent namespace packages as needed."""
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        dotted = ".".join(parts[:i])
        if dotted not in sys.modules:
            if i < len(parts):
                # Intermediate: real namespace module so sub-lookups work
                mod = _types.ModuleType(dotted)
                mod.__path__ = []  # mark as package
                sys.modules[dotted] = mod
            else:
                # Leaf: MagicMock so attribute access on imported names works
                sys.modules[dotted] = MagicMock()

for _heavy in (
    "oracledb",
    "psycopg",
    "psycopg_pool",
    "authlib.integrations.flask_client",
    "authlib.integrations.base_client",
):
    _stub_package(_heavy)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

YB_TOOL_NAMES = {"yb_list_tables", "yb_describe_table", "yb_query_table"}
ALLOWED_TABLE = "awdc.laas_population_data"


def _make_yugabyte_server_stub():
    """Return a minimal in-process stub with the same interface as YugabyteMCPServer."""
    stub = MagicMock()
    stub.get_available_tools.return_value = [
        {
            "name": "yb_list_tables",
            "description": "List tables",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "yb_describe_table",
            "description": "Describe a table",
            "parameters": {
                "type": "object",
                "properties": {"table_name": {"type": "string"}},
                "required": ["table_name"],
            },
        },
        {
            "name": "yb_query_table",
            "description": "Query a table",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["table_name"],
            },
        },
    ]
    stub.execute_tool.return_value = {
        "success": True,
        "tables": [{"name": ALLOWED_TABLE}],
        "count": 1,
    }
    return stub


def _make_empty_mcp_client():
    """Return a real MCPClient with no HTTP server configs."""
    from modules.mcp_client import MCPClient

    return MCPClient([])


# ---------------------------------------------------------------------------
# Unit: MCPClient.register_in_process_server
# ---------------------------------------------------------------------------

class TestRegisterInProcessServer:
    """MCPClient correctly ingests tools from a local server object."""

    def test_tools_appear_in_available_tools(self):
        client = _make_empty_mcp_client()
        stub = _make_yugabyte_server_stub()

        client.register_in_process_server("yugabyte", stub)

        assert YB_TOOL_NAMES.issubset(set(client.available_tools.keys()))

    def test_get_tools_for_llm_returns_yb_tools(self):
        client = _make_empty_mcp_client()
        stub = _make_yugabyte_server_stub()
        client.register_in_process_server("yugabyte", stub)

        tools = client.get_tools_for_llm()
        names = {t["name"] for t in tools}
        assert YB_TOOL_NAMES.issubset(names)

    def test_server_status_set_to_connected(self):
        from modules.mcp_client import ServerStatus

        client = _make_empty_mcp_client()
        stub = _make_yugabyte_server_stub()
        client.register_in_process_server("yugabyte", stub)

        assert client.server_status.get("yugabyte") == ServerStatus.CONNECTED

    def test_idempotent_re_registration(self):
        """Calling register twice (after a warm start) should not duplicate tools."""
        client = _make_empty_mcp_client()
        stub = _make_yugabyte_server_stub()
        client.register_in_process_server("yugabyte", stub)
        client.register_in_process_server("yugabyte", stub)

        yb_tools = [t for t in client.get_tools_for_llm() if t["name"].startswith("yb_")]
        assert len(yb_tools) == 3  # exactly 3, not 6


# ---------------------------------------------------------------------------
# Unit: MCPClient.execute_tool in-process routing
# ---------------------------------------------------------------------------

class TestExecuteToolInProcess:
    """execute_tool() calls the in-process server, not HTTP."""

    def test_routes_yb_list_tables_to_in_process_server(self):
        client = _make_empty_mcp_client()
        stub = _make_yugabyte_server_stub()
        client.register_in_process_server("yugabyte", stub)

        result = client.execute_tool("yb_list_tables", {})

        stub.execute_tool.assert_called_once_with("yb_list_tables", {})
        assert result.result["success"] is True
        assert result.error is None

    def test_routes_yb_describe_table(self):
        client = _make_empty_mcp_client()
        stub = _make_yugabyte_server_stub()
        stub.execute_tool.return_value = {
            "success": True,
            "table_name": ALLOWED_TABLE,
            "columns": [],
            "column_count": 0,
        }
        client.register_in_process_server("yugabyte", stub)

        result = client.execute_tool("yb_describe_table", {"table_name": ALLOWED_TABLE})

        stub.execute_tool.assert_called_once_with(
            "yb_describe_table", {"table_name": ALLOWED_TABLE}
        )
        assert result.result["success"] is True

    def test_routes_yb_query_table(self):
        client = _make_empty_mcp_client()
        stub = _make_yugabyte_server_stub()
        stub.execute_tool.return_value = {
            "success": True,
            "rows": [{"animal_type": "DOG"}],
            "row_count": 1,
        }
        client.register_in_process_server("yugabyte", stub)

        result = client.execute_tool("yb_query_table", {"table_name": ALLOWED_TABLE, "limit": 5})

        assert result.result["rows"][0]["animal_type"] == "DOG"

    def test_does_not_attempt_http_for_in_process_tool(self):
        """The sessions dict must NOT be touched for in-process tools."""
        client = _make_empty_mcp_client()
        stub = _make_yugabyte_server_stub()
        client.register_in_process_server("yugabyte", stub)

        # If HTTP path were hit, accessing sessions['yugabyte'] would raise KeyError;
        # confirm no such access happens.
        client.execute_tool("yb_list_tables", {})
        assert "yugabyte" not in client.sessions


# ---------------------------------------------------------------------------
# Integration: /api/chat route in api/index.py
# ---------------------------------------------------------------------------

def _import_index_module():
    """
    Import api.index exactly once, patching validate_config_on_startup so the
    module-level call doesn't sys.exit when LLM_API_KEY / SECRET_KEY are absent
    in the test environment.  Returns the module.
    """
    import importlib

    # api.index is already imported (cached) — just return it
    if "api.index" in sys.modules:
        return sys.modules["api.index"]

    with patch("config.validate_config_on_startup", return_value=None):
        import api.index as idx_module  # noqa: F401

    return sys.modules["api.index"]


def _make_chat_app():
    """
    Return (app, yb_stub, mcp_client_instance, mock_llm) from api/index.py
    with all heavy services replaced by stubs.
    """
    yb_stub = _make_yugabyte_server_stub()

    # Build a real MCPClient pre-loaded with the yb tools
    from modules.mcp_client import MCPClient

    real_mcp = MCPClient([])
    real_mcp.register_in_process_server("yugabyte", yb_stub)

    idx_module = _import_index_module()

    idx_module.mcp_client = real_mcp
    idx_module._services_initialized = True

    # Stub LLM service
    mock_llm = MagicMock()
    mock_llm.create_system_prompt.return_value = "You are a helpful assistant."
    idx_module.llm_service = mock_llm

    idx_module.app.config["TESTING"] = True
    idx_module.app.config["SECRET_KEY"] = "test-secret-key-for-tests-only"

    return idx_module.app, yb_stub, real_mcp, mock_llm


class TestChatRouteYbTools:
    """End-to-end tests for /api/chat with yb_ tools."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app, self.yb_stub, self.mcp_client, self.mock_llm = _make_chat_app()
        self.client = self.app.test_client()

    def _auth_session(self, client):
        """Push a fake authenticated session into the test client."""
        from datetime import datetime, timedelta

        with client.session_transaction() as sess:
            sess["user"] = {
                "id": "test-user-1",
                "email": "test@example.com",
                "name": "Test User",
                "provider": "google",
            }
            sess["token_expires_at"] = (datetime.utcnow() + timedelta(hours=1)).timestamp()

    # ------------------------------------------------------------------
    # Test 1: yb_ tools are offered to the LLM
    # ------------------------------------------------------------------
    def test_yb_tools_offered_to_llm(self):
        """process_conversation must receive the three yb_ tool definitions."""
        self.mock_llm.process_conversation.return_value = (
            "Here are the tables.",
            [],
        )

        self._auth_session(self.client)
        resp = self.client.post(
            "/api/chat",
            json={"message": "list the tables"},
            content_type="application/json",
        )

        assert resp.status_code == 200

        call_kwargs = self.mock_llm.process_conversation.call_args
        available_tools = call_kwargs[1].get("available_tools") or call_kwargs[0][1]
        tool_names = {t["name"] for t in available_tools}
        assert YB_TOOL_NAMES.issubset(tool_names), (
            f"Expected yb_ tools in available_tools, got: {tool_names}"
        )

    # ------------------------------------------------------------------
    # Test 2: when LLM requests yb_list_tables, it is executed
    # ------------------------------------------------------------------
    def test_yb_list_tables_executed_when_llm_requests_it(self):
        """
        When process_conversation calls the tool_executor with yb_list_tables,
        the in-process server's execute_tool is invoked.
        """
        # Make process_conversation actually call the tool_executor once
        def fake_process(conversation_history, available_tools, tool_executor,
                         system_prompt=None, max_iterations=5):
            tool_result = tool_executor(tool_name="yb_list_tables", parameters={})
            return "Tables fetched.", [{"tool_name": "yb_list_tables", "result": tool_result}]

        self.mock_llm.process_conversation.side_effect = fake_process

        self._auth_session(self.client)
        resp = self.client.post(
            "/api/chat",
            json={"message": "list the tables"},
            content_type="application/json",
        )

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["tool_calls_count"] == 1
        self.yb_stub.execute_tool.assert_called_once_with("yb_list_tables", {})

    # ------------------------------------------------------------------
    # Test 3: yb_describe_table execution
    # ------------------------------------------------------------------
    def test_yb_describe_table_executed_when_llm_requests_it(self):
        self.yb_stub.execute_tool.return_value = {
            "success": True,
            "table_name": ALLOWED_TABLE,
            "columns": [{"name": "animal_type", "type": "character varying"}],
            "column_count": 1,
        }

        def fake_process(conversation_history, available_tools, tool_executor,
                         system_prompt=None, max_iterations=5):
            tool_executor(
                tool_name="yb_describe_table",
                parameters={"table_name": ALLOWED_TABLE},
            )
            return "Schema retrieved.", [{"tool_name": "yb_describe_table"}]

        self.mock_llm.process_conversation.side_effect = fake_process

        self._auth_session(self.client)
        resp = self.client.post(
            "/api/chat",
            json={"message": "describe the table"},
            content_type="application/json",
        )

        assert resp.status_code == 200
        self.yb_stub.execute_tool.assert_called_once_with(
            "yb_describe_table", {"table_name": ALLOWED_TABLE}
        )

    # ------------------------------------------------------------------
    # Test 4: yb_query_table execution
    # ------------------------------------------------------------------
    def test_yb_query_table_executed_when_llm_requests_it(self):
        self.yb_stub.execute_tool.return_value = {
            "success": True,
            "rows": [{"animal_type": "DOG", "intake_date": "2024-01-15"}],
            "row_count": 1,
        }

        def fake_process(conversation_history, available_tools, tool_executor,
                         system_prompt=None, max_iterations=5):
            tool_executor(
                tool_name="yb_query_table",
                parameters={"table_name": ALLOWED_TABLE, "limit": 10},
            )
            return "Query results returned.", [{"tool_name": "yb_query_table"}]

        self.mock_llm.process_conversation.side_effect = fake_process

        self._auth_session(self.client)
        resp = self.client.post(
            "/api/chat",
            json={"message": "how many dogs were there?"},
            content_type="application/json",
        )

        assert resp.status_code == 200
        self.yb_stub.execute_tool.assert_called_once_with(
            "yb_query_table", {"table_name": ALLOWED_TABLE, "limit": 10}
        )

    # ------------------------------------------------------------------
    # Test 5: response still returns even if no tools called
    # ------------------------------------------------------------------
    def test_chat_still_works_without_tool_calls(self):
        self.mock_llm.process_conversation.return_value = (
            "I can help with that, but no tool was needed.",
            [],
        )

        self._auth_session(self.client)
        resp = self.client.post(
            "/api/chat",
            json={"message": "what is 2 + 2?"},
            content_type="application/json",
        )

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["tool_calls_count"] == 0
        assert "response" in data


# ---------------------------------------------------------------------------
# Integration: initialize_services() wires yugabyte_server into mcp_client
# ---------------------------------------------------------------------------

class TestInitializeServicesRegistration:
    """
    Verify that initialize_services() calls register_in_process_server when
    both mcp_client and yugabyte_server are available.
    """

    def test_yb_tools_in_mcp_client_after_init(self):
        idx_module = _import_index_module()
        from modules.mcp_client import MCPClient

        yb_stub = _make_yugabyte_server_stub()
        fresh_mcp = MCPClient([])

        saved_state = {
            "mcp_client": idx_module.mcp_client,
            "yugabyte_server": idx_module.yugabyte_server,
            "llm_service": idx_module.llm_service,
            "pdf_server": idx_module.pdf_server,
            "oracle_server": idx_module.oracle_server,
            "apex_handler": idx_module.apex_handler,
            "_services_initialized": idx_module._services_initialized,
        }

        try:
            # Pre-populate to skip those init branches
            idx_module.mcp_client = fresh_mcp
            idx_module.yugabyte_server = yb_stub
            idx_module.llm_service = MagicMock()
            idx_module.pdf_server = MagicMock()
            idx_module.oracle_server = None
            idx_module.apex_handler = None
            idx_module._services_initialized = False

            with patch("api.index.PDFMCPServer", return_value=MagicMock()):
                with patch("api.index.ApexRestHandler", return_value=MagicMock()):
                    idx_module.initialize_services()

            tool_names = set(fresh_mcp.available_tools.keys())
            assert YB_TOOL_NAMES.issubset(tool_names), (
                f"yb_ tools missing after initialize_services(); got: {tool_names}"
            )
        finally:
            for k, v in saved_state.items():
                setattr(idx_module, k, v)
