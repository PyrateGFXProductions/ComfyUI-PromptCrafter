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
from . import json_utils
# ------------------------------------------------------------------------------------
# API Client Abstraction
# ------------------------------------------------------------------------------------

class OllamaClient:
    """Client for handling local Ollama models."""
    def __init__(self, base_url):
        self.provider = "ollama"
        self.base_url = base_url
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
                    print(f"\033[94m[PromptCrafter] Ollama model '{model_id}' does not support /api/chat. Switching to /api/generate.\033[0m")
            else:
                last_err = data_or_err
                if last_status_code == 503: # Connection Error
                    break # Don't retry if the server is down
        return False, (last_err or "Unknown Ollama error")

    def _format_http_error(self, e: requests.exceptions.HTTPError) -> str:
        """Formats a human-readable error message from an HTTPError exception."""
        status_code = e.response.status_code
        reason = e.response.reason
        error_details = f"HTTP {status_code} {reason}."
        try:
            error_json = e.response.json()
            if isinstance(error_json, dict):
                error_content = error_json.get("error")
                if isinstance(error_content, dict):
                    error_message = error_content.get("message") or json.dumps(error_content)
                else:
                    error_message = error_content or json.dumps(error_json)
            else:
                error_message = str(error_json)
            error_details += f" Details: {error_message}"
        except json.JSONDecodeError:
            error_details += f" Raw response: {e.response.text[:500]}"
        return f"{self.provider.capitalize()} API Error: {error_details}"

    def _make_request(self, url, headers, payload, timeout):
        """A shared helper for making POST requests and handling common HTTP/network errors."""
        try:
            session = config.SHARED_SESSION if config.SHARED_SESSION is not None else requests
            response = session.post(url, headers=headers, json=payload, timeout=timeout)
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
            if not content: # FIX: Check for 'thinking' field if 'content' is empty
                content = data["message"].get("thinking", "")
        
        return (True, content.strip()) if content else (False, f"Could not find response content in Ollama output: {json.dumps(data)}")

class OpenAICompatibleClient(OllamaClient):
    """
    Client for handling any OpenAI-compatible server (e.g., LM Studio, text-generation-webui).
    Inherits from OllamaClient to reuse _make_request and _format_http_error.
    """
    def __init__(self, base_url, provider_name="openai_compatible"):
        super().__init__(base_url)
        self.provider = provider_name

    def query(self, model_id, prompt, images_b64=None, timeout=60, temperature=None, seed=None, **kwargs):
        # LM Studio's OpenAI endpoint doesn't have a separate /generate, so we only use one endpoint.
        payload = self._build_payload("chat", model_id, prompt, images_b64, temperature, seed)
        # The endpoint is /v1/chat/completions
        ok, data_or_err, _ = self._make_request(url=f"{self.base_url}/v1/chat/completions", headers={}, payload=payload, timeout=timeout)
        return self._parse_response(data_or_err) if ok else (False, data_or_err)

    def _build_payload(self, endpoint, model, prompt, images_b64, temperature=None, seed=None, **kwargs):
        # Build a payload that mimics the OpenAI Chat Completions API structure.
        messages = []
        user_content = [{"type": "text", "text": prompt}]
        if images_b64:
            for img_b64 in images_b64:
                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
        
        messages.append({"role": "user", "content": user_content})
        
        payload = {"model": model, "messages": messages, "stream": False}
        if temperature is not None: payload["temperature"] = float(temperature)
        if seed is not None and int(seed) >= 0: payload["seed"] = int(seed)
        return payload

    def _parse_response(self, data):
        # Parse the OpenAI-like response structure.
        try:
            content = data["choices"][0]["message"]["content"]
            return (True, content.strip()) if content else (False, f"Could not find response content in {self.provider.capitalize()} output.")
        except (KeyError, IndexError, TypeError) as e:
            return False, f"Error parsing {self.provider.capitalize()} response: {e}. Response: {json.dumps(data)}"

# --- Client Registry and Dispatchers ---
CLIENT_REGISTRY = {
    "ollama": OllamaClient(config.LOCAL_SERVER_CONFIG["ollama"]["base_url"]),
    "lmstudio": OpenAICompatibleClient(config.LOCAL_SERVER_CONFIG["lmstudio"]["base_url"], provider_name="lmstudio"),
    "text-generation-webui": OpenAICompatibleClient(config.LOCAL_SERVER_CONFIG["text-generation-webui"]["base_url"], provider_name="text-generation-webui"),
}

