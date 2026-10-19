# Plan: Add YugabyteDB MCP Server to AWDC Chatbot

## Overview

Extend the existing Flask/MCP chatbot with a second database backend — YugabyteDB
(Postgres-compatible) — alongside the current Oracle APEX and PDF backends. The new
backend exposes animal shelter data for LA County (`awdc.laas_population_data`, 59,153
rows) and six other county tables via a new `YugabyteMCPServer` class that mirrors the
`OracleMCPServer` pattern exactly.

The implementation delivers one new MCP tool, `yb_query_table`, with full aggregation
support (COUNT/AVG/SUM/MIN/MAX + GROUP BY + ORDER BY + FILTER) so the LLM can answer
the 5 demo questions without raw SQL or in-memory aggregation. Security posture is
strictly stronger than the Oracle server: no user-supplied string is ever concatenated
into SQL; all values are bound parameters; table names are validated against an env
allow-list before any query runs.

### Scope

**In scope:**
- `modules/yugabyte_mcp_server.py` — new file, `YugabyteMCPServer` class
- `modules/mcp_client.py` — add `yugabyte` ServerConfig
- `app.py` and `api/index.py` — wire YugabyteMCPServer into `initialize_services()`
- `modules/llm_service.py` — update system prompt to describe both backends
- `requirements.txt` — add `psycopg[binary]`
- `.env.example` — add `YUGABYTE_*` placeholder vars
- `vercel.json` — raise `maxDuration` from 10 to 30
- `tests/test_yugabyte_integration.py` — new test file

**Out of scope:** changes to Oracle, PDF, session, auth, or analytics paths.

---

## Sub-Tasks

---

### Sub-Task 1 — Create `modules/yugabyte_mcp_server.py`

**Status:** `[x] done`

**Intent:**
Implement the `YugabyteMCPServer` class, which is the core of this feature. It must
mirror the Oracle server's interface (same method names, same return shapes) so the rest
of the wiring is mechanical. The main addition over the Oracle server is the structured
query-builder in `query_table()`, which replaces the Oracle server's unsafe raw-string
WHERE clause with a validated, parameterized builder that also supports aggregation.

**Expected Outcomes:**
- The class can be instantiated when `YUGABYTE_*` env vars are set.
- `list_tables()` returns the allow-listed tables with metadata from `information_schema`.
- `describe_table(table_name)` returns column names, data types, and nullability — same
  shape as `OracleMCPServer.describe_view()`.
- `query_table()` builds and executes safe SELECT queries for all combinations of:
  plain row fetch, structured filters, aggregates, group-by (column name or date
  expression), order-by, and limit.
- All 5 ground-truth queries from the brief are expressible through `yb_query_table`.
- `get_available_tools()` returns MCP tool definitions for `yb_list_tables`,
  `yb_describe_table`, `yb_query_table` in the same format as the Oracle server.
- `execute_tool()` dispatches correctly.
- `health_check()` returns status/pool info.
- `close()` and context manager protocol work.

**Todo List:**
1. Add module docstring and imports (`os`, `logging`, `psycopg`, `psycopg.pool`, typing).
2. Implement `_parse_allowed_tables()` — reads `YUGABYTE_ALLOWED_TABLES` env var,
   upper-strips entries, handles schema-qualified names (`awdc.laas_population_data`).
3. Implement `_validate_configuration()` — raises `ValueError` if host/user/password/
   allowed_tables are missing.
4. Implement `_initialize_connection_pool()` — uses `psycopg.pool.ConnectionPool` with
   `min_size=1`, `max_size=5`; connection string built from `YUGABYTE_HOST`,
   `YUGABYTE_PORT` (default 5433), `YUGABYTE_DBNAME`, `YUGABYTE_USER`,
   `YUGABYTE_PASSWORD`, `YUGABYTE_SSLMODE` (default `require`).
5. Implement `_is_table_allowed(table_name)` — normalizes to lowercase, handles
   schema-qualified form.
