"""
Flask Chatbot Application with MCP Integration
Main application file with routes and configuration
"""

import os
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from flask import Flask, request, jsonify, session, render_template, g, redirect, url_for
from dotenv import load_dotenv
from config import Config, MetadataConfig, validate_config_on_startup
from modules.session_manager import SessionManager
from modules.mcp_client import create_mcp_client_from_env
from modules.llm_service import create_llm_service_from_env
from modules.apex_rest_handler import ApexRestHandler, register_apex_routes
from modules.oracle_mcp_server import OracleMCPServer
from modules.pdf_mcp_server import PDFMCPServer
from modules.yugabyte_mcp_server import YugabyteMCPServer
from modules.logging_config import configure_from_env, RequestLoggingContext, get_logger
from modules.error_handler import (
    format_error_response, get_user_friendly_message,
    ChatbotError, log_error_with_context
)
from modules.oauth2_manager import OAuth2Manager
from modules.auth_decorator import require_auth, require_api_auth
from modules.activity_tracker import get_activity_tracker

# Load environment variables
load_dotenv()

# Validate configuration at startup (Requirements: 6.1, 6.3, 6.5)
validate_config_on_startup()

# Configure logging from environment
configure_from_env()
logger = get_logger(__name__)

# Log safe configuration for debugging
logger.info("Application configuration loaded", extra={'config': Config.get_safe_config()})

# Initialize Flask application
app = Flask(__name__)

# Initialize session manager
session_manager = SessionManager()

# Initialize OAuth2 manager
oauth2_manager = None

# Initialize MCP client and LLM service (module-level caching)
# These are module-level variables for connection caching across invocations
mcp_client = None
llm_service = None
oracle_server = None
pdf_server = None
yugabyte_server = None
apex_handler = None

# Cache for initialization status to avoid repeated attempts
_initialization_attempted = False
_initialization_timestamp = None
_services_initialized = False

# Initialization timing metrics
_init_metrics = {
    'total_time': 0.0,
    'llm_service_time': 0.0,
    'oracle_server_time': 0.0,
    'pdf_server_time': 0.0,
    'yugabyte_server_time': 0.0,
    'mcp_client_time': 0.0,
    'apex_handler_time': 0.0,
    'cold_start': True,
    'initialization_count': 0
}

# Configuration using centralized Config class (Requirements: 6.1, 6.3)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_COOKIE_SECURE'] = Config.FLASK_ENV == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=Config.SESSION_TIMEOUT)

# Initialize OAuth2 manager after app configuration
try:
    oauth2_manager = OAuth2Manager(app)
    logger.info("OAuth2 manager initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OAuth2 manager: {str(e)}", exc_info=True)
    # Set to None so we can check if it's available
    oauth2_manager = None

# Initialize activity tracker
try:
    activity_tracker = get_activity_tracker()
    logger.info("Activity tracker initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize activity tracker: {str(e)}", exc_info=True)
    activity_tracker = None