def check_local_server_status():
    """Performs a single, clear check for all configured local server connectivity at startup."""
    for provider, provider_config in config.LOCAL_SERVER_CONFIG.items():
        try:
            if not provider_config.get("enabled", True):
                continue
            
            status, models = _get_provider_models(provider, provider_config, log_errors=False) # log_errors=False to avoid double printing
            
            provider_name = provider.capitalize()
            if status == 'ok':
                model_count = len(models)
                print(f"\033[92m[PromptCrafter] {provider_name} is online. Found {model_count} model(s).\033[0m")
            elif status == 'connection_error':
                print(f"\033[91m[PromptCrafter] {provider_name} is OFFLINE. Is it running at {provider_config['base_url']}?\033[0m")
        except Exception as e:
            # This is a safety net to prevent any single provider check from crashing the whole startup.
            print(f"\033[91m[PromptCrafter] An unexpected error occurred while checking status for {provider.capitalize()}: {e}\033[0m")

def _filter_kwargs(func: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Filters a dictionary of keyword arguments to only include those accepted by a function."""
    sig = inspect.signature(func)
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()): return kwargs
    allowed_keys = {p.name for p in sig.parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    return {k: v for k, v in kwargs.items() if k in allowed_keys}

def query_model_auto(model, prompt, images=None, **kwargs):
    """Dispatches a text/vision query to the appropriate API client."""
    from . import utils # Keep this local import to avoid circular dependency at module level
    images_b64 = [utils.encode_image(im) for im in images if im is not None] if images else []
    utils._debug_print(kwargs.get("debug_mode", False), kwargs.get("debug_title", "") or f"Query to {model}", prompt)
    
    try:
        provider, model_id = model.split('/', 1)
    except ValueError:
        return False, f"Invalid model format '{model}'. Expected 'provider/model_name'."

    client = CLIENT_REGISTRY.get(provider.lower())
    if not client:
        return False, f"No client configured for provider '{provider}'."

    filtered_kwargs = _filter_kwargs(client.query, kwargs)
    return client.query(model_id, prompt, images_b64=images_b64, **filtered_kwargs)

def _reason_with_model(model, prompt, images=None, **kwargs):
    # Standardize the use_chat_api/prefer_chat parameter
    if 'use_chat_api' in kwargs:
        kwargs['prefer_chat'] = kwargs.pop('use_chat_api')

    # Set defaults for reasoning tasks, but allow timeout to be overridden
    kwargs.setdefault('prefer_chat', True)
    kwargs.setdefault('temperature', 0.0)
    kwargs.setdefault('timeout', 120) # Default, but can be overridden by user

    ok, resp = query_model_auto(model, prompt, images=images, **kwargs)
    if not ok: return False, f"Model reasoning query failed: {resp}"
    try:
        return True, json_utils._extract_and_parse_json(resp)
    except json_utils.JSONParsingError as e:
        return False, f"Failed to parse JSON from model response. Error: {e}"

# ------------------------------------------------------------------------------------
# Model Discovery
# ------------------------------------------------------------------------------------

_model_cache = {}
_cache_lock = threading.Lock()
CACHE_EXPIRATION_SECONDS = 300 # 5 minutes

class ModelInspector:
    """A helper class to determine model capabilities from its metadata."""
    
    # A centralized set of keywords to identify vision models.
    # This makes it easy to update as new model families are released.
    VISION_KEYWORDS = {
        "llava", "moondream", "bakllava", "fuyu", "idefics", 
        "qwen", "qwen2.5vl", "qwen3-vl", "vision", "clip", "mmproj"
    }

    @classmethod
    def is_vision_model(cls, model_details: dict) -> bool:
        """
        Determines if a model is vision-capable using a multi-faceted approach.
        """
        # Strategy 1: Deep inspection of Ollama's detailed metadata.
        # This is the most reliable method when available.
        details = model_details.get("details", {})
        if details:
            families = details.get("families") or []
            architecture = details.get("general.architecture", "")
            
            if any(f in cls.VISION_KEYWORDS for f in families):
                return True
            if any(kw in architecture for kw in cls.VISION_KEYWORDS):
                return True

        # Strategy 2: Fallback to checking the model's name (ID).
        # This is essential for OpenAI-compatible servers like LM Studio.
        model_id = model_details.get("id", "").lower()
        if any(kw in model_id for kw in cls.VISION_KEYWORDS):
            return True
            
        return False

def _get_models_by_type(model_type):
    """
    Gets models of a specific type (vision, text, or all) by inspecting metadata.
    Results are cached for a short period to improve performance.
    """
    # The logic here is now more complex due to multiple providers, so we'll
    # rely on the more robust _get_all_model_data to handle caching internally.
    # This function will just filter the results from the main source of truth.

    global _model_cache
    with _cache_lock:
        now = time.time()
        if model_type in _model_cache:
            cached_data, timestamp = _model_cache[model_type]
            if now - timestamp < CACHE_EXPIRATION_SECONDS:
                return cached_data

    all_models_details = _get_all_model_data()

    filtered_models = []
    for m in all_models_details:
        is_vision = ModelInspector.is_vision_model(m)
        # The name is now pre-formatted with the provider prefix
        model_name = m["name"] 
        if model_type == "all":
            filtered_models.append(model_name)
        elif model_type == "vision" and is_vision:
            filtered_models.append(model_name)
        elif model_type == "text" and not is_vision:
            filtered_models.append(model_name)

    available_models = sorted(list(set(filtered_models)))

    if not available_models:
        available_models = ["NO_MODELS_FOUND_CHECK_CONSOLE"]
    else:
        # The fallback model now needs to be prefixed with its provider
        preferred_fallback_base = config.FALLBACK_VISION_MODEL if model_type == "vision" else config.FALLBACK_TEXT_MODEL
        # Find the first available model that ends with the preferred base name (e.g., find '.../qwen2.5vl:7b')
        preferred_model_found = next((m for m in available_models if m.endswith(f"/{preferred_fallback_base}")), None)
        if preferred_model_found:
            available_models.remove(preferred_model_found)
            available_models.insert(0, preferred_model_found)
    
    with _cache_lock:
        _model_cache[model_type] = (available_models, time.time())
    return available_models

def _get_provider_models(provider, provider_config, log_errors=True):
    """Fetches models from a single configured provider."""
    base_url = provider_config["base_url"]
    status, models = 'other_error', []
    session = config.SHARED_SESSION or requests
    try:
        if provider == "ollama":
            resp = session.get(f"{base_url}/api/tags", timeout=5)
        elif provider in ["lmstudio", "text-generation-webui"]:
            resp = session.get(f"{base_url}/v1/models", timeout=3)
        else:
            return 'not_supported', []

        resp.raise_for_status()
        data = resp.json()

        if provider == "ollama":
            models = data.get("models", [])
        elif provider in ["lmstudio", "text-generation-webui"]:
            # LM Studio's response is OpenAI-like: {"object": "list", "data": [{"id": "model-name", ...}]}
            # We'll reformat it to match Ollama's structure for consistency.
            lm_models = data.get("data", [])
            models = [{"name": m.get("id"), "id": m.get("id"), "details": {}} for m in lm_models]

        # Add the provider prefix to the name for UI display and dispatching
        for model_info in models:
            model_info["name"] = f"{provider}/{model_info.get('name') or model_info.get('id')}"

        status = 'ok'
    except requests.exceptions.ConnectionError as e:
        status = 'connection_error'
        if log_errors: print(f"\033[93m[PromptCrafter] Info: {provider.capitalize()} is offline. If you use it, please ensure it's running at {base_url}.\033[0m")
    except requests.exceptions.RequestException as e:
        if log_errors: print(f"\033[93m[PromptCrafter] Warning: Could not fetch {provider.capitalize()} models. Error: {e}\033[0m")
    return status, models

def _get_all_model_data(log_errors=True):
    """Fetches all model data from all configured local servers."""
    all_models = []
    for provider, provider_config in config.LOCAL_SERVER_CONFIG.items():
        if provider_config.get("enabled", True):
            _, models = _get_provider_models(provider, provider_config, log_errors)
            all_models.extend(models)
    return all_models

def get_vision_models(): return _get_models_by_type("vision") # noqa
def get_text_models(): return _get_models_by_type("text") # noqa
def get_all_models(): return _get_models_by_type("all") # noqa
