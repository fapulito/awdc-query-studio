"""
YugabyteDB MCP Server Module

Provides MCP server functionality for YugabyteDB (Postgres-compatible) access.
Mirrors the OracleMCPServer interface: allow-listed tables, connection pool via
psycopg v3, health_check, list_tables, describe_table, query_table, and
execute_tool dispatch.

Security posture is strictly stronger than the Oracle server:
- No user-supplied string is ever concatenated into SQL.
- All filter/aggregate values are bound parameters.
- Table names are validated against an allow-list and sanitized before use.
- Aggregation expressions, GROUP BY date functions, and ORDER BY references
  are rendered from server-side templates with fixed-set validated inputs only.
"""

import os
import re
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Set, Tuple

from modules.error_handler import (
    DatabaseError, ValidationError, TimeoutError,
    handle_database_errors, log_error_with_context
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixed-set constants — nothing outside these sets ever reaches SQL
# ---------------------------------------------------------------------------
_VALID_FILTER_OPERATORS: Set[str] = {"=", "<", ">", "<=", ">=", "BETWEEN", "IN", "date_relative"}
_VALID_AGG_FUNCTIONS: Set[str] = {"COUNT", "AVG", "SUM", "MIN", "MAX"}
_VALID_DATE_TRUNC_UNITS: Set[str] = {"month", "year", "day"}
_VALID_EXTRACT_UNITS: Set[str] = {"month", "year", "day"}
_VALID_DATE_ANCHORS: Set[str] = {"current_year_start"}
_VALID_ORDER_DIRECTIONS: Set[str] = {"ASC", "DESC"}


class YugabyteMCPServer:
    """
    MCP Server for YugabyteDB (Postgres-compatible) integration.

    Provides tools for querying allow-listed tables with full aggregation
    support via structured, parameterized query building.  The query builder
    never accepts raw SQL strings from callers — every identifier is validated
    against the live schema and every value is a bound parameter.
    """

    def __init__(self) -> None:
        """
        Initialize YugabyteMCPServer from environment variables.
        Raises ValueError if required config is missing.
        """
        self.host = os.getenv("YUGABYTE_HOST", "")
        self.port = int(os.getenv("YUGABYTE_PORT", "5433"))
        self.dbname = os.getenv("YUGABYTE_DBNAME", "yugabyte")
        self.user = os.getenv("YUGABYTE_USER", "")
        self.password = os.getenv("YUGABYTE_PASSWORD", "")
        self.sslmode = os.getenv("YUGABYTE_SSLMODE", "require")
        self.allowed_tables: List[str] = self._parse_allowed_tables()
        self.query_timeout = int(os.getenv("QUERY_TIMEOUT", "5"))
        self.max_result_size = int(os.getenv("MAX_RESULT_SIZE", "1000"))

        self._validate_configuration()
        self.pool = self._initialize_connection_pool()
        logger.info(
            "YugabyteMCPServer initialized",
            extra={"allowed_tables": self.allowed_tables, "host": self.host}
        )

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def _parse_allowed_tables(self) -> List[str]:
        """
        Parse YUGABYTE_ALLOWED_TABLES env var.

        Entries are lowercased and stripped.  Schema-qualified names
        (e.g. 'awdc.laas_population_data') are preserved as-is.

        Returns:
            List of allowed table name strings (lowercase).
        """
        raw = os.getenv("YUGABYTE_ALLOWED_TABLES", "")
        if not raw:
            return []
        return [t.strip().lower() for t in raw.split(",") if t.strip()]

    def _validate_configuration(self) -> None:
        """
        Raise ValueError if any required env var is missing.
        """
        if not self.host:
            raise ValueError("YUGABYTE_HOST environment variable is required")
        if not self.user:
            raise ValueError("YUGABYTE_USER environment variable is required")
        if not self.password:
            raise ValueError("YUGABYTE_PASSWORD environment variable is required")
        if not self.allowed_tables:
            logger.warning("YUGABYTE_ALLOWED_TABLES is empty — no tables will be accessible")

    def _initialize_connection_pool(self):
        """
        Create a psycopg v3 ConnectionPool.

        Returns the pool object; raises on failure so callers learn early.
        """
        try:
            from psycopg_pool import ConnectionPool  # psycopg[pool] or psycopg[binary]
        except ImportError:
            from psycopg.pool import ConnectionPool  # fallback path

        conninfo = (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password} sslmode={self.sslmode}"
        )
        try:
            pool = ConnectionPool(
                conninfo,
                min_size=1,
                max_size=5,
                open=False,   # open lazily on first use
            )
            pool.open(wait=True, timeout=10)
            logger.info("YugabyteDB connection pool opened")
            return pool
        except Exception as exc:
            logger.error(f"Failed to open YugabyteDB connection pool: {exc}")
            raise

    # ------------------------------------------------------------------
    # Context manager / lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def _get_connection(self):
        """Yield a psycopg v3 connection from the pool."""
        conn = self.pool.getconn()
        try:
            yield conn
        finally:
            self.pool.putconn(conn)

    def close(self) -> None:
        """Close the connection pool."""
        if self.pool:
            try:
                self.pool.close()
                logger.info("YugabyteDB connection pool closed")
            except Exception as exc:
                logger.error(f"Error closing YugabyteDB pool: {exc}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ------------------------------------------------------------------
    # Allow-list and name validation
    # ------------------------------------------------------------------

    def _is_table_allowed(self, table_name: str) -> bool:
        """Return True if table_name (lowercased) is in the allow-list."""
        return table_name.lower() in self.allowed_tables

    def _sanitize_table_name(self, table_name: str) -> str:
        """
        Validate table_name characters.

        Allows alphanumerics, underscores, and a single dot (for schema
        qualification).  Raises ValidationError on any other character.

        Returns:
            Lowercased table name.
        """
        if not re.fullmatch(r"[a-zA-Z0-9_.]+", table_name):
            raise ValidationError(
                "table_name",
                f"Invalid table name '{table_name}': only letters, digits, underscores, "
                "and a single dot (schema.table) are allowed",
            )
        return table_name.lower()

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """Execute SELECT 1 and return pool stats."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return {
                "status": "healthy",
                "message": "YugabyteDB connection is active",
                "pool_stats": {
                    "min_size": self.pool.min_size,
                    "max_size": self.pool.max_size,
                },
            }
        except Exception as exc:
            logger.error(f"YugabyteDB health check failed: {exc}")
            return {"status": "unhealthy", "message": str(exc)}

    def list_tables(self) -> Dict[str, Any]:
        """
        Return allow-listed tables with metadata from information_schema.

        Returns:
            {success, tables: [{name, schema, description}], count}
        """
        if not self.allowed_tables:
            return {"success": True, "tables": [], "count": 0, "message": "No tables configured"}

        tables_info: List[Dict[str, str]] = []

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    for qualified_name in self.allowed_tables:
                        # Split schema.table or treat unqualified as public
                        if "." in qualified_name:
                            schema_name, table_name = qualified_name.split(".", 1)
                        else:
                            schema_name, table_name = "public", qualified_name

                        cur.execute(
                            """
                            SELECT table_schema, table_name
                            FROM information_schema.tables
                            WHERE LOWER(table_schema) = %s
                              AND LOWER(table_name)   = %s
                            """,
                            (schema_name, table_name),
                        )
                        row = cur.fetchone()
                        tables_info.append({
                            "name": qualified_name,
                            "schema": schema_name,
                            "description": (
                                f"{schema_name}.{table_name}" if row else "Table not found in database"
                            ),
                        })

            return {"success": True, "tables": tables_info, "count": len(tables_info)}

        except Exception as exc:
            logger.error(f"Error listing tables: {exc}")
            return {"success": False, "error": f"Failed to list tables: {exc}"}

    def describe_table(self, table_name: str) -> Dict[str, Any]:
        """
        Return column names, data types, and nullability for an allow-listed table.

        Return shape mirrors OracleMCPServer.describe_view() so callers are
        interchangeable.

        Returns:
            {success, table_name, columns: [{name, type, nullable, position}], column_count}
        """
        try:
            table_name = self._sanitize_table_name(table_name)
            if not self._is_table_allowed(table_name):
                return {"success": False, "error": f"Table '{table_name}' is not in the allowed list"}

            if "." in table_name:
                schema_name, bare_name = table_name.split(".", 1)
            else:
                schema_name, bare_name = "public", table_name

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT column_name,
                               data_type,
                               is_nullable,
                               ordinal_position
                        FROM information_schema.columns
                        WHERE LOWER(table_schema) = %s
                          AND LOWER(table_name)   = %s
                        ORDER BY ordinal_position
                        """,
                        (schema_name, bare_name),
                    )
                    rows = cur.fetchall()

            if not rows:
                return {"success": False, "error": f"Table '{table_name}' not found or has no columns"}

            columns = [
                {
                    "name": r[0],
                    "type": r[1],
                    "nullable": r[2] == "YES",
                    "position": r[3],
                }
                for r in rows
            ]
            return {
                "success": True,
                "table_name": table_name,
                "columns": columns,
                "column_count": len(columns),
            }

        except ValidationError as exc:
            return {"success": False, "error": exc.message}
        except Exception as exc:
            logger.error(f"Error describing table {table_name}: {exc}")
            return {"success": False, "error": f"Failed to describe table: {exc}"}

    def _get_valid_columns(self, table_name: str) -> Set[str]:
        """
        Return a set of lowercased valid column names for table_name.

        Makes one DB round-trip; callers should cache the result within a
        single query_table invocation.
        """
        result = self.describe_table(table_name)
        if not result.get("success"):
            raise ValidationError("table_name", result.get("error", "Could not describe table"))
        return {col["name"].lower() for col in result["columns"]}

    # ------------------------------------------------------------------
    # Query-builder helpers — nothing from these methods concatenates a
    # user-supplied string into SQL.
    # ------------------------------------------------------------------

    def _resolve_date_relative(self, value: Dict[str, Any]) -> str:
        """
        Resolve a date_relative value object to a safe SQL expression.

        Recognized anchors: "current_year_start"
        offset_years: integer offset (0 = no offset, -1 = minus 1 year, etc.)

        Returns a SQL expression string (safe — rendered from fixed templates).
        Raises ValidationError on unrecognized anchor.
        """
        anchor = value.get("anchor", "")
        if anchor not in _VALID_DATE_ANCHORS:
            raise ValidationError(
                "date_relative.anchor",
                f"Unknown anchor '{anchor}'. Valid anchors: {sorted(_VALID_DATE_ANCHORS)}",
            )
        offset_years = int(value.get("offset_years", 0))  # cast to int — never a string
        base_expr = "DATE_TRUNC('year', CURRENT_DATE)"
        if offset_years == 0:
            return base_expr
        # offset_years is an integer computed here on the server; it never came from a
        # user-supplied SQL fragment.
        direction = "+" if offset_years > 0 else "-"
        abs_years = abs(offset_years)
        return f"{base_expr} {direction} INTERVAL '{abs_years} years'"

    def _build_filter_sql(
        self,
        filter_obj: Dict[str, Any],
        params: List[Any],
        valid_columns: Set[str],
    ) -> str:
        """
        Build a single WHERE predicate fragment from a structured filter object.

        filter_obj keys:
            column   — column name (validated against valid_columns)
            operator — one of _VALID_FILTER_OPERATORS
            value    — scalar | list (for IN) | {anchor, offset_years} (for date_relative)

        All non-date_relative values are appended to params as bound parameters.

        Returns a SQL fragment string (no user strings embedded).
        Raises ValidationError on invalid column or operator.
        """
        col = filter_obj.get("column", "").lower()
        operator = filter_obj.get("operator", "")
        value = filter_obj.get("value")

        if col not in valid_columns:
            raise ValidationError("filter.column", f"Unknown column '{col}'")
        if operator not in _VALID_FILTER_OPERATORS:
            raise ValidationError(
                "filter.operator",
                f"Invalid operator '{operator}'. Valid: {sorted(_VALID_FILTER_OPERATORS)}",
            )

        # Use quoted identifier — col has already been validated against the schema
        quoted_col = f'"{col}"'

        if operator == "date_relative":
            sql_expr = self._resolve_date_relative(value)
            # The resolved expression is a server-side constant; no user string embedded
            return f"{quoted_col} = {sql_expr}"

        if operator == "BETWEEN":
            if not (isinstance(value, (list, tuple)) and len(value) == 2):
                raise ValidationError("filter.value", "BETWEEN requires a list of exactly 2 values")
            params.append(value[0])
            params.append(value[1])
            return f"{quoted_col} BETWEEN %s AND %s"

        if operator == "IN":
            if not isinstance(value, (list, tuple)) or len(value) == 0:
                raise ValidationError("filter.value", "IN requires a non-empty list")
            placeholders = ", ".join(["%s"] * len(value))
            params.extend(value)
            return f"{quoted_col} IN ({placeholders})"

        # Simple comparison: =, <, >, <=, >=
        params.append(value)
        return f"{quoted_col} {operator} %s"

    def _build_group_by_expr(
        self,
        item: Any,
        valid_columns: Set[str],
    ) -> Tuple[str, str]:
        """
        Build a GROUP BY / SELECT expression from a group_by list item.

        item may be:
          - str  — plain column name (validated)
          - dict — {column, date_trunc: "month"|"year"|"day"}
                   {column, extract:   "month"|"year"|"day"}

        Returns:
            (select_expr, alias) — select_expr goes into SELECT and GROUP BY;
            alias is used for ORDER BY references.
        """
        if isinstance(item, str):
            col = item.lower()
            if col not in valid_columns:
                raise ValidationError("group_by", f"Unknown column '{col}'")
            return f'"{col}"', col

        if not isinstance(item, dict):
            raise ValidationError("group_by", "group_by items must be a column name or a dict")

        col = item.get("column", "").lower()
        if col not in valid_columns:
            raise ValidationError("group_by.column", f"Unknown column '{col}'")

        if "date_trunc" in item:
            unit = item["date_trunc"].lower()
            if unit not in _VALID_DATE_TRUNC_UNITS:
                raise ValidationError(
                    "group_by.date_trunc",
                    f"Invalid unit '{unit}'. Valid: {sorted(_VALID_DATE_TRUNC_UNITS)}",
                )
            alias = f"{col}_{unit}"
            expr = f"DATE_TRUNC('{unit}', \"{col}\")"
            return expr, alias

        if "extract" in item:
            unit = item["extract"].lower()
            if unit not in _VALID_EXTRACT_UNITS:
                raise ValidationError(
                    "group_by.extract",
                    f"Invalid unit '{unit}'. Valid: {sorted(_VALID_EXTRACT_UNITS)}",
                )
            alias = f"{col}_{unit}"
            expr = f"EXTRACT({unit} FROM \"{col}\")"
            return expr, alias

        raise ValidationError("group_by", "dict items must have 'date_trunc' or 'extract' key")

    def _build_aggregate_expr(
        self,
        agg_obj: Dict[str, Any],
        params: List[Any],
        valid_columns: Set[str],
    ) -> Tuple[str, str]:
        """
        Build an aggregate SELECT expression from a structured aggregate object.

        agg_obj keys:
            function — one of COUNT | AVG | SUM | MIN | MAX
            column   — validated column name, or '*' for COUNT only
            alias    — output alias (alphanumeric/underscore only)
            round    — optional int: digits for ROUND(...)
            filter   — optional {column, operator, value} for FILTER (WHERE ...)

        Returns:
            (sql_expr, alias)
        Raises ValidationError on invalid inputs.
        """
        func = agg_obj.get("function", "").upper()
        col = agg_obj.get("column", "")
        alias = agg_obj.get("alias", func.lower())
        round_digits = agg_obj.get("round")
        filter_obj = agg_obj.get("filter")

        if func not in _VALID_AGG_FUNCTIONS:
            raise ValidationError(
                "aggregate.function",
                f"Invalid function '{func}'. Valid: {sorted(_VALID_AGG_FUNCTIONS)}",
            )

        # Validate alias — only safe identifier characters
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", alias):
            raise ValidationError(
                "aggregate.alias",
                f"Invalid alias '{alias}': only letters, digits, underscores allowed, must start with letter/underscore",
            )

        # Validate column
        if col == "*":
            if func != "COUNT":
                raise ValidationError("aggregate.column", "Only COUNT may use '*' as column")
            col_expr = "*"
        else:
            col_lower = col.lower()
            if col_lower not in valid_columns:
                raise ValidationError("aggregate.column", f"Unknown column '{col}'")
            col_expr = f'"{col_lower}"'

        inner = f"{func}({col_expr})"

        # Optional FILTER (WHERE ...) clause
        if filter_obj:
            filter_sql = self._build_filter_sql(filter_obj, params, valid_columns)
            inner = f"{func}({col_expr}) FILTER (WHERE {filter_sql})"

        # Optional ROUND
        if round_digits is not None:
            digits = int(round_digits)  # enforce integer, never user string
            inner = f"ROUND(CAST({inner} AS NUMERIC), {digits})"

        return f"{inner} AS \"{alias}\"", alias

    # ------------------------------------------------------------------
    # Main query entry point
    # ------------------------------------------------------------------

    @handle_database_errors
    def query_table(
        self,
        table_name: str,
        filters: Optional[List[Dict[str, Any]]] = None,
        aggregates: Optional[List[Dict[str, Any]]] = None,
        group_by: Optional[List[Any]] = None,
        order_by: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute a safe SELECT query on an allow-listed table.

        Supports plain row fetch, structured WHERE filters, aggregation
        (COUNT/AVG/SUM/MIN/MAX), GROUP BY with optional date expressions,
        and ORDER BY.  All values are bound parameters; all identifiers are
        validated against the live schema.

        Args:
            table_name  — allow-listed, schema-qualified table name.
            filters     — list of {column, operator, value} filter objects.
            aggregates  — list of {function, column, alias, round?, filter?}.
            group_by    — list of column names or date-expression dicts.
            order_by    — {by: alias_or_column, direction: ASC|DESC}.
            limit       — max rows (capped at MAX_RESULT_SIZE).

        Returns:
            {success, table_name, columns, rows, row_count, limited}
        """
        try:
            table_name = self._sanitize_table_name(table_name)
        except ValidationError as exc:
            raise ValidationError("table_name", exc.message)

        if not self._is_table_allowed(table_name):
            raise ValidationError(
                "table_name",
                f"Table '{table_name}' is not in the allowed list",
                {"allowed_tables": self.allowed_tables},
            )

        # One schema round-trip per query_table call
        valid_columns = self._get_valid_columns(table_name)

        effective_limit = min(limit or self.max_result_size, self.max_result_size)
        params: List[Any] = []

        # ----------------------------------------------------------
        # Build SELECT clause
        # ----------------------------------------------------------
        has_aggregates = bool(aggregates)
        has_group_by = bool(group_by)

        select_parts: List[str] = []
        group_by_exprs: List[str] = []       # SQL expressions for GROUP BY clause
        group_by_aliases: List[str] = []     # aliases for ORDER BY reference
        agg_aliases: List[str] = []

        if has_group_by:
            for item in group_by:
                expr, alias = self._build_group_by_expr(item, valid_columns)
                select_parts.append(f"{expr} AS \"{alias}\"")
                group_by_exprs.append(expr)
                group_by_aliases.append(alias)

        if has_aggregates:
            for agg in aggregates:
                expr, alias = self._build_aggregate_expr(agg, params, valid_columns)
                select_parts.append(expr)
                agg_aliases.append(alias)

        if not select_parts:
            # Plain row fetch
            select_clause = "*"
        else:
            select_clause = ", ".join(select_parts)

        # ----------------------------------------------------------
        # Build WHERE clause
        # ----------------------------------------------------------
        where_parts: List[str] = []
        if filters:
            for f in filters:
                where_parts.append(self._build_filter_sql(f, params, valid_columns))
        where_clause = " AND ".join(where_parts)

        # ----------------------------------------------------------
        # Build ORDER BY clause
        # ----------------------------------------------------------
        order_clause = ""
        if order_by:
            by_raw = order_by.get("by", "").lower()
            direction = order_by.get("direction", "ASC").upper()
            if direction not in _VALID_ORDER_DIRECTIONS:
                raise ValidationError(
                    "order_by.direction",
                    f"Invalid direction '{direction}'. Use ASC or DESC",
                )
            # by must reference a group_by alias or aggregate alias (both server-generated)
            all_aliases = group_by_aliases + agg_aliases + list(valid_columns)
            if by_raw not in [a.lower() for a in all_aliases]:
                raise ValidationError(
                    "order_by.by",
                    f"ORDER BY target '{by_raw}' must reference a group_by alias, "
                    "aggregate alias, or valid column name",
                )
            order_clause = f'ORDER BY "{by_raw}" {direction}'

        # ----------------------------------------------------------
        # Assemble full query
        # ----------------------------------------------------------
        sql = f'SELECT {select_clause} FROM "{table_name}"'
        # For schema-qualified names the table itself must be quoted properly
        # e.g. "awdc"."laas_population_data"
        if "." in table_name:
            schema_part, bare_part = table_name.split(".", 1)
            sql = f'SELECT {select_clause} FROM "{schema_part}"."{bare_part}"'

        if where_clause:
            sql += f" WHERE {where_clause}"

        if group_by_exprs:
            sql += " GROUP BY " + ", ".join(group_by_exprs)

        if order_clause:
            sql += f" {order_clause}"

        sql += " LIMIT %s"
        params.append(effective_limit)

        logger.debug(f"Executing YugabyteDB query: {sql} | params count: {len(params)}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(sql, params)
                except Exception as exc:
                    raise DatabaseError(
                        f"Query execution failed: {exc}",
                        query=sql,
                        details={"table_name": table_name},
                    )
                col_names = [desc.name for desc in cur.description]
                raw_rows = cur.fetchall()

        rows = []
        for raw_row in raw_rows:
            row_dict: Dict[str, Any] = {}
            for col_name, value in zip(col_names, raw_row):
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                elif isinstance(value, (bytes, bytearray)):
                    value = value.hex()
                row_dict[col_name] = value
            rows.append(row_dict)

        logger.info(f"YugabyteDB query on '{table_name}': {len(rows)} rows returned")

        return {
            "success": True,
            "table_name": table_name,
            "columns": col_names,
            "rows": rows,
            "row_count": len(rows),
            "limited": len(rows) >= effective_limit,
        }

    # ------------------------------------------------------------------
    # MCP interface
    # ------------------------------------------------------------------

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Return MCP tool definitions for the LLM.

        Exposes: yb_list_tables, yb_describe_table, yb_query_table.
        The yb_query_table schema fully documents aggregates, group_by, and
        order_by so the model can construct the right call without guessing.
        """
        return [
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
                                        "enum": ["=", "<", ">", "<=", ">=", "BETWEEN", "IN", "date_relative"],
                                    },
                                    "value": {
                                        "description": (
                                            "Scalar, list (for IN/BETWEEN), or "
                                            "{anchor, offset_years} for date_relative. "
                                            "anchor must be 'current_year_start'."
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
                            "description": f"Max rows (server cap: {self.max_result_size})",
                        },
                    },
                    "required": ["table_name"],
                },
            },
        ]

    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch an MCP tool call by name.

        Args:
            tool_name  — one of yb_list_tables | yb_describe_table | yb_query_table
            parameters — tool parameters dict

        Returns:
            Tool result dict (same shape as OracleMCPServer.execute_tool).
        """
        if tool_name == "yb_list_tables":
            return self.list_tables()

        if tool_name == "yb_describe_table":
            return self.describe_table(table_name=parameters.get("table_name", ""))

        if tool_name == "yb_query_table":
            return self.query_table(
                table_name=parameters.get("table_name", ""),
                filters=parameters.get("filters"),
                aggregates=parameters.get("aggregates"),
                group_by=parameters.get("group_by"),
                order_by=parameters.get("order_by"),
                limit=parameters.get("limit"),
            )

        return {"success": False, "error": f"Unknown tool: {tool_name}"}
