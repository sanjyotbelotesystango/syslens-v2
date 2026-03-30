"""
tests/test_syslens.py — Full test suite for sYsLens v2. 117 tests.
Run: python tests/test_syslens.py
"""

import sys, re, math, json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

GREEN="\033[92m"; RED="\033[91m"; YELLOW="\033[93m"; CYAN="\033[96m"
RESET="\033[0m"; BOLD="\033[1m"

_pass=0; _fail=0; _skip=0; _results=[]

def ok(name):
    global _pass; _pass+=1; _results.append((True,name))
    print(f"  {GREEN}✓{RESET}  {name}")

def fail(name, reason=""):
    global _fail; _fail+=1; _results.append((False,name))
    print(f"  {RED}✗{RESET}  {name}")
    if reason: print(f"       {RED}{reason}{RESET}")

def skip(name, reason=""):
    global _skip; _skip+=1; _results.append((None,name))
    print(f"  {YELLOW}⊘{RESET}  {name} {YELLOW}(skipped: {reason}){RESET}")

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")

def assert_equal(val, expected, name):
    if val==expected: ok(name)
    else: fail(name, f"got {val!r}, expected {expected!r}")

def assert_true(cond, name, reason=""):
    if cond: ok(name)
    else: fail(name, reason)

def assert_raises(exc_type, fn, name):
    try:
        fn(); fail(name, f"Expected {exc_type.__name__} but no exception raised")
    except exc_type: ok(name)
    except Exception as e: fail(name, f"Expected {exc_type.__name__} but got {type(e).__name__}: {e}")


# ── 1. MODELS ─────────────────────────────────────────────────────────────────

def test_models():
    section("1. Models — Pydantic validation")
    from backend.models import (
        ChartType, ChartSeries, VisualizationSpec,
        AnalysisResult, AnalysisRequest, KPICard, AgentMode
    )
    assert_equal(ChartType("bar"),            ChartType.BAR,            "ChartType: 'bar' parses")
    assert_equal(ChartType("horizontal_bar"), ChartType.HORIZONTAL_BAR, "ChartType: 'horizontal_bar' parses")
    assert_equal(ChartType("sunburst"),       ChartType.SUNBURST,       "ChartType: 'sunburst' parses")
    assert_raises(ValueError, lambda: ChartType("column"),         "ChartType: 'column' is invalid")
    assert_raises(ValueError, lambda: ChartType("horizontal bar"), "ChartType: space variant is invalid")

    s = ChartSeries(name="test", x=["a","b","c"], y=[1.0, float("nan"), float("inf")])
    assert_true(all(v is None or math.isfinite(v) for v in s.y if v is not None),
                "ChartSeries: NaN and Inf replaced with None")
    assert_equal(len(s.y), 3, "ChartSeries: length preserved after cleaning")

    spec = VisualizationSpec(
        chart_type=ChartType.BAR,
        series=[ChartSeries(name="s", x=["a","b","c","d"], y=[1,2,3])]
    )
    assert_equal(len(spec.series[0].x), len(spec.series[0].y),
                 "VisualizationSpec: x/y auto-trimmed to same length")

    spec2 = VisualizationSpec(
        chart_type=ChartType.LINE,
        series=[ChartSeries(name="s", y=[10,20,30])]
    )
    assert_equal(len(spec2.series[0].x), 3, "VisualizationSpec: missing x auto-generated")

    assert_raises(
        Exception,
        lambda: VisualizationSpec(
            chart_type=ChartType.SUNBURST,
            series=[ChartSeries(name="s", x=["a"], y=[1])]
        ),
        "VisualizationSpec: sunburst without labels raises"
    )

    try:
        VisualizationSpec(
            chart_type=ChartType.SUNBURST,
            series=[ChartSeries(name="s",
                labels=["Root","A","B"], parents=["","Root","Root"], values=[0,50,50])]
        )
        ok("VisualizationSpec: valid sunburst passes")
    except Exception as e:
        fail("VisualizationSpec: valid sunburst passes", str(e))

    k1 = KPICard(label="Revenue", value=1_250_000, prefix="$")
    assert_equal(k1.display_value(), "$1.25M", "KPICard: $1.25M formatting")
    k2 = KPICard(label="Users", value=45_300, suffix=" users")
    assert_equal(k2.display_value(), "45.3K users", "KPICard: 45.3K formatting")
    k3 = KPICard(label="Rate", value=12.5, suffix="%", formatted="12.5%")
    assert_equal(k3.display_value(), "12.5%", "KPICard: formatted field takes priority")

    try:
        AnalysisRequest(text="test", file_bytes=b"hello", session_id="s1")
        ok("AnalysisRequest: bytes field accepted")
    except Exception as e:
        fail("AnalysisRequest: bytes field accepted", str(e))

    assert_equal(AgentMode("direct_data"),   AgentMode.DIRECT_DATA,   "AgentMode: direct_data")
    assert_equal(AgentMode("knowledge_map"), AgentMode.KNOWLEDGE_MAP, "AgentMode: knowledge_map")
    assert_equal(AgentMode("file_analysis"), AgentMode.FILE_ANALYSIS, "AgentMode: file_analysis")