def initialize_services():
    """
    Initialize MCP client, LLM service, and APEX handlers with caching
    Uses module-level caching to avoid re-initialization on every request
    Tracks timing metrics for performance monitoring
    Requirements: 2.4, 2.5
    """
    global mcp_client, llm_service, oracle_server, pdf_server, yugabyte_server, apex_handler
    global _initialization_attempted, _initialization_timestamp, _services_initialized
    global _init_metrics
    
    # If services are already initialized, return immediately (warm start)
    if _services_initialized:
        logger.debug("Services already initialized (warm start), skipping")
        _init_metrics['cold_start'] = False
        return
    
    # Track if this is a cold start
    is_cold_start = _init_metrics['initialization_count'] == 0
    _init_metrics['cold_start'] = is_cold_start
    _init_metrics['initialization_count'] += 1
    
    logger.info(f"Initializing services ({'cold start' if is_cold_start else 'warm start'})...")
    total_start = time.time()
    current_time = time.time()
    
    # Initialize LLM service first (critical dependency)
    if llm_service is None:
        try:
            llm_start = time.time()
            logger.info("Initializing LLM service")
            llm_service = create_llm_service_from_env()
            llm_elapsed = time.time() - llm_start
            _init_metrics['llm_service_time'] = llm_elapsed
            logger.info(f"LLM service initialized in {llm_elapsed:.3f}s")
            # Mark initialization as successful
            _initialization_attempted = True
            _initialization_timestamp = current_time
        except Exception as e:
            logger.error(f"Failed to initialize LLM service: {str(e)}")
            # Reset cache flags so we can retry
            _initialization_attempted = False
            _initialization_timestamp = None
            raise  # LLM service is critical
    
    # Initialize Oracle MCP Server (optional) using Config
    if oracle_server is None and Config.is_oracle_enabled():
        try:
            oracle_start = time.time()
            logger.info("Initializing Oracle MCP Server")
            oracle_server = OracleMCPServer()
            oracle_elapsed = time.time() - oracle_start
            _init_metrics['oracle_server_time'] = oracle_elapsed
            logger.info(f"Oracle MCP Server initialized in {oracle_elapsed:.3f}s")
        except Exception as e:
            logger.warning(f"Oracle MCP Server not available: {str(e)}")

    # Initialize YugabyteDB MCP Server (optional)
    if yugabyte_server is None and os.getenv('YUGABYTE_HOST'):
        try:
            yb_start = time.time()
            logger.info("Initializing YugabyteDB MCP Server")
            yugabyte_server = YugabyteMCPServer()
            yb_elapsed = time.time() - yb_start
            _init_metrics['yugabyte_server_time'] = yb_elapsed
            logger.info(f"YugabyteDB MCP Server initialized in {yb_elapsed:.3f}s")
        except Exception as e:
            logger.warning(f"YugabyteDB MCP Server not available: {str(e)}")

    # Initialize PDF MCP Server
    if pdf_server is None:
        try:
            pdf_start = time.time()
            logger.info("Initializing PDF MCP Server")
            pdf_server = PDFMCPServer()
            pdf_elapsed = time.time() - pdf_start
            _init_metrics['pdf_server_time'] = pdf_elapsed
            logger.info(f"PDF MCP Server initialized in {pdf_elapsed:.3f}s")
        except Exception as e:
            logger.error(f"Failed to initialize PDF MCP Server: {str(e)}")
    
    # Initialize MCP client (skip connection attempts to avoid lag)
    if mcp_client is None:
        try:
            mcp_start = time.time()
            logger.info("Initializing MCP client (without server connections)")
            mcp_client = create_mcp_client_from_env()
            # Skip connect_servers() to avoid connection retry delays
            # Servers will connect on-demand when tools are actually used
            mcp_elapsed = time.time() - mcp_start
            _init_metrics['mcp_client_time'] = mcp_elapsed
            logger.info(f"MCP client initialized in {mcp_elapsed:.3f}s (lazy connection mode)")
        except Exception as e:
            logger.error(f"Failed to initialize MCP client: {str(e)}")
            # Continue without MCP client - will work in degraded mode
    
    # Initialize APEX REST handler
    if apex_handler is None and llm_service is not None:
        try:
            apex_start = time.time()
            logger.info("Initializing APEX REST handler")
            apex_handler = ApexRestHandler(oracle_server, pdf_server, llm_service, yugabyte_server)
            apex_elapsed = time.time() - apex_start
            _init_metrics['apex_handler_time'] = apex_elapsed
            logger.info(f"APEX REST handler initialized in {apex_elapsed:.3f}s")
        except Exception as e:
            logger.error(f"Failed to initialize APEX REST handler: {str(e)}")
    
    # Calculate total initialization time
    total_elapsed = time.time() - total_start
    _init_metrics['total_time'] = total_elapsed
    
    # Mark services as fully initialized
    _services_initialized = True
    
    # Log detailed metrics
    logger.info(
        f"All services initialized successfully in {total_elapsed:.3f}s "
        f"({'cold start' if is_cold_start else 'warm start'})",
        extra={
            'initialization_metrics': _init_metrics,
            'cold_start': is_cold_start
        }
    )


def warmup_services():
    """
    Warmup function to pre-initialize all services at application startup
    This reduces cold start latency by initializing services before first request
    Requirements: 2.4
    """
    logger.info("Starting service warmup...")
    start_time = time.time()
    
    try:
        initialize_services()
        elapsed = time.time() - start_time
        logger.info(
            f"Service warmup completed in {elapsed:.3f}s",
            extra={'warmup_time': elapsed, 'metrics': _init_metrics}
        )
        return True
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"Service warmup failed after {elapsed:.3f}s: {str(e)}",
            extra={'warmup_time': elapsed, 'error': str(e)}
        )
        return False


