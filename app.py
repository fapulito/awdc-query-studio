"""
app.py — local development entry point.

Service globals and route decorators live here so that the test suite can
patch them via @patch('app.mcp_client'), @patch('app.llm_service'), etc.
Route bodies are delegated to modules.app_core.impl_* helpers.
"""

import os
import sys
import time
from datetime import timedelta
from typing import Optional

from flask import Flask, redirect, url_for
from dotenv import load_dotenv
from config import Config, MetadataConfig, validate_config_on_startup
from modules.session_manager import SessionManager
from modules.mcp_client import create_mcp_client_from_env
from modules.llm_service import create_llm_service_from_env
from modules.apex_rest_handler import ApexRestHandler, register_apex_routes
from modules.oracle_mcp_server import OracleMCPServer
from modules.pdf_mcp_server import PDFMCPServer
from modules.yugabyte_mcp_server import YugabyteMCPServer
from modules.logging_config import configure_from_env, get_logger
from modules.oauth2_manager import OAuth2Manager
from modules.auth_decorator import require_auth, require_api_auth
from modules.activity_tracker import get_activity_tracker
from modules.app_core import (
    create_app,
    impl_login, impl_auth_redirect, impl_auth_callback, impl_logout,
    impl_get_user, impl_index, impl_chat,
    impl_get_history, impl_clear_history, impl_health, impl_warmup,
    impl_analytics_dashboard, impl_get_analytics,
    impl_pricing, impl_create_checkout_session, impl_stripe_webhook,
)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()
validate_config_on_startup()
configure_from_env()
logger = get_logger(__name__)
logger.info("Application configuration loaded", extra={'config': Config.get_safe_config()})

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
app = create_app(
    template_folder=os.path.join(_HERE, 'templates'),
    static_folder=os.path.join(_HERE, 'static'),
)

# ---------------------------------------------------------------------------
# Service globals (patched by tests via @patch('app.mcp_client') etc.)
# ---------------------------------------------------------------------------

mcp_client = None
llm_service = None
oracle_server = None
pdf_server = None
yugabyte_server = None
apex_handler = None
oauth2_manager = OAuth2Manager(app)

try:
    activity_tracker = get_activity_tracker()
    logger.info("Activity tracker initialized successfully")
except Exception as _e:
    logger.error(f"Failed to initialize activity tracker: {_e}", exc_info=True)
    activity_tracker = None

_initialization_attempted = False
_initialization_timestamp = None
_services_initialized = False

_init_metrics = {
    'total_time': 0.0,
    'llm_service_time': 0.0,
    'oracle_server_time': 0.0,
    'pdf_server_time': 0.0,
    'yugabyte_server_time': 0.0,
    'mcp_client_time': 0.0,
    'apex_handler_time': 0.0,
    'cold_start': True,
    'initialization_count': 0,
}

# ---------------------------------------------------------------------------
# Service initialization
# ---------------------------------------------------------------------------

def initialize_services():
    """
    Initialize MCP client, LLM service, and APEX handlers with caching.
    Requirements: 2.4, 2.5
    """
    global mcp_client, llm_service, oracle_server, pdf_server, yugabyte_server, apex_handler
    global _initialization_attempted, _initialization_timestamp, _services_initialized
    global _init_metrics

    if _services_initialized:
        logger.debug("Services already initialized (warm start), skipping")
        _init_metrics['cold_start'] = False
        return

    is_cold_start = _init_metrics['initialization_count'] == 0
    _init_metrics['cold_start'] = is_cold_start
    _init_metrics['initialization_count'] += 1

    logger.info(
        f"Initializing services ({'cold start' if is_cold_start else 'warm start'})..."
    )
    total_start = time.time()
    current_time = time.time()

    if llm_service is None:
        try:
            llm_start = time.time()
            logger.info("Initializing LLM service")
            llm_service = create_llm_service_from_env()
            _init_metrics['llm_service_time'] = time.time() - llm_start
            logger.info(f"LLM service initialized in {_init_metrics['llm_service_time']:.3f}s")
            _initialization_attempted = True
            _initialization_timestamp = current_time
        except Exception as exc:
            logger.error(f"Failed to initialize LLM service: {exc}")
            _initialization_attempted = False
            _initialization_timestamp = None
            raise

    if oracle_server is None and Config.is_oracle_enabled():
        try:
            t = time.time()
            oracle_server = OracleMCPServer()
            _init_metrics['oracle_server_time'] = time.time() - t
            logger.info(f"Oracle MCP Server initialized in {_init_metrics['oracle_server_time']:.3f}s")
        except Exception as exc:
            logger.warning(f"Oracle MCP Server not available: {exc}")

    if yugabyte_server is None and os.getenv('YUGABYTE_HOST'):
        try:
            t = time.time()
            yugabyte_server = YugabyteMCPServer()
            _init_metrics['yugabyte_server_time'] = time.time() - t
            logger.info(f"YugabyteDB MCP Server initialized in {_init_metrics['yugabyte_server_time']:.3f}s")
        except Exception as exc:
            logger.warning(f"YugabyteDB MCP Server not available: {exc}")

    if pdf_server is None:
        try:
            t = time.time()
            pdf_server = PDFMCPServer()
            _init_metrics['pdf_server_time'] = time.time() - t
            logger.info(f"PDF MCP Server initialized in {_init_metrics['pdf_server_time']:.3f}s")
        except Exception as exc:
            logger.error(f"Failed to initialize PDF MCP Server: {exc}")

    if mcp_client is None:
        try:
            t = time.time()
            mcp_client = create_mcp_client_from_env()
            _init_metrics['mcp_client_time'] = time.time() - t
            logger.info(f"MCP client initialized in {_init_metrics['mcp_client_time']:.3f}s (lazy connection mode)")
        except Exception as exc:
            logger.error(f"Failed to initialize MCP client: {exc}")

    if mcp_client is not None and yugabyte_server is not None:
        if not any(t.startswith('yb_') for t in mcp_client.available_tools):
            mcp_client.register_in_process_server('yugabyte', yugabyte_server)
            logger.info("YugabyteDB in-process server registered with MCP client")

    if apex_handler is None and llm_service is not None:
        try:
            t = time.time()
            apex_handler = ApexRestHandler(
                oracle_server, pdf_server, llm_service, yugabyte_server
            )
            _init_metrics['apex_handler_time'] = time.time() - t
            logger.info(f"APEX REST handler initialized in {_init_metrics['apex_handler_time']:.3f}s")
        except Exception as exc:
            logger.error(f"Failed to initialize APEX REST handler: {exc}")

    _init_metrics['total_time'] = time.time() - total_start
    _services_initialized = True
    logger.info(
        f"All services initialized successfully in {_init_metrics['total_time']:.3f}s "
        f"({'cold start' if is_cold_start else 'warm start'})",
        extra={'initialization_metrics': _init_metrics, 'cold_start': is_cold_start},
    )