6. Implement `_sanitize_table_name(table_name)` — allows only `[a-zA-Z0-9_.]` (the `.`
   is needed for schema-qualified names); raises `ValidationError` otherwise.
7. Implement `health_check()` — executes `SELECT 1`, returns pool stats.
8. Implement `list_tables()` — queries `information_schema.tables` filtered to
   allow-listed tables; returns `{success, tables: [{name, schema, description}], count}`.
9. Implement `describe_table(table_name)` — queries `information_schema.columns` for the
   validated table; returns `{success, table_name, columns: [{name, type, nullable,
   position}], column_count}`. This is the schema the LLM sees and the validator uses.
10. Implement `_get_valid_columns(table_name)` — calls `describe_table` internally,
    returns a set of valid lowercase column names for validation in `query_table`.
11. Implement `_build_filter_sql(filter_obj, params, valid_columns)` — validates column
    against valid_columns; maps operator from fixed set (`=`, `<`, `>`, `<=`, `>=`,
    `BETWEEN`, `IN`, `date_relative`); for `date_relative` operator resolves the value
    object `{anchor, offset_years}` to a safe SQL expression (only `current_year_start`
    and `current_year_start` − N years are recognized; no user string is used); all
    other values appended to `params` list as bound parameters; returns SQL fragment.
12. Implement `_build_group_by_expr(item, valid_columns)` — if item is a plain string,
    validates against valid_columns and returns quoted identifier; if item is
    `{column, date_trunc}` or `{column, extract}`, validates column, validates
    `date_trunc`/`extract` value against a fixed set (`month`, `year`, `day`), and
    returns `DATE_TRUNC('month', col)` or `EXTRACT(month FROM col)` — no user string
    touches the SQL template. Returns `(sql_expr, alias_str)` tuple for use in SELECT
    and GROUP BY.
13. Implement `_build_aggregate_expr(agg_obj, params, valid_columns)` — validates
    function against `{COUNT, AVG, SUM, MIN, MAX}`; validates column against
    valid_columns (or allows `*` for COUNT only); applies optional `ROUND(..., digits)`;
    builds optional `FILTER (WHERE ...)` clause by delegating to `_build_filter_sql`;
    returns `(sql_expr, alias_str)`.
14. Implement `query_table(table_name, filters=None, aggregates=None, group_by=None,
    order_by=None, limit=None)` — assembles SELECT using the above helpers; plain-fetch
    path when no aggregates/group_by; applies LIMIT (capped at `MAX_RESULT_SIZE`);
    executes with `psycopg` cursor using `%s` placeholders and the params list; returns
    `{success, table_name, columns, rows, row_count, limited}`.
15. Implement `get_available_tools()` — returns MCP JSON schema for `yb_list_tables`,
    `yb_describe_table`, `yb_query_table`. The `yb_query_table` schema must fully
    document the `aggregates`, `group_by`, and `order_by` optional params so the LLM
    can see them.
16. Implement `execute_tool(tool_name, parameters)` — dispatches to the three methods.
17. Implement `close()` and `__enter__`/`__exit__`.

**Relevant Context:**
- Mirror class structure from `modules/oracle_mcp_server.py` (connection pool, context
  manager, `_is_view_allowed`, `_sanitize_view_name`, `get_available_tools`,
  `execute_tool` dispatch).
- `psycopg` v3 API differs from `oracledb`: `psycopg.pool.ConnectionPool`, cursor uses
  `%s` placeholders, `conn.cursor()` is a context manager itself.
- Schema-qualified table names: `awdc.laas_population_data`. The sanitizer must allow
  `.` but still reject any other special characters.
- `_get_valid_columns` will make a DB round-trip; cache the result per table_name within
  the request to avoid multiple round-trips inside a single `query_table` call.
- For the `date_relative` operator, the only recognized anchor values are
  `"current_year_start"` (→ `DATE_TRUNC('year', CURRENT_DATE)`) — offset applied as
  `+ INTERVAL 'N years'` with N a server-side integer, never a user string.