# ── 2. ROUTER ─────────────────────────────────────────────────────────────────

def test_router():
    section("2. Router — Intent classification heuristics")
    from backend.models import AgentMode, SessionContext, VisualizationSpec, ChartSeries, ChartType, AnalysisResult
    from backend.project_agents.router_agent import RouterAgent, _DATA_PRESENT_PATTERNS, _CONCEPT_PHRASES, _STRONG_FOLLOWUP_WORDS, _KNOWLEDGE_TOPICS

    router    = RouterAgent()
    ctx_empty = SessionContext()

    def route(text, has_file=False, has_image=False, filename="", ctx=None):
        return router.route(text, ctx or ctx_empty, has_file=has_file,
                            has_image=has_image, filename=filename)

    assert_equal(route("analyze this", filename="data.csv"),  AgentMode.FILE_ANALYSIS, "Router: .csv -> file_analysis")
    assert_equal(route("analyze this", filename="report.xlsx"), AgentMode.FILE_ANALYSIS, "Router: .xlsx -> file_analysis")
    assert_equal(route("summarize this", filename="report.pdf"), AgentMode.PDF, "Router: .pdf -> pdf")

    assert_equal(route("visualize this", has_image=True), AgentMode.VISION, "Router: image -> vision (default)")
    assert_equal(route("extract data from this invoice", has_image=True), AgentMode.OCR_IMAGE,
                 "Router: image + 'extract invoice' -> ocr_image")

    for text, expected in [
        ("what is machine learning",            AgentMode.KNOWLEDGE_MAP),
        ("what are the SOLID principles",       AgentMode.KNOWLEDGE_MAP),
        ("explain quantum computing",           AgentMode.KNOWLEDGE_MAP),
        ("history of the internet",             AgentMode.KNOWLEDGE_MAP),
        ("describe how neural networks work",   AgentMode.KNOWLEDGE_MAP),
        ("timeline of artificial intelligence", AgentMode.KNOWLEDGE_MAP),
        ("principles of clean code",            AgentMode.KNOWLEDGE_MAP),
        ("introduction to blockchain",          AgentMode.KNOWLEDGE_MAP),
    ]:
        assert_equal(route(text), expected, f"Router: concept -> knowledge_map | '{text[:45]}'")

    # NEW: knowledge topics (investment rationale etc) → knowledge_map
    for text, expected in [
        ("investment rationale for Amazon",        AgentMode.KNOWLEDGE_MAP),
        ("investment thesis for Tesla",            AgentMode.KNOWLEDGE_MAP),
        ("competitive analysis of Netflix",        AgentMode.KNOWLEDGE_MAP),
        ("pros and cons of cloud computing",       AgentMode.KNOWLEDGE_MAP),
    ]:
        assert_equal(route(text), expected, f"Router: knowledge topic -> knowledge_map | '{text[:45]}'")

    # Data-present patterns → direct_data
    for text, expected in [
        ("Apple: $394B, Microsoft: $211B, Google: $282B",   AgentMode.DIRECT_DATA),
        ("VanEck Gold Miners ETF: +134.92%",                AgentMode.DIRECT_DATA),
        ("Q1: 120B, Q2: 135B, Q3: 142B, Q4: 158B",        AgentMode.DIRECT_DATA),
        ("iShares Silver Trust 1-Year Return: +162.19%",    AgentMode.DIRECT_DATA),
        ("Revenue: $1.2M growth rate: 15%",                 AgentMode.DIRECT_DATA),
    ]:
        assert_equal(route(text), expected, f"Router: numeric -> direct_data | '{text[:45]}'")

    for text in ["top 5 reasons AI is important", "3 key factors in software design",
                 "give me 4 examples of machine learning"]:
        lower = text.lower()
        concept_match = any(lower.startswith(p) for p in _CONCEPT_PHRASES)
        fin_match = bool(_DATA_PRESENT_PATTERNS.search(text)) and len(text.split()) > 4
        assert_true(not fin_match or concept_match,
                    f"Router: no false positive for '{text[:45]}'")

    # FIX: concept phrase beats file extension
    assert_equal(route("what is machine learning", filename="data.csv"),
                 AgentMode.KNOWLEDGE_MAP, "Router: concept phrase beats file extension")

    # FIX: strong follow-up beats file extension
    dummy = AnalysisResult(
        mode="direct_data",
        spec=VisualizationSpec(chart_type=ChartType.BAR,
                               series=[ChartSeries(name="s", x=["a"], y=[1.0])])
    )
    ctx_prev = SessionContext(last_result=dummy)
    assert_equal(route("make that a pie chart", filename="data.csv", ctx=ctx_prev),
                 AgentMode.FOLLOWUP, "Router: 'make' follow-up beats file extension")
    assert_equal(route("change to bar chart", filename="data.csv", ctx=ctx_prev),
                 AgentMode.FOLLOWUP, "Router: 'change' follow-up beats file extension")

    # Strong follow-up words check
    assert_true("make" in _STRONG_FOLLOWUP_WORDS, "Router: 'make' in _STRONG_FOLLOWUP_WORDS")
    assert_true("change" in _STRONG_FOLLOWUP_WORDS, "Router: 'change' in _STRONG_FOLLOWUP_WORDS")
    assert_true("convert" in _STRONG_FOLLOWUP_WORDS, "Router: 'convert' in _STRONG_FOLLOWUP_WORDS")

    # Knowledge topics list
    assert_true("investment rationale" in _KNOWLEDGE_TOPICS, "Router: 'investment rationale' in _KNOWLEDGE_TOPICS")

    # Data-present pattern tests
    for text, should_match, name in [
        ("12.5%",       True,  "percent pattern"),
        ("$394",        True,  "dollar pattern"),
        ("+134.92%",    True,  "signed percent pattern"),
        ("$1.2M",       True,  "dollar + M suffix"),
        ("15 billion",  True,  "billion word"),
        ("growth: 12",  True,  "keyword + number"),
        ("5 reasons",   False, "ordinal '5 reasons' no match"),
        ("top 3 tips",  False, "ordinal '3 tips' no match"),
        ("abc",         False, "pure text no match"),
    ]:
        assert_equal(bool(_DATA_PRESENT_PATTERNS.search(text)), should_match, f"Regex: {name}")