def warmup_services():
    """Warmup function to pre-initialize all services. Requirements: 2.4"""
    logger.info("Starting service warmup...")
    start_time = time.time()
    try:
        initialize_services()
        elapsed = time.time() - start_time
        logger.info(
            f"Service warmup completed in {elapsed:.3f}s",
            extra={'warmup_time': elapsed, 'metrics': _init_metrics},
        )
        return True
    except Exception as exc:
        elapsed = time.time() - start_time
        logger.error(
            f"Service warmup failed after {elapsed:.3f}s: {exc}",
            extra={'warmup_time': elapsed, 'error': str(exc)},
        )
        return False


def get_initialization_metrics():
    """Return initialization timing metrics for monitoring."""
    return {
        **_init_metrics,
        'services_initialized': _services_initialized,
        'initialization_timestamp': _initialization_timestamp,
    }


# ---------------------------------------------------------------------------
# Routes — decorators here, bodies delegated to app_core.impl_*
# ---------------------------------------------------------------------------

@app.before_request
def initialize_on_first_request():
    """Initialize services on first request to avoid import-time delays."""
    global _services_initialized
    if not _services_initialized:
        logger.info("First request detected, initializing services...")
        warmup_services()


@app.route('/login', methods=['GET'])
def login():
    """Display login page. Requirements: 1.1"""
    return impl_login(oauth2_manager)


@app.route('/auth/<provider>', methods=['GET'])
def auth_redirect(provider: str):
    """Initiate OAuth2 flow. Requirements: 1.1"""
    return impl_auth_redirect(provider, oauth2_manager)


@app.route('/callback/<provider>', methods=['GET'])
def auth_callback(provider: str):
    """Handle OAuth2 callback. Requirements: 1.2, 1.3, 1.4"""
    return impl_auth_callback(provider, oauth2_manager, activity_tracker)


@app.route('/logout', methods=['GET'])
def logout():
    """Log out current user. Requirements: 2.4, 5.3"""
    return impl_logout(activity_tracker)


@app.route('/api/user', methods=['GET'])
@require_api_auth
def get_user():
    """Return current user info. Requirements: 5.3"""
    return impl_get_user()


@app.route('/', methods=['GET'])
@require_auth
def index():
    """Serve chat interface. Requirements: 1.1, 2.1, 1.5, 3.2"""
    return impl_index()


@app.route('/api/chat', methods=['POST'])
@require_api_auth
def chat():
    """Process chat message. Requirements: 1.1, 1.4, 2.1, 6.1, 1.3, 1.5, 6.2, 3.1, 3.2, 3.4"""
    return impl_chat(mcp_client, llm_service, activity_tracker)


@app.route('/api/session/history', methods=['GET'])
@require_api_auth
def get_history():
    """Get conversation history. Requirements: 1.3, 3.1, 3.2, 3.4"""
    return impl_get_history()


@app.route('/api/session/clear', methods=['POST'])
@require_api_auth
def clear_history():
    """Clear conversation history. Requirements: 1.3, 3.1, 3.2, 3.4"""
    return impl_clear_history()


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint. Requirements: 2.1"""
    return impl_health(mcp_client, llm_service, yugabyte_server, get_initialization_metrics)


@app.route('/api/warmup', methods=['GET', 'POST'])
def warmup():
    """Warmup endpoint. Requirements: 2.4"""
    return impl_warmup(initialize_services)


@app.route('/admin/analytics', methods=['GET'])
@require_auth
def analytics_dashboard():
    """Analytics dashboard. Requirements: 8.4"""
    return impl_analytics_dashboard()


@app.route('/api/analytics', methods=['GET'])
@require_api_auth
def get_analytics():
    """Usage analytics API. Requirements: 8.4"""
    return impl_get_analytics(activity_tracker)


@app.route('/pricing', methods=['GET'])
def pricing():
    """Freemium pricing page."""
    return impl_pricing()


@app.route('/billing/create-checkout-session', methods=['POST'])
@require_auth
def create_checkout_session():
    """Create Stripe Checkout session."""
    return impl_create_checkout_session()


@app.route('/billing/webhook', methods=['POST'])
def stripe_webhook():
    """Stripe webhook handler."""
    return impl_stripe_webhook()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    logger.info("Pre-initializing services at startup...")
    warmup_services()
    port = int(os.getenv('PORT', 5000))
    debug = Config.FLASK_ENV != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug)
