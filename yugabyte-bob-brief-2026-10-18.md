# Bob brief — add YugabyteDB querying to awdc-chat
Prepared Sun 2026-10-18 ~3:10 PM PT. David approved: existing chatbot keeps the suggested
modernization AND gains the ability to query the YugabyteDB (Postgres-compatible) shelter
database, in addition to the Oracle APEX views it already queries.
Codebase facts verified from the source ZIP — do not re-derive them in the session.

## How the existing code is shaped (verified)
- `modules/oracle_mcp_server.py` — class `OracleMCPServer`: config validation,
  `_parse_allowed_views()` (env allow-list), connection pool, `health_check()`,
  `list_views()`, `describe_view(view_name)`, `query_view(view_name, where_clause=None, ...)`,
  `get_available_tools()` returning tool defs named `query_view` / `list_views` / `describe_view`,
  and `execute_tool(tool_name, parameters)` dispatch.
- `modules/mcp_client.py` (~line 564) — servers are registered as `ServerConfig(name='oracle',
  type='oracle', ...)` in a config list.
- Servers are wired in BOTH entry points: `app.py` (~lines 152–191) and `api/index.py`
  (~line 154) — instantiate server, pass into `ApexRestHandler(oracle_server, pdf_server, llm_service)`.
  Any new server must be wired in both files or Vercel will not have it.
- `.env.example` documents every env var; `requirements.txt` pins every dependency.

