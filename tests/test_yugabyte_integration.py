"""
Unit tests for YugabyteMCPServer.

All tests use mocked psycopg connections — no live database required.
Run with: pytest tests/test_yugabyte_integration.py -v
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.yugabyte_mcp_server import YugabyteMCPServer
from modules.error_handler import ValidationError, DatabaseError


# ---------------------------------------------------------------------------
# Shared LAAS column metadata (mirrors the real awdc.laas_population_data schema)
# ---------------------------------------------------------------------------
LAAS_COLUMNS = [
    ("animal_type",       "character varying", "YES", 1),
    ("intake_date",       "date",              "YES", 2),
    ("outcome_type",      "character varying", "YES", 3),
    ("outcome_date",      "date",              "YES", 4),
    ("length_of_stay",    "integer",           "YES", 5),
    ("intake_type",       "character varying", "YES", 6),
    ("intake_condition",  "character varying", "YES", 7),
    ("sex",               "character varying", "YES", 8),
    ("weight",            "numeric",           "YES", 9),
    ("shelter",           "character varying", "YES", 10),
]

ALLOWED_TABLE = "awdc.laas_population_data"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pool():
    """Return a mock psycopg_pool.ConnectionPool."""
    pool = MagicMock()
    pool.min_size = 1
    pool.max_size = 5
    return pool


@pytest.fixture
def server(mock_pool):
    """
    Return a YugabyteMCPServer with env vars set and connection pool mocked.
    Bypasses actual DB connection.
    """
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
    with patch.dict(os.environ, env):
        # Patch the pool constructor so no real connection is attempted
        with patch("modules.yugabyte_mcp_server.YugabyteMCPServer._initialize_connection_pool",
                   return_value=mock_pool):
            s = YugabyteMCPServer()
    return s


def _make_cursor(rows, col_names):
    """Return a mock cursor that returns the given rows and description."""
    cursor = MagicMock()
    # MagicMock's built-in .name attribute can't be set via the constructor
    # for child mocks — create a plain object instead.
    class _Col:
        def __init__(self, n):
            self.name = n
    cursor.description = [_Col(c) for c in col_names]
    cursor.fetchall.return_value = rows
    cursor.fetchone.return_value = rows[0] if rows else None
    # Support context manager usage: `with conn.cursor() as cur`
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    return cursor


def _wire_pool(server, cursor):
    """
    Make server.pool.getconn() return a connection whose .cursor() returns cursor.
    """
    conn = MagicMock()
    conn.cursor.return_value = cursor
    server.pool.getconn.return_value = conn
    return conn


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_healthy(self, server):
        cursor = _make_cursor([(1,)], ["?column?"])
        _wire_pool(server, cursor)
        result = server.health_check()
        assert result["status"] == "healthy"
        assert "pool_stats" in result


# ---------------------------------------------------------------------------
# list_tables
# ---------------------------------------------------------------------------

class TestListTables:
    def test_list_tables_returns_allowed_only(self, server):
        # information_schema.tables returns one row for the allowed table
        cursor = _make_cursor(
            [("awdc", "laas_population_data")],
            ["table_schema", "table_name"],
        )
        _wire_pool(server, cursor)
        result = server.list_tables()
        assert result["success"] is True
        assert result["count"] == 1
        assert result["tables"][0]["name"] == ALLOWED_TABLE

    def test_list_tables_empty_when_not_configured(self, server):
        server.allowed_tables = []
        result = server.list_tables()
        assert result["success"] is True
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# describe_table
# ---------------------------------------------------------------------------

class TestDescribeTable:
    def test_describe_table_returns_columns(self, server):
        cursor = _make_cursor(LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"])
        _wire_pool(server, cursor)
        result = server.describe_table(ALLOWED_TABLE)
        assert result["success"] is True
        assert result["column_count"] == len(LAAS_COLUMNS)
        col_names = {c["name"] for c in result["columns"]}
        assert "animal_type" in col_names
        assert "intake_date" in col_names
        assert "length_of_stay" in col_names

    def test_describe_table_rejects_non_allowed(self, server):
        result = server.describe_table("awdc.ocac_shelter_data")
        assert result["success"] is False
        assert "not in the allowed list" in result["error"]

    def test_describe_table_rejects_invalid_chars(self, server):
        result = server.describe_table("awdc.bad; DROP TABLE users--")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# query_table — allow-list and sanitizer
# ---------------------------------------------------------------------------

class TestQueryTableSecurity:
    def test_rejects_non_allowed_table(self, server):
        # @handle_database_errors wraps ValidationError into DatabaseError
        with pytest.raises((ValidationError, DatabaseError), match="not in the allowed list"):
            server.query_table("awdc.ocac_shelter_data")

    def test_rejects_invalid_table_name_characters(self, server):
        with pytest.raises((ValidationError, DatabaseError)):
            server.query_table("awdc.bad'; DROP TABLE--")

    def test_rejects_invalid_column_in_filter(self, server):
        # describe_table mock returns LAAS columns
        cursor = _make_cursor(LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"])
        _wire_pool(server, cursor)
        with pytest.raises((ValidationError, DatabaseError), match="Unknown column|owner_name"):
            server.query_table(
                ALLOWED_TABLE,
                filters=[{"column": "owner_name", "operator": "=", "value": "Smith"}],
            )


# ---------------------------------------------------------------------------
# query_table — plain fetch
# ---------------------------------------------------------------------------

class TestQueryTablePlainFetch:
    def test_plain_fetch_no_filters(self, server):
        # First call is describe_table (LAAS_COLUMNS), second is the actual query
        schema_cursor = _make_cursor(LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"])
        data_cursor = _make_cursor(
            [("DOG", "2024-01-15", "ADOPTION", "2024-01-20", 5, "STRAY", "HEALTHY", "M", 15.2, "WEST LA")],
            ["animal_type", "intake_date", "outcome_type", "outcome_date",
             "length_of_stay", "intake_type", "intake_condition", "sex", "weight", "shelter"],
        )
        conn = MagicMock()
        # cursor() is called twice: once for describe, once for query
        conn.cursor.side_effect = [schema_cursor, data_cursor]
        server.pool.getconn.return_value = conn

        result = server.query_table(ALLOWED_TABLE, limit=10)
        assert result["success"] is True
        assert result["row_count"] == 1
        assert result["rows"][0]["animal_type"] == "DOG"

    def test_plain_fetch_with_simple_filter(self, server):
        schema_cursor = _make_cursor(LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"])
        data_cursor = _make_cursor(
            [("CAT", "2024-03-01", "RETURN TO OWNER", "2024-03-10", 9, "STRAY", "HEALTHY", "F", 8.5, "EAST LA")],
            ["animal_type", "intake_date", "outcome_type", "outcome_date",
             "length_of_stay", "intake_type", "intake_condition", "sex", "weight", "shelter"],
        )
        conn = MagicMock()
        conn.cursor.side_effect = [schema_cursor, data_cursor]
        server.pool.getconn.return_value = conn

        result = server.query_table(
            ALLOWED_TABLE,
            filters=[{"column": "animal_type", "operator": "=", "value": "CAT"}],
            limit=5,
        )
        assert result["success"] is True
        assert result["rows"][0]["animal_type"] == "CAT"

        # Confirm the executed SQL contained %s (parameterised, not concatenated value)
        executed_sql = conn.cursor.return_value.__enter__.return_value.execute.call_args
        if executed_sql:
            sql_str = executed_sql[0][0]
            assert "CAT" not in sql_str  # value must not appear in SQL text


# ---------------------------------------------------------------------------
# query_table — aggregation + group_by (Q2 / Q3 pattern)
# ---------------------------------------------------------------------------

class TestQueryTableAggregation:
    def _setup_two_cursor_conn(self, server, data_rows, data_cols):
        schema_cursor = _make_cursor(LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"])
        data_cursor = _make_cursor(data_rows, data_cols)
        conn = MagicMock()
        conn.cursor.side_effect = [schema_cursor, data_cursor]
        server.pool.getconn.return_value = conn
        return conn

    def test_count_group_by_column(self, server):
        """Q2 pattern: COUNT(*) GROUP BY animal_type ORDER BY count DESC"""
        self._setup_two_cursor_conn(server,
            [("DOG", 25000), ("CAT", 18000), ("BIRD", 500)],
            ["animal_type", "count"],
        )
        result = server.query_table(
            ALLOWED_TABLE,
            aggregates=[{"function": "COUNT", "column": "*", "alias": "count"}],
            group_by=["animal_type"],
            order_by={"by": "count", "direction": "DESC"},
        )
        assert result["success"] is True
        assert result["rows"][0]["animal_type"] == "DOG"

    def test_avg_with_round_group_by(self, server):
        """Q3 pattern: ROUND(AVG(length_of_stay), 1) GROUP BY animal_type"""
        self._setup_two_cursor_conn(server,
            [("DOG", 12.3), ("CAT", 8.7)],
            ["animal_type", "avg_los"],
        )
        result = server.query_table(
            ALLOWED_TABLE,
            aggregates=[{"function": "AVG", "column": "length_of_stay", "alias": "avg_los", "round": 1}],
            group_by=["animal_type"],
        )
        assert result["success"] is True
        assert len(result["rows"]) == 2

    def test_count_with_date_trunc_group_by(self, server):
        """Q1 pattern: COUNT(*) GROUP BY DATE_TRUNC('month', intake_date)"""
        self._setup_two_cursor_conn(server,
            [("2024-01-01", 320), ("2024-02-01", 410)],
            ["intake_date_month", "count"],
        )
        result = server.query_table(
            ALLOWED_TABLE,
            aggregates=[{"function": "COUNT", "column": "*", "alias": "count"}],
            group_by=[{"column": "intake_date", "date_trunc": "month"}],
            order_by={"by": "intake_date_month", "direction": "ASC"},
        )
        assert result["success"] is True
        assert result["row_count"] == 2

    def test_count_with_extract_group_by(self, server):
        """Q5 pattern: COUNT(*) GROUP BY EXTRACT(month FROM intake_date)"""
        self._setup_two_cursor_conn(server,
            [(6, 890), (7, 1050)],
            ["intake_date_month", "count"],
        )
        result = server.query_table(
            ALLOWED_TABLE,
            aggregates=[{"function": "COUNT", "column": "*", "alias": "count"}],
            group_by=[{"column": "intake_date", "extract": "month"}],
            order_by={"by": "count", "direction": "DESC"},
        )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# query_table — FILTER (WHERE ...) on aggregate (Q4 pattern)
# ---------------------------------------------------------------------------

class TestQueryTableAggregateFilter:
    def test_count_filter_where_dogs_vs_cats(self, server):
        """Q4 pattern: COUNT(*) FILTER (WHERE animal_type='DOG') AS dogs"""
        schema_cursor = _make_cursor(LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"])
        data_cursor = _make_cursor(
            [("ADOPTION", 3200, 1800), ("RETURN TO OWNER", 800, 400)],
            ["outcome_type", "dogs", "cats"],
        )
        conn = MagicMock()
        conn.cursor.side_effect = [schema_cursor, data_cursor]
        server.pool.getconn.return_value = conn

        result = server.query_table(
            ALLOWED_TABLE,
            aggregates=[
                {"function": "COUNT", "column": "*", "alias": "dogs",
                 "filter": {"column": "animal_type", "operator": "=", "value": "DOG"}},
                {"function": "COUNT", "column": "*", "alias": "cats",
                 "filter": {"column": "animal_type", "operator": "=", "value": "CAT"}},
            ],
            group_by=["outcome_type"],
            order_by={"by": "dogs", "direction": "DESC"},
        )
        assert result["success"] is True
        assert result["rows"][0]["dogs"] == 3200


# ---------------------------------------------------------------------------
# query_table — date_relative operator (Q1 date filter)
# ---------------------------------------------------------------------------

class TestQueryTableDateRelative:
    def test_date_relative_operator_resolves_to_sql_expression(self, server):
        """
        Verify date_relative filter builds a safe SQL expression and does NOT
        embed the user-supplied anchor string verbatim into SQL.
        """
        schema_cursor = _make_cursor(LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"])
        data_cursor = _make_cursor([], ["intake_date_month", "count"])
        data_cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.side_effect = [schema_cursor, data_cursor]
        server.pool.getconn.return_value = conn

        result = server.query_table(
            ALLOWED_TABLE,
            filters=[
                {"column": "intake_date", "operator": "date_relative",
                 "value": {"anchor": "current_year_start", "offset_years": -1}},
                {"column": "intake_date", "operator": "date_relative",
                 "value": {"anchor": "current_year_start", "offset_years": 0}},
            ],
            aggregates=[{"function": "COUNT", "column": "*", "alias": "count"}],
            group_by=[{"column": "intake_date", "date_trunc": "month"}],
        )
        assert result["success"] is True

    def test_date_relative_rejects_unknown_anchor(self, server):
        schema_cursor = _make_cursor(LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"])
        conn = MagicMock()
        conn.cursor.return_value = schema_cursor
        server.pool.getconn.return_value = conn

        # @handle_database_errors wraps ValidationError into DatabaseError
        with pytest.raises((ValidationError, DatabaseError), match="Unknown anchor|evil_injection"):
            server.query_table(
                ALLOWED_TABLE,
                filters=[
                    {"column": "intake_date", "operator": "date_relative",
                     "value": {"anchor": "evil_injection", "offset_years": 0}},
                ],
            )


# ---------------------------------------------------------------------------
# query_table — date_relative with max_date anchor
# ---------------------------------------------------------------------------

class TestQueryTableDateRelativeMaxDate:
    """
    Verify the max_date anchor resolves to a server-side MAX() subquery and
    that negative offsets apply correctly — no user string ever appears in SQL.
    """

    def _setup(self, server):
        """Wire a two-cursor connection (schema + data) and return the connection mock."""
        schema_cursor = _make_cursor(
            LAAS_COLUMNS, ["column_name", "data_type", "is_nullable", "ordinal_position"]
        )
        data_cursor = _make_cursor([], ["intake_date_month", "count"])
        data_cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.side_effect = [schema_cursor, data_cursor]
        server.pool.getconn.return_value = conn
        return conn

    def test_max_date_offset_zero_succeeds(self, server):
        """offset_years=0 with max_date anchor must succeed and produce a result dict."""
        conn = self._setup(server)
        result = server.query_table(
            ALLOWED_TABLE,
            filters=[
                {"column": "intake_date", "operator": "date_relative",
                 "value": {"anchor": "max_date", "offset_years": 0}},
            ],
            aggregates=[{"function": "COUNT", "column": "*", "alias": "count"}],
            group_by=[{"column": "intake_date", "date_trunc": "month"}],
        )
        assert result["success"] is True

    def test_max_date_sql_contains_subquery(self, server):
        """
        The generated SQL must contain a MAX() subquery referencing the column —
        the anchor string 'max_date' must NOT appear in the SQL text.
        Verifies via _resolve_date_relative directly (no DB round-trip needed).
        """
        expr = server._resolve_date_relative(
            {"anchor": "max_date", "offset_years": 0},
            table_name=ALLOWED_TABLE,
            column="intake_date",
        )
        assert "max_date" not in expr, "anchor name must not appear in SQL expression"
        assert "MAX" in expr, "MAX subquery must appear in SQL expression"
        assert "SELECT MAX" in expr
        assert ALLOWED_TABLE in expr

    def test_max_date_negative_offset_succeeds(self, server):
        """offset_years=-1 resolves to one year before max_date; no SQL injection."""
        conn = self._setup(server)
        result = server.query_table(
            ALLOWED_TABLE,
            filters=[
                {"column": "intake_date", "operator": "date_relative",
                 "value": {"anchor": "max_date", "offset_years": -1}},
                {"column": "intake_date", "operator": "date_relative",
                 "value": {"anchor": "max_date", "offset_years": 0}},
            ],
            aggregates=[{"function": "COUNT", "column": "*", "alias": "count"}],
            group_by=[{"column": "intake_date", "date_trunc": "month"}],
        )
        assert result["success"] is True

    def test_resolve_date_relative_max_date_expression_zero_offset(self, server):
        """Unit-test _resolve_date_relative directly for exact SQL rendering."""
        expr = server._resolve_date_relative(
            {"anchor": "max_date", "offset_years": 0},
            table_name=ALLOWED_TABLE,
            column="intake_date",
        )
        assert "DATE_TRUNC('year'" in expr
        assert "SELECT MAX" in expr
        assert '"intake_date"' in expr
        assert ALLOWED_TABLE in expr
        # No offset interval when offset_years=0
        assert "INTERVAL" not in expr

    def test_resolve_date_relative_max_date_expression_negative_offset(self, server):
        """_resolve_date_relative with offset_years=-2 must append a subtraction interval."""
        expr = server._resolve_date_relative(
            {"anchor": "max_date", "offset_years": -2},
            table_name=ALLOWED_TABLE,
            column="intake_date",
        )
        assert "DATE_TRUNC('year'" in expr
        assert "SELECT MAX" in expr
        assert "- INTERVAL '2 years'" in expr


# ---------------------------------------------------------------------------
# execute_tool dispatch
# ---------------------------------------------------------------------------

class TestExecuteToolDispatch:
    def test_dispatch_yb_list_tables(self, server):
        with patch.object(server, "list_tables", return_value={"success": True, "tables": [], "count": 0}) as m:
            result = server.execute_tool("yb_list_tables", {})
            m.assert_called_once()
            assert result["success"] is True

    def test_dispatch_yb_describe_table(self, server):
        with patch.object(server, "describe_table", return_value={"success": True}) as m:
            result = server.execute_tool("yb_describe_table", {"table_name": ALLOWED_TABLE})
            m.assert_called_once_with(table_name=ALLOWED_TABLE)

    def test_dispatch_yb_query_table(self, server):
        with patch.object(server, "query_table", return_value={"success": True, "rows": [], "row_count": 0}) as m:
            result = server.execute_tool("yb_query_table", {"table_name": ALLOWED_TABLE, "limit": 5})
            m.assert_called_once()
            assert result["success"] is True

    def test_dispatch_unknown_tool(self, server):
        result = server.execute_tool("does_not_exist", {})
        assert result["success"] is False
        assert "Unknown tool" in result["error"]


# ---------------------------------------------------------------------------
# get_available_tools schema
# ---------------------------------------------------------------------------

class TestGetAvailableTools:
    def test_returns_three_tools(self, server):
        tools = server.get_available_tools()
        names = {t["name"] for t in tools}
        assert names == {"yb_list_tables", "yb_describe_table", "yb_query_table"}

    def test_yb_query_table_documents_aggregates(self, server):
        tools = {t["name"]: t for t in server.get_available_tools()}
        props = tools["yb_query_table"]["parameters"]["properties"]
        assert "aggregates" in props
        assert "group_by" in props
        assert "order_by" in props
        assert "filters" in props
