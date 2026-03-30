"""
project_agents/router_agent.py

INTENT-FIRST ROUTING:
  Every query has a cognitive intent. Detect it first, then route.

  RANK    → "Top N X"                      → direct_data → horizontal_bar
  TREND   → "X growth 2019 to 2024"        → direct_data → line
  SHARE   → "market share / mix / %"       → direct_data → donut
  COMPARE → "X vs Y vs Z"                  → direct_data → radar / grouped_bar
  CONCEPT → "What is X / history / SOLID"  → knowledge_map → sunburst
  DATA    → inline numbers / bullets       → direct_data → auto
  FILE    → CSV/Excel uploaded             → file_analysis
  IMAGE   → image uploaded                 → vision / ocr_image
  FOLLOW  → "make it a bar / change..."    → followup
  GREET   → "Hi / thanks"                 → greeting
"""

from __future__ import annotations
import re
from pathlib import Path

from ..models import AgentMode, SessionContext
from ..llm_client import call_router_llm, extract_json

# ── Greetings ─────────────────────────────────────────────────────────────────
_GREETINGS = {
    "hi", "hello", "hey", "hiya", "howdy", "thanks", "thank you",
    "thank u", "thx", "ok", "okay", "k", "sure", "bye", "goodbye",
    "see you", "cya", "good morning", "good afternoon", "good evening",
    "what can you do", "help", "how are you", "what are you", "who are you",
}

# ── Follow-up verbs ────────────────────────────────────────────────────────────
_STRONG_FOLLOWUP_WORDS = {
    "make", "change", "convert", "switch", "flip", "turn",
    "drill", "zoom", "rotate", "transpose", "invert",
}

# IMPORTANT: only include words that CANNOT appear in a standalone query.
# Do NOT include: "revenue", "top", "show", "compare", "trend", "breakdown"
# — these are valid query words, not followup signals.
_FOLLOWUP_KEYWORDS = {
    "instead", "that chart", "same data", "previous chart",
    "make it", "change it", "convert it", "switch to",
    "now show", "now make", "also show", "add to",
    "filter it", "sort it", "update it", "redo",
}

# ── OCR phrases ────────────────────────────────────────────────────────────────
_OCR_PHRASES = (
    "extract", "read", "scan", "get data", "get numbers", "what does it say",
    "invoice", "document", "table in", "text in", "receipt",
)

# ── "Data not available" → narrative response, knowledge_map ─────────────────
_NO_DATA_PHRASES = (
    "isn't available", "is not available", "doesn't include",
    "not in our", "not available in", "we don't have",
    "would need to come from", "you'd typically want",
    "this granular", "bloomberg", "refinitiv", "want me to check",
)

# ═══════════════════════════════════════════════════════════════════════════════
# INTENT PATTERNS — ordered by specificity
# ═══════════════════════════════════════════════════════════════════════════════

# ── RANK intent → horizontal_bar ──────────────────────────────────────────────
# "Top 10 programming languages", "Richest countries by GDP", "Best frameworks"
_RANK_PATTERN = re.compile(
    r'^(top|best|worst|biggest|largest|richest|leading|fastest|most'
    r'|highest|lowest|cheapest|expensive|popular)\s+\d*\s*\w',
    re.IGNORECASE
)
# Hints that say "rank by" anywhere in the sentence
_RANK_BY_PATTERN = re.compile(
    r'\b(by\s+(revenue|gdp|population|size|market cap|spend|usage|popularity'
    r'|performance|return|growth|share|volume|count|score))\b',
    re.IGNORECASE
)

# ── TREND intent → line / area ────────────────────────────────────────────────
# "Netflix subscriber growth 2019 to 2024", "India GDP rate 2015–2024"
_TREND_PATTERN = re.compile(
    r'(\w[\w\s]+?)\s+(growth|trend|rate|evolution|change|rise|fall|increase'
    r'|decrease|performance|history|over time|year[- ]over[- ]year|yoy)'
    r'(\s+(from|since|between|\d{4}))?',
    re.IGNORECASE
)
# Year-range explicitly stated
_YEAR_RANGE = re.compile(r'\b(20\d{2})\s*(to|-|–|through)\s*(20\d{2})\b', re.IGNORECASE)
# "over the last N years"
_LAST_N_YEARS = re.compile(r'over (the )?(last|past) \d+ years?', re.IGNORECASE)

