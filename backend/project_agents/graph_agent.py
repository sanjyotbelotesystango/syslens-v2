"""
project_agents/graph_agent.py — File analysis agent (CSV / Excel).

KEY FIXES:
  1. generated_code stored on result — powers the "View Code" UI feature.
  2. Better code gen prompt: clearer user-intent understanding, better column
     detection, explicit chart-type selection rules for file data.
  3. Per-item series parsing in _parse() — one bad series doesn't crash all.
"""

from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Callable

from ..models import (
    AgentMode, SessionContext, AnalysisResult,
    VisualizationSpec, ChartSeries, ChartType,
)
from ..llm_client import call_llm, extract_json
from ..project_mcp.sandbox_client import SandboxClient

logger = logging.getLogger("syslens.graph_agent")

_CODE_GEN_SYSTEM = """You are a Python data scientist. Write a complete analysis script.

Dataset info:
{fingerprint}

User request: "{request}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — READ THE FILE (use this exact pattern):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import os, json
import pandas as pd
import numpy as np

_file_path = os.environ.get('SYSLENS_FILE', '/sandbox/{filename}')
ext = os.path.splitext(_file_path)[1].lower()
if ext == '.csv':
    df = pd.read_csv(_file_path)
elif ext in ('.xlsx', '.xlsm'):
    df = pd.read_excel(_file_path, engine='openpyxl')
elif ext == '.xls':
    df = pd.read_excel(_file_path, engine='xlrd')
else:
    df = pd.read_csv(_file_path)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — CLEAN THE DATA:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
df.columns = df.columns.str.strip()
df = df.dropna(how='all').dropna(axis=1, how='all')
df = df.ffill()
# Strip currency/percent symbols from numeric columns
for col in df.select_dtypes(include='object').columns:
    converted = df[col].str.replace(r'[$,%]', '', regex=True).str.strip()
    numeric = pd.to_numeric(converted, errors='coerce')
    if numeric.notna().mean() >= 0.5:
        df[col] = numeric
df = df.fillna(0) if df.select_dtypes(include='number').columns.any() else df.fillna('Unknown')

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — CHART TYPE SELECTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Date/time column present → "line" (sort chronologically, max 80 points)
• Category + numeric, ≤15 categories → "bar"
• Category + numeric, >15 categories → "horizontal_bar" (top 20 by value)
• Proportion/share data → "pie" (max 10 slices, group rest as "Other")
• Two numeric columns → "scatter"
• Single numeric distribution → "histogram"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — OUTPUT (assign to variable named `output`):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
output = {{
    "chart_type": "bar|line|pie|donut|scatter|area|histogram|waterfall|funnel|horizontal_bar",
    "title": "...",
    "x_label": "...",
    "y_label": "...",
    "insight": "key finding in max 80 words",
    "stats": {{"rows": int(df.shape[0]), "columns": int(df.shape[1])}},
    "cleaning_steps": ["step 1", "step 2"],
    "series": [{{"name": "...", "x": list_of_labels, "y": list_of_numbers}}]
}}

Rules:
- All y values must be Python float/int (use float(v) to ensure)
- x labels must be strings
- bar/pie: max 20 items
- line: max 80 points, sorted by date/time

Available: pandas, numpy, openpyxl, xlrd
Return ONLY Python code — no markdown, no explanation."""


