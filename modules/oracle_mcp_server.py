"""
Oracle APEX MCP Server Module

This module provides MCP server functionality for Oracle database access.
It implements connection pooling, secure credential management, and exposes
database views as MCP tools.
"""

import os
import logging
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
import oracledb
from modules.error_handler import (
    DatabaseError, ValidationError, TimeoutError,
    handle_database_errors, log_error_with_context
)
from modules.serverless_optimizer import get_connection_cache, optimize_cold_start

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
    
    @handle_database_errors
    def query_view(self, view_name: str, where_clause: Optional[str] = None, 
                   limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute a SELECT query on a whitelisted view with comprehensive error handling.
        
        Args:
            view_name: Name of the view to query
            where_clause: Optional WHERE clause (without the WHERE keyword)
            limit: Optional limit on number of rows returned
            
        Returns:
            Dictionary containing query results and metadata
            
        Raises:
            DatabaseError: On query execution failure
            ValidationError: On invalid input
        """
        try:
            # Sanitize and validate view name
            try:
                view_name = self._sanitize_view_name(view_name)
            except ValueError as e:
                raise ValidationError("view_name", str(e))
            
            if not self._is_view_allowed(view_name):
                raise ValidationError(
                    "view_name",
                    f"View '{view_name}' is not in the allowed list",
                    {"allowed_views": self.allowed_views}
                )
            
            # Apply result size limit
            if limit is None:
                limit = self.max_result_size
            else:
                limit = min(limit, self.max_result_size)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                try:
                    # Build query with parameterization
                    query = f"SELECT * FROM {view_name}"
                    
                    if where_clause:
                        # Basic validation of WHERE clause
                        dangerous_keywords = ['DROP', 'DELETE', 'INSERT', 'UPDATE', 'TRUNCATE', 
                                             'ALTER', 'CREATE', 'GRANT', 'REVOKE']
                        where_upper = where_clause.upper()
                        if any(keyword in where_upper for keyword in dangerous_keywords):
                            raise ValidationError(
                                "where_clause",
                                "WHERE clause contains forbidden SQL keywords",
                                {"forbidden_keywords": dangerous_keywords}
                            )
                        query += f" WHERE {where_clause}"
                    
                    # Add row limit
                    query = f"SELECT * FROM ({query}) WHERE ROWNUM <= :limit"
                    
                    # Execute query with timeout
                    try:
                        cursor.execute(query, {"limit": limit})
                    except oracledb.DatabaseError as e:
                        error_obj, = e.args
                        if error_obj.code == 1013:  # ORA-01013: user requested cancel of current operation
                            raise TimeoutError("database_query", self.query_timeout, {
                                "view_name": view_name,
                                "query": query
                            })
                        else:
                            raise DatabaseError(
                                f"Query execution failed: {error_obj.message}",
                                query=query,
                                details={"error_code": error_obj.code}
                            )
                    
                    # Fetch results
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    
                    # Format results
                    results = []
                    for row in rows:
                        row_dict = {}
                        for i, col_name in enumerate(columns):
                            value = row[i]
                            # Convert Oracle-specific types to JSON-serializable types
                            if hasattr(value, 'isoformat'):  # datetime objects
                                value = value.isoformat()
                            elif isinstance(value, (bytes, bytearray)):  # binary data
                                value = value.hex()
                            row_dict[col_name] = value
                        results.append(row_dict)
                    
                    logger.info(f"Successfully queried view {view_name}: {len(results)} rows returned")
                    
                    return {
                        "success": True,
                        "view_name": view_name,
                        "columns": columns,
                        "rows": results,
                        "row_count": len(results),
                        "limited": len(results) >= limit
                    }
                    
                finally:
                    cursor.close()
                
        except (ValidationError, DatabaseError, TimeoutError):
            # Re-raise our custom exceptions
            raise
        except oracledb.Error as e:
            error_obj, = e.args
            log_error_with_context(e, {
                "view_name": view_name,
                "where_clause": where_clause,
                "error_code": error_obj.code if hasattr(error_obj, 'code') else None
            })
            raise DatabaseError(
                f"Database error: {error_obj.message if hasattr(error_obj, 'message') else str(e)}",
                details={"view_name": view_name}
            )
        except Exception as e:
            log_error_with_context(e, {
                "view_name": view_name,
                "where_clause": where_clause
            })
            raise DatabaseError(f"Unexpected error: {str(e)}")
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Get MCP tool definitions for this server.
        
        Returns:
            List of tool definitions in MCP format
        """
        return [
            {
                "name": "query_view",
                "description": "Execute a SELECT query on a whitelisted Oracle database view",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "view_name": {
                            "type": "string",
                            "description": "Name of the view to query"
                        },
                        "where_clause": {
                            "type": "string",
                            "description": "Optional WHERE clause (without the WHERE keyword)"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of rows to return"
                        }
                    },
                    "required": ["view_name"]
                }
            },
            {
                "name": "list_views",
                "description": "List all available database views that can be queried",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "describe_view",
                "description": "Get schema information (columns, types) for a specific view",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "view_name": {
                            "type": "string",
                            "description": "Name of the view to describe"
                        }
                    },
                    "required": ["view_name"]
                }
            }
        ]
    
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an MCP tool by name.
        
        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters
            
        Returns:
            Tool execution result
        """
        if tool_name == "query_view":
            return self.query_view(
                view_name=parameters.get("view_name"),
                where_clause=parameters.get("where_clause"),
                limit=parameters.get("limit")
            )
        elif tool_name == "list_views":
            return self.list_views()
        elif tool_name == "describe_view":
            return self.describe_view(view_name=parameters.get("view_name"))
        else:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}"
            }
