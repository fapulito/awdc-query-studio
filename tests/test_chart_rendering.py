"""
tests/test_chart_rendering.py

Tests for the chart rendering feature:

  1. Python-side result payload extraction:
       - process_conversation captures _last_result
       - /api/chat includes result field with table/columns/rows (capped at 200)
       - result is None when no data query ran

  2. Chart classification logic (ported from static/app.js to pure Python
     so we can assert chart type selection and value fidelity without a browser):
       - monthly-trend shape → "line"
       - by-species shape → "bar"
       - non-chartable (single scalar, free text) → None
       - bar chart top-12 grouping with "Other"
       - line chart preserves exact row values (no rounding/substitution)
       - bar chart preserves exact row values

No live database or LLM API key required.
"""

import json
import os
import sys
import re
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub heavy optional deps
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


ALLOWED_TABLE = "awdc.laas_population_data"

# ---------------------------------------------------------------------------
# Python port of classifyChart / prepBarData / prepLineData from app.js
# (Must stay in sync with the JS logic in static/app.js)
# ---------------------------------------------------------------------------

def _first_val(rows, col):
    for row in rows:
        v = row.get(col)
        if v is not None and v != "":
            return v
    return None


def _is_date_like(col, rows):
    if re.search(r"date|month|year|period|week|day", col, re.IGNORECASE):
        return True
    v = _first_val(rows, col)
    if isinstance(v, str) and re.match(r"^\d{4}-\d{2}", v):
        return True
    return False


def _is_numeric(col, rows):
    v = _first_val(rows, col)
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def classify_chart(result):
    """Python equivalent of classifyChart() in static/app.js."""
    if not result:
        return None
    cols = result.get("columns", [])
    rows = result.get("rows", [])
    if not rows or len(cols) < 2:
        return None

    # Rule 1: date-like + numeric → line
    for i, col in enumerate(cols):
        if _is_date_like(col, rows):
            for j, col2 in enumerate(cols):
                if j != i and _is_numeric(col2, rows):
                    return {"type": "line", "labelCol": col, "valueCol": col2}

    # Rule 2: categorical string + numeric → bar
    cat_col = None
    num_col = None
    for col in cols:
        v = _first_val(rows, col)
        if isinstance(v, str) and not _is_date_like(col, rows) and cat_col is None:
            cat_col = col
        if _is_numeric(col, rows) and num_col is None:
            num_col = col
    if cat_col and num_col:
        return {"type": "bar", "labelCol": cat_col, "valueCol": num_col}

    return None


def prep_bar_data(result, spec):
    """Python equivalent of prepBarData() in static/app.js."""
    MAX_BARS = 12
    pairs = [
        {"label": str(row.get(spec["labelCol"], "")), "value": row[spec["valueCol"]]}
        for row in result["rows"]
    ]
    pairs.sort(key=lambda p: p["value"], reverse=True)
    if len(pairs) <= MAX_BARS:
        return pairs
    top = pairs[:MAX_BARS]
    other_sum = sum(p["value"] for p in pairs[MAX_BARS:])
    top.append({"label": "Other", "value": other_sum})
    return top


def prep_line_data(result, spec):
    """Python equivalent of prepLineData() in static/app.js."""
    pairs = [
        {"label": str(row.get(spec["labelCol"], "")), "value": row[spec["valueCol"]]}
        for row in result["rows"]
    ]
    pairs.sort(key=lambda p: p["label"])
    return pairs


# ---------------------------------------------------------------------------
# Fixture datasets
# ---------------------------------------------------------------------------

MONTHLY_TREND_RESULT = {
    "table": ALLOWED_TABLE,
    "columns": ["intake_date_month", "count"],
    "rows": [
        {"intake_date_month": "2023-01-01", "count": 320},
        {"intake_date_month": "2023-02-01", "count": 410},
        {"intake_date_month": "2023-03-01", "count": 390},
        {"intake_date_month": "2023-04-01", "count": 445},
        {"intake_date_month": "2023-05-01", "count": 512},
        {"intake_date_month": "2023-06-01", "count": 489},
    ],
}

