"""
OAuth2 Manager for handling authentication with multiple providers.
Supports Google, GitHub, Facebook, LinkedIn, and Auth0.
Requirements: 4.1, 4.2, 1.1, 1.2, 1.3, 1.4, 3.4
"""

import os
import secrets
import logging
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode
from flask import Flask, session, url_for
from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client import OAuthError
from config import Config

# Initialize logger
logger = logging.getLogger(__name__)


class OAuth2Error(Exception):
    """
    Custom exception for OAuth2-related errors.
    Provides user-friendly error messages and error codes.
    Requirements: 1.4, 3.4
    """
    
    def __init__(self, message: str, code: str = 'OAUTH2_ERROR', details: Optional[str] = None):
        """
        Initialize OAuth2Error.
        
        Args:
            message: User-friendly error message
            code: Error code for categorization
            details: Technical details (not shown to users in production)
        """
        self.message = message
        self.code = code
        self.details = details
        super().__init__(self.message)
    
    def to_dict(self) -> Dict:
        """Convert error to dictionary for JSON responses."""
        error_dict = {
            'error': True,
            'message': self.message,
            'code': self.code
        }
        if self.details:
            error_dict['details'] = self.details
        return error_dict


class OAuth2Manager:
    """
    Manages OAuth2 authentication with multiple providers.
    Handles authorization URL generation, token exchange, and user info retrieval.
    Includes comprehensive error handling and logging.
    Requirements: 1.4, 3.4, 4.4
    """
    
    # Provider configuration with URLs and scopes
    PROVIDER_CONFIGS = {
        'google': {
            'authorize_url': 'https://accounts.google.com/o/oauth2/v2/auth',
            'access_token_url': 'https://oauth2.googleapis.com/token',
            'userinfo_url': 'https://www.googleapis.com/oauth2/v2/userinfo',
            'scope': 'openid email profile',
            'userinfo_compliance_fix': None,
        },
        'github': {
            'authorize_url': 'https://github.com/login/oauth/authorize',
            'access_token_url': 'https://github.com/login/oauth/access_token',
            'userinfo_url': 'https://api.github.com/user',
            'scope': 'read:user user:email',
            'userinfo_compliance_fix': None,
        },
        'facebook': {
            'authorize_url': 'https://www.facebook.com/v12.0/dialog/oauth',
            'access_token_url': 'https://graph.facebook.com/v12.0/oauth/access_token',
            'userinfo_url': 'https://graph.facebook.com/me?fields=id,name,email',
            'scope': 'email public_profile',
            'userinfo_compliance_fix': None,
        },
        'linkedin': {
            'authorize_url': 'https://www.linkedin.com/oauth/v2/authorization',
            'access_token_url': 'https://www.linkedin.com/oauth/v2/accessToken',
            'userinfo_url': 'https://api.linkedin.com/v2/me',
            'scope': 'r_liteprofile r_emailaddress',
            'userinfo_compliance_fix': None,
        },
        'auth0': {
            'authorize_url': None,  # Set dynamically based on domain
            'access_token_url': None,  # Set dynamically based on domain
            'userinfo_url': None,  # Set dynamically based on domain
            'scope': 'openid profile email',
            'userinfo_compliance_fix': None,
        }
    }
    
    def __init__(self, app: Flask):
        """
        Initialize OAuth2Manager with Flask app.
        
        Args:
            app: Flask application instance
            
        Requirements: 4.1, 4.4
        """
        self.app = app
        self.oauth = OAuth(app)
        self.providers = {}
        
        try:
            self._configure_providers()
            logger.info(
                f"OAuth2Manager initialized with {len(self.providers)} provider(s)",
                extra={'providers': list(self.providers.keys())}
            )
        except Exception as e:
            logger.error(f"Failed to initialize OAuth2Manager: {str(e)}")
            raise OAuth2Error(
                message="Failed to initialize authentication system",
                code="OAUTH2_INIT_ERROR",
                details=str(e)
            )
    
    def _configure_providers(self) -> None:
        """
        Configure OAuth2 providers based on environment variables.
        Only configures providers that have credentials set.
        
        Requirements: 4.1, 4.2, 4.4
        """
        # Configure Google
        if Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET:
            try:
                self.providers['google'] = self.oauth.register(
                    name='google',
                    client_id=Config.GOOGLE_CLIENT_ID,
                    client_secret=Config.GOOGLE_CLIENT_SECRET,
                    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                    client_kwargs={
                        'scope': self.PROVIDER_CONFIGS['google']['scope']
                    }
                )
                logger.info("Google OAuth2 provider configured successfully")
            except Exception as e:
                logger.error(f"Failed to configure Google OAuth2 provider: {str(e)}")
                raise OAuth2Error(
                    message="Failed to configure Google authentication",
                    code="PROVIDER_CONFIG_ERROR",
                    details=str(e)
                )
        
        # Configure GitHub
        if Config.GITHUB_CLIENT_ID and Config.GITHUB_CLIENT_SECRET:
            try:
                self.providers['github'] = self.oauth.register(
                    name='github',
                    client_id=Config.GITHUB_CLIENT_ID,
                    client_secret=Config.GITHUB_CLIENT_SECRET,
                    access_token_url=self.PROVIDER_CONFIGS['github']['access_token_url'],
                    access_token_params=None,
                    authorize_url=self.PROVIDER_CONFIGS['github']['authorize_url'],
                    authorize_params=None,
                    api_base_url='https://api.github.com/',
                    client_kwargs={
                        'scope': self.PROVIDER_CONFIGS['github']['scope']
                    }
                )
                logger.info("GitHub OAuth2 provider configured successfully")
            except Exception as e:
                logger.error(f"Failed to configure GitHub OAuth2 provider: {str(e)}")
                raise OAuth2Error(
                    message="Failed to configure GitHub authentication",
                    code="PROVIDER_CONFIG_ERROR",
                    details=str(e)
                )
        
        # Configure Facebook
        if Config.FACEBOOK_CLIENT_ID and Config.FACEBOOK_CLIENT_SECRET:
            try:
                self.providers['facebook'] = self.oauth.register(
                    name='facebook',
                    client_id=Config.FACEBOOK_CLIENT_ID,
                    client_secret=Config.FACEBOOK_CLIENT_SECRET,
                    access_token_url=self.PROVIDER_CONFIGS['facebook']['access_token_url'],
                    access_token_params=None,
                    authorize_url=self.PROVIDER_CONFIGS['facebook']['authorize_url'],
                    authorize_params=None,
                    api_base_url='https://graph.facebook.com/',
                    client_kwargs={
                        'scope': self.PROVIDER_CONFIGS['facebook']['scope']
                    }
                )
                logger.info("Facebook OAuth2 provider configured successfully")
            except Exception as e:
                logger.error(f"Failed to configure Facebook OAuth2 provider: {str(e)}")
                raise OAuth2Error(
                    message="Failed to configure Facebook authentication",
                    code="PROVIDER_CONFIG_ERROR",
                    details=str(e)
                )
        
        # Configure LinkedIn
        if Config.LINKEDIN_CLIENT_ID and Config.LINKEDIN_CLIENT_SECRET:
            try:
                self.providers['linkedin'] = self.oauth.register(
                    name='linkedin',
                    client_id=Config.LINKEDIN_CLIENT_ID,
                    client_secret=Config.LINKEDIN_CLIENT_SECRET,
                    access_token_url=self.PROVIDER_CONFIGS['linkedin']['access_token_url'],
                    access_token_params=None,
                    authorize_url=self.PROVIDER_CONFIGS['linkedin']['authorize_url'],
                    authorize_params=None,
                    api_base_url='https://api.linkedin.com/',
                    client_kwargs={
                        'scope': self.PROVIDER_CONFIGS['linkedin']['scope']
                    }
                )
                logger.info("LinkedIn OAuth2 provider configured successfully")
            except Exception as e:
                logger.error(f"Failed to configure LinkedIn OAuth2 provider: {str(e)}")
                raise OAuth2Error(
                    message="Failed to configure LinkedIn authentication",
                    code="PROVIDER_CONFIG_ERROR",
                    details=str(e)
                )
        
        # Configure Auth0
        if Config.AUTH0_CLIENT_ID and Config.AUTH0_CLIENT_SECRET and Config.AUTH0_DOMAIN:
            try:
                auth0_domain = Config.AUTH0_DOMAIN
                self.providers['auth0'] = self.oauth.register(
                    name='auth0',
                    client_id=Config.AUTH0_CLIENT_ID,
                    client_secret=Config.AUTH0_CLIENT_SECRET,
                    server_metadata_url=f'https://{auth0_domain}/.well-known/openid-configuration',
                    client_kwargs={
                        'scope': self.PROVIDER_CONFIGS['auth0']['scope']
                    }
                )
                logger.info("Auth0 OAuth2 provider configured successfully")
            except Exception as e:
                logger.error(f"Failed to configure Auth0 OAuth2 provider: {str(e)}")
                raise OAuth2Error(
                    message="Failed to configure Auth0 authentication",
                    code="PROVIDER_CONFIG_ERROR",
                    details=str(e)
                )
        
        # Validate that at least one provider is configured
        if not self.providers:
            logger.error("No OAuth2 providers configured")
            raise OAuth2Error(
                message="Authentication system is not properly configured. Please contact support.",
                code="NO_PROVIDERS_CONFIGURED",
                details="No OAuth2 providers have valid credentials configured"
            )
    
    def get_provider(self, provider_name: str):
        """
        Get configured OAuth2 client for specific provider.
        
        Args:
            provider_name: Name of the provider (google, github, facebook, linkedin, auth0)
            
        Returns:
            OAuth2 client instance
            
        Raises:
            OAuth2Error: If provider is not configured
            
        Requirements: 4.2, 1.4
        """
        if provider_name not in self.providers:
            available = ', '.join(self.providers.keys()) if self.providers else 'none'
            logger.warning(
                f"Attempt to use unconfigured provider: {provider_name}",
                extra={'provider': provider_name, 'available_providers': list(self.providers.keys())}
            )
            raise OAuth2Error(
                message=f"The authentication provider '{provider_name}' is not available. Please use one of: {available}",
                code="PROVIDER_NOT_CONFIGURED",
                details=f"Provider '{provider_name}' is not configured"
            )
        return self.providers[provider_name]
    
    def is_provider_configured(self, provider_name: str) -> bool:
        """
        Check if a provider is configured.
        
        Args:
            provider_name: Name of the provider
            
        Returns:
            True if provider is configured, False otherwise
        """
        return provider_name in self.providers
    
    def get_configured_providers(self) -> list:
        """
        Get list of all configured provider names.
        
        Returns:
            List of configured provider names
        """
        return list(self.providers.keys())
    
    def create_authorization_url(self, provider_name: str, redirect_uri: str) -> Tuple[str, str]:
        """
        Generate OAuth2 authorization URL and state token.
        
        Args:
            provider_name: Name of the provider
            redirect_uri: Callback URL for OAuth2 redirect
            
        Returns:
            Tuple of (authorization_url, state_token)
            
        Raises:
            OAuth2Error: If provider is not configured or URL generation fails
            
        Requirements: 1.1, 1.4
        """
        try:
            provider = self.get_provider(provider_name)
            
            # Generate secure random state token for CSRF protection
            state = secrets.token_urlsafe(32)
            
            # Store state in session for validation
            session['oauth2_state'] = state
            session['oauth2_provider'] = provider_name
            
            # Generate authorization URL
            authorization_url = provider.authorize_redirect(redirect_uri, state=state)
            
            logger.info(
                f"Generated authorization URL for {provider_name}",
                extra={'provider': provider_name}
            )
            
            return authorization_url, state
            
        except OAuth2Error:
            # Re-raise OAuth2Error as-is
            raise
        except Exception as e:
            logger.error(
                f"Failed to create authorization URL for {provider_name}: {str(e)}",
                extra={'provider': provider_name, 'error': str(e)}
            )
            raise OAuth2Error(
                message="Failed to initiate authentication. Please try again.",
                code="AUTH_URL_GENERATION_ERROR",
                details=str(e)
            )
    
    def validate_state(self, state: str) -> bool:
        """
        Validate OAuth2 state parameter to prevent CSRF attacks.
        
        Args:
            state: State parameter from OAuth2 callback
            
        Returns:
            True if state is valid, False otherwise
            
        Requirements: 1.2, 1.4
        """
        stored_state = session.get('oauth2_state')
        
        if not stored_state:
            logger.warning("State validation failed: no stored state in session")
            return False
        
        if not state:
            logger.warning("State validation failed: no state parameter provided")
            return False
        
        # Constant-time comparison to prevent timing attacks
        is_valid = secrets.compare_digest(stored_state, state)
        
        if not is_valid:
            logger.warning(
                "State validation failed: state mismatch",
                extra={'stored_state_length': len(stored_state), 'provided_state_length': len(state)}
            )
        
        return is_valid
    
    def exchange_code_for_token(self, provider_name: str, authorization_response: str) -> dict:
        """
        Exchange authorization code for access token.
        
        Args:
            provider_name: Name of the provider
            authorization_response: Full callback URL with code parameter
            
        Returns:
            Token dictionary containing access_token and other metadata
            
        Raises:
            OAuth2Error: If provider is not configured or token exchange fails
            
        Requirements: 1.2, 1.4
        """
        try:
            provider = self.get_provider(provider_name)
            
            # Exchange code for token
            token = provider.authorize_access_token()
            
            logger.info(
                f"Successfully exchanged authorization code for token with {provider_name}",
                extra={'provider': provider_name}
            )
            
            return token
            
        except OAuth2Error:
            # Re-raise OAuth2Error as-is
            raise
        except OAuthError as e:
            logger.error(
                f"OAuth error during token exchange with {provider_name}: {e.error} - {e.description}",
                extra={'provider': provider_name, 'error': e.error, 'description': e.description}
            )
            
            # Provide user-friendly error messages based on error type
            if e.error == 'access_denied':
                raise OAuth2Error(
                    message="Authentication was cancelled. Please try again if you want to log in.",
                    code="AUTH_CANCELLED",
                    details=e.description
                )
            elif e.error == 'invalid_grant':
                raise OAuth2Error(
                    message="Authentication failed. The authorization code may have expired. Please try again.",
                    code="INVALID_GRANT",
                    details=e.description
                )
            else:
                raise OAuth2Error(
                    message=f"Authentication failed: {e.description or 'Unable to complete authentication'}",
                    code="TOKEN_EXCHANGE_ERROR",
                    details=f"{e.error}: {e.description}"
                )
        except Exception as e:
            logger.error(
                f"Unexpected error during token exchange with {provider_name}: {str(e)}",
                extra={'provider': provider_name, 'error': str(e)}
            )
            raise OAuth2Error(
                message="An unexpected error occurred during authentication. Please try again.",
                code="TOKEN_EXCHANGE_ERROR",
                details=str(e)
            )
    
    def get_user_info(self, provider_name: str, token: dict) -> dict:
        """
        Retrieve user information from OAuth2 provider.
        
        Args:
            provider_name: Name of the provider
            token: Access token dictionary
            
        Returns:
            Dictionary containing user information (id, email, name, etc.)
            
        Raises:
            OAuth2Error: If provider is not configured or user info retrieval fails
            
        Requirements: 1.3, 1.4
        """
        try:
            provider = self.get_provider(provider_name)
            
            logger.debug(
                f"Retrieving user info from {provider_name}",
                extra={'provider': provider_name}
            )
            # Get user info from provider
            if provider_name == 'google':
                resp = provider.get('https://www.googleapis.com/oauth2/v2/userinfo', token=token)
                user_info = resp.json()
                return {
                    'id': user_info.get('id'),
                    'email': user_info.get('email'),
                    'name': user_info.get('name'),
                    'picture': user_info.get('picture'),
                    'provider': provider_name
                }
            
            elif provider_name == 'github':
                resp = provider.get('user', token=token)
                user_info = resp.json()
                
                # GitHub may not return email in main response, fetch separately
                email = user_info.get('email')
                if not email:
                    email_resp = provider.get('user/emails', token=token)
                    emails = email_resp.json()
                    # Get primary email
                    for email_obj in emails:
                        if email_obj.get('primary'):
                            email = email_obj.get('email')
                            break
                    if not email and emails:
                        email = emails[0].get('email')
                
                return {
                    'id': str(user_info.get('id')),
                    'email': email,
                    'name': user_info.get('name') or user_info.get('login'),
                    'picture': user_info.get('avatar_url'),
                    'provider': provider_name
                }
            
            elif provider_name == 'facebook':
                resp = provider.get('me?fields=id,name,email', token=token)
                user_info = resp.json()
                return {
                    'id': user_info.get('id'),
                    'email': user_info.get('email'),
                    'name': user_info.get('name'),
                    'picture': f"https://graph.facebook.com/{user_info.get('id')}/picture?type=large",
                    'provider': provider_name
                }
            
            elif provider_name == 'linkedin':
                # LinkedIn v2 API requires two separate calls
                resp = provider.get('v2/me', token=token)
                user_info = resp.json()
                
                # Get email separately
                email_resp = provider.get('v2/emailAddress?q=members&projection=(elements*(handle~))', token=token)
                email_data = email_resp.json()
                email = None
                if 'elements' in email_data and email_data['elements']:
                    email = email_data['elements'][0].get('handle~', {}).get('emailAddress')
                
                # Construct name from localized fields
                first_name = user_info.get('localizedFirstName', '')
                last_name = user_info.get('localizedLastName', '')
                name = f"{first_name} {last_name}".strip()
                
                return {
                    'id': user_info.get('id'),
                    'email': email,
                    'name': name,
                    'picture': None,  # LinkedIn profile pictures require additional permissions
                    'provider': provider_name
                }
            
            elif provider_name == 'auth0':
                resp = provider.get('userinfo', token=token)
                user_info = resp.json()
                return {
                    'id': user_info.get('sub'),
                    'email': user_info.get('email'),
                    'name': user_info.get('name'),
                    'picture': user_info.get('picture'),
                    'provider': provider_name
                }
            
            else:
                logger.error(f"Unsupported provider: {provider_name}")
                raise OAuth2Error(
                    message=f"Provider '{provider_name}' is not supported",
                    code="UNSUPPORTED_PROVIDER",
                    details=f"Provider '{provider_name}' is not implemented"
                )
            
            logger.info(
                f"Successfully retrieved user info from {provider_name}",
                extra={
                    'provider': provider_name,
                    'user_id': user_info.get('id'),
                    'has_email': bool(user_info.get('email'))
                }
            )
            
            return user_info
                
        except OAuth2Error:
            # Re-raise OAuth2Error as-is
            raise
        except OAuthError as e:
            logger.error(
                f"OAuth error retrieving user info from {provider_name}: {str(e)}",
                extra={'provider': provider_name, 'error': e.error}
            )
            raise OAuth2Error(
                message="Failed to retrieve your profile information. Please try again.",
                code="USER_INFO_ERROR",
                details=f"{e.error}: {e.description}"
            )
        except Exception as e:
            logger.error(
                f"Unexpected error retrieving user info from {provider_name}: {str(e)}",
                extra={'provider': provider_name, 'error': str(e)}
            )
            raise OAuth2Error(
                message="Failed to retrieve your profile information. Please try again.",
                code="USER_INFO_ERROR",
                details=str(e)
            )
    
    def clear_session_state(self) -> None:
        """
        Clear OAuth2-related session data.
        Should be called after successful authentication or on error.
        Requirements: 1.4
        """
        session.pop('oauth2_state', None)
        session.pop('oauth2_provider', None)
        logger.debug("Cleared OAuth2 session state")
