"""
app_core.py — shared Flask application factory and route implementation helpers.

Both entry points (app.py at the repo root and api/index.py under api/) call
create_app() to get a configured Flask application, and delegate all route
bodies to the implementation functions defined here.

The service globals (mcp_client, llm_service, etc.) intentionally stay in the
entry-file namespaces so that the existing test suite can patch them via
@patch('app.mcp_client') and idx_module.mcp_client = ... without modification.

Route functions in the entry files call the corresponding _impl_* helper here,
passing their local service references explicitly.
"""

import os
import time
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from flask import (
    Flask, request, jsonify, session, render_template,
    g, redirect, url_for, current_app,
)
from config import Config, MetadataConfig
from modules.session_manager import SessionManager
from modules.logging_config import get_logger
from modules.error_handler import (
    format_error_response, get_user_friendly_message,
    ChatbotError, log_error_with_context,
)
import modules.billing as billing

logger = get_logger(__name__)

# Shared session manager — one instance per process, used by both entry points.
session_manager = SessionManager()


# ---------------------------------------------------------------------------
# Flask application factory
# ---------------------------------------------------------------------------

def create_app(template_folder: str, static_folder: str) -> Flask:
    """
    Create and return a configured Flask application.

    Routes are NOT registered here; each entry file registers its own routes
    so that @patch('app.mcp_client') in tests targets the correct namespace.
    Only the before/after-request hooks, error handlers, and Flask config are
    wired up here.

    Args:
        template_folder: Absolute path to the Jinja2 templates directory.
        static_folder:   Absolute path to the static-assets directory.

    Returns:
        Configured Flask application object (no routes registered yet).
    """
    application = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
    )

    # Flask configuration (Requirements: 6.1, 6.3)
    application.config['SECRET_KEY'] = Config.SECRET_KEY
    application.config['SESSION_TYPE'] = 'filesystem'
    application.config['SESSION_COOKIE_SECURE'] = Config.FLASK_ENV == 'production'
    application.config['SESSION_COOKIE_HTTPONLY'] = True
    application.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    application.config['PERMANENT_SESSION_LIFETIME'] = timedelta(
        seconds=Config.SESSION_TIMEOUT
    )

    _register_lifecycle_hooks(application)
    _register_error_handlers(application)

    return application


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------

def _register_lifecycle_hooks(app: Flask) -> None:

    @app.before_request
    def before_request():
        """Setup request context (Requirements: 1.5, 6.3, 6.2)."""
        g.start_time = time.time()
        g.request_id = str(uuid.uuid4())
        if request.path.startswith('/static/') or request.path == '/api/health':
            return
        if 'session_id' in session and not session_manager.is_session_valid():
            logger.info(
                f"Session {session['session_id']} expired, cleaning up"
            )
            session_manager.cleanup_session()

    @app.after_request
    def after_request(response):
        """Log request/response info (Requirements: 6.2)."""
        duration_ms = (
            (time.time() - g.start_time) * 1000 if hasattr(g, 'start_time') else 0
        )
        logger.info(
            f"Request completed: {request.method} {request.path} - "
            f"Status: {response.status_code}, Duration: {duration_ms:.2f}ms",
            extra={
                'request_id': getattr(g, 'request_id', None),
                'session_id': session.get('session_id'),
                'method': request.method,
                'path': request.path,
                'status_code': response.status_code,
                'duration_ms': duration_ms,
            },
        )
        return response


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

def _register_error_handlers(app: Flask) -> None:

    @app.errorhandler(404)
    def not_found(error):
        logger.warning(
            f"Resource not found: {request.path}",
            extra={'request_id': getattr(g, 'request_id', None), 'path': request.path},
        )
        return jsonify({
            'error': True,
            'message': 'Resource not found',
            'code': 'NOT_FOUND',
        }), 404

    @app.errorhandler(500)
    def internal_error(error):
        log_error_with_context(
            error,
            {
                'request_id': getattr(g, 'request_id', None),
                'path': request.path,
                'method': request.method,
            },
        )
        return jsonify(format_error_response(
            error,
            include_details=Config.FLASK_ENV != 'production',
            include_traceback=Config.FLASK_ENV == 'development',
        )), 500

    @app.errorhandler(Exception)
    def handle_exception(error):
        log_error_with_context(
            error,
            {
                'request_id': getattr(g, 'request_id', None),
                'path': request.path,
                'method': request.method,
            },
        )
        return jsonify(format_error_response(
            error,
            include_details=Config.FLASK_ENV != 'production',
            include_traceback=Config.FLASK_ENV == 'development',
        )), getattr(error, 'code', 500)


