import json
import time
from typing import List, Dict, Any, Optional

import requests
from PySide6.QtCore import QThread, Signal, Slot

from app.data.app_data import app_data

# =========================
# Local: Ollama
# =========================

class SendMessageWorker(QThread):
    completed_llm_call = Signal(str)
    failed_llm_call = Signal(str)

    def __init__(self, messages: List[Dict[str, str]], model: str, options=None):
        super().__init__()
        self.messages = messages
        self.model = model
        self.options = options

    @Slot()
    def run(self):
        try:
            print("contacting ollama")
            result = query_ollama(self.messages, self.model, self.options)
            message_content = result.get('message', {}).get('content', '')
            self.completed_llm_call.emit(message_content)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response else None
            body = ""
            try:
                body = e.response.text
            except:
                pass
            retry_after = e.response.headers.get("Retry-After") if e.response else None
            msg = f"HTTP {status}\nRetry-After: {retry_after}\n\n{body}"
            self.failed_llm_call.emit(msg)
        except Exception as e:
            self.failed_llm_call.emit(str(e))


def query_ollama(messages, model: str, options=None):
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options
    }

    response = requests.post(
        app_data.get("settings.ollama.url", "http://localhost:11434") + "/api/chat",
        json=payload,
        timeout=60
    )
    response.raise_for_status()
    print("ollama responded")
    return response.json()


class GetModelListWorker(QThread):
    completed_llm_call = Signal(list)
    failed_llm_call = Signal(str)

    def __init__(self):
        super().__init__()

    @Slot()
    def run(self):
        try:
            print("contacting ollama")
            result = get_available_models()
            print(json.dumps(result))
            self.completed_llm_call.emit(result)
        except Exception as e:
            self.failed_llm_call.emit(str(e))


def get_available_models():
    try:
        response = requests.get(
            app_data.get("settings.ollama.url", "http://localhost:11434") + "/api/tags",
            timeout=15
        )
        response.raise_for_status()
        models = response.json().get("models", [])
        return [model["name"] for model in models]
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to Ollama. Is the server running?")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(str(e))


# =========================
# Remote Providers
# =========================

class GetRemoteModelsWorker(QThread):
    """
    Fetches available model IDs for each provider.
    Input: list of providers [{"id","name","api_key","base_url",...}]
    Output: dict mapping provider_id -> list[str]
    """
    completed_llm_call = Signal(dict)
    failed_llm_call = Signal(str)

    def __init__(self, providers: List[Dict[str, Any]]):
        super().__init__()
        self.providers = providers

    @Slot()
    def run(self):
        try:
            out: Dict[str, List[str]] = {}
            for p in self.providers:
                pid = (p.get("id") or "").lower()
                key = p.get("api_key") or ""
                base = (p.get("base_url") or "").rstrip("/")

                if not key:
                    out[pid] = []
                    continue

                if pid in ("openai", "deepseek", "custom"):
                    base_url = base or (
                        "https://api.openai.com/v1" if pid == "openai"
                        else "https://api.deepseek.com/v1" if pid == "deepseek"
                        else ""  # custom requires base_url
                    )
                    if not base_url:
                        out[pid] = []
                        continue
                    out[pid] = _list_openai_compatible_models(key, base_url)

                elif pid == "anthropic":
                    out[pid] = _list_anthropic_models(key, base or "https://api.anthropic.com")

                else:
                    out[pid] = []

            self.completed_llm_call.emit(out)
        except Exception as e:
            self.failed_llm_call.emit(str(e))


def _list_openai_compatible_models(api_key: str, base_url: str) -> List[str]:
    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    def _do():
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()

    data = _with_retries(_do, max_retries=2, base_delay=1.0)
    items = data.get("data") or data.get("models") or []
    return [it["id"] if isinstance(it, dict) and "id" in it else str(it) for it in items]

def _list_anthropic_models(api_key: str, base_url: str) -> List[str]:
    # As of late 2024/2025, Anthropic exposes /v1/models for account-visible models.
    url = f"{base_url.rstrip('/')}/v1/models"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code == 404:
        # Some accounts/regions may not have this yet; fail soft.
        return []
    r.raise_for_status()
    data = r.json()
    items = data.get("data") or data.get("models") or []
    return [it["id"] if isinstance(it, dict) and "id" in it else str(it) for it in items]

