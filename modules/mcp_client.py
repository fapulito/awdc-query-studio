"""
MCP Client Module
Handles connection to MCP servers, tool discovery, and execution
Requirements: 3.1, 3.2, 3.3, 3.4
"""

import os
import logging
import time
import requests
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from modules.error_handler import (
    MCPConnectionError, MCPToolExecutionError, TimeoutError,
    handle_mcp_errors, log_error_with_context, ErrorRecoveryStrategy
)

logger = logging.getLogger(__name__)


class ServerStatus(Enum):
    """MCP Server connection status"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    CONNECTING = "connecting"


@dataclass
class ServerConfig:
    """Configuration for an MCP server"""
    name: str
    type: str  # 'oracle', 'pdf', etc.
    endpoint: str
    credentials: Dict[str, str]
    enabled: bool = True
    timeout: int = 10
    max_retries: int = 3
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class Tool:
    """Represents an MCP tool"""
    name: str
    description: str
    parameters: Dict[str, Any]
    server_name: str
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for LLM"""
        return {
            'name': self.name,
            'description': self.description,
            'parameters': self.parameters
        }


@dataclass
class ToolCall:
    """Represents a tool call request"""
    tool_name: str
    parameters: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)


class MCPClient:
    """
    MCP Client for managing connections to MCP servers and executing tools
    Implements connection pooling, retry logic, and graceful degradation
    """
    
    def __init__(self, server_configs: List[ServerConfig]):
        """
        Initialize MCP client with server configurations
        
        Args:
            server_configs: List of ServerConfig objects
        """
        self.server_configs = {config.name: config for config in server_configs if config.enabled}
        self.server_status: Dict[str, ServerStatus] = {}
        self.available_tools: Dict[str, Tool] = {}
        self.sessions: Dict[str, requests.Session] = {}
        # Maps tool_name -> in-process server object for tools registered via
        # register_in_process_server().  These bypass HTTP entirely.
        self._in_process_servers: Dict[str, Any] = {}
        
        logger.info(f"MCPClient initialized with {len(self.server_configs)} server(s)")
    
    def register_in_process_server(self, server_name: str, server: Any) -> None:
        """
        Register an in-process MCP server so its tools are available without
        an HTTP connection.  The server must implement:
            get_available_tools() -> List[Dict[str, Any]]
            execute_tool(tool_name: str, parameters: Dict[str, Any]) -> Dict

        Args:
            server_name: Logical name used in status reporting
            server:      In-process server instance
        """
        tools = server.get_available_tools()
        for tool_data in tools:
            tool = Tool(
                name=tool_data['name'],
                description=tool_data.get('description', ''),
                parameters=tool_data.get('parameters', {}),
                server_name=server_name,
            )
            self.available_tools[tool.name] = tool
            self._in_process_servers[tool.name] = server
        self.server_status[server_name] = ServerStatus.CONNECTED
        logger.info(
            f"Registered in-process server '{server_name}' with "
            f"{len(tools)} tool(s): {[t['name'] for t in tools]}"
        )

    def connect_servers(self) -> Dict[str, bool]:
        """
        Connect to all configured MCP servers
        
        Returns:
            Dictionary mapping server names to connection success status
        """
        connection_results = {}
        
        for server_name, config in self.server_configs.items():
            logger.info(f"Connecting to MCP server: {server_name}")
            self.server_status[server_name] = ServerStatus.CONNECTING
            
            try:
                success = self._connect_server(config)
                connection_results[server_name] = success
                
                if success:
                    self.server_status[server_name] = ServerStatus.CONNECTED
                    logger.info(f"Successfully connected to {server_name}")
                else:
                    self.server_status[server_name] = ServerStatus.ERROR
                    logger.warning(f"Failed to connect to {server_name}")
                    
            except Exception as e:
                logger.error(f"Error connecting to {server_name}: {str(e)}")
                self.server_status[server_name] = ServerStatus.ERROR
                connection_results[server_name] = False
        
        return connection_results
    
    def _connect_server(self, config: ServerConfig) -> bool:
        """
        Connect to a single MCP server with retry logic
        
        Args:
            config: Server configuration
            
        Returns:
            True if connection successful, False otherwise
            
        Raises:
            MCPConnectionError: If connection fails after all retries
        """
        session = requests.Session()
        session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'MCP-Client/1.0'
        })
        
        # Add authentication if provided
        if 'api_key' in config.credentials:
            session.headers.update({
                'Authorization': f"Bearer {config.credentials['api_key']}"
            })
        
        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(config.max_retries):
            try:
                # Test connection with health check
                response = session.get(
                    f"{config.endpoint}/health",
                    timeout=config.timeout
                )
                
                if response.status_code == 200:
                    self.sessions[config.name] = session
                    
                    # Discover tools from this server
                    self._discover_tools(config)
                    return True
                    
                logger.warning(
                    f"Health check failed for {config.name}: "
                    f"status {response.status_code}, attempt {attempt + 1}/{config.max_retries}"
                )
                last_error = f"HTTP {response.status_code}"
                
            except requests.exceptions.Timeout as e:
                last_error = f"Connection timeout: {str(e)}"
                logger.warning(
                    f"Connection timeout (attempt {attempt + 1}/{config.max_retries}) "
                    f"for {config.name}: {str(e)}"
                )
                
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection refused: {str(e)}"
                logger.warning(
                    f"Connection refused (attempt {attempt + 1}/{config.max_retries}) "
                    f"for {config.name}: {str(e)}"
                )
                
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                logger.warning(
                    f"Connection attempt {attempt + 1}/{config.max_retries} "
                    f"failed for {config.name}: {str(e)}"
                )
            
            # Exponential backoff
            if attempt < config.max_retries - 1:
                backoff_time = 2 ** attempt
                logger.debug(f"Waiting {backoff_time}s before retry")
                time.sleep(backoff_time)
        
        # All retries failed - log but don't raise to allow graceful degradation
        log_error_with_context(
            MCPConnectionError(config.name, last_error or "Unknown error"),
            {"endpoint": config.endpoint, "retries": config.max_retries}
        )
        return False
    
    def _discover_tools(self, config: ServerConfig) -> None:
        """
        Discover available tools from an MCP server
        
        Args:
            config: Server configuration
        """
        try:
            session = self.sessions.get(config.name)
            if not session:
                logger.error(f"No session found for {config.name}")
                return
            
            response = session.get(
                f"{config.endpoint}/tools",
                timeout=config.timeout
            )
            
            if response.status_code == 200:
                tools_data = response.json()
                
                if 'tools' in tools_data:
                    for tool_data in tools_data['tools']:
                        tool = Tool(
                            name=tool_data['name'],
                            description=tool_data.get('description', ''),
                            parameters=tool_data.get('parameters', {}),
                            server_name=config.name
                        )
                        self.available_tools[tool.name] = tool
                        logger.debug(f"Discovered tool: {tool.name} from {config.name}")
                    
                    logger.info(
                        f"Discovered {len(tools_data['tools'])} tool(s) "
                        f"from {config.name}"
                    )
            else:
                logger.warning(
                    f"Failed to discover tools from {config.name}: "
                    f"status {response.status_code}"
                )
                
        except Exception as e:
            logger.error(f"Error discovering tools from {config.name}: {str(e)}")
    
    def get_available_tools(self) -> List[Tool]:
        """
        Get list of all available tools from connected servers
        
        Returns:
            List of Tool objects
        """
        return list(self.available_tools.values())
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """
        Get tools formatted for LLM function calling
        
        Returns:
            List of tool definitions in LLM-compatible format
        """
        return [tool.to_dict() for tool in self.available_tools.values()]
    
    def get_server_status(self) -> Dict[str, str]:
        """
        Get connection status for all servers
        
        Returns:
            Dictionary mapping server names to status strings
        """
        return {
            name: status.value 
            for name, status in self.server_status.items()
        }
    
    def is_tool_available(self, tool_name: str) -> bool:
        """
        Check if a specific tool is available
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            True if tool is available, False otherwise
        """
        return tool_name in self.available_tools
    
    def disconnect(self) -> None:
        """
        Disconnect from all MCP servers and cleanup resources
        """
        logger.info("Disconnecting from all MCP servers")
        
        for server_name, session in self.sessions.items():
            try:
                session.close()
                self.server_status[server_name] = ServerStatus.DISCONNECTED
                logger.debug(f"Closed session for {server_name}")
            except Exception as e:
                logger.error(f"Error closing session for {server_name}: {str(e)}")
        
        self.sessions.clear()
        self.available_tools.clear()
        logger.info("All MCP server connections closed")
    
    def reconnect_server(self, server_name: str) -> bool:
        """
        Attempt to reconnect to a specific server
        
        Args:
            server_name: Name of the server to reconnect
            
        Returns:
            True if reconnection successful, False otherwise
        """
        if server_name not in self.server_configs:
            logger.error(f"Unknown server: {server_name}")
            return False
        
        config = self.server_configs[server_name]
        logger.info(f"Attempting to reconnect to {server_name}")
        
        # Close existing session if any
        if server_name in self.sessions:
            try:
                self.sessions[server_name].close()
            except Exception as e:
                logger.warning(f"Error closing old session: {str(e)}")
            del self.sessions[server_name]
        
        # Remove old tools from this server
        tools_to_remove = [
            tool_name for tool_name, tool in self.available_tools.items()
            if tool.server_name == server_name
        ]
        for tool_name in tools_to_remove:
            del self.available_tools[tool_name]
        
        # Attempt reconnection
        return self._connect_server(config)
    
    def execute_tool(
        self, 
        tool_name: str, 
        parameters: Dict[str, Any],
        timeout: Optional[int] = None
    ) -> ToolCall:
        """
        Execute a tool on the appropriate MCP server with comprehensive error handling
        
        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters
            timeout: Optional timeout override in seconds
            
        Returns:
            ToolCall object with result or error
        """
        tool_call = ToolCall(tool_name=tool_name, parameters=parameters)
        
        try:
            # Check if tool exists
            if tool_name not in self.available_tools:
                raise MCPToolExecutionError(
                    tool_name,
                    "Tool not found in available tools",
                    {"available_tools": list(self.available_tools.keys())}
                )
            
            tool = self.available_tools[tool_name]
            server_name = tool.server_name

            # --- In-process fast path: bypass HTTP for locally registered servers ---
            if tool_name in self._in_process_servers:
                in_proc_server = self._in_process_servers[tool_name]
                result = in_proc_server.execute_tool(tool_name, parameters)
                tool_call.result = result
                logger.info(f"Executed in-process tool '{tool_name}' on '{server_name}'")
                return tool_call
            # --- End in-process fast path ---
            
            # Check if server is connected (HTTP servers only)
            if server_name not in self.sessions:
                logger.warning(f"Server '{server_name}' not connected, attempting reconnection")
                
                # Attempt to reconnect
                if self.reconnect_server(server_name):
                    logger.info(f"Reconnection to {server_name} successful")
                else:
                    raise MCPConnectionError(
                        server_name,
                        "Server not connected and reconnection failed"
                    )
            
            # Get server configuration for timeout
            config = self.server_configs[server_name]
            execution_timeout = timeout or config.timeout
            
            # Execute tool with retry logic using ErrorRecoveryStrategy
            def execute_attempt():
                return self._execute_tool_request(
                    server_name=server_name,
                    tool_name=tool_name,
                    parameters=parameters,
                    timeout=execution_timeout
                )
            
            try:
                result = ErrorRecoveryStrategy.retry_with_backoff(
                    execute_attempt,
                    max_retries=2,
                    initial_delay=1.0,
                    backoff_factor=2.0,
                    exceptions=(requests.exceptions.RequestException,)
                )
                
                tool_call.result = result
                logger.info(f"Successfully executed tool '{tool_name}' on {server_name}")
                return tool_call
                
            except requests.exceptions.Timeout as e:
                raise TimeoutError("tool_execution", execution_timeout, {
                    "tool_name": tool_name,
                    "server_name": server_name
                })
                
            except requests.exceptions.RequestException as e:
                raise MCPToolExecutionError(
                    tool_name,
                    f"Request failed: {str(e)}",
                    {"server_name": server_name}
                )
        
        except (MCPToolExecutionError, MCPConnectionError, TimeoutError) as e:
            tool_call.error = e.message
            log_error_with_context(e, {
                "tool_name": tool_name,
                "parameters": parameters,
                "timeout": timeout
            })
            
        except Exception as e:
            error_msg = f"Unexpected error executing tool: {str(e)}"
            tool_call.error = error_msg
            log_error_with_context(e, {
                "tool_name": tool_name,
                "parameters": parameters
            })
        
        return tool_call
    
    def _execute_tool_request(
        self,
        server_name: str,
        tool_name: str,
        parameters: Dict[str, Any],
        timeout: int
    ) -> Dict[str, Any]:
        """
        Execute tool request to MCP server
        
        Args:
            server_name: Name of the server
            tool_name: Name of the tool
            parameters: Tool parameters
            timeout: Request timeout in seconds
            
        Returns:
            Tool execution result
            
        Raises:
            requests.exceptions.RequestException: On request failure
        """
        session = self.sessions[server_name]
        config = self.server_configs[server_name]
        
        # Format request according to MCP protocol
        request_data = {
            'tool': tool_name,
            'parameters': parameters
        }
        
        logger.debug(f"Executing tool '{tool_name}' on {server_name} with params: {parameters}")
        
        response = session.post(
            f"{config.endpoint}/execute",
            json=request_data,
            timeout=timeout
        )
        
        # Handle response
        if response.status_code == 200:
            result = response.json()
            
            # Check for error in response
            if result.get('error'):
                raise Exception(result.get('message', 'Unknown error from server'))
            
            return result
            
        elif response.status_code == 404:
            raise Exception(f"Tool '{tool_name}' not found on server")
            
        elif response.status_code == 400:
            error_data = response.json()
            raise Exception(f"Invalid parameters: {error_data.get('message', 'Unknown error')}")
            
        elif response.status_code >= 500:
            raise Exception(f"Server error: {response.status_code}")
            
        else:
            raise Exception(f"Unexpected response status: {response.status_code}")
    
    def execute_tools_batch(
        self,
        tool_calls: List[Tuple[str, Dict[str, Any]]],
        timeout: Optional[int] = None
    ) -> List[ToolCall]:
        """
        Execute multiple tools in sequence
        
        Args:
            tool_calls: List of (tool_name, parameters) tuples
            timeout: Optional timeout override for each tool
            
        Returns:
            List of ToolCall objects with results or errors
        """
        results = []
        
        for tool_name, parameters in tool_calls:
            result = self.execute_tool(tool_name, parameters, timeout)
            results.append(result)
            
            # If a critical tool fails, log but continue with others
            if result.error:
                logger.warning(
                    f"Tool '{tool_name}' failed in batch execution: {result.error}"
                )
        
        return results
    
    def get_tool_info(self, tool_name: str) -> Optional[Tool]:
        """
        Get information about a specific tool
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool object or None if not found
        """
        return self.available_tools.get(tool_name)


