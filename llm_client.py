"""
Shared LLM client — used by Phase 2 (role ranking + gap analysis),
Phase 3 (technical deep scan), and Phase 4 (content generation).

100% free tier. Supports two providers, both free with no credit card:
  - Groq  (https://console.groq.com)           -> GROQ_API_KEY
  - Gemini (https://aistudio.google.com/apikey) -> GEMINI_API_KEY

Set LLM_PROVIDER=groq or LLM_PROVIDER=gemini in .env to choose the primary
(defaults to groq). If BOTH keys are present in .env, the client will
AUTOMATICALLY fail over to the other provider when the primary's free-tier
quota is exhausted — no manual .env editing or rerun needed mid-session.

Retries with backoff on ordinary per-minute rate limits (a busy moment that
clears in seconds). For a per-DAY quota exhaustion (which can't be waited
out in a normal retry loop — Groq's free tier resets on a ~24h cycle), it
skips straight to the fallback provider instead of retrying pointlessly.
"""

import json
import os
import re
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"

MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2


class LLMError(Exception):
    pass


class RateLimitError(LLMError):
    """A per-minute (or otherwise short) rate limit — worth retrying."""

    pass


class QuotaExhaustedError(LLMError):
    """A per-day (or otherwise long-window) quota limit — retrying won't help
    within a normal session; better to fail over to another provider."""

    pass


def _parse_retry_after_seconds(error_text: str, default: float) -> float:
    """Groq's error message includes 'Please try again in 420ms' — use that
    if present, otherwise fall back to a default backoff."""
    match = re.search(r"try again in ([\d.]+)(ms|s)", error_text)
    if not match:
        return default
    value, unit = match.groups()
    value = float(value)
    return value / 1000 if unit == "ms" else value


