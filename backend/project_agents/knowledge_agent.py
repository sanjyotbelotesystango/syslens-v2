"""
project_agents/knowledge_agent.py — Concept-to-hierarchy visualization.

KEY FIXES:
  1. Better prompt — clearer node structure, forces meaningful depth.
  2. Label truncation — long labels caused text overflow in sunburst.
  3. generated_code stored on result — powers the "View Code" UI feature.
  4. Fallback sunburst on any parse failure (no crash).
  5. Non-numeric values default to 1.0, invalid parents fixed to root.
"""

from __future__ import annotations
import json
import logging

from ..models import (
    AgentMode, SessionContext, AnalysisResult,
    VisualizationSpec, ChartSeries, ChartType,
)
from ..llm_client import call_llm, extract_json

logger = logging.getLogger("syslens.knowledge_agent")

# Max characters per node label — prevents overflow in sunburst
_MAX_LABEL_LEN = 25


_SYSTEM_PROMPT = """You are a knowledge mapping agent.
Transform ANY concept, topic, question, or analytical subject into a structured hierarchy.

THIS IS CRITICAL: Return ONLY valid JSON — no prose, no explanation, no markdown.

Return ONLY this JSON structure:
{
  "chart_type": "sunburst",
  "title": "Short Topic Name",
  "insight": "2-sentence summary of the topic (max 80 words)",
  "stats": {},
  "labels":  ["Root", "Category 1", "Sub 1A", "Sub 1B", "Category 2", "Sub 2A"],
  "parents": ["",     "Root",        "Category 1", "Category 1", "Root", "Category 2"],
  "values":  [0,      40,            20,            20,           30,     30],
  "text":    ["",     "brief description", "detail", "detail", "brief description", "detail"]
}

RULES:
- labels[0] = the topic/root node; parents[0] = "" (empty string)
- Every non-root node MUST have parents[i] that exists in labels
- Root value = 0; child values = relative importance 10-100
- Depth 1: 3–5 main categories. Depth 2: 2–3 items per category. Max 25 nodes total.
- Keep each label SHORT (max 3 words). Abbreviate if needed.
- text[i] = one-sentence description of that node (max 12 words)
- labels, parents, values, text MUST be the same length

CHART TYPE SELECTION:
- Use "treemap"  for: X vs Y comparisons, technology comparisons, pros/cons, feature matrices
- Use "sunburst" for: historical timelines, hierarchical concepts, investment frameworks, principles
- Default to "sunburst" when unsure

For COMPANY/INVESTMENT topics: categories = Strengths, Risks, Opportunities, Strategy, Financials
For TECHNICAL COMPARISON (X vs Y): categories = each technology being compared
For HISTORICAL topics: categories = time periods as depth-1 nodes
For CONCEPT topics: categories = main sub-domains"""


_FOLLOWUP_SYSTEM = """You are modifying an existing knowledge map.

Current spec:
{spec}

Update per the user instruction. Return the same JSON structure.
If adding depth: add child nodes under the requested parent.
If changing chart type: update chart_type only."""


