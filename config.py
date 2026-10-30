"""
Centralized configuration management for Flask Chatbot MCP application.
Loads and validates environment variables at startup.
Requirements: 6.1, 6.3, 6.5
"""

import os
import sys
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


class Config:
    """Application configuration with validation."""
    
    # Flask Configuration
    FLASK_ENV: str = os.getenv('FLASK_ENV', 'production')
    SECRET_KEY: str = os.getenv('SECRET_KEY', '')
    
    # LLM Service Configuration
    LLM_API_KEY: str = os.getenv('LLM_API_KEY', '')
    LLM_MODEL: str = os.getenv('LLM_MODEL', 'gpt-4')
    LLM_API_BASE_URL: str = os.getenv('LLM_API_BASE_URL', 'https://api.openai.com/v1')
    LLM_MAX_TOKENS: int = int(os.getenv('LLM_MAX_TOKENS', '1000'))
    LLM_TEMPERATURE: float = float(os.getenv('LLM_TEMPERATURE', '0.7'))
    LLM_TIMEOUT: int = int(os.getenv('LLM_TIMEOUT', '30'))
    LLM_MAX_RETRIES: int = int(os.getenv('LLM_MAX_RETRIES', '3'))
    
    # Oracle Database Configuration
    ORACLE_CONNECTION_STRING: str = os.getenv('ORACLE_CONNECTION_STRING', '')
    ORACLE_USER: str = os.getenv('ORACLE_USER', '')
    ORACLE_PASSWORD: str = os.getenv('ORACLE_PASSWORD', '')
    ORACLE_ALLOWED_VIEWS: List[str] = os.getenv('ORACLE_ALLOWED_VIEWS', '').split(',') if os.getenv('ORACLE_ALLOWED_VIEWS') else []
    
    # PDF Connector Configuration
    PDF_STORAGE_PATH: str = os.getenv('PDF_STORAGE_PATH', './pdfs')
    PDF_INDEX_FILE: str = os.getenv('PDF_INDEX_FILE', './pdf_index.json')
    PDF_INDEX_REFRESH_INTERVAL: int = int(os.getenv('PDF_INDEX_REFRESH_INTERVAL', '3600'))
    PDF_MAX_SEARCH_RESULTS: int = int(os.getenv('PDF_MAX_SEARCH_RESULTS', '10'))
    
    # MCP Server Configuration (if deployed separately)
    MCP_ORACLE_ENDPOINT: Optional[str] = os.getenv('MCP_ORACLE_ENDPOINT')
    MCP_PDF_ENDPOINT: Optional[str] = os.getenv('MCP_PDF_ENDPOINT')
    
    # Application Settings
    SESSION_TIMEOUT: int = int(os.getenv('SESSION_TIMEOUT', '1800'))
    MAX_CONVERSATION_HISTORY: int = int(os.getenv('MAX_CONVERSATION_HISTORY', '50'))
    QUERY_TIMEOUT: int = int(os.getenv('QUERY_TIMEOUT', '5'))
    MAX_RESULT_SIZE: int = int(os.getenv('MAX_RESULT_SIZE', '1000'))
    
    # Logging Configuration
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: str = os.getenv('LOG_FILE', './logs/chatbot.log')
    LOG_JSON: bool = os.getenv('LOG_JSON', 'false').lower() == 'true'
    
    # Serverless Optimization
    CONNECTION_CACHE_TTL: int = int(os.getenv('CONNECTION_CACHE_TTL', '300'))
    INIT_CACHE_TTL: int = int(os.getenv('INIT_CACHE_TTL', '300'))
    ENABLE_LAZY_LOADING: bool = os.getenv('ENABLE_LAZY_LOADING', 'true').lower() == 'true'
    
    # OAuth2 Configuration
    OAUTH2_ENABLED: bool = os.getenv('OAUTH2_ENABLED', 'false').lower() == 'true'
    OAUTH2_DEFAULT_PROVIDER: str = os.getenv('OAUTH2_DEFAULT_PROVIDER', 'google')
    OAUTH2_CALLBACK_URL_BASE: str = os.getenv('OAUTH2_CALLBACK_URL_BASE', 'http://localhost:5000')
    OAUTH2_TOKEN_EXPIRATION: int = int(os.getenv('OAUTH2_TOKEN_EXPIRATION', '3600'))
    
    # OAuth2 Provider Credentials - Google
    GOOGLE_CLIENT_ID: str = os.getenv('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET: str = os.getenv('GOOGLE_CLIENT_SECRET', '')
    
    # OAuth2 Provider Credentials - GitHub
    GITHUB_CLIENT_ID: str = os.getenv('GITHUB_CLIENT_ID', '')
    GITHUB_CLIENT_SECRET: str = os.getenv('GITHUB_CLIENT_SECRET', '')
    
    # OAuth2 Provider Credentials - Facebook
    FACEBOOK_CLIENT_ID: str = os.getenv('FACEBOOK_CLIENT_ID', '')
    FACEBOOK_CLIENT_SECRET: str = os.getenv('FACEBOOK_CLIENT_SECRET', '')
    
    # OAuth2 Provider Credentials - LinkedIn
    LINKEDIN_CLIENT_ID: str = os.getenv('LINKEDIN_CLIENT_ID', '')
    LINKEDIN_CLIENT_SECRET: str = os.getenv('LINKEDIN_CLIENT_SECRET', '')
    
    # OAuth2 Provider Credentials - Auth0
    AUTH0_CLIENT_ID: str = os.getenv('AUTH0_CLIENT_ID', '')
    AUTH0_CLIENT_SECRET: str = os.getenv('AUTH0_CLIENT_SECRET', '')
    AUTH0_DOMAIN: str = os.getenv('AUTH0_DOMAIN', '')
    
    # Stripe Billing Configuration
    STRIPE_SECRET_KEY: str = os.getenv('STRIPE_SECRET_KEY', '')
    STRIPE_PRO_PRICE_ID: str = os.getenv('STRIPE_PRO_PRICE_ID', '')
    STRIPE_WEBHOOK_SECRET: str = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    STRIPE_TEST_MODE: bool = os.getenv('STRIPE_SECRET_KEY', '').startswith('sk_test_')
    
    @classmethod
    def validate(cls) -> None:
        """
        Validate that all required environment variables are present and valid.
        Raises ConfigurationError if validation fails.
        Requirements: 6.1, 6.3, 6.5
        """
        errors = []
        
        # Validate Flask configuration
        if not cls.SECRET_KEY:
            errors.append("SECRET_KEY is required for session management")
        elif len(cls.SECRET_KEY) < 16:
            errors.append("SECRET_KEY must be at least 16 characters long")
        
        # Validate LLM configuration
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY is required for AI functionality")
        
        if not cls.LLM_MODEL:
            errors.append("LLM_MODEL is required")
        
        if cls.LLM_MAX_TOKENS <= 0:
            errors.append("LLM_MAX_TOKENS must be greater than 0")
        
        if not (0 <= cls.LLM_TEMPERATURE <= 2):
            errors.append("LLM_TEMPERATURE must be between 0 and 2")
        
        # Validate Oracle configuration (if Oracle views are specified)
        if cls.ORACLE_ALLOWED_VIEWS:
            if not cls.ORACLE_CONNECTION_STRING:
                errors.append("ORACLE_CONNECTION_STRING is required when ORACLE_ALLOWED_VIEWS is specified")
            
            if not cls.ORACLE_USER:
                errors.append("ORACLE_USER is required when ORACLE_ALLOWED_VIEWS is specified")
            
            if not cls.ORACLE_PASSWORD:
                errors.append("ORACLE_PASSWORD is required when ORACLE_ALLOWED_VIEWS is specified")
        
        # Validate PDF configuration
        if not cls.PDF_STORAGE_PATH:
            errors.append("PDF_STORAGE_PATH is required")
        
        # Validate application settings
        if cls.SESSION_TIMEOUT <= 0:
            errors.append("SESSION_TIMEOUT must be greater than 0")
        
        if cls.MAX_CONVERSATION_HISTORY <= 0:
            errors.append("MAX_CONVERSATION_HISTORY must be greater than 0")
        
        if cls.QUERY_TIMEOUT <= 0:
            errors.append("QUERY_TIMEOUT must be greater than 0")
        
        # Validate log level
        valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if cls.LOG_LEVEL.upper() not in valid_log_levels:
            errors.append(f"LOG_LEVEL must be one of: {', '.join(valid_log_levels)}")
        
        # Validate OAuth2 configuration (if enabled)
        if cls.OAUTH2_ENABLED:
            # Check that at least one provider is configured
            providers_configured = []
            
            if cls.GOOGLE_CLIENT_ID and cls.GOOGLE_CLIENT_SECRET:
                providers_configured.append('google')
            
            if cls.GITHUB_CLIENT_ID and cls.GITHUB_CLIENT_SECRET:
                providers_configured.append('github')
            
            if cls.FACEBOOK_CLIENT_ID and cls.FACEBOOK_CLIENT_SECRET:
                providers_configured.append('facebook')
            
            if cls.LINKEDIN_CLIENT_ID and cls.LINKEDIN_CLIENT_SECRET:
                providers_configured.append('linkedin')
            
            if cls.AUTH0_CLIENT_ID and cls.AUTH0_CLIENT_SECRET and cls.AUTH0_DOMAIN:
                providers_configured.append('auth0')
            
            if not providers_configured:
                errors.append("OAuth2 is enabled but no providers are configured. At least one provider (Google, GitHub, Facebook, LinkedIn, or Auth0) must have client_id and client_secret set")
            
            # Validate default provider is configured
            if cls.OAUTH2_DEFAULT_PROVIDER not in providers_configured:
                if providers_configured:
                    errors.append(f"OAUTH2_DEFAULT_PROVIDER '{cls.OAUTH2_DEFAULT_PROVIDER}' is not configured. Available providers: {', '.join(providers_configured)}")
                else:
                    errors.append(f"OAUTH2_DEFAULT_PROVIDER '{cls.OAUTH2_DEFAULT_PROVIDER}' is set but no providers are configured")
            
            # Validate callback URL
            if not cls.OAUTH2_CALLBACK_URL_BASE:
                errors.append("OAUTH2_CALLBACK_URL_BASE is required when OAuth2 is enabled")
            
            # Validate token expiration
            if cls.OAUTH2_TOKEN_EXPIRATION <= 0:
                errors.append("OAUTH2_TOKEN_EXPIRATION must be greater than 0")
        
        # If there are validation errors, raise exception
        if errors:
            error_message = "Configuration validation failed:\n" + "\n".join(f"  - {error}" for error in errors)
            raise ConfigurationError(error_message)
    
    @classmethod
    def get_safe_config(cls) -> dict:
        """
        Return configuration dictionary with sensitive values masked.
        Used for logging and debugging without exposing credentials.
        Requirements: 6.2, 6.5
        """
        def mask_value(value: str, show_chars: int = 4) -> str:
            """Mask sensitive string values."""
            if not value or len(value) <= show_chars:
                return "***"
            return value[:show_chars] + "***"
        
        return {
            'FLASK_ENV': cls.FLASK_ENV,
            'SECRET_KEY': mask_value(cls.SECRET_KEY),
            'LLM_API_KEY': mask_value(cls.LLM_API_KEY),
            'LLM_MODEL': cls.LLM_MODEL,
            'LLM_API_BASE_URL': cls.LLM_API_BASE_URL,
            'LLM_MAX_TOKENS': cls.LLM_MAX_TOKENS,
            'LLM_TEMPERATURE': cls.LLM_TEMPERATURE,
            'ORACLE_CONNECTION_STRING': mask_value(cls.ORACLE_CONNECTION_STRING) if cls.ORACLE_CONNECTION_STRING else None,
            'ORACLE_USER': mask_value(cls.ORACLE_USER) if cls.ORACLE_USER else None,
            'ORACLE_PASSWORD': '***' if cls.ORACLE_PASSWORD else None,
            'ORACLE_ALLOWED_VIEWS': cls.ORACLE_ALLOWED_VIEWS,
            'PDF_STORAGE_PATH': cls.PDF_STORAGE_PATH,
            'PDF_INDEX_FILE': cls.PDF_INDEX_FILE,
            'SESSION_TIMEOUT': cls.SESSION_TIMEOUT,
            'MAX_CONVERSATION_HISTORY': cls.MAX_CONVERSATION_HISTORY,
            'LOG_LEVEL': cls.LOG_LEVEL,
            'OAUTH2_ENABLED': cls.OAUTH2_ENABLED,
            'OAUTH2_DEFAULT_PROVIDER': cls.OAUTH2_DEFAULT_PROVIDER,
            'OAUTH2_CALLBACK_URL_BASE': cls.OAUTH2_CALLBACK_URL_BASE,
            'OAUTH2_TOKEN_EXPIRATION': cls.OAUTH2_TOKEN_EXPIRATION,
            'GOOGLE_CLIENT_ID': mask_value(cls.GOOGLE_CLIENT_ID) if cls.GOOGLE_CLIENT_ID else None,
            'GOOGLE_CLIENT_SECRET': '***' if cls.GOOGLE_CLIENT_SECRET else None,
            'GITHUB_CLIENT_ID': mask_value(cls.GITHUB_CLIENT_ID) if cls.GITHUB_CLIENT_ID else None,
            'GITHUB_CLIENT_SECRET': '***' if cls.GITHUB_CLIENT_SECRET else None,
            'FACEBOOK_CLIENT_ID': mask_value(cls.FACEBOOK_CLIENT_ID) if cls.FACEBOOK_CLIENT_ID else None,
            'FACEBOOK_CLIENT_SECRET': '***' if cls.FACEBOOK_CLIENT_SECRET else None,
            'LINKEDIN_CLIENT_ID': mask_value(cls.LINKEDIN_CLIENT_ID) if cls.LINKEDIN_CLIENT_ID else None,
            'LINKEDIN_CLIENT_SECRET': '***' if cls.LINKEDIN_CLIENT_SECRET else None,
            'AUTH0_CLIENT_ID': mask_value(cls.AUTH0_CLIENT_ID) if cls.AUTH0_CLIENT_ID else None,
            'AUTH0_CLIENT_SECRET': '***' if cls.AUTH0_CLIENT_SECRET else None,
            'AUTH0_DOMAIN': cls.AUTH0_DOMAIN if cls.AUTH0_DOMAIN else None,
            'CONFIGURED_OAUTH2_PROVIDERS': cls.get_configured_oauth2_providers(),
        }
    
    @classmethod
    def is_oracle_enabled(cls) -> bool:
        """Check if Oracle database integration is enabled."""
        return bool(cls.ORACLE_ALLOWED_VIEWS and cls.ORACLE_CONNECTION_STRING)
    
    @classmethod
    def is_pdf_enabled(cls) -> bool:
        """Check if PDF connector is enabled."""
        return bool(cls.PDF_STORAGE_PATH)
    
    @classmethod
    def is_oauth2_enabled(cls) -> bool:
        """Check if OAuth2 authentication is enabled."""
        return cls.OAUTH2_ENABLED
    
    @classmethod
    def get_configured_oauth2_providers(cls) -> List[str]:
        """Get list of configured OAuth2 providers."""
        providers = []
        
        if cls.GOOGLE_CLIENT_ID and cls.GOOGLE_CLIENT_SECRET:
            providers.append('google')
        
        if cls.GITHUB_CLIENT_ID and cls.GITHUB_CLIENT_SECRET:
            providers.append('github')
        
        if cls.FACEBOOK_CLIENT_ID and cls.FACEBOOK_CLIENT_SECRET:
            providers.append('facebook')
        
        if cls.LINKEDIN_CLIENT_ID and cls.LINKEDIN_CLIENT_SECRET:
            providers.append('linkedin')
        
        if cls.AUTH0_CLIENT_ID and cls.AUTH0_CLIENT_SECRET and cls.AUTH0_DOMAIN:
            providers.append('auth0')
        
        return providers


class MetadataConfig:
    """
    Application metadata for branding and social sharing.
    Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
    """
    
    # Application branding
    APP_NAME: str = os.getenv('APP_NAME', 'Chatbot Assistant')
    APP_DESCRIPTION: str = os.getenv('APP_DESCRIPTION', 'AI-powered chatbot with MCP integration for Oracle APEX and PDF documents')
    APP_URL: str = os.getenv('APP_URL', 'http://localhost:5000')
    APP_TAGLINE: str = os.getenv('APP_TAGLINE', 'Ask questions about your data')
    
    # Social media metadata
    OG_IMAGE: str = os.getenv('OG_IMAGE', '/static/images/og-image.png')
    OG_IMAGE_WIDTH: int = int(os.getenv('OG_IMAGE_WIDTH', '1200'))
    OG_IMAGE_HEIGHT: int = int(os.getenv('OG_IMAGE_HEIGHT', '630'))
    OG_TYPE: str = os.getenv('OG_TYPE', 'website')
    
    TWITTER_CARD_TYPE: str = os.getenv('TWITTER_CARD_TYPE', 'summary_large_image')
    TWITTER_SITE: str = os.getenv('TWITTER_SITE', '')
    TWITTER_CREATOR: str = os.getenv('TWITTER_CREATOR', '')
    TWITTER_IMAGE: str = os.getenv('TWITTER_IMAGE', '/static/images/twitter-card.png')
    
    # Favicon paths
    FAVICON_SVG: str = os.getenv('FAVICON_SVG', '/static/images/favicon.svg')
    FAVICON_ICO: str = os.getenv('FAVICON_ICO', '/static/images/favicon.ico')
    FAVICON_16: str = os.getenv('FAVICON_16', '/static/images/favicon-16x16.png')
    FAVICON_32: str = os.getenv('FAVICON_32', '/static/images/favicon-32x32.png')
    APPLE_TOUCH_ICON: str = os.getenv('APPLE_TOUCH_ICON', '/static/images/apple-touch-icon.png')
    
    # Application logo
    LOGO_PATH: str = os.getenv('LOGO_PATH', '/static/images/logo.png')
    
    # Theme colors
    THEME_COLOR: str = os.getenv('THEME_COLOR', '#667eea')
    BACKGROUND_COLOR: str = os.getenv('BACKGROUND_COLOR', '#ffffff')
    
    @classmethod
    def validate(cls) -> None:
        """
        Validate metadata configuration.
        Requirements: 7.5
        """
        errors = []
        
        # Validate required fields
        if not cls.APP_NAME:
            errors.append("APP_NAME is required for metadata")
        
        if not cls.APP_DESCRIPTION:
            errors.append("APP_DESCRIPTION is required for metadata")
        
        if not cls.APP_URL:
            errors.append("APP_URL is required for metadata")
        
        # Validate URL format
        if cls.APP_URL and not (cls.APP_URL.startswith('http://') or cls.APP_URL.startswith('https://')):
            errors.append("APP_URL must start with http:// or https://")
        
        # Validate image dimensions
        if cls.OG_IMAGE_WIDTH <= 0:
            errors.append("OG_IMAGE_WIDTH must be greater than 0")
        
        if cls.OG_IMAGE_HEIGHT <= 0:
            errors.append("OG_IMAGE_HEIGHT must be greater than 0")
        
        # Validate Twitter card type
        valid_twitter_card_types = ['summary', 'summary_large_image', 'app', 'player']
        if cls.TWITTER_CARD_TYPE not in valid_twitter_card_types:
            errors.append(f"TWITTER_CARD_TYPE must be one of: {', '.join(valid_twitter_card_types)}")
        
        # Validate OG type
        valid_og_types = ['website', 'article', 'profile', 'video', 'music', 'book']
        if cls.OG_TYPE not in valid_og_types:
            errors.append(f"OG_TYPE must be one of: {', '.join(valid_og_types)}")
        
        # Validate theme color format (should be hex color)
        if cls.THEME_COLOR and not cls.THEME_COLOR.startswith('#'):
            errors.append("THEME_COLOR must be a hex color starting with #")
        
        if cls.BACKGROUND_COLOR and not cls.BACKGROUND_COLOR.startswith('#'):
            errors.append("BACKGROUND_COLOR must be a hex color starting with #")
        
        if errors:
            error_message = "Metadata configuration validation failed:\n" + "\n".join(f"  - {error}" for error in errors)
            raise ConfigurationError(error_message)
    
    @classmethod
    def get_full_image_url(cls, image_path: str) -> str:
        """
        Get full URL for an image path.
        Converts relative paths to absolute URLs for social media.
        """
        if image_path.startswith('http://') or image_path.startswith('https://'):
            return image_path
        return cls.APP_URL.rstrip('/') + image_path
    
    @classmethod
    def to_dict(cls) -> dict:
        """
        Return metadata as dictionary for template rendering.
        """
        return {
            'app_name': cls.APP_NAME,
            'app_description': cls.APP_DESCRIPTION,
            'app_url': cls.APP_URL,
            'app_tagline': cls.APP_TAGLINE,
            'og_image': cls.get_full_image_url(cls.OG_IMAGE),
            'og_image_width': cls.OG_IMAGE_WIDTH,
            'og_image_height': cls.OG_IMAGE_HEIGHT,
            'og_type': cls.OG_TYPE,
            'twitter_card_type': cls.TWITTER_CARD_TYPE,
            'twitter_site': cls.TWITTER_SITE,
            'twitter_creator': cls.TWITTER_CREATOR,
            'twitter_image': cls.get_full_image_url(cls.TWITTER_IMAGE),
            'favicon_svg': cls.FAVICON_SVG,
            'favicon_ico': cls.FAVICON_ICO,
            'favicon_16': cls.FAVICON_16,
            'favicon_32': cls.FAVICON_32,
            'apple_touch_icon': cls.APPLE_TOUCH_ICON,
            'logo_path': cls.LOGO_PATH,
            'theme_color': cls.THEME_COLOR,
            'background_color': cls.BACKGROUND_COLOR,
        }


def validate_config_on_startup() -> None:
    """
    Validate configuration at application startup.
    Call this function early in the application initialization.
    Requirements: 6.3, 7.5
    """
    try:
        Config.validate()
        print("✓ Configuration validation successful")
        
        # Validate metadata configuration
        MetadataConfig.validate()
        print("✓ Metadata configuration validation successful")
    except ConfigurationError as e:
        print(f"✗ Configuration Error:\n{e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error during configuration validation: {e}", file=sys.stderr)
        sys.exit(1)


# Export the Config class
__all__ = ['Config', 'MetadataConfig', 'ConfigurationError', 'validate_config_on_startup']
