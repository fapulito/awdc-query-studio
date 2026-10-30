"""
tests/test_sql_transparency.py

Tests for the executed-SQL transparency feature:
  1. query_table() returns executed_sql byte-identical to the statement
     passed to cur.execute, and parameters matches.
  2. process_conversation() harvests and deduplicates query metadata.
  3. /api/chat includes a top-level `queries` array in the JSON response.

No live database, no LLM API key required.
"""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub heavy optional deps (same pattern as test_chat_yb_tools.py)
# ---------------------------------------------------------------------------
import types as _types


def _stub_package(name: str):
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        dotted = ".".join(parts[:i])
        if dotted not in sys.modules:
            if i < len(parts):
                mod = _types.ModuleType(dotted)
                mod.__path__ = []
                sys.modules[dotted] = mod
            else:
                sys.modules[dotted] = MagicMock()


for _heavy in (
    "oracledb",
    "psycopg",
    "psycopg_pool",
    "authlib.integrations.flask_client",
    "authlib.integrations.base_client",
    "stripe",
):
    _stub_package(_heavy)


# ---------------------------------------------------------------------------
# Shared LAAS column metadata
# ---------------------------------------------------------------------------
LAAS_COLUMNS = [
    ("animal_type",      "character varying", "YES", 1),
    ("intake_date",      "date",              "YES", 2),
    ("outcome_type",     "character varying", "YES", 3),
    ("outcome_date",     "date",              "YES", 4),
    ("length_of_stay",   "integer",           "YES", 5),
    ("intake_type",      "character varying", "YES", 6),
    ("intake_condition", "character varying", "YES", 7),
    ("sex",              "character varying", "YES", 8),
    ("weight",           "numeric",           "YES", 9),
    ("shelter",          "character varying", "YES", 10),
]

ALLOWED_TABLE = "awdc.laas_population_data"


def _make_cursor(rows, col_names):
    class _Col:
        def __init__(self, n):
            self.name = n

    cursor = MagicMock()
    cursor.description = [_Col(c) for c in col_names]
    cursor.fetchall.return_value = rows
    cursor.fetchone.return_value = rows[0] if rows else None
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    return cursor


def _wire_pool(server, schema_cursor, data_cursor):
    conn = MagicMock()
    conn.cursor.side_effect = [schema_cursor, data_cursor]
    server.pool.getconn.return_value = conn
    return conn


# ---------------------------------------------------------------------------
# Fixture: YugabyteMCPServer with mocked pool
# ---------------------------------------------------------------------------

@pytest.fixture
def server():
    from modules.yugabyte_mcp_server import YugabyteMCPServer

    env = {
        "YUGABYTE_HOST": "test.yugabyte.cloud",
        "YUGABYTE_PORT": "5433",
        "YUGABYTE_DBNAME": "yugabyte",
        "YUGABYTE_USER": "readonly_user",
        "YUGABYTE_PASSWORD": "secret",
        "YUGABYTE_SSLMODE": "require",
        "YUGABYTE_ALLOWED_TABLES": ALLOWED_TABLE,
        "MAX_RESULT_SIZE": "1000",
        "QUERY_TIMEOUT": "5",
    }
    mock_pool = MagicMock()
    mock_pool.min_size = 1
    mock_pool.max_size = 5
    with patch.dict(os.environ, env):
        with patch(
            "modules.yugabyte_mcp_server.YugabyteMCPServer._initialize_connection_pool",
            return_value=mock_pool,
        ):
            s = YugabyteMCPServer()
    return s


# ===========================================================================
# 1. query_table — executed_sql and parameters
# ===========================================================================

