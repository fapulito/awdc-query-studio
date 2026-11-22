"""
tests/test_watsonx_provider.py

Unit tests for the IBM watsonx.ai Granite adapter.

Coverage:
  1. IAM token exchange — request shape, caching, refresh-margin logic.
  2. Message / tool mapping — round-trip through format helpers.
  3. Provider selection — LLM_PROVIDER unset keeps OpenAI default;
     LLM_PROVIDER=watsonx selects the new path in create_llm_service_from_env.

All HTTP is mocked; no live calls; no real API key anywhere.
"""

import json
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.watsonx_provider import (
    _TokenCache,
    _from_watsonx_response,
    _to_watsonx_messages,
    _to_watsonx_tools,
    get_iam_token,
    WatsonxProvider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_cache() -> _TokenCache:
    return _TokenCache()


def _mock_iam_response(access_token: str = "tok_abc", expires_in: int = 3600):
    """Return a mock requests.Response for a successful IAM token exchange."""
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"access_token": access_token, "expires_in": expires_in}
    return resp


def _mock_watsonx_response(content: str = "Hello", tool_calls=None):
    """Return a mock requests.Response for a successful watsonx chat call."""
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    resp.json.return_value = {
        "results": [{"stop_reason": "stop", "message": message}],
        "model_id": "ibm/granite-4-h-small",
    }
    return resp


# ===========================================================================
# 1. IAM token exchange
# ===========================================================================

class TestIamTokenExchange:

    @patch("modules.watsonx_provider.requests.post")
    def test_exchange_request_shape(self, mock_post):
        """IAM exchange POSTs correct grant_type and no api_key in headers."""
        mock_post.return_value = _mock_iam_response("token_xyz")
        cache = _fresh_cache()

        result = get_iam_token("my-secret-key", _cache=cache)

        assert result == "token_xyz"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args

        # URL
        assert call_kwargs[0][0] == "https://iam.cloud.ibm.com/identity/token"

        # Body must contain the correct grant_type
        data = call_kwargs[1]["data"]
        assert data["grant_type"] == "urn:ibm:params:oauth:grant-type:apikey"
        assert data["apikey"] == "my-secret-key"

        # Authorization header must NOT appear in this request
        headers = call_kwargs[1].get("headers", {})
        assert "Authorization" not in headers

    @patch("modules.watsonx_provider.requests.post")
    def test_token_cached_no_second_request(self, mock_post):
        """Second call with valid cached token does not hit the IAM endpoint."""
        mock_post.return_value = _mock_iam_response("cached_tok", expires_in=3600)
        cache = _fresh_cache()

        t1 = get_iam_token("key", _cache=cache)
        t2 = get_iam_token("key", _cache=cache)

        assert t1 == t2 == "cached_tok"
        assert mock_post.call_count == 1

    @patch("modules.watsonx_provider.requests.post")
    def test_token_refreshed_after_expiry(self, mock_post):
        """An expired cached token triggers a fresh exchange."""
        mock_post.return_value = _mock_iam_response("first_tok", expires_in=3600)
        cache = _fresh_cache()

        get_iam_token("key", _cache=cache)
        # Manually expire the cache
        cache._expires_at = time.monotonic() - 1

        mock_post.return_value = _mock_iam_response("second_tok", expires_in=3600)
        t2 = get_iam_token("key", _cache=cache)

        assert t2 == "second_tok"
        assert mock_post.call_count == 2

    @patch("modules.watsonx_provider.requests.post")
    def test_refresh_margin_applied(self, mock_post):
        """Token expires_at is set to (expires_in - 60) seconds from now."""
        mock_post.return_value = _mock_iam_response("tok", expires_in=3600)
        cache = _fresh_cache()

        before = time.monotonic()
        get_iam_token("key", _cache=cache)
        after = time.monotonic()

        # expires_at should be ~3540 s from now (± a few ms for execution time)
        expected_min = before + 3600 - 60 - 1
        expected_max = after + 3600 - 60 + 1
        assert expected_min <= cache._expires_at <= expected_max

    @patch("modules.watsonx_provider.requests.post")
    def test_exchange_failure_raises(self, mock_post):
        """HTTP error from IAM raises RuntimeError (never ValueError)."""
        import requests as req_lib
        mock_post.side_effect = req_lib.RequestException("connection refused")
        cache = _fresh_cache()

        with pytest.raises(RuntimeError, match="IAM token exchange failed"):
            get_iam_token("key", _cache=cache)

    @patch("modules.watsonx_provider.requests.post")
    def test_missing_access_token_in_response_raises(self, mock_post):
        """IAM response without access_token field raises RuntimeError."""
        resp = MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {}  # no access_token
        mock_post.return_value = resp
        cache = _fresh_cache()

        with pytest.raises(RuntimeError, match="did not contain access_token"):
            get_iam_token("key", _cache=cache)


