"""
Oracle MCP Server — structured-filter safety tests.

These tests verify that query_view:
  1. Rejects unknown / non-allow-listed view names.
  2. Rejects unknown column names in filters.
  3. Rejects disallowed operators.
  4. Never interpolates user-supplied values — they must always appear in
     bind_params, never in the returned SQL fragment.
  5. Handles BETWEEN and IN correctly (right placeholders, right param count).
  6. Accepts valid filters end-to-end (schema validation stub, execution stub).

No live database is required.  oracledb is stubbed at module import time.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Stub out oracledb BEFORE modules/oracle_mcp_server.py is imported so that
# the "import oracledb" at module level does not fail.
# ---------------------------------------------------------------------------
import types as _types

def _stub_leaf(name: str):
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

for _dep in ("oracledb", "psycopg", "psycopg_pool",
             "authlib.integrations.flask_client",
             "authlib.integrations.base_client"):
    _stub_leaf(_dep)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Patch the serverless_optimizer to avoid side-effects at import time.
with patch("modules.serverless_optimizer.get_connection_cache", return_value={}):
    with patch("modules.serverless_optimizer.optimize_cold_start", lambda f: f):
        from modules.oracle_mcp_server import OracleMCPServer, _VALID_FILTER_OPERATORS

from modules.error_handler import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_VIEW = "MY_SAFE_VIEW"
COLUMNS = {"id", "status", "created_date", "amount"}


def _make_server(allowed_views=(ALLOWED_VIEW,)):
    """Return an OracleMCPServer instance that never touches a real database."""
    server = OracleMCPServer.__new__(OracleMCPServer)
    server.connection_string = "host:1521/svc"
    server.username = "usr"
    server.password = "pw"
    server.allowed_views = list(allowed_views)
    server.query_timeout = 5
    server.max_result_size = 1000
    server.pool = MagicMock()
    return server


def _make_cursor(rows, col_names):
    """Build a mock cursor that returns *rows* and whose description matches *col_names*."""
    cur = MagicMock()
    cur.description = [(name,) for name in col_names]
    cur.fetchall.return_value = rows
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    return cur


def _wire_pool(server, cursor):
    """
    Make server._get_connection() yield a mock connection that returns
    *cursor* from conn.cursor().
    """
    conn = MagicMock()
    conn.cursor.return_value = cursor
    from contextlib import contextmanager

    @contextmanager
    def _fake_conn():
        yield conn

    server._get_connection = _fake_conn
    return conn


# ---------------------------------------------------------------------------
# Unit tests: _build_filter_sql
# ---------------------------------------------------------------------------

class TestBuildFilterSql:
    """_build_filter_sql validates identifiers & operators and builds safe SQL."""

    def setup_method(self):
        self.server = _make_server()
        self.valid_columns = COLUMNS

    # -----------------------------------------------------------------------
    # Column validation
    # -----------------------------------------------------------------------

    def test_rejects_unknown_column(self):
        bind = {}
        with pytest.raises(ValidationError, match="Unknown column"):
            self.server._build_filter_sql(
                {"column": "secret_col", "operator": "=", "value": "x"},
                bind,
                self.valid_columns,
            )

    def test_rejects_column_with_sql_injection_payload(self):
        """Columns with SQL metacharacters must fail the data-dict lookup."""
        bind = {}
        for bad_col in ("id; DROP TABLE users--", "id' OR '1'='1", "id UNION SELECT"):
            with pytest.raises(ValidationError, match="Unknown column"):
                self.server._build_filter_sql(
                    {"column": bad_col, "operator": "=", "value": 1},
                    bind,
                    self.valid_columns,
                )

    # -----------------------------------------------------------------------
    # Operator validation
    # -----------------------------------------------------------------------

    def test_rejects_unknown_operator(self):
        bind = {}
        with pytest.raises(ValidationError, match="Invalid operator"):
            self.server._build_filter_sql(
                {"column": "id", "operator": "LIKE", "value": "%x%"},
                bind,
                self.valid_columns,
            )

    def test_rejects_freeform_sql_as_operator(self):
        """A UNION or subquery injected as an operator must be rejected."""
        bind = {}
        for bad_op in ("= 1 OR 1=1 --", "UNION SELECT", "; DROP TABLE"):
            with pytest.raises(ValidationError, match="Invalid operator"):
                self.server._build_filter_sql(
                    {"column": "status", "operator": bad_op, "value": "active"},
                    bind,
                    self.valid_columns,
                )

    # -----------------------------------------------------------------------
    # Simple scalar comparison
    # -----------------------------------------------------------------------

    def test_eq_binds_value_not_interpolated(self):
        bind = {}
        fragment = self.server._build_filter_sql(
            {"column": "status", "operator": "=", "value": "'; DROP TABLE users--"},
            bind,
            self.valid_columns,
        )
        # The dangerous string must NOT appear in the SQL fragment
        assert "DROP" not in fragment
        assert "users" not in fragment
        # But it MUST appear as a bind parameter value
        assert "'; DROP TABLE users--" in bind.values()
        # The fragment uses a named :param placeholder
        assert ":param_" in fragment

    def test_eq_fragment_structure(self):
        bind = {}
        fragment = self.server._build_filter_sql(
            {"column": "id", "operator": "=", "value": 42},
            bind,
            self.valid_columns,
        )
        assert fragment.startswith('"ID"')
        assert "= :param_" in fragment
        assert 42 in bind.values()

    def test_gte_produces_correct_operator(self):
        bind = {}
        fragment = self.server._build_filter_sql(
            {"column": "amount", "operator": ">=", "value": 100},
            bind,
            self.valid_columns,
        )
        assert ">= :param_" in fragment
        assert 100 in bind.values()

    # -----------------------------------------------------------------------
    # BETWEEN
    # -----------------------------------------------------------------------

    def test_between_binds_two_values(self):
        bind = {}
        fragment = self.server._build_filter_sql(
            {"column": "amount", "operator": "BETWEEN", "value": [10, 99]},
            bind,
            self.valid_columns,
        )
        assert "BETWEEN :" in fragment
        assert "AND :" in fragment
        values = list(bind.values())
        assert 10 in values
        assert 99 in values

    def test_between_rejects_non_list_value(self):
        bind = {}
        with pytest.raises(ValidationError, match="BETWEEN requires"):
            self.server._build_filter_sql(
                {"column": "amount", "operator": "BETWEEN", "value": 50},
                bind,
                self.valid_columns,
            )

    def test_between_rejects_list_of_wrong_length(self):
        bind = {}
        with pytest.raises(ValidationError, match="BETWEEN requires"):
            self.server._build_filter_sql(
                {"column": "amount", "operator": "BETWEEN", "value": [1, 2, 3]},
                bind,
                self.valid_columns,
            )

    # -----------------------------------------------------------------------
    # IN
    # -----------------------------------------------------------------------

    def test_in_binds_each_value(self):
        bind = {}
        fragment = self.server._build_filter_sql(
            {"column": "status", "operator": "IN",
             "value": ["OPEN", "PENDING", "'; DROP TABLE--"]},
            bind,
            self.valid_columns,
        )
        # Dangerous string must be bound, not in the SQL
        assert "DROP" not in fragment
        assert "'; DROP TABLE--" in bind.values()
        # Three placeholders
        assert fragment.count(":param_") == 3

    def test_in_rejects_empty_list(self):
        bind = {}
        with pytest.raises(ValidationError, match="non-empty list"):
            self.server._build_filter_sql(
                {"column": "status", "operator": "IN", "value": []},
                bind,
                self.valid_columns,
            )

    def test_in_rejects_scalar_value(self):
        bind = {}
        with pytest.raises(ValidationError, match="non-empty list"):
            self.server._build_filter_sql(
                {"column": "status", "operator": "IN", "value": "OPEN"},
                bind,
                self.valid_columns,
            )

    # -----------------------------------------------------------------------
    # Param isolation across multiple filters
    # -----------------------------------------------------------------------

    def test_multiple_filters_use_distinct_param_keys(self):
        """Two filters on the same column must produce independent param keys."""
        bind = {}
        f1 = self.server._build_filter_sql(
            {"column": "amount", "operator": ">=", "value": 10},
            bind, self.valid_columns,
        )
        f2 = self.server._build_filter_sql(
            {"column": "amount", "operator": "<=", "value": 99},
            bind, self.valid_columns,
        )
        # All keys unique
        assert len(set(bind.keys())) == 2
        assert list(bind.values()).count(10) == 1
        assert list(bind.values()).count(99) == 1


# ---------------------------------------------------------------------------
# Unit tests: query_view — validation layer (no DB execution needed)
# ---------------------------------------------------------------------------

class TestQueryViewValidation:
    """query_view rejects bad inputs before touching the database."""

    def setup_method(self):
        self.server = _make_server()

    def test_rejects_non_allowed_view(self):
        """Non-allow-listed view raises ValidationError (re-raised as DatabaseError)."""
        from modules.error_handler import DatabaseError as OracleDBError
        with pytest.raises((ValidationError, OracleDBError)):
            self.server.query_view(view_name="EVIL_VIEW")

    def test_rejects_view_name_with_sql_injection(self):
        """View names with metacharacters are rejected by _sanitize_view_name."""
        from modules.error_handler import DatabaseError as OracleDBError
        with pytest.raises((ValidationError, OracleDBError)):
            self.server.query_view(view_name="MY_VIEW; DROP TABLE users--")

    def test_rejects_view_name_with_spaces(self):
        from modules.error_handler import DatabaseError as OracleDBError
        with pytest.raises((ValidationError, OracleDBError)):
            self.server.query_view(view_name="MY VIEW")

    def test_rejects_unknown_column_in_filter(self):
        """When a filter references a non-existent column, ValidationError is raised."""
        from modules.error_handler import DatabaseError as OracleDBError
        server = _make_server()
        server._get_valid_columns = MagicMock(return_value=COLUMNS)

        with pytest.raises((ValidationError, OracleDBError)):
            server.query_view(
                view_name=ALLOWED_VIEW,
                filters=[{"column": "nonexistent_col", "operator": "=", "value": 1}],
            )

    def test_rejects_disallowed_operator_in_filter(self):
        from modules.error_handler import DatabaseError as OracleDBError
        server = _make_server()
        server._get_valid_columns = MagicMock(return_value=COLUMNS)

        with pytest.raises((ValidationError, OracleDBError)):
            server.query_view(
                view_name=ALLOWED_VIEW,
                filters=[{"column": "id", "operator": "LIKE", "value": "%x%"}],
            )

    def test_where_clause_parameter_not_accepted(self):
        """Confirm that query_view no longer accepts a 'where_clause' keyword."""
        import inspect
        sig = inspect.signature(OracleMCPServer.query_view)
        assert "where_clause" not in sig.parameters, (
            "query_view must not expose a free-form where_clause parameter"
        )


# ---------------------------------------------------------------------------
# Integration tests: query_view — end-to-end with stubbed DB
# ---------------------------------------------------------------------------

class TestQueryViewEndToEnd:
    """query_view produces correct SQL and returns well-formed results."""

    def _setup_server_with_columns(self, columns=COLUMNS):
        server = _make_server()
        server._get_valid_columns = MagicMock(return_value=columns)
        return server

    def test_no_filters_produces_select_star(self):
        server = self._setup_server_with_columns()
        cursor = _make_cursor([], ["ID", "STATUS"])
        _wire_pool(server, cursor)

        result = server.query_view(view_name=ALLOWED_VIEW)

        assert result["success"] is True
        sql = result["executed_sql"]
        # The outer ROWNUM wrapper always adds WHERE ROWNUM <= :_limit.
        # Verify the inner query (before the ROWNUM wrapping) has no user WHERE clause.
        assert "SELECT * FROM" in sql
        assert ALLOWED_VIEW in sql
        # No user filter should produce a WHERE in the inner SELECT
        # The SQL shape is: SELECT * FROM (SELECT * FROM "VIEW") WHERE ROWNUM <= :_limit
        inner_sql = sql.split("WHERE ROWNUM")[0]
        assert "WHERE" not in inner_sql

    def test_eq_filter_value_in_params_not_sql(self):
        server = self._setup_server_with_columns()
        cursor = _make_cursor([], ["ID", "STATUS"])
        _wire_pool(server, cursor)

        injection = "'; DELETE FROM my_safe_view--"
        result = server.query_view(
            view_name=ALLOWED_VIEW,
            filters=[{"column": "status", "operator": "=", "value": injection}],
        )

        assert result["success"] is True
        assert injection not in result["executed_sql"]
        # Param should appear in the serialised params dict
        assert injection in result["parameters"].values()

    def test_between_filter_value_bound(self):
        server = self._setup_server_with_columns()
        cursor = _make_cursor([], ["AMOUNT"])
        _wire_pool(server, cursor)

        result = server.query_view(
            view_name=ALLOWED_VIEW,
            filters=[{"column": "amount", "operator": "BETWEEN", "value": [1, 999]}],
        )

        assert result["success"] is True
        sql = result["executed_sql"]
        assert "BETWEEN" in sql
        assert "1" not in sql.split("ROWNUM")[0]  # value must not be literal in SQL
        assert "999" not in sql.split("ROWNUM")[0]

    def test_in_filter_multiple_values_bound(self):
        server = self._setup_server_with_columns()
        cursor = _make_cursor([], ["STATUS"])
        _wire_pool(server, cursor)

        result = server.query_view(
            view_name=ALLOWED_VIEW,
            filters=[{"column": "status", "operator": "IN", "value": ["A", "B", "C"]}],
        )

        assert result["success"] is True
        assert result["executed_sql"].count(":param_") == 3

    def test_result_row_count(self):
        server = self._setup_server_with_columns()
        rows = [(1, "open"), (2, "closed")]
        cursor = _make_cursor(rows, ["ID", "STATUS"])
        _wire_pool(server, cursor)

        result = server.query_view(view_name=ALLOWED_VIEW)

        assert result["row_count"] == 2
        assert len(result["rows"]) == 2

    def test_limit_appears_in_executed_sql(self):
        server = self._setup_server_with_columns()
        cursor = _make_cursor([], ["ID"])
        _wire_pool(server, cursor)

        result = server.query_view(view_name=ALLOWED_VIEW, limit=7)

        assert result["success"] is True
        assert "ROWNUM" in result["executed_sql"]
        # The limit value must be a bind param, not a literal in SQL
        assert "7" not in result["executed_sql"]
        assert "7" in result["parameters"].values()

    def test_executed_sql_and_parameters_returned(self):
        """query_view must return executed_sql and parameters for transparency."""
        server = self._setup_server_with_columns()
        cursor = _make_cursor([], ["ID"])
        _wire_pool(server, cursor)

        result = server.query_view(view_name=ALLOWED_VIEW)

        assert "executed_sql" in result
        assert "parameters" in result
        assert isinstance(result["executed_sql"], str)
        assert isinstance(result["parameters"], dict)


# ---------------------------------------------------------------------------
# Tool interface tests
# ---------------------------------------------------------------------------

class TestGetAvailableTools:
    """get_available_tools must not expose where_clause."""

    def test_query_view_tool_has_no_where_clause_param(self):
        server = _make_server()
        tools = server.get_available_tools()
        qv_tool = next(t for t in tools if t["name"] == "query_view")
        assert "where_clause" not in qv_tool["parameters"]["properties"]

    def test_query_view_tool_has_filters_param(self):
        server = _make_server()
        tools = server.get_available_tools()
        qv_tool = next(t for t in tools if t["name"] == "query_view")
        assert "filters" in qv_tool["parameters"]["properties"]

    def test_execute_tool_routes_correctly(self):
        server = _make_server()
        server.query_view = MagicMock(return_value={"success": True})
        server.list_views = MagicMock(return_value={"success": True, "views": []})
        server.describe_view = MagicMock(return_value={"success": True, "columns": []})

        server.execute_tool("query_view", {"view_name": ALLOWED_VIEW})
        server.query_view.assert_called_once_with(
            view_name=ALLOWED_VIEW, filters=None, limit=None
        )

        server.execute_tool("list_views", {})
        server.list_views.assert_called_once()

        server.execute_tool("describe_view", {"view_name": ALLOWED_VIEW})
        server.describe_view.assert_called_once_with(view_name=ALLOWED_VIEW)

    def test_execute_tool_unknown_returns_error(self):
        server = _make_server()
        result = server.execute_tool("nonexistent_tool", {})
        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    def test_execute_tool_does_not_pass_where_clause(self):
        """Even if a caller naively passes where_clause, it must not reach query_view."""
        server = _make_server()
        server.query_view = MagicMock(return_value={"success": True})
        # Pass where_clause in parameters dict (legacy caller pattern)
        server.execute_tool(
            "query_view",
            {"view_name": ALLOWED_VIEW, "where_clause": "1=1; DROP TABLE users--"},
        )
        # query_view is called without where_clause
        call_kwargs = server.query_view.call_args[1]
        assert "where_clause" not in call_kwargs
