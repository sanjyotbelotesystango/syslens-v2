"""
frontend/app.py — sYsLens v2 Streamlit UI.

Built to match the reference app's UX patterns:
  - Sidebar: logo, new chat, analytics, file upload, image upload, suggested questions
  - Main area: full-width chat with mode pills, KPI rows, Plotly charts, summary
  - SQLite analytics via db_logger
  - Friendly error messages for rate limits, timeouts, sandbox failures
  - st.status() with live step messages during analysis

The frontend imports ONLY from backend.engine — no agent logic here.
"""

import sys
import time
import re
import logging
import traceback
from pathlib import Path

import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.engine import SyslensEngine
from backend.models import AnalysisRequest, AnalysisResult, KPICard
from backend.config import settings
sys.path.insert(0, str(Path(__file__).parent))
from db_logger import init_db, log_query, get_stats, get_recent

# ── Logging — all levels print to terminal ─────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("syslens.frontend")

# ── DB init ────────────────────────────────────────────────────────────────────
init_db()

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="sYsLens",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Design tokens — dark mode (default) ────────────── */
:root {
  --bg:           #0d0d16;
  --surface:      #12121e;
  --surface2:     #18182a;
  --surface3:     #1e1e30;
  --border:       #252538;
  --border-hi:    #34344e;
  --accent:       #7c6fff;
  --accent-soft:  rgba(124,111,255,0.15);
  --accent-glow:  rgba(124,111,255,0.20);
  --accent2:      #fbbf24;
  --accent3:      #34d399;
  --text:         #dcdcf0;
  --text-mid:     #8888a8;
  --text-dim:     #484868;
  --green:        #34d399;
  --red:          #f87171;
  --input-bg:     #1a1a2c;
  --input-text:   #dcdcf0;
  --btn-file-bg:  #252538;
  --btn-file-fg:  #9898b8;
}

/* ── Light mode tokens ──────────────────────────────── */
[data-theme="light"] {
  --bg:           #f4f4f8;
  --surface:      #ffffff;
  --surface2:     #f0f0f6;
  --surface3:     #e8e8f2;
  --border:       #dcdce8;
  --border-hi:    #c8c8de;
  --accent:       #6c5fff;
  --accent-soft:  rgba(108,95,255,0.10);
  --accent-glow:  rgba(108,95,255,0.18);
  --accent2:      #d97706;
  --accent3:      #059669;
  --text:         #1a1a2e;
  --text-mid:     #505070;
  --text-dim:     #9090b0;
  --green:        #059669;
  --red:          #dc2626;
  --input-bg:     #ffffff;
  --input-text:   #1a1a2e;
  --btn-file-bg:  #f0f0f6;
  --btn-file-fg:  #505070;
}

/* ── Base ───────────────────────────────────────────── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.main .block-container {
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: 'Inter', sans-serif !important;
}

/* ── Sidebar toggle arrow — always visible ─────────── */
/* The collapse/expand button Streamlit renders as a chevron */
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"],
button[kind="header"],
[aria-label="Close sidebar"],
[aria-label="Open sidebar"],
.st-emotion-cache-1cyp863,
.st-emotion-cache-pkbazv  {
  background: var(--surface3) !important;
  border: 1px solid var(--border-hi) !important;
  border-radius: 8px !important;
  color: var(--text) !important;
  opacity: 1 !important;
  visibility: visible !important;
}
/* The actual SVG arrow icon inside toggle */
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="stSidebarCollapseButton"] svg,
button[kind="header"] svg {
  fill: var(--text-mid) !important;
  color: var(--text-mid) !important;
  stroke: var(--text-mid) !important;
}
/* Position the collapsed-state toggle so it always shows */
[data-testid="stSidebarCollapsedControl"] {
  position: fixed !important;
  top: 1rem !important;
  left: .75rem !important;
  z-index: 9999 !important;
  width: 2.2rem !important;
  height: 2.2rem !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}

/* ── Sidebar ───────────────────────────────────────── */
[data-testid="stSidebar"] {
  background: var(--surface) !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] * {
  color: var(--text) !important;
}
[data-testid="stSidebar"] .stMarkdown p {
  font-size: .80rem !important;
  color: var(--text-mid) !important;
  line-height: 1.65 !important;
}
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] strong {
  color: var(--text) !important;
  font-size: .82rem !important;
}

/* ── Buttons (sidebar & general) ──────────────────── */
.stButton > button {
  background: linear-gradient(135deg, var(--accent) 0%, #9b8fff 100%) !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: 10px !important;
  font-family: 'Inter', sans-serif !important;
  font-weight: 600 !important;
  font-size: .88rem !important;
  padding: .55rem 1.2rem !important;
  transition: all .2s ease !important;
  width: 100% !important;
  letter-spacing: .02em !important;
}
.stButton > button:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 20px var(--accent-glow) !important;
}
.stButton > button:active { transform: translateY(0px) !important; }

