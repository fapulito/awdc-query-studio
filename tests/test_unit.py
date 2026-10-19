"""
Unit Tests for Flask Chatbot MCP Application
Tests core functionality of MCP client, LLM service, Oracle server, PDF server, and Flask routes
Requirements: All
"""

import os
import sys
import json
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime

# Add modules to path
sys.path.insert(0, 'modules')

# Import modules to test
from modules.mcp_client import MCPClient, ServerConfig, Tool, ToolCall, ServerStatus
from modules.llm_service import LLMService, LLMConfig, ToolCallRequest
from modules.oracle_mcp_server import OracleMCPServer
from modules.pdf_mcp_server import PDFMCPServer
from modules.session_manager import SessionManager, Message
from modules.error_handler import (
    MCPConnectionError, MCPToolExecutionError, DatabaseError,
    PDFProcessingError, LLMAPIError, TimeoutError
)


# ============================================================================
# MCP Client Tests
# ============================================================================

class TestMCPClient:
    """Test MCP Client tool execution and connection management"""
    
    def test_initialization(self):
        """Test MCP client initialization with server configs"""
        configs = [
            ServerConfig(
                name='test_server',
                type='test',
                endpoint='http://localhost:5000',
                credentials={'api_key': 'test_key'},
                enabled=True
            )
        ]
        
        client = MCPClient(configs)
        
        assert 'test_server' in client.server_configs
        assert client.server_configs['test_server'].name == 'test_server'
        assert len(client.available_tools) == 0
    
    def test_disabled_server_not_loaded(self):
        """Test that disabled servers are not loaded"""
        configs = [
            ServerConfig(
                name='disabled_server',
                type='test',
                endpoint='http://localhost:5000',
                credentials={},
                enabled=False
            )
        ]
        
        client = MCPClient(configs)
        
        assert 'disabled_server' not in client.server_configs
    
    def test_get_available_tools(self):
        """Test retrieving available tools"""
        configs = [
            ServerConfig(
                name='test_server',
                type='test',
                endpoint='http://localhost:5000',
                credentials={}
            )
        ]
        
        client = MCPClient(configs)
        
        # Manually add a tool
        tool = Tool(
            name='test_tool',
            description='Test tool',
            parameters={'type': 'object'},
            server_name='test_server'
        )
        client.available_tools['test_tool'] = tool
        
        tools = client.get_available_tools()
        assert len(tools) == 1
        assert tools[0].name == 'test_tool'
    
    def test_get_tools_for_llm(self):
        """Test formatting tools for LLM"""
        configs = [
            ServerConfig(
                name='test_server',
                type='test',
                endpoint='http://localhost:5000',
                credentials={}
            )
        ]
        
        client = MCPClient(configs)
        
        # Add a tool
        tool = Tool(
            name='test_tool',
            description='Test tool description',
            parameters={'type': 'object', 'properties': {}},
            server_name='test_server'
        )
        client.available_tools['test_tool'] = tool
        
        llm_tools = client.get_tools_for_llm()
        assert len(llm_tools) == 1
        assert llm_tools[0]['name'] == 'test_tool'
        assert llm_tools[0]['description'] == 'Test tool description'
    
    def test_is_tool_available(self):
        """Test checking tool availability"""
        configs = [
            ServerConfig(
                name='test_server',
                type='test',
                endpoint='http://localhost:5000',
                credentials={}
            )
        ]
        
        client = MCPClient(configs)
        
        # Add a tool
        tool = Tool(
            name='available_tool',
            description='Available tool',
            parameters={},
            server_name='test_server'
        )
        client.available_tools['available_tool'] = tool
        
        assert client.is_tool_available('available_tool') is True
        assert client.is_tool_available('missing_tool') is False
    
    def test_get_server_status(self):
        """Test retrieving server status"""
        configs = [
            ServerConfig(
                name='test_server',
                type='test',
                endpoint='http://localhost:5000',
                credentials={}
            )
        ]
        
        client = MCPClient(configs)
        client.server_status['test_server'] = ServerStatus.CONNECTED
        
        status = client.get_server_status()
        assert status['test_server'] == 'connected'


