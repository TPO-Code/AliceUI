from __future__ import annotations
import time
from typing import Any, Dict, List, Optional, Tuple
import requests


Message = Dict[str, str]


class ToolServerError(Exception):
    """Raised when the Tool Server returns a non-2xx response.

    The exception message includes the HTTP method, path, status code,
    and any `detail` returned by the server when available.
    """
    pass


class ToolServerClient:
    """Tiny client for your local Tool Server (FastAPI).

    This client wraps the Tool Server’s HTTP API:
      - `/discover`: RAG-based tool selection for a conversation turn
      - `/execute`: execute a single tool call
      - `/execute/batch`: execute multiple tool calls (optional endpoint)
      - `/tools/reload`, `/config`, `/health`

    It also caches discovery results per conversation for the TTL
    returned by the server so you don’t re-query embeddings every turn.

    Example:
        >>> ts = ToolServerClient(base_url="http://localhost:7077")
        >>> messages = [{"role":"user", "content":"Remind me to feed the cat at 8am"}]
        >>> tools, alias_map = ts.build_openai_tools("conv-123", messages)
        >>> # use `tools` in your LLM request; when it returns tool_calls:
        >>> res = ts.execute("conv-123", "calendar_create_event", {
        ...     "title":"Feed the cat",
        ...     "start_time":"2025-08-12T08:00:00+01:00",
        ...     "end_time":"2025-08-12T08:05:00+01:00",
        ...     "event_type":"alarm",
        ... })
        >>> res["ok"]
        True
    """

    def __init__(self, base_url: str = "http://localhost:7077", timeout: int = 30):
        """Create a client.

        Args:
            base_url: Root URL where the Tool Server is listening.
            timeout: Per-request timeout in seconds.

        Notes:
            This class uses a persistent `requests.Session()` for connection reuse.
        """
        self.base_url = base_url.rstrip("/")
        self.s = requests.Session()
        self.timeout = timeout
        # conv_id -> (expires_at_epoch, tools_list, alias_map)
        self._cache: Dict[str, Tuple[float, List[Dict[str, Any]], Dict[str, str]]] = {}

    # ---------- HTTP helpers ----------
    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST JSON and return parsed JSON or {}.

        Raises:
            ToolServerError: on 4xx/5xx with human-friendly detail when available.
        """
        url = f"{self.base_url}{path}"
        r = self.s.post(url, json=payload, timeout=self.timeout)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:
                detail = r.text
            raise ToolServerError(f"POST {path} {r.status_code}: {detail}")
        return r.json() if r.content else {}

    def _get(self, path: str) -> Dict[str, Any]:
        """GET JSON and return parsed JSON or {}.

        Raises:
            ToolServerError: on 4xx/5xx.
        """
        url = f"{self.base_url}{path}"
        r = self.s.get(url, timeout=self.timeout)
        if r.status_code >= 400:
            raise ToolServerError(f"GET {path} {r.status_code}: {r.text}")
        return r.json() if r.content else {}

    # ---------- High-level API ----------
    def discover(
        self,
        conversation_id: str,
        messages: List[Message],
        k_tools: Optional[int] = None
    ) -> Dict[str, Any]:
        """Call `/discover` to get RAG-selected tool schemas for this turn.

        Args:
            conversation_id: Stable identifier for the chat/thread.
            messages: Recent conversation turns (each: {"role","content"}).
            k_tools: Optional override for max tools in fallback mode.

        Returns:
            The raw response dict, typically:
            {
              "method": "pallet" | "tools",
              "tools": [ { "type":"function", "function": {...} }, ... ],
              "alias_map": { "<api_name>": "<dotted_name>", ... },
              "cache_ttl_sec": 300,
              "debug": {...}
            }

        Notes:
            - `tools` are ready to drop into OpenAI-style chat.completions.
            - `alias_map` lets you translate from API-safe names back to
              your original dotted names (useful for logging).
        """
        payload: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "messages": messages,
        }
        if k_tools is not None:
            payload["k_tools"] = int(k_tools)
        return self._post("/discover", payload)

    def build_openai_tools(
        self,
        conversation_id: str,
        messages: List[Message],
        k_tools: Optional[int] = None,
        force_refresh: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """Cached discover: return `(tools, alias_map)` for LLM requests.

        Args:
            conversation_id: Stable identifier for the chat/thread.
            messages: Recent conversation turns.
            k_tools: Optional override for max tools (discover fallback).
            force_refresh: Bypass the local cache and re-discover.

        Returns:
            A tuple `(tools, alias_map)`:
              - tools: list of OpenAI-style tool specs for your LLM request
              - alias_map: mapping from API-safe name → dotted name

        Caching:
            The result is cached per conversation until the TTL provided by
            the Tool Server (`cache_ttl_sec`). Use `force_refresh=True`
            after you reload tools/pallets or change thresholds.
        """
        now = time.time()
        cached = self._cache.get(conversation_id)
        if not force_refresh and cached and cached[0] > now:
            return cached[1], cached[2]

        resp = self.discover(conversation_id, messages, k_tools=k_tools)
        tools = resp.get("tools", [])
        alias_map = resp.get("alias_map", {})
        ttl = int(resp.get("cache_ttl_sec", 0))
        self._cache[conversation_id] = (now + ttl, tools, alias_map)
        return tools, alias_map

    def execute(
        self,
        conversation_id: str,
        function: str,
        arguments: Dict[str, Any],
        tool_call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a single tool call via `/execute`.

        Args:
            conversation_id: Chat/thread ID (for logging/correlation).
            function: API-safe tool name (e.g., "calendar_create_event").
            arguments: Dict of arguments to pass to the tool.
            tool_call_id: Optional LLM tool_call id for round-tripping.

        Returns:
            Dict with keys:
              - ok (bool)
              - content (str)      # your tool’s JSON/string output when ok
              - error (str?)       # present when ok=False
              - duration_ms (int?) # execution time
              - trace (str?)       # stack trace on exception

        Raises:
            ToolServerError: on HTTP error status codes.

        Notes:
            Arguments are JSON-schema validated server-side before execution.
        """
        payload: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "function": function,
            "arguments": arguments,
        }
        if tool_call_id:
            payload["tool_call_id"] = tool_call_id
        return self._post("/execute", payload)

    def execute_batch(
        self,
        conversation_id: str,
        calls: List[Dict[str, Any]],
        parallel: bool = False
    ) -> Dict[str, Any]:
        """Execute multiple tool calls via `/execute/batch` (if available).

        Args:
            conversation_id: Chat/thread ID.
            calls: List of calls, each:
                   {"function": str, "arguments": dict, "tool_call_id": str|None}
            parallel: If True, the server may run calls concurrently.
                      Default False preserves order deterministically.

        Returns:
            Dict:
            {
              "results": [
                {
                  "tool_call_id": "...",
                  "function": "calendar_create_event",
                  "ok": true,
                  "content": "...",
                  "error": null,
                  "duration_ms": 42
                },
                ...
              ]
            }

        Raises:
            ToolServerError: if the endpoint is missing or returns an error.

        Notes:
            If your server does not expose `/execute/batch`, call `execute()`
            in a loop on the client instead.
        """
        payload = {"conversation_id": conversation_id, "calls": calls, "parallel": bool(parallel)}
        return self._post("/execute/batch", payload)

    # ---------- Utilities ----------
    def get_config(self) -> Dict[str, Any]:
        """Return the Tool Server’s active config (paths, ports, thresholds)."""
        return self._get("/config")

    def reload_tools(self) -> Dict[str, Any]:
        """Ask the server to rescan JSON/Python tool files."""
        return self._post("/tools/reload", {})

    def health(self) -> Dict[str, Any]:
        """Ping `/health` and return its JSON (usually `{\"status\":\"ok\"}`)."""
        return self._get("/health")