# ── 3. KPI BUILDER ────────────────────────────────────────────────────────────

def test_kpi_builder():
    section("3. KPI Builder — Deterministic math (zero hallucination)")
    from backend.visualizations.kpi_builder import _compute_candidates, _delta_meaningful, _detect_unit_suffix
    from backend.models import AnalysisResult, VisualizationSpec, ChartSeries, ChartType

    result = AnalysisResult(
        mode="direct_data",
        spec=VisualizationSpec(
            chart_type=ChartType.LINE,
            series=[ChartSeries(name="Revenue", x=["Q1","Q2","Q3","Q4"], y=[120.0,135.0,142.0,158.0])]
        )
    )
    candidates = _compute_candidates(result)
    assert_true(len(candidates) >= 1, "KPI: returns at least one candidate")
    c = candidates[0]
    assert_equal(c["total"],     555.0,  "KPI: total = Python sum (exact)")
    assert_equal(c["average"],   138.75, "KPI: average = Python mean (exact)")
    assert_equal(c["maximum"],   158.0,  "KPI: maximum = Python max (exact)")
    assert_equal(c["minimum"],   120.0,  "KPI: minimum = Python min (exact)")
    assert_equal(c["delta"],     38.0,   "KPI: delta = last - first (exact)")
    assert_equal(c["delta_pct"], 31.67,  "KPI: delta_pct = % change (exact)")
    assert_equal(c["peak_label"], "Q4",  "KPI: peak_label = label at max")

    # Bug 5: delta suppressed for pie/donut
    result_pie = AnalysisResult(
        mode="direct_data",
        spec=VisualizationSpec(
            chart_type=ChartType.PIE,
            series=[ChartSeries(name="Market Cap",
                                x=["Apple","Google","Amazon"], y=[394.0,282.0,513.0])]
        )
    )
    assert_true(not _delta_meaningful(result_pie), "KPI: delta suppressed for pie chart")
    pie_cands = _compute_candidates(result_pie)
    assert_true(len(pie_cands) > 0, "KPI: pie returns candidates")
    assert_true(pie_cands[0]["delta"] is None, "KPI: pie candidate has delta=None")

    result_donut = AnalysisResult(
        mode="direct_data",
        spec=VisualizationSpec(chart_type=ChartType.DONUT,
                               series=[ChartSeries(name="s", x=["A","B"], y=[50.0,50.0])])
    )
    assert_true(not _delta_meaningful(result_donut), "KPI: delta suppressed for donut chart")

    # Bug 6: unit suffix detection
    result_billions = AnalysisResult(
        mode="direct_data",
        insight="Amazon leads with $513B revenue",
        spec=VisualizationSpec(chart_type=ChartType.BAR,
                               series=[ChartSeries(name="Revenue", x=["Apple","Amazon"], y=[394.0,513.0])])
    )
    suffix = _detect_unit_suffix(result_billions)
    assert_equal(suffix, "B", "KPI: unit suffix 'B' detected from insight")

    # None handling
    result_nan = AnalysisResult(
        mode="direct_data",
        spec=VisualizationSpec(chart_type=ChartType.BAR,
                               series=[ChartSeries(name="Sales", x=["A","B","C"], y=[100.0,None,200.0])])
    )
    cands = _compute_candidates(result_nan)
    assert_true(len(cands) >= 1, "KPI: handles None values in series")
    assert_equal(cands[0]["count"], 2,     "KPI: count excludes None values")
    assert_equal(cands[0]["total"], 300.0, "KPI: total excludes None (100+200=300)")

    # Sunburst returns nothing
    result_sb = AnalysisResult(
        mode="knowledge_map",
        spec=VisualizationSpec(chart_type=ChartType.SUNBURST,
                               series=[ChartSeries(name="ML",
                                   labels=["Root","A","B"], parents=["","Root","Root"], values=[0,50,50])])
    )
    assert_equal(_compute_candidates(result_sb), [], "KPI: sunburst returns no candidates")

    result_stats = AnalysisResult(
        mode="file_analysis",
        spec=VisualizationSpec(chart_type=ChartType.BAR,
                               series=[ChartSeries(name="s", x=["a"], y=[1.0])]),
        stats={"rows": 15006, "columns": 22}
    )
    cands2 = _compute_candidates(result_stats)
    assert_true(any("extra_stats" in c for c in cands2), "KPI: stats dict included in candidates")