def get_initialization_metrics():
    """
    Get initialization timing metrics for monitoring and debugging
    
    Returns:
        Dictionary containing initialization metrics
    """
    return {
        **_init_metrics,
        'services_initialized': _services_initialized,
        'initialization_timestamp': _initialization_timestamp
    }


@app.before_request
def before_request():
    """
    Setup request context and logging before each request
    Requirements: 1.5, 6.3, 6.2
    """
    # Store request start time for duration tracking
    g.start_time = time.time()
    
    # Generate request ID for tracking
    import uuid
    g.request_id = str(uuid.uuid4())
    
    # Skip session check for static files and health endpoint
    if request.path.startswith('/static/') or request.path == '/api/health':
        return
    
    # Check if session exists and is expired
    if 'session_id' in session and not session_manager.is_session_valid():
        logger.info(f"Session {session['session_id']} expired, cleaning up")
        session_manager.cleanup_session()


@app.after_request
def after_request(response):
    """
    Log request/response information after each request
    Requirements: 6.2
    """
    # Calculate request duration
    if hasattr(g, 'start_time'):
        duration_ms = (time.time() - g.start_time) * 1000
    else:
        duration_ms = 0
    
    # Log request/response
    request_id = getattr(g, 'request_id', None)
    session_id = session.get('session_id')
    
    logger.info(
        f"Request completed: {request.method} {request.path} - "
        f"Status: {response.status_code}, Duration: {duration_ms:.2f}ms",
        extra={
            'request_id': request_id,
            'session_id': session_id,
            'method': request.method,
            'path': request.path,
            'status_code': response.status_code,
            'duration_ms': duration_ms
        }
    )
    
    return response


@app.route('/login', methods=['GET'])
def login():
    """
    Display login page with OAuth2 provider options.
    Requirements: 1.1, 1.4
    """
    try:
        # Check if OAuth2 manager is initialized
        if oauth2_manager is None:
            logger.error("OAuth2 manager not initialized")
            return render_template(
                'login.html',
                providers=[],
                error="Authentication system is not available. Please contact support.",
                metadata=MetadataConfig.to_dict()
            )
        
        # Get list of configured providers
        providers = oauth2_manager.get_configured_providers()
        
        # Check if any providers are configured
        if not providers:
            logger.error("No OAuth2 providers configured")
            return render_template(
                'login.html',
                providers=[],
                error="Authentication is not configured. Please contact support.",
                metadata=MetadataConfig.to_dict()
            )
        
        # Get error message from query params if present
        error_message = request.args.get('error')
        
        logger.debug(
            f"Serving login page with {len(providers)} provider(s)",
            extra={'providers': providers, 'has_error': bool(error_message)}
        )
        
        return render_template('login.html', providers=providers, error=error_message, metadata=MetadataConfig.to_dict())
    except Exception as e:
        logger.error(f"Error serving login page: {str(e)}", exc_info=True)
        return jsonify({
            'error': True,
            'message': 'Unable to load login page',
            'code': 'TEMPLATE_ERROR'
        }), 500


@app.route('/auth/<provider>', methods=['GET'])
def auth_redirect(provider: str):
    """
    Initiate OAuth2 flow by redirecting to provider's authorization page.
    
    Args:
        provider: OAuth2 provider name (google, github, facebook, linkedin, auth0)
        
    Requirements: 1.1, 1.4
    """
    try:
        # Check if OAuth2 manager is initialized
        if oauth2_manager is None:
            logger.error("OAuth2 manager not initialized")
            return redirect(url_for('login', error='Authentication system is not available'))
        
        # Check if provider is configured
        if not oauth2_manager.is_provider_configured(provider):
            logger.warning(
                f"Attempt to authenticate with unconfigured provider: {provider}",
                extra={'provider': provider}
            )
            return redirect(url_for('login', error=f'Provider {provider} is not configured'))
        
        # Generate callback URL
        redirect_uri = url_for('auth_callback', provider=provider, _external=True)
        
        # Create authorization URL and store state in session
        authorization_url, state = oauth2_manager.create_authorization_url(provider, redirect_uri)
        
        logger.info(
            f"Initiating OAuth2 flow with {provider}",
            extra={'provider': provider, 'redirect_uri': redirect_uri}
        )
        
        # Redirect to provider's authorization page
        return authorization_url
        
    except Exception as e:
        logger.error(
            f"Error initiating OAuth2 flow for {provider}: {str(e)}",
            extra={'provider': provider, 'error': str(e)},
            exc_info=True
        )
        
        # Provide user-friendly error message
        error_msg = "Failed to initiate authentication. Please try again."
        if hasattr(e, 'message'):
            error_msg = e.message
        
        return redirect(url_for('login', error=error_msg))