/* ── File uploader ─────────────────────────────────── */
[data-testid="stFileUploader"] {
  background: var(--surface2) !important;
  border: 1.5px dashed var(--border-hi) !important;
  border-radius: 12px !important;
  padding: .5rem .75rem !important;
}
[data-testid="stFileUploader"] label,
[data-testid="stFileUploader"] p,
[data-testid="stFileUploader"] small,
[data-testid="stFileUploader"] span {
  color: var(--text-mid) !important;
  font-size: .78rem !important;
}
/* Browse files button — FIX: was black on dark */
[data-testid="stFileUploader"] button,
[data-testid="stFileUploaderDeleteBtn"] {
  background: var(--btn-file-bg) !important;
  border: 1px solid var(--border-hi) !important;
  color: var(--btn-file-fg) !important;
  border-radius: 8px !important;
  font-family: 'Inter', sans-serif !important;
  font-size: .80rem !important;
  font-weight: 500 !important;
  width: auto !important;
  min-width: 7rem !important;
  padding: .35rem .9rem !important;
  transition: all .15s !important;
}
[data-testid="stFileUploader"] button:hover {
  background: var(--accent-soft) !important;
  border-color: var(--accent) !important;
  color: var(--accent) !important;
  transform: none !important;
  box-shadow: none !important;
}

/* ── Chat input — NO WHITE GLOW ────────────────────── */
/* Kill the outer Streamlit wrapper glow/shadow */
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
.stChatFloatingInputContainer,
.stChatFloatingInputContainer > div {
  background: var(--bg) !important;
  border-top: 1px solid var(--border) !important;
  box-shadow: none !important;
}
[data-testid="stChatInput"] {
  background: transparent !important;
  box-shadow: none !important;
  border: none !important;
}
/* The actual textarea */
[data-testid="stChatInput"] textarea {
  background: var(--input-bg) !important;
  color: var(--input-text) !important;
  border: 1.5px solid var(--border-hi) !important;
  border-radius: 12px !important;
  font-family: 'Inter', sans-serif !important;
  font-size: .92rem !important;
  padding: .7rem 1rem !important;
  caret-color: var(--accent) !important;
  line-height: 1.5 !important;
  box-shadow: none !important;
  outline: none !important;
  resize: none !important;
}
[data-testid="stChatInput"] textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px var(--accent-soft) !important;
  outline: none !important;
}
[data-testid="stChatInput"] textarea::placeholder {
  color: var(--text-dim) !important;
  opacity: 1 !important;
}
/* Send button */
[data-testid="stChatInput"] button,
[data-testid="stChatInputSubmitButton"] {
  background: var(--accent) !important;
  border-radius: 9px !important;
  border: none !important;
  width: auto !important;
  padding: .4rem .7rem !important;
  transition: background .15s !important;
}
[data-testid="stChatInput"] button:hover,
[data-testid="stChatInputSubmitButton"]:hover {
  background: #9b8fff !important;
  transform: none !important;
  box-shadow: none !important;
}

/* ── Text area ─────────────────────────────────────── */
.stTextArea textarea {
  background: var(--input-bg) !important;
  color: var(--input-text) !important;
  border: 1px solid var(--border-hi) !important;
  border-radius: 10px !important;
  font-family: 'JetBrains Mono', monospace !important;
}

/* ── Chat messages ─────────────────────────────────── */
[data-testid="stChatMessage"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 14px !important;
  margin-bottom: .7rem !important;
  padding: .2rem 0 !important;
}
[data-testid="stChatMessage"] p {
  color: var(--text) !important;
  font-size: .90rem !important;
  line-height: 1.75 !important;
}

/* ── Expanders ─────────────────────────────────────── */
[data-testid="stExpander"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
}
[data-testid="stExpander"] summary {
  font-family: 'Inter', sans-serif !important;
  font-size: .82rem !important;
  color: var(--text-mid) !important;
  font-weight: 500 !important;
}
[data-testid="stExpander"] summary:hover { color: var(--text) !important; }

/* ── Metrics / KPI ─────────────────────────────────── */
[data-testid="metric-container"] {
  background: var(--surface2) !important;
  border: 1px solid var(--border) !important;
  border-radius: 12px !important;
  padding: 1rem 1.1rem !important;
}
[data-testid="stMetricLabel"] {
  color: var(--text-dim) !important;
  font-size: .70rem !important;
  text-transform: uppercase !important;
  letter-spacing: .07em !important;
}
[data-testid="stMetricValue"] {
  color: var(--accent2) !important;
  font-weight: 700 !important;
  font-size: 1.35rem !important;
}
[data-testid="stMetricDelta"] { font-size: .78rem !important; }

