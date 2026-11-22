"""
watsonx_provider.py — IBM watsonx.ai Granite adapter.

Implements IAM token exchange (with caching / refresh), and translates
between the app's internal OpenAI-shaped message/tool dicts and the native
watsonx.ai text/chat endpoint.

The endpoint used:
  POST {WATSONX_URL}/ml/v1/text/chat?version=2024-05-01

No OpenAI client is used here; all HTTP is done via the standard `requests`
library that is already in requirements.txt.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
_WATSONX_API_VERSION = "2024-05-01"

# Refresh the token this many seconds before it actually expires.
_TOKEN_REFRESH_MARGIN_SECS = 60


# ---------------------------------------------------------------------------
# IAM token cache (module-level singleton; one entry per API key hash)
# ---------------------------------------------------------------------------

class _TokenCache:
    """Thread-safe-enough in-process token cache for a single API key."""

    __slots__ = ("_access_token", "_expires_at")

    def __init__(self):
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    def get(self) -> Optional[str]:
        """Return cached token if still valid, else None."""
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token
        return None

    def set(self, access_token: str, expires_in: int) -> None:
        """Store token; subtract refresh margin from expiry."""
        self._access_token = access_token
        self._expires_at = (
            time.monotonic() + max(0, expires_in - _TOKEN_REFRESH_MARGIN_SECS)
        )

    def clear(self) -> None:
        self._access_token = None
        self._expires_at = 0.0


_token_cache = _TokenCache()


# ---------------------------------------------------------------------------
# Public token helper
# ---------------------------------------------------------------------------

def get_iam_token(api_key: str, *, _cache: _TokenCache = _token_cache) -> str:
    """
    Return a valid IAM access token for *api_key*.

    Uses the module-level cache; performs a fresh exchange if the cached
    token is absent or within _TOKEN_REFRESH_MARGIN_SECS of expiry.

    The API key is never logged.
    """
    cached = _cache.get()
    if cached:
        return cached

    logger.info("Requesting new IAM access token")
    try:
        resp = requests.post(
            _IAM_TOKEN_URL,
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": api_key,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        # Never include the api_key in the message
        raise RuntimeError(f"IAM token exchange failed: {exc}") from exc

    body = resp.json()
    access_token = body.get("access_token")
    expires_in = int(body.get("expires_in", 3600))

    if not access_token:
        raise RuntimeError("IAM response did not contain access_token")

    _cache.set(access_token, expires_in)
    logger.info("IAM access token obtained (expires_in=%ds)", expires_in)
    return access_token


# ---------------------------------------------------------------------------
# Message / tool format conversion
# ---------------------------------------------------------------------------

def _to_watsonx_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert the app's internal message list to watsonx chat format.

    The app uses OpenAI-style dicts:
      {"role": "user"|"assistant"|"system"|"tool", "content": "...",
       "tool_calls": [...], "tool_call_id": "..."}

    watsonx native format for roles:
      system / user / assistant — identical structure.
      assistant with tool calls: role="assistant", tool_calls=[{id, type, function:{name, arguments}}]
      tool result:               role="tool", tool_call_id="...", content="..."

    The watsonx format is structurally the same as OpenAI for this endpoint,
    so conversion is mostly pass-through; we just drop unknown keys.
    """
    out = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "tool":
            # Tool result message
            out.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": content if content is not None else "",
            })
        elif role == "assistant":
            entry: Dict[str, Any] = {
                "role": "assistant",
                "content": content if content is not None else "",
            }
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                entry["tool_calls"] = _normalise_tool_calls(tool_calls)
            out.append(entry)
        else:
            # system or user
            out.append({"role": role, "content": content})

    return out


