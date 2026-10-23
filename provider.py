"""Gemma 4 provider adapter (Gemini API). Lazy: nothing connects until the first request.

Model IDs come from .env (GEMMA_MODELS, comma separated). The defaults are the Gemma 4 IDs
listed by the Gemini API models endpoint for this project's key.
"""
import os
import time

DEFAULT_MODELS = ["gemma-4-26b-a4b-it", "gemma-4-31b-it"]


class ProviderError(Exception):
    """kind: missing_key | auth | bad_model | rate_limit | server | timeout | network | empty | budget"""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind

    FRIENDLY = {
        "missing_key": "No Gemini API key. Add GEMINI_API_KEY to .env, or use Sample replay.",
        "auth": "The API key was rejected. Check GEMINI_API_KEY in .env.",
        "bad_model": "The configured Gemma model isn't available for this key.",
        "rate_limit": "Too many requests (429). Wait a minute and try again.",
        "server": "Google's servers are busy. Try again shortly.",
        "timeout": "The model took too long to answer.",
        "network": "No internet connection to the model.",
        "empty": "The model returned an empty answer.",
        "budget": "Gave up after the time budget ran out.",
    }

    @property
    def friendly(self):
        return self.FRIENDLY.get(self.kind, str(self))


class GemmaProvider:
    def __init__(self, api_key=None, models=None, request_timeout_s=90, overall_budget_s=240, max_attempts=4):
        self._api_key = api_key
        env_models = [m.strip() for m in os.getenv("GEMMA_MODELS", "").split(",") if m.strip()]
        self.models = models or env_models or ([os.getenv("GEMMA_MODEL")] if os.getenv("GEMMA_MODEL") else []) or DEFAULT_MODELS
        self.request_timeout_s = request_timeout_s
        self.overall_budget_s = overall_budget_s
        self.max_attempts = max_attempts
        self._client = None
        self.last_model = None

    def _get_client(self):
        if self._client is None:
            key = self._api_key or os.getenv("GEMINI_API_KEY")
            if not key or key == "paste-your-key-here":
                raise ProviderError("missing_key", "GEMINI_API_KEY is not set")
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=key, http_options=types.HttpOptions(timeout=int(self.request_timeout_s * 1000))
            )
        return self._client

    @staticmethod
    def _classify(exc):
        from google.genai import errors

        if isinstance(exc, errors.ClientError):
            code = getattr(exc, "code", None)
            if code in (401, 403):
                return ProviderError("auth", "credentials rejected")
            if code == 404:
                return ProviderError("bad_model", "model not found")
            if code == 429:
                return ProviderError("rate_limit", "rate limited")
            return ProviderError("bad_model", f"request rejected ({code})")
        if isinstance(exc, errors.ServerError):
            return ProviderError("server", f"server error {getattr(exc, 'code', '')}")
        name = type(exc).__name__.lower()
        if "timeout" in name:
            return ProviderError("timeout", "request timed out")
        if "connect" in name or "network" in name:
            return ProviderError("network", "network error")
        return ProviderError("server", type(exc).__name__)

    def generate(self, contents):
        """Return model text. Retries server/timeout/429 across models within the time budget."""
        client = self._get_client()
        deadline = time.monotonic() + self.overall_budget_s
        last = None
        for attempt in range(self.max_attempts):
            model = self.models[attempt % len(self.models)]
            try:
                response = client.models.generate_content(model=model, contents=contents)
                text = (getattr(response, "text", None) or "").strip()
                if not text:
                    raise ProviderError("empty", "empty response")
                self.last_model = model
                return text
            except ProviderError as e:
                last = e
            except Exception as e:  # noqa: BLE001 - classified below
                last = self._classify(e)
                if last.kind in ("auth", "missing_key"):
                    raise last
                if last.kind == "bad_model" and len(self.models) == 1:
                    raise last
            is_last_try = attempt == self.max_attempts - 1
            wait = min(2 ** attempt, 8)
            if is_last_try or time.monotonic() + wait >= deadline:
                break
            time.sleep(wait)  # bounded backoff, never after the final attempt
        if last and time.monotonic() >= deadline:
            raise ProviderError("budget", str(last))
        raise last or ProviderError("server", "no attempts made")