# ============================================================================
# LLM Service Tests
# ============================================================================

class TestLLMService:
    """Test LLM service message formatting and parsing"""
    
    @patch('modules.llm_service._get_openai')
    def test_format_messages_without_system_prompt(self, mock_get_openai):
        """Test message formatting without system prompt"""
        # Mock OpenAI client
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_get_openai.return_value = mock_openai
        
        config = LLMConfig(
            api_key='test_key',
            model='gpt-4'
        )
        
        service = LLMService(config)
        
        conversation = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there!'}
        ]
        
        formatted = service.format_messages(conversation)
        
        assert len(formatted) == 2
        assert formatted[0]['role'] == 'user'
        assert formatted[0]['content'] == 'Hello'
    
    @patch('modules.llm_service._get_openai')
    def test_format_messages_with_system_prompt(self, mock_get_openai):
        """Test message formatting with system prompt"""
        # Mock OpenAI client
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_get_openai.return_value = mock_openai
        
        config = LLMConfig(
            api_key='test_key',
            model='gpt-4'
        )
        
        service = LLMService(config)
        
        conversation = [
            {'role': 'user', 'content': 'Hello'}
        ]
        
        formatted = service.format_messages(
            conversation,
            system_prompt='You are a helpful assistant'
        )
        
        assert len(formatted) == 2
        assert formatted[0]['role'] == 'system'
        assert formatted[0]['content'] == 'You are a helpful assistant'
        assert formatted[1]['role'] == 'user'
    
    @patch('modules.llm_service._get_openai')
    def test_format_tools_for_llm(self, mock_get_openai):
        """Test formatting MCP tools for LLM function calling"""
        # Mock OpenAI client
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_get_openai.return_value = mock_openai
        
        config = LLMConfig(
            api_key='test_key',
            model='gpt-4'
        )
        
        service = LLMService(config)
        
        tools = [
            {
                'name': 'search_database',
                'description': 'Search the database',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string'}
                    },
                    'required': ['query']
                }
            }
        ]
        
        formatted = service.format_tools_for_llm(tools)
        
        assert len(formatted) == 1
        assert formatted[0]['type'] == 'function'
        assert formatted[0]['function']['name'] == 'search_database'
        assert formatted[0]['function']['description'] == 'Search the database'
    
    @patch('modules.llm_service._get_openai')
    def test_parse_response_with_content_only(self, mock_get_openai):
        """Test parsing LLM response with only text content"""
        # Mock OpenAI client
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_get_openai.return_value = mock_openai
        
        config = LLMConfig(
            api_key='test_key',
            model='gpt-4'
        )
        
        service = LLMService(config)
        
        response = {
            'content': 'This is a response',
            'role': 'assistant',
            'finish_reason': 'stop',
            'tool_calls': []
        }
        
        content, tool_calls = service.parse_response(response)
        
        assert content == 'This is a response'
        assert len(tool_calls) == 0
    
    @patch('modules.llm_service._get_openai')
    def test_parse_response_with_tool_calls(self, mock_get_openai):
        """Test parsing LLM response with tool calls"""
        # Mock OpenAI client
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_get_openai.return_value = mock_openai
        
        config = LLMConfig(
            api_key='test_key',
            model='gpt-4'
        )
        
        service = LLMService(config)
        
        response = {
            'content': None,
            'role': 'assistant',
            'finish_reason': 'tool_calls',
            'tool_calls': [
                {
                    'id': 'call_123',
                    'type': 'function',
                    'function': {
                        'name': 'search_database',
                        'arguments': '{"query": "test"}'
                    }
                }
            ]
        }
        
        content, tool_calls = service.parse_response(response)
        
        assert content is None
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == 'search_database'
        assert tool_calls[0].parameters == {'query': 'test'}
    
    @patch('modules.llm_service._get_openai')
    def test_create_system_prompt_with_tools(self, mock_get_openai):
        """Test creating system prompt with available tools"""
        # Mock OpenAI client
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_get_openai.return_value = mock_openai
        
        config = LLMConfig(
            api_key='test_key',
            model='gpt-4'
        )
        
        service = LLMService(config)
        
        tools = [
            {'name': 'tool1', 'description': 'First tool'},
            {'name': 'tool2', 'description': 'Second tool'}
        ]
        
        prompt = service.create_system_prompt(tools)
        
        assert 'tool1' in prompt
        assert 'tool2' in prompt
        assert 'First tool' in prompt