def _normalise_tool_calls(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ensure tool_calls list has the shape watsonx expects:
      [{"id": "...", "type": "function",
        "function": {"name": "...", "arguments": "<json-string>"}}]
    """
    result = []
    for tc in raw:
        fn = tc.get("function", {})
        args = fn.get("arguments", "{}")
        # arguments must be a string in both OpenAI and watsonx
        if isinstance(args, dict):
            args = json.dumps(args)
        result.append({
            "id": tc.get("id", ""),
            "type": "function",
            "function": {
                "name": fn.get("name", ""),
                "arguments": args,
            },
        })
    return result


def _to_watsonx_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert OpenAI-style tool defs to watsonx format.

    OpenAI / internal:
      [{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}]

    watsonx (same shape — passes through unchanged).
    """
    return tools  # watsonx accepts the same schema


def _from_watsonx_response(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a watsonx /ml/v1/text/chat response body to the app's internal
    response dict:
      {"content": str|None, "role": "assistant",
       "finish_reason": str, "tool_calls": [...]}

    watsonx response shape:
      {
        "results": [
          {
            "generated_text": "...",   # may be absent when tool_calls present
            "stop_reason": "...",
            "message": {
              "role": "assistant",
              "content": "...",        # may be null/absent
              "tool_calls": [...]      # present when model calls a tool
            }
          }
        ],
        "model_id": "...",
        ...
      }
    """
    results = body.get("results", [])
    if not results:
        return {"content": None, "role": "assistant", "finish_reason": "stop", "tool_calls": []}

    first = results[0]
    message = first.get("message", {})
    content = message.get("content") or first.get("generated_text") or None
    stop_reason = first.get("stop_reason", "stop")

    # Normalise tool_calls
    raw_tool_calls = message.get("tool_calls", [])
    tool_calls = []
    for tc in raw_tool_calls:
        fn = tc.get("function", {})
        args = fn.get("arguments", "{}")
        if isinstance(args, dict):
            args = json.dumps(args)
        tool_calls.append({
            "id": tc.get("id", ""),
            "type": "function",
            "function": {
                "name": fn.get("name", ""),
                "arguments": args,
            },
        })

    return {
        "content": content,
        "role": "assistant",
        "finish_reason": stop_reason,
        "tool_calls": tool_calls,
    }


# ---------------------------------------------------------------------------
# Main adapter class
# ---------------------------------------------------------------------------

class WatsonxProvider:
    """
    Thin adapter that exposes a send_message() interface compatible with the
    rest of LLMService, backed by the watsonx.ai native text/chat endpoint.

    Parameters
    ----------
    api_key      : IBM Cloud API key (never logged).
    project_id   : watsonx project UUID.
    model_id     : Foundation model identifier (e.g. 'ibm/granite-4-h-small').
    base_url     : watsonx.ai base URL (default: https://us-south.ml.cloud.ibm.com).
    max_tokens   : Maximum new tokens to generate.
    temperature  : Sampling temperature.
    timeout      : HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        project_id: str,
        model_id: str,
        base_url: str = "https://us-south.ml.cloud.ibm.com",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self.project_id = project_id
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        # Private cache instance so tests can inject their own
        self._token_cache = _TokenCache()
        logger.info(
            "WatsonxProvider initialised: model=%s project=%s url=%s",
            model_id, project_id, base_url,
        )

    def _get_token(self) -> str:
        return get_iam_token(self._api_key, _cache=self._token_cache)

    def send_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
    ) -> Dict[str, Any]:
        """
        Send a chat request to watsonx.ai and return the app-internal response dict.

        Raises RuntimeError on auth or HTTP failure (caller should catch and
        convert to LLMAPIError).
        """
        token = self._get_token()

        wx_messages = _to_watsonx_messages(messages)

        payload: Dict[str, Any] = {
            "model_id": self.model_id,
            "project_id": self.project_id,
            "messages": wx_messages,
            "parameters": {
                "max_new_tokens": self.max_tokens,
                "temperature": self.temperature,
            },
        }

        if tools:
            payload["tools"] = _to_watsonx_tools(tools)
            payload["tool_choice"] = tool_choice

        url = f"{self.base_url}/ml/v1/text/chat?version={_WATSONX_API_VERSION}"

        try:
            resp = requests.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"watsonx HTTP request failed: {exc}") from exc

        if resp.status_code == 401:
            # Token may have been invalidated server-side; clear cache and retry once
            logger.warning("watsonx 401 — clearing token cache and retrying")
            self._token_cache.clear()
            token = self._get_token()
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise RuntimeError(f"watsonx HTTP request failed on retry: {exc}") from exc

        if not resp.ok:
            raise RuntimeError(
                f"watsonx API error {resp.status_code}: {resp.text[:400]}"
            )

        return _from_watsonx_response(resp.json())