# ---------------------------------------------------------------------------
# Route implementation helpers
# Each _impl_* function contains the actual route body, accepting the
# service objects it needs as explicit parameters.  Entry files call these
# from their own route functions so the test suite can patch entry-file globals.
# ---------------------------------------------------------------------------

def impl_login(oauth2_manager):
    """Implementation for GET /login."""
    try:
        providers = oauth2_manager.get_configured_providers()
        error_message = request.args.get('error')
        return render_template(
            'login.html',
            providers=providers,
            error=error_message,
            metadata=MetadataConfig.to_dict(),
        )
    except Exception as exc:
        logger.error(f"Error serving login page: {exc}")
        return jsonify({
            'error': True,
            'message': 'Unable to load login page',
            'code': 'TEMPLATE_ERROR',
        }), 500


def impl_auth_redirect(provider: str, oauth2_manager):
    """Implementation for GET /auth/<provider>."""
    try:
        if not oauth2_manager.is_provider_configured(provider):
            logger.warning(
                f"Attempt to authenticate with unconfigured provider: {provider}"
            )
            return redirect(
                url_for('login', error=f'Provider {provider} is not configured')
            )
        redirect_uri = url_for('auth_callback', provider=provider, _external=True)
        authorization_url, state = oauth2_manager.create_authorization_url(
            provider, redirect_uri
        )
        logger.info(f"Redirecting to {provider} for authentication")
        return authorization_url
    except Exception as exc:
        logger.error(f"Error initiating OAuth2 flow for {provider}: {exc}")
        return redirect(url_for('login', error='Failed to initiate authentication'))


def impl_auth_callback(provider: str, oauth2_manager, activity_tracker):
    """Implementation for GET /callback/<provider>."""
    try:
        state = request.args.get('state')
        if not state or not oauth2_manager.validate_state(state):
            logger.warning(
                f"Invalid state parameter in OAuth2 callback for {provider}"
            )
            oauth2_manager.clear_session_state()
            return redirect(
                url_for('login',
                        error='Invalid authentication state. Please try again.')
            )

        error = request.args.get('error')
        if error:
            error_description = request.args.get(
                'error_description', 'Authentication failed'
            )
            logger.warning(
                f"OAuth2 error from {provider}: {error} - {error_description}"
            )
            oauth2_manager.clear_session_state()
            return redirect(
                url_for('login',
                        error=f'Authentication failed: {error_description}')
            )

        try:
            token = oauth2_manager.exchange_code_for_token(provider, request.url)
        except Exception as exc:
            logger.error(
                f"Failed to exchange code for token with {provider}: {exc}"
            )
            oauth2_manager.clear_session_state()
            return redirect(
                url_for('login', error='Failed to complete authentication')
            )

        try:
            user_info = oauth2_manager.get_user_info(provider, token)
        except Exception as exc:
            logger.error(f"Failed to retrieve user info from {provider}: {exc}")
            oauth2_manager.clear_session_state()
            return redirect(
                url_for('login', error='Failed to retrieve user information')
            )

        session['user'] = user_info
        session['access_token'] = token.get('access_token')
        expires_in = token.get('expires_in', Config.OAUTH2_TOKEN_EXPIRATION)
        session['token_expires_at'] = datetime.utcnow().timestamp() + expires_in
        session['login_timestamp'] = datetime.utcnow().timestamp()
        session.permanent = True
        oauth2_manager.clear_session_state()

        logger.info(
            f"User authenticated successfully via {provider}",
            extra={
                'provider': provider,
                'user_id': user_info.get('id'),
                'user_email': user_info.get('email'),
            },
        )

        if activity_tracker:
            try:
                activity_tracker.log_login(
                    user_id=user_info.get('id', user_info.get('email', 'unknown')),
                    provider=provider,
                    metadata={
                        'user_agent': request.headers.get('User-Agent', 'unknown'),
                        'ip_address': request.remote_addr,
                    },
                )
            except Exception as exc:
                logger.error(f"Failed to log login activity: {exc}")

        next_url = session.pop('next_url', None)
        return redirect(next_url) if next_url else redirect(url_for('index'))

    except Exception as exc:
        logger.error(
            f"Unexpected error in OAuth2 callback for {provider}: {exc}"
        )
        oauth2_manager.clear_session_state()
        return redirect(
            url_for('login',
                    error='An unexpected error occurred during authentication')
        )