class KnowledgeAgent:

    def run(self, text: str, ctx: SessionContext) -> AnalysisResult:
        history  = ctx.recent_messages(4)
        messages = history + [{"role": "user", "content": f"Create a knowledge map for: {text}"}]
        raw      = call_llm(_SYSTEM_PROMPT, messages, max_tokens=2500)
        return self._parse(raw, AgentMode.KNOWLEDGE_MAP, topic=text)

    def run_followup(self, instruction: str, last_result: AnalysisResult, ctx: SessionContext) -> AnalysisResult:
        current_spec = json.dumps(last_result.spec.model_dump(), indent=2)
        system       = _FOLLOWUP_SYSTEM.format(spec=current_spec)
        raw          = call_llm(system, [{"role": "user", "content": instruction}], max_tokens=2500)
        return self._parse(raw, AgentMode.FOLLOWUP, topic=instruction)

    def _parse(self, raw: str, mode: AgentMode, topic: str = "") -> AnalysisResult:
        try:
            data    = extract_json(raw)
            insight = data.pop("insight", "")
            stats   = data.pop("stats", {})
            title   = data.get("title", topic or "Knowledge Map")

            labels  = data.get("labels",  []) or []
            parents = data.get("parents", []) or []
            text    = data.get("text",    []) or []

            # Safe float conversion
            raw_values = data.get("values", []) or []
            values = []
            for v in raw_values:
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    values.append(1.0)

            if len(labels) < 2:
                logger.warning(f"KnowledgeAgent: {len(labels)} labels for '{topic}' — using fallback")
                return self._fallback_result(title or topic, insight, mode)

            n = len(labels)

            # Truncate long labels for clean display
            labels = [str(l)[:_MAX_LABEL_LEN] for l in labels]

            # Pad / trim supporting arrays to exactly n
            parents = (list(parents)[:n] + [""] * n)[:n]
            values  = (list(values)[:n]  + [1.0] * n)[:n]
            text    = (list(text)[:n]    + [""] * n)[:n]

            # Ensure root has empty parent and value=0 (remainder mode computes it)
            parents[0] = ""
            values[0]  = 0.0  # root value must be 0 with branchvalues="remainder"

            # Validate parents — fix orphaned nodes
            labels_set = set(labels)
            for i in range(1, n):
                if parents[i] not in labels_set and parents[i] != "":
                    logger.debug(f"KnowledgeAgent: invalid parent '{parents[i]}' → fixed to root")
                    parents[i] = labels[0]

            try:
                chart_type = ChartType(data.get("chart_type", "sunburst"))
            except ValueError:
                chart_type = ChartType.SUNBURST

            if chart_type not in (ChartType.SUNBURST, ChartType.TREEMAP):
                chart_type = ChartType.SUNBURST

            spec = VisualizationSpec(
                chart_type=chart_type,
                title=title,
                series=[ChartSeries(
                    name=title,
                    labels=labels,
                    parents=parents,
                    values=values,
                    text=text,
                )],
            )

            generated_code = _build_knowledge_code(labels, parents, values, text, title, insight)

            return AnalysisResult(
                mode=mode.value,
                spec=spec,
                insight=insight,
                stats=stats,
                generated_code=generated_code,
            )

        except Exception as exc:
            logger.warning(f"KnowledgeAgent._parse failed: {type(exc).__name__}: {exc} — using fallback")
            return self._fallback_result(topic or "Knowledge Map", "", mode)

    def _fallback_result(self, topic: str, insight: str, mode: AgentMode) -> AnalysisResult:
        """Last-resort fallback: retry LLM with a simpler prompt focused only on the topic."""
        try:
            simple_prompt = (
                f"Create a simple knowledge map for: {topic}\n\n"
                "Return JSON with labels, parents, values, text arrays. "
                "Root node first with parent=''. 4-8 nodes total."
            )
            raw  = call_llm(_SYSTEM_PROMPT, [{"role": "user", "content": simple_prompt}], max_tokens=1000)
            data = extract_json(raw)

            labels  = data.get("labels",  []) or []
            parents = data.get("parents", []) or []
            text    = data.get("text",    []) or []
            raw_values = data.get("values", []) or []
            values = []
            for v in raw_values:
                try:    values.append(float(v))
                except: values.append(1.0)

            if len(labels) >= 2:
                n = len(labels)
                labels  = [str(l)[:_MAX_LABEL_LEN] for l in labels]
                parents = (list(parents)[:n] + [""] * n)[:n]
                values  = (list(values)[:n]  + [1.0] * n)[:n]
                text    = (list(text)[:n]    + [""] * n)[:n]
                parents[0] = ""
                values[0]  = 0.0
                labels_set = set(labels)
                for i in range(1, n):
                    if parents[i] not in labels_set:
                        parents[i] = labels[0]

                spec = VisualizationSpec(
                    chart_type=ChartType.SUNBURST,
                    title=data.get("title", topic),
                    series=[ChartSeries(
                        name=topic, labels=labels, parents=parents,
                        values=values, text=text,
                    )],
                )
                return AnalysisResult(
                    mode=mode.value, spec=spec,
                    insight=data.get("insight", insight) or f"Overview of {topic}.",
                    generated_code=_build_knowledge_code(labels, parents, values, text, topic, insight),
                )
        except Exception:
            pass

        # If LLM retry also fails, raise — don't show a generic wrong chart
        raise ValueError(
            f"Could not generate a knowledge map for '{topic[:60]}'. "
            "Try rephrasing or being more specific."
        )


def _build_knowledge_code(labels, parents, values, text, title, insight):
    lines = [
        "# sYsLens — Knowledge Map Spec",
        "# " + "─" * 50,
        "",
        "import plotly.graph_objects as go",
        "",
        f"title = '{title}'",
        "",
        f"labels  = {labels}",
        f"parents = {parents}",
        f"values  = {values}",
        "",
        "fig = go.Figure(go.Sunburst(",
        "    labels=labels, parents=parents, values=values,",
        "    branchvalues='remainder',  # root=0, children carry their own weight",
        "))",
        f"fig.update_layout(title='{title}')",
        "fig.show()",
    ]
    if insight:
        lines.insert(2, f"# Insight: {insight}")
    return "\n".join(lines)