def _is_daily_quota_error(error_text: str) -> bool:
    """Detects long-window quota exhaustion (e.g. 'tokens per day (TPD)') vs
    an ordinary short-window rate limit. Retrying a daily cap with backoff is
    pointless — the wait time would be tens of minutes to hours, not seconds."""
    lowered = error_text.lower()
    return "per day" in lowered or "tpd" in lowered or "daily" in lowered


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        _is_fallback: bool = False,
    ):
        # Supports the same MODEL=provider/model-name convention used elsewhere
        # (e.g. MODEL=gemini/gemini-3.1-flash-lite, MODEL=groq/llama-3.3-70b-versatile).
        # If MODEL is set in .env, it takes precedence over LLM_PROVIDER + defaults.
        combined = os.environ.get("MODEL")
        if combined and "/" in combined and provider is None and model is None:
            provider, model = combined.split("/", 1)

        self.provider = (provider or os.environ.get("LLM_PROVIDER") or "groq").lower()
        self.groq_key = os.environ.get("GROQ_API_KEY")
        self.gemini_key = os.environ.get("GEMINI_API_KEY")

        if self.provider == "groq":
            self.api_key = api_key or self.groq_key
            self.model = model or DEFAULT_GROQ_MODEL
            if not self.api_key:
                raise LLMError(
                    "No GROQ_API_KEY found. Get a free key at https://console.groq.com "
                    "and add it to your .env as GROQ_API_KEY=gsk_..."
                )
        elif self.provider == "gemini":
            self.api_key = api_key or self.gemini_key
            self.model = model or DEFAULT_GEMINI_MODEL
            if not self.api_key:
                raise LLMError(
                    "No GEMINI_API_KEY found. Get a free key at "
                    "https://aistudio.google.com/apikey and add it to your .env "
                    "as GEMINI_API_KEY=..."
                )
        else:
            raise LLMError(
                f"Unknown provider '{self.provider}'. Use 'groq' or 'gemini'."
            )

        # Build a fallback client for the OTHER provider, if its key is available.
        # Only built once per client (not recursively) to avoid ping-ponging forever
        # if both providers are simultaneously exhausted.
        self._fallback_client = None
        if not _is_fallback:
            other_provider = "gemini" if self.provider == "groq" else "groq"
            other_key = self.gemini_key if other_provider == "gemini" else self.groq_key
            if other_key:
                self._fallback_client = LLMClient(
                    provider=other_provider, _is_fallback=True
                )

    # ---------- provider-specific calls ----------

    def _call_groq(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        json_mode: bool,
        max_tokens: int,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=60)

        if resp.status_code == 429:
            if _is_daily_quota_error(resp.text):
                raise QuotaExhaustedError(resp.text[:500])
            raise RateLimitError(resp.text[:500])
        if not resp.ok:
            raise LLMError(f"Groq API error {resp.status_code}: {resp.text[:500]}")

        return resp.json()["choices"][0]["message"]["content"]

    def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        json_mode: bool,
        max_tokens: int,
    ) -> str:
        url = GEMINI_API_URL_TEMPLATE.format(model=self.model)
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if json_mode:
            payload["generationConfig"]["response_mime_type"] = "application/json"

        resp = requests.post(
            url, params={"key": self.api_key}, json=payload, timeout=60
        )

        if resp.status_code == 429:
            if _is_daily_quota_error(resp.text):
                raise QuotaExhaustedError(resp.text[:500])
            raise RateLimitError(resp.text[:500])
        if not resp.ok:
            raise LLMError(f"Gemini API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise LLMError(
                f"Unexpected Gemini response shape: {json.dumps(data)[:500]}"
            )

    def _call_provider(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        json_mode: bool,
        max_tokens: int,
    ) -> str:
        if self.provider == "groq":
            return self._call_groq(
                system_prompt, user_prompt, temperature, json_mode, max_tokens
            )
        else:
            return self._call_gemini(
                system_prompt, user_prompt, temperature, json_mode, max_tokens
            )

    # ---------- public interface ----------

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        json_mode: bool = False,
        max_tokens: int = 4096,
    ) -> str:
        """
        Single-turn chat completion. Retries on ordinary rate limits with
        backoff; on a daily-quota exhaustion, or after retries are used up,
        automatically fails over to the other provider if its key is set.
        """
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                return self._call_provider(
                    system_prompt, user_prompt, temperature, json_mode, max_tokens
                )
            except QuotaExhaustedError as e:
                last_error = e
                print(
                    f"  {self.provider} daily quota exhausted — retrying won't help within this session."
                )
                break  # skip remaining retries, go straight to fallback below
            except RateLimitError as e:
                last_error = e
                wait = _parse_retry_after_seconds(
                    str(e), default=BASE_BACKOFF_SECONDS * (2**attempt)
                )
                wait = min(wait, 60) + 0.5  # small buffer, cap at 60s
                print(
                    f"  Rate limited ({self.provider}), waiting {wait:.1f}s before retry "
                    f"({attempt + 1}/{MAX_RETRIES})..."
                )
                time.sleep(wait)

        # Primary provider exhausted (either daily quota, or ran out of retries).
        if self._fallback_client is not None:
            print(
                f"  Switching to {self._fallback_client.provider} as fallback provider..."
            )
            try:
                return self._fallback_client.chat(
                    system_prompt,
                    user_prompt,
                    temperature=temperature,
                    json_mode=json_mode,
                    max_tokens=max_tokens,
                )
            except LLMError as fallback_error:
                raise LLMError(
                    f"Both providers failed. {self.provider}: {last_error} | "
                    f"{self._fallback_client.provider}: {fallback_error}"
                )

        raise LLMError(
            f"{self.provider} is rate-limited/exhausted and no fallback provider is configured "
            f"(set both GROQ_API_KEY and GEMINI_API_KEY in .env to enable automatic fallback). "
            f"Last error: {last_error}"
        )

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Chat completion that returns parsed JSON. Handles the common failure
        mode where the model wraps its JSON in ```json fences despite being
        told not to.
        """
        raw = self.chat(
            system_prompt,
            user_prompt,
            temperature=temperature,
            json_mode=True,
            max_tokens=max_tokens,
        )
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise LLMError(
                f"Model did not return valid JSON: {e}\nRaw output: {raw[:500]}"
            )
