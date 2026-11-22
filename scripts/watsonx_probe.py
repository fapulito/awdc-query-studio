"""
watsonx_probe.py — raw-response capture for Granite tool-calling diagnostics.

Sends one chat request per model to the watsonx.ai text/chat endpoint using
the EXACT system prompt, tool definitions, and request parameters the
production app sends.  Prints the full raw JSON response for each model.

Usage
-----
    python scripts/watsonx_probe.py [extra_model_id ...]

Required environment variables
-------------------------------
    WATSONX_API_KEY       IBM Cloud API key (never printed)
    WATSONX_PROJECT_ID    watsonx project UUID
    WATSONX_URL           watsonx base URL, e.g. https://us-south.ml.cloud.ibm.com

No application code is modified by this script.
"""

import json
import os
import sys

import requests

# ---------------------------------------------------------------------------
# IAM token exchange  (same logic as modules/watsonx_provider.py)
# ---------------------------------------------------------------------------

_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
_WATSONX_API_VERSION = "2024-05-01"


def _get_iam_token(api_key: str) -> str:
    """Exchange *api_key* for an IAM access token.  Key is never printed."""
    resp = requests.post(
        _IAM_TOKEN_URL,
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if not resp.ok:
        print(f"[ERROR] IAM token exchange failed — HTTP {resp.status_code}")
        print(resp.text)
        sys.exit(1)
    body = resp.json()
    token = body.get("access_token")
    if not token:
        print("[ERROR] IAM response contained no access_token")
        print(json.dumps(body, indent=2))
        sys.exit(1)
    return token


# ---------------------------------------------------------------------------
# App's REAL system prompt  (copied verbatim from LLMService.create_system_prompt,
# no-grounding branch — the same text the production request uses on a first turn)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant with access to various data sources and tools.\n"
    "You can help users query databases, search documents, and retrieve information.\n"
    "\n"
    "When users ask questions:\n"
    "1. Analyze what information is needed\n"
    "2. Use the appropriate tools to gather data\n"
    "3. Provide clear, concise answers based on the retrieved information\n"
    "4. If you cannot find the information, explain what you tried and suggest alternatives\n"
    "\n"
    "Always cite your sources when providing information from tools.\n"
    "\n"
    "DATA SOURCES — route questions to the right backend:\n"
    "\n"
    "Oracle APEX (tools: query_view, list_views, describe_view)\n"
    "  Use for organisational or administrative data exposed as Oracle APEX views.\n"
    "  Call describe_view to inspect columns before querying an unfamiliar view.\n"
    "\n"
    "YugabyteDB shelter database (tools: yb_query_table, yb_list_tables, yb_describe_table)\n"
    "  Use for animal shelter population data from California county shelters\n"
    "  (LA County, Orange County, Riverside, San Bernardino, etc.).\n"
    "  Tables are in the \"awdc\" schema, e.g. awdc.laas_population_data.\n"
    "  IMPORTANT: call yb_describe_table once per table per conversation before\n"
    "  your first yb_query_table for that table — the schema stays in conversation\n"
    "  history so subsequent questions on the same table go straight to querying.\n"
    "  Use the aggregates and group_by parameters of yb_query_table for COUNT,\n"
    "  AVG, SUM, date-grouped trends, and filtered aggregates; do not fetch raw\n"
    "  rows and aggregate in your response.\n"
    "  For month-by-month trend questions, prefer a single yb_query_table call\n"
    "  using a date_trunc month group_by together with date_relative filters\n"
    "  using the max_date anchor (anchor=\"max_date\") rather than querying\n"
    "  multiple tables or years separately.\n"
    "\n"
    "PDF documents (tools: search_pdfs, get_document, list_documents)\n"
    "  Use for searching uploaded reference documents.\n"
    "\n"
    "FILTER VALUE RULES (awdc.laas_population_data):\n"
    "  1. Use UPPER(col) = UPPER(value) semantics (operator '=') for text\n"
    "     columns animal_type, outcome_type, shelter — the server case-folds\n"
    "     automatically.\n"
    "  2. ZERO-ROW GUARDRAIL: if a query returns 0 rows and had text filters,\n"
    "     retry once with corrected filter values. If still 0 rows, say so\n"
    "     plainly naming the filters — never invent a data-limitation excuse."
)

