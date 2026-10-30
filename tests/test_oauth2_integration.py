"""
OAuth2 Authentication Integration Tests
Tests complete OAuth2 flow, protected routes, session management, and error handling
Requirements: All
"""

import os
import sys
import pytest
import json
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from flask import session

# Add modules to path
sys.path.insert(0, 'modules')

from modules.oauth2_manager import OAuth2Manager, OAuth2Error


# ============================================================================
# OAuth2 Flow Integration Tests
# ============================================================================

class TestOAuth2FlowIntegration:
    """Test complete OAuth2 authentication flow with mocked providers"""
    
    @pytest.fixture
    def client(self):
        """Create test client with mocked OAuth2 manager"""
        from app import app as flask_app
        flask_app.config['TESTING'] = True
        flask_app.config['SECRET_KEY'] = 'test_secret_key_for_integration'
        return flask_app.test_client()
    
    @patch('app.oauth2_manager')
    def test_complete_oauth2_flow_google(self, mock_oauth2_manager, client):
        """Test complete OAuth2 flow with Google provider"""
        from flask import redirect
        
        # Configure mock OAuth2 manager
        mock_oauth2_manager.get_configured_providers.return_value = ['google', 'github']
        mock_oauth2_manager.is_provider_configured.return_value = True
        
        # Step 1: Access login page
        response = client.get('/login')
        assert response.status_code == 200
        assert b'google' in response.data.lower()
        
        # Step 2: Initiate OAuth2 flow
        # Mock create_authorization_url to return a redirect response
        mock_oauth2_manager.create_authorization_url.return_value = (
            redirect('https://accounts.google.com/o/oauth2/auth?state=test_state'),
            'test_state'
        )
        
        response = client.get('/auth/google', follow_redirects=False)
        assert response.status_code == 302
        assert 'accounts.google.com' in response.location
        
        # Step 3: Handle OAuth2 callback
        mock_oauth2_manager.validate_state.return_value = True
        mock_oauth2_manager.exchange_code_for_token.return_value = {
            'access_token': 'test_access_token',
            'expires_in': 3600,
            'token_type': 'Bearer'
        }
        mock_oauth2_manager.get_user_info.return_value = {
            'id': 'google_user_123',
            'email': 'test@example.com',
            'name': 'Test User',
            'picture': 'https://example.com/photo.jpg',
            'provider': 'google'
        }
        
        # Set state in session
        with client.session_transaction() as sess:
            sess['oauth2_state'] = 'test_state'
        
        # Simulate callback from Google
        response = client.get(
            '/callback/google?code=test_auth_code&state=test_state',
            follow_redirects=False
        )
        
        assert response.status_code == 302
        assert response.location == '/'
        
        # Verify session contains user data
        with client.session_transaction() as sess:
            assert 'user' in sess
            assert sess['user']['email'] == 'test@example.com'
            assert sess['user']['provider'] == 'google'
            assert 'access_token' in sess
            assert 'token_expires_at' in sess
    
    @patch('app.oauth2_manager')
    def test_complete_oauth2_flow_github(self, mock_oauth2_manager, client):
        """Test complete OAuth2 flow with GitHub provider"""
        from flask import redirect
        
        # Configure mock OAuth2 manager
        mock_oauth2_manager.is_provider_configured.return_value = True
        
        # Step 1: Initiate OAuth2 flow
        mock_oauth2_manager.create_authorization_url.return_value = (
            redirect('https://github.com/login/oauth/authorize?state=test_state'),
            'test_state'
        )
        
        response = client.get('/auth/github', follow_redirects=False)
        assert response.status_code == 302
        assert 'github.com' in response.location
        
        # Step 2: Handle OAuth2 callback
        mock_oauth2_manager.validate_state.return_value = True
        mock_oauth2_manager.exchange_code_for_token.return_value = {
            'access_token': 'github_token',
            'expires_in': 3600
        }
        mock_oauth2_manager.get_user_info.return_value = {
            'id': 'github_user_456',
            'email': 'github@example.com',
            'name': 'GitHub User',
            'provider': 'github'
        }
        
        with client.session_transaction() as sess:
            sess['oauth2_state'] = 'test_state'
        
        response = client.get(
            '/callback/github?code=test_code&state=test_state',
            follow_redirects=False
        )
        
        assert response.status_code == 302
        
        with client.session_transaction() as sess:
            assert sess['user']['provider'] == 'github'