# ── 4. PLOTLY FACTORY ─────────────────────────────────────────────────────────

def test_plotly_factory():
    section("4. Plotly Factory — All 14 chart types render without crash")
    try:
        import plotly.graph_objects as go
    except ImportError:
        skip("Plotly factory tests", "plotly not installed"); return

    from backend.visualizations.plotly_factory import build
    from backend.models import VisualizationSpec, ChartSeries, ChartType

    std  = [ChartSeries(name="S", x=["A","B","C","D"], y=[10,25,18,32])]
    pie  = [ChartSeries(name="S", x=["A","B","C"],    y=[30,50,20])]
    hier = [ChartSeries(name="Root",
                labels= ["Root","Cat A","Sub A1","Sub A2","Cat B","Sub B1"],
                parents=["",    "Root", "Cat A", "Cat A", "Root", "Cat B"],
                values= [0,60,30,30,40,40])]
    scat = [ChartSeries(name="S", x=["1","2","3","4"], y=[1.1,2.2,3.3,4.4])]

    for ct, series, name in [
        (ChartType.BAR,            std,  "bar"),
        (ChartType.HORIZONTAL_BAR, std,  "horizontal_bar"),
        (ChartType.LINE,           std,  "line"),
        (ChartType.AREA,           std,  "area"),
        (ChartType.PIE,            pie,  "pie"),
        (ChartType.DONUT,          pie,  "donut"),
        (ChartType.SCATTER,        scat, "scatter"),
        (ChartType.HISTOGRAM,      std,  "histogram"),
        (ChartType.BOX,            std,  "box"),
        (ChartType.RADAR,          std,  "radar"),
        (ChartType.FUNNEL,         std,  "funnel"),
        (ChartType.WATERFALL,      std,  "waterfall"),
        (ChartType.SUNBURST,       hier, "sunburst"),
        (ChartType.TREEMAP,        hier, "treemap"),
    ]:
        try:
            fig = build(VisualizationSpec(chart_type=ct, title=f"Test {name}", series=series))
            assert_true(isinstance(fig, go.Figure), f"Factory: {name} returns go.Figure")
        except Exception as e:
            fail(f"Factory: {name} renders without crash", str(e))

    try:
        fig = build(VisualizationSpec(chart_type=ChartType.BAR,
                                      series=[ChartSeries(name="s", x=[], y=[])]))
        assert_true(isinstance(fig, go.Figure), "Factory: empty series returns figure (not crash)")
    except Exception as e:
        fail("Factory: empty series handled gracefully", str(e))

    try:
        fig = build(VisualizationSpec(chart_type=ChartType.SUNBURST, series=hier))
        h = fig.layout.height
        assert_true(h is not None and h >= 400, f"Factory: sunburst has explicit height (got {h})")
    except Exception as e:
        fail("Factory: sunburst has explicit height", str(e))