@app.route('/callback/<provider>', methods=['GET'])
def auth_callback(provider: str):
    """
    Handle OAuth2 callback from provider after user authorization.
    
    Args:
        provider: OAuth2 provider name (google, github, facebook, linkedin, auth0)
        
    Requirements: 1.2, 1.3, 1.4, 3.4
    """
    try:
        # Check if OAuth2 manager is initialized
        if oauth2_manager is None:
            logger.error("OAuth2 manager not initialized during callback")
            return redirect(url_for('login', error='Authentication system is not available'))
        
        # Get state parameter from callback
        state = request.args.get('state')
        
        # Validate state to prevent CSRF attacks
        if not state or not oauth2_manager.validate_state(state):
            logger.warning(
                f"Invalid state parameter in OAuth2 callback for {provider}",
                extra={
                    'provider': provider,
                    'has_state': bool(state),
                    'has_stored_state': bool(session.get('oauth2_state'))
                }
            )
            oauth2_manager.clear_session_state()
            return redirect(url_for('login', error='Invalid authentication state. Please try again.'))
        
        # Check for error from provider
        error = request.args.get('error')
        if error:
            error_description = request.args.get('error_description', 'Authentication failed')
            logger.warning(
                f"OAuth2 error from {provider}: {error} - {error_description}",
                extra={'provider': provider, 'error': error, 'error_description': error_description}
            )
            oauth2_manager.clear_session_state()
            
            # Provide user-friendly error messages
            if error == 'access_denied':
                error_msg = 'Authentication was cancelled. Please try again if you want to log in.'
            else:
                error_msg = f'Authentication failed: {error_description}'
            
            return redirect(url_for('login', error=error_msg))
        
        # Exchange authorization code for access token
        try:
            token = oauth2_manager.exchange_code_for_token(provider, request.url)
            logger.debug(
                f"Successfully exchanged code for token with {provider}",
                extra={'provider': provider}
            )
        except Exception as e:
            logger.error(
                f"Failed to exchange code for token with {provider}: {str(e)}",
                extra={'provider': provider, 'error': str(e)},
                exc_info=True
            )
            oauth2_manager.clear_session_state()
            
            # Use custom error message if available
            error_msg = "Failed to complete authentication. Please try again."
            if hasattr(e, 'message'):
                error_msg = e.message
            
            return redirect(url_for('login', error=error_msg))
        
        # Retrieve user information from provider
        try:
            user_info = oauth2_manager.get_user_info(provider, token)
            logger.debug(
                f"Successfully retrieved user info from {provider}",
                extra={'provider': provider, 'user_id': user_info.get('id')}
            )
        except Exception as e:
            logger.error(
                f"Failed to retrieve user info from {provider}: {str(e)}",
                extra={'provider': provider, 'error': str(e)},
                exc_info=True
            )
            oauth2_manager.clear_session_state()
            
            # Use custom error message if available
            error_msg = "Failed to retrieve your profile information. Please try again."
            if hasattr(e, 'message'):
                error_msg = e.message
            
            return redirect(url_for('login', error=error_msg))
        
        # Store user data and token in session
        session['user'] = user_info
        session['access_token'] = token.get('access_token')
        
        # Calculate token expiration (default to 1 hour if not provided)
        expires_in = token.get('expires_in', Config.OAUTH2_TOKEN_EXPIRATION)
        session['token_expires_at'] = datetime.utcnow().timestamp() + expires_in
        
        # Store login timestamp for session duration tracking
        session['login_timestamp'] = datetime.utcnow().timestamp()
        
        # Mark session as permanent to respect PERMANENT_SESSION_LIFETIME
        session.permanent = True
        
        # Clear OAuth2 state from session
        oauth2_manager.clear_session_state()
        
        # Log successful authentication
        logger.info(
            f"User authenticated successfully via {provider}",
            extra={
                'provider': provider,
                'user_id': user_info.get('id'),
                'user_email': user_info.get('email'),
                'token_expires_in': expires_in
            }
        )
        
        # Track login activity
        if activity_tracker:
            try:
                activity_tracker.log_login(
                    user_id=user_info.get('id', user_info.get('email', 'unknown')),
                    provider=provider,
                    metadata={
                        'user_agent': request.headers.get('User-Agent', 'unknown'),
                        'ip_address': request.remote_addr
                    }
                )
            except Exception as e:
                logger.error(f"Failed to log login activity: {str(e)}")
        
        # Redirect to original requested URL or home page
        next_url = session.pop('next_url', None)
        if next_url:
            logger.debug(f"Redirecting to original URL: {next_url}")
            return redirect(next_url)
        else:
            return redirect(url_for('index'))
        
    except Exception as e:
        logger.error(
            f"Unexpected error in OAuth2 callback for {provider}: {str(e)}",
            extra={'provider': provider, 'error': str(e)},
            exc_info=True
        )
        oauth2_manager.clear_session_state()
        return redirect(url_for('login', error='An unexpected error occurred during authentication'))


