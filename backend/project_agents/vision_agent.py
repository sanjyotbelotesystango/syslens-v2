"""
project_agents/vision_agent.py — Extract data from chart/table images.

KEY FIXES:
  1. generated_code stored on result — powers the "View Code" UI feature.
  2. Per-item series parsing — one bad dict skips, doesn't crash all.
  3. User-friendly error messages.
"""

from __future__ import annotations
import logging

from ..models import (
    AgentMode, SessionContext, AnalysisResult,
    VisualizationSpec, ChartSeries, ChartType,
)
from ..llm_client import call_vision_llm, extract_json

logger = logging.getLogger("syslens.vision_agent")


_SYSTEM_PROMPT = """You are a chart and data extraction agent.
Look at the image carefully. Determine what type of content it contains.

STEP 1 — Identify the content:
• Chart/graph (bar, line, pie, scatter, etc.) → extract ALL data points
• Table/spreadsheet → convert to the most appropriate chart type
• Screenshot with numbers/stats → extract the key metrics as a bar chart
• Text with data mentions → extract numeric values as a chart
• Photo with no data → return a simple summary bar with count=1

STEP 2 — Select chart type based on what you see:
• Bar chart in image → "bar" or "horizontal_bar"
• Line/trend chart → "line"
• Pie/donut in image → "donut"
• Scatter plot → "scatter"
• Table with categories and values → "bar" or "horizontal_bar"
• Mixed/unclear → "bar" (safest default)

STEP 3 — Extract data precisely:
• Read every visible number, label, axis tick, and legend entry
• Estimate values from axis scale if exact number not shown
• Multiple legend entries → multiple series with same x-axis labels

Return ONLY this JSON (no prose, no markdown, no explanation):
{
  "chart_type": "bar|horizontal_bar|line|area|pie|donut|scatter",
  "title": "descriptive title based on what you see",
  "x_label": "x axis label or category name",
  "y_label": "y axis label or value name",
  "insight": "1-2 sentence description of what the chart shows (max 60 words)",
  "stats": {"data_points": N},
  "series": [
    { "name": "series or legend name", "x": ["Label A", "Label B"], "y": [10.5, 25.0] }
  ]
}

IMPORTANT:
- y values must be real numbers — never null, never strings
- len(x) must equal len(y) exactly
- If you cannot read exact values, estimate from visual proportions
- Always return at least 1 series with at least 1 data point"""


class VisionAgent:

    def run(self, text: str, image_b64: str, media_type: str, ctx: SessionContext) -> AnalysisResult:
        prompt = text or "Extract all data from this chart or table and recreate it exactly."
        raw    = call_vision_llm(_SYSTEM_PROMPT, prompt, image_b64, media_type, max_tokens=2500)
        return self._parse(raw)

    def _parse(self, raw: str) -> AnalysisResult:
        data    = extract_json(raw)
        insight = data.pop("insight", "")
        stats   = data.pop("stats", {})

        raw_series = data.pop("series", [])
        if not raw_series:
            raise ValueError(
                "No data could be extracted from the image. "
                "Please ensure the image contains a chart or table with visible numeric values."
            )

        series = []
        for s in raw_series:
            try:
                series.append(ChartSeries(**s))
            except Exception as e:
                logger.warning(f"VisionAgent: skipping malformed series: {e}")
                continue

        if not series:
            raise ValueError(
                "The image data could not be parsed. "
                "Try uploading a clearer image or describing the data manually."
            )

        try:
            chart_type = ChartType(data.get("chart_type", "bar"))
        except ValueError:
            chart_type = ChartType.BAR

        spec = VisualizationSpec(
            chart_type=chart_type,
            title=data.get("title", "Extracted from Image"),
            x_label=data.get("x_label", ""),
            y_label=data.get("y_label", ""),
            series=series,
        )

        # Build generated_code showing the extracted data
        code_lines = [
            "# sYsLens — Vision Extraction Result",
            "# " + "─" * 50,
            "# Data extracted from uploaded image",
            "",
            "import plotly.graph_objects as go",
            "",
            f"chart_type = '{spec.chart_type.value}'",
            f"title      = '{spec.title}'",
            "",
        ]
        for i, s in enumerate(series):
            vname = f"series_{i}" if len(series) > 1 else "data"
            code_lines.append(f"{vname} = {{")
            code_lines.append(f'    "name": "{s.name}",')
            x_repr = repr(s.x[:20]) + (" # ..." if len(s.x) > 20 else "")
            y_repr = repr(s.y[:20]) + (" # ..." if len(s.y) > 20 else "")
            code_lines.append(f'    "x": {x_repr},')
            code_lines.append(f'    "y": {y_repr},')
            code_lines.append("}")
            code_lines.append("")
        if insight:
            code_lines.append(f"# Insight: {insight}")

        return AnalysisResult(
            mode=AgentMode.VISION.value,
            spec=spec,
            insight=insight,
            stats=stats,
            generated_code="\n".join(code_lines),
        )