# ── 5. LLM CLIENT ─────────────────────────────────────────────────────────────

def test_llm_client():
    section("5. LLM Client — JSON extraction from messy responses")
    from backend.llm_client import extract_json

    assert_equal(extract_json('{"mode": "direct_data", "confidence": 0.9}')["mode"],
                 "direct_data", "extract_json: direct JSON object")
    assert_equal(extract_json('```json\n{"chart_type": "bar"}\n```')["chart_type"],
                 "bar", "extract_json: markdown json fence")
    assert_equal(extract_json('```\n{"chart_type": "pie"}\n```')["chart_type"],
                 "pie", "extract_json: plain ``` fence")
    assert_equal(extract_json('Sure! Here:\n{"mode": "knowledge_map"}\nThanks.')["mode"],
                 "knowledge_map", "extract_json: JSON buried in prose")

    r = extract_json('[{"label": "Revenue", "value": 100}]')
    assert_true(isinstance(r, list) and r[0]["label"] == "Revenue", "extract_json: JSON array")

    assert_raises(ValueError, lambda: extract_json("plain text no JSON"),
                  "extract_json: raises ValueError on no JSON")

    r2 = extract_json('{"series": [{"x": ["A","B"], "y": [1, 2]}]}')
    assert_true("series" in r2, "extract_json: nested JSON with arrays")


