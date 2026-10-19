# 🐾 AWDC Query Studio


![Python](https://img.shields.io/badge/Python-3.x-blue) ![Flask](https://img.shields.io/badge/Flask-3.0-black) ![MCP](https://img.shields.io/badge/Protocol-MCP-purple) ![YugabyteDB](https://img.shields.io/badge/DB-YugabyteDB-orange) ![Deployed on Vercel](https://img.shields.io/badge/Deployed-Vercel-black) ![License: MIT](https://img.shields.io/badge/License-MIT-green)
**Natural-language querying for municipal animal shelter data.**
Ask in plain English; an LLM assistant answers by calling database tools — never by writing raw SQL.

Built for AngelHack **"Building with IBM Bob"** (build window Sep 28 – Oct 18, 2026), Experienced Developers track ("Modernize What Matters"), by David Anderson — volunteer with the Animal Welfare Data Center since 2024.

## 🎯 What it does

Municipal animal shelter data is public (collected via FOIA) but effectively locked behind database skills. This project modernizes the Animal Welfare Data Center's legacy stack — an Oracle APEX portal and a production Flask chatbot — into a query studio where shelter staff, advocates, and journalists ask questions in plain English:

- *"How did intakes trend month by month in the last full year of data?"*
- *"What were the outcomes by species?"*
- *"What is the average length of stay, overall and by species?"*
- *"Which outcome types are most common for dogs vs. cats?"*
- *"In which months do intakes peak?"*

## 🔴 Live demo

- App: https://chat.california.vision (OAuth sign-in required)
- Demo video (≤3 min): [YOUTUBE LINK]
- The five questions above are the demo script.

## 🗄️ Data

YugabyteDB cluster (Postgres-compatible), schema `awdc`, **346,734 municipal shelter records** across seven Southern California county tables — Los Angeles (`laas_population_data`, 59,153), Orange County (`ocac_shelter_data`, 192,149), Riverside (two tables, 80,088), San Bernardino (three tables, 15,344). Animal-level records only; no pet-owner PII columns.

## 🏗️ Architecture

Flask app on Vercel (serverless), OAuth2 sign-in (Google, GitHub, Facebook, LinkedIn, Auth0). The LLM (OpenAI, tool-calling) reaches data only through **Model Context Protocol (MCP) tool servers** that run in-process:

| Tool server | Backend | Tools |
|---|---|---|
| `modules/oracle_mcp_server.py` (legacy) | Oracle APEX views | `query_view`, `list_views`, `describe_view` |
| `modules/yugabyte_mcp_server.py` (**new, built with Bob**) | YugabyteDB | `yb_list_tables`, `yb_describe_table`, `yb_query_table` |
| `modules/pdf_mcp_server.py` (legacy) | PDF documents | `search_pdfs`, `get_document`, `list_documents` |

🔒 **Safety model.** The model never emits SQL. `yb_query_table` accepts *structured* filters ({column, operator, value} from a fixed operator set, including a server-rendered `date_relative` operator), *structured* aggregations (COUNT/AVG/SUM/MIN/MAX with optional FILTER clauses), and `group_by` on validated columns or server-templated date expressions. Every identifier is validated against the table schema and an allow-list (`YUGABYTE_ALLOWED_TABLES`); every value is a bound parameter; the app connects as a **read-only** database user.

## 🤖 What IBM Bob Delivered

Bob was the development partner for the entire modernization project. Session exports are in `bob_sessions/`.

Session | What Bob did |
|---|---|
| Ask mode — full audit | Audited the legacy chatbot end-to-end: architecture, data model, PII handling, and a 16-item prioritized modernization list. Found a real SQL-injection weakness (raw WHERE-clause concatenation in the Oracle server) and a hardcoded localhost URL in the APEX package. |
| Plan mode — brief review | Reviewed the Yugabyte implementation brief against the audited code, confirmed every claim, and caught a design gap: the demo questions are aggregate queries that a filter-only tool cannot express — prompting the structured-aggregation extension before any code was written. |
| Plan mode — design decisions | Resolved the open design questions with the developer: `date_relative` filter operator (server-rendered anchors/offsets), schema exposure via `yb_describe_table` plus server-side validation, `ApexRestHandler` extended with an optional Yugabyte argument, describe-once-per-table prompt rule. Produced `bob_sessions/yugabyte-plan.md`. |
| Agent mode — build | Wrote `modules/yugabyte_mcp_server.py` (570 lines) and `scripts/smoke_yugabyte.py`; wired the new backend into both entry points (`app.py`, `api/index.py`), the MCP client, and the LLM system prompt; raised the Vercel function timeout 10s → 30s for TLS cold starts; updated config/docs; wrote `tests/test_yugabyte_integration.py`. Smoke check against the live cluster: **PASSED**. |

The modernization roadmap in the README of the legacy repo (de-duplicating `app.py`/`api/index.py`, parameterizing the APEX package URL, applying the same structured-filter hardening to the Oracle server) comes directly from Bob's audit.

## 📦 Legacy assets vs. new code (Fresh Code Rule)

Pre-existing assets (not submitted as new work): the Oracle APEX application, the `awdc` dataset, and the Flask chatbot codebase (`github.com/calivision/awdc-chat`, private; live at chat.california.vision). **All code in this repository's modernization layer — the Yugabyte MCP server, its wiring, the smoke check, and its tests — was written during the build window**, working from the working tree of the legacy app, with Bob session exports as the dated record. This submission repo is a clean export of that state.

## 🚀 Run it

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in Oracle and/or Yugabyte + LLM + OAuth values
python app.py          # local dev; production entry point is api/index.py on Vercel
python scripts/smoke_yugabyte.py   # verifies the Yugabyte backend end-to-end
```

Key env vars: `LLM_PROVIDER=openai`, `LLM_API_KEY`, `LLM_MODEL=gpt-4o`, `YUGABYTE_HOST/PORT/DBNAME/USER/PASSWORD/SSLMODE`, `YUGABYTE_ALLOWED_TABLES`. Secrets live only in `.env` / Vercel env — never in this repo.

The legacy chatbot's original README — full quick-start, Vercel deployment, and OAuth setup documentation — is preserved verbatim at `docs/LEGACY_README.md`.

## 🗺️ Roadmap

- Apply the structured-filter pattern to the legacy Oracle server (closes the audit's P1 injection finding there too).
- Freemium subscriptions via Stripe — the pattern is already in production in the author's Textract SaaS (free/pro/enterprise tiers, Checkout + webhooks) and ports directly.
- More municipalities beyond Southern California; charts and exports (CSV/Excel) alongside result tables.