# ---------------------------------------------------------------------------
# App's REAL tool definitions  (copied verbatim from
# YugabyteMCPServer.get_available_tools(), then passed through
# LLMService.format_tools_for_llm() which wraps each in {"type":"function","function":{...}})
# ---------------------------------------------------------------------------

_MAX_RESULT_SIZE = 1000  # matches server default for the description string

_RAW_TOOLS = [
    {
        "name": "yb_list_tables",
        "description": (
            "List all available YugabyteDB animal shelter tables. "
            "Returns table names and schemas."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "yb_describe_table",
        "description": (
            "Get column names, data types, and nullability for a YugabyteDB "
            "shelter table.  Call this once per table per conversation before "
            "the first yb_query_table — the schema stays in conversation "
            "history so subsequent questions go straight to querying."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "Schema-qualified table name, e.g. 'awdc.laas_population_data'",
                }
            },
            "required": ["table_name"],
        },
    },
    {
        "name": "yb_query_table",
        "description": (
            "Query an allow-listed YugabyteDB shelter table.  Supports plain "
            "row fetch, structured WHERE filters, aggregation (COUNT/AVG/SUM/"
            "MIN/MAX), GROUP BY with optional DATE_TRUNC or EXTRACT date "
            "expressions, and ORDER BY.  Call yb_describe_table first to "
            "confirm column names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "Schema-qualified allow-listed table name",
                },
                "filters": {
                    "type": "array",
                    "description": "Optional WHERE filters (AND-combined)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "operator": {
                                "type": "string",
                                "enum": ["=", "<", ">", "<=", ">=", "BETWEEN", "IN", "ILIKE", "date_relative"],
                            },
                            "value": {
                                "description": (
                                    "Scalar, list (for IN/BETWEEN), or "
                                    "{anchor, offset_years} for date_relative. "
                                    "anchor must be 'current_year_start' (start of "
                                    "current calendar year) or 'max_date' (start of "
                                    "the calendar year containing the latest date in "
                                    "the column — use this for 'last full year of data' "
                                    "or 'most recent year in the data' questions). "
                                    "offset_years=0 means the anchor year itself; "
                                    "offset_years=-1 means one year earlier."
                                )
                            },
                        },
                        "required": ["column", "operator", "value"],
                    },
                },
                "aggregates": {
                    "type": "array",
                    "description": "Aggregate expressions to compute",
                    "items": {
                        "type": "object",
                        "properties": {
                            "function": {
                                "type": "string",
                                "enum": ["COUNT", "AVG", "SUM", "MIN", "MAX"],
                            },
                            "column": {
                                "type": "string",
                                "description": "Column name, or '*' for COUNT",
                            },
                            "alias": {"type": "string"},
                            "round": {
                                "type": "integer",
                                "description": "Decimal places for ROUND(...)",
                            },
                            "filter": {
                                "type": "object",
                                "description": "FILTER (WHERE ...) applied to this aggregate only",
                                "properties": {
                                    "column": {"type": "string"},
                                    "operator": {"type": "string"},
                                    "value": {},
                                },
                            },
                        },
                        "required": ["function", "column", "alias"],
                    },
                },
                "group_by": {
                    "type": "array",
                    "description": (
                        "GROUP BY expressions. Each item is either a column name "
                        "(string) or a date-expression object: "
                        "{column, date_trunc: 'month'|'year'|'day'} or "
                        "{column, extract: 'month'|'year'|'day'}."
                    ),
                    "items": {},
                },
                "order_by": {
                    "type": "object",
                    "description": "ORDER BY a group_by alias or aggregate alias",
                    "properties": {
                        "by": {"type": "string", "description": "Alias or column name"},
                        "direction": {"type": "string", "enum": ["ASC", "DESC"]},
                    },
                    "required": ["by", "direction"],
                },
                "limit": {
                    "type": "integer",
                    "description": f"Max rows (server cap: {_MAX_RESULT_SIZE})",
                },
            },
            "required": ["table_name"],
        },
    },
]

