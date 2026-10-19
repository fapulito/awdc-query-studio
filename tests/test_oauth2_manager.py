"""
Unit Tests for OAuth2 Manager and Authentication Components
Tests OAuth2Manager, authentication decorators, and session validation
Requirements: All
"""

import os
import sys
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, timedelta
from flask import Flask, session

# Add modules to path
sys.path.insert(0, 'modules')

from modules.oauth2_manager import OAuth2Manager, OAuth2Error
from modules.auth_decorator import (
    is_token_expired,
    get_current_user,
    clear_session,
    require_auth,
    require_api_auth
)


# ============================================================================
# OAuth2Manager Tests
# ============================================================================

class TestOAuth2Manager:
    """Test OAuth2Manager class functionality"""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app"""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test_secret_key'
        app.config['TESTING'] = True
        return app
    
    @pytest.fixture
    def app_context(self, app):
        """Create Flask app context"""
        with app.app_context():
            yield app
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_initialization_with_google(self, mock_config, app_context):
        """Test OAuth2Manager initialization with Google provider"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        manager = OAuth2Manager(app_context)
        
        assert 'google' in manager.providers
        assert manager.is_provider_configured('google')
    
    @patch.dict(os.environ, {
        'GITHUB_CLIENT_ID': 'test_github_id',
        'GITHUB_CLIENT_SECRET': 'test_github_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_initialization_with_github(self, mock_config, app_context):
        """Test OAuth2Manager initialization with GitHub provider"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = None
        mock_config.GOOGLE_CLIENT_SECRET = None
        mock_config.GITHUB_CLIENT_ID = 'test_github_id'
        mock_config.GITHUB_CLIENT_SECRET = 'test_github_secret'
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        manager = OAuth2Manager(app_context)
        
        assert 'github' in manager.providers
        assert manager.is_provider_configured('github')
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret',
        'GITHUB_CLIENT_ID': 'test_github_id',
        'GITHUB_CLIENT_SECRET': 'test_github_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_initialization_with_multiple_providers(self, mock_config, app_context):
        """Test OAuth2Manager initialization with multiple providers"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = 'test_github_id'
        mock_config.GITHUB_CLIENT_SECRET = 'test_github_secret'
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        manager = OAuth2Manager(app_context)
        
        assert len(manager.providers) == 2
        assert 'google' in manager.providers
        assert 'github' in manager.providers
    
    @patch.dict(os.environ, {}, clear=True)
    @patch('modules.oauth2_manager.Config')
    def test_initialization_without_providers_fails(self, mock_config, app_context):
        """Test OAuth2Manager initialization fails without any providers"""
        # Mock Config class attributes with no providers
        mock_config.GOOGLE_CLIENT_ID = None
        mock_config.GOOGLE_CLIENT_SECRET = None
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        with pytest.raises(OAuth2Error) as exc_info:
            OAuth2Manager(app_context)
        
        # The error is wrapped, so check that it's an initialization error
        assert exc_info.value.code in ['NO_PROVIDERS_CONFIGURED', 'OAUTH2_INIT_ERROR']
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_get_provider_success(self, mock_config, app_context):
        """Test getting a configured provider"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        manager = OAuth2Manager(app_context)
        
        provider = manager.get_provider('google')
        assert provider is not None
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_get_provider_not_configured(self, mock_config, app_context):
        """Test getting an unconfigured provider raises error"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        manager = OAuth2Manager(app_context)
        
        with pytest.raises(OAuth2Error) as exc_info:
            manager.get_provider('github')
        
        assert exc_info.value.code == 'PROVIDER_NOT_CONFIGURED'
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_is_provider_configured(self, mock_config, app_context):
        """Test checking if provider is configured"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        manager = OAuth2Manager(app_context)
        
        assert manager.is_provider_configured('google') is True
        assert manager.is_provider_configured('github') is False
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret',
        'GITHUB_CLIENT_ID': 'test_github_id',
        'GITHUB_CLIENT_SECRET': 'test_github_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_get_configured_providers(self, mock_config, app_context):
        """Test getting list of configured providers"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = 'test_github_id'
        mock_config.GITHUB_CLIENT_SECRET = 'test_github_secret'
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        manager = OAuth2Manager(app_context)
        
        providers = manager.get_configured_providers()
        assert len(providers) == 2
        assert 'google' in providers
        assert 'github' in providers


# ============================================================================
# Authentication Decorator Tests
# ============================================================================

class TestAuthenticationDecorators:
    """Test authentication decorators and helper functions"""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app with routes"""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test_secret_key'
        app.config['TESTING'] = True
        
        @app.route('/protected')
        @require_auth
        def protected_route():
            return 'Protected content'
        
        @app.route('/api/protected', methods=['POST'])
        @require_api_auth
        def protected_api():
            return {'data': 'Protected API data'}
        
        @app.route('/login')
        def login():
            return 'Login page'
        
        return app
    
    @pytest.fixture
    def client(self, app):
        """Create test client"""
        return app.test_client()
    
    def test_is_token_expired_with_none(self):
        """Test token expiration check with None"""
        assert is_token_expired(None) is True
    
    def test_is_token_expired_with_expired_token(self):
        """Test token expiration check with expired token"""
        # Token expired 1 hour ago
        expired_time = (datetime.utcnow() - timedelta(hours=1)).timestamp()
        assert is_token_expired(expired_time) is True
    
    def test_is_token_expired_with_valid_token(self):
        """Test token expiration check with valid token"""
        # Token expires in 1 hour
        future_time = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        assert is_token_expired(future_time) is False
    
    def test_get_current_user_with_session(self, app):
        """Test getting current user from session"""
        with app.test_request_context():
            session['user'] = {
                'id': '123',
                'email': 'test@example.com',
                'name': 'Test User'
            }
            
            user = get_current_user()
            assert user is not None
            assert user['email'] == 'test@example.com'
    
    def test_get_current_user_without_session(self, app):
        """Test getting current user without session"""
        with app.test_request_context():
            user = get_current_user()
            assert user is None
    
    def test_clear_session(self, app):
        """Test clearing session data"""
        with app.test_request_context():
            session['user'] = {'id': '123'}
            session['token_expires_at'] = 12345
            session['other_data'] = 'test'
            
            clear_session()
            
            assert 'user' not in session
            assert 'token_expires_at' not in session
            assert 'other_data' not in session
    
    def test_require_auth_without_authentication(self, client):
        """Test require_auth decorator redirects unauthenticated users"""
        response = client.get('/protected')
        
        assert response.status_code == 302
        assert '/login' in response.location
    
    def test_require_auth_with_valid_authentication(self, client):
        """Test require_auth decorator allows authenticated users"""
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com',
                'name': 'Test User'
            }
            # Token expires in 1 hour
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        
        response = client.get('/protected')
        
        assert response.status_code == 200
        assert b'Protected content' in response.data
    
    def test_require_auth_with_expired_token(self, client):
        """Test require_auth decorator redirects users with expired tokens"""
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com'
            }
            # Token expired 1 hour ago
            sess['token_expires_at'] = (datetime.utcnow() - timedelta(hours=1)).timestamp()
        
        response = client.get('/protected')
        
        assert response.status_code == 302
        assert '/login' in response.location
    
    def test_require_api_auth_without_authentication(self, client):
        """Test require_api_auth decorator returns 401 for unauthenticated users"""
        response = client.post('/api/protected')
        
        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] is True
        assert data['code'] == 'UNAUTHORIZED'
    
    def test_require_api_auth_with_valid_authentication(self, client):
        """Test require_api_auth decorator allows authenticated users"""
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com'
            }
            # Token expires in 1 hour
            sess['token_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
        
        response = client.post('/api/protected')
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'data' in data
    
    def test_require_api_auth_with_expired_token(self, client):
        """Test require_api_auth decorator returns 401 for expired tokens"""
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': '123',
                'email': 'test@example.com'
            }
            # Token expired 1 hour ago
            sess['token_expires_at'] = (datetime.utcnow() - timedelta(hours=1)).timestamp()
        
        response = client.post('/api/protected')
        
        assert response.status_code == 401
        data = response.get_json()
        assert data['error'] is True
        assert data['code'] == 'SESSION_EXPIRED'


# ============================================================================
# Session Validation Tests
# ============================================================================

class TestSessionValidation:
    """Test session validation logic"""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app"""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test_secret_key'
        app.config['TESTING'] = True
        return app
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_validate_state_success(self, mock_config, app):
        """Test successful state validation"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        with app.test_request_context():
            manager = OAuth2Manager(app)
            
            # Set state in session
            test_state = 'test_state_token_12345'
            session['oauth2_state'] = test_state
            
            # Validate with same state
            assert manager.validate_state(test_state) is True
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_validate_state_mismatch(self, mock_config, app):
        """Test state validation fails with mismatch"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        with app.test_request_context():
            manager = OAuth2Manager(app)
            
            # Set state in session
            session['oauth2_state'] = 'correct_state'
            
            # Validate with different state
            assert manager.validate_state('wrong_state') is False
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_validate_state_no_stored_state(self, mock_config, app):
        """Test state validation fails without stored state"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        with app.test_request_context():
            manager = OAuth2Manager(app)
            
            # No state in session
            assert manager.validate_state('some_state') is False
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_validate_state_no_provided_state(self, mock_config, app):
        """Test state validation fails without provided state"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        with app.test_request_context():
            manager = OAuth2Manager(app)
            
            # Set state in session
            session['oauth2_state'] = 'test_state'
            
            # Validate with None
            assert manager.validate_state(None) is False
    
    @patch.dict(os.environ, {
        'GOOGLE_CLIENT_ID': 'test_google_id',
        'GOOGLE_CLIENT_SECRET': 'test_google_secret'
    })
    @patch('modules.oauth2_manager.Config')
    def test_clear_session_state(self, mock_config, app):
        """Test clearing OAuth2 session state"""
        # Mock Config class attributes
        mock_config.GOOGLE_CLIENT_ID = 'test_google_id'
        mock_config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
        mock_config.GITHUB_CLIENT_ID = None
        mock_config.GITHUB_CLIENT_SECRET = None
        mock_config.FACEBOOK_CLIENT_ID = None
        mock_config.FACEBOOK_CLIENT_SECRET = None
        mock_config.LINKEDIN_CLIENT_ID = None
        mock_config.LINKEDIN_CLIENT_SECRET = None
        mock_config.AUTH0_CLIENT_ID = None
        mock_config.AUTH0_CLIENT_SECRET = None
        mock_config.AUTH0_DOMAIN = None
        
        with app.test_request_context():
            manager = OAuth2Manager(app)
            
            # Set OAuth2 session data
            session['oauth2_state'] = 'test_state'
            session['oauth2_provider'] = 'google'
            session['other_data'] = 'should_remain'
            
            manager.clear_session_state()
            
            # OAuth2 data should be cleared
            assert 'oauth2_state' not in session
            assert 'oauth2_provider' not in session
            # Other data should remain
            assert session.get('other_data') == 'should_remain'


# ============================================================================
# OAuth2Error Tests
# ============================================================================

class TestOAuth2Error:
    """Test OAuth2Error exception class"""
    
    def test_oauth2_error_basic(self):
        """Test basic OAuth2Error creation"""
        error = OAuth2Error(
            message="Test error message",
            code="TEST_ERROR"
        )
        
        assert error.message == "Test error message"
        assert error.code == "TEST_ERROR"
        assert error.details is None
    
    def test_oauth2_error_with_details(self):
        """Test OAuth2Error with details"""
        error = OAuth2Error(
            message="User-friendly message",
            code="ERROR_CODE",
            details="Technical details for debugging"
        )
        
        assert error.message == "User-friendly message"
        assert error.code == "ERROR_CODE"
        assert error.details == "Technical details for debugging"
    
    def test_oauth2_error_to_dict(self):
        """Test OAuth2Error to_dict method"""
        error = OAuth2Error(
            message="Test message",
            code="TEST_CODE",
            details="Test details"
        )
        
        error_dict = error.to_dict()
        
        assert error_dict['error'] is True
        assert error_dict['message'] == "Test message"
        assert error_dict['code'] == "TEST_CODE"
        assert error_dict['details'] == "Test details"
    
    def test_oauth2_error_to_dict_without_details(self):
        """Test OAuth2Error to_dict without details"""
        error = OAuth2Error(
            message="Test message",
            code="TEST_CODE"
        )
        
        error_dict = error.to_dict()
        
        assert error_dict['error'] is True
        assert error_dict['message'] == "Test message"
        assert error_dict['code'] == "TEST_CODE"
        assert 'details' not in error_dict


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == '__main__':
    # Run with pytest
    pytest.main([__file__, '-v', '--tb=short'])