BY_SPECIES_RESULT = {
    "table": ALLOWED_TABLE,
    "columns": ["animal_type", "count"],
    "rows": [
        {"animal_type": "DOG", "count": 25000},
        {"animal_type": "CAT", "count": 18000},
        {"animal_type": "BIRD", "count": 500},
        {"animal_type": "RABBIT", "count": 300},
    ],
}

SINGLE_SCALAR_RESULT = {
    "table": ALLOWED_TABLE,
    "columns": ["total"],
    "rows": [{"total": 43300}],
}

FREE_TEXT_RESULT = {
    "table": ALLOWED_TABLE,
    "columns": ["note"],
    "rows": [{"note": "No data available for this period."}],
}

TWO_TEXT_RESULT = {
    "table": ALLOWED_TABLE,
    "columns": ["shelter", "description"],
    "rows": [
        {"shelter": "West LA", "description": "Open"},
        {"shelter": "East LA", "description": "Closed"},
    ],
}


# ===========================================================================
# 1. Chart classification
# ===========================================================================

class TestClassifyChart:
    def test_monthly_trend_classified_as_line(self):
        spec = classify_chart(MONTHLY_TREND_RESULT)
        assert spec is not None
        assert spec["type"] == "line"
        assert spec["labelCol"] == "intake_date_month"
        assert spec["valueCol"] == "count"

    def test_by_species_classified_as_bar(self):
        spec = classify_chart(BY_SPECIES_RESULT)
        assert spec is not None
        assert spec["type"] == "bar"
        assert spec["labelCol"] == "animal_type"
        assert spec["valueCol"] == "count"

    def test_single_scalar_not_chartable(self):
        assert classify_chart(SINGLE_SCALAR_RESULT) is None

    def test_single_text_column_not_chartable(self):
        assert classify_chart(FREE_TEXT_RESULT) is None

    def test_two_text_columns_not_chartable(self):
        assert classify_chart(TWO_TEXT_RESULT) is None

    def test_empty_rows_not_chartable(self):
        r = {"table": ALLOWED_TABLE, "columns": ["animal_type", "count"], "rows": []}
        assert classify_chart(r) is None

    def test_none_result_not_chartable(self):
        assert classify_chart(None) is None

    def test_date_name_triggers_line_even_without_iso_value(self):
        """Column named 'intake_date' (contains 'date') + numeric → line."""
        r = {
            "table": ALLOWED_TABLE,
            "columns": ["intake_date", "avg_los"],
            "rows": [{"intake_date": "2023-Q1", "avg_los": 12.4}],
        }
        spec = classify_chart(r)
        assert spec is not None
        assert spec["type"] == "line"

    def test_iso_date_value_triggers_line_without_date_name(self):
        """Column named 'bucket' but value looks like ISO date → line."""
        r = {
            "table": ALLOWED_TABLE,
            "columns": ["bucket", "total"],
            "rows": [{"bucket": "2024-01-01", "total": 100}],
        }
        spec = classify_chart(r)
        assert spec is not None
        assert spec["type"] == "line"


# ===========================================================================
# 2. Plotted values equal fixture values — no substitution
# ===========================================================================

