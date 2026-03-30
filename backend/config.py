"""
config.py — Application settings.

Extends the original config.py pattern.
All settings loaded from .env at the project root.

FIX (Gemini critique #4 — Sandbox subprocess security):
  Added SANDBOX_ALLOW_SUBPROCESS flag (default: true for dev, false for prod).
  In production, set SANDBOX_ALLOW_SUBPROCESS=false in .env to disable the
  subprocess fallback entirely. File analysis will fail gracefully instead of
  running LLM-generated code on the host machine.
"""

import os
from dotenv import load_dotenv
from pathlib import Path

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


class Settings:
    # ── LLM Provider ──────────────────────────────────────────────────────
    LLM_PROVIDER:    str = os.getenv("LLM_PROVIDER",    "openai")
    ROUTER_PROVIDER: str = os.getenv("ROUTER_PROVIDER", "groq")

    # ── OpenAI ────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL:   str = os.getenv("OPENAI_MODEL",   "gpt-4o")
    OPENAI_MINI_MODEL: str = os.getenv("OPENAI_MINI_MODEL", "gpt-40-mini")

    # ── Groq ──────────────────────────────────────────────────────────────
    GROQ_API_KEY:    str = os.getenv("GROQ_API_KEY",    "")
    GROQ_MODEL:      str = os.getenv("GROQ_MODEL",      "llama-3.3-70b-versatile")
    GROQ_FAST_MODEL: str = os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant")

    # ── Anthropic (optional) ───────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL:   str = os.getenv("ANTHROPIC_MODEL",   "claude-sonnet-4-20250514")

    # ── Azure OpenAI (legacy — inherited from original codebase) ──────────
    AZURE_OPENAI_API_KEY:     str = os.getenv("AZURE_OPENAI_API_KEY",     "")
    AZURE_OPENAI_ENDPOINT:    str = os.getenv("AZURE_OPENAI_ENDPOINT",    "")
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    AZURE_OPEN_AI_MODEL:      str = os.getenv("AZURE_OPEN_AI_MODEL",      "gpt-4o")

    # ── Sandbox ────────────────────────────────────────────────────────────
    MCP_SANDBOX_URL:     str  = os.getenv("MCP_SANDBOX_URL",     "http://localhost:3000/sse")
    SANDBOX_IMAGE:       str  = os.getenv("SANDBOX_IMAGE",       "syslens-sandbox:latest")
    SANDBOX_TIMEOUT_SEC: int  = int(os.getenv("SANDBOX_TIMEOUT_SEC", "60"))  # reduced from 90

    # SECURITY: subprocess fallback runs LLM code on the host machine.
    # Set to "false" in production. Default true for local dev convenience.
    SANDBOX_ALLOW_SUBPROCESS: bool = os.getenv("SANDBOX_ALLOW_SUBPROCESS", "true").lower() == "true"

    # ── Figure cache ───────────────────────────────────────────────────────
    FIGURE_CACHE_SIZE: int = int(os.getenv("FIGURE_CACHE_SIZE", "32"))

    # ── App ───────────────────────────────────────────────────────────────
    MAX_HISTORY_TURNS: int  = int(os.getenv("MAX_HISTORY_TURNS", "20"))
    DEBUG:             bool = os.getenv("DEBUG", "false").lower() == "true"

    def effective_router_provider(self) -> str:
        if self.ROUTER_PROVIDER == "groq" and not self.GROQ_API_KEY:
            return self.LLM_PROVIDER
        return self.ROUTER_PROVIDER


settings = Settings()