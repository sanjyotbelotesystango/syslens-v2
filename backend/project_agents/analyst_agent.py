"""
project_agents/analyst_agent.py

INTENT-AWARE data extraction and chart generation.

The user's cognitive intent determines the chart type.
The LLM is given one rule per intent — no ambiguity.
"""

from __future__ import annotations
import json
import logging

from ..models import (
    AgentMode, SessionContext, AnalysisResult,
    VisualizationSpec, ChartSeries, ChartType,
)
from ..llm_client import call_llm, extract_json

logger = logging.getLogger("syslens.analyst_agent")


_SYSTEM_PROMPT = """You are a data visualization agent with one job:
detect the user's intent, supply or extract the right data, pick the right chart.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — DETECT INTENT (read the query carefully)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RANK    "Top N X", "Richest countries", "Best frameworks", "Biggest companies"
        → chart: horizontal_bar (sorted, largest at top)

TREND   "X growth 2019 to 2024", "GDP rate over 10 years", "subscriber change"
        → chart: line (x = years/dates, one point per period)

SHARE   "market share", "energy mix", "breakdown by", "% of", "distribution"
        → chart: donut (proportions always sum to ~100%)

COMPARE "React vs Vue vs Angular", "AWS vs Azure vs GCP", "A vs B vs C"
        → chart: radar  (each technology = one series, axes = key attributes)
        → OR: bar       (if only 2 things being compared on single metric)

MIXED_RETURNS "commodities returns", "+134% ... -36%", "gains and losses"
        → chart: bar    (green for positive, red for negative automatically)

TIMELINE "History of the internet", "Timeline of AI", "History of X", "Evolution of Y"
        → chart: horizontal_bar
        → x = time period labels: use specific decades or years, NOT vague labels
            Good:  ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s"]
            Good:  ["1969", "1983", "1991", "2004", "2007", "2015", "2023"]
            Bad:   ["Early", "Middle", "Recent"]
        → y = significance score (1–10 integer) — how important was that period/event
        → series name = topic name (e.g. "Internet Milestones")
        → insight = list the 3 most important actual milestones (e.g. "ARPANET 1969, WWW 1991, Social Media 2004")
        → Use REAL events from your training knowledge — never invent milestone names
        → Sort chronologically (earliest x first)

INLINE  "Apple: $394B, Google: $282B", "Q1: 120, Q2: 135"
        → chart: bar or line based on whether x-axis is time or categories

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — GET THE DATA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Priority order:
1. EXPLICIT numbers in the user message → always use these first
2. EXTRACTED from bullet points/tables → parse every "Label: value" pattern
3. TRAINING KNOWLEDGE for well-known topics → supply real data from your knowledge
   Add "[Estimated]" prefix to insight when using training data.

For COMPARE intent (X vs Y vs Z — "vs", "versus", "compare"):
   - Choose 5–7 meaningful dimensions SPECIFIC to what is being compared.
     For tech frameworks: Performance, Learning Curve, Ecosystem, Community,
                          Job Market, Scalability, Bundle Size
     For cloud providers: Pricing, Global Reach, Services Breadth, ML/AI Tools,
                          Documentation, Enterprise Support, Market Share
     For programming languages: Speed, Learning Curve, Ecosystem, Job Demand,
                                 Community, Versatility, Type Safety
     For anything else: infer the most relevant comparison dimensions yourself.
   - One series per item being compared (e.g. one series per framework/product)
   - All series share IDENTICAL x labels (the dimension names)
   - Score each item on each dimension: 0 = worst, 100 = best
   - Use your knowledge to make the scores accurate and differentiated —
     scores should reflect real relative strengths, not all be similar numbers
   - DO NOT copy example scores — generate based on the actual items in the query

For TIMELINE intent (History of X):
   - Create milestone entries as horizontal_bar
   - x = ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s"] or specific years
   - y = significance score (1–10) for each period
   - name = "Key Milestones"
   - insight should describe the actual milestones

For RANK intent:
   - Use accurate ranked data from your training knowledge
   - Sort descending (highest value first in the list)
   - Include at least 7 items, max 15
   - All values must be real estimates — never invent or repeat placeholder numbers

For TREND intent:
   - Use actual yearly/quarterly values from training knowledge
   - One x per year: ["2019", "2020", "2021", "2022", "2023", "2024"]
   - Sort chronologically

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — RETURN JSON (no prose, no markdown)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "chart_type": "horizontal_bar | line | donut | radar | bar | area | scatter | funnel | waterfall",
  "title": "Specific descriptive title based on query",
  "x_label": "axis label",
  "y_label": "axis label with units",
  "insight": "The most important finding in 1-2 sentences. [Estimated] if training data used.",
  "stats": {},
  "series": [
    { "name": "Series A", "x": ["Label 1", "Label 2"], "y": [42.0, 28.5] },
    { "name": "Series B", "x": ["Label 1", "Label 2"], "y": [35.0, 40.0] }
  ]
}

HARD CONSTRAINTS:
• Every y value = finite number (float/int). Never null, never string, never NaN.
• len(x) == len(y) for EVERY series — mismatch causes crash
• radar: every series has SAME x labels (the attributes), different y values
• donut/pie: ONE series, all y > 0, values represent proportions
• line: sort x chronologically; max 80 points
• horizontal_bar: max 15 items; sort by y descending
• bar: max 12 items"""