class TestQueryTableExecutedSql:
    """
    query_table() must return executed_sql == the exact string passed to
    cur.execute, and parameters must contain the same values (as strings).
    """

    def test_executed_sql_present_in_result(self, server):
        schema_cur = _make_cursor(
            LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"]
        )
        data_cur = _make_cursor(
            [("DOG", "2024-01-15", "ADOPTION", "2024-01-20", 5, "STRAY", "HEALTHY", "M", 15.2, "WEST LA")],
            ["animal_type", "intake_date", "outcome_type", "outcome_date",
             "length_of_stay", "intake_type", "intake_condition", "sex", "weight", "shelter"],
        )
        _wire_pool(server, schema_cur, data_cur)

        result = server.query_table(ALLOWED_TABLE, limit=10)

        assert result["success"] is True
        assert "executed_sql" in result
        assert isinstance(result["executed_sql"], str)
        assert len(result["executed_sql"]) > 0

    def test_executed_sql_byte_identical_to_execute_call(self, server):
        """
        The executed_sql string in the result must be exactly the string
        that was passed to cur.execute(), byte for byte.
        """
        schema_cur = _make_cursor(
            LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"]
        )
        data_cur = _make_cursor([], ["animal_type", "intake_date"])
        data_cur.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.side_effect = [schema_cur, data_cur]
        server.pool.getconn.return_value = conn

        result = server.query_table(
            ALLOWED_TABLE,
            filters=[{"column": "animal_type", "operator": "=", "value": "CAT"}],
            limit=5,
        )

        assert result["success"] is True

        # Retrieve the SQL that was actually passed to cursor.execute
        # data_cur is the second cursor created; get its execute call args
        execute_call_args = data_cur.execute.call_args
        assert execute_call_args is not None, "cur.execute was not called on data cursor"
        actual_sql_passed = execute_call_args[0][0]  # first positional arg to execute

        assert result["executed_sql"] == actual_sql_passed, (
            "executed_sql in result does not match the SQL passed to cur.execute"
        )

    def test_parameters_present_and_json_safe(self, server):
        schema_cur = _make_cursor(
            LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"]
        )
        data_cur = _make_cursor([], ["animal_type"])
        data_cur.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.side_effect = [schema_cur, data_cur]
        server.pool.getconn.return_value = conn

        result = server.query_table(
            ALLOWED_TABLE,
            filters=[{"column": "animal_type", "operator": "=", "value": "DOG"}],
            limit=20,
        )

        assert result["success"] is True
        assert "parameters" in result
        assert isinstance(result["parameters"], list)
        # All values must be JSON-serialisable strings
        for p in result["parameters"]:
            assert isinstance(p, str)
        # JSON round-trip must not raise
        json.dumps(result["parameters"])

    def test_parameters_match_execute_call(self, server):
        """parameters in the result must correspond to what was passed to execute."""
        schema_cur = _make_cursor(
            LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"]
        )
        data_cur = _make_cursor([], ["animal_type"])
        data_cur.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.side_effect = [schema_cur, data_cur]
        server.pool.getconn.return_value = conn

        result = server.query_table(
            ALLOWED_TABLE,
            filters=[{"column": "animal_type", "operator": "=", "value": "BIRD"}],
            limit=5,
        )

        execute_call_args = data_cur.execute.call_args
        actual_params = list(execute_call_args[0][1])  # second positional arg: params list

        # result["parameters"] contains str() of each actual param
        assert result["parameters"] == [str(p) for p in actual_params]

    def test_no_executed_sql_in_list_tables(self, server):
        """list_tables must NOT include executed_sql (only query_table gets it)."""
        cursor = _make_cursor(
            [("awdc", "laas_population_data")],
            ["table_schema", "table_name"],
        )
        server.pool.getconn.return_value.__enter__ = MagicMock(
            return_value=MagicMock(cursor=MagicMock(return_value=cursor))
        )
        # list_tables uses getconn differently — just assert that even if it ran:
        result = server.list_tables()
        assert "executed_sql" not in result

    def test_no_executed_sql_in_describe_table(self, server):
        """describe_table must NOT include executed_sql."""
        cursor = _make_cursor(
            LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"]
        )
        conn = MagicMock()
        conn.cursor.return_value = cursor
        server.pool.getconn.return_value = conn

        result = server.describe_table(ALLOWED_TABLE)
        assert "executed_sql" not in result


# ===========================================================================
# 2. process_conversation — query harvesting and deduplication
# ===========================================================================

