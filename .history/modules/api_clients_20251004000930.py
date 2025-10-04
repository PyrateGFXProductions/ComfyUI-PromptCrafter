import requests
# Standard library imports
import os
import io
import json
import time
import inspect
import threading
from typing import Callable, Dict, Any

# Local module imports
import base64
from . import config

# ------------------------------------------------------------------------------------
# API Client Abstraction
# ------------------------------------------------------------------------------------

class BaseAPIClient:
    """Abstract base class for all API clients."""
    def __init__(self, provider, client_config):
        self.provider = provider
        self.config = client_config
        self.api_key = client_config.get("api_key")
        self.base_url = client_config.get("base_url")

    def _get_headers(self): return {}
    def _get_url(self, model_id): raise NotImplementedError(f"URL generation not implemented for {self.provider}")
    def _build_payload(self, model_id, prompt, images_b64, **kwargs): raise NotImplementedError(f"Payload building not implemented for {self.provider}")
    def _parse_response(self, data): raise NotImplementedError(f"Response parsing not implemented for {self.provider}")

    def query(self, model_id, prompt, images_b64=None, timeout=60, **kwargs):
        """Handles a standard query by building a payload, making a request, and parsing the response."""
        headers = self._get_headers()
        url = self._get_url(model_id)
        payload = self._build_payload(model_id, prompt, images_b64, **kwargs)
        result = self._make_request(url=url, headers=headers, payload=payload, timeout=timeout)
        ok = result[0]
        data_or_err = result[1]
        if not ok: return False, data_or_err # Return the error message directly
        return self._parse_response(data_or_err) # On success, parse the data

    def _format_http_error(self, e: requests.exceptions.HTTPError) -> str:
        """Formats a human-readable error message from an HTTPError exception."""
        status_code = e.response.status_code
        reason = e.response.reason
        error_details = f"HTTP {status_code} {reason}."
        try:
            error_json = e.response.json()
            error_message = error_json.get("error", {}).get("message") or error_json.get("error") or json.dumps(error_json)
            error_details += f" Details: {error_message}"
        except json.JSONDecodeError:
            error_details += f" Raw response: {e.response.text[:500]}"
        return f"{self.provider.capitalize()} API Error: {error_details}"

    def _make_request(self, url, headers, payload, timeout):
        """A shared helper for making POST requests and handling common HTTP/network errors."""
        try:
            response = config.SHARED_SESSION.post(url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            return True, response.json(), response.status_code
        except requests.exceptions.RequestException as e:
            if isinstance(e, requests.exceptions.ConnectionError):
                return False, f"{self.provider.capitalize()} API Error: Could not connect to the server at {url}. Please ensure the server is running and the address is correct.", 503
            if isinstance(e, requests.exceptions.Timeout):
                return False, f"{self.provider.capitalize()} API Error: The request timed out after {timeout} seconds. The model may be loading. Try increasing the 'timeout' setting.", 408
            if isinstance(e, requests.exceptions.HTTPError):
                return False, self._format_http_error(e), e.response.status_code
            return False, f"{self.provider.capitalize()} API connection error: {e}", 500

    def is_configured(self):
        return bool(self.api_key)

class OllamaClient(BaseAPIClient):
    """Client for handling local Ollama models."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._chat_api_unsupported = set() # Stores models that don't support /api/chat
        self._lock = threading.Lock() # For thread-safe access to the unsupported set

    def is_configured(self): return True

    def query(self, model_id, prompt, images_b64=None, timeout=60, temperature=None, seed=None, prefer_chat=False, **kwargs):
        use_chat_first = (prefer_chat or bool(images_b64)) and model_id not in self._chat_api_unsupported
        endpoints_to_try = ["chat", "generate"] if use_chat_first else ["generate", "chat"]

        last_err = None
        last_status_code = None
        for endpoint in endpoints_to_try:
            # Skip generate if we already know chat is the only way (e.g. for images)
            if endpoint == "generate" and use_chat_first and not prefer_chat:
                continue

            payload = self._build_payload(endpoint, model_id, prompt, images_b64, temperature, seed)
            ok, data_or_err, status_code = self._make_request(url=f"{self.base_url}/api/{endpoint}", headers={}, payload=payload, timeout=timeout)

            if ok:
                return self._parse_response(data_or_err)

            last_status_code = status_code
            if status_code == 404 and endpoint == "chat":
                with self._lock:
                    self._chat_api_unsupported.add(model_id)
                    print(f"\033[94m[PromptCrafterer] Ollama model '{model_id}' does not support /api/chat. Switching to /api/generate.\033[0m")
            else:
                last_err = data_or_err
                if last_status_code == 503: # Connection Error
                    break # Don't retry if the server is down
        return False, (last_err or "Unknown Ollama error")

    def _build_payload(self, endpoint, model, prompt, images_b64, temperature=None, seed=None, **kwargs):
        payload = {"model": model, "stream": False, "options": {}}
        if endpoint == "chat":
            msg = {"role": "user", "content": prompt}
            if images_b64: msg["images"] = images_b64
            payload["messages"] = [msg]
        else:
            payload["prompt"] = prompt
            if images_b64: payload["images"] = images_b64
        if temperature is not None: payload["options"]["temperature"] = float(temperature)
        if seed is not None and int(seed) >= 0: payload["options"]["seed"] = int(seed)
        if not payload["options"]:
            del payload["options"]
        return payload

    def _parse_response(self, data):
        content = ""
        if "response" in data: # /api/generate
            content = data.get("response", "")
        elif "message" in data and isinstance(data["message"], dict): # /api/chat
            content = data["message"].get("content", "")
        
        return (True, content.strip()) if content else (False, f"Could not find response content in Ollama output: {json.dumps(data)}")

# --- Client Registry and Dispatchers ---
OLLAMA_CLIENT = OllamaClient(provider="ollama", client_config={"base_url": config.OLLAMA_BASE})

def check_ollama_status():
    """Performs a single, clear check for Ollama connectivity at startup."""
    status, _, _ = _get_all_model_data(log_errors=False)
    if status == 'ok':
        print(f"\033[92m[PromptCrafterer] Ollama is Online. Models will be available.\033[0m")
    else:
        print(f"\033[91m[PromptCrafterer] Ollama is OFFLINE. Local models will not be available.\033[0m")

def _filter_kwargs(func: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Filters a dictionary of keyword arguments to only include those accepted by a function."""
    sig = inspect.signature(func)
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()): return kwargs
    allowed_keys = {p.name for p in sig.parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    return {k: v for k, v in kwargs.items() if k in allowed_keys}

def query_model_auto(model, prompt, images=None, **kwargs):
    """Dispatches a text/vision query to the appropriate API client."""
    from . import utils
    images_b64 = [utils.encode_image(im) for im in images if im is not None] if images else []
    utils._debug_print(kwargs.get("debug_mode", False), kwargs.get("debug_title", "") or f"Query to {model}", prompt)

    client = OLLAMA_CLIENT
    model_id = model
    filtered_kwargs = _filter_kwargs(client.query, kwargs)
    return client.query(model_id, prompt, images_b64=images_b64, **filtered_kwargs)

def _reason_with_model(model, prompt, images=None, **kwargs):
    """A helper function that asks a model a question where the expected answer is JSON."""
    from . import utils

    # Standardize the use_chat_api/prefer_chat parameter
    if 'use_chat_api' in kwargs:
        kwargs['prefer_chat'] = kwargs.pop('use_chat_api')

    # Set defaults for reasoning tasks
    kwargs.setdefault('prefer_chat', True)
    kwargs.setdefault('temperature', 0.0)
    kwargs.setdefault('timeout', 40)

    ok, resp = query_model_auto(model, prompt, images=images, **kwargs)
    if not ok: return False, f"Model reasoning query failed: {resp}"
    try:
        return True, utils._extract_and_parse_json(resp)
    except utils.JSONParsingError as e:
        return False, f"Failed to parse JSON from model response. Error: {e}"

# ------------------------------------------------------------------------------------
# Model Discovery
# ------------------------------------------------------------------------------------

_model_cache = {}
_cache_lock = threading.Lock()
CACHE_EXPIRATION_SECONDS = 300 # 5 minutes

def _is_vision_model(model_details: dict) -> bool:
    """Checks if an Ollama model is vision-capable based on its metadata."""
    details = model_details.get("details", {})
    families = details.get("families") or []
    architecture = details.get("general.architecture", "")
    
    VISION_FAMILIES = {"llava", "moondream", "bakllava", "fuyu", "idefics", "qwen2.5vl"}
    
    return any(f in VISION_FAMILIES for f in families) or 'clip' in architecture or 'vision' in architecture or 'mmproj' in architecture


def _get_models_by_type(model_type):
    """
    Gets models of a specific type (vision, text, or all) by inspecting metadata.
    Results are cached for a short period to improve performance.
    """
    global _model_cache
    with _cache_lock:
        now = time.time()
        if model_type in _model_cache:
            cached_data, timestamp = _model_cache[model_type]
            if now - timestamp < CACHE_EXPIRATION_SECONDS:
                return cached_data

    ollama_status, ollama_models_details, _ = _get_all_model_data()

    local_models = []
    if ollama_status == 'ok':
        for m in ollama_models_details:
            is_vision = _is_vision_model(m)
            if model_type == "all":
                local_models.append(m["name"])
            elif model_type == "vision" and is_vision:
                local_models.append(m["name"])
            elif model_type == "text" and not is_vision:
                local_models.append(m["name"])

    available_models = sorted(list(set(local_models)))

    if not available_models:
        if ollama_status == 'connection_error':
            available_models = ["OLLAMA_OFFLINE_CHECK_CONSOLE"]
        else:
            available_models = ["NO_MODELS_FOUND_OR_CONFIGURED"]
    else:
        preferred_fallback = config.FALLBACK_VISION_MODEL if model_type == "vision" else config.FALLBACK_TEXT_MODEL
        if preferred_fallback in available_models:
            available_models.remove(preferred_fallback)
            available_models.insert(0, preferred_fallback)
    
    with _cache_lock:
        _model_cache[model_type] = (available_models, time.time())

    return available_models

def _get_all_model_data(log_errors=True):
    """
    Fetches all model data from all sources (Ollama, remote APIs) ONCE and caches it.
    This is the new single source of truth for model discovery.
    """
    # 1. Fetch Ollama Models
    ollama_status, ollama_models = 'other_error', []
    try:
        resp = config.SHARED_SESSION.get(f"{config.OLLAMA_BASE}/api/tags", timeout=3)
        resp.raise_for_status()
        ollama_models = resp.json().get("models", [])
        ollama_status = 'ok'
    except requests.exceptions.ConnectionError as e:
        ollama_status = 'connection_error'
        if log_errors: print(f"\033[91m[PromptCrafterer] Ollama connection failed. Is it running at {config.OLLAMA_BASE}? Error: {e}\033[0m")
    except requests.exceptions.RequestException as e:
        if log_errors: print(f"\033[93m[PromptCrafterer] Warning: Could not fetch Ollama models. Error: {e}\033[0m")

    # 2. Fetch Remote API Models
    # This part is removed as we no longer have built-in remote API configs.
    return ollama_status, ollama_models, None

def get_vision_models(): return _get_models_by_type("vision") # noqa
def get_text_models(): return _get_models_by_type("text") # noqa
def get_all_models(): return _get_models_by_type("all") # noqa
