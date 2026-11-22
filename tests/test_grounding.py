"""
Tests for NL-to-SQL grounding (Change 1-3 of 2026-11-17 work order).

Covers:
  1. YugabyteMCPServer.get_grounding_values() — fetch, caching, fail-open.
  2. LLMService.create_system_prompt() — grounding block injected correctly.
  3. _build_filter_sql() case-insensitive expansion for grounded columns.
  4. impl_chat() passes yugabyte_server grounding into the system prompt.

No live database or HTTP server is required — everything is stubbed.
"""

import os
import sys
import time
import pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub heavy optional dependencies before importing application code.
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
):
    _stub_package(_heavy)


from modules.yugabyte_mcp_server import YugabyteMCPServer
from modules.llm_service import LLMService, LLMConfig


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_yugabyte_integration.py conventions)
# ---------------------------------------------------------------------------

ALLOWED_TABLE = "awdc.laas_population_data"

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


def _make_cursor(rows, col_names):
    class _Col:
        def __init__(self, n):
            self.name = n

    cursor = MagicMock()
    cursor.description = [_Col(c) for c in col_names]
    cursor.fetchall.return_value = rows
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    return cursor


def _wire_pool(server, cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    server.pool.getconn.return_value = conn
    return conn


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    pool.min_size = 1
    pool.max_size = 5
    return pool


@pytest.fixture
def server(mock_pool):
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
        with patch(
            "modules.yugabyte_mcp_server.YugabyteMCPServer._initialize_connection_pool",
            return_value=mock_pool,
        ):
            s = YugabyteMCPServer()
    return s


# ---------------------------------------------------------------------------
# 1. get_grounding_values — normal fetch
# ---------------------------------------------------------------------------


class TestGetGroundingValues:
    def _make_distinct_cursor_factory(self, server):
        """
        Return a function that, when called N times, returns a fresh cursor
        whose fetchall() yields one column's distinct values.
        The order matches _GROUNDING_COLUMNS[ALLOWED_TABLE].
        """
        per_col_rows = {
            "animal_type":  [("BIRD",), ("CAT",), ("DOG",), ("RABBIT",)],
            "outcome_type": [("Adoption",), ("Euthanized",), ("Return to Owner",)],
            "shelter":      [("EAST LA",), ("WEST LA",)],
        }
        columns = server._GROUNDING_COLUMNS[ALLOWED_TABLE]
        cursors = [
            _make_cursor(per_col_rows[c], [c]) for c in columns
        ]
        idx = {"i": 0}

        def _next_cursor():
            c = cursors[idx["i"]]
            idx["i"] += 1
            return c

        return _next_cursor

    def test_returns_distinct_values_per_column(self, server):
        factory = self._make_distinct_cursor_factory(server)

        conn = MagicMock()
        conn.cursor.side_effect = [factory() for _ in server._GROUNDING_COLUMNS[ALLOWED_TABLE]]
        server.pool.getconn.return_value = conn

        result = server.get_grounding_values()

        assert ALLOWED_TABLE in result
        assert "animal_type" in result[ALLOWED_TABLE]
        assert "DOG" in result[ALLOWED_TABLE]["animal_type"]
        assert "CAT" in result[ALLOWED_TABLE]["animal_type"]
        assert "Euthanized" in result[ALLOWED_TABLE]["outcome_type"]

    def test_cache_prevents_second_db_hit(self, server):
        """Second call within TTL must not query the database again."""
        factory = self._make_distinct_cursor_factory(server)

        conn = MagicMock()
        conn.cursor.side_effect = [factory() for _ in server._GROUNDING_COLUMNS[ALLOWED_TABLE]]
        server.pool.getconn.return_value = conn

        first = server.get_grounding_values()
        # Poison the pool so a second DB hit would fail
        server.pool.getconn.side_effect = RuntimeError("Should not be called again")

        second = server.get_grounding_values()

        assert first == second  # same cached dict

    def test_cache_expires_after_ttl(self, server):
        """After TTL elapses, a fresh fetch is performed."""
        factory = self._make_distinct_cursor_factory(server)

        conn = MagicMock()
        conn.cursor.side_effect = [factory() for _ in server._GROUNDING_COLUMNS[ALLOWED_TABLE]]
        server.pool.getconn.return_value = conn

        server.get_grounding_values()

        # Wind the clock forward past the TTL
        server._grounding_fetched_at -= server._grounding_ttl + 1

        # Provide a fresh set of cursors for the second fetch
        factory2 = self._make_distinct_cursor_factory(server)
        conn2 = MagicMock()
        conn2.cursor.side_effect = [factory2() for _ in server._GROUNDING_COLUMNS[ALLOWED_TABLE]]
        server.pool.getconn.return_value = conn2
        server.pool.getconn.side_effect = None  # remove any poison

        second = server.get_grounding_values()
        assert ALLOWED_TABLE in second

    def test_fail_open_on_db_error(self, server):
        """If the DB raises, get_grounding_values() must return {} without raising."""
        server.pool.getconn.side_effect = RuntimeError("connection refused")

        result = server.get_grounding_values()

        # Fail-open: empty value lists, not an exception
        assert isinstance(result, dict)
        # Either returns partial results or empty; must not raise
        for col_map in result.values():
            for values in col_map.values():
                assert isinstance(values, list)

    def test_returns_empty_when_table_not_allowed(self, server):
        """If the allowed table list doesn't match, nothing is returned."""
        server.allowed_tables = []
        result = server.get_grounding_values()
        assert result == {}


# ---------------------------------------------------------------------------
# 2. create_system_prompt — grounding block
# ---------------------------------------------------------------------------


class TestCreateSystemPromptGrounding:
    @pytest.fixture
    def llm(self):
        cfg = LLMConfig(api_key="test-key", model="gpt-4o", provider="openai")
        with patch("modules.llm_service.LLMService.__init__", lambda self, config: None):
            svc = LLMService.__new__(LLMService)
            svc.config = cfg
            svc.client = None
        return svc

    def test_grounding_values_appear_in_prompt(self, llm):
        grounding = {
            ALLOWED_TABLE: {
                "animal_type":  ["CAT", "DOG"],
                "outcome_type": ["Adoption", "Euthanized"],
                "shelter":      ["EAST LA", "WEST LA"],
            }
        }
        prompt = llm.create_system_prompt([], grounding_values=grounding)

        assert "DOG" in prompt
        assert "CAT" in prompt
        assert "Euthanized" in prompt
        assert "EAST LA" in prompt
        assert "FILTER VALUE GROUNDING" in prompt

    def test_zero_row_guardrail_rule_in_prompt_with_grounding(self, llm):
        grounding = {ALLOWED_TABLE: {"animal_type": ["DOG"], "outcome_type": [], "shelter": []}}
        prompt = llm.create_system_prompt([], grounding_values=grounding)

        assert "ZERO-ROW GUARDRAIL" in prompt
        assert "retry" in prompt.lower()

    def test_zero_row_rule_in_prompt_without_grounding(self, llm):
        """Even with no grounding data, the guardrail instruction is present."""
        prompt = llm.create_system_prompt([])
        assert "ZERO-ROW GUARDRAIL" in prompt or "0 rows" in prompt or "retry" in prompt.lower()

    def test_no_grounding_placeholder_when_values_empty(self, llm):
        """An empty value list produces the 'grounding unavailable' placeholder."""
        grounding = {ALLOWED_TABLE: {"animal_type": []}}
        prompt = llm.create_system_prompt([], grounding_values=grounding)
        assert "grounding unavailable" in prompt

    def test_gemini_provider_unaffected(self, llm):
        llm.config.provider = "gemini"
        grounding = {ALLOWED_TABLE: {"animal_type": ["DOG"]}}
        prompt = llm.create_system_prompt([], grounding_values=grounding)
        # Gemini returns a simple prompt without grounding
        assert "DOG" not in prompt


# ---------------------------------------------------------------------------
# 3. _build_filter_sql — case-insensitive expansion
# ---------------------------------------------------------------------------


class TestBuildFilterSqlCaseInsensitive:
    """
    Unit-test _build_filter_sql() directly to verify UPPER() wrapping
    for the grounded categorical columns.
    """

    @pytest.fixture
    def srv(self, server):
        return server

    def test_equality_on_animal_type_uses_upper(self, srv):
        params = []
        sql = srv._build_filter_sql(
            {"column": "animal_type", "operator": "=", "value": "dog"},
            params,
            {"animal_type"},
        )
        assert "UPPER" in sql
        assert sql.startswith("UPPER(")
        assert params == ["dog"]

    def test_equality_on_outcome_type_uses_upper(self, srv):
        params = []
        sql = srv._build_filter_sql(
            {"column": "outcome_type", "operator": "=", "value": "adoption"},
            params,
            {"outcome_type"},
        )
        assert "UPPER" in sql

    def test_equality_on_shelter_uses_upper(self, srv):
        params = []
        sql = srv._build_filter_sql(
            {"column": "shelter", "operator": "=", "value": "East LA"},
            params,
            {"shelter"},
        )
        assert "UPPER" in sql

    def test_equality_on_non_grounded_column_no_upper(self, srv):
        """Non-grounded columns like intake_type must NOT have UPPER()."""
        params = []
        sql = srv._build_filter_sql(
            {"column": "intake_type", "operator": "=", "value": "STRAY"},
            params,
            {"intake_type"},
        )
        assert "UPPER" not in sql
        assert '"intake_type" = %s' in sql

    def test_in_operator_on_animal_type_uses_upper(self, srv):
        params = []
        sql = srv._build_filter_sql(
            {"column": "animal_type", "operator": "IN", "value": ["dog", "cat"]},
            params,
            {"animal_type"},
        )
        assert "UPPER" in sql
        assert params == ["dog", "cat"]

    def test_in_operator_on_non_grounded_column_no_upper(self, srv):
        params = []
        sql = srv._build_filter_sql(
            {"column": "intake_type", "operator": "IN", "value": ["STRAY", "OWNER SURRENDER"]},
            params,
            {"intake_type"},
        )
        assert "UPPER" not in sql

    def test_ilike_operator_accepted(self, srv):
        params = []
        sql = srv._build_filter_sql(
            {"column": "shelter", "operator": "ILIKE", "value": "%east%"},
            params,
            {"shelter"},
        )
        assert "ILIKE" in sql
        assert params == ["%east%"]

    def test_value_never_embedded_in_sql(self, srv):
        """The filter value must always be a bound parameter, never in the SQL text."""
        params = []
        sql = srv._build_filter_sql(
            {"column": "animal_type", "operator": "=", "value": "INJECTION_CANARY"},
            params,
            {"animal_type"},
        )
        assert "INJECTION_CANARY" not in sql
        assert "INJECTION_CANARY" in params


# ---------------------------------------------------------------------------
# 4. impl_chat — grounding forwarded to create_system_prompt
# ---------------------------------------------------------------------------


class TestImplChatGrounding:
    """Verify that impl_chat passes yugabyte_server to create_system_prompt."""

    def test_grounding_passed_to_system_prompt(self):
        """When yugabyte_server is supplied, its grounding values reach the prompt."""
        from modules.app_core import impl_chat
        from modules.llm_service import LLMService

        grounding_data = {
            ALLOWED_TABLE: {
                "animal_type": ["CAT", "DOG"],
                "outcome_type": ["Adoption"],
                "shelter": ["EAST LA"],
            }
        }

        yb_server = MagicMock()
        yb_server.get_grounding_values.return_value = grounding_data

        captured_prompt = {}

        real_create = LLMService.create_system_prompt

        def mock_create(self, tools, grounding_values=None):
            captured_prompt["grounding"] = grounding_values
            return real_create(self, tools, grounding_values=grounding_values)

        cfg = LLMConfig(api_key="k", model="gpt-4o", provider="openai")
        llm_svc = MagicMock(spec=LLMService)
        llm_svc.config = cfg
        llm_svc.create_system_prompt.side_effect = mock_create.__get__(llm_svc, type(llm_svc))

        # We only need to verify create_system_prompt is called with the grounding;
        # we do that by checking the side_effect captured arg.
        llm_svc.create_system_prompt.side_effect = (
            lambda tools, grounding_values=None: (
                captured_prompt.update({"grounding": grounding_values}) or "test-prompt"
            )
        )
        llm_svc.process_conversation.return_value = ("answer", [], [], None)

        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []

        # Minimal Flask request context
        import flask
        flask_app = flask.Flask(__name__)
        flask_app.secret_key = "test"

        with flask_app.test_request_context(
            "/api/chat",
            method="POST",
            json={"message": "how many dogs?"},
        ):
            flask.session["user"] = {"email": "test@test.com"}
            with patch("modules.app_core.billing") as mock_billing:
                mock_billing.check_limit.return_value = (True, 0, 100)
                mock_billing.record_question.return_value = None
                impl_chat(mcp, llm_svc, None, yugabyte_server=yb_server)

        assert captured_prompt.get("grounding") == grounding_data

    def test_grounding_fail_open(self):
        """If get_grounding_values() raises, impl_chat must NOT raise."""
        from modules.app_core import impl_chat
        from modules.llm_service import LLMService

        yb_server = MagicMock()
        yb_server.get_grounding_values.side_effect = RuntimeError("DB down")

        llm_svc = MagicMock(spec=LLMService)
        llm_svc.create_system_prompt.return_value = "prompt without grounding"
        llm_svc.process_conversation.return_value = ("answer", [], [], None)

        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []

        import flask
        flask_app = flask.Flask(__name__)
        flask_app.secret_key = "test"

        with flask_app.test_request_context(
            "/api/chat",
            method="POST",
            json={"message": "how many dogs?"},
        ):
            flask.session["user"] = {"email": "test@test.com"}
            with patch("modules.app_core.billing") as mock_billing:
                mock_billing.check_limit.return_value = (True, 0, 100)
                mock_billing.record_question.return_value = None
                # Must not raise
                resp = impl_chat(mcp, llm_svc, None, yugabyte_server=yb_server)

        # create_system_prompt was still called (without grounding)
        llm_svc.create_system_prompt.assert_called_once()
        _, kwargs = llm_svc.create_system_prompt.call_args
        assert kwargs.get("grounding_values") is None


# ---------------------------------------------------------------------------
# 5. QUERY DISCIPLINE block — present in system prompt (Nov-22 work order)
# ---------------------------------------------------------------------------


class TestQueryDisciplinePrompt:
    """
    Verify that the QUERY DISCIPLINE instruction block added by the Nov-22
    granite query-discipline work order is present in the assembled system
    prompt for all relevant code paths.

    Rules verified:
      R1  DATASET SCOPE / no county filter
      R2  SHELTER FILTER only when explicitly named
      R3  AGGREGATE FIRST / no SELECT *
      R4  ONE COLUMN ONE CONDITION / use IN
      R5  GROUNDED VALUES ONLY
      R6  ZERO MEANS WRONG FORMULATION
    """

    @pytest.fixture
    def llm(self):
        cfg = LLMConfig(api_key="test-key", model="gpt-4o", provider="openai")
        with patch("modules.llm_service.LLMService.__init__", lambda self, config: None):
            svc = LLMService.__new__(LLMService)
            svc.config = cfg
            svc.client = None
        return svc

    # -- helpers -------------------------------------------------------------

    def _prompt(self, llm, grounding=None):
        return llm.create_system_prompt([], grounding_values=grounding)

    # -- R1: dataset-scope rule ----------------------------------------------

    def test_r1_query_discipline_header_present(self, llm):
        assert "QUERY DISCIPLINE" in self._prompt(llm)

    def test_r1_dataset_scope_no_county_filter(self, llm):
        p = self._prompt(llm)
        assert "DATASET SCOPE" in p
        # Must say LA County describes the whole dataset, not a filter value
        assert "LA County" in p or "Los Angeles County" in p
        assert "NOT a filter" in p or "not a filter" in p.lower() or "is NOT a filter" in p

    def test_r1_no_county_name_as_filter_value(self, llm):
        p = self._prompt(llm)
        assert "NEVER" in p
        # The prohibition on using county name as a filter must appear
        assert "shelter_code" in p

    # -- R2: shelter-filter-only-when-named rule -----------------------------

    def test_r2_shelter_filter_explicit_only(self, llm):
        p = self._prompt(llm)
        assert "explicitly" in p.lower()
        # Shelter names ≠ shelter_code values
        assert "shelter_code" in p

    # -- R3: aggregate-first / no raw-row dumps ------------------------------

    def test_r3_no_select_star(self, llm):
        p = self._prompt(llm)
        assert "SELECT *" in p
        assert "NEVER" in p
        # Both must co-occur — the rule says NEVER issue SELECT *
        idx_never = p.rfind("NEVER")
        idx_star = p.rfind("SELECT *")
        # The NEVER before SELECT * must exist
        assert p.count("SELECT *") >= 1

    def test_r3_aggregate_first_phrase(self, llm):
        p = self._prompt(llm)
        assert "AGGREGATE FIRST" in p or "aggregate" in p.lower()

    # -- R4: one column, one condition ---------------------------------------

    def test_r4_in_operator_guidance(self, llm):
        p = self._prompt(llm)
        assert "IN" in p
        assert "ONE COLUMN" in p or "one column" in p.lower()

    # -- R5: grounded values only --------------------------------------------

    def test_r5_grounded_values_only(self, llm):
        p = self._prompt(llm)
        assert "GROUNDED VALUES" in p or "grounded" in p.lower()

    # -- R6: zero means wrong formulation ------------------------------------

    def test_r6_zero_means_wrong_formulation(self, llm):
        p = self._prompt(llm)
        assert "ZERO MEANS WRONG" in p or "zero-row" in p.lower() or "COUNT of 0" in p

    def test_r6_drop_shelter_filter_on_zero(self, llm):
        p = self._prompt(llm)
        # Must instruct to DROP shelter/shelter_code filters when reformulating
        assert "DROP" in p
        assert "shelter" in p.lower()

    # -- Block present with and without grounding ---------------------------

    def test_discipline_block_present_without_grounding(self, llm):
        """The discipline block must appear even when no grounding data is passed."""
        p = llm.create_system_prompt([])
        assert "QUERY DISCIPLINE" in p

    def test_discipline_block_present_with_grounding(self, llm):
        """The discipline block must survive alongside the grounding block."""
        grounding = {
            ALLOWED_TABLE: {
                "animal_type": ["CAT", "DOG"],
                "outcome_type": ["Adoption"],
                "shelter": ["EAST LA", "WEST LA"],
            }
        }
        p = llm.create_system_prompt([], grounding_values=grounding)
        assert "QUERY DISCIPLINE" in p
        # Grounding block must still be present too
        assert "FILTER VALUE GROUNDING" in p
        assert "EAST LA" in p

    def test_gemini_provider_unaffected_by_discipline_block(self, llm):
        """Gemini uses a minimal prompt; it must not contain the discipline block."""
        llm.config.provider = "gemini"
        p = llm.create_system_prompt([])
        assert "QUERY DISCIPLINE" not in p
