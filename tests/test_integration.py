"""
Integration Tests for Flask Chatbot MCP Application
Tests end-to-end message flow and component integration
Requirements: All
"""

import os
import sys
import json
import pytest
from unittest.mock import Mock, MagicMock, patch
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add modules to path
sys.path.insert(0, 'modules')


# ============================================================================
# End-to-End Message Flow Tests
# ============================================================================

class TestEndToEndFlow:
    """Test complete message flow from user input to response"""
    
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
    
    @patch('app.llm_service')
    @patch('app.mcp_client')
    def test_chat_message_flow_without_tools(self, mock_mcp, mock_llm, client):
        """Test basic chat message flow without tool calls"""
        # Mock LLM service
        mock_llm.create_system_prompt.return_value = "You are a helpful assistant"
        mock_llm.process_conversation.return_value = ("Hello! How can I help you?", [])
        
        # Mock MCP client
        mock_mcp.get_tools_for_llm.return_value = []
        
        response = client.post(
            '/api/chat',
            json={'message': 'Hello'},
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'response' in data
        assert 'session_id' in data
    
    @patch('app.llm_service')
    @patch('app.mcp_client')
    def test_chat_message_flow_with_tool_execution(self, mock_mcp, mock_llm, client):
        """Test chat message flow with tool execution"""
        # Mock MCP client with tools
        mock_mcp.get_tools_for_llm.return_value = [
            {
                'name': 'search_pdfs',
                'description': 'Search PDF documents',
                'parameters': {'type': 'object'}
            }
        ]
        
        # Mock tool execution
        mock_tool_result = MagicMock()
        mock_tool_result.result = {'results': ['Document 1', 'Document 2']}
        mock_tool_result.error = None
        mock_mcp.execute_tool.return_value = mock_tool_result
        
        # Mock LLM service
        mock_llm.create_system_prompt.return_value = "You are a helpful assistant"
        mock_llm.process_conversation.return_value = (
            "I found 2 documents for you.",
            [{'tool_name': 'search_pdfs', 'parameters': {'query': 'test'}}]
        )
        
        response = client.post(
            '/api/chat',
            json={'message': 'Search for test documents'},
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'response' in data
        assert data['tool_calls_count'] == 1


# ============================================================================
# PDF Processing Integration Tests
# ============================================================================

class TestPDFIntegration:
    """Test PDF processing with various file formats"""
    
    @pytest.fixture
    def pdf_server(self):
        """Create PDF MCP server instance"""
        from modules.pdf_mcp_server import PDFMCPServer
        return PDFMCPServer()
    
    def test_pdf_indexing(self, pdf_server):
        """Test PDF indexing functionality"""
        # Check if PDFs are indexed
        result = pdf_server.list_documents()
        
        assert 'success' in result
        if result['success']:
            assert 'documents' in result
            assert 'count' in result
    
    def test_pdf_search_integration(self, pdf_server):
        """Test PDF search with actual indexed content"""
        # Only test if PDFs are available
        docs = pdf_server.list_documents()
        if not docs.get('success') or docs.get('count', 0) == 0:
            pytest.skip("No PDFs available for testing")
        
        # Search for common term
        result = pdf_server.search_pdfs('APEX', limit=5)
        
        assert 'success' in result
        if result['success']:
            assert 'results' in result
            assert 'count' in result
    
    def test_pdf_document_retrieval(self, pdf_server):
        """Test retrieving full PDF document"""
        # Get list of documents
        docs = pdf_server.list_documents()
        if not docs.get('success') or docs.get('count', 0) == 0:
            pytest.skip("No PDFs available for testing")
        
        # Get first document
        first_doc = docs['documents'][0]['filename']
        result = pdf_server.get_document(first_doc)
        
        assert 'success' in result
        if result['success']:
            assert 'pages' in result
            assert 'page_count' in result


# ============================================================================
# Error Handling Integration Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling scenarios"""
    
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
    
    @patch('app.llm_service')
    @patch('app.mcp_client')
    def test_llm_api_error_handling(self, mock_mcp, mock_llm, client):
        """Test handling of LLM API errors"""
        from modules.error_handler import LLMAPIError
        
        # Mock LLM service to raise error
        mock_llm.create_system_prompt.return_value = "You are a helpful assistant"
        mock_llm.process_conversation.side_effect = LLMAPIError(
            "API rate limit exceeded",
            model="gpt-4"
        )
        
        # Mock MCP client
        mock_mcp.get_tools_for_llm.return_value = []
        
        response = client.post(
            '/api/chat',
            json={'message': 'Hello'},
            content_type='application/json'
        )
        
        # Should return 200 with error message in response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'response' in data
        assert 'temporarily unavailable' in data['response'].lower()
    
    @patch('app.llm_service')
    @patch('app.mcp_client')
    def test_tool_execution_error_handling(self, mock_mcp, mock_llm, client):
        """Test handling of tool execution errors"""
        # Mock MCP client with tools
        mock_mcp.get_tools_for_llm.return_value = [
            {
                'name': 'query_database',
                'description': 'Query database',
                'parameters': {'type': 'object'}
            }
        ]
        
        # Mock tool execution with error
        mock_tool_result = MagicMock()
        mock_tool_result.result = None
        mock_tool_result.error = "Database connection failed"
        mock_mcp.execute_tool.return_value = mock_tool_result
        
        # Mock LLM service
        mock_llm.create_system_prompt.return_value = "You are a helpful assistant"
        mock_llm.process_conversation.return_value = (
            "I encountered an error accessing the database.",
            [{'tool_name': 'query_database', 'parameters': {}, 'error': 'Database connection failed'}]
        )
        
        response = client.post(
            '/api/chat',
            json={'message': 'Query the database'},
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'response' in data


# ============================================================================
# Session Management Integration Tests
# ============================================================================

class TestSessionIntegration:
    """Test session management across requests"""
    
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
    
    @patch('app.llm_service')
    @patch('app.mcp_client')
    def test_session_persistence(self, mock_mcp, mock_llm, client):
        """Test that session persists across multiple requests"""
        # Mock services
        mock_mcp.get_tools_for_llm.return_value = []
        mock_llm.create_system_prompt.return_value = "You are a helpful assistant"
        mock_llm.process_conversation.return_value = ("Response", [])
        
        # First request
        response1 = client.post(
            '/api/chat',
            json={'message': 'First message'},
            content_type='application/json'
        )
        
        data1 = json.loads(response1.data)
        session_id1 = data1.get('session_id')
        
        # Second request (should use same session)
        response2 = client.post(
            '/api/chat',
            json={'message': 'Second message'},
            content_type='application/json'
        )
        
        data2 = json.loads(response2.data)
        session_id2 = data2.get('session_id')
        
        # Session IDs should match
        assert session_id1 == session_id2
        assert data2['message_count'] == 4  # 2 user + 2 assistant messages
    
    def test_session_history_retrieval(self, client):
        """Test retrieving conversation history"""
        # Get history (may be empty if no active session)
        response = client.get('/api/session/history')
        
        # Should return 404 if no session or 200 with history
        assert response.status_code in [200, 404]
    
    @patch('app.llm_service')
    @patch('app.mcp_client')
    def test_session_clear(self, mock_mcp, mock_llm, client):
        """Test clearing conversation history"""
        # Mock services
        mock_mcp.get_tools_for_llm.return_value = []
        mock_llm.create_system_prompt.return_value = "You are a helpful assistant"
        mock_llm.process_conversation.return_value = ("Response", [])
        
        # Create a session with a message
        client.post(
            '/api/chat',
            json={'message': 'Test message'},
            content_type='application/json'
        )
        
        # Clear history
        response = client.post('/api/session/clear')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data.get('success') is True


# ============================================================================
# Health Check Integration Tests
# ============================================================================

class TestHealthCheck:
    """Test health check endpoint"""
    
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
    
    def test_health_endpoint(self, client):
        """Test health check returns proper status"""
        response = client.get('/api/health')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'status' in data
        assert 'timestamp' in data
        assert 'configuration' in data
        assert 'services' in data


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == '__main__':
    # Run with pytest
    pytest.main([__file__, '-v', '--tb=short'])