# ── 6. SANDBOX ────────────────────────────────────────────────────────────────

def test_sandbox():
    section("6. Sandbox — Code execution (subprocess fallback)")
    from backend.project_mcp.sandbox_client import SandboxClient, _indent

    assert_true(_indent("x = 1\ny = 2").startswith("    x"), "_indent: adds 4-space indent")

    client = SandboxClient()
    client._docker_available = False  # force subprocess for test isolation

    code = """
import json
output = {
    "chart_type": "bar", "title": "Test", "x_label": "X", "y_label": "Y",
    "insight": "test insight", "stats": {"rows": 5}, "cleaning_steps": ["step 1"],
    "series": [{"name": "S", "x": ["A", "B"], "y": [10.0, 20.0]}]
}
"""
    result = client.execute(code)
    assert_true(result.success,                           "Sandbox: valid script succeeds")
    assert_true(result.output_json is not None,           "Sandbox: output_json is parsed")
    assert_equal(result.output_json.get("chart_type"), "bar", "Sandbox: chart_type in output")
    assert_equal(result.output_json["series"][0]["y"], [10.0, 20.0], "Sandbox: series data preserved")

    bad = client.execute("x = 1 / 0")
    assert_true(not bad.success,        "Sandbox: failing script returns success=False")
    assert_true(len(bad.stderr) > 0,    "Sandbox: stderr captured on failure")

    no_out = client.execute("x = 42  # forgot to assign output")
    assert_true(not no_out.success,     "Sandbox: missing 'output' var returns failure")
    assert_true(hasattr(client, "_docker_available"), "Sandbox: client initialized correctly")

    # FIX Bug 4: SYSLENS_FILE env var injected in subprocess mode
    code_env = """
import os, json
file_path = os.environ.get('SYSLENS_FILE', '')
output = {
    "chart_type": "bar", "title": "T", "x_label": "", "y_label": "",
    "insight": "ok", "stats": {}, "cleaning_steps": [],
    "series": [{"name": "s", "x": ["found"],
                "y": [1.0 if file_path and __import__('os').path.exists(file_path) else 0.0]}]
}
"""
    env_result = client.execute(code_env, file_bytes=b"col1,col2\n1,2\n", filename="test.csv")
    assert_true(env_result.success, "Sandbox: SYSLENS_FILE script runs successfully")
    if env_result.output_json:
        assert_equal(env_result.output_json["series"][0]["y"][0], 1.0,
                     "Sandbox: SYSLENS_FILE points to existing file")


# ── 7. SESSION MEMORY ─────────────────────────────────────────────────────────