class TestProcessConversationQueryHarvesting:
    """
    process_conversation() must collect executed_sql / parameters from
    yb_query_table results into the third return value and deduplicate by
    (sql, parameters).
    """

    def _make_llm_service(self):
        from modules.llm_service import LLMService, LLMConfig

        cfg = LLMConfig(api_key="test-key", model="gpt-4o", provider="openai")
        svc = LLMService(cfg)
        return svc

    def _make_query_tool_result(self, sql, params, row_count=3, table=ALLOWED_TABLE):
        """Return an object mimicking MCPClient.execute_tool() result for yb_query_table."""
        result = MagicMock()
        result.result = {
            "success": True,
            "table_name": table,
            "columns": ["animal_type"],
            "rows": [{"animal_type": "DOG"}] * row_count,
            "row_count": row_count,
            "limited": False,
            "executed_sql": sql,
            "parameters": [str(p) for p in params],
        }
        result.error = None
        return result

    def test_queries_collected_from_yb_query_table(self):
        """A single yb_query_table call produces one entry in queries."""
        svc = self._make_llm_service()

        _sql = 'SELECT * FROM "awdc"."laas_population_data" LIMIT %s'
        _params = ["10"]
        tool_result = self._make_query_tool_result(_sql, _params)

        def fake_executor(tool_name, parameters):
            return tool_result

        # Stub send_message to immediately return "no more tool calls"
        def fake_send(messages, tools=None, tool_choice=None):
            # First call: return a tool-call response; second call: return final text
            if not hasattr(fake_send, "_called"):
                fake_send._called = True
                return {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_001",
                            "function": {"name": "yb_query_table", "arguments": '{"table_name": "' + ALLOWED_TABLE + '"}'},
                        }
                    ],
                }
            return {"content": "Here are the results.", "tool_calls": []}

        with patch.object(svc, "send_message", side_effect=fake_send):
            with patch.object(svc, "parse_response") as mock_parse:
                # First parse: yields one tool request; second: no tool requests
                mock_tool_req = MagicMock()
                mock_tool_req.tool_name = "yb_query_table"
                mock_tool_req.parameters = {"table_name": ALLOWED_TABLE}
                mock_tool_req.id = "call_001"
                mock_parse.side_effect = [
                    (None, [mock_tool_req]),
                    ("Here are the results.", []),
                ]

                content, tool_calls, queries, _result = svc.process_conversation(
                    conversation_history=[{"role": "user", "content": "list dogs"}],
                    available_tools=[],
                    tool_executor=fake_executor,
                )

        assert len(queries) == 1
        assert queries[0]["sql"] == _sql
        assert queries[0]["parameters"] == _params
        assert queries[0]["row_count"] == 3
        assert queries[0]["table"] == ALLOWED_TABLE

    def test_duplicate_queries_deduplicated(self):
        """The same (sql, parameters) pair appearing twice produces only one entry."""
        svc = self._make_llm_service()

        _sql = 'SELECT COUNT(*) AS "count" FROM "awdc"."laas_population_data" LIMIT %s'
        _params = ["1000"]
        tool_result = self._make_query_tool_result(_sql, _params, row_count=1)

        call_count = [0]

        def fake_executor(tool_name, parameters):
            call_count[0] += 1
            return tool_result

        mock_tool_req_a = MagicMock()
        mock_tool_req_a.tool_name = "yb_query_table"
        mock_tool_req_a.parameters = {"table_name": ALLOWED_TABLE}
        mock_tool_req_a.id = "call_001"

        mock_tool_req_b = MagicMock()
        mock_tool_req_b.tool_name = "yb_query_table"
        mock_tool_req_b.parameters = {"table_name": ALLOWED_TABLE}
        mock_tool_req_b.id = "call_002"

        with patch.object(svc, "send_message", return_value={"content": None, "tool_calls": []}):
            with patch.object(svc, "parse_response") as mock_parse:
                mock_parse.side_effect = [
                    (None, [mock_tool_req_a, mock_tool_req_b]),
                    ("Done.", []),
                ]
                content, tool_calls, queries, _result = svc.process_conversation(
                    conversation_history=[{"role": "user", "content": "count"}],
                    available_tools=[],
                    tool_executor=fake_executor,
                )

        assert len(queries) == 1, f"Expected 1 deduplicated query, got {len(queries)}"

    def test_non_query_tools_not_in_queries(self):
        """yb_list_tables and yb_describe_table must not produce query entries."""
        svc = self._make_llm_service()

        list_result = MagicMock()
        list_result.result = {"success": True, "tables": [], "count": 0}
        list_result.error = None

        mock_tool_req = MagicMock()
        mock_tool_req.tool_name = "yb_list_tables"
        mock_tool_req.parameters = {}
        mock_tool_req.id = "call_001"

        with patch.object(svc, "send_message", return_value={"content": None, "tool_calls": []}):
            with patch.object(svc, "parse_response") as mock_parse:
                mock_parse.side_effect = [
                    (None, [mock_tool_req]),
                    ("No query tables.", []),
                ]
                content, tool_calls, queries, _result = svc.process_conversation(
                    conversation_history=[{"role": "user", "content": "list tables"}],
                    available_tools=[],
                    tool_executor=lambda tool_name, parameters: list_result,
                )

        assert queries == []

    def test_queries_empty_when_no_tools_called(self):
        svc = self._make_llm_service()

        with patch.object(svc, "send_message", return_value={"content": "Hello!", "tool_calls": []}):
            with patch.object(svc, "parse_response", return_value=("Hello!", [])):
                content, tool_calls, queries, _result = svc.process_conversation(
                    conversation_history=[{"role": "user", "content": "hi"}],
                    available_tools=[],
                    tool_executor=lambda **kw: None,
                )

        assert queries == []
        assert content == "Hello!"