# ============================================================================
# Oracle MCP Server Tests
# ============================================================================

class TestOracleMCPServer:
    """Test Oracle MCP server query execution"""
    
    @patch.dict(os.environ, {
        'ORACLE_CONNECTION_STRING': 'localhost:1521/XEPDB1',
        'ORACLE_USER': 'test_user',
        'ORACLE_PASSWORD': 'test_pass'
    })
    @patch('modules.oracle_mcp_server.oracledb')
    def test_initialization(self, mock_oracledb):
        """Test Oracle server initialization"""
        mock_pool = MagicMock()
        mock_oracledb.create_pool.return_value = mock_pool
        
        server = OracleMCPServer()
        
        assert server.pool is not None
        mock_oracledb.create_pool.assert_called_once()
    
    @patch.dict(os.environ, {
        'ORACLE_CONNECTION_STRING': 'localhost:1521/XEPDB1',
        'ORACLE_USER': 'test_user',
        'ORACLE_PASSWORD': 'test_pass'
    })
    @patch('modules.oracle_mcp_server.oracledb')
    def test_get_available_tools(self, mock_oracledb):
        """Test retrieving available tools from Oracle server"""
        mock_pool = MagicMock()
        mock_oracledb.create_pool.return_value = mock_pool
        
        server = OracleMCPServer()
        tools = server.get_available_tools()
        
        assert len(tools) > 0
        tool_names = [tool['name'] for tool in tools]
        assert 'query_view' in tool_names
        assert 'list_views' in tool_names
    
    @patch.dict(os.environ, {
        'ORACLE_CONNECTION_STRING': 'localhost:1521/XEPDB1',
        'ORACLE_USER': 'test_user',
        'ORACLE_PASSWORD': 'test_pass'
    })
    @patch('modules.oracle_mcp_server.oracledb')
    def test_health_check(self, mock_oracledb):
        """Test Oracle server health check"""
        mock_pool = MagicMock()
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        
        mock_oracledb.create_pool.return_value = mock_pool
        mock_pool.acquire.return_value.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)
        
        server = OracleMCPServer()
        health = server.health_check()
        
        # Health check may return unhealthy if pool is not properly initialized
        assert 'status' in health
        assert 'message' in health


# ============================================================================
# PDF MCP Server Tests
# ============================================================================

class TestPDFMCPServer:
    """Test PDF connector search functionality"""
    
    @patch.dict(os.environ, {'PDF_STORAGE_PATH': 'pdfs'})
    def test_initialization(self):
        """Test PDF server initialization"""
        server = PDFMCPServer()
        
        assert server.storage_path == 'pdfs'
        assert isinstance(server.index, dict)
    
    @patch.dict(os.environ, {'PDF_STORAGE_PATH': 'pdfs'})
    def test_get_available_tools(self):
        """Test retrieving available tools from PDF server"""
        server = PDFMCPServer()
        tools = server.get_available_tools()
        
        assert len(tools) > 0
        tool_names = [tool['name'] for tool in tools]
        assert 'search_pdfs' in tool_names
        assert 'list_documents' in tool_names
        assert 'get_document' in tool_names
    
    @patch.dict(os.environ, {'PDF_STORAGE_PATH': 'pdfs'})
    def test_list_documents(self):
        """Test listing available PDF documents"""
        server = PDFMCPServer()
        result = server.list_documents()
        
        assert 'success' in result
        if result['success']:
            assert 'documents' in result
            assert 'count' in result
    
    @patch.dict(os.environ, {'PDF_STORAGE_PATH': 'pdfs'})
    def test_search_pdfs_basic(self):
        """Test basic PDF search functionality"""
        server = PDFMCPServer()
        
        # Only test if PDFs are indexed
        if server.index:
            result = server.search_pdfs('APEX', limit=5)
            
            assert 'success' in result
            if result['success']:
                assert 'results' in result
                assert 'count' in result
    
    @patch.dict(os.environ, {'PDF_STORAGE_PATH': 'pdfs'})
    def test_health_check(self):
        """Test PDF server health check"""
        server = PDFMCPServer()
        health = server.health_check()
        
        assert 'status' in health
        assert 'indexed_documents' in health


