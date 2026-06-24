"""
Multi-provider LLM wrapper — free first, paid as fallback.

Priority order (cheapest / freest first):
  1. Groq        — FREE. llama-3.3-70b. Sign up: console.groq.com (no card)
                   14,400 req/day free. Faster than Claude for JSON tasks.
  2. GLM-5.2     — FREE tier. 1M context. Sign up: z.ai (ZhipuAI)
                   OpenAI-compatible API. Strong at structured reasoning.
  3. Gemini      — FREE. gemini-1.5-flash. Sign up: aistudio.google.com (no card)
                   1M tokens/day free.
  4. Anthropic   — PAID fallback. Only used if all free keys are missing.

Set ONE key to go fully free:
  GROQ_API_KEY=gsk_...      ← preferred (faster, better JSON reliability)
  GLM_API_KEY=...           ← alternative (1M context, great for long docs)
  GEMINI_API_KEY=AIza...    ← alternative

Uses httpx directly — no extra packages needed.
"""

import os
import re
import httpx

# ── Provider config ────────────────────────────────────────────────────────────
GROQ_KEY      = os.getenv("GROQ_API_KEY")
GLM_KEY       = os.getenv("GLM_API_KEY")
GEMINI_KEY    = os.getenv("GEMINI_API_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

GROQ_MODEL      = os.getenv("GROQ_MODEL",      "llama-3.3-70b-versatile")
GLM_MODEL       = os.getenv("GLM_MODEL",       "glm-5.2")
GEMINI_MODEL    = os.getenv("GEMINI_MODEL",    "gemini-1.5-flash-latest")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

TIMEOUT = 45   # seconds


def _clean_json(text: str) -> str:
    """Strip markdown fences that some models add."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ── Provider implementations (raw httpx — no SDK deps) ────────────────────────

def _groq(system: str, user: str, max_tokens: int) -> str:
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model":    GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "max_tokens":      max_tokens,
            "temperature":     0.1,
            "response_format": {"type": "json_object"},
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _glm(system: str, user: str, max_tokens: int) -> str:
    r = httpx.post(
        "https://api.z.ai/api/paas/v4/chat/completions",
        headers={
            "Authorization": f"Bearer {GLM_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model":    GLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "max_tokens":  max_tokens,
            "temperature": 0.1,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _gemini(system: str, user: str, max_tokens: int) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
    )
    r = httpx.post(
        url,
        json={
            "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
            "generationConfig": {
                "maxOutputTokens":  max_tokens,
                "temperature":      0.1,
                "responseMimeType": "application/json",
            },
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _anthropic(system: str, user: str, max_tokens: int) -> str:
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type":      "application/json",
        },
        json={
            "model":      ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "system":     system,
            "messages":   [{"role": "user", "content": user}],
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


# ── Public interface ───────────────────────────────────────────────────────────

def which_provider() -> str:
    """Return name of the provider that will be used."""
    if GROQ_KEY:      return f"Groq ({GROQ_MODEL}) — FREE"
    if GLM_KEY:       return f"GLM-5.2 ({GLM_MODEL}) — FREE (z.ai)"
    if GEMINI_KEY:    return f"Gemini ({GEMINI_MODEL}) — FREE"
    if ANTHROPIC_KEY: return f"Anthropic ({ANTHROPIC_MODEL}) — PAID"
    return "NONE — set GROQ_API_KEY, GLM_API_KEY, or GEMINI_API_KEY"


def call_llm(system: str, user: str, max_tokens: int = 2048) -> str:
    """
    Call the best available LLM. Returns raw text (JSON string for structured tasks).
    Priority: Groq → GLM-5.2 → Gemini → Anthropic (paid fallback).
    """
    attempts = []

    if GROQ_KEY:
        try:
            return _clean_json(_groq(system, user, max_tokens))
        except Exception as e:
            attempts.append(f"Groq: {e}")

    if GLM_KEY:
        try:
            return _clean_json(_glm(system, user, max_tokens))
        except Exception as e:
            attempts.append(f"GLM: {e}")

    if GEMINI_KEY:
        try:
            return _clean_json(_gemini(system, user, max_tokens))
        except Exception as e:
            attempts.append(f"Gemini: {e}")

    if ANTHROPIC_KEY:
        try:
            return _clean_json(_anthropic(system, user, max_tokens))
        except Exception as e:
            attempts.append(f"Anthropic: {e}")

    raise RuntimeError(
        "No LLM key set. Add ONE of these to your .env (all FREE):\n"
        "  GROQ_API_KEY   → console.groq.com (no card, 14,400 req/day)\n"
        "  GLM_API_KEY    → z.ai (no card, 1M context, GLM-5.2)\n"
        "  GEMINI_API_KEY → aistudio.google.com/app/apikey (no card)\n"
        f"Errors: {' | '.join(attempts)}"
    )


if __name__ == "__main__":
    print(f"Active provider: {which_provider()}")
    test = call_llm(
        system="You return JSON only.",
        user='Return {"status": "ok", "provider": "working"}',
        max_tokens=50,
    )
    print(f"Test response: {test}")
