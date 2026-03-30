import os
from pathlib import Path

# Load .env for local dev
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
except Exception:
    pass

# Load Streamlit secrets for cloud
try:
    import streamlit as st
    for _k, _v in st.secrets.items():
        if not os.environ.get(_k):
            os.environ[_k] = str(_v)
except Exception:
    pass

class Settings:
    LLM_PROVIDER    = os.getenv("LLM_PROVIDER",    "openai")
    ROUTER_PROVIDER = os.getenv("ROUTER_PROVIDER", "groq")
    OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY",  "")
    OPENAI_MODEL    = os.getenv("OPENAI_MODEL",    "gpt-4o")
    GROQ_API_KEY    = os.getenv("GROQ_API_KEY",    "")
    GROQ_MODEL      = os.getenv("GROQ_MODEL",      "llama-3.3-70b-versatile")
    GROQ_FAST_MODEL = os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant")
    ANTHROPIC_API_KEY        = os.getenv("ANTHROPIC_API_KEY",        "")
    ANTHROPIC_MODEL          = os.getenv("ANTHROPIC_MODEL",          "claude-sonnet-4-20250514")
    AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY",     "")
    AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT",    "")
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    AZURE_OPEN_AI_MODEL      = os.getenv("AZURE_OPEN_AI_MODEL",      "gpt-4o")
    SANDBOX_IMAGE            = os.getenv("SANDBOX_IMAGE",            "syslens-sandbox:latest")
    SANDBOX_TIMEOUT_SEC      = int(os.getenv("SANDBOX_TIMEOUT_SEC",  "60"))
    SANDBOX_ALLOW_SUBPROCESS = os.getenv("SANDBOX_ALLOW_SUBPROCESS", "true").lower() == "true"
    FIGURE_CACHE_SIZE        = int(os.getenv("FIGURE_CACHE_SIZE",    "32"))
    MAX_HISTORY_TURNS        = int(os.getenv("MAX_HISTORY_TURNS",    "20"))
    DEBUG                    = os.getenv("DEBUG", "false").lower() == "true"

    def effective_router_provider(self):
        if self.ROUTER_PROVIDER == "groq" and not self.GROQ_API_KEY:
            return self.LLM_PROVIDER
        return self.ROUTER_PROVIDER

settings = Settings()