def impl_logout(activity_tracker):
    """Implementation for GET /logout."""
    try:
        user = session.get('user', {})
        user_email = user.get('email', 'unknown')
        user_id = user.get('id', 'unknown')
        provider = user.get('provider', 'unknown')

        login_timestamp = session.get('login_timestamp')
        session_duration = 0
        if login_timestamp:
            session_duration = int(datetime.utcnow().timestamp() - login_timestamp)

        message_count = 0
        try:
            if session_manager.is_session_valid():
                message_count = session_manager.get_message_count()
        except Exception:
            pass

        if activity_tracker:
            try:
                activity_tracker.log_logout(
                    user_id=user_id if user_id != 'unknown' else user_email,
                    session_duration=session_duration,
                    message_count=message_count,
                    metadata={'provider': provider},
                )
            except Exception as exc:
                logger.error(f"Failed to log logout activity: {exc}")

        session.clear()
        logger.info(f"User logged out: {user_email}")
        return redirect(url_for('login'))

    except Exception as exc:
        logger.error(f"Error during logout: {exc}")
        session.clear()
        return redirect(url_for('login'))


def impl_get_user():
    """Implementation for GET /api/user."""
    try:
        user = session.get('user', {})
        return jsonify({
            'id': user.get('id'),
            'email': user.get('email'),
            'name': user.get('name'),
            'picture': user.get('picture'),
            'provider': user.get('provider'),
        }), 200
    except Exception as exc:
        logger.error(f"Error retrieving user info: {exc}")
        return jsonify({
            'error': True,
            'message': 'Failed to retrieve user information',
            'code': 'USER_INFO_ERROR',
        }), 500


def impl_index():
    """Implementation for GET /."""
    try:
        user = session.get('user', {})
        response = render_template(
            'index.html', user=user, metadata=MetadataConfig.to_dict()
        )
        response = current_app.make_response(response)
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as exc:
        logger.error(f"Error serving index page: {exc}")
        return jsonify({
            'error': True,
            'message': 'Unable to load chat interface',
            'code': 'TEMPLATE_ERROR',
        }), 500