# ===========================================================================
# 3. /api/chat — queries field in JSON response
# ===========================================================================

def _import_index_module():
    import importlib

    if "api.index" in sys.modules:
        return sys.modules["api.index"]
    with patch("config.validate_config_on_startup", return_value=None):
        import api.index as idx_module  # noqa: F401

    return sys.modules["api.index"]


def _make_chat_app_with_queries():
    from modules.mcp_client import MCPClient

    yb_stub = MagicMock()
    yb_stub.get_available_tools.return_value = [
        {
            "name": "yb_query_table",
            "description": "Query",
            "parameters": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
        }
    ]
    yb_stub.execute_tool.return_value = {"success": True, "rows": [], "row_count": 0}

    real_mcp = MCPClient([])
    real_mcp.register_in_process_server("yugabyte", yb_stub)

    idx = _import_index_module()
    idx.mcp_client = real_mcp
    idx._services_initialized = True

    mock_llm = MagicMock()
    mock_llm.create_system_prompt.return_value = "You are helpful."
    idx.llm_service = mock_llm

    idx.app.config["TESTING"] = True
    idx.app.config["SECRET_KEY"] = "test-secret-key-for-tests-only"

    return idx.app, mock_llm


class TestChatRouteQueriesField:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app, self.mock_llm = _make_chat_app_with_queries()
        self.client = self.app.test_client()

    def _auth_session(self, client):
        from datetime import datetime, timedelta

        with client.session_transaction() as sess:
            sess["user"] = {
                "id": "test-user-1",
                "email": "test@example.com",
                "name": "Test User",
                "provider": "google",
            }
            sess["token_expires_at"] = (datetime.utcnow() + timedelta(hours=1)).timestamp()

    def test_queries_field_present_and_empty_when_no_db_calls(self):
        """When no yb_query_table is called, queries must be an empty list."""
        # Return a 4-tuple (current interface)
        self.mock_llm.process_conversation.return_value = (
            "Here is the answer.",
            [],
            [],
            None,
        )

        self._auth_session(self.client)
        resp = self.client.post(
            "/api/chat",
            json={"message": "hello"},
            content_type="application/json",
        )

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "queries" in data
        assert data["queries"] == []

    def test_queries_field_populated_when_db_query_ran(self):
        """When process_conversation returns queries, they appear in the API response."""
        sample_queries = [
            {
                "table": ALLOWED_TABLE,
                "sql": 'SELECT COUNT(*) AS "count" FROM "awdc"."laas_population_data" LIMIT %s',
                "parameters": ["1000"],
                "row_count": 1,
            }
        ]
        self.mock_llm.process_conversation.return_value = (
            "There were 1000 dogs.",
            [{"tool_name": "yb_query_table"}],
            sample_queries,
            None,
        )

        self._auth_session(self.client)
        resp = self.client.post(
            "/api/chat",
            json={"message": "how many dogs?"},
            content_type="application/json",
        )

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "queries" in data
        assert len(data["queries"]) == 1
        q = data["queries"][0]
        assert q["table"] == ALLOWED_TABLE
        assert "SELECT" in q["sql"]
        assert q["row_count"] == 1
        assert isinstance(q["parameters"], list)