_FOLLOWUP_SYSTEM = """You are modifying an existing visualization.

Current spec:
{spec}

Apply ONLY the change the user requests. Keep all data values identical.

Chart type mapping:
  "line" / "trend" / "over time"  → "line"
  "bar" / "column" / "compare"    → "bar"
  "pie" / "donut" / "share"       → "donut"
  "horizontal"                    → "horizontal_bar"
  "area" / "filled"               → "area"
  "scatter" / "dots"              → "scatter"
  "radar" / "spider" / "web"      → "radar"

Return ONLY valid JSON in the same format."""


class AnalystAgent:

    def run(self, text: str, ctx: SessionContext) -> AnalysisResult:
        history  = ctx.recent_messages(6)
        messages = history + [{"role": "user", "content": f"Visualize this:\n\n{text}"}]
        raw      = call_llm(_SYSTEM_PROMPT, messages, max_tokens=3000)
        return self._parse(raw, AgentMode.DIRECT_DATA, original_text=text)

    def run_followup(self, instruction: str, last_result: AnalysisResult, ctx: SessionContext) -> AnalysisResult:
        current_spec = json.dumps(last_result.spec.model_dump() if last_result.spec else {}, indent=2)
        system       = _FOLLOWUP_SYSTEM.format(spec=current_spec)
        raw          = call_llm(system, [{"role": "user", "content": instruction}], max_tokens=3000)
        return self._parse(raw, AgentMode.FOLLOWUP, original_text=instruction)

    def _parse(self, raw: str, mode: AgentMode, original_text: str = "") -> AnalysisResult:
        data    = extract_json(raw)
        insight = data.pop("insight", "")
        stats   = data.pop("stats", {})
        cleaning = data.pop("cleaning_steps", [])

        raw_series = data.pop("series", [])
        if not raw_series:
            raise ValueError(
                "No chart data returned. Try pasting your data directly "
                "(e.g. 'Apple: $394B, Google: $282B') or uploading a file."
            )

        series = []
        for s in raw_series:
            try:
                cs = ChartSeries(**s)
                nums = [v for v in (cs.y or []) if v is not None]
                if len(nums) == 0:
                    logger.warning(f"AnalystAgent: dropping all-null series '{cs.name}'")
                    continue
                series.append(cs)
            except Exception as e:
                logger.warning(f"AnalystAgent: skipping malformed series: {e}")
                continue

        if not series:
            raise ValueError(
                "Could not parse chart data. "
                "Please check that your input contains numeric values."
            )

        try:
            chart_type = ChartType(data.get("chart_type", "bar"))
        except ValueError:
            chart_type = ChartType.BAR

        spec = VisualizationSpec(
            chart_type=chart_type,
            title=data.get("title", "Analysis"),
            x_label=data.get("x_label", ""),
            y_label=data.get("y_label", ""),
            series=series,
        )

        return AnalysisResult(
            mode=mode.value,
            spec=spec,
            insight=insight,
            cleaning_steps=cleaning,
            stats=stats,
            generated_code=_build_code(spec, insight, original_text),
        )


def _build_code(spec: VisualizationSpec, insight: str, source: str) -> str:
    lines = ["# sYsLens — Visualization Spec", "# " + "─" * 48]
    if source:
        preview = source[:80].replace("\n", " ")
        lines.append(f'# Source: "{preview}{"..." if len(source) > 80 else ""}"')
    lines += ["", "import plotly.graph_objects as go", "",
              f"chart_type = '{spec.chart_type.value}'",
              f"title      = '{spec.title}'", ""]
    for i, s in enumerate(spec.series):
        vname = f"series_{i}" if len(spec.series) > 1 else "data"
        lines += [f"{vname} = {{", f'    "name": "{s.name}",']
        if s.labels:
            lines += [f'    "labels":  {s.labels},',
                      f'    "parents": {s.parents},',
                      f'    "values":  {s.values},']
        else:
            xr = repr(s.x[:20]) + (" # ..." if len(s.x) > 20 else "")
            yr = repr(s.y[:20]) + (" # ..." if len(s.y) > 20 else "")
            lines += [f'    "x": {xr},', f'    "y": {yr},']
        lines += ["}", ""]
    if insight:
        lines.append(f"# Insight: {insight}")
    return "\n".join(lines)