- `ApexRestHandler.__init__` will be extended in Sub-Task 2 to accept `yugabyte_server`
  as an optional fourth argument (default `None`). The `YugabyteMCPServer` class itself
  does not need to know about this — its interface is self-contained.

---

### Sub-Task 1b — Smoke-check `YugabyteMCPServer` against the real cluster

**Status:** `[x] done`

**Intent:**
Validate the driver, TLS handshake, connection pool, and query-builder against the live
YugabyteDB Aeon cluster before wiring the new server into either entry point. The blast
radius of a failure here is one file; after wiring it would be both entry points plus
`ApexRestHandler`. Fail fast while the change is still isolated.

**Expected Outcomes:**
- A short standalone script can be run manually: `python scripts/smoke_yugabyte.py`.
- Running it with `YUGABYTE_*` vars set in `.env` produces:
  - One successful `describe_table` call (returns column list for
    `awdc.laas_population_data`).
  - One successful aggregate `query_table` call (COUNT grouped by `animal_type`,
    no date filter — fast, bounded result).
  - Printed output showing row count and first few rows.
- Running it without `YUGABYTE_HOST` set prints a clear "not configured" message and
  exits 0.

**Todo List:**
1. Create `scripts/smoke_yugabyte.py`:
   - Load `.env` via `python-dotenv`.
   - Check for `YUGABYTE_HOST`; if absent, print message and exit 0.
   - Instantiate `YugabyteMCPServer` directly (no Flask context needed).
   - Call `describe_table('awdc.laas_population_data')`, print the column list.
   - Call `query_table('awdc.laas_population_data', aggregates=[{function: COUNT,
     column: *, alias: count}], group_by=['animal_type'], order_by={by: count,
     direction: DESC}, limit=10)`, print result rows.
   - Call `health_check()`, print pool status.
   - Print "Smoke check passed" on success; let exceptions propagate naturally for
     visibility.
2. Run the script manually and confirm output before proceeding to Sub-Task 2.

**Relevant Context:**
- `scripts/` already contains `analyze_apex_apis.py`, `check_gemini_models.py`,
  `check_models.py` — this follows the same pattern (standalone diagnostic script).
- The script is not a pytest test; it requires a live connection and real env vars.
  It is a manual step, not part of CI.

---

### Sub-Task 2 — Wire `YugabyteMCPServer` into both entry points and `mcp_client.py`

**Status:** `[x] done`

**Intent:**
Register the new server in the same three places the Oracle server is registered, so
both local dev (`app.py`) and the Vercel deployment (`api/index.py`) initialize it,
and the `MCPClient` configuration includes it for any future HTTP-mode use.

**Expected Outcomes:**
- `ApexRestHandler.__init__` accepts `yugabyte_server=None` as an optional fourth
  argument and stores it as `self.yugabyte_server`.
- `initialize_services()` in both `app.py` and `api/index.py` instantiates
  `YugabyteMCPServer` when `YUGABYTE_HOST` is set, logs timing, and passes it to
  `ApexRestHandler(oracle_server, pdf_server, llm_service, yugabyte_server)`.
- Both entry points still work when `YUGABYTE_HOST` is absent — `yugabyte_server`
  defaults to `None` and `ApexRestHandler` receives `None` for that argument.
