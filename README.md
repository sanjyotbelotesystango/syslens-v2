# sYsLens v2 — Autonomous Data Intelligence Engine

A production-grade multi-agent platform that acts as a Virtual Data Scientist.
Accepts text, files, and images — returns interactive Plotly visualizations.

---

## Project Structure

```
syslens_v2/
│
├── backend/                        ← Pure Python. Zero UI code.
│   ├── engine.py                   ← Single public interface (start here)
│   ├── config.py                   ← All settings, loaded from .env
│   ├── models.py                   ← All Pydantic models
│   ├── llm_client.py               ← Unified LLM client (4 providers)
│   ├── utils.py                    ← File reading + fingerprint builder
│   │
│   ├── memory/
│   │   └── session.py              ← Per-session conversation state
│   │
│   ├── project_agents/             ← One agent per input mode
│   │   ├── router_agent.py         ← Classifies intent
│   │   ├── analyst_agent.py        ← Direct data + follow-ups
│   │   ├── graph_agent.py          ← File analysis (2-stage)
│   │   ├── knowledge_agent.py      ← Concept → sunburst / treemap
│   │   └── vision_agent.py         ← Image → chart
│   │
│   ├── project_mcp/
│   │   └── sandbox_client.py       ← Docker / subprocess execution
│   │
│   └── visualizations/
│       └── plotly_factory.py       ← Builds Plotly figures from spec
│
├── frontend/
│   └── app.py                      ← Streamlit UI (imports engine only)
│
├── .streamlit/config.toml          ← Dark theme
├── Dockerfile.sandbox              ← Secure sandbox image
├── requirements.txt
└── .env.example                    ← Configuration template
```

---

## Quick Start

```bash
# 1. Enter project
cd syslens_v2

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
venv\Scripts\activate.bat         # Windows

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure credentials
cp .env.example .env
# Edit .env — set OPENAI_API_KEY and GROQ_API_KEY at minimum

# 5. Run
streamlit run frontend/app.py
```

Browser opens at **http://localhost:8501**

---

## Minimum .env (what you actually need)

```env
LLM_PROVIDER=openai
ROUTER_PROVIDER=groq

OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
```

Get a free Groq key at https://console.groq.com

---

## The Four Input Modes

| Mode | Trigger | What happens |
|---|---|---|
| `direct_data` | Paste raw numbers or a table | LLM extracts structure → chart |
| `knowledge_map` | "What is X?" / "Explain Y" | LLM builds hierarchy → sunburst / treemap |
| `vision` | Upload a chart screenshot | Vision LLM reads pixels → recreates chart |
| `file_analysis` | Upload CSV / Excel | LLM writes Python → sandbox executes → chart |

Follow-up messages ("make that a pie chart", "show top 5") automatically mutate
the previous visualization using conversation memory.

---

## Using the Engine as a Tool

The backend is completely decoupled from Streamlit.
Any web app, API, or LLM tool can call it directly:

```python
from backend.engine import SyslensEngine
from backend.models import AnalysisRequest

engine = SyslensEngine()

# Text data
result = engine.analyze(AnalysisRequest(
    text="Q1: 120K, Q2: 145K, Q3: 98K, Q4: 210K",
    session_id="my_session",
))

print(result.insight)          # analytical finding
print(result.spec.chart_type)  # ChartType.BAR
print(result.spec.series)      # list of ChartSeries

# File
with open("sales.csv", "rb") as f:
    result = engine.analyze(AnalysisRequest(
        text="Show monthly revenue trend",
        file_bytes=f.read(),
        filename="sales.csv",
        session_id="my_session",
    ))

# Follow-up (uses session memory automatically)
result2 = engine.analyze(AnalysisRequest(
    text="Now make that a pie chart",
    session_id="my_session",
))

# Render with Plotly
from backend.visualizations.plotly_factory import build
fig = build(result.spec)
fig.show()
```

---

## Supported Chart Types

`bar` · `horizontal_bar` · `line` · `area` · `pie` · `donut` ·
`scatter` · `histogram` · `box` · `radar` · `funnel` · `waterfall` ·
`sunburst` · `treemap`

---

## Supported LLM Providers

| Provider | Key | Used for |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | Main agents + vision (gpt-4o) |
| `groq` | `GROQ_API_KEY` | Router agent (8b-instant, ~200ms) |
| `anthropic` | `ANTHROPIC_API_KEY` | Alternative (Claude) |
| `azure` | `AZURE_OPENAI_API_KEY` | Legacy (inherited from original) |

Set `LLM_PROVIDER` in `.env` to switch the main provider.
`ROUTER_PROVIDER` defaults to `groq` and falls back to `LLM_PROVIDER` if
`GROQ_API_KEY` is not set.

---

## Docker Sandbox (optional)

Used by the File Analysis agent for secure code execution.
Without Docker, the engine falls back to a subprocess automatically.

```bash
# Build once
docker build -f Dockerfile.sandbox -t syslens-sandbox:latest .

# Verify
docker images | grep syslens-sandbox
```

---

## Original Codebase Inheritance

| Original file | Status |
|---|---|
| `config.py` | Extended — added OpenAI, Groq, Anthropic |
| `models.py` | Extended — added ChartType, VisualizationSpec, memory models; legacy models kept |
| `llm_utils.py` | Replaced by `backend/llm_client.py` — same concept, all 4 providers |
| `utils.py` | Extended — `extract_metadata` and `save_file` preserved; added `build_file_fingerprint` |
| `project_agents/analyst_agent.py` | Extended — same name, same role, new capabilities |
| `project_agents/graph_agent.py` | Extended — same name, now 2-stage pipeline |
| `project_mcp/sandbox_client.py` | Extended — same name, Docker + subprocess fallback |