# ── SHARE / DISTRIBUTION intent → donut ───────────────────────────────────────
# "Cloud market share", "Global energy mix", "breakdown by region"
_SHARE_PATTERN = re.compile(
    r'\b(market share|share of|composition|breakdown|distribution|mix'
    r'|proportion|percentage of|% of|split by|by source|by region'
    r'|by type|by sector|by category)\b',
    re.IGNORECASE
)

# ── COMPARE intent → radar / grouped bar ──────────────────────────────────────
# "React vs Vue vs Angular", "AWS vs Azure", "compare X and Y"
_COMPARE_PATTERN = re.compile(
    r'\bvs\.?\s|\bversus\b|\bcompare\b|\bcomparison\b|\bdifference between\b'
    r'|\bpros and cons\b|\bA vs B\b|\bX vs Y\b',
    re.IGNORECASE
)
# "A vs B vs C" structure
_MULTI_VS = re.compile(r'\w[\w\s]+?\s+vs\.?\s+\w[\w\s]+?\s+vs\.?\s+\w', re.IGNORECASE)

# ── CONCEPT / EXPLAIN intent → knowledge_map (sunburst) ───────────────────────
# "What is machine learning", "History of internet", "SOLID principles"
_CONCEPT_PHRASES = (
    "what is", "what are", "explain", "describe", "how does", "how do",
    "define", "tell me about", "concept of", "evolution of",
    "introduction to", "overview of", "what was", "who invented",
    "when was", "why is", "why does", "how it works",
)
# Topics that are ALWAYS conceptual explanations (not chartable data)
_PURE_CONCEPT_TOPICS = (
    "what is machine learning", "what is ai", "what is blockchain",
    "what is cloud computing", "what is devops", "what is agile",
    "solid principles", "what are solid", "design patterns",
    "what is docker", "what is kubernetes", "what is react",
)
_KNOWLEDGE_TOPICS = (
    "investment rationale", "investment thesis", "business strategy",
    "competitive analysis", "competitive advantage", "pros and cons",
    "swot analysis", "strengths and weaknesses", "why invest", "why buy",
    "valuation metrics", "risks of", "opportunities for", "future of",
    "impact of", "principles of",
)

# ── Well-known chartable topics → direct_data ─────────────────────────────────
_CHARTABLE_TOPICS = re.compile(
    r'(programming languages?|tech companies|cloud (providers?|market)|'
    r'energy mix|energy (by|from)|gdp|cryptocurrency|stock market|etf|'
    r'market (share|cap)|nasdaq|s&p|dow jones|global \w+ (by|mix|share)|'
    r'aws.*(azure|gcp)|azure.*(aws|gcp)|subscriber|subscribers|'
    r'revenue \d{4}|performance \d{4}|returns? \d{4})',
    re.IGNORECASE
)

# ── Actual numeric data inline ─────────────────────────────────────────────────
_DATA_INLINE = re.compile(
    r'(\d+\.?\d*\s*%)'
    r'|(\$\s*\d)'
    r'|([+\-]\d+\.?\d*%)'
    r'|(\d+\.?\d*\s*(billion|million|trillion|\bB\b|\bM\b|\bK\b))'  # "394B" or "$394B"
    r'|(revenue|sales|profit|cost|price|return|yield|cagr|margin|rate|spend)\s*:?\s*\d'
    r'|(\d+\.?\d*\s*[xX]\b)'
    r'|([A-Za-z][\w\s]+:\s*\$?\d)',   # "Apple: $394" or "Apple: 394"
    re.IGNORECASE
)

# ── Timeline / history → direct_data (horizontal_bar milestones) ──────────────
_TIMELINE_PATTERN = re.compile(
    r'^(history of|timeline of|evolution of|milestones of|when was|'
    r'chronology of|development of|story of)\b',
    re.IGNORECASE
)