## Paste-ready Bob prompt (Bob session — Code mode)
> Extend this Flask/MCP chatbot with a second database backend: YugabyteDB (Postgres wire-compatible), alongside the existing Oracle APEX backend. Mirror the existing pattern exactly — do not invent a new architecture.
>
> 1. Create `modules/yugabyte_mcp_server.py` with class `YugabyteMCPServer` modeled on `modules/oracle_mcp_server.py`: config validation, an allow-list parsed from `YUGABYTE_ALLOWED_TABLES`, a connection pool using `psycopg` (v3, binary), `health_check()`, `list_tables()`, `describe_table(table_name)`, `query_table(table_name, where_clause=None, limit=...)`, `get_available_tools()` exposing tools named `yb_list_tables`, `yb_describe_table`, `yb_query_table`, and `execute_tool()` dispatch with the same return shapes as the Oracle server.
> 2. Security rules — STRICTER than the Oracle server, deliberately: Bob's audit (Session 1) found that `oracle_mcp_server.query_view()` concatenates a raw LLM-supplied WHERE clause into SQL behind only a keyword blocklist (misses UNION, comments, semicolons). Do NOT replicate that pattern. `yb_query_table` must accept STRUCTURED filters only — a list of {column, operator, value} with operators from a fixed set (=, <, >, <=, >=, BETWEEN, IN) — validate each column against `describe_table` output, and bind every value as a query parameter. Queries may only touch allow-listed tables; only SELECT may ever run; table names validated against the allow-list before use; a read-only database user is assumed.
> 2b. AGGREGATION (added after Bob's Plan-mode review, 2026-10-18 ~16:29 PT — Bob correctly flagged that the 5 demo questions are aggregate queries that filters alone cannot express, and result sets are capped at 1,000 rows so in-memory aggregation is impossible). Extend `yb_query_table` (ONE tool, optional params — not a second tool) with:
>    - `aggregates`: list of {function, column, alias, round?, filter?} — function from the fixed set COUNT, AVG, SUM, MIN, MAX; column a validated table column (or `*` for COUNT only); optional `round` = digits for the result; optional `filter` = one structured {column, operator, value} rendered as a SQL FILTER (WHERE ...) clause with the value bound as a parameter.
>    - `group_by`: list whose items are either a validated column name OR a date expression object {column, date_trunc: "month"|"year"} or {column, extract: "month"|"year"|"day"} — rendered by the server from templates, never from user-supplied strings.
>    - `order_by`: {by: a group_by column/expression or an aggregate alias, direction: ASC|DESC}.
>    Every identifier is validated against `describe_table` output; every value is a bound parameter; no user string is ever concatenated into SQL. With this extension the 5 ground-truth queries in this brief (COUNT/GROUP BY, DATE_TRUNC month trend, AVG(length_of_stay), COUNT(*) FILTER for dogs-vs-cats, EXTRACT month peaks) must all be expressible through the tool.
> 3. Connection from env: `YUGABYTE_HOST`, `YUGABYTE_PORT` (default 5433), `YUGABYTE_DBNAME`, `YUGABYTE_USER`, `YUGABYTE_PASSWORD`, `YUGABYTE_SSLMODE` (default `require` — Yugabyte Aeon requires TLS).
> 4. Register the server in `modules/mcp_client.py` next to the Oracle `ServerConfig` (name/type `yugabyte`), and wire it in both `app.py` and `api/index.py` alongside the existing servers, including the health/warmup path. Also raise `maxDuration` in `vercel.json` from 10 to 30 seconds — the audit flagged that a Yugabyte TLS cold start can exceed the current 10 s cap.
> 5. Add `psycopg[binary]` to `requirements.txt` and the `YUGABYTE_*` variables to `.env.example` with placeholder values only.
> 6. Update the LLM system prompt tool descriptions so the model can choose Oracle views vs. Yugabyte tables based on the question, and add a test mirroring `tests/test_apex_integration.py` for the Yugabyte tool dispatch with a mocked connection.
> Do not change the Oracle or PDF paths. Export this session as markdown when done.

## What David supplies from his files (never into chat, only into his env)
- Yugabyte Aeon connection details: host, port, database name, user, password → his local
  `.env` and the Vercel project env vars. Per his deployment README a **read-only user was
  already created during deployment** — use that one. (His deployment README's Quick Start
  section has the values; it stays out of every repo.)

## The real schema (from David's Yugabyte deployment README, uploaded 2026-10-18)
Cluster database `yugabyte`, schema **`awdc`**, seven county tables, 346,734 records total:
`laas_population_data` (LA County, **59,153**), `ocac_shelter_data` (Orange Co., 192,149),
`rcas_july_shelter_data` (50,220), `rcas_shelter_data` (29,868), `sbdv_shelter_data` (9,628),
`sbac_shelter_data` (5,706), `sbas_shelter_data` (10).
**Demo allow-list: `awdc.laas_population_data` only** (fully documented columns; add others later).
LAAS columns the demo needs: `animal_type` (DOG/CAT/BIRD/RABBIT…), `intake_date`,
`outcome_type` (ADOPTION, RETURN TO OWNER…), `outcome_date`, `length_of_stay` (days, INTEGER),
plus `intake_type`, `intake_condition`, `sex`, `weight`, `shelter`. No owner PII columns —
animal-level data only (`owner_surrender_reason` is free text; exclude it from demo output).
Note for Bob: table names are schema-qualified (`awdc.laas_population_data`) — the allow-list
check and sanitizer must handle the `awdc.` prefix.

## The 5 canned questions → ground-truth SQL on `awdc.laas_population_data`
Bob's tool path must be able to produce these results (Postgres/Yugabyte dialect):
1. Intake trend by month, last full year:
   `SELECT DATE_TRUNC('month', intake_date) AS month, COUNT(*) FROM awdc.laas_population_data WHERE intake_date >= DATE_TRUNC('year', CURRENT_DATE) - INTERVAL '1 year' AND intake_date < DATE_TRUNC('year', CURRENT_DATE) GROUP BY 1 ORDER BY 1;`
2. Outcomes by species:
   `SELECT animal_type, outcome_type, COUNT(*) FROM awdc.laas_population_data GROUP BY 1, 2 ORDER BY 1, 3 DESC;`
3. Average length of stay, overall and by species:
   `SELECT animal_type, ROUND(AVG(length_of_stay),1) FROM awdc.laas_population_data GROUP BY 1;` (plus the ungrouped overall average)
4. Dogs vs. cats outcome mix:
   `SELECT outcome_type, COUNT(*) FILTER (WHERE animal_type='DOG') AS dogs, COUNT(*) FILTER (WHERE animal_type='CAT') AS cats FROM awdc.laas_population_data GROUP BY 1 ORDER BY 2 DESC;`
5. Peak intake months:
   `SELECT EXTRACT(MONTH FROM intake_date) AS month, COUNT(*) FROM awdc.laas_population_data GROUP BY 1 ORDER BY 2 DESC;`

## Acceptance test (before this counts as done)
With the env set, in the running app, one question per data source:
- APEX path (existing): any question the live chatbot already answers.
- Yugabyte path (new): "How did intakes trend month by month in the last full year of data?"
  → the model must call `yb_query_table` against the allow-listed shelter table and return rows.
Then run the remaining 4 canned questions against whichever source holds their data.

## Sequencing guardrail (submission safety)
Timebox this to ~60–75 minutes of Bob time. The AngelHack submission does NOT depend on it:
the APEX-path demo plus the Bob audit already make a complete submission. If the Yugabyte
wiring fights back (driver, TLS, Vercel cold start), stop, ship without it, and list
"YugabyteDB backend — in progress" under What's Next. Internal submit target stays 6:00 PM PT;
hard deadline 8:59 PM PT.
