"""
visualizations/kpi_builder.py — Auto-extract KPI metric cards.

BUGS FIXED:
  Bug 5 — Delta suppressed for non-time-series charts (pie/donut/etc).
  Bug 6 — Unit suffix preserved (394B -> $394B not $394.0).
"""

from __future__ import annotations
import json
import math
import re
import logging
from typing import List

from ..models import KPICard, AnalysisResult, ChartType

logger = logging.getLogger("syslens.kpi")


_ALWAYS_TREND = {ChartType.LINE, ChartType.AREA, ChartType.WATERFALL, ChartType.FUNNEL}
_CONDITIONAL_TREND = {ChartType.BAR, ChartType.HORIZONTAL_BAR}
_NEVER_TREND = {
    ChartType.PIE, ChartType.DONUT, ChartType.RADAR,
    ChartType.SCATTER, ChartType.HISTOGRAM, ChartType.BOX,
    ChartType.SUNBURST, ChartType.TREEMAP,
}


def _is_time_series(result: AnalysisResult) -> bool:
    for series in result.spec.series:
        if not series.x:
            continue
        for label in series.x:
            s = str(label).lower().strip()
            if re.match(r'^q[1-4]', s):
                return True
            if re.match(r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', s):
                return True
            if re.match(r'^\d{4}$', s):
                return True
            if re.match(r'^\d{4}[-/]\d{2}', s):
                return True
            if re.match(r'^(h1|h2|fy|fy\d{2,4})', s):
                return True
    return False


def _delta_meaningful(result: AnalysisResult) -> bool:
    ct = result.spec.chart_type
    if ct in _ALWAYS_TREND:
        return True
    if ct in _CONDITIONAL_TREND:
        return _is_time_series(result)
    return False


def _detect_unit_suffix(result: AnalysisResult) -> str:
    haystack = " ".join(filter(None, [
        result.spec.title or "",
        result.insight or "",
        result.spec.x_label or "",
        result.spec.y_label or "",
    ])).lower()

    # Full word matches — singular and plural (e.g. "in billions", "revenue in million")
    if re.search(r'\bbillions?\b', haystack):
        return "B"
    if re.search(r'\bmillions?\b', haystack):
        return "M"
    if re.search(r'\bthousands?\b', haystack):
        return "K"

    # Abbreviation matches in insight/title (e.g. "$513B", "$1.2M", "394B")
    abbrev = re.search(r'\$?\d+\.?\d*([BMKbmk])\b', haystack)
    if abbrev:
        return abbrev.group(1).upper()

    for series in result.spec.series:
        if not series.x:
            continue
        for label in series.x:
            match = re.search(r'\d+\.?\d*([BMKbmk])\b', str(label))
            if match:
                return match.group(1).upper()

    return ""


def _compute_candidates(result: AnalysisResult) -> list[dict]:
    candidates = []

    if result.spec.chart_type in {ChartType.SUNBURST, ChartType.TREEMAP}:
        return []

    include_delta = _delta_meaningful(result)
    unit_suffix   = _detect_unit_suffix(result)

    for s in result.spec.series:
        if not s.y:
            continue
        nums = [v for v in s.y if v is not None and math.isfinite(v)]
        if not nums:
            continue

        total = round(sum(nums), 4)
        avg   = round(total / len(nums), 4)
        mx    = round(max(nums), 4)
        mn    = round(min(nums), 4)

        delta     = None
        delta_pct = None
        if include_delta and len(nums) >= 2 and nums[0] != 0:
            delta     = round(nums[-1] - nums[0], 4)
            delta_pct = round((delta / abs(nums[0])) * 100, 2)

        peak_label = None
        if s.x and len(s.x) == len(s.y):
            try:
                peak_idx   = nums.index(mx)
                peak_label = str(s.x[peak_idx])
            except (ValueError, IndexError):
                pass

        candidates.append({
            "series_name": s.name,
            "count":       len(nums),
            "total":       total,
            "average":     avg,
            "maximum":     mx,
            "minimum":     mn,
            "latest":      nums[-1],
            "first":       nums[0],
            "delta":       delta,
            "delta_pct":   delta_pct,
            "peak_label":  peak_label,
            "unit_suffix": unit_suffix,
        })

    if result.stats:
        candidates.append({"extra_stats": result.stats})

    return candidates


_LABEL_SYSTEM = """You are a KPI card labeling agent.
You receive pre-calculated metrics computed by Python. All numbers are exact.
Your ONLY job: select 2-4 meaningful metrics and format them for display.

STRICT RULES:
1. NEVER change, round, or recalculate any number.
2. If "delta" is null, do NOT include a delta/trend KPI.
3. UNIT SUFFIX — if "unit_suffix" is not empty, append it:
     "B" -> 513.0 becomes "$513B"; "M" -> 1250.0 becomes "$1.25M"
4. For distribution charts (pie/donut): show maximum and count only. No delta.
5. color: green (growth), red (negative), amber (neutral), cyan (default), purple (special).

Return ONLY a JSON array:
[
  {
    "label":       "Total Revenue",
    "value":       1630.0,
    "formatted":   "$1,630B",
    "delta":       null,
    "delta_label": null,
    "prefix":      "$",
    "suffix":      "B",
    "color":       "cyan"
  }
]

If no meaningful KPI, return [].
Return ONLY the JSON array."""


def extract_kpis(result: AnalysisResult) -> List[KPICard]:
    from ..llm_client import call_llm, extract_json

    try:
        candidates = _compute_candidates(result)
    except Exception as e:
        logger.warning(f"KPI computation failed: {e}")
        return []

    if not candidates:
        return []

    context = json.dumps({
        "chart_title": result.spec.title,
        "chart_type":  result.spec.chart_type.value,
        "insight":     (result.insight or "")[:200],
        "candidates":  candidates,
    }, default=str)

    try:
        raw = call_llm(
            _LABEL_SYSTEM,
            [{"role": "user", "content": f"Label these pre-computed metrics:\n{context}"}],
            max_tokens=600,
            temperature=0.0,
        )
        data = extract_json(raw)
        if not isinstance(data, list):
            return []
        kpis = []
        for item in data[:4]:
            try:
                kpis.append(KPICard(**item))
            except Exception:
                continue
        logger.info(f"Extracted {len(kpis)} KPIs")
        return kpis
    except Exception as e:
        logger.warning(f"KPI labeling failed: {e}")
        return []