/* ── Status widget ─────────────────────────────────── */
[data-testid="stStatus"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
}
[data-testid="stStatus"] p { color: var(--text-mid) !important; font-size: .82rem !important; }

/* ── Code blocks ───────────────────────────────────── */
[data-testid="stCode"], .stCode, pre {
  background: #09091a !important;
  border: 1px solid var(--border) !important;
  border-radius: 8px !important;
}
pre code, code {
  font-family: 'JetBrains Mono', monospace !important;
  font-size: .82rem !important;
  color: #c8d0f8 !important;
}

/* ── Dividers ──────────────────────────────────────── */
hr { border-color: var(--border) !important; margin: .65rem 0 !important; }

/* ── Streamlit chrome ──────────────────────────────── */
#MainMenu, footer,
[data-testid="stDecoration"]     { visibility: hidden !important; height: 0 !important; }
header[data-testid="stHeader"]   { background: transparent !important; }

/* ── Scrollbar ─────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-hi); border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

/* ── Caption / small ───────────────────────────────── */
[data-testid="stCaptionContainer"] p,
.stCaption, small { color: var(--text-dim) !important; font-size: .75rem !important; }

/* ── Select / radio / checkbox ─────────────────────── */
[data-testid="stSelectbox"] > div > div,
[data-testid="stMultiSelect"] > div > div {
  background: var(--surface2) !important;
  border-color: var(--border-hi) !important;
  color: var(--text) !important;
}

/* ══════════════════════════════════════════════════════
   CUSTOM CLASSES
   ══════════════════════════════════════════════════════ */