@app.route('/logout', methods=['GET'])
def logout():
    """
    Log out the current user by clearing session data.
    Requirements: 2.4, 5.3, 4.4
    """
    try:
        # Get user info for logging before clearing session
        user = session.get('user', {})
        user_email = user.get('email', 'unknown')
        user_id = user.get('id', 'unknown')
        provider = user.get('provider', 'unknown')
        
        # Calculate session duration
        login_timestamp = session.get('login_timestamp')
        session_duration = 0
        if login_timestamp:
            session_duration = int(datetime.utcnow().timestamp() - login_timestamp)
        
        # Get message count from session manager if available
        message_count = 0
        try:
            if session_manager.is_session_valid():
                message_count = session_manager.get_message_count()
        except:
            pass
        
        # Track logout activity before clearing session
        if activity_tracker:
            try:
                activity_tracker.log_logout(
                    user_id=user_id if user_id != 'unknown' else user_email,
                    session_duration=session_duration,
                    message_count=message_count,
                    metadata={
                        'provider': provider
                    }
                )
            except Exception as e:
                logger.error(f"Failed to log logout activity: {str(e)}")
        
        # Clear all session data
        session.clear()
        
        logger.info(
            f"User logged out successfully",
            extra={
                'user_email': user_email,
                'user_id': user_id,
                'provider': provider,
                'ip_address': request.remote_addr,
                'session_duration': session_duration,
                'message_count': message_count
            }
        )
        
        # Redirect to login page
        return redirect(url_for('login'))
        
    except Exception as e:
        logger.error(
            f"Error during logout: {str(e)}",
            extra={'error': str(e)},
            exc_info=True
        )
        # Clear session anyway
        session.clear()
        return redirect(url_for('login'))


