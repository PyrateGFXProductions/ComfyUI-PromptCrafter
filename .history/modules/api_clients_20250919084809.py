# Standard library imports
import json
import time
import inspect
from typing import Callable, Dict, Any

# Local module imports
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
        ok, data_or_err = self._make_request(url=url, headers=headers, payload=payload, timeout=timeout)
        if not ok: return False, data_or_err
        return self._parse_response(data_or_err)

    def _make_request(self, url, headers, payload, timeout):
        """A shared helper for making POST requests and handling common HTTP/network errors."""
        try:
            response = config.SHARED_SESSION.post(url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status() # Raises HTTPError for 4xx/5xx status codes
            return True, response.json()
        except config.requests.exceptions.ConnectionError:
            return False, f"{self.provider.capitalize()} API Error: Could not connect to the server at {url}. Please ensure the server is running and the address is correct."
        except config.requests.exceptions.Timeout as e:
            return False, f"{self.provider.capitalize()} API Error: The request timed out after {timeout} seconds. The model may be loading into memory for the first time. Try increasing the 'timeout' setting on the node."
        except config.requests.exceptions.HTTPError as e:
            # This handles non-2xx responses
            error_details = f"HTTP {e.response.status_code} {e.response.reason}."
            try:
                # Try to parse JSON error from the response body
                error_json = e.response.json()
                error_message = error_json.get("error", {}).get("message") or error_json.get("error") or json.dumps(error_json)
                error_details += f" Details: {error_message}"
            except json.JSONDecodeError:
                error_details += f" Raw response: {e.response.text[:500]}"
            return False, f"{self.provider.capitalize()} API Error: {error_details}", e.response.status_code
        except json.JSONDecodeError:
            # This handles cases where the server returns 200 OK but with invalid JSON
            return False, f"{self.provider.capitalize()} API returned a 200 OK response with invalid JSON. Raw response: {getattr(response, 'text', 'N/A')[:500]}"
        except config.requests.exceptions.RequestException as e:
            # A catch-all for other requests-related errors
            return False, f"{self.provider.capitalize()} API connection error: {e}"

    def is_configured(self):
        return bool(self.api_key)

class OllamaClient(BaseAPIClient):
    """Client for handling local Ollama models."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._chat_api_unsupported = set() # Stores models that don't support /api/chat

    def is_configured(self): return True

    def query(self, model_id, prompt, images_b64=None, timeout=60, temperature=None, seed=None, prefer_chat=False, **kwargs):
        use_chat_first = (prefer_chat or bool(images_b64)) and model_id not in self._chat_api_unsupported
        endpoints_to_try = ["chat", "generate"] if use_chat_first else ["generate", "chat"]

        last_err = None
        for endpoint in endpoints_to_try:
            # Skip generate if we already know chat is the only way (e.g. for images)
            if endpoint == "generate" and use_chat_first and not prefer_chat:
                continue

            payload = self._build_payload(endpoint, model_id, prompt, images_b64, temperature, seed)
            result = self._make_request(url=f"{self.base_url}/api/{endpoint}", headers={}, payload=payload, timeout=timeout)
            ok, data_or_err = result[0], result[1]

            if ok:
                return self._parse_response(data_or_err)

            status_code = result[2] if len(result) > 2 else None
            if status_code == 404 and endpoint == "chat":
                self._chat_api_unsupported.add(model_id)
                print(f"\033[94m[PromptCrafter] Ollama model '{model_id}' does not support /api/chat. Switching to /api/generate.\033[0m")
                continue # Immediately try the next endpoint
            else:
                last_err = data_or_err
                if "Could not connect" in str(last_err):
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
        if not payload["options"]: del payload["options"]
        return payload

    def _parse_response(self, data):
        content = ""
        if "response" in data: # /api/generate
            content = data.get("response", "")
        elif "message" in data and isinstance(data["message"], dict): # /api/chat
            content = data["message"].get("content", "")
        
        return (True, content.strip()) if content else (False, f"Could not find response content in Ollama output: {json.dumps(data)}")

class OpenAIClient(BaseAPIClient):
    """Client for OpenAI's APIs."""
    def _get_headers(self): return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
    def _get_url(self, model_id): return f"{self.base_url}/chat/completions"
    def _build_payload(self, model_id, prompt, images_b64, **kwargs):
        content = [{"type": "text", "text": prompt}]
        if images_b64:
            for img_b64 in images_b64: content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
        payload = {"model": model_id, "messages": [{"role": "user", "content": content}], "max_tokens": 4096}
        if kwargs.get('temperature') is not None: payload["temperature"] = float(kwargs.get('temperature'))
        if kwargs.get('seed') is not None and int(kwargs.get('seed')) >= 0: payload["seed"] = int(kwargs.get('seed'))
        return payload
    def _parse_response(self, data): return True, data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

class AnthropicClient(BaseAPIClient):
    """Client for Anthropic's (Claude) Messages API."""
    def _get_headers(self): return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    def _get_url(self, model_id): return f"{self.base_url}/messages"
    def _build_payload(self, model_id, prompt, images_b64, **kwargs):
        content = [{"type": "text", "text": prompt}]
        if images_b64:
            for img_b64 in images_b64: content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}})
        payload = {"model": model_id, "messages": [{"role": "user", "content": content}], "max_tokens": 4096}
        if kwargs.get('temperature') is not None: payload["temperature"] = float(kwargs.get('temperature'))
        return payload
    def _parse_response(self, data): return True, "".join([c.get("text", "") for c in data.get("content", [])]).strip()