class TestPlottedValueFidelity:
    def test_line_values_match_fixture(self):
        spec = classify_chart(MONTHLY_TREND_RESULT)
        data = prep_line_data(MONTHLY_TREND_RESULT, spec)
        fixture_counts = sorted([row["count"] for row in MONTHLY_TREND_RESULT["rows"]])
        plotted_values = sorted([d["value"] for d in data])
        assert plotted_values == fixture_counts, \
            "Line chart plotted values must equal fixture row values exactly"

    def test_line_labels_match_fixture(self):
        spec = classify_chart(MONTHLY_TREND_RESULT)
        data = prep_line_data(MONTHLY_TREND_RESULT, spec)
        fixture_labels = sorted([str(row["intake_date_month"]) for row in MONTHLY_TREND_RESULT["rows"]])
        plotted_labels = sorted([d["label"] for d in data])
        assert plotted_labels == fixture_labels

    def test_bar_values_match_fixture_when_under_12(self):
        spec = classify_chart(BY_SPECIES_RESULT)
        data = prep_bar_data(BY_SPECIES_RESULT, spec)
        fixture_counts = sorted([row["count"] for row in BY_SPECIES_RESULT["rows"]])
        plotted_values = sorted([d["value"] for d in data])
        assert plotted_values == fixture_counts, \
            "Bar chart plotted values must equal fixture row values exactly (no rounding)"

    def test_bar_sorted_descending(self):
        spec = classify_chart(BY_SPECIES_RESULT)
        data = prep_bar_data(BY_SPECIES_RESULT, spec)
        values = [d["value"] for d in data]
        assert values == sorted(values, reverse=True), "Bar chart must be sorted descending"

    def test_bar_top_12_grouping(self):
        """When > 12 categories, top 12 are kept and the rest grouped as 'Other'."""
        rows = [{"species": f"SPECIES_{i}", "count": 1000 - i} for i in range(20)]
        result = {
            "table": ALLOWED_TABLE,
            "columns": ["species", "count"],
            "rows": rows,
        }
        spec = classify_chart(result)
        assert spec is not None
        data = prep_bar_data(result, spec)
        assert len(data) == 13, "Should have 12 top categories + 'Other'"
        assert data[-1]["label"] == "Other"
        # Other value = sum of rows 12..19 = (988 + 987 + ... + 981) = 8 values
        expected_other = sum(row["count"] for row in rows[12:])
        assert data[-1]["value"] == expected_other

    def test_bar_12_categories_no_other(self):
        """Exactly 12 categories → no 'Other' grouping."""
        rows = [{"species": f"SPECIES_{i}", "count": 100 - i} for i in range(12)]
        result = {
            "table": ALLOWED_TABLE,
            "columns": ["species", "count"],
            "rows": rows,
        }
        spec = classify_chart(result)
        data = prep_bar_data(result, spec)
        assert len(data) == 12
        assert all(d["label"] != "Other" for d in data)


# ===========================================================================
# 3. process_conversation captures _last_result (Python unit test)
# ===========================================================================

class TestProcessConversationLastResult:
    def _make_llm_service(self):
        from modules.llm_service import LLMService, LLMConfig
        cfg = LLMConfig(api_key="test-key", model="gpt-4o", provider="openai")
        return LLMService(cfg)

    def _make_query_tool_result(self, rows, columns):
        result = MagicMock()
        result.result = {
            "success": True,
            "table_name": ALLOWED_TABLE,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "limited": False,
            "executed_sql": "SELECT ...",
            "parameters": [],
        }
        result.error = None
        return result

    def test_last_result_is_none_when_no_data_query(self):
        svc = self._make_llm_service()

        with patch.object(svc, "send_message", return_value={"content": "Hi!", "tool_calls": []}):
            with patch.object(svc, "parse_response", return_value=("Hi!", [])):
                _, _, _, last = svc.process_conversation(
                    conversation_history=[{"role": "user", "content": "hello"}],
                    available_tools=[],
                    tool_executor=lambda **kw: None,
                )

        assert last is None

    def test_last_result_captured_from_yb_query_table(self):
        svc = self._make_llm_service()
        rows = [{"animal_type": "DOG", "count": 25000}]
        cols = ["animal_type", "count"]
        tool_result = self._make_query_tool_result(rows, cols)

        mock_req = MagicMock()
        mock_req.tool_name = "yb_query_table"
        mock_req.parameters = {"table_name": ALLOWED_TABLE}
        mock_req.id = "call_001"

        with patch.object(svc, "send_message", return_value={"content": None, "tool_calls": []}):
            with patch.object(svc, "parse_response") as mp:
                mp.side_effect = [
                    (None, [mock_req]),
                    ("Done.", []),
                ]
                _, _, _, last = svc.process_conversation(
                    conversation_history=[{"role": "user", "content": "count by species"}],
                    available_tools=[],
                    tool_executor=lambda tool_name, parameters: tool_result,
                )

        assert last is not None
        assert last["table_name"] == ALLOWED_TABLE
        assert last["columns"] == cols
        assert last["rows"] == rows

    def test_last_result_is_most_recent_query(self):
        """When two queries run, _last_result is the second one."""
        svc = self._make_llm_service()

        rows_a = [{"animal_type": "DOG", "count": 100}]
        rows_b = [{"intake_date_month": "2024-01-01", "count": 50}]
        tool_a = self._make_query_tool_result(rows_a, ["animal_type", "count"])
        tool_b = self._make_query_tool_result(rows_b, ["intake_date_month", "count"])
        tool_b.result["table_name"] = "second_table"

        call_num = [0]
        def fake_executor(tool_name, parameters):
            call_num[0] += 1
            return tool_a if call_num[0] == 1 else tool_b

        req_a = MagicMock(); req_a.tool_name = "yb_query_table"; req_a.id = "c1"
        req_b = MagicMock(); req_b.tool_name = "yb_query_table"; req_b.id = "c2"

        with patch.object(svc, "send_message", return_value={"content": None, "tool_calls": []}):
            with patch.object(svc, "parse_response") as mp:
                mp.side_effect = [
                    (None, [req_a, req_b]),
                    ("Done.", []),
                ]
                _, _, _, last = svc.process_conversation(
                    conversation_history=[{"role": "user", "content": "two queries"}],
                    available_tools=[],
                    tool_executor=fake_executor,
                )

        assert last["table_name"] == "second_table"