- `get_initialization_metrics()` and `/api/health` show a `yugabyte_server` key.
- `mcp_client.py`'s `create_mcp_client_from_env()` adds a `ServerConfig(name='yugabyte',
  type='yugabyte', ...)` when `YUGABYTE_HOST` is set.
- `vercel.json` `maxDuration` raised from 10 to 30.

**Todo List:**
1. In `modules/apex_rest_handler.py` `ApexRestHandler.__init__`: add
   `yugabyte_server: Optional[YugabyteMCPServer] = None` as a fourth parameter; store as
   `self.yugabyte_server = yugabyte_server`. Add the import at the top of the file
   (guard with `TYPE_CHECKING` or a lazy import to avoid circular deps if needed).
2. In `modules/mcp_client.py` `create_mcp_client_from_env()` (after the PDF block,
   ~line 596): add a `yugabyte` ServerConfig block guarded by `os.getenv('YUGABYTE_HOST')`.
3. In `app.py`: import `YugabyteMCPServer` at top of file; add `yugabyte_server = None`
   to module-level globals (~line 57); add `'yugabyte_server_time': 0.0` to
   `_init_metrics` dict (~line 65); add an instantiation block in `initialize_services()`
   after the Oracle block, guarded by `YUGABYTE_HOST`; pass `yugabyte_server` to
   `ApexRestHandler(oracle_server, pdf_server, llm_service, yugabyte_server)`.
4. Apply the identical changes to `api/index.py`.
5. In both entry points include `yugabyte_server` status in `/api/health`
   `service_status` dict.
6. In `vercel.json`, change `"maxDuration": 10` to `"maxDuration": 30`.

**Relevant Context:**
- Oracle wiring pattern in `app.py` lines 147–158; `api/index.py` lines 149–159.
- Module-level globals declared at `app.py` lines 53–57.
- `_init_metrics` dict initialized at `app.py` lines 65–74.
- `ApexRestHandler` is in `modules/apex_rest_handler.py`; current `__init__` signature
  is `(self, oracle_server, pdf_server, llm_service)` — add `yugabyte_server=None`.
- `vercel.json` is 33 lines; `maxDuration` is on line 6.

---

### Sub-Task 3 — Update system prompt and `.env.example` / `requirements.txt`

**Status:** `[x] done`

**Intent:**
Give the LLM the context it needs to route questions to the right backend, and document
the new env vars and dependency for operators.

**Expected Outcomes:**
- `create_system_prompt()` in `modules/llm_service.py` includes a routing paragraph
  distinguishing Oracle APEX views (structured org data) from Yugabyte tables (animal
  shelter data by county).
- `requirements.txt` contains `psycopg[binary]` (no version pin required initially;
  add `>=3.1` if psycopg 2 is also present to avoid ambiguity).
- `.env.example` contains all six `YUGABYTE_*` vars with placeholder values and a
  comment explaining each, placed in a new `# YugabyteDB Configuration` section.

**Todo List:**
1. In `modules/llm_service.py` `create_system_prompt()` (~line 542): extend the
   `base_prompt` for the OpenAI path to include a "Data sources" paragraph — Oracle
   APEX tools (`query_view`, `list_views`, `describe_view`) for org/admin data; Yugabyte
   tools (`yb_query_table`, `yb_list_tables`, `yb_describe_table`) for animal shelter
   population data. Mention: call `yb_describe_table` before the first `yb_query_table`
   for a given table in a conversation — the schema stays in conversation history so
   subsequent questions on the same table go straight to querying.
2. Add `psycopg[binary]` to `requirements.txt` on a new line after the existing DB
   libraries.
3. Add `YUGABYTE_*` section to `.env.example`:
   ```
   # YugabyteDB Configuration
   YUGABYTE_HOST=your-cluster.yugabyte.cloud
   YUGABYTE_PORT=5433
   YUGABYTE_DBNAME=yugabyte
   YUGABYTE_USER=your_readonly_user
   YUGABYTE_PASSWORD=your_password
   YUGABYTE_SSLMODE=require
   YUGABYTE_ALLOWED_TABLES=awdc.laas_population_data
   ```

**Relevant Context:**
- `create_system_prompt()` in `modules/llm_service.py` line 542; the OpenAI path builds
  `base_prompt` and appends tool descriptions from `available_tools`.
- `requirements.txt` — check whether `psycopg2` is already listed; if so, note the
  distinction in a comment.
- `.env.example` is the operator-facing documentation for all env vars.

---

### Sub-Task 4 — Write `tests/test_yugabyte_integration.py`

**Status:** `[x] done`

**Intent:**
Verify the `YugabyteMCPServer` tool dispatch and query-builder logic without a live
database. Mirror the structure of `tests/test_apex_integration.py`.