class SendRemoteMessageWorker(QThread):
    completed_llm_call = Signal(str)
    failed_llm_call = Signal(str)

    def __init__(self,
                 messages: List[Dict[str, str]],
                 provider_id: str,
                 model: str,
                 api_key: str,
                 base_url: Optional[str] = None,
                 options: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.messages = messages
        self.provider_id = (provider_id or "").lower()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url or ""
        self.options = options or {}

    @Slot()
    def run(self):
        try:
            if self.provider_id in ("openai", "deepseek", "custom"):
                content = query_openai_compatible(
                    messages=self.messages,
                    model=self.model,
                    api_key=self.api_key,
                    base_url=resolve_openai_base_url(self.provider_id, self.base_url),
                    options=self.options
                )
            elif self.provider_id == "anthropic":
                content = query_anthropic(
                    messages=self.messages,
                    model=self.model,
                    api_key=self.api_key,
                    base_url=self.base_url or None,
                    options=self.options
                )
            else:
                raise ValueError(f"Unknown provider_id: {self.provider_id}")

            self.completed_llm_call.emit(content)

        except Exception as e:
            self.failed_llm_call.emit(str(e))


# ---------- OpenAI-compatible ----------

def _is_o1_family(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith("o1")  # o1, o1-mini, o1-preview, o1-*

def _split_system(messages):
    system_text = ""
    rest = []
    for m in messages or []:
        if m.get("role") == "system" and not system_text:
            system_text = m.get("content", "") or ""
        else:
            rest.append(m)
    return system_text, rest

def _adapt_for_o1(messages, options=None):
    """
    For o1-family models:
      - remove system role; prepend its text to the first user message
      - ensure max_completion_tokens is present
      - drop params that are unsupported
    """
    system_text, rest = _split_system(messages)
    out = []
    injected = False
    for m in rest:
        if m.get("role") == "user" and system_text and not injected:
            out.append({"role": "user", "content": f"{system_text}\n\n{m.get('content','')}"})
            injected = True
        else:
            out.append(m)
    if system_text and not injected:
        out.insert(0, {"role": "user", "content": system_text})

    opts = dict(options or {})
    # map max_tokens -> max_completion_tokens
    if "max_tokens" in opts and "max_completion_tokens" not in opts:
        opts["max_completion_tokens"] = opts.pop("max_tokens")
    # provide a sensible default if missing
    opts.setdefault("max_completion_tokens", 512)
    # remove unsupported knobs
    for k in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "n"):
        opts.pop(k, None)
    return out, opts

def resolve_openai_base_url(provider_id: str, user_base_url: str) -> str:
    if user_base_url:
        return user_base_url.rstrip("/")
    if provider_id == "openai":
        return "https://api.openai.com/v1"
    if provider_id == "deepseek":
        return "https://api.deepseek.com/v1"
    raise ValueError("Custom provider requires a base_url (OpenAI-compatible).")


def query_openai_compatible(messages, model, api_key, base_url, options=None) -> str:
    url = f"{base_url}/chat/completions"

    # ADAPT for o1-family
    payload_messages, payload_options = (messages, options or {})
    if _is_o1_family(model):
        payload_messages, payload_options = _adapt_for_o1(messages, options)

    payload = {
        "model": model,
        "messages": payload_messages,
        "stream": False,
        **({} if not payload_options else payload_options),
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _do():
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    data = _with_retries(_do, max_retries=3, base_delay=1.0)  # keep the backoff you added
    return data["choices"][0]["message"]["content"]


# -------------- Anthropic --------------

ANTHROPIC_VERSION = "2023-06-01"

def _split_system_and_messages(messages: List[Dict[str, str]]):
    system_text = ""
    remaining: List[Dict[str, str]] = []
    for m in messages:
        role = m.get("role", "")
        if role == "system" and not system_text:
            system_text = m.get("content", "")
        else:
            remaining.append(m)
    return system_text, remaining


def _to_anthropic_messages(msgs: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for m in msgs:
        role = m.get("role")
        if role in ("user", "assistant"):
            out.append({
                "role": role,
                "content": [{"type": "text", "text": m.get("content", "")}],
            })
    return out


def query_anthropic(messages, model, api_key, base_url=None, options=None) -> str:
    url = (base_url.rstrip("/") if base_url else "https://api.anthropic.com") + "/v1/messages"
    system_text, core_msgs = _split_system_and_messages(messages)
    body = {
        "model": model,
        "messages": _to_anthropic_messages(core_msgs),
        "max_tokens": (options.get("max_tokens") if options and "max_tokens" in options else 1024),
    }
    if system_text:
        body["system"] = system_text
    if options:
        for k in ("temperature", "top_p", "stop_sequences"):
            if k in options:
                body[k] = options[k]
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}

    def _do():
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        return resp.json()

    data = _with_retries(_do, max_retries=3, base_delay=1.0)
    for p in data.get("content", []):
        if p.get("type") == "text":
            return p.get("text", "")
    return json.dumps(data, indent=2)

def _parse_retry_after(resp) -> float | None:
    """Return seconds to wait, based on headers if provided."""
    if not resp:
        return None
    h = resp.headers or {}
    ra = h.get("Retry-After")
    if ra:
        try:
            return float(ra)
        except Exception:
            pass
    # Some providers include x-ratelimit-* reset hints; we just ignore specifics here.
    return None

def _with_retries(func, *, max_retries: int = 3, base_delay: float = 1.0):
    """Run func() with simple exponential backoff on 429/5xx."""
    delay = base_delay
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 429 or (status and 500 <= status < 600):
                wait = _parse_retry_after(e.response) or delay
                time.sleep(wait)
                delay *= 2
                last_exc = e
                continue
            raise
        except Exception as e:
            last_exc = e
            break
    if last_exc:
        raise last_exc