class GraphAgent:
    def __init__(self):
        self._sandbox = SandboxClient()

    def run(
        self,
        text: str,
        file_bytes: bytes,
        filename: str,
        fingerprint: dict,
        ctx: SessionContext,
        progress_cb: Callable[[str], None] | None = None,
    ) -> AnalysisResult:

        def log(msg: str):
            logger.info(msg)
            if progress_cb:
                progress_cb(msg)

        # Stage 1 — Generate code
        log(f"GraphAgent: generating code for '{filename}'")
        code = self._generate_code(
            request=text or "Analyze this dataset. Show the most insightful chart.",
            filename=filename,
            fingerprint=fingerprint,
            ctx=ctx,
        )
        log(f"GraphAgent: generated {len(code.splitlines())} lines")

        # Stage 2 — Execute
        log("GraphAgent: executing in sandbox")
        result = self._sandbox.execute(code, file_bytes=file_bytes, filename=filename, progress_cb=log)

        if not result.success:
            logger.error(f"GraphAgent: execution failed, retrying\n{result.stderr[:400]}")
            code2 = self._fix_code(code, result.stderr, filename, fingerprint, text)
            result = self._sandbox.execute(code2, file_bytes=file_bytes, filename=filename, progress_cb=log)

            if not result.success:
                raise RuntimeError(
                    f"File analysis failed after retry.\n"
                    f"Error: {result.stderr[:500]}"
                )
            code = code2  # use the fixed code for display

        # Stage 3 — Parse output
        log("GraphAgent: parsing output")
        return self._parse(result.output_json or {}, generated_code=code, filename=filename)

    def _generate_code(self, request: str, filename: str, fingerprint: dict, ctx: SessionContext) -> str:
        system = _CODE_GEN_SYSTEM.format(
            fingerprint=json.dumps(fingerprint, indent=2, default=str),
            request=request,
            filename=filename,
        )
        messages = ctx.recent_messages(2) + [
            {"role": "user", "content": f"Generate code to analyze '{filename}'. Request: {request}"}
        ]
        code = call_llm(system, messages, max_tokens=3000, temperature=0.05)
        return _strip_fences(code)

    def _fix_code(self, failed_code: str, error: str, filename: str, fingerprint: dict, request: str) -> str:
        fix_prompt = (
            f"The following code failed:\n\nERROR:\n{error[:600]}\n\n"
            f"FAILED CODE:\n{failed_code[:2000]}\n\n"
            f"Fix it. Use os.environ.get('SYSLENS_FILE', '/sandbox/{filename}') to read the file.\n"
            f"Check column names carefully against the fingerprint below.\n"
            f"Fingerprint:\n{json.dumps(fingerprint, indent=2, default=str)[:1000]}\n"
            f"Return only working Python code."
        )
        system = _CODE_GEN_SYSTEM.format(
            fingerprint=json.dumps(fingerprint, indent=2, default=str),
            request=request,
            filename=filename,
        )
        code = call_llm(system, [{"role": "user", "content": fix_prompt}], max_tokens=3000, temperature=0.05)
        return _strip_fences(code)

    def _parse(self, data: dict, generated_code: str = "", filename: str = "") -> AnalysisResult:
        if not data:
            raise ValueError("Sandbox returned empty output.")

        insight  = data.pop("insight", "")
        stats    = data.pop("stats", {})
        cleaning = data.pop("cleaning_steps", [])

        raw_series = data.pop("series", [])
        if not raw_series:
            raise ValueError("No chart series in sandbox output.")

        # Per-item parsing — coerce types before building ChartSeries
        series = []
        for s in raw_series:
            try:
                # Coerce x to list of strings — Pandas may output int64/Timestamp
                if "x" in s and isinstance(s["x"], list):
                    s["x"] = [str(v) for v in s["x"]]
                # Coerce y to list of floats — filter out non-numeric values
                if "y" in s and isinstance(s["y"], list):
                    clean_y = []
                    for v in s["y"]:
                        try:
                            f = float(v)
                            import math as _math
                            clean_y.append(None if (_math.isnan(f) or _math.isinf(f)) else f)
                        except (TypeError, ValueError):
                            clean_y.append(None)
                    s["y"] = clean_y
                cs = ChartSeries(**s)
                # Only keep series with at least one real number
                real_nums = [v for v in (cs.y or []) if v is not None]
                if real_nums:
                    series.append(cs)
                else:
                    logger.warning(f"GraphAgent: dropping all-null series '{cs.name}'")
            except Exception as e:
                logger.warning(f"GraphAgent: skipping malformed series: {e}")
                continue

        if not series:
            raise ValueError("Could not parse any valid chart series from the analysis output.")

        try:
            chart_type = ChartType(data.get("chart_type", "bar"))
        except ValueError:
            chart_type = ChartType.BAR

        spec = VisualizationSpec(
            chart_type=chart_type,
            title=data.get("title", f"Analysis: {filename}"),
            x_label=data.get("x_label", ""),
            y_label=data.get("y_label", ""),
            series=series,
        )

        return AnalysisResult(
            mode=AgentMode.FILE_ANALYSIS.value,
            spec=spec,
            insight=insight,
            cleaning_steps=cleaning,
            stats=stats,
            generated_code=generated_code,
        )


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:python)?\s*([\s\S]+?)```", text)
    return match.group(1).strip() if match else text