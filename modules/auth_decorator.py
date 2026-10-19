"""
Authentication decorators for protecting routes and API endpoints.

This module provides decorators to enforce OAuth2 authentication on Flask routes.
It includes session validation, token expiration checking, and helper functions
for user management.

Requirements: 1.5, 3.1, 3.2, 3.4, 4.4
"""

from functools import wraps
from flask import session, redirect, url_for, request, jsonify
from datetime import datetime
from typing import Optional, Dict, Any, Callable
import logging

logger = logging.getLogger(__name__)


def is_token_expired(token_expires_at: Optional[int]) -> bool:
    """
    Check if the authentication token has expired.
    
    Args:
        token_expires_at: Unix timestamp of token expiration, or None
        
    Returns:
        True if token is expired or missing, False otherwise
        
    Requirements: 2.2, 2.3
    """
    if token_expires_at is None:
        logger.debug("Token expiration check: no expiration timestamp found")
        return True
    
    current_time = datetime.utcnow().timestamp()
    is_expired = current_time >= token_expires_at
    
    if is_expired:
        time_since_expiry = current_time - token_expires_at
        logger.debug(
            f"Token expired {time_since_expiry:.0f} seconds ago",
            extra={'token_expires_at': token_expires_at, 'current_time': current_time}
        )
    
    return is_expired


def get_current_user() -> Optional[Dict[str, Any]]:
    """
    Retrieve the current authenticated user from the session.
    
    Returns:
        User dictionary containing id, email, name, picture, and provider,
        or None if no user is authenticated
    """
    return session.get('user')


def clear_session() -> None:
    """
    Clear all session data for logout or expired sessions.
    
    This utility ensures complete session cleanup including user data,
    tokens, and any temporary redirect URLs.
    
    Requirements: 2.4, 4.4
    """
    # Get user info before clearing for logging
    user = session.get('user', {})
    user_email = user.get('email', 'unknown')
    user_id = user.get('id', 'unknown')
    
    session.clear()
    
    logger.info(
        "Session cleared",
        extra={'user_email': user_email, 'user_id': user_id}
    )


def require_auth(f: Callable) -> Callable:
    """
    Decorator to require authentication for page routes.
    
    This decorator checks if a user is authenticated and has a valid token.
    If not authenticated, it redirects to the login page. If the token is
    expired, it clears the session and redirects to login.
    
    The original requested URL is stored in the session for redirect after
    successful authentication.
    
    Args:
        f: The Flask route function to protect
        
    Returns:
        Decorated function that enforces authentication
        
    Requirements: 1.5, 3.1, 3.2, 3.4, 4.4
        
    Example:
        @app.route('/')
        @require_auth
        def index():
            return render_template('index.html')
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is in session
        if 'user' not in session:
            logger.warning(
                f"Unauthenticated access attempt to protected route",
                extra={
                    'path': request.path,
                    'method': request.method,
                    'ip_address': request.remote_addr,
                    'user_agent': request.headers.get('User-Agent', 'unknown')
                }
            )
            # Store original URL for redirect after login
            session['next_url'] = request.url
            return redirect(url_for('login'))
        
        # Get user info for logging
        user = session.get('user', {})
        user_email = user.get('email', 'unknown')
        user_id = user.get('id', 'unknown')
        provider = user.get('provider', 'unknown')
        
        # Check token expiration
        token_expires_at = session.get('token_expires_at')
        if is_token_expired(token_expires_at):
            logger.info(
                f"Session expired for user",
                extra={
                    'user_email': user_email,
                    'user_id': user_id,
                    'provider': provider,
                    'path': request.path,
                    'token_expires_at': token_expires_at
                }
            )
            clear_session()
            session['next_url'] = request.url
            return redirect(url_for('login'))
        
        # User is authenticated and token is valid
        logger.debug(
            f"Authenticated access to protected route",
            extra={
                'user_email': user_email,
                'user_id': user_id,
                'provider': provider,
                'path': request.path
            }
        )
        
        return f(*args, **kwargs)
    
    return decorated_function


def require_api_auth(f: Callable) -> Callable:
    """
    Decorator to require authentication for API endpoints.
    
    This decorator checks if a user is authenticated and has a valid token.
    Unlike require_auth, this returns JSON error responses instead of redirects,
    making it suitable for API endpoints that are called via AJAX/fetch.
    
    Args:
        f: The Flask API route function to protect
        
    Returns:
        Decorated function that enforces authentication
        
    Requirements: 3.1, 3.2, 3.4, 4.4
        
    Example:
        @app.route('/api/chat', methods=['POST'])
        @require_api_auth
        def chat():
            return jsonify({'response': 'Hello'})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is in session
        if 'user' not in session:
            logger.warning(
                f"Unauthenticated API access attempt",
                extra={
                    'path': request.path,
                    'method': request.method,
                    'ip_address': request.remote_addr,
                    'user_agent': request.headers.get('User-Agent', 'unknown')
                }
            )
            return jsonify({
                'error': True,
                'message': 'Authentication required',
                'code': 'UNAUTHORIZED'
            }), 401
        
        # Get user info for logging
        user = session.get('user', {})
        user_email = user.get('email', 'unknown')
        user_id = user.get('id', 'unknown')
        provider = user.get('provider', 'unknown')
        
        # Check token expiration
        token_expires_at = session.get('token_expires_at')
        if is_token_expired(token_expires_at):
            logger.info(
                f"Session expired for API access",
                extra={
                    'user_email': user_email,
                    'user_id': user_id,
                    'provider': provider,
                    'path': request.path,
                    'token_expires_at': token_expires_at
                }
            )
            clear_session()
            return jsonify({
                'error': True,
                'message': 'Session expired',
                'code': 'SESSION_EXPIRED'
            }), 401
        
        # User is authenticated and token is valid
        logger.debug(
            f"Authenticated API access",
            extra={
                'user_email': user_email,
                'user_id': user_id,
                'provider': provider,
                'path': request.path,
                'method': request.method
            }
        )
        
        return f(*args, **kwargs)
    
    return decorated_function