# ── File dashboard phrases ─────────────────────────────────────────────────────
_FILE_PHRASES = re.compile(
    r'^(show|display|analyze|plot|chart|graph|visualize)\s+'
    r'(top|bottom|all|my|the|by)?\s*'
    r'(supplier|vendor|customer|product|order|sales|spend|revenue|category|'
    r'transaction|invoice|record|data|report|metric)',
    re.IGNORECASE
)

# ── LLM fallback system prompt ─────────────────────────────────────────────────
_ROUTER_SYSTEM = """You are an intent-classification router. Classify the user's query.

INTENTS (return exactly one):
- direct_data   : Has actual numbers, OR is a chartable topic (rankings, trends,
                  market share, comparisons with data, historical stats).
                  Examples: "Top 10 languages", "Netflix growth 2019-2024",
                  "Cloud market share", "React vs Vue vs Angular" (chart comparison)
- knowledge_map : Pure conceptual explanation with no chartable data.
                  Examples: "What is ML", "SOLID principles", "How does DNS work"
- greeting      : Social messages, thanks, "what can you do"
- followup      : Modifying the previous visualization ("make it a bar", "filter by US")
- file_analysis : File was uploaded (CSV/Excel)
- vision        : Image of a chart/graph to recreate
- ocr_image     : Image of text/table to extract data from
- pdf           : PDF document uploaded

KEY RULES:
- "X vs Y" for tech/products → direct_data (radar comparison chart)
- "history of X" or "timeline of X" → direct_data (milestone bar chart)
- "Top N X" → direct_data (horizontal bar ranking)
- "X growth YEAR to YEAR" → direct_data (line trend)
- "What is X" / "Explain X" / "SOLID" → knowledge_map

Return only: {"mode": "<intent>", "confidence": 0.0-1.0}"""