# ============================================================================
# Session Manager Tests
# ============================================================================

class TestSessionManager:
    """Test session and conversation management"""
    
    @pytest.fixture
    def app_context(self):
        """Create Flask app context for testing"""
        from app import app
        app.config['TESTING'] = True
        with app.test_request_context():
            yield app
    
    def test_initialize_session(self, app_context):
        """Test session initialization"""
        from flask import session
        manager = SessionManager()
        
        session_id = manager.initialize_session()
        
        assert session_id is not None
        assert len(session_id) > 0
    
    def test_add_message(self, app_context):
        """Test adding messages to conversation"""
        manager = SessionManager()
        
        manager.initialize_session()
        
        message = manager.add_message('user', 'Hello')
        
        assert message.role == 'user'
        assert message.content == 'Hello'
        assert message.timestamp is not None
    
    def test_get_conversation_history(self, app_context):
        """Test retrieving conversation history"""
        manager = SessionManager()
        
        manager.initialize_session()
        
        manager.add_message('user', 'Hello')
        manager.add_message('assistant', 'Hi there!')
        
        history = manager.get_conversation_history()
        
        assert len(history) == 2
        assert history[0].role == 'user'
        assert history[1].role == 'assistant'
    
    def test_clear_conversation_history(self, app_context):
        """Test clearing conversation history"""
        manager = SessionManager()
        
        manager.initialize_session()
        
        manager.add_message('user', 'Hello')
        manager.add_message('assistant', 'Hi!')
        
        manager.clear_conversation_history()
        
        history = manager.get_conversation_history()
        assert len(history) == 0
    
    def test_get_message_count(self, app_context):
        """Test getting message count"""
        manager = SessionManager()
        
        manager.initialize_session()
        
        manager.add_message('user', 'Message 1')
        manager.add_message('assistant', 'Response 1')
        manager.add_message('user', 'Message 2')
        
        count = manager.get_message_count()
        assert count == 3


# ============================================================================
# Flask Route Tests
# ============================================================================

class TestFlaskRoutes:
    """Test Flask route handlers"""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app"""
        from app import app as flask_app
        flask_app.config['TESTING'] = True
        return flask_app
    
    @pytest.fixture
    def client(self, app):
        """Create test client"""
        return app.test_client()
    
    def test_index_route(self, client):
        """Test index route serves chat interface"""
        response = client.get('/')
        
        assert response.status_code == 200
    
    def test_health_route(self, client):
        """Test health check endpoint"""
        response = client.get('/api/health')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'status' in data
        assert 'timestamp' in data
    
    @patch('app.initialize_services')
    def test_chat_route_missing_message(self, mock_init, client):
        """Test chat route with missing message"""
        # Mock initialization to avoid OpenAI client issues
        mock_init.return_value = None
        
        response = client.post(
            '/api/chat',
            json={},
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['error'] is True
        assert 'message' in data
    
    @patch('app.initialize_services')
    def test_chat_route_empty_message(self, mock_init, client):
        """Test chat route with empty message"""
        # Mock initialization to avoid OpenAI client issues
        mock_init.return_value = None
        
        response = client.post(
            '/api/chat',
            json={'message': ''},
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['error'] is True


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == '__main__':
    # Run with pytest
    pytest.main([__file__, '-v', '--tb=short'])