# ===========================================================================
# 4. /api/chat result payload in JSON response
# ===========================================================================

def _import_index_module():
    import importlib
    if "api.index" in sys.modules:
        return sys.modules["api.index"]
    with patch("config.validate_config_on_startup", return_value=None):
        import api.index as idx_module  # noqa
    return sys.modules["api.index"]


def _make_chat_app_with_result():
    from modules.mcp_client import MCPClient

    yb_stub = MagicMock()
    yb_stub.get_available_tools.return_value = [{
        "name": "yb_query_table",
        "description": "Q",
        "parameters": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    }]
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
    idx.app.config["SECRET_KEY"] = "test-secret-for-tests-only"

    return idx.app, mock_llm


class TestChatRouteResultField:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app, self.mock_llm = _make_chat_app_with_result()
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

    def test_result_null_when_no_data_query(self):
        self.mock_llm.process_conversation.return_value = ("Answer.", [], [], None)
        self._auth_session(self.client)
        resp = self.client.post("/api/chat", json={"message": "hello"},
                                content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "result" in data
        assert data["result"] is None

    def test_result_payload_present_when_data_query_ran(self):
        rows = [
            {"animal_type": "DOG", "count": 25000},
            {"animal_type": "CAT", "count": 18000},
        ]
        last_result = {
            "success": True,
            "table_name": ALLOWED_TABLE,
            "columns": ["animal_type", "count"],
            "rows": rows,
            "row_count": 2,
            "limited": False,
            "executed_sql": "SELECT ...",
            "parameters": [],
        }
        self.mock_llm.process_conversation.return_value = (
            "Dogs lead.", [], [], last_result
        )
        self._auth_session(self.client)
        resp = self.client.post("/api/chat", json={"message": "count by species"},
                                content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["result"] is not None
        assert data["result"]["table"] == ALLOWED_TABLE
        assert data["result"]["columns"] == ["animal_type", "count"]
        assert len(data["result"]["rows"]) == 2
        assert data["result"]["rows"][0]["count"] == 25000

    def test_result_rows_capped_at_200(self):
        rows = [{"animal_type": f"SPECIES_{i}", "count": i} for i in range(250)]
        last_result = {
            "success": True,
            "table_name": ALLOWED_TABLE,
            "columns": ["animal_type", "count"],
            "rows": rows,
            "row_count": 250,
            "limited": True,
            "executed_sql": "SELECT ...",
            "parameters": [],
        }
        self.mock_llm.process_conversation.return_value = (
            "Many species.", [], [], last_result
        )
        self._auth_session(self.client)
        resp = self.client.post("/api/chat", json={"message": "count by species"},
                                content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["result"] is not None
        assert len(data["result"]["rows"]) == 200, "rows must be capped at 200"
        # First 200 rows are the first 200 from the original (index 0..199)
        assert data["result"]["rows"][0]["count"] == 0
        assert data["result"]["rows"][199]["count"] == 199