class GoogleClient(BaseAPIClient):
    """Client for Google's Gemini API."""
    def _get_headers(self): return {"Content-Type": "application/json"}
    def _get_url(self, model_id): return f"{self.base_url}/models/{model_id}:generateContent?key={self.api_key}"
    def _build_payload(self, model_id, prompt, images_b64, **kwargs):
        parts = [{"text": prompt}]
        if images_b64:
            for img_b64 in images_b64: parts.append({"inline_data": {"mime_type": "image/png", "data": img_b64}})
        payload = {"contents": [{"parts": parts}]}
        gen_config = {}
        if kwargs.get('temperature') is not None: gen_config["temperature"] = float(kwargs.get('temperature'))
        if gen_config: payload["generationConfig"] = gen_config
        payload["safetySettings"] = [{"category": c, "threshold": "BLOCK_NONE"} for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
        return payload
    def _parse_response(self, data):
        text_parts = [part['text'] for candidate in data.get('candidates', []) for part in candidate.get('content', {}).get('parts', []) if 'text' in part]
        if not text_parts:
            block_reason = data.get('promptFeedback', {}).get('blockReason')
            return False, f"Request blocked by Gemini API. Reason: {block_reason}" if block_reason else f"No text content in Gemini response: {json.dumps(data)}"
        return True, "".join(text_parts).strip()

# --- Client Registry and Dispatchers ---
API_CLIENTS = {
    "openai": OpenAIClient(provider="openai", client_config=config.API_CONFIG.get("openai", {})),
    "anthropic": AnthropicClient(provider="anthropic", client_config=config.API_CONFIG.get("anthropic", {})),
    "google": GoogleClient(provider="google", client_config=config.API_CONFIG.get("google", {})),
}
OLLAMA_CLIENT = OllamaClient(provider="ollama", client_config={"base_url": config.OLLAMA_BASE})

def _log_api_status():
    """Informs the user which remote APIs are configured and ready to use."""
    configured_apis = [p.upper() for p, c in API_CLIENTS.items() if c.is_configured()]
    if configured_apis:
        print(f"\033[92m[PromptCrafter] API support enabled for: {', '.join(configured_apis)}\033[0m")

def check_ollama_status():
    """Performs a single, clear check for Ollama connectivity at startup."""
    status, _ = _fetch_ollama_models(retries=1)
    if status == 'ok':
        print(f"\033[92m[PromptCrafter] Ollama is Online. Models will be available.\033[0m")
    else:
        print(f"\033[91m[PromptCrafter] Ollama is OFFLINE. Local models will not be available.\033[0m")

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

    provider, model_id = "ollama", model
    if "/" in model:
        provider_candidate, model_id_candidate = model.split("/", 1)
        if provider_candidate in API_CLIENTS:
            provider, model_id = provider_candidate, model_id_candidate

    client = API_CLIENTS.get(provider) or OLLAMA_CLIENT
    if not client.is_configured():
        return False, f"API key for provider '{provider}' not found. Please set the corresponding environment variable."
    
    filtered_kwargs = _filter_kwargs(client.query, kwargs)
    return client.query(model_id, prompt, images_b64=images_b64, **filtered_kwargs)

def _reason_with_model(model, prompt, use_chat_api, temperature, seed, images=None, timeout=40, debug_mode=False, debug_title=""):
    """A helper function that asks a model a question where the expected answer is JSON."""
    from . import utils
    ok, resp = query_model_auto(model, prompt, images=images, prefer_chat=use_chat_api, temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title=debug_title)
    if not ok: return False, f"Model reasoning query failed: {resp}"
    try:
        return True, utils._extract_and_parse_json(resp)
    except utils.JSONParsingError as e:
        return False, f"Failed to parse JSON from model response. Error: {e}"

# ------------------------------------------------------------------------------------
# Model Discovery
# ------------------------------------------------------------------------------------

def _fetch_ollama_models(retries=3, delay=2):
    """Connects to the local Ollama server to get a list of all installed models."""
    last_exc = None
    for i in range(retries):
        try:
            resp = config.SHARED_SESSION.get(f"{config.OLLAMA_BASE}/api/tags", timeout=5)
            resp.raise_for_status()
            return 'ok', resp.json().get("models", [])
        except config.requests.exceptions.ConnectionError as e:
            last_exc = e
            if i < retries - 1:
                print(f"\033[93m[PromptCrafter] Ollama connection failed (Attempt {i+1}/{retries}). Retrying in {delay}s...\033[0m")
                time.sleep(delay)
            continue
        except config.requests.exceptions.RequestException as e:
            last_exc = e
            break # Don't retry on non-connection errors like timeouts
        except Exception as e:
            last_exc = e
            break

    if isinstance(last_exc, config.requests.exceptions.ConnectionError):
        print(f"\033[91m[PromptCrafter] FATAL: Could not connect to Ollama at '{config.OLLAMA_BASE}' after {retries} attempts. Please ensure Ollama is running and the URL is correct.\033[0m")
        return 'connection_error', str(last_exc)

    return 'other_error', str(last_exc or "Unknown error during model fetch.")

def _get_models_by_type(model_type):
    """Gets models of a specific type (vision, text, or all) by inspecting metadata."""
    ollama_status, ollama_data = _fetch_ollama_models()
    ollama_models_details = ollama_data if ollama_status == 'ok' else []

    VISION_FAMILIES = {"llava", "moondream", "bakllava", "fuyu", "idefics", "qwen2.5vl"}
    local_models = []
    if ollama_status == 'ok':
        for m in ollama_models_details:
            details = m.get("details", {})
            families = details.get("families") or []
            architecture = details.get("general.architecture", "")
            is_vision = any(f in VISION_FAMILIES for f in families) or 'clip' in architecture or 'vision' in architecture or 'mmproj' in architecture
            if (model_type == "vision" and is_vision) or \
               (model_type == "text" and not is_vision) or \
               (model_type == "all"):
                local_models.append(m["name"])

    api_models = []
    for provider, client_config in config.API_CONFIG.items():
        if client_config.get("api_key"):
            key = "vision_models" if model_type == "vision" else "text_models"
            provider_models = set(client_config.get("vision_models", []) + client_config.get("text_models", [])) if model_type == "all" else client_config.get(key, [])
            api_models.extend([f"{provider}/{model}" for model in provider_models])

    available_models = sorted(list(set(local_models + api_models)))

    if not available_models:
        if ollama_status == 'connection_error':
            return ["OLLAMA_OFFLINE_CHECK_CONSOLE"]
        return ["NO_MODELS_FOUND_OR_CONFIGURED"]

    preferred_fallback = config.FALLBACK_VISION_MODEL if model_type == "vision" else config.FALLBACK_TEXT_MODEL
    if preferred_fallback in available_models:
        available_models.remove(preferred_fallback)
        available_models.insert(0, preferred_fallback)
    
    return available_models

def get_vision_models(): return _get_models_by_type("vision")
def get_text_models(): return _get_models_by_type("text")
def get_all_models(): return _get_models_by_type("all")