/* Logo */
.logo {
  font-family: 'Inter', sans-serif;
  font-weight: 800;
  font-size: 1.65rem;
  background: linear-gradient(135deg, #7c6fff 0%, #fbbf24 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: .1rem;
  letter-spacing: -.02em;
}
.tagline {
  font-size: .62rem;
  color: var(--text-dim);
  letter-spacing: .20em;
  text-transform: uppercase;
  margin-bottom: .9rem;
  font-weight: 500;
}

/* Theme toggle pill */
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  background: var(--surface2);
  border: 1px solid var(--border-hi);
  border-radius: 20px;
  padding: .22rem .75rem;
  font-size: .72rem;
  color: var(--text-mid);
  cursor: pointer;
  transition: all .2s;
  user-select: none;
}
.theme-toggle:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* Mode pills */
.mode-pill {
  display: inline-flex;
  align-items: center;
  gap: .3rem;
  font-size: .64rem;
  text-transform: uppercase;
  letter-spacing: .08em;
  padding: .22rem .9rem;
  border-radius: 20px;
  margin-bottom: .85rem;
  font-family: 'Inter', sans-serif;
  font-weight: 700;
}
.mode-file      { background:rgba(124,111,255,.10); color:#9b8fff; border:1px solid rgba(124,111,255,.28); }
.mode-text      { background:rgba(52,211,153,.07);  color:#34d399; border:1px solid rgba(52,211,153,.22); }
.mode-general   { background:rgba(251,191,36,.07);  color:#fbbf24; border:1px solid rgba(251,191,36,.22); }
.mode-image     { background:rgba(99,179,237,.07);  color:#63b3ed; border:1px solid rgba(99,179,237,.22); }
.mode-pdf       { background:rgba(248,113,113,.07); color:#f87171; border:1px solid rgba(248,113,113,.22); }
.mode-knowledge { background:rgba(124,111,255,.08); color:#a78bfa; border:1px solid rgba(124,111,255,.22); }

/* Blocks */
.answer-block {
  background: var(--surface2);
  border-left: 3px solid var(--accent);
  border-radius: 0 10px 10px 0;
  padding: .85rem 1.3rem;
  font-size: .88rem;
  line-height: 1.8;
  color: var(--text);
  margin: .45rem 0 .75rem;
}
.summary-block {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: .85rem 1.3rem;
  font-size: .84rem;
  line-height: 1.8;
  margin-top: .55rem;
}
.error-block {
  background: rgba(248,113,113,.06);
  border: 1px solid rgba(248,113,113,.28);
  border-radius: 10px;
  padding: .75rem 1.2rem;
  color: #fca5a5;
  font-size: .84rem;
  line-height: 1.7;
}
.file-meta {
  font-size: .71rem;
  color: var(--text-dim);
  margin-top: .35rem;
  display: flex;
  gap: .9rem;
  flex-wrap: wrap;
}
.file-meta span { color: var(--accent3); font-weight: 600; }

.stat-row { font-size: .74rem; line-height: 2.1; color: var(--text-mid); }
.hist-item {
  font-size: .70rem;
  color: var(--text-dim);
  padding: .13rem 0;
  border-bottom: 1px solid rgba(255,255,255,.03);
}
.hist-sub { font-size: .64rem; color: var(--text-dim); opacity: .6; }
.input-hint {
  font-size: .75rem;
  color: var(--text-mid);
  line-height: 1.8;
}
.input-hint strong { color: var(--text); }
</style>
""", unsafe_allow_html=True)


# ── Session state defaults ─────────────────────────────────────────────────────
_DEFAULTS = {
    "messages":     [],
    "file_path":    None,
    "file_meta":    {},
    "file_cols":    [],
    "image_bytes":  None,
    "image_mime":   None,
    "chat_history": [],
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

if "engine" not in st.session_state:
    st.session_state.engine = SyslensEngine()

# Theme: default dark, toggleable
if "theme_dark" not in st.session_state:
    st.session_state.theme_dark = True

# Inject data-theme attribute into <html> so CSS variables switch
_theme_attr = "" if st.session_state.theme_dark else 'data-theme="light"'
st.markdown(
    f'<script>document.documentElement.setAttribute("data-theme", '
    f'"{("" if st.session_state.theme_dark else "light")}");</script>',
    unsafe_allow_html=True,
)

SESSION_ID = "streamlit_default"
engine: SyslensEngine = st.session_state.engine


# ── Constants ──────────────────────────────────────────────────────────────────
_MODE_PILL = {
    "direct_data":   ("mode-text",      "◈ direct data"),
    "knowledge_map": ("mode-knowledge", "◈ knowledge map"),
    "vision":        ("mode-image",     "◈ vision"),
    "ocr_image":     ("mode-image",     "◈ ocr extraction"),
    "file_analysis": ("mode-file",      "◈ file analysis"),
    "pdf":           ("mode-pdf",       "◈ pdf analysis"),
    "followup":      ("mode-general",   "◈ follow-up"),
}

_SUGGESTIONS = [
    {"keys": ["spend","amount","cost","revenue","value","total"],  "icon": "💰", "text": "Show top 10 items by value"},
    {"keys": ["supplier","vendor","partner","company"],            "icon": "🏢", "text": "Which supplier has the most records?"},
    {"keys": ["date","month","year","period","week","quarter"],    "icon": "📈", "text": "Show trend over time"},
    {"keys": ["country","region","location","city","state"],       "icon": "🌍", "text": "Breakdown by geography"},
    {"keys": ["category","type","segment","class","group"],        "icon": "🏷️",  "text": "Breakdown by category"},
    {"keys": ["unit","department","division","team","branch"],     "icon": "📊", "text": "Compare by business unit"},
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def friendly_error(e: Exception) -> str:
    msg = str(e)
    if "429" in msg or "rate_limit" in msg.lower():
        wait = re.search(r"try again in ([\d\.]+[smh])", msg)
        return f"⏳ <strong>Rate limit reached.</strong>{' Wait ' + wait.group(1) + '.' if wait else ' Please wait a moment.'}"
    if "timeout" in msg.lower():
        return "⏱ <strong>Request timed out.</strong> Please try again."
    if "sandbox" in msg.lower() or "docker" in msg.lower():
        return "🐳 <strong>Sandbox error.</strong> Check Docker or subprocess permissions."
    if "api_key" in msg.lower() or "authentication" in msg.lower():
        return "🔑 <strong>API key error.</strong> Check your .env file."
    return f"⚠ <strong>Error:</strong> {msg.split(chr(10))[0][:220]}"


def _get_suggestions(cols: list) -> list:
    lower = " ".join(c.lower() for c in cols)
    out = []
    for s in _SUGGESTIONS:
        if any(k in lower for k in s["keys"]):
            out.append(s)
        if len(out) == 4:
            break
    return out


def _render_kpi_row(kpis: list) -> None:
    if not kpis:
        return
    cols = st.columns(min(len(kpis), 4))
    for col, kpi in zip(cols, kpis[:4]):
        with col:
            delta_str = None
            if kpi.delta is not None:
                sign = "+" if kpi.delta >= 0 else ""
                delta_str = f"{sign}{kpi.delta:.1f}"
                if kpi.delta_label:
                    delta_str += f" {kpi.delta_label}"
            st.metric(label=kpi.label, value=kpi.display_value(), delta=delta_str)


def _render_summary(insight: str, stats: dict, cleaning: list) -> None:
    if insight:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", insight) if s.strip()]
        if len(sentences) >= 3:
            labels = ["Trend", "Comparison", "Outlook"]
            parts  = "".join(
                f'<div style="display:flex;gap:.5rem;margin-bottom:.4rem;">'
                f'<span style="color:#6c63ff;font-weight:700;flex-shrink:0;min-width:80px">{lbl}:</span>'
                f'<span style="color:#9ca3af">{s}</span></div>'
                for lbl, s in zip(labels, sentences[:3])
            )
            st.markdown(
                f'<div class="summary-block">'
                f'<div style="color:#e2e2f0;font-weight:700;margin-bottom:.6rem;font-family:Syne,sans-serif;">◈ Summary</div>'
                f'{parts}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f'<div class="answer-block">{insight}</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if stats:
            with st.expander("📊 Dataset stats", expanded=False):
                for k, v in stats.items():
                    st.markdown(
                        f'<span style="color:#5a5a72">{k}:</span> '
                        f'<span style="color:#e2e2f0;font-weight:600">{v}</span>',
                        unsafe_allow_html=True,
                    )
    with c2:
        if cleaning:
            with st.expander("🔧 Processing pipeline", expanded=False):
                for step in cleaning:
                    st.markdown(
                        f'<span style="color:#4ade80">✓</span> '
                        f'<span style="color:#9ca3af">{step}</span>',
                        unsafe_allow_html=True,
                    )


def render_result(result: AnalysisResult, msg_idx: int = 0) -> None:
    """Render one AnalysisResult: mode pill → KPIs → chart → summary → view code."""
    if result is None:
        st.markdown('<div class="error-block">⚠ No response generated.</div>', unsafe_allow_html=True)
        return

    # ── Greeting mode: just show text, no chart ────────────────────────────────
    if result.mode == "greeting":
        st.markdown(f'<div class="answer-block">{result.insight}</div>', unsafe_allow_html=True)
        return

    pill_cls, pill_label = _MODE_PILL.get(result.mode, ("mode-general", f"◈ {result.mode}"))
    st.markdown(f'<span class="mode-pill {pill_cls}">{pill_label}</span>', unsafe_allow_html=True)

    if result.kpis:
        _render_kpi_row(result.kpis)
        st.markdown("")

    if result.spec:
        st.caption(f"`{result.spec.chart_type.value.upper()}` · `{result.spec.title}`")
        try:
            fig = engine.get_figure(result)
            import hashlib
            # Key = spec hash + message position index.
            # The index makes every chart in the conversation unique,
            # even when a follow-up produces an identical spec to a previous turn.
            spec_hash = hashlib.md5(result.spec.model_dump_json().encode()).hexdigest()[:10]
            _chart_key = f"chart_{spec_hash}_{msg_idx}"
            st.plotly_chart(
                fig,
                key=_chart_key,
                use_container_width=True,
                config={
                    "displayModeBar": True,
                    "displaylogo": False,
                    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
                    "toImageButtonOptions": {"format": "png", "filename": "syslens_chart", "scale": 2},
                },
            )
        except Exception as err:
            st.markdown(f'<div class="error-block">⚠ Chart render error: {err}</div>', unsafe_allow_html=True)

    _render_summary(result.insight, result.stats, result.cleaning_steps)

    # ── View Code ──────────────────────────────────────────────────────────────
    if result.generated_code:
        with st.expander("🔍 View Code", expanded=False):
            mode_labels = {
                "file_analysis": "Python — Generated analysis script",
                "direct_data":   "Python — Extracted data spec",
                "followup":      "Python — Updated spec",
                "vision":        "Python — Vision extraction",
                "ocr_image":     "Python — OCR extraction",
                "knowledge_map": "Python — Knowledge map spec",
                "pdf":           "Python — PDF extraction spec",
            }
            st.caption(mode_labels.get(result.mode, "Python — Generated code"))
            st.code(result.generated_code, language="python")


# ── SIDEBAR ────────────────────────────────────────────────────────────────────
with st.sidebar:
    # Logo row + theme toggle on same line
    col_logo, col_theme = st.columns([3, 1])
    with col_logo:
        st.markdown('<div class="logo">sYsLens</div>', unsafe_allow_html=True)
        st.markdown('<div class="tagline">Data Intelligence · v2</div>', unsafe_allow_html=True)
    with col_theme:
        st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
        _icon = "☀️" if st.session_state.theme_dark else "🌙"
        _label = "Light" if st.session_state.theme_dark else "Dark"
        if st.button(f"{_icon}", key="theme_toggle", help=f"Switch to {_label} mode"):
            st.session_state.theme_dark = not st.session_state.theme_dark
            st.rerun()

    if st.button("✦ New Chat", key="new_chat"):
        for k, v in _DEFAULTS.items():
            st.session_state[k] = v
        engine.clear_session(SESSION_ID)
        engine.clear_cache()
        st.rerun()

    st.markdown("---")

    # Analytics panel
    with st.expander("📊 Query Analytics", expanded=False):
        try:
            stats = get_stats()
            if stats and stats.get("queries", 0):
                st.markdown(
                    f'<div class="stat-row">'
                    f'Queries: <b>{stats["queries"]}</b> &nbsp;|&nbsp; Charts: <b>{stats["visuals"]}</b><br>'
                    f'Avg time: <b>{stats["avg_duration"]}s</b> &nbsp;|&nbsp; Success: <b>{stats["success_rate"]}%</b>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("**Recent:**")
                for row in get_recent(5):
                    q    = row["question"][:34] + "…" if len(row["question"]) > 34 else row["question"]
                    icon = "✅" if row["success"] else "❌"
                    st.markdown(
                        f'<div class="hist-item">{icon} {q}<br>'
                        f'<span class="hist-sub">{row["mode"]} · {row["duration_seconds"]:.1f}s'
                        f' · {row["visual_count"]} chart · {row["kpi_count"]} KPI</span></div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown('<div class="input-hint">No queries yet.</div>', unsafe_allow_html=True)
        except Exception as err:
            st.markdown(f'<div class="error-block" style="font-size:.74rem">DB: {err}</div>', unsafe_allow_html=True)

    st.markdown("---")

    # File upload
    st.markdown("**Data Source** *(CSV · Excel · PDF)*")
    uploaded_file = st.file_uploader(
        label="Upload file", type=["xlsx", "xls", "csv", "pdf"],
        label_visibility="collapsed", key="sidebar_file",
    )
    if uploaded_file:
        if uploaded_file.size > 20 * 1024 * 1024:
            st.error(f"File too large ({uploaded_file.size/1024/1024:.1f} MB). Max 20 MB.")
        else:
            up_dir = Path(__file__).parent.parent / "data" / "uploads"
            up_dir.mkdir(parents=True, exist_ok=True)
            save_path = up_dir / uploaded_file.name
            save_path.write_bytes(uploaded_file.getvalue())
            st.session_state.file_path = str(save_path)

            ext = Path(uploaded_file.name).suffix.lower()
            st.session_state.file_cols = []
            if ext != ".pdf":
                try:
                    df = (pd.read_csv(str(save_path)) if ext == ".csv"
                          else pd.read_excel(str(save_path)))
                    df.columns = df.columns.str.strip()
                    st.session_state.file_cols = list(df.columns)
                    st.session_state.file_meta = {
                        "filename": uploaded_file.name,
                        "rows": len(df), "cols": len(df.columns),
                        "size": (f"{uploaded_file.size/1024:.0f} KB"
                                 if uploaded_file.size < 1_048_576
                                 else f"{uploaded_file.size/1_048_576:.1f} MB"),
                    }
                except Exception:
                    st.session_state.file_meta = {"filename": uploaded_file.name}
            else:
                st.session_state.file_meta = {
                    "filename": uploaded_file.name,
                    "size": f"{uploaded_file.size/1024:.0f} KB",
                }

            st.success(f"📎 {uploaded_file.name}")
            m = st.session_state.file_meta
            parts = []
            if m.get("rows"):
                parts.append(f'Rows <span>{m["rows"]:,}</span>')
            if m.get("cols"):
                parts.append(f'Cols <span>{m["cols"]}</span>')
            if m.get("size"):
                parts.append(m["size"])
            if parts:
                st.markdown(f'<div class="file-meta">{" &nbsp; ".join(parts)}</div>', unsafe_allow_html=True)

            sugs = _get_suggestions(st.session_state.file_cols)
            if sugs:
                st.markdown("---")
                st.markdown("**Suggested Questions**")
                for s in sugs:
                    if st.button(f"{s['icon']} {s['text']}", key=f"sug_{s['text']}"):
                        st.session_state["_prefill"] = s["text"]

    st.markdown("---")

    # Image upload
    st.markdown("**Image Input** *(chart · table · report)*")
    uploaded_img = st.file_uploader(
        label="Upload image", type=["png", "jpg", "jpeg", "webp"],
        label_visibility="collapsed", key="sidebar_img",
    )
    if uploaded_img:
        st.session_state.image_bytes = uploaded_img.getvalue()
        st.session_state.image_mime  = uploaded_img.type
        st.success(f"🖼 {uploaded_img.name}")
        if st.button("📊 Visualize Image Data", key="viz_img"):
            st.session_state["_prefill_image"] = True

    st.markdown("---")

    st.markdown(
        '<div class="input-hint">'
        '📋 <strong>Paste any data</strong> — tables, JSON, stats, financial metrics.<br><br>'
        '💬 <strong>Ask any question</strong> — get charts, KPIs, and insights.<br><br>'
        '📁 <strong>Upload a file</strong> — CSV, Excel, PDF, or image above.'
        '</div>',
        unsafe_allow_html=True,
    )

    history = st.session_state.chat_history
    if history:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown(
                f'<div style="font-size:.68rem;color:var(--text-dim);padding-top:.3rem">'
                f'🧠 {len(history)} turn{"s" if len(history) != 1 else ""} in memory</div>',
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("🗑", key="clear_mem", help="Clear memory"):
                st.session_state.chat_history = []
                st.rerun()

    st.markdown("---")
    st.markdown(
        '<div style="font-size:.65rem;color:var(--text-dim);text-align:center;letter-spacing:.06em">◈ sYsLens · v2</div>',
        unsafe_allow_html=True,
    )


# ── MAIN AREA ──────────────────────────────────────────────────────────────────
st.markdown("---")

# Render existing messages
for _msg_idx, msg in enumerate(st.session_state.messages):
    avatar = "🧑" if msg["role"] == "user" else "🤖"
    with st.chat_message(msg["role"], avatar=avatar):
        if msg["content_type"] == "text":
            st.markdown(msg["content"])
        elif msg["content_type"] == "result":
            render_result(msg["content"], msg_idx=_msg_idx)
        elif msg["content_type"] == "error":
            st.markdown(f'<div class="error-block">{msg["content"]}</div>', unsafe_allow_html=True)

# Empty state
if not st.session_state.messages:
    st.markdown(
        '<div style="text-align:center;padding:5rem 2rem;">'
        '<div style="font-size:3rem;margin-bottom:1.2rem;opacity:.5">◈</div>'
        '<div style="font-size:1.05rem;color:var(--text-mid);font-weight:600;margin-bottom:.6rem;letter-spacing:-.01em">'
        'sYsLens Data Intelligence</div>'
        '<div style="font-size:.84rem;color:var(--text-dim);line-height:2.1;max-width:380px;margin:0 auto">'
        '📁 Upload a spreadsheet, PDF, or image<br>'
        '📊 Paste raw numbers, tables, or JSON<br>'
        '💬 Ask any question — get charts &amp; insights'
        '</div></div>',
        unsafe_allow_html=True,
    )


# ── Input / prefill ────────────────────────────────────────────────────────────
prefill       = st.session_state.pop("_prefill", "")
trigger_image = st.session_state.pop("_prefill_image", False)
user_input    = st.chat_input(placeholder="Ask anything · paste data · describe a follow-up…")
if prefill:
    user_input = prefill


# ── Image trigger ──────────────────────────────────────────────────────────────
if trigger_image and st.session_state.image_bytes:
    _q = "Visualize the data in this uploaded image"

    with st.chat_message("user", avatar="🧑"):
        st.markdown("🖼 Visualize uploaded image data")
    st.session_state.messages.append(
        {"role": "user", "content_type": "text", "content": "🖼 Visualize uploaded image data"}
    )

    with st.chat_message("assistant", avatar="🤖"):
        with st.status("Analysing image…", expanded=True) as _status:
            st.write("⏳ Detecting data in image…")
            st.write("⏳ Extracting values and labels…")
            st.write("⏳ Building visualization…")
            _t0 = time.time()
            try:
                _result = engine.analyze(AnalysisRequest(
                    text        = _q,
                    image_bytes = st.session_state.image_bytes,
                    image_type  = st.session_state.image_mime or "image/png",
                    session_id  = SESSION_ID,
                ))
                _dur = time.time() - _t0
                _status.update(label=f"Done ✓  ({_dur:.1f}s)", state="complete", expanded=False)

                # FIX: clear image bytes after successful vision/OCR analysis
                # so subsequent text queries are not re-routed to vision mode.
                if _result.mode in ("vision", "ocr_image"):
                    st.session_state.image_bytes = None
                    st.session_state.image_mime  = None

                log_query(question=_q, mode=_result.mode, provider=settings.LLM_PROVIDER,
                          model=settings.OPENAI_MODEL, success=True,
                          summary=_result.insight[:200], duration_seconds=_dur,
                          visual_count=1, kpi_count=len(_result.kpis))
                render_result(_result, msg_idx=len(st.session_state.messages))
                st.session_state.messages.append(
                    {"role": "assistant", "content_type": "result", "content": _result}
                )
                st.session_state.chat_history.append({"role": "assistant", "question": _q, "mode": _result.mode})
            except Exception as _e:
                _dur = time.time() - _t0
                _status.update(label="Error", state="error", expanded=False)
                _err = friendly_error(_e)
                st.markdown(f'<div class="error-block">{_err}</div>', unsafe_allow_html=True)
                log_query(question=_q, mode="vision", provider=settings.LLM_PROVIDER,
                          model=settings.OPENAI_MODEL, success=False,
                          error_message=str(_e)[:300], duration_seconds=_dur)


# ── Main chat ──────────────────────────────────────────────────────────────────
if user_input and user_input.strip():
    user_input = user_input.strip()

    with st.chat_message("user", avatar="🧑"):
        st.markdown(f"💬 {user_input}")
    st.session_state.messages.append(
        {"role": "user", "content_type": "text", "content": f"💬 {user_input}"}
    )

    with st.chat_message("assistant", avatar="🤖"):
        with st.status("Thinking…", expanded=True) as _status:
            st.write("⏳ Understanding your input…")
            st.write("⏳ Routing to the right agent…")
            st.write("⏳ Building visualizations…")
            st.write("⏳ Extracting KPIs and insights…")
            _t0 = time.time()

            def _on_progress(msg: str) -> None:
                _status.update(label=msg)

            try:
                # Read file bytes from saved path
                _file_bytes = None
                _filename   = None
                if st.session_state.file_path:
                    _p = Path(st.session_state.file_path)
                    if _p.exists():
                        _file_bytes = _p.read_bytes()
                        _filename   = _p.name

                # Only send image_bytes if user explicitly mentions the image
                # or if they haven't analyzed it yet (image just uploaded).
                # This prevents every text query from being routed to vision mode.
                _has_image_intent = st.session_state.image_bytes and (
                    any(w in user_input.lower() for w in
                        ["image", "photo", "picture", "chart", "graph", "table",
                         "extract", "read", "scan", "visualize", "what", "show"])
                )
                _img_bytes = st.session_state.image_bytes if _has_image_intent else None
                _img_mime  = st.session_state.image_mime  if _has_image_intent else None

                _result = engine.analyze(
                    AnalysisRequest(
                        text        = user_input,
                        file_bytes  = _file_bytes,
                        filename    = _filename,
                        image_bytes = _img_bytes,
                        image_type  = _img_mime,
                        session_id  = SESSION_ID,
                    ),
                    progress_cb=_on_progress,
                )
                _dur = time.time() - _t0
                _status.update(label=f"Done ✓  ({_dur:.1f}s)", state="complete", expanded=False)

                # FIX: clear image bytes after vision/OCR so next text query
                # is not misrouted to vision mode.
                if _result.mode in ("vision", "ocr_image"):
                    st.session_state.image_bytes = None
                    st.session_state.image_mime  = None

                log_query(
                    question=user_input, mode=_result.mode,
                    provider=settings.LLM_PROVIDER, model=settings.OPENAI_MODEL,
                    success=True, summary=_result.insight[:200],
                    duration_seconds=_dur, visual_count=1, kpi_count=len(_result.kpis),
                )

                render_result(_result, msg_idx=len(st.session_state.messages))
                st.session_state.messages.append(
                    {"role": "assistant", "content_type": "result", "content": _result}
                )
                st.session_state.chat_history.extend([
                    {"role": "user",      "question": user_input, "mode": _result.mode},
                    {"role": "assistant", "question": user_input, "mode": _result.mode,
                     "summary": _result.insight[:100]},
                ])
                if len(st.session_state.chat_history) > 20:
                    st.session_state.chat_history = st.session_state.chat_history[-20:]

            except Exception as _e:
                _dur = time.time() - _t0
                logger.error(
                    f"Frontend: request FAILED — mode=unknown\n"
                    f"Input: {user_input[:200]}\n"
                    f"{traceback.format_exc()}"
                )
                _err = friendly_error(_e)
                _status.update(label="Error", state="error", expanded=False)
                st.markdown(f'<div class="error-block">{_err}</div>', unsafe_allow_html=True)
                st.session_state.messages.append(
                    {"role": "assistant", "content_type": "error", "content": _err}
                )
                log_query(question=user_input, mode="unknown",
                          provider=settings.LLM_PROVIDER, model=settings.OPENAI_MODEL,
                          success=False, error_message=str(_e)[:300], duration_seconds=_dur)

    st.rerun()