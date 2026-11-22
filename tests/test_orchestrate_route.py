"""
Tests for POST /api/agent/query — the IBM watsonx Orchestrate service route.

Covered scenarios
-----------------
1. ORCHESTRATE_SERVICE_KEY unset → 503 SERVICE_DISABLED
2. Missing X-Service-Key header  → 401 UNAUTHORIZED
3. Wrong X-Service-Key value     → 401 UNAUTHORIZED
4. Correct key, mocked LLM/DB    → 200 with 'response' and 'queries' in payload
5. Correct key but empty message → 400 (delegated to impl_chat)
6. Existing /api/chat still returns 401 without a session cookie (unchanged)
"""

import json
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub missing optional packages so app.py can be imported in a slim venv.
# These stubs are only installed in sys.modules if the real package is absent.
# ---------------------------------------------------------------------------

def _stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)


if "authlib" not in sys.modules:
    # Build a minimal package hierarchy so sub-module imports work.
    _authlib = types.ModuleType("authlib")
    _authlib.__path__ = []  # mark as package
    sys.modules["authlib"] = _authlib

    _authlib_int = types.ModuleType("authlib.integrations")
    _authlib_int.__path__ = []
    sys.modules["authlib.integrations"] = _authlib_int
    _authlib.__dict__["integrations"] = _authlib_int

    _OAuth = type("OAuth", (), {
        "__init__": lambda self, app=None: None,
        "register": lambda self, *a, **kw: None,
    })
    _fc = types.ModuleType("authlib.integrations.flask_client")
    _fc.OAuth = _OAuth
    sys.modules["authlib.integrations.flask_client"] = _fc

    _OAuthError = type("OAuthError", (Exception,), {})
    _bc = types.ModuleType("authlib.integrations.base_client")
    _bc.OAuthError = _OAuthError
    sys.modules["authlib.integrations.base_client"] = _bc

if "stripe" not in sys.modules:
    _stub_module("stripe")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GOOD_KEY = "test-service-key-abc123"


@pytest.fixture
def app():
    """Create test Flask app from app.py entry point."""
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Helper: mock LLM + MCP so impl_chat returns a real 200
# ---------------------------------------------------------------------------

def _mock_chat_services(mock_mcp, mock_llm):
    """Configure minimal mocks so impl_chat returns a 200 payload."""
    mock_mcp.get_tools_for_llm.return_value = []
    mock_llm.create_system_prompt.return_value = "system prompt"
    # process_conversation must return a 4-tuple (content, tool_calls, queries, last_result)
    mock_llm.process_conversation.return_value = (
        "Here is the monthly count.",
        [],
        ["SELECT month, COUNT(*) FROM intakes GROUP BY month"],
        None,
    )


# ---------------------------------------------------------------------------
# 1. ORCHESTRATE_SERVICE_KEY unset → 503
# ---------------------------------------------------------------------------

class TestServiceKeyUnset:

    @patch.dict(os.environ, {}, clear=False)
    def test_returns_503_when_key_env_unset(self, client):
        # Remove the env var if it was set by a parent environment
        env_without_key = {k: v for k, v in os.environ.items()
                          if k != "ORCHESTRATE_SERVICE_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            response = client.post(
                "/api/agent/query",
                json={"message": "hello"},
                content_type="application/json",
            )
        assert response.status_code == 503
        data = json.loads(response.data)
        assert data["error"] is True
        assert data["code"] == "SERVICE_DISABLED"


# ---------------------------------------------------------------------------
# 2 & 3. Missing / wrong key → 401
# ---------------------------------------------------------------------------

class TestBadKey:

    @patch.dict(os.environ, {"ORCHESTRATE_SERVICE_KEY": GOOD_KEY})
    def test_missing_key_header_returns_401(self, client):
        response = client.post(
            "/api/agent/query",
            json={"message": "hello"},
            content_type="application/json",
        )
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["error"] is True
        assert data["code"] == "UNAUTHORIZED"

    @patch.dict(os.environ, {"ORCHESTRATE_SERVICE_KEY": GOOD_KEY})
    def test_wrong_key_returns_401(self, client):
        response = client.post(
            "/api/agent/query",
            json={"message": "hello"},
            headers={"X-Service-Key": "completely-wrong"},
            content_type="application/json",
        )
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["error"] is True
        assert data["code"] == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# 4. Correct key → 200 with answer payload
# ---------------------------------------------------------------------------

class TestCorrectKey:

    @patch("app.mcp_client")
    @patch("app.llm_service")
    @patch.dict(os.environ, {"ORCHESTRATE_SERVICE_KEY": GOOD_KEY})
    def test_correct_key_returns_200_with_response(self, mock_llm, mock_mcp, client):
        _mock_chat_services(mock_mcp, mock_llm)

        response = client.post(
            "/api/agent/query",
            json={"message": "How many intakes per month?"},
            headers={"X-Service-Key": GOOD_KEY},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "response" in data
        assert isinstance(data["response"], str)
        assert len(data["response"]) > 0
        assert "queries" in data

    @patch("app.mcp_client")
    @patch("app.llm_service")
    @patch.dict(os.environ, {"ORCHESTRATE_SERVICE_KEY": GOOD_KEY})
    def test_empty_message_returns_400(self, mock_llm, mock_mcp, client):
        """impl_chat rejects empty messages regardless of auth method."""
        _mock_chat_services(mock_mcp, mock_llm)

        response = client.post(
            "/api/agent/query",
            json={"message": ""},
            headers={"X-Service-Key": GOOD_KEY},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"] is True


# ---------------------------------------------------------------------------
# 5. /api/chat remains session-guarded (unchanged behaviour)
# ---------------------------------------------------------------------------

class TestExistingChatRouteUnchanged:

    def test_chat_without_session_still_returns_401(self, client):
        """The original route must still reject unauthenticated callers."""
        response = client.post(
            "/api/chat",
            json={"message": "hello"},
            content_type="application/json",
        )
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["error"] is True
        assert data["code"] == "UNAUTHORIZED"