def create_mcp_client_from_env() -> MCPClient:
    """
    Create MCP client from environment variables
    
    Returns:
        Configured MCPClient instance
    """
    server_configs = []
    
    # Oracle MCP Server configuration
    if os.getenv('ORACLE_CONNECTION_STRING'):
        oracle_config = ServerConfig(
            name='oracle',
            type='oracle',
            endpoint=os.getenv('MCP_ORACLE_ENDPOINT', 'http://localhost:5001'),
            credentials={
                'connection_string': os.getenv('ORACLE_CONNECTION_STRING', ''),
                'user': os.getenv('ORACLE_USER', ''),
                'password': os.getenv('ORACLE_PASSWORD', '')
            },
            enabled=True,
            timeout=int(os.getenv('QUERY_TIMEOUT', 10)),
            max_retries=3
        )
        server_configs.append(oracle_config)
        logger.info("Oracle MCP server configuration loaded")
    
    # PDF MCP Server configuration
    if os.getenv('PDF_STORAGE_PATH'):
        pdf_config = ServerConfig(
            name='pdf',
            type='pdf',
            endpoint=os.getenv('MCP_PDF_ENDPOINT', 'http://localhost:5002'),
            credentials={
                'storage_path': os.getenv('PDF_STORAGE_PATH', '')
            },
            enabled=True,
            timeout=int(os.getenv('QUERY_TIMEOUT', 10)),
            max_retries=3
        )
        server_configs.append(pdf_config)
        logger.info("PDF MCP server configuration loaded")

    # YugabyteDB MCP Server configuration
    if os.getenv('YUGABYTE_HOST'):
        yugabyte_config = ServerConfig(
            name='yugabyte',
            type='yugabyte',
            endpoint=os.getenv('MCP_YUGABYTE_ENDPOINT', 'http://localhost:5003'),
            credentials={
                'host': os.getenv('YUGABYTE_HOST', ''),
                'user': os.getenv('YUGABYTE_USER', ''),
                'password': os.getenv('YUGABYTE_PASSWORD', '')
            },
            enabled=True,
            timeout=int(os.getenv('QUERY_TIMEOUT', 10)),
            max_retries=3
        )
        server_configs.append(yugabyte_config)
        logger.info("YugabyteDB MCP server configuration loaded")

    if not server_configs:
        logger.warning("No MCP servers configured")
    
    return MCPClient(server_configs)