class RouterAgent:
    """Routes every query to the correct agent based on cognitive intent."""

    def route(self, text: str, ctx: SessionContext,
              has_file: bool = False, has_image: bool = False, filename: str = "") -> AgentMode:

        lower  = text.lower().strip()
        words  = lower.split()
        nwords = len(words)

        # ── 1. Greeting ────────────────────────────────────────────────────────
        # FIX: use word-boundary match, not startswith.
        # "history".startswith("hi") = True — kills all history/help/hey queries.
        # Correct check: first WORD must be a greeting word, or full text is in set.
        first_word = words[0] if words else ""
        if lower in _GREETINGS:
            return AgentMode.GREETING
        if nwords <= 3 and first_word in _GREETINGS:
            return AgentMode.GREETING

        # ── 2. Strong follow-up (before file check) ────────────────────────────
        if ctx.last_result and first_word in _STRONG_FOLLOWUP_WORDS:
            return AgentMode.FOLLOWUP

        # ── 3a. Timeline / history — MUST come BEFORE concept phrases ──────────
        # "history of X" and "timeline of X" are data queries, not concept explanations.
        # If checked after _CONCEPT_PHRASES, "history of" could fall into knowledge_map
        # depending on future phrase additions.
        if _TIMELINE_PATTERN.match(text):
            return AgentMode.DIRECT_DATA

        # ── 3b. Pure concept topics — always sunburst ─────────────────────────
        if any(lower == t or lower.startswith(t) for t in _PURE_CONCEPT_TOPICS):
            return AgentMode.KNOWLEDGE_MAP

        if any(lower.startswith(phrase) for phrase in _CONCEPT_PHRASES):
            # BUT: if it also has a year range → it's a trend query, not a concept
            if not _YEAR_RANGE.search(text):
                return AgentMode.KNOWLEDGE_MAP

        # ── 4. Knowledge topics (analytical prose) ─────────────────────────────
        if any(topic in lower for topic in _KNOWLEDGE_TOPICS):
            return AgentMode.KNOWLEDGE_MAP

        # ── 5. "Data not available" long-form response ─────────────────────────
        if any(phrase in lower for phrase in _NO_DATA_PHRASES):
            return AgentMode.KNOWLEDGE_MAP

        # ── 6. File extension fast-paths ───────────────────────────────────────
        if filename:
            ext = Path(filename).suffix.lower()
            if ext == ".pdf":
                return AgentMode.PDF
            if ext in (".csv", ".xlsx", ".xls", ".xlsm"):
                return AgentMode.FILE_ANALYSIS

        # ── 7. Image routing ───────────────────────────────────────────────────
        if has_image:
            return AgentMode.OCR_IMAGE if any(p in lower for p in _OCR_PHRASES) else AgentMode.VISION
        if has_file:
            return AgentMode.FILE_ANALYSIS

        # ── 8. General follow-up ───────────────────────────────────────────────
        # Only route as follow-up when:
        #   a) There IS a previous result to follow up on
        #   b) Query is very short (≤6 words) — longer queries are new requests
        #   c) Query contains an explicit modification phrase
        # Crucially: RANK/TREND/SHARE patterns checked BEFORE this so
        # "Top 7 tech companies by revenue" never reaches here.
        if ctx.last_result and nwords <= 6:
            if any(kw in lower for kw in _FOLLOWUP_KEYWORDS):
                return AgentMode.FOLLOWUP

        # ── 9. Inline numeric data ─────────────────────────────────────────────
        # Threshold: >2 words (not >4) — catches "1-Day Return: +4.29%" (3 words)
        if _DATA_INLINE.search(text) and nwords > 2:
            return AgentMode.DIRECT_DATA

        # ══════════════════════════════════════════════════════════════════════
        # INTENT DETECTION — determines chart type downstream
        # ══════════════════════════════════════════════════════════════════════

        # ── 10. RANK intent → horizontal_bar ──────────────────────────────────
        if _RANK_PATTERN.match(text) and nwords > 3:
            return AgentMode.DIRECT_DATA
        if _RANK_BY_PATTERN.search(text) and nwords > 4:
            return AgentMode.DIRECT_DATA

        # ── 11. TREND intent → line chart ──────────────────────────────────────
        if _YEAR_RANGE.search(text):
            return AgentMode.DIRECT_DATA
        if _LAST_N_YEARS.search(text):
            return AgentMode.DIRECT_DATA
        if _TREND_PATTERN.search(text) and nwords > 4:
            return AgentMode.DIRECT_DATA

        # ── 12. SHARE/DISTRIBUTION intent → donut ─────────────────────────────
        if _SHARE_PATTERN.search(text) and nwords > 3:
            return AgentMode.DIRECT_DATA

        # ── 13. COMPARE intent → radar / grouped bar ───────────────────────────
        # "X vs Y vs Z" → chartable comparison, NOT knowledge_map
        if _COMPARE_PATTERN.search(text):
            return AgentMode.DIRECT_DATA

        # ── 14. Well-known chartable topics ───────────────────────────────────
        if _CHARTABLE_TOPICS.search(text) and nwords > 3:
            return AgentMode.DIRECT_DATA

        # ── 15. Long prose → knowledge_map ────────────────────────────────────
        if nwords > 30:
            return AgentMode.KNOWLEDGE_MAP

        # ── 16. File dashboard phrases without a file ─────────────────────────
        if _FILE_PHRASES.match(text):
            return AgentMode.FILE_ANALYSIS

        # ── 17. LLM fallback ──────────────────────────────────────────────────
        history_snippet = "\n".join(
            f"{t.role.upper()}: {t.content[:100]}"
            for t in ctx.turns[-4:]
        ) or "(no history)"

        user_msg = (
            f"History:\n{history_snippet}\n\n"
            f"Input ({nwords} words): \"{text}\"\n\n"
            "Classify the intent."
        )

        try:
            raw    = call_router_llm(_ROUTER_SYSTEM, [{"role": "user", "content": user_msg}])
            result = extract_json(raw)
            mode   = result.get("mode", "direct_data")
            if mode == "needs_file":
                return AgentMode.FILE_ANALYSIS
            return AgentMode(mode)
        except Exception:
            return AgentMode.KNOWLEDGE_MAP if nwords > 8 else AgentMode.DIRECT_DATA