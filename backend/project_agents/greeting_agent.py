"""
project_agents/greeting_agent.py — Handles conversational messages with no chart.

When user says "Hi", "Thanks", "What can you do?" etc., instead of
forcing a chart, we return a helpful text response.
"""

from __future__ import annotations
from ..models import AgentMode, AnalysisResult, SessionContext
from ..llm_client import call_llm

_GREETING_SYSTEM = """You are sYsLens, an AI data intelligence assistant.
The user has sent a greeting, thank-you, or conversational message.

Respond warmly and helpfully in 2-3 sentences. Mention what you can do:
- Analyze CSV/Excel files and generate charts
- Extract data from text and visualize it
- Answer questions about topics with visual knowledge maps
- Recreate charts from images
- Analyze PDFs

Keep it brief and friendly. No JSON, no markdown, just plain text."""


class GreetingAgent:

    def run(self, text: str, ctx: SessionContext) -> AnalysisResult:
        # For very common greetings, use a fixed response (no LLM cost)
        lower = text.lower().strip()

        if lower in {"hi", "hello", "hey", "hiya", "howdy"}:
            reply = (
                "Hello! I'm sYsLens — paste any data, ask a question, or upload a file "
                "and I'll generate charts, KPIs, and insights for you. "
                "What would you like to explore today?"
            )
        elif any(t in lower for t in {"thanks", "thank you", "thank u", "thx"}):
            reply = "You're welcome! Let me know if there's anything else you'd like to visualize or analyze."
        elif "what can you do" in lower or lower in {"help"}:
            reply = (
                "I can: 📊 visualize data you paste · 📁 analyze CSV/Excel files · "
                "🖼 extract data from chart images · 📄 process PDFs · "
                "🗺 build knowledge maps for any topic · 💬 answer follow-up questions. "
                "Just ask!"
            )
        elif "who are you" in lower or "what are you" in lower:
            reply = (
                "I'm sYsLens v2 — an AI data intelligence engine. "
                "Give me data, a question, or a file and I'll turn it into "
                "interactive charts, KPI cards, and insights."
            )
        else:
            # Use LLM for other conversational messages
            try:
                reply = call_llm(
                    _GREETING_SYSTEM,
                    [{"role": "user", "content": text}],
                    max_tokens=150,
                    temperature=0.5,
                )
            except Exception:
                reply = "Hi! Paste some data, upload a file, or ask a question to get started."

        return AnalysisResult(
            mode=AgentMode.GREETING.value,
            spec=None,           # no chart for greetings
            insight=reply,
        )