def test_session_memory():
    section("7. Session Memory — Conversation history")
    from backend.memory.session import SessionStore

    store = SessionStore()
    sess  = store.get("test_session_1")

    sess.add_turn("user",      "Hello",     mode="direct_data")
    sess.add_turn("assistant", "Chart!",    mode="direct_data")
    sess.add_turn("user",      "Follow up", mode="followup")

    ctx = sess.get_context()
    assert_equal(len(ctx.turns), 3,               "Memory: stores 3 turns")
    assert_equal(ctx.turns[0].role,    "user",    "Memory: first turn is user")
    assert_equal(ctx.turns[0].content, "Hello",   "Memory: content preserved")
    assert_equal(ctx.turns[0].mode, "direct_data","Memory: mode preserved")

    msgs = ctx.recent_messages(2)
    assert_equal(len(msgs), 2,                    "Memory: recent_messages(2) returns 2")
    assert_equal(msgs[0]["role"], "assistant",     "Memory: most recent message order")

    for i in range(50):
        sess.add_turn("user", f"msg {i}")
    ctx2 = sess.get_context()
    assert_true(len(ctx2.turns) <= 40, "Memory: rolling window caps turn count")

    sess.clear()
    ctx3 = sess.get_context()
    assert_equal(len(ctx3.turns), 0,       "Memory: clear() empties turns")
    assert_true(ctx3.last_result is None,  "Memory: clear() removes last_result")

    s1 = store.get("user_a"); s2 = store.get("user_b")
    s1.add_turn("user", "msg from A")
    assert_equal(len(store.get("user_b").get_context().turns), 0,
                 "Memory: sessions are independent")


# ── 8. INTEGRATION ────────────────────────────────────────────────────────────