# Mirror LLMService.format_tools_for_llm(): wrap each raw tool in the
# {"type": "function", "function": {...}} envelope.
_FORMATTED_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("parameters", {"type": "object", "properties": {}, "required": []}),
        },
    }
    for t in _RAW_TOOLS
]

# ---------------------------------------------------------------------------
# Probe logic
# ---------------------------------------------------------------------------

def _probe_model(model_id: str, project_id: str, base_url: str, token: str) -> None:
    """Send one chat request to *model_id* and print the raw response."""
    separator = "=" * 72
    print(f"\n{separator}")
    print(f"MODEL: {model_id}")
    print(separator)

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "For LA County, how many intakes by animal type?"},
    ]

    # Payload mirrors WatsonxProvider.send_message() exactly
    payload = {
        "model_id": model_id,
        "project_id": project_id,
        "messages": messages,
        "parameters": {
            "max_new_tokens": 1000,
            "temperature": 0.7,
        },
        "tools": _FORMATTED_TOOLS,
        "tool_choice": "auto",
    }

    url = f"{base_url.rstrip('/')}/ml/v1/text/chat?version={_WATSONX_API_VERSION}"

    print(f"POST {url}")
    print(f"Payload size: {len(json.dumps(payload))} bytes, "
          f"{len(_FORMATTED_TOOLS)} tools, {len(messages)} messages")

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
    except requests.RequestException as exc:
        print(f"[NETWORK ERROR] {exc}")
        return

    print(f"\nHTTP status: {resp.status_code}")
    print("\n--- RAW RESPONSE BODY (verbatim) ---")

    try:
        body = resp.json()
        print(json.dumps(body, indent=2))
    except ValueError:
        print(body.text)
        return

    # Point at any tool_calls in the response
    _locate_tool_calls(body)


def _locate_tool_calls(body: dict) -> None:
    """Scan the response body for tool_calls in any position and report."""
    found = []

    # Standard watsonx path: body.results[0].message.tool_calls
    for i, result in enumerate(body.get("results", [])):
        tcs = result.get("message", {}).get("tool_calls", [])
        if tcs:
            found.append((f"results[{i}].message.tool_calls", tcs))
        # Also check if tool_calls appears directly on the result object
        tcs_direct = result.get("tool_calls", [])
        if tcs_direct:
            found.append((f"results[{i}].tool_calls", tcs_direct))

    # Also check top-level (non-standard)
    tcs_top = body.get("tool_calls", [])
    if tcs_top:
        found.append(("tool_calls (top-level)", tcs_top))

    # Check choices[] shape (OpenAI-compat responses)
    for i, choice in enumerate(body.get("choices", [])):
        tcs = choice.get("message", {}).get("tool_calls", [])
        if tcs:
            found.append((f"choices[{i}].message.tool_calls", tcs))

    print()
    if found:
        print("*** TOOL CALLS FOUND ***")
        for path, tcs in found:
            print(f"  Field path : {path}")
            print(f"  Count      : {len(tcs)}")
            print(f"  Content    : {json.dumps(tcs, indent=4)}")
    else:
        print("No tool_calls found in any known field.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    api_key = os.environ.get("WATSONX_API_KEY", "")
    project_id = os.environ.get("WATSONX_PROJECT_ID", "")
    base_url = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")

    missing = [v for v, k in [("WATSONX_API_KEY", api_key),
                               ("WATSONX_PROJECT_ID", project_id)]
               if not k]
    if missing:
        print(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    # Default models + any extras from argv
    models = [
        "ibm/granite-4-h-small",
        "ibm/granite-3.3-8b-instruct",
    ] + sys.argv[1:]

    print("Obtaining IAM token…")
    token = _get_iam_token(api_key)
    print("IAM token obtained (not printed).")
    print(f"Project  : {project_id}")
    print(f"Base URL : {base_url}")
    print(f"Models   : {models}")

    for model_id in models:
        _probe_model(model_id, project_id, base_url, token)

    print("\n" + "=" * 72)
    print("Probe complete.")


if __name__ == "__main__":
    main()