# ============================================================================
# Protected Route Access Tests
# ============================================================================

class TestProtectedRouteAccess:
    """Test protected route access with and without authentication"""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app"""
        from app import app as flask_app
        flask_app.config['TESTING'] = True
        flask_app.config['SECRET_KEY'] = 'test_secret_key'
        return flask_app
    
    @pytest.fixture
    def client(self, app):
        """Create test client"""
        return app.test_client()
    
    def test_access_protected_page_without_auth(self, client):
        """Test accessing protected page without authentication redirects to login"""
        response = client.get('/', follow_redirects=False)
        
        assert response.status_code == 302
        assert '/login' in response.location
    
    def test_access_protected_page_with_auth(self, client):
        """Test accessing protected page with valid authentication"""
        # Set up authenticated session
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com',
                'name': 'Test User',
                'provider': 'google'
            }
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        
        response = client.get('/')
        
        assert response.status_code == 200
        assert b'Test User' in response.data or b'test@example.com' in response.data
    
    def test_access_protected_api_without_auth(self, client):
        """Test accessing protected API without authentication returns 401"""
        response = client.post(
            '/api/chat',
            json={'message': 'Hello'},
            content_type='application/json'
        )
        
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['error'] is True
        assert data['code'] == 'UNAUTHORIZED'
    
    @patch('app.llm_service')
    @patch('app.mcp_client')
    def test_access_protected_api_with_auth(self, mock_mcp, mock_llm, client):
        """Test accessing protected API with valid authentication"""
        # Set up authenticated session
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com',
                'name': 'Test User'
            }
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        
        # Mock LLM service
        mock_llm.create_system_prompt.return_value = "You are a helpful assistant"
        mock_llm.process_conversation.return_value = ("Hello! How can I help?", [], [])
        mock_llm.config.provider = "openai"
        
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
    
    def test_access_health_endpoint_without_auth(self, client):
        """Test health endpoint is accessible without authentication"""
        response = client.get('/api/health')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'status' in data
        assert 'timestamp' in data
    
    def test_access_session_history_without_auth(self, client):
        """Test session history endpoint requires authentication"""
        response = client.get('/api/session/history')
        
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['code'] == 'UNAUTHORIZED'
    
    def test_access_session_clear_without_auth(self, client):
        """Test session clear endpoint requires authentication"""
        response = client.post('/api/session/clear')
        
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['code'] == 'UNAUTHORIZED'


# ============================================================================
# Session Expiration and Renewal Tests
# ============================================================================

class TestSessionExpirationAndRenewal:
    """Test session expiration and renewal scenarios"""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app"""
        from app import app as flask_app
        flask_app.config['TESTING'] = True
        flask_app.config['SECRET_KEY'] = 'test_secret_key'
        return flask_app
    
    @pytest.fixture
    def client(self, app):
        """Create test client"""
        return app.test_client()
    
    def test_expired_token_redirects_to_login(self, client):
        """Test that expired token redirects to login page"""
        # Set up session with expired token
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com'
            }
            # Token expired 1 hour ago
            sess['token_expires_at'] = (datetime.utcnow() - timedelta(hours=1)).timestamp()
        
        response = client.get('/', follow_redirects=False)
        
        assert response.status_code == 302
        assert '/login' in response.location
        
        # Verify session was cleared
        with client.session_transaction() as sess:
            assert 'user' not in sess
    
    def test_expired_token_api_returns_401(self, client):
        """Test that expired token returns 401 for API endpoints"""
        # Set up session with expired token
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com'
            }
            # Token expired 1 hour ago
            sess['token_expires_at'] = (datetime.utcnow() - timedelta(hours=1)).timestamp()
        
        response = client.post(
            '/api/chat',
            json={'message': 'Hello'},
            content_type='application/json'
        )
        
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['code'] == 'SESSION_EXPIRED'
    
    def test_valid_token_allows_access(self, client):
        """Test that valid token allows access"""
        # Set up session with valid token
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com',
                'name': 'Test User'
            }
            # Token expires in 1 hour
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        
        response = client.get('/')
        
        assert response.status_code == 200
    
    def test_session_persistence_across_requests(self, client):
        """Test that session persists across multiple requests"""
        # Set up authenticated session
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com'
            }
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        
        # Make first request
        response1 = client.get('/')
        assert response1.status_code == 200
        
        # Make second request - session should still be valid
        response2 = client.get('/')
        assert response2.status_code == 200
        
        # Verify session data persists
        with client.session_transaction() as sess:
            assert sess['user']['email'] == 'test@example.com'