@app.route('/api/user', methods=['GET'])
@require_api_auth
def get_user():
    """
    Return current authenticated user information.
    Requirements: 5.3
    """
    try:
        user = session.get('user', {})
        
        return jsonify({
            'id': user.get('id'),
            'email': user.get('email'),
            'name': user.get('name'),
            'picture': user.get('picture'),
            'provider': user.get('provider')
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving user info: {str(e)}")
        return jsonify({
            'error': True,
            'message': 'Failed to retrieve user information',
            'code': 'USER_INFO_ERROR'
        }), 500


@app.route('/', methods=['GET'])
@require_auth
def index():
    """
    Serve the chat interface
    Requirements: 1.1, 2.1, 1.5, 3.2
    """
    try:
        # Get authenticated user information
        user = session.get('user', {})
        
        response = render_template('index.html', user=user, metadata=MetadataConfig.to_dict())
        # Add cache-busting headers to prevent browser caching
        response = app.make_response(response)
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        logger.error(f"Error serving index page: {str(e)}")
        return jsonify({
            'error': True,
            'message': 'Unable to load chat interface',
            'code': 'TEMPLATE_ERROR'
        }), 500


@app.route('/api/chat', methods=['POST'])
@require_api_auth
def chat():
    """
    Process chat messages and return responses with comprehensive logging
    Requirements: 1.1, 1.4, 2.1, 6.1, 1.3, 1.5, 6.2, 3.1, 3.2, 3.4
    """
    request_id = getattr(g, 'request_id', None)
    
    try:
        # Get message from request
        data = request.get_json()
        if not data or 'message' not in data:
            logger.warning(f"Invalid request: missing message field", extra={'request_id': request_id})
            return jsonify({
                'error': True,
                'message': 'Message is required',
                'code': 'INVALID_REQUEST'
            }), 400
        
        user_message = data['message'].strip()
        if not user_message:
            logger.warning(f"Empty message received", extra={'request_id': request_id})
            return jsonify({
                'error': True,
                'message': 'Message cannot be empty',
                'code': 'EMPTY_MESSAGE'
            }), 400
        
        # Initialize or validate session
        session_id = session_manager.initialize_session()
        logger.info(
            f"Processing message for session {session_id}",
            extra={
                'request_id': request_id,
                'session_id': session_id,
                'message_length': len(user_message)
            }
        )
        
        # Add user message to conversation history
        session_manager.add_message('user', user_message)
        
        # Track message activity (without content)
        if activity_tracker:
            try:
                user = session.get('user', {})
                user_id = user.get('id', user.get('email', 'unknown'))
                activity_tracker.log_message(
                    user_id=user_id,
                    session_id=session_id,
                    metadata={
                        'user_agent': request.headers.get('User-Agent', 'unknown')
                    }
                )
            except Exception as e:
                logger.error(f"Failed to log message activity: {str(e)}")
        
        # Get conversation history for LLM
        conversation_messages = session_manager.get_conversation_history()
        conversation_dict = [
            {'role': msg.role, 'content': msg.content}
            for msg in conversation_messages
        ]
        
        # Get available tools from MCP client (only for OpenAI, not Gemini)
        available_tools = []
        if mcp_client and llm_service.config.provider == "openai":
            available_tools = mcp_client.get_tools_for_llm()
            logger.debug(
                f"Available tools: {len(available_tools)}",
                extra={'request_id': request_id, 'session_id': session_id}
            )
        else:
            if llm_service.config.provider == "gemini":
                logger.debug(
                    "Gemini provider detected, skipping tool integration",
                    extra={'request_id': request_id, 'session_id': session_id}
                )
            else:
                logger.warning(
                    "MCP client not available, proceeding without tools",
                    extra={'request_id': request_id, 'session_id': session_id}
                )
        
        # Create system prompt (without tools for Gemini)
        system_prompt = llm_service.create_system_prompt(available_tools)
        
        # Process conversation with LLM
        try:
            response_content, tool_calls = llm_service.process_conversation(
                conversation_history=conversation_dict[:-1],  # Exclude the just-added user message
                available_tools=available_tools,
                tool_executor=mcp_client.execute_tool if mcp_client else lambda **kwargs: None,
                system_prompt=system_prompt,
                max_iterations=5
            )
            
            logger.info(
                f"LLM processing completed: {len(tool_calls)} tool calls",
                extra={
                    'request_id': request_id,
                    'session_id': session_id,
                    'tool_calls_count': len(tool_calls)
                }
            )
        except ChatbotError as e:
            logger.error(
                f"LLM processing failed: {e.message}",
                extra={'request_id': request_id, 'session_id': session_id, 'error_code': e.code}
            )
            response_content = get_user_friendly_message(e)
            tool_calls = []
        except Exception as e:
            log_error_with_context(e, {
                'request_id': request_id,
                'session_id': session_id,
                'message_length': len(user_message)
            })
            response_content = "I apologize, but I'm having trouble processing your request right now. Please try again later."
            tool_calls = []
        
        # Add assistant response to conversation history
        assistant_message = session_manager.add_message(
            'assistant',
            response_content,
            tool_calls=tool_calls if tool_calls else None
        )
        
        # Get session info for response
        message_count = session_manager.get_message_count()
        
        logger.info(
            f"Chat response generated successfully",
            extra={
                'request_id': request_id,
                'session_id': session_id,
                'message_count': message_count,
                'response_length': len(response_content)
            }
        )
        
        return jsonify({
            'response': assistant_message.content,
            'timestamp': assistant_message.timestamp,
            'session_id': session_id,
            'message_count': message_count,
            'tool_calls_count': len(tool_calls) if tool_calls else 0
        }), 200
        
    except ChatbotError as e:
        log_error_with_context(e, {'request_id': request_id})
        error_response = format_error_response(
            e,
            include_details=Config.FLASK_ENV != 'production'
        )
        return jsonify(error_response), 500
        
    except Exception as e:
        log_error_with_context(e, {'request_id': request_id})
        error_response = format_error_response(
            e,
            include_details=Config.FLASK_ENV != 'production',
            include_traceback=Config.FLASK_ENV == 'development'
        )
        return jsonify(error_response), 500


@app.route('/api/session/history', methods=['GET'])
@require_api_auth
def get_history():
    """
    Get conversation history for current session
    Requirements: 1.3, 3.1, 3.2, 3.4
    """
    try:
        if not session_manager.is_session_valid():
            return jsonify({
                'error': True,
                'message': 'No active session',
                'code': 'NO_SESSION'
            }), 404
        
        messages = session_manager.get_conversation_history()
        session_info = session_manager.get_session_info()
        
        return jsonify({
            'session_id': session_info.session_id,
            'messages': [msg.to_dict() for msg in messages],
            'message_count': len(messages),
            'created_at': session_info.created_at,
            'last_activity': session_info.last_activity
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving conversation history: {str(e)}")
        return jsonify({
            'error': True,
            'message': 'Failed to retrieve conversation history',
            'code': 'HISTORY_ERROR'
        }), 500


@app.route('/api/session/clear', methods=['POST'])
@require_api_auth
def clear_history():
    """
    Clear conversation history for current session
    Requirements: 1.3, 3.1, 3.2, 3.4
    """
    try:
        if not session_manager.is_session_valid():
            return jsonify({
                'error': True,
                'message': 'No active session',
                'code': 'NO_SESSION'
            }), 404
        
        session_id = session_manager.get_session_id()
        session_manager.clear_conversation_history()
        
        return jsonify({
            'success': True,
            'message': 'Conversation history cleared',
            'session_id': session_id
        }), 200
        
    except Exception as e:
        logger.error(f"Error clearing conversation history: {str(e)}")
        return jsonify({
            'error': True,
            'message': 'Failed to clear conversation history',
            'code': 'CLEAR_ERROR'
        }), 500


@app.route('/api/health', methods=['GET'])
def health():
    """
    Health check endpoint with initialization metrics
    Requirements: 2.1
    """
    try:
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'version': '1.0.0',
            'environment': os.getenv('FLASK_ENV', 'development')
        }
        
        # Check if required services are configured using Config
        config_status = {
            'llm_configured': bool(Config.LLM_API_KEY),
            'oracle_configured': Config.is_oracle_enabled(),
            'pdf_configured': Config.is_pdf_enabled()
        }
        health_status['configuration'] = config_status
        
        # Check service status
        service_status = {
            'mcp_client': 'initialized' if mcp_client else 'not_initialized',
            'llm_service': 'initialized' if llm_service else 'not_initialized',
            'yugabyte_server': 'initialized' if yugabyte_server else 'not_initialized',
        }
        
        if mcp_client:
            service_status['mcp_servers'] = mcp_client.get_server_status()
            service_status['available_tools'] = len(mcp_client.get_available_tools())
        
        health_status['services'] = service_status
        
        # Add initialization metrics
        health_status['initialization_metrics'] = get_initialization_metrics()
        
        return jsonify(health_status), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@app.route('/api/warmup', methods=['GET', 'POST'])
def warmup():
    """
    Warmup endpoint for pre-initializing connections
    Useful for reducing cold start latency
    Requirements: 2.4
    """
    try:
        from modules.serverless_optimizer import warmup_connections, get_cold_start_metrics
        
        # Initialize services
        initialize_services()
        
        # Warmup connections
        warmup_results = warmup_connections()
        
        # Get performance metrics
        metrics = get_cold_start_metrics()
        
        return jsonify({
            'status': 'warmed_up',
            'timestamp': datetime.utcnow().isoformat(),
            'warmup_results': warmup_results,
            'metrics': metrics
        }), 200
        
    except Exception as e:
        logger.error(f"Warmup failed: {str(e)}")
        return jsonify({
            'status': 'warmup_failed',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@app.route('/admin/analytics', methods=['GET'])
@require_auth
def analytics_dashboard():
    """
    Display analytics dashboard (admin only).
    
    Requirements: 8.4
    """
    try:
        # Check if user has admin role
        user = session.get('user', {})
        is_admin = user.get('is_admin', False)
        
        # For now, allow any authenticated user to view analytics
        # In production, you should implement proper admin role checking
        # if not is_admin:
        #     return redirect(url_for('index'))
        
        return render_template('admin/analytics.html', user=user, metadata=MetadataConfig.to_dict())
        
    except Exception as e:
        logger.error(f"Error serving analytics dashboard: {str(e)}", exc_info=True)
        return jsonify({
            'error': True,
            'message': 'Unable to load analytics dashboard',
            'code': 'TEMPLATE_ERROR'
        }), 500


@app.route('/api/analytics', methods=['GET'])
@require_api_auth
def get_analytics():
    """
    Return usage analytics (admin only).
    
    Query parameters:
        - start_date: ISO format date string (optional)
        - end_date: ISO format date string (optional)
        - user_id: Specific user ID for user stats (optional)
    
    Requirements: 8.4
    """
    try:
        # Check if user has admin role
        user = session.get('user', {})
        is_admin = user.get('is_admin', False)
        
        # For now, allow any authenticated user to view analytics
        # In production, you should implement proper admin role checking
        # if not is_admin:
        #     return jsonify({
        #         'error': True,
        #         'message': 'Unauthorized. Admin access required.',
        #         'code': 'FORBIDDEN'
        #     }), 403
        
        if not activity_tracker:
            return jsonify({
                'error': True,
                'message': 'Analytics not available',
                'code': 'ANALYTICS_UNAVAILABLE'
            }), 503
        
        # Parse date parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        user_id = request.args.get('user_id')
        
        start_dt = None
        end_dt = None
        
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
            except ValueError:
                return jsonify({
                    'error': True,
                    'message': 'Invalid start_date format. Use ISO format (YYYY-MM-DD)',
                    'code': 'INVALID_DATE'
                }), 400
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
            except ValueError:
                return jsonify({
                    'error': True,
                    'message': 'Invalid end_date format. Use ISO format (YYYY-MM-DD)',
                    'code': 'INVALID_DATE'
                }), 400
        
        # Get user-specific or global stats
        if user_id:
            stats = activity_tracker.get_user_stats(user_id, start_dt, end_dt)
        else:
            stats = activity_tracker.get_global_stats(start_dt, end_dt)
        
        return jsonify({
            'success': True,
            'stats': stats,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving analytics: {str(e)}", exc_info=True)
        return jsonify({
            'error': True,
            'message': 'Failed to retrieve analytics',
            'code': 'ANALYTICS_ERROR'
        }), 500


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors with logging"""
    request_id = getattr(g, 'request_id', None)
    logger.warning(
        f"Resource not found: {request.path}",
        extra={'request_id': request_id, 'path': request.path}
    )
    return jsonify({
        'error': True,
        'message': 'Resource not found',
        'code': 'NOT_FOUND'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors with comprehensive logging"""
    request_id = getattr(g, 'request_id', None)
    log_error_with_context(
        error,
        {
            'request_id': request_id,
            'path': request.path,
            'method': request.method
        }
    )
    
    error_response = format_error_response(
        error,
        include_details=Config.FLASK_ENV != 'production',
        include_traceback=Config.FLASK_ENV == 'development'
    )
    return jsonify(error_response), 500


@app.errorhandler(Exception)
def handle_exception(error):
    """Handle all unhandled exceptions with logging"""
    request_id = getattr(g, 'request_id', None)
    log_error_with_context(
        error,
        {
            'request_id': request_id,
            'path': request.path,
            'method': request.method
        }
    )
    
    # Return appropriate status code
    status_code = 500
    if hasattr(error, 'code'):
        status_code = error.code
    
    error_response = format_error_response(
        error,
        include_details=Config.FLASK_ENV != 'production',
        include_traceback=Config.FLASK_ENV == 'development'
    )
    return jsonify(error_response), status_code


if __name__ == '__main__':
    # Warmup services before starting the application
    logger.info("Pre-initializing services at startup...")
    warmup_services()
    
    # Run the application
    port = int(os.getenv('PORT', 5000))
    debug = Config.FLASK_ENV != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug)