**Expected Outcomes:**
- Tests pass with `pytest` using mocked `psycopg` connections.
- Covered: tool dispatch for all three tools, `describe_table` column validation,
  `query_table` plain-fetch path, `query_table` with aggregates + group_by,
  `query_table` FILTER clause, `date_relative` operator resolution, allow-list
  rejection, sanitizer rejection of invalid table names, `health_check`.

**Todo List:**
1. Read `tests/test_apex_integration.py` to match its structure (fixtures, mock patterns).
2. Write `TestYugabyteMCPServer` class with:
   - `test_list_tables_returns_allowed_only`
   - `test_describe_table_returns_columns`
   - `test_query_table_plain_fetch` (no filters, no aggregates)
   - `test_query_table_with_filter` (structured `=` filter, value bound as param)
   - `test_query_table_with_aggregate_and_group_by` (COUNT + DATE_TRUNC month)
   - `test_query_table_with_filter_clause_on_aggregate` (COUNT FILTER WHERE)
   - `test_query_table_date_relative_operator` (resolves to DATE_TRUNC SQL expression)
   - `test_query_table_rejects_non_allowed_table`
   - `test_query_table_rejects_invalid_column_in_filter`
   - `test_sanitize_table_name_rejects_injection`
   - `test_health_check_healthy`
   - `test_execute_tool_dispatch`
3. Mock `psycopg.pool.ConnectionPool` and cursor; return realistic column/row data
   shaped like the LAAS table schema from the brief.

**Relevant Context:**
- `tests/test_apex_integration.py` — use as structural template.
- `tests/test_unit.py` — shows mock patterns for `OracleMCPServer` and `MCPClient`.
- The 5 canned queries in the brief are the ground truth for what the builder must
  produce — test cases 3 and 4 together cover Q1 and Q4.

---

## Key Design Decisions (Locked)

| Decision | Choice | Reason |
|---|---|---|
| One tool vs. two | One tool `yb_query_table` with optional params | LLM tool-call loop caps at 5; minimise round-trips |
| Date-relative filter | `operator: "date_relative"`, `value: {anchor, offset_years}` | Explicit, type-safe; no user string enters SQL |
| Schema exposure | `yb_describe_table` returns full column list to LLM | Inform model + server validation = two independent safety layers |
| Aggregation design | Structured `{function, column, alias, round?, filter?}` objects | All identifiers validated; all values parameterized |
| Group-by date exprs | `{column, date_trunc}` / `{column, extract}` objects | Fixed-set values; server renders SQL template |
| Security posture | Strictly stronger than Oracle — no raw WHERE string | Audit P1 finding; deliberately documented in brief |
| Entry-point duplication | Wire in both `app.py` AND `api/index.py` | Brief requirement; Vercel only runs `api/index.py` |
| ApexRestHandler dispatch | `yugabyte_server` passed as optional 4th arg | Single dispatch path; avoids hidden module-level variable split across two files |
| Describe-first rule | Per table per conversation, not per question | Schema stays in history; saves tool-loop iterations on questions 2–5 |
| Smoke check | Manual script before wiring | Fail fast on driver/TLS while blast radius is one file |

## Files Changed

| File | Change type |
|---|---|
| `modules/yugabyte_mcp_server.py` | New |
| `modules/apex_rest_handler.py` | Edit — add optional yugabyte_server arg |
| `modules/mcp_client.py` | Edit — add yugabyte ServerConfig block |
| `app.py` | Edit — wire yugabyte_server into initialize_services and ApexRestHandler |
| `api/index.py` | Edit — same as app.py |
| `modules/llm_service.py` | Edit — extend system prompt |
| `requirements.txt` | Edit — add psycopg[binary] |
| `.env.example` | Edit — add YUGABYTE_* vars |
| `vercel.json` | Edit — maxDuration 10 → 30 |
| `scripts/smoke_yugabyte.py` | New — manual live-cluster validation script |
| `tests/test_yugabyte_integration.py` | New |
