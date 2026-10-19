"""
Smoke-check script for YugabyteMCPServer.

Runs one describe_table call and one aggregate query_table call against the
live YugabyteDB Aeon cluster.  Requires YUGABYTE_* vars in .env or environment.

Usage:
    python scripts/smoke_yugabyte.py

Exit codes:
    0 — passed (or not configured)
    1 — failed
"""

import sys
import json
import os

# Load .env from project root
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env")
except ImportError:
    pass  # dotenv optional — rely on shell env

# Guard: only proceed if configured
if not os.getenv("YUGABYTE_HOST"):
    print("YUGABYTE_HOST is not set — YugabyteDB not configured, skipping smoke check.")
    sys.exit(0)

print("=== YugabyteDB Smoke Check ===")
print(f"Host : {os.getenv('YUGABYTE_HOST')}")
print(f"DB   : {os.getenv('YUGABYTE_DBNAME', 'yugabyte')}")
print(f"User : {os.getenv('YUGABYTE_USER')}")
print()

try:
    from modules.yugabyte_mcp_server import YugabyteMCPServer
except Exception as exc:
    print(f"FAIL — could not import YugabyteMCPServer: {exc}")
    sys.exit(1)

try:
    server = YugabyteMCPServer()
except Exception as exc:
    print(f"FAIL — could not instantiate YugabyteMCPServer: {exc}")
    sys.exit(1)

TABLE = os.getenv("YUGABYTE_ALLOWED_TABLES", "awdc.laas_population_data").split(",")[0].strip()

# --- 1. health_check ---
print("--- health_check ---")
try:
    health = server.health_check()
    print(json.dumps(health, indent=2))
    if health.get("status") != "healthy":
        print("FAIL — health check returned unhealthy")
        sys.exit(1)
    print()
except Exception as exc:
    print(f"FAIL — health_check raised: {exc}")
    sys.exit(1)

# --- 2. describe_table ---
print(f"--- describe_table('{TABLE}') ---")
try:
    desc = server.describe_table(TABLE)
    if not desc.get("success"):
        print(f"FAIL — describe_table: {desc.get('error')}")
        sys.exit(1)
    print(f"Columns ({desc['column_count']}):")
    for col in desc["columns"]:
        nullable = "NULL" if col["nullable"] else "NOT NULL"
        print(f"  {col['position']:>3}. {col['name']:<30} {col['type']:<20} {nullable}")
    print()
except Exception as exc:
    print(f"FAIL — describe_table raised: {exc}")
    sys.exit(1)

# --- 3. query_table — aggregate: COUNT(*) GROUP BY animal_type ---
print(f"--- query_table: COUNT(*) GROUP BY animal_type (limit 10) ---")
try:
    result = server.query_table(
        table_name=TABLE,
        aggregates=[{"function": "COUNT", "column": "*", "alias": "count"}],
        group_by=["animal_type"],
        order_by={"by": "count", "direction": "DESC"},
        limit=10,
    )
    if not result.get("success"):
        print(f"FAIL — query_table: {result.get('error')}")
        sys.exit(1)
    print(f"Row count: {result['row_count']}")
    for row in result["rows"]:
        print(f"  {row}")
    print()
except Exception as exc:
    print(f"FAIL — query_table raised: {exc}")
    sys.exit(1)

server.close()
print("=== Smoke check PASSED ===")
sys.exit(0)