def impl_chat(mcp_client, llm_service, activity_tracker):
    """
    Implementation for POST /api/chat.

    Reads service objects from the caller's namespace (passed explicitly) so
    that test patches on app.mcp_client / api.index.mcp_client take effect.
    """
    request_id = getattr(g, 'request_id', None)

    try:
        data = request.get_json()
        if not data or 'message' not in data:
            logger.warning(
                "Invalid request: missing message field",
                extra={'request_id': request_id},
            )
            return jsonify({
                'error': True,
                'message': 'Message is required',
                'code': 'INVALID_REQUEST',
            }), 400

        user_message = data['message'].strip()
        if not user_message:
            logger.warning("Empty message received", extra={'request_id': request_id})
            return jsonify({
                'error': True,
                'message': 'Message cannot be empty',
                'code': 'EMPTY_MESSAGE',
            }), 400

        # Billing: check plan limit
        try:
            _email = session.get('user', {}).get('email', '')
            if _email:
                _allowed, _used, _limit = billing.check_limit(_email)
                if not _allowed:
                    _tier = billing.get_or_create_user(_email).get('tier', 'free')
                    return jsonify({
                        'error': 'Plan limit reached',
                        'message': (
                            f"You have reached your {_used}-question monthly limit. "
                            "Upgrade to Pro for more."
                        ),
                        'upgrade_url': '/pricing',
                        'response': (
                            f"You've used all {_limit} questions in your {_tier} plan "
                            "this month. Visit /pricing to upgrade to Pro."
                        ),
                    }), 402
        except Exception as billing_exc:
            logger.warning(f"Billing check failed (fail open): {billing_exc}")

        session_id = session_manager.initialize_session()
        logger.info(
            f"Processing message for session {session_id}",
            extra={
                'request_id': request_id,
                'session_id': session_id,
                'message_length': len(user_message),
            },
        )

        session_manager.add_message('user', user_message)

        if activity_tracker:
            try:
                _user = session.get('user', {})
                activity_tracker.log_message(
                    user_id=_user.get('id', _user.get('email', 'unknown')),
                    session_id=session_id,
                    metadata={
                        'user_agent': request.headers.get('User-Agent', 'unknown')
                    },
                )
            except Exception as exc:
                logger.error(f"Failed to log message activity: {exc}")

        conversation_messages = session_manager.get_conversation_history()
        conversation_dict = [
            {'role': msg.role, 'content': msg.content}
            for msg in conversation_messages
        ]

        # All providers get tools (api/index.py behavior)
        available_tools = []
        if mcp_client:
            available_tools = mcp_client.get_tools_for_llm()
            logger.debug(
                f"Available tools: {len(available_tools)}",
                extra={'request_id': request_id, 'session_id': session_id},
            )
        else:
            logger.warning(
                "MCP client not available, proceeding without tools",
                extra={'request_id': request_id, 'session_id': session_id},
            )

        system_prompt = llm_service.create_system_prompt(available_tools)

        try:
            # Include full conversation_dict (api/index.py behavior)
            response_content, tool_calls, queries, _last_result = (
                llm_service.process_conversation(
                    conversation_history=conversation_dict,
                    available_tools=available_tools,
                    tool_executor=(
                        mcp_client.execute_tool if mcp_client
                        else lambda **kwargs: None
                    ),
                    system_prompt=system_prompt,
                    max_iterations=10,
                )
            )
            logger.info(
                f"LLM processing completed: {len(tool_calls)} tool calls",
                extra={
                    'request_id': request_id,
                    'session_id': session_id,
                    'tool_calls_count': len(tool_calls),
                },
            )
        except ChatbotError as exc:
            logger.error(
                f"LLM processing failed: {exc.message}",
                extra={
                    'request_id': request_id,
                    'session_id': session_id,
                    'error_code': exc.code,
                },
            )
            response_content = get_user_friendly_message(exc)
            tool_calls = []
            queries = []
            _last_result = None
        except Exception as exc:
            log_error_with_context(exc, {
                'request_id': request_id,
                'session_id': session_id,
                'message_length': len(user_message),
            })
            response_content = (
                "I apologize, but I'm having trouble processing your request "
                "right now. Please try again later."
            )
            tool_calls = []
            queries = []
            _last_result = None

        assistant_message = session_manager.add_message(
            'assistant',
            response_content,
            tool_calls=tool_calls if tool_calls else None,
        )
        message_count = session_manager.get_message_count()

        logger.info(
            "Chat response generated successfully",
            extra={
                'request_id': request_id,
                'session_id': session_id,
                'message_count': message_count,
                'response_length': len(response_content),
            },
        )

        # Billing: record successful question
        try:
            _email = session.get('user', {}).get('email', '')
            if _email:
                billing.record_question(_email)
        except Exception as billing_exc:
            logger.warning(f"Billing record failed (fail open): {billing_exc}")

        _result_payload = None
        if (
            _last_result
            and isinstance(_last_result, dict)
            and _last_result.get("success")
            and _last_result.get("rows")
        ):
            _result_payload = {
                "table": _last_result.get("table_name", ""),
                "columns": _last_result.get("columns", []),
                "rows": _last_result["rows"][:200],
            }

        return jsonify({
            'response': assistant_message.content,
            'timestamp': assistant_message.timestamp,
            'session_id': session_id,
            'message_count': message_count,
            'tool_calls_count': len(tool_calls) if tool_calls else 0,
            'queries': queries if queries else [],
            'result': _result_payload,
        }), 200

    except ChatbotError as exc:
        log_error_with_context(exc, {'request_id': request_id})
        return jsonify(format_error_response(
            exc, include_details=Config.FLASK_ENV != 'production'
        )), 500

    except Exception as exc:
        log_error_with_context(exc, {'request_id': request_id})
        return jsonify(format_error_response(
            exc,
            include_details=Config.FLASK_ENV != 'production',
            include_traceback=Config.FLASK_ENV == 'development',
        )), 500


