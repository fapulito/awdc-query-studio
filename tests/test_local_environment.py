"""
Test script to verify local Flask environment works properly.
This test ensures the application can run in a local development environment.
Requirements: All
"""

import os
import sys
import pytest
from unittest.mock import patch

# Add modules to path
sys.path.insert(0, 'modules')


class TestLocalEnvironment:
    """Test local Flask environment setup and configuration"""
    
    def test_app_imports_successfully(self):
        """Test that the Flask app can be imported without errors"""
        try:
            from app import app
            assert app is not None
            # App exists and is a Flask instance
            assert hasattr(app, 'config')
        except Exception as e:
            pytest.fail(f"Failed to import Flask app: {str(e)}")
    
    def test_app_configuration(self):
        """Test that app configuration is properly set"""
        from app import app
        
        # Check essential configuration exists
        assert 'SECRET_KEY' in app.config
        assert app.config['SECRET_KEY'] is not None
        assert app.config['SESSION_TYPE'] == 'filesystem'
        assert app.config['SESSION_COOKIE_HTTPONLY'] is True
        assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
    
    def test_routes_are_registered(self):
        """Test that all required routes are registered"""
        from app import app
        
        # Get all registered routes
        routes = [rule.rule for rule in app.url_map.iter_rules()]
        
        # Check authentication routes
        assert '/login' in routes
        assert '/auth/<provider>' in routes
        assert '/callback/<provider>' in routes
        assert '/logout' in routes
        
        # Check main routes
        assert '/' in routes
        assert '/api/chat' in routes
        assert '/api/health' in routes
        assert '/api/user' in routes
        
        # Check session routes
        assert '/api/session/history' in routes
        assert '/api/session/clear' in routes
        
        # Check analytics routes
        assert '/admin/analytics' in routes
        assert '/api/analytics' in routes
    
    def test_oauth2_manager_with_credentials(self):
        """Test OAuth2 manager initializes when credentials are provided"""
        from flask import Flask
        from modules.oauth2_manager import OAuth2Manager
        from config import Config
        
        # Temporarily set credentials on Config class
        original_google_id = Config.GOOGLE_CLIENT_ID
        original_google_secret = Config.GOOGLE_CLIENT_SECRET
        
        try:
            Config.GOOGLE_CLIENT_ID = 'test_google_id'
            Config.GOOGLE_CLIENT_SECRET = 'test_google_secret'
            
            test_app = Flask(__name__)
            test_app.config['SECRET_KEY'] = 'test_secret'
            
            manager = OAuth2Manager(test_app)
            assert manager is not None
            assert 'google' in manager.get_configured_providers()
        finally:
            # Restore original values
            Config.GOOGLE_CLIENT_ID = original_google_id
            Config.GOOGLE_CLIENT_SECRET = original_google_secret
    
    def test_test_client_creation(self):
        """Test that Flask test client can be created"""
        from app import app
        
        app.config['TESTING'] = True
        client = app.test_client()
        
        assert client is not None
    
    def test_health_endpoint_accessible(self):
        """Test that health endpoint is accessible without authentication"""
        from app import app
        
        app.config['TESTING'] = True
        client = app.test_client()
        
        response = client.get('/api/health')
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'status' in data
        assert 'timestamp' in data
    
    def test_login_page_accessible(self):
        """Test that login page is accessible"""
        from app import app
        
        app.config['TESTING'] = True
        client = app.test_client()
        
        response = client.get('/login')
        
        # Should return 200 even without OAuth2 configured
        # (will show error message to user)
        assert response.status_code == 200
    
    def test_protected_routes_redirect_to_login(self):
        """Test that protected routes redirect to login when not authenticated"""
        from app import app
        
        app.config['TESTING'] = True
        client = app.test_client()
        
        # Test main page
        response = client.get('/', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.location
        
        # Test analytics dashboard
        response = client.get('/admin/analytics', follow_redirects=False)
        assert response.status_code == 302
        assert '/login' in response.location
    
    def test_protected_api_returns_401(self):
        """Test that protected API endpoints return 401 when not authenticated"""
        from app import app
        
        app.config['TESTING'] = True
        client = app.test_client()
        
        # Test chat API
        response = client.post('/api/chat', json={'message': 'test'})
        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 'UNAUTHORIZED'
        
        # Test user API
        response = client.get('/api/user')
        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 'UNAUTHORIZED'
        
        # Test session history API
        response = client.get('/api/session/history')
        assert response.status_code == 401
        
        # Test session clear API
        response = client.post('/api/session/clear')
        assert response.status_code == 401
        
        # Test analytics API
        response = client.get('/api/analytics')
        assert response.status_code == 401


if __name__ == '__main__':
    # Run with pytest
    pytest.main([__file__, '-v', '--tb=short'])