def test_integration():
    section("8. Integration — End-to-end flow (mocked LLM calls)")
    from backend.engine import SyslensEngine
    from backend.models import AnalysisRequest, AgentMode, ChartType
    from backend.memory.session import clear_session, get_session
    import backend.project_agents.analyst_agent   as _aa
    import backend.project_agents.knowledge_agent as _ka

    MOCK_BAR = json.dumps({
        "chart_type": "bar", "title": "Tech Market Cap",
        "x_label": "Company", "y_label": "Billion USD",
        "insight": "Amazon leads with $513B", "stats": {"count": 4},
        "series": [{"name": "Market Cap",
                    "x": ["Apple","Google","Amazon","Meta"],
                    "y": [394,282,513,116]}]
    })
    MOCK_PIE_RESPONSE = json.dumps({
        "chart_type": "pie", "title": "Revenue Distribution",
        "x_label": "", "y_label": "",
        "insight": "Amazon leads with 40% share.", "stats": {},
        "series": [{"name": "Revenue",
                    "x": ["Apple","Google","Amazon","Meta"],
                    "y": [394,282,513,116]}]
    })
    # Labels at TOP LEVEL — this is what knowledge_agent._parse() reads via data.get("labels")
    MOCK_KNOWLEDGE_RESPONSE = json.dumps({
        "chart_type": "sunburst", "title": "Machine Learning",
        "x_label": "", "y_label": "",
        "insight": "ML is a subfield of AI with three main paradigms.",
        "stats": {},
        "labels":  ["Machine Learning","Supervised","Unsupervised","Reinforcement"],
        "parents": ["","Machine Learning","Machine Learning","Machine Learning"],
        "values":  [0, 40, 35, 25],
        "text":    ["Root","Labeled data","Unlabeled data","Reward-based"]
    })
    MOCK_KPI = json.dumps([
        {"label": "Total Market Cap", "value": 1305.0, "formatted": "$1.31T", "color": "cyan"}
    ])

    # ── Test 1: Direct data ────────────────────────────────────────────────────
    clear_session("test_int")
    engine = SyslensEngine()

    _orig_aa = _aa.call_llm
    try:
        _aa.call_llm = lambda *a, **kw: MOCK_BAR
        with patch("backend.llm_client.call_router_llm",
                   return_value='{"mode": "direct_data", "confidence": 0.95}'), \
             patch("backend.llm_client.call_llm", return_value=MOCK_KPI):
            result = engine.analyze(AnalysisRequest(
                text="Apple: $394B, Google: $282B, Amazon: $513B, Meta: $116B",
                session_id="test_int"
            ))
    finally:
        _aa.call_llm = _orig_aa

    assert_equal(result.mode, AgentMode.DIRECT_DATA.value,      "Integration: direct data routed correctly")
    assert_equal(result.spec.chart_type.value, "bar",           "Integration: bar chart returned")
    assert_equal(len(result.spec.series), 1,                    "Integration: one series returned")
    assert_equal(len(result.spec.series[0].y), 4,               "Integration: 4 data points")
    assert_true(bool(result.insight),                           "Integration: insight not empty")
    assert_true(bool(result.generated_code),                    "Integration: generated_code populated")

    # ── Test 2: Follow-up changes chart type ───────────────────────────────────
    _orig_aa2 = _aa.call_llm
    try:
        _aa.call_llm = lambda *a, **kw: MOCK_PIE_RESPONSE
        with patch("backend.llm_client.call_router_llm",
                   return_value='{"mode": "followup", "confidence": 0.99}'), \
             patch("backend.llm_client.call_llm", return_value=MOCK_KPI):
            result2 = engine.analyze(AnalysisRequest(
                text="make that a pie chart",
                session_id="test_int"
            ))
    finally:
        _aa.call_llm = _orig_aa2

    assert_equal(result2.mode, AgentMode.FOLLOWUP.value,        "Integration: follow-up routed correctly")
    assert_equal(result2.spec.chart_type.value, "pie",          "Integration: follow-up changed to pie chart")

    # ── Test 3: Session memory ─────────────────────────────────────────────────
    ctx = get_session("test_int").get_context()
    assert_true(len(ctx.turns) >= 4,        "Integration: turns accumulate across requests")
    assert_true(ctx.last_result is not None, "Integration: last_result stored in session")

    # ── Test 4: Knowledge map -> sunburst ─────────────────────────────────────
    # Direct attribute patching: reliable even with module-level import binding
    clear_session("test_km")
    engine2 = SyslensEngine()

    _orig_ka = _ka.call_llm
    try:
        _ka.call_llm = lambda *a, **kw: MOCK_KNOWLEDGE_RESPONSE
        with patch("backend.llm_client.call_router_llm",
                   return_value='{"mode": "knowledge_map", "confidence": 0.95}'), \
             patch("backend.llm_client.call_llm", return_value=MOCK_KPI):
            result_km = engine2.analyze(AnalysisRequest(
                text="what is machine learning",
                session_id="test_km"
            ))
    finally:
        _ka.call_llm = _orig_ka   # always restore

    assert_equal(result_km.mode, AgentMode.KNOWLEDGE_MAP.value, "Integration: knowledge_map routed correctly")
    assert_equal(result_km.spec.chart_type.value, "sunburst",   "Integration: sunburst for concept question")
    assert_true(result_km.spec.series[0].labels is not None,    "Integration: sunburst has labels")
    assert_equal(len(result_km.spec.series[0].labels), 4,       "Integration: 4 nodes in sunburst")
    assert_true(bool(result_km.generated_code),                 "Integration: knowledge_map generated_code populated")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run_all():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  sYsLens v2 — Full Test Suite{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    for name, fn in [
        ("Models",         test_models),
        ("Router",         test_router),
        ("KPI Builder",    test_kpi_builder),
        ("Plotly Factory", test_plotly_factory),
        ("LLM Client",     test_llm_client),
        ("Sandbox",        test_sandbox),
        ("Session Memory", test_session_memory),
        ("Integration",    test_integration),
    ]:
        try:
            fn()
        except Exception as e:
            import traceback
            fail(f"[{name}] CRASHED", traceback.format_exc())

    total = _pass + _fail + _skip
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  Results: {total} tests total{RESET}")
    print(f"  {GREEN}{BOLD}Passed: {_pass}{RESET}")
    if _fail: print(f"  {RED}{BOLD}Failed: {_fail}{RESET}")
    if _skip: print(f"  {YELLOW}Skipped: {_skip}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    if _fail == 0:
        print(f"{GREEN}{BOLD}  ✓ All tests passed. Ready for demo.{RESET}\n")
    else:
        print(f"{RED}{BOLD}  ✗ {_fail} test(s) failed. Fix before demo.{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    run_all()