def impl_get_history():
    """Implementation for GET /api/session/history."""
    try:
        if not session_manager.is_session_valid():
            return jsonify({
                'error': True,
                'message': 'No active session',
                'code': 'NO_SESSION',
            }), 404
        messages = session_manager.get_conversation_history()
        session_info = session_manager.get_session_info()
        return jsonify({
            'session_id': session_info.session_id,
            'messages': [msg.to_dict() for msg in messages],
            'message_count': len(messages),
            'created_at': session_info.created_at,
            'last_activity': session_info.last_activity,
        }), 200
    except Exception as exc:
        logger.error(f"Error retrieving conversation history: {exc}")
        return jsonify({
            'error': True,
            'message': 'Failed to retrieve conversation history',
            'code': 'HISTORY_ERROR',
        }), 500


def impl_clear_history():
    """Implementation for POST /api/session/clear."""
    try:
        if not session_manager.is_session_valid():
            return jsonify({
                'error': True,
                'message': 'No active session',
                'code': 'NO_SESSION',
            }), 404
        session_id = session_manager.get_session_id()
        session_manager.clear_conversation_history()
        return jsonify({
            'success': True,
            'message': 'Conversation history cleared',
            'session_id': session_id,
        }), 200
    except Exception as exc:
        logger.error(f"Error clearing conversation history: {exc}")
        return jsonify({
            'error': True,
            'message': 'Failed to clear conversation history',
            'code': 'CLEAR_ERROR',
        }), 500


def impl_health(mcp_client, llm_service, yugabyte_server, get_initialization_metrics):
    """Implementation for GET /api/health."""
    try:
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'version': '1.0.0',
            'environment': os.getenv('FLASK_ENV', 'development'),
        }
        health_status['configuration'] = {
            'llm_configured': bool(Config.LLM_API_KEY),
            'oracle_configured': Config.is_oracle_enabled(),
            'pdf_configured': Config.is_pdf_enabled(),
        }
        service_status = {
            'mcp_client': 'initialized' if mcp_client else 'not_initialized',
            'llm_service': 'initialized' if llm_service else 'not_initialized',
            'yugabyte_server': (
                'initialized' if yugabyte_server else 'not_initialized'
            ),
        }
        if mcp_client:
            service_status['mcp_servers'] = mcp_client.get_server_status()
            service_status['available_tools'] = len(mcp_client.get_available_tools())
        health_status['services'] = service_status
        health_status['initialization_metrics'] = get_initialization_metrics()
        return jsonify(health_status), 200
    except Exception as exc:
        logger.error(f"Health check failed: {exc}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(exc),
            'timestamp': datetime.utcnow().isoformat(),
        }), 500


def impl_warmup(initialize_services):
    """Implementation for GET|POST /api/warmup."""
    try:
        from modules.serverless_optimizer import warmup_connections, get_cold_start_metrics
        initialize_services()
        return jsonify({
            'status': 'warmed_up',
            'timestamp': datetime.utcnow().isoformat(),
            'warmup_results': warmup_connections(),
            'metrics': get_cold_start_metrics(),
        }), 200
    except Exception as exc:
        logger.error(f"Warmup failed: {exc}")
        return jsonify({
            'status': 'warmup_failed',
            'error': str(exc),
            'timestamp': datetime.utcnow().isoformat(),
        }), 500


