"""
Oracle APEX MCP Server Module

This module provides MCP server functionality for Oracle database access.
It implements connection pooling, secure credential management, and exposes
database views as MCP tools.

Security model: all user-supplied values are bound parameters; all
column/view identifiers are validated against a fixed allow-list and the
live Oracle data dictionary before use.  No free-form SQL is ever accepted
from the LLM.
"""

import os
import logging
import re
from typing import Dict, List, Optional, Any, Set
from contextlib import contextmanager
import oracledb
from modules.error_handler import (
    DatabaseError, ValidationError, TimeoutError,
    handle_database_errors, log_error_with_context
)
from modules.serverless_optimizer import get_connection_cache, optimize_cold_start

# ---------------------------------------------------------------------------
# Allowed filter operators — fixed set, never extended from user input
# ---------------------------------------------------------------------------
_VALID_FILTER_OPERATORS: Set[str] = {"=", "<", ">", "<=", ">=", "BETWEEN", "IN"}

# Oracle column name: letters, digits, underscore, hash, dollar — no spaces,
# no SQL meta-characters.  Same conservative pattern as the Yugabyte server.
_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_#$]*$')

logger = logging.getLogger(__name__)


class OracleMCPServer:
    """
    MCP Server for Oracle APEX database integration.
    
    Provides tools for querying database views, listing available views,
    and describing view schemas with built-in security and performance features.
    """
    
    def __init__(self):
        """
        Initialize Oracle MCP Server with configuration from environment variables.
        Uses connection caching for serverless optimization.
        Requirements: 2.4, 2.5
        """
        self.connection_string = os.getenv('ORACLE_CONNECTION_STRING')
        self.username = os.getenv('ORACLE_USER')
        self.password = os.getenv('ORACLE_PASSWORD')
        self.allowed_views = self._parse_allowed_views()
        self.query_timeout = int(os.getenv('QUERY_TIMEOUT', '5'))
        self.max_result_size = int(os.getenv('MAX_RESULT_SIZE', '1000'))
        
        # Check connection cache first
        cache = get_connection_cache()
        self.pool = cache.get('oracle_connection_pool')
        
        self._validate_configuration()
        
        # Only initialize if not cached
        if self.pool is None:
            self._initialize_connection_pool()
            # Cache the connection pool
            if self.pool:
                cache.set('oracle_connection_pool', self.pool)
    
    def _validate_configuration(self) -> None:
        """
        Validate that all required configuration is present.
        
        Raises:
            ValueError: If required environment variables are missing
        """
        if not self.connection_string:
            raise ValueError("ORACLE_CONNECTION_STRING environment variable is required")
        if not self.username:
            raise ValueError("ORACLE_USER environment variable is required")
        if not self.password:
            raise ValueError("ORACLE_PASSWORD environment variable is required")
        if not self.allowed_views:
            logger.warning("ORACLE_ALLOWED_VIEWS is empty - no views will be accessible")
    
    def _parse_allowed_views(self) -> List[str]:
        """
        Parse the comma-separated list of allowed views from environment.
        
        Returns:
            List of allowed view names (uppercase, stripped)
        """
        views_str = os.getenv('ORACLE_ALLOWED_VIEWS', '')
        if not views_str:
            return []
        return [view.strip().upper() for view in views_str.split(',') if view.strip()]
    
    def _initialize_connection_pool(self) -> None:
        """
        Initialize Oracle connection pool for efficient connection management.
        
        Uses oracledb connection pooling with configurable min/max connections.
        """
        try:
            # Parse connection string (format: host:port/service_name)
            parts = self.connection_string.split('/')
            if len(parts) != 2:
                raise ValueError("Invalid connection string format. Expected: host:port/service_name")
            
            host_port = parts[0]
            service_name = parts[1]
            
            if ':' in host_port:
                host, port = host_port.split(':')
                port = int(port)
            else:
                host = host_port
                port = 1521  # Default Oracle port
            
            # Create connection pool
            self.pool = oracledb.create_pool(
                user=self.username,
                password=self.password,
                dsn=f"{host}:{port}/{service_name}",
                min=1,
                max=5,
                increment=1,
                getmode=oracledb.POOL_GETMODE_WAIT
            )
            
            logger.info("Oracle connection pool initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Oracle connection pool: {str(e)}")
            raise
    
    @contextmanager
    def _get_connection(self):
        """
        Context manager for acquiring and releasing database connections.
        
        Yields:
            Oracle database connection from the pool
        """
        connection = None
        try:
            connection = self.pool.acquire()
            yield connection
        finally:
            if connection:
                self.pool.release(connection)
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on database connection.
        
        Returns:
            Dictionary with health status and details
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM DUAL")
                result = cursor.fetchone()
                cursor.close()
                
                if result and result[0] == 1:
                    return {
                        "status": "healthy",
                        "message": "Database connection is active",
                        "pool_status": {
                            "open_connections": self.pool.opened,
                            "busy_connections": self.pool.busy
                        }
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "message": "Unexpected query result"
                    }
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return {
                "status": "unhealthy",
                "message": f"Health check failed: {str(e)}"
            }
    
    def close(self) -> None:
        """Close the connection pool and release all resources."""
        if self.pool:
            try:
                self.pool.close()
                logger.info("Oracle connection pool closed")
            except Exception as e:
                logger.error(f"Error closing connection pool: {str(e)}")
    
    def __enter__(self):
        """Support context manager protocol."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Support context manager protocol."""
        self.close()
    
    def _is_view_allowed(self, view_name: str) -> bool:
        """
        Check if a view is in the allowed list.
        
        Args:
            view_name: Name of the view to check
            
        Returns:
            True if view is allowed, False otherwise
        """
        return view_name.upper() in self.allowed_views
    
    def _sanitize_view_name(self, view_name: str) -> str:
        """
        Sanitize view name to prevent SQL injection.
        
        Args:
            view_name: View name to sanitize
            
        Returns:
            Sanitized view name
            
        Raises:
            ValueError: If view name contains invalid characters
        """
        # Only allow alphanumeric characters and underscores
        if not view_name.replace('_', '').isalnum():
            raise ValueError(f"Invalid view name: {view_name}")
        return view_name.upper()
    
    def list_views(self) -> Dict[str, Any]:
        """
        List all available database views that are whitelisted.
        
        Returns:
            Dictionary containing list of available views with metadata
        """
        try:
            if not self.allowed_views:
                return {
                    "success": True,
                    "views": [],
                    "message": "No views are configured"
                }
            
            views_info = []
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                for view_name in self.allowed_views:
                    try:
                        # Get view metadata from Oracle data dictionary
                        query = """
                            SELECT comments 
                            FROM user_tab_comments 
                            WHERE table_name = :view_name 
                            AND table_type = 'VIEW'
                        """
                        cursor.execute(query, {"view_name": view_name})
                        result = cursor.fetchone()
                        
                        views_info.append({
                            "name": view_name,
                            "description": result[0] if result and result[0] else "No description available"
                        })
                    except Exception as e:
                        logger.warning(f"Could not fetch metadata for view {view_name}: {str(e)}")
                        views_info.append({
                            "name": view_name,
                            "description": "Metadata unavailable"
                        })
                
                cursor.close()
            
            return {
                "success": True,
                "views": views_info,
                "count": len(views_info)
            }
            
        except Exception as e:
            logger.error(f"Error listing views: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to list views: {str(e)}"
            }
    
    def describe_view(self, view_name: str) -> Dict[str, Any]:
        """
        Get schema information for a specific view.
        
        Args:
            view_name: Name of the view to describe
            
        Returns:
            Dictionary containing column information and metadata
        """
        try:
            # Sanitize and validate view name
            view_name = self._sanitize_view_name(view_name)
            
            if not self._is_view_allowed(view_name):
                return {
                    "success": False,
                    "error": f"View '{view_name}' is not in the allowed list"
                }
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Get column information
                query = """
                    SELECT 
                        column_name,
                        data_type,
                        data_length,
                        nullable,
                        column_id
                    FROM user_tab_columns
                    WHERE table_name = :view_name
                    ORDER BY column_id
                """
                cursor.execute(query, {"view_name": view_name})
                columns = cursor.fetchall()
                
                if not columns:
                    cursor.close()
                    return {
                        "success": False,
                        "error": f"View '{view_name}' not found or has no columns"
                    }
                
                # Format column information
                column_info = []
                for col in columns:
                    column_info.append({
                        "name": col[0],
                        "type": col[1],
                        "length": col[2],
                        "nullable": col[3] == 'Y',
                        "position": col[4]
                    })
                
                cursor.close()
                
                return {
                    "success": True,
                    "view_name": view_name,
                    "columns": column_info,
                    "column_count": len(column_info)
                }
                
        except ValueError as e:
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"Error describing view {view_name}: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to describe view: {str(e)}"
            }
    
    # ------------------------------------------------------------------
    # Query-builder helpers
    # ------------------------------------------------------------------

    def _get_valid_columns(self, view_name: str) -> Set[str]:
        """
        Return the set of lowercased column names that exist in *view_name*.

        Queries user_tab_columns with a bind parameter — the view name has
        already been sanitised and allow-listed before this is called.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT column_name FROM user_tab_columns WHERE table_name = :vn",
                    {"vn": view_name},
                )
                return {row[0].lower() for row in cursor.fetchall()}
            finally:
                cursor.close()

    def _build_filter_sql(
        self,
        filter_obj: Dict[str, Any],
        bind_params: Dict[str, Any],
        valid_columns: Set[str],
    ) -> str:
        """
        Build a single WHERE predicate from a structured filter object.

        filter_obj keys:
            column   — column name (validated against valid_columns)
            operator — one of _VALID_FILTER_OPERATORS
            value    — scalar | list of 2 (BETWEEN) | list (IN)

        Values are placed in bind_params as named Oracle bind parameters
        (:param_N).  The returned string contains only :param_N placeholders
        and quoted identifiers — no user strings are ever interpolated.

        Raises ValidationError on invalid column or operator.
        """
        col = filter_obj.get("column", "").upper()
        operator = filter_obj.get("operator", "")
        value = filter_obj.get("value")

        if col.lower() not in valid_columns:
            raise ValidationError("filter.column", f"Unknown column '{col}'")
        if operator not in _VALID_FILTER_OPERATORS:
            raise ValidationError(
                "filter.operator",
                f"Invalid operator '{operator}'. Valid: {sorted(_VALID_FILTER_OPERATORS)}",
            )

        # Oracle allows double-quoted identifiers; col is uppercased from the
        # data dictionary so quoting is safe.
        quoted_col = f'"{col}"'
        param_base = f"param_{len(bind_params)}"

        if operator == "BETWEEN":
            if not (isinstance(value, (list, tuple)) and len(value) == 2):
                raise ValidationError("filter.value", "BETWEEN requires a list of exactly 2 values")
            k_lo = f"{param_base}_lo"
            k_hi = f"{param_base}_hi"
            bind_params[k_lo] = value[0]
            bind_params[k_hi] = value[1]
            return f"{quoted_col} BETWEEN :{k_lo} AND :{k_hi}"

        if operator == "IN":
            if not isinstance(value, (list, tuple)) or len(value) == 0:
                raise ValidationError("filter.value", "IN requires a non-empty list")
            placeholders = []
            for i, v in enumerate(value):
                k = f"{param_base}_in{i}"
                bind_params[k] = v
                placeholders.append(f":{k}")
            return f"{quoted_col} IN ({', '.join(placeholders)})"

        # Simple comparison: =, <, >, <=, >=
        bind_params[param_base] = value
        return f"{quoted_col} {operator} :{param_base}"

    @handle_database_errors
    def query_view(
        self,
        view_name: str,
        filters: Optional[List[Dict[str, Any]]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute a safe SELECT query on a whitelisted Oracle view.

        All user-supplied values are bound parameters; all identifiers are
        validated against the allow-list and the live Oracle data dictionary.
        Free-form SQL is never accepted.

        Args:
            view_name: Name of the view to query (must be on the allow-list).
            filters:   Optional list of structured filter objects, each with
                       {column, operator, value}.  Supported operators:
                       =, <, >, <=, >=, BETWEEN, IN.
            limit:     Maximum number of rows to return.

        Returns:
            {success, view_name, columns, rows, row_count, limited,
             executed_sql, parameters}

        Raises:
            DatabaseError:  On query execution failure.
            ValidationError: On invalid input.
        """
        try:
            try:
                view_name = self._sanitize_view_name(view_name)
            except ValueError as e:
                raise ValidationError("view_name", str(e))

            if not self._is_view_allowed(view_name):
                raise ValidationError(
                    "view_name",
                    f"View '{view_name}' is not in the allowed list",
                    {"allowed_views": self.allowed_views},
                )

            effective_limit = min(limit or self.max_result_size, self.max_result_size)

            # One schema round-trip to get the live column set
            valid_columns = self._get_valid_columns(view_name)

            # Build WHERE clause — all values go into bind_params
            bind_params: Dict[str, Any] = {}
            where_parts: List[str] = []
            if filters:
                for f in filters:
                    where_parts.append(
                        self._build_filter_sql(f, bind_params, valid_columns)
                    )

            # Oracle double-quotes the view name; _sanitize_view_name ensures
            # it contains only [A-Za-z0-9_], so quoting is safe.
            sql = f'SELECT * FROM "{view_name}"'
            if where_parts:
                sql += " WHERE " + " AND ".join(where_parts)

            # Row-limit via subquery + ROWNUM (standard Oracle pattern)
            bind_params["_limit"] = effective_limit
            sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= :_limit"

            with self._get_connection() as conn:
                cursor = conn.cursor()
                try:
                    try:
                        cursor.execute(sql, bind_params)
                    except oracledb.DatabaseError as e:
                        error_obj, = e.args
                        if error_obj.code == 1013:
                            raise TimeoutError("database_query", self.query_timeout, {
                                "view_name": view_name,
                                "query": sql,
                            })
                        raise DatabaseError(
                            f"Query execution failed: {error_obj.message}",
                            query=sql,
                            details={"error_code": error_obj.code},
                        )

                    columns = [desc[0] for desc in cursor.description]
                    rows_raw = cursor.fetchall()
                finally:
                    cursor.close()

            results = []
            for row in rows_raw:
                row_dict: Dict[str, Any] = {}
                for i, col_name in enumerate(columns):
                    value = row[i]
                    if hasattr(value, "isoformat"):
                        value = value.isoformat()
                    elif isinstance(value, (bytes, bytearray)):
                        value = value.hex()
                    row_dict[col_name] = value
                results.append(row_dict)

            logger.info(f"Queried view {view_name}: {len(results)} rows returned")

            safe_params = {k: str(v) for k, v in bind_params.items()}
            return {
                "success": True,
                "view_name": view_name,
                "columns": columns,
                "rows": results,
                "row_count": len(results),
                "limited": len(results) >= effective_limit,
                "executed_sql": sql,
                "parameters": safe_params,
            }

        except (ValidationError, DatabaseError, TimeoutError):
            raise
        except oracledb.Error as e:
            error_obj, = e.args
            log_error_with_context(e, {
                "view_name": view_name,
                "error_code": error_obj.code if hasattr(error_obj, "code") else None,
            })
            raise DatabaseError(
                f"Database error: {error_obj.message if hasattr(error_obj, 'message') else str(e)}",
                details={"view_name": view_name},
            )
        except Exception as e:
            log_error_with_context(e, {"view_name": view_name})
            raise DatabaseError(f"Unexpected error: {str(e)}")
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Return MCP tool definitions for the LLM.

        query_view no longer accepts a free-form where_clause parameter.
        Filters must be provided as a structured list of {column, operator,
        value} objects.
        """
        return [
            {
                "name": "query_view",
                "description": (
                    "Execute a safe SELECT query on a whitelisted Oracle APEX view. "
                    "Filters must be structured objects — free-form SQL is not accepted. "
                    "Supported operators: =, <, >, <=, >=, BETWEEN (value is a 2-element list), "
                    "IN (value is a list).  Call describe_view first to confirm column names."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "view_name": {
                            "type": "string",
                            "description": "Name of the allow-listed view to query",
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
                                        "enum": ["=", "<", ">", "<=", ">=", "BETWEEN", "IN"],
                                    },
                                    "value": {
                                        "description": (
                                            "Scalar for =/</>/<=/>=; "
                                            "list of 2 for BETWEEN; "
                                            "non-empty list for IN"
                                        )
                                    },
                                },
                                "required": ["column", "operator", "value"],
                            },
                        },
                        "limit": {
                            "type": "integer",
                            "description": f"Maximum number of rows to return (server cap: {self.max_result_size})",
                        },
                    },
                    "required": ["view_name"],
                },
            },
            {
                "name": "list_views",
                "description": "List all available Oracle APEX views that can be queried",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "describe_view",
                "description": (
                    "Get column names and types for a specific Oracle APEX view. "
                    "Call this once per view per conversation before querying it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "view_name": {
                            "type": "string",
                            "description": "Name of the view to describe",
                        }
                    },
                    "required": ["view_name"],
                },
            },
        ]

    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch an MCP tool call by name.

        Args:
            tool_name:  One of query_view | list_views | describe_view.
            parameters: Tool parameters dict.

        Returns:
            Tool result dict.
        """
        if tool_name == "query_view":
            return self.query_view(
                view_name=parameters.get("view_name"),
                filters=parameters.get("filters"),
                limit=parameters.get("limit"),
            )
        elif tool_name == "list_views":
            return self.list_views()
        elif tool_name == "describe_view":
            return self.describe_view(view_name=parameters.get("view_name"))
        else:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}",
            }