# ===========================================================================
# 2. Message / tool format mapping
# ===========================================================================

class TestMessageToolMapping:

    def test_user_system_messages_pass_through(self):
        """user and system messages convert unchanged."""
        msgs = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello"},
        ]
        out = _to_watsonx_messages(msgs)
        assert out == msgs

    def test_assistant_message_without_tool_calls(self):
        """Plain assistant message converts with no tool_calls key."""
        msgs = [{"role": "assistant", "content": "Sure."}]
        out = _to_watsonx_messages(msgs)
        assert out == [{"role": "assistant", "content": "Sure."}]
        assert "tool_calls" not in out[0]

    def test_assistant_message_with_tool_calls(self):
        """Assistant tool-call message carries normalised tool_calls list."""
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "yb_query_table", "arguments": '{"table": "foo"}'},
                    }
                ],
            }
        ]
        out = _to_watsonx_messages(msgs)
        assert len(out) == 1
        tc = out[0]["tool_calls"][0]
        assert tc["id"] == "call_1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "yb_query_table"
        assert tc["function"]["arguments"] == '{"table": "foo"}'

    def test_tool_result_message(self):
        """Tool result message converts to watsonx role=tool format."""
        msgs = [
            {"role": "tool", "tool_call_id": "call_1", "content": '{"rows": []}'}
        ]
        out = _to_watsonx_messages(msgs)
        assert out[0] == {"role": "tool", "tool_call_id": "call_1", "content": '{"rows": []}'}

    def test_tool_call_arguments_dict_serialised(self):
        """If arguments are already a dict (not string), they get JSON-serialised."""
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "fn", "arguments": {"k": "v"}},
                    }
                ],
            }
        ]
        out = _to_watsonx_messages(msgs)
        args = out[0]["tool_calls"][0]["function"]["arguments"]
        assert isinstance(args, str)
        assert json.loads(args) == {"k": "v"}

    def test_tools_pass_through(self):
        """Tool definitions are returned unchanged (same schema as OpenAI)."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "yb_query_table",
                    "description": "Query a table",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ]
        assert _to_watsonx_tools(tools) == tools

    def test_full_two_turn_round_trip(self):
        """
        A two-turn exchange (user → tool call → tool result → answer) round-trips
        through the format helpers with meaning preserved.
        """
        # Turn 1: user asks, model calls a tool
        messages_turn1 = [
            {"role": "system", "content": "You are a data assistant."},
            {"role": "user", "content": "How many animals were intake in May?"},
        ]

        # Simulate watsonx response with a tool call
        watsonx_resp_body = {
            "results": [
                {
                    "stop_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_42",
                                "type": "function",
                                "function": {
                                    "name": "yb_query_table",
                                    "arguments": json.dumps({"table": "laas_population_data"}),
                                },
                            }
                        ],
                    },
                }
            ]
        }
        internal_resp = _from_watsonx_response(watsonx_resp_body)
        assert internal_resp["role"] == "assistant"
        assert len(internal_resp["tool_calls"]) == 1
        tc = internal_resp["tool_calls"][0]
        assert tc["id"] == "call_42"
        assert tc["function"]["name"] == "yb_query_table"
        args = json.loads(tc["function"]["arguments"])
        assert args["table"] == "laas_population_data"

        # Turn 2: app appends assistant + tool result, then sends back
        messages_turn2 = messages_turn1 + [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": internal_resp["tool_calls"],
            },
            {"role": "tool", "tool_call_id": "call_42", "content": '{"rows": [{"month": "2024-05"}]}'},
        ]
        wx_messages = _to_watsonx_messages(messages_turn2)
        # tool result preserved
        tool_msg = wx_messages[-1]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_42"
        assert "2024-05" in tool_msg["content"]

        # Simulate final answer
        final_body = {
            "results": [
                {
                    "stop_reason": "stop",
                    "message": {"role": "assistant", "content": "There were 1,234 intakes in May."},
                }
            ]
        }
        final = _from_watsonx_response(final_body)
        assert final["content"] == "There were 1,234 intakes in May."
        assert final["tool_calls"] == []

    def test_from_watsonx_response_empty_results(self):
        """Empty results list returns a safe default dict."""
        result = _from_watsonx_response({})
        assert result["content"] is None
        assert result["tool_calls"] == []

    def test_from_watsonx_response_no_tool_calls_key(self):
        """Response without tool_calls key returns empty list."""
        body = {"results": [{"stop_reason": "stop", "message": {"role": "assistant", "content": "hi"}}]}
        result = _from_watsonx_response(body)
        assert result["content"] == "hi"
        assert result["tool_calls"] == []


# ===========================================================================
# 3. Provider selection via create_llm_service_from_env
# ===========================================================================

class TestProviderSelection:

    @patch("modules.llm_service._get_openai")
    def test_default_provider_is_openai(self, mock_get_openai):
        """With LLM_PROVIDER unset, provider defaults to openai."""
        mock_openai = MagicMock()
        mock_openai.OpenAI.return_value = MagicMock()
        mock_get_openai.return_value = mock_openai

        env = {"LLM_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=False):
            # Remove watsonx and provider vars if set by other tests
            for k in ("LLM_PROVIDER", "WATSONX_API_KEY", "WATSONX_PROJECT_ID"):
                os.environ.pop(k, None)

            from modules.llm_service import create_llm_service_from_env
            svc = create_llm_service_from_env()

        assert svc.config.provider == "openai"

    @patch("modules.watsonx_provider.requests.post")
    def test_watsonx_provider_selected(self, mock_post):
        """LLM_PROVIDER=watsonx selects the watsonx path."""
        mock_post.return_value = _mock_iam_response()

        env = {
            "LLM_PROVIDER": "watsonx",
            "WATSONX_API_KEY": "wx-key",
            "WATSONX_PROJECT_ID": "proj-123",
            "WATSONX_MODEL_ID": "ibm/granite-4-h-small",
            "WATSONX_URL": "https://us-south.ml.cloud.ibm.com",
        }
        with patch.dict(os.environ, env, clear=False):
            from modules.llm_service import create_llm_service_from_env
            svc = create_llm_service_from_env()

        assert svc.config.provider == "watsonx"
        assert svc.config.model == "ibm/granite-4-h-small"
        assert svc.config.watsonx_project_id == "proj-123"
        assert svc._watsonx is not None

    def test_watsonx_missing_api_key_raises(self):
        """LLM_PROVIDER=watsonx without WATSONX_API_KEY raises ValueError."""
        env = {"LLM_PROVIDER": "watsonx", "WATSONX_PROJECT_ID": "proj-123"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("WATSONX_API_KEY", None)
            from modules.llm_service import create_llm_service_from_env
            with pytest.raises(ValueError, match="WATSONX_API_KEY"):
                create_llm_service_from_env()

    def test_watsonx_missing_project_id_raises(self):
        """LLM_PROVIDER=watsonx without WATSONX_PROJECT_ID raises ValueError."""
        env = {"LLM_PROVIDER": "watsonx", "WATSONX_API_KEY": "some-key"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("WATSONX_PROJECT_ID", None)
            from modules.llm_service import create_llm_service_from_env
            with pytest.raises(ValueError, match="WATSONX_PROJECT_ID"):
                create_llm_service_from_env()

    @patch("modules.llm_service._get_openai")
    def test_openai_path_still_requires_llm_api_key(self, mock_get_openai):
        """OpenAI path still raises ValueError when LLM_API_KEY absent."""
        mock_get_openai.return_value = MagicMock()
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai"}, clear=False):
            os.environ.pop("LLM_API_KEY", None)
            from modules.llm_service import create_llm_service_from_env
            with pytest.raises(ValueError, match="LLM_API_KEY"):
                create_llm_service_from_env()