def impl_analytics_dashboard():
    """Implementation for GET /admin/analytics."""
    try:
        user = session.get('user', {})
        return render_template(
            'admin/analytics.html',
            user=user,
            metadata=MetadataConfig.to_dict(),
        )
    except Exception as exc:
        logger.error(f"Error serving analytics dashboard: {exc}", exc_info=True)
        return jsonify({
            'error': True,
            'message': 'Unable to load analytics dashboard',
            'code': 'TEMPLATE_ERROR',
        }), 500


def impl_get_analytics(activity_tracker):
    """Implementation for GET /api/analytics."""
    try:
        if not activity_tracker:
            return jsonify({
                'error': True,
                'message': 'Analytics not available',
                'code': 'ANALYTICS_UNAVAILABLE',
            }), 503

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
                    'code': 'INVALID_DATE',
                }), 400

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
            except ValueError:
                return jsonify({
                    'error': True,
                    'message': 'Invalid end_date format. Use ISO format (YYYY-MM-DD)',
                    'code': 'INVALID_DATE',
                }), 400

        stats = (
            activity_tracker.get_user_stats(user_id, start_dt, end_dt)
            if user_id
            else activity_tracker.get_global_stats(start_dt, end_dt)
        )
        return jsonify({
            'success': True,
            'stats': stats,
            'timestamp': datetime.utcnow().isoformat(),
        }), 200

    except Exception as exc:
        logger.error(f"Error retrieving analytics: {exc}", exc_info=True)
        return jsonify({
            'error': True,
            'message': 'Failed to retrieve analytics',
            'code': 'ANALYTICS_ERROR',
        }), 500


def impl_pricing():
    """Implementation for GET /pricing."""
    user = session.get('user')
    return render_template(
        'pricing.html', user=user, metadata=MetadataConfig.to_dict()
    )


def impl_create_checkout_session():
    """Implementation for POST /billing/create-checkout-session."""
    try:
        import stripe as _stripe
        _stripe.api_key = Config.STRIPE_SECRET_KEY
        user_email = session.get('user', {}).get('email', '')
        base_url = request.host_url.rstrip('/')
        checkout = _stripe.checkout.Session.create(
            mode='subscription',
            line_items=[{'price': Config.STRIPE_PRO_PRICE_ID, 'quantity': 1}],
            customer_email=user_email,
            success_url=base_url + '/?billing=success',
            cancel_url=base_url + '/pricing?billing=cancelled',
        )
        return jsonify({'url': checkout.url})
    except Exception as exc:
        logger.error(f"Stripe checkout creation failed: {exc}")
        return jsonify({'error': 'Failed to create checkout session'}), 500


def impl_stripe_webhook():
    """Implementation for POST /billing/webhook."""
    try:
        import stripe as _stripe
        _stripe.api_key = Config.STRIPE_SECRET_KEY
        payload = request.get_data()
        sig_header = request.headers.get('Stripe-Signature', '')
        event = _stripe.Webhook.construct_event(
            payload, sig_header, Config.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:
        logger.warning(f"Stripe webhook verification failed: {exc}")
        return jsonify({'error': 'Invalid webhook'}), 400

    try:
        if event['type'] == 'checkout.session.completed':
            customer_email = event['data']['object'].get('customer_email')
            if customer_email:
                billing.set_tier(customer_email, 'pro')
                logger.info(
                    f"Upgraded {customer_email} to pro via Stripe webhook"
                )
        elif event['type'] == 'customer.subscription.deleted':
            import stripe as _stripe2
            _stripe2.api_key = Config.STRIPE_SECRET_KEY
            customer_id = event['data']['object'].get('customer')
            if customer_id:
                customer = _stripe2.Customer.retrieve(customer_id)
                customer_email = customer.get('email')
                if customer_email:
                    billing.set_tier(customer_email, 'free')
                    logger.info(
                        f"Downgraded {customer_email} to free via Stripe webhook"
                    )
    except Exception as exc:
        logger.error(f"Error processing Stripe webhook event: {exc}")
        return jsonify({'error': 'Webhook handler error'}), 500

    return jsonify({'status': 'ok'})