# ============================================================================
# Error Handling Scenarios Tests
# ============================================================================

class TestErrorHandlingScenarios:
    """Test various error handling scenarios in OAuth2 flow"""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app"""
        from app import app as flask_app
        flask_app.config['TESTING'] = True
        flask_app.config['SECRET_KEY'] = 'test_secret_key'
        return flask_app
    
    @pytest.fixture
    def client(self, app):
        """Create test client"""
        return app.test_client()
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    def test_invalid_state_parameter(self, client):
        """Test handling of invalid state parameter in callback"""
        with patch('modules.oauth2_manager.OAuth2Manager.validate_state') as mock_validate:
            mock_validate.return_value = False
            
            # Set different state in session
            with client.session_transaction() as sess:
                sess['oauth2_state'] = 'correct_state'
            
            # Callback with wrong state
            response = client.get(
                '/callback/google?code=test_code&state=wrong_state',
                follow_redirects=False
            )
            
            assert response.status_code == 302
            assert '/login' in response.location
            assert 'error=' in response.location
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    def test_provider_error_in_callback(self, client):
        """Test handling of error from OAuth2 provider"""
        response = client.get(
            '/callback/google?error=access_denied&error_description=User+cancelled',
            follow_redirects=False
        )
        
        assert response.status_code == 302
        assert '/login' in response.location
        assert 'error=' in response.location
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    def test_token_exchange_failure(self, client):
        """Test handling of token exchange failure"""
        with patch('modules.oauth2_manager.OAuth2Manager.validate_state') as mock_validate, \
             patch('modules.oauth2_manager.OAuth2Manager.exchange_code_for_token') as mock_exchange:
            
            mock_validate.return_value = True
            mock_exchange.side_effect = OAuth2Error(
                message="Failed to exchange code for token",
                code="TOKEN_EXCHANGE_ERROR"
            )
            
            with client.session_transaction() as sess:
                sess['oauth2_state'] = 'test_state'
            
            response = client.get(
                '/callback/google?code=invalid_code&state=test_state',
                follow_redirects=False
            )
            
            assert response.status_code == 302
            assert '/login' in response.location
            assert 'error=' in response.location
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    def test_user_info_retrieval_failure(self, client):
        """Test handling of user info retrieval failure"""
        with patch('modules.oauth2_manager.OAuth2Manager.validate_state') as mock_validate, \
             patch('modules.oauth2_manager.OAuth2Manager.exchange_code_for_token') as mock_exchange, \
             patch('modules.oauth2_manager.OAuth2Manager.get_user_info') as mock_user_info:
            
            mock_validate.return_value = True
            mock_exchange.return_value = {'access_token': 'test_token', 'expires_in': 3600}
            mock_user_info.side_effect = OAuth2Error(
                message="Failed to retrieve user information",
                code="USER_INFO_ERROR"
            )
            
            with client.session_transaction() as sess:
                sess['oauth2_state'] = 'test_state'
            
            response = client.get(
                '/callback/google?code=test_code&state=test_state',
                follow_redirects=False
            )
            
            assert response.status_code == 302
            assert '/login' in response.location
            assert 'error=' in response.location
    
    def test_unconfigured_provider_access(self, client):
        """Test accessing unconfigured provider returns error"""
        response = client.get('/auth/facebook', follow_redirects=False)
        
        assert response.status_code == 302
        assert '/login' in response.location
        assert 'error=' in response.location
    
    def test_missing_message_in_chat_api(self, client):
        """Test chat API with missing message field"""
        # Set up authenticated session
        with client.session_transaction() as sess:
            sess['user'] = {'id': '123', 'email': 'test@example.com'}
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        
        response = client.post(
            '/api/chat',
            json={},
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['code'] == 'INVALID_REQUEST'
    
    def test_empty_message_in_chat_api(self, client):
        """Test chat API with empty message"""
        # Set up authenticated session
        with client.session_transaction() as sess:
            sess['user'] = {'id': '123', 'email': 'test@example.com'}
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        
        response = client.post(
            '/api/chat',
            json={'message': '   '},
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['code'] == 'EMPTY_MESSAGE'


# ============================================================================
# Logout Flow Tests
# ============================================================================

class TestLogoutFlow:
    """Test logout functionality"""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app"""
        from app import app as flask_app
        flask_app.config['TESTING'] = True
        flask_app.config['SECRET_KEY'] = 'test_secret_key'
        return flask_app
    
    @pytest.fixture
    def client(self, app):
        """Create test client"""
        return app.test_client()
    
    def test_logout_clears_session(self, client):
        """Test that logout clears all session data"""
        # Set up authenticated session
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com',
                'name': 'Test User'
            }
            sess['access_token'] = 'test_token'
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
            sess['other_data'] = 'should_be_cleared'
        
        # Logout
        response = client.get('/logout', follow_redirects=False)
        
        assert response.status_code == 302
        assert '/login' in response.location
        
        # Verify session is cleared
        with client.session_transaction() as sess:
            assert 'user' not in sess
            assert 'access_token' not in sess
            assert 'token_expires_at' not in sess
            assert 'other_data' not in sess
    
    def test_logout_redirects_to_login(self, client):
        """Test that logout redirects to login page"""
        # Set up authenticated session
        with client.session_transaction() as sess:
            sess['user'] = {'id': '123', 'email': 'test@example.com'}
        
        response = client.get('/logout', follow_redirects=False)
        
        assert response.status_code == 302
        assert response.location == '/login'
    
    def test_access_after_logout_requires_reauth(self, client):
        """Test that accessing protected routes after logout requires re-authentication"""
        # Set up and logout
        with client.session_transaction() as sess:
            sess['user'] = {'id': '123', 'email': 'test@example.com'}
        
        client.get('/logout')
        
        # Try to access protected route
        response = client.get('/', follow_redirects=False)
        
        assert response.status_code == 302
        assert '/login' in response.location


# ============================================================================
# User Info API Tests
# ============================================================================

class TestUserInfoAPI:
    """Test user info API endpoint"""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app"""
        from app import app as flask_app
        flask_app.config['TESTING'] = True
        flask_app.config['SECRET_KEY'] = 'test_secret_key'
        return flask_app
    
    @pytest.fixture
    def client(self, app):
        """Create test client"""
        return app.test_client()
    
    def test_get_user_info_without_auth(self, client):
        """Test getting user info without authentication"""
        response = client.get('/api/user')
        
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['code'] == 'UNAUTHORIZED'
    
    def test_get_user_info_with_auth(self, client):
        """Test getting user info with authentication"""
        # Set up authenticated session
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': 'user_123',
                'email': 'test@example.com',
                'name': 'Test User',
                'picture': 'https://example.com/photo.jpg',
                'provider': 'google'
            }
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        
        response = client.get('/api/user')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['id'] == 'user_123'
        assert data['email'] == 'test@example.com'
        assert data['name'] == 'Test User'
        assert data['provider'] == 'google'


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == '__main__':
    # Run with pytest
    pytest.main([__file__, '-v', '--tb=short'])
