"""
visualizations/plotly_factory.py — Build Plotly figures from VisualizationSpec.
"""

from __future__ import annotations
import math
import plotly.graph_objects as go

from ..models import VisualizationSpec, ChartType, ChartSeries

# ── Palette — carefully spaced hues, vivid but not neon ──────────────────────
# Adjacent colors are always perceptually distinct on dark backgrounds.
# Avoid pure red/green as defaults — those are reserved for semantic meaning.
COLORS = [
    "#38bdf8",   # sky blue      — primary
    "#fb923c",   # warm orange
    "#a78bfa",   # violet
    "#34d399",   # emerald
    "#fbbf24",   # amber
    "#f472b6",   # rose pink
    "#22d3ee",   # cyan
    "#818cf8",   # indigo
    "#e879f9",   # fuchsia
    "#2dd4bf",   # teal
    "#c084fc",   # purple
    "#67e8f9",   # light cyan
]

# Semantic — ONLY used when data sign matters (returns, growth, loss)
_POS  = "#34d399"   # emerald — clearly positive, not garish
_NEG  = "#f87171"   # soft coral-red — clearly negative, not alarming
_NEUT = "#94a3b8"   # slate — zero / neutral

BG        = "#0a0f1a"
BG_PLOT   = "#111827"
TEXT      = "#c8d8e8"
TEXT_DIM  = "#4a6a8a"
GRID      = "rgba(255,255,255,0.05)"
ZEROLINE  = "rgba(255,255,255,0.12)"
FONT_MONO = "Share Tech Mono, Courier New, monospace"
FONT_BODY = "Oxanium, Helvetica, sans-serif"
_MAX_LABEL = 22


def _base_layout(title: str = "") -> dict:
    return dict(
        title=dict(text=title, font=dict(size=15, color=TEXT, family=FONT_BODY), x=0.02, xanchor="left"),
        paper_bgcolor=BG,
        plot_bgcolor=BG_PLOT,
        font=dict(family=FONT_MONO, color=TEXT_DIM, size=11),
        margin=dict(l=55, r=20, t=55, b=55),
        legend=dict(
            bgcolor="rgba(10,15,26,0.85)",
            bordercolor=ZEROLINE, borderwidth=1,
            font=dict(color=TEXT_DIM, size=10),
        ),
        hoverlabel=dict(
            bgcolor="#0d1930", bordercolor=COLORS[0],
            font=dict(family=FONT_BODY, color=TEXT, size=12),
        ),
        colorway=COLORS,
    )


def _xy_layout(x_label: str = "", y_label: str = "") -> dict:
    axis = dict(
        gridcolor=GRID, zerolinecolor=ZEROLINE, zerolinewidth=1,
        tickfont=dict(family=FONT_MONO, color=TEXT_DIM, size=10),
        linecolor=ZEROLINE,
    )
    return dict(
        xaxis=dict(**axis, title=dict(text=x_label, font=dict(color=TEXT_DIM, size=11))),
        yaxis=dict(**axis, title=dict(text=y_label, font=dict(color=TEXT_DIM, size=11)),
                   tickformat=",.2~f"),
    )


def _no_data_fig(title: str, reason: str = "No data available") -> go.Figure:
    fig = go.Figure()
    layout = _base_layout(title)
    layout["height"] = 300
    fig.update_layout(**layout)
    fig.add_annotation(
        text=f'<span style="font-size:22px">📊</span><br>'
             f'<span style="color:{TEXT};font-size:14px">{reason}</span>',
        x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, align="center",
        font=dict(color=TEXT_DIM, size=13, family=FONT_BODY),
    )
    return fig


def _error_fig(title: str, error: str) -> go.Figure:
    fig = go.Figure()
    layout = _base_layout(f"⚠ {title}")
    layout["height"] = 300
    fig.update_layout(**layout)
    fig.add_annotation(
        text=f'<span style="color:#f87171;font-size:13px"><b>Error generating chart</b></span>'
             f'<br><span style="color:{TEXT_DIM};font-size:11px">{str(error)[:180]}</span>',
        x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, align="center",
        font=dict(family=FONT_MONO),
    )
    return fig


def _valid_series(s: ChartSeries) -> bool:
    nums = [v for v in (s.y or []) if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))]
    return len(nums) > 0


def build(spec: VisualizationSpec) -> go.Figure:
    try:
        builders = {
            ChartType.BAR:            _bar,
            ChartType.HORIZONTAL_BAR: _horizontal_bar,
            ChartType.LINE:           _line,
            ChartType.AREA:           _area,
            ChartType.PIE:            _pie,
            ChartType.DONUT:          _donut,
            ChartType.SCATTER:        _scatter,
            ChartType.HISTOGRAM:      _histogram,
            ChartType.BOX:            _box,
            ChartType.RADAR:          _radar,
            ChartType.FUNNEL:         _funnel,
            ChartType.WATERFALL:      _waterfall,
            ChartType.SUNBURST:       _sunburst,
            ChartType.TREEMAP:        _treemap,
        }
        return builders[spec.chart_type](spec)
    except Exception as e:
        return _error_fig(spec.title, str(e))


# ── Chart builders ─────────────────────────────────────────────────────────────

def _bar(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        y_vals = s.y or []
        has_negatives = any(v is not None and v < 0 for v in y_vals)

        if has_negatives and len(valid) == 1:
            # Signed data: semantic colors for +/- only when needed
            bar_colors = [(_POS if (v is not None and v >= 0) else _NEG) for v in y_vals]
            marker = dict(color=bar_colors, opacity=0.90,
                          line=dict(color="rgba(0,0,0,0.25)", width=0.5))
        elif len(valid) == 1:
            # Single series ranking/comparison — each bar a different palette color
            bar_colors = [COLORS[j % len(COLORS)] for j in range(len(y_vals))]
            marker = dict(color=bar_colors, opacity=0.90,
                          line=dict(color="rgba(0,0,0,0.2)", width=0.5))
        else:
            # Multi-series: one color per series
            c = COLORS[i % len(COLORS)]
            marker = dict(color=c, opacity=0.90,
                          line=dict(color="rgba(0,0,0,0.2)", width=0.5))

        fig.add_trace(go.Bar(
            name=s.name, x=s.x, y=s.y,
            marker=marker,
            text=[_fmt(v) for v in y_vals],
            textposition="auto",       # "auto" fits inside tall bars, outside short ones
            textfont=dict(family=FONT_MONO, color=TEXT, size=10),
            hovertemplate="<b>%{x}</b><br>%{y:,.3~f}<extra></extra>",
            cliponaxis=False,
        ))

    barmode = "group" if len(valid) > 1 else "relative"
    layout = _base_layout(spec.title)
    layout.update(_xy_layout(spec.x_label, spec.y_label))
    layout["barmode"]   = barmode
    layout["bargap"]    = 0.30
    layout["yaxis"]     = {**layout.get("yaxis", {}), "automargin": True}
    fig.update_layout(**layout)
    return fig


def _horizontal_bar(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        y_vals = s.y or []
        has_negatives = any(v is not None and v < 0 for v in y_vals)

        if has_negatives and len(valid) == 1:
            bar_colors = [(_POS if (v is not None and v >= 0) else _NEG) for v in y_vals]
            marker = dict(color=bar_colors, opacity=0.90,
                          line=dict(color="rgba(0,0,0,0.2)", width=0.5))
        elif len(valid) == 1:
            bar_colors = [COLORS[j % len(COLORS)] for j in range(len(y_vals))]
            marker = dict(color=bar_colors, opacity=0.90,
                          line=dict(color="rgba(0,0,0,0.15)", width=0.5))
        else:
            c = COLORS[i % len(COLORS)]
            marker = dict(color=c, opacity=0.90)

        fig.add_trace(go.Bar(
            name=s.name, x=s.y, y=s.x, orientation="h",
            marker=marker,
            text=[_fmt(v) for v in y_vals],
            textposition="outside",
            textfont=dict(family=FONT_MONO, color=TEXT, size=10),
            hovertemplate="<b>%{y}</b><br>%{x:,.3~f}<extra></extra>",
            cliponaxis=False,
        ))

    # Height scales with number of items — ranking charts need room per bar
    n_items = max(len(s.x or []) for s in valid)
    chart_height = max(380, min(80 * n_items, 800))

    base = _base_layout(spec.title)
    base.pop("margin", None)
    fig.update_layout(
        **base,
        height=chart_height,
        xaxis=dict(
            gridcolor=GRID, zerolinecolor=ZEROLINE,
            title=dict(text=spec.y_label, font=dict(color=TEXT_DIM)),
            tickfont=dict(family=FONT_MONO, color=TEXT_DIM, size=10),
            automargin=True,
        ),
        yaxis=dict(
            gridcolor=GRID,
            categoryorder="total ascending",   # largest value bar at top
            title=dict(text=spec.x_label, font=dict(color=TEXT_DIM)),
            tickfont=dict(family=FONT_MONO, color=TEXT_DIM, size=10),
            automargin=True,
        ),
        bargap=0.22,
        margin=dict(l=200, r=120, t=55, b=50),
        uniformtext_minsize=8,
        uniformtext_mode="hide",
    )
    return fig


def _line(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        r, g, b = _hex_rgb(c)
        n_points = len(s.y or [])
        # Larger markers for sparse data (trends over years), tiny for dense
        marker_size = 8 if n_points <= 15 else 4
        show_text   = n_points <= 12   # annotate values when few points
        fig.add_trace(go.Scatter(
            name=s.name, x=s.x, y=s.y,
            mode="lines+markers+text" if show_text else "lines+markers",
            line=dict(color=c, width=2.5, shape="spline"),
            marker=dict(color=c, size=marker_size, line=dict(color=BG, width=2)),
            text=[_fmt(v) for v in (s.y or [])] if show_text else None,
            textposition="top center",
            textfont=dict(family=FONT_MONO, color=c, size=9),
            fill="tozeroy" if len(valid) == 1 else "none",
            fillcolor=f"rgba({r},{g},{b},0.06)",
            hovertemplate="<b>%{x}</b><br>%{y:,.3~f}<extra></extra>",
        ))
    layout = _base_layout(spec.title)
    layout.update(_xy_layout(spec.x_label, spec.y_label))
    # Extra top margin so text labels above peaks don't clip
    layout["margin"] = dict(l=60, r=20, t=70, b=55)
    fig.update_layout(**layout)
    return fig


def _area(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        r, g, b = _hex_rgb(c)
        fig.add_trace(go.Scatter(
            name=s.name, x=s.x, y=s.y,
            mode="lines",
            line=dict(color=c, width=2.5),
            fill="tozeroy",
            fillcolor=f"rgba({r},{g},{b},0.18)",
            hovertemplate="<b>%{x}</b><br>%{y:,.3~f}<extra></extra>",
        ))
    fig.update_layout(**_base_layout(spec.title), **_xy_layout(spec.x_label, spec.y_label))
    return fig


def _pie(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not _valid_series(s):
        return _no_data_fig(spec.title)
    pairs = [(x, y) for x, y in zip(s.x, s.y) if y is not None and y > 0]
    if not pairs:
        return _no_data_fig(spec.title, "No positive values to plot")
    labels, values = zip(*pairs)
    colors = [COLORS[j % len(COLORS)] for j in range(len(labels))]
    fig = go.Figure(go.Pie(
        labels=list(labels), values=list(values),
        marker=dict(colors=colors, line=dict(color=BG, width=2.5)),
        textinfo="label+percent",
        textfont=dict(family=FONT_MONO, size=11, color=TEXT),
        hovertemplate="<b>%{label}</b><br>%{value:,.2~f} (%{percent})<extra></extra>",
        rotation=90,    # start from top — more natural reading order
    ))
    fig.update_layout(**_base_layout(spec.title))
    return fig


def _donut(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not _valid_series(s):
        return _no_data_fig(spec.title)
    pairs = [(x, y) for x, y in zip(s.x, s.y) if y is not None and y > 0]
    if not pairs:
        return _no_data_fig(spec.title, "No positive values to plot")
    labels, values = zip(*pairs)
    total = sum(values)
    colors = [COLORS[j % len(COLORS)] for j in range(len(labels))]

    # Only pull the largest slice — highlights the leader without looking exploded
    max_idx = list(values).index(max(values))
    pull = [0.06 if j == max_idx else 0 for j in range(len(labels))]

    fig = go.Figure(go.Pie(
        labels=list(labels), values=list(values),
        hole=0.58,
        marker=dict(colors=colors, line=dict(color=BG, width=2.5)),
        textinfo="label+percent",
        textfont=dict(family=FONT_MONO, size=11, color=TEXT),
        hovertemplate="<b>%{label}</b><br>%{value:,.2~f} (%{percent})<extra></extra>",
        pull=pull,
        rotation=90,
    ))
    fig.add_annotation(
        text=f"<b>{_fmt(total)}</b>",
        x=0.5, y=0.5,
        font=dict(size=20, color=TEXT, family=FONT_BODY),
        showarrow=False,
    )
    fig.update_layout(**_base_layout(spec.title))
    return fig


def _scatter(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        x_vals = [_safe_float(v) for v in s.x]
        fig.add_trace(go.Scatter(
            name=s.name, x=x_vals, y=s.y, mode="markers",
            marker=dict(color=c, size=9, opacity=0.80,
                        line=dict(color=BG, width=0.5)),
            hovertemplate=f"{s.name}<br>X: %{{x:.3g}}<br>Y: %{{y:.3g}}<extra></extra>",
        ))
    fig.update_layout(**_base_layout(spec.title), **_xy_layout(spec.x_label, spec.y_label))
    return fig


def _histogram(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        vals = [v for v in s.y if v is not None]
        fig.add_trace(go.Histogram(
            name=s.name, x=vals,
            marker=dict(color=c, opacity=0.85,
                        line=dict(color=BG, width=0.5)),
        ))
    fig.update_layout(**_base_layout(spec.title),
                      **_xy_layout(spec.x_label or "Value", spec.y_label or "Frequency"),
                      barmode="overlay")
    return fig


def _box(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        r, g, b = _hex_rgb(c)
        fig.add_trace(go.Box(
            name=s.name, y=[v for v in s.y if v is not None],
            marker=dict(color=c, size=4),
            line=dict(color=c, width=1.5),
            fillcolor=f"rgba({r},{g},{b},0.15)",
            boxmean="sd",
        ))
    fig.update_layout(**_base_layout(spec.title), **_xy_layout(spec.x_label, spec.y_label))
    return fig


def _radar(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        r, g, b = _hex_rgb(c)
        cats = s.x or [f"Attr {j+1}" for j in range(len(s.y))]
        # Close the polygon
        vals        = list(s.y) + [s.y[0]]  if s.y  else []
        cats_closed = list(cats) + [cats[0]] if cats else []
        fig.add_trace(go.Scatterpolar(
            name=s.name, r=vals, theta=cats_closed,
            fill="toself",
            line=dict(color=c, width=2.5),
            fillcolor=f"rgba({r},{g},{b},0.15)",
            marker=dict(color=c, size=6, line=dict(color=BG, width=1)),
            hovertemplate="<b>%{theta}</b><br>" + s.name + ": %{r:.1f}<extra></extra>",
        ))
    layout = _base_layout(spec.title)
    layout.pop("margin", None)
    layout["height"] = 520
    layout["margin"] = dict(l=60, r=60, t=60, b=60)
    layout["polar"]  = dict(
        bgcolor=BG_PLOT,
        radialaxis=dict(
            visible=True,
            gridcolor=GRID,
            tickfont=dict(color=TEXT_DIM, size=9),
            linecolor=ZEROLINE,
            range=[0, 100],   # normalized 0–100 scale for comparisons
        ),
        angularaxis=dict(
            gridcolor=GRID,
            tickfont=dict(color=TEXT, size=12, family=FONT_BODY),
            linecolor=ZEROLINE,
        ),
    )
    # Legend is critical for multi-series radar
    layout["legend"] = dict(
        bgcolor="rgba(10,15,26,0.9)",
        bordercolor=ZEROLINE, borderwidth=1,
        font=dict(color=TEXT, size=11),
        orientation="h",
        y=-0.05,
    )
    fig.update_layout(**layout)
    return fig


def _funnel(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not _valid_series(s):
        return _no_data_fig(spec.title)
    n = len(s.x)
    colors = [COLORS[j % len(COLORS)] for j in range(n)]
    fig = go.Figure(go.Funnel(
        y=s.x, x=s.y,
        marker=dict(color=colors, line=dict(color=BG, width=1)),
        textfont=dict(family=FONT_MONO, color=TEXT, size=11),
        hovertemplate="<b>%{y}</b><br>%{x:,.2~f}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(spec.title))
    return fig


def _waterfall(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not _valid_series(s):
        return _no_data_fig(spec.title)
    measures = ["relative"] * len(s.x)
    if measures:
        measures[-1] = "total"
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measures,
        x=s.x, y=s.y,
        text=[_fmt(v) for v in s.y], textposition="outside",
        textfont=dict(family=FONT_MONO, color=TEXT, size=10),
        # Use palette semantic colors, not harsh neon
        increasing=dict(marker=dict(color=_POS)),
        decreasing=dict(marker=dict(color=_NEG)),
        totals=dict(marker=dict(color=COLORS[0])),
        connector=dict(line=dict(color=ZEROLINE, width=1, dash="dot")),
    ))
    fig.update_layout(**_base_layout(spec.title), **_xy_layout(spec.x_label, spec.y_label))
    return fig


def _sunburst(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not s.labels or len(s.labels) < 2:
        return _no_data_fig(spec.title, "No hierarchy data")

    # Truncate long labels — prevents text overflow
    display_labels = [str(l)[:_MAX_LABEL] for l in s.labels]
    n = len(display_labels)

    label_map = {old: new for old, new in zip(s.labels, display_labels)}
    display_parents = [label_map.get(p, p)[:_MAX_LABEL] if p else "" for p in (s.parents or [])]

    # Safe values — root must be 0 for remainder mode
    raw_values = s.values or []
    safe_values = []
    for v in raw_values:
        try:
            f = float(v)
            safe_values.append(max(f, 0.01) if math.isfinite(f) else 1.0)
        except (TypeError, ValueError):
            safe_values.append(1.0)
    safe_values = (safe_values + [1.0] * n)[:n]
    for i, p in enumerate(display_parents):
        if p == "":
            safe_values[i] = 0.0

    # Richer, more varied color palette for hierarchy levels
    hier_colors = (COLORS * (n // len(COLORS) + 1))[:n]

    fig = go.Figure(go.Sunburst(
        labels=display_labels,
        parents=display_parents,
        values=safe_values,
        text=s.text or [""] * n,
        branchvalues="remainder",
        hovertemplate="<b>%{label}</b><br>%{customdata}<br><extra></extra>",
        customdata=s.text or [""] * n,
        textfont=dict(family=FONT_BODY, size=11, color="#ffffff"),  # white text on colored segments
        insidetextorientation="auto",
        leaf=dict(opacity=0.88),
        marker=dict(
            colors=hier_colors,
            line=dict(color=BG, width=2),       # thicker separator = cleaner look
        ),
        maxdepth=3,
        rotation=0,
    ))
    layout = _base_layout(spec.title)
    layout.pop("margin", None)
    layout["height"] = 540
    layout["margin"] = dict(l=10, r=10, t=60, b=10)
    fig.update_layout(**layout)
    return fig


def _treemap(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not s.labels or len(s.labels) < 2:
        return _no_data_fig(spec.title, "No hierarchy data")

    display_labels = [str(l)[:_MAX_LABEL] for l in s.labels]
    n = len(display_labels)
    label_map = {old: new for old, new in zip(s.labels, display_labels)}
    display_parents = [label_map.get(p, p)[:_MAX_LABEL] if p else "" for p in (s.parents or [])]

    raw_values = s.values or []
    safe_values = []
    for v in raw_values:
        try:
            f = float(v)
            safe_values.append(max(f, 0.01) if math.isfinite(f) else 1.0)
        except (TypeError, ValueError):
            safe_values.append(1.0)
    safe_values = (safe_values + [1.0] * n)[:n]
    for i, p in enumerate(display_parents):
        if p == "":
            safe_values[i] = 0.0

    fig = go.Figure(go.Treemap(
        labels=display_labels,
        parents=display_parents,
        values=safe_values,
        text=s.text or [""] * n,
        branchvalues="remainder",
        hovertemplate="<b>%{label}</b><br>%{text}<br><extra></extra>",
        textfont=dict(family=FONT_BODY, size=12, color="#ffffff"),
        marker=dict(
            colors=(COLORS * (n // len(COLORS) + 1))[:n],
            line=dict(color=BG, width=2.5),
            pad=dict(t=6, l=4, r=4, b=4),
        ),
    ))
    layout = _base_layout(spec.title)
    layout.pop("margin", None)
    layout["height"] = 520
    layout["margin"] = dict(l=10, r=10, t=60, b=10)
    fig.update_layout(**layout)
    return fig


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _fmt(v) -> str:
    try:
        f = float(v)
        if abs(f) >= 1e9:  return f"{f/1e9:,.2f}B"
        if abs(f) >= 1e6:  return f"{f/1e6:,.2f}M"
        if abs(f) >= 1e3:  return f"{f/1e3:,.1f}K"
        return f"{int(f):,}" if f == int(f) else f"{f:,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _base_layout(title: str = "") -> dict:
    return dict(
        title=dict(text=title, font=dict(size=15, color=TEXT, family=FONT_BODY), x=0.02, xanchor="left"),
        paper_bgcolor=BG,
        plot_bgcolor=BG_PLOT,
        font=dict(family=FONT_MONO, color=TEXT_DIM, size=11),
        margin=dict(l=55, r=20, t=50, b=50),
        legend=dict(
            bgcolor="rgba(10,15,26,0.85)",
            bordercolor=ZEROLINE, borderwidth=1,
            font=dict(color=TEXT_DIM, size=10),
        ),
        hoverlabel=dict(
            bgcolor="#0d1930", bordercolor=COLORS[0],
            font=dict(family=FONT_BODY, color=TEXT, size=12),
        ),
        colorway=COLORS,
    )


def _xy_layout(x_label: str = "", y_label: str = "") -> dict:
    axis = dict(
        gridcolor=GRID, zerolinecolor=ZEROLINE, zerolinewidth=1,
        tickfont=dict(family=FONT_MONO, color=TEXT_DIM, size=10),
        linecolor=ZEROLINE,
    )
    return dict(
        xaxis=dict(**axis, title=dict(text=x_label, font=dict(color=TEXT_DIM, size=11))),
        yaxis=dict(**axis, title=dict(text=y_label, font=dict(color=TEXT_DIM, size=11)),
                   tickformat=",.2~f"),
    )


def _no_data_fig(title: str, reason: str = "No data available") -> go.Figure:
    """Return a styled empty-state figure instead of a blank canvas."""
    fig = go.Figure()
    layout = _base_layout(title)
    layout["height"] = 300
    fig.update_layout(**layout)
    fig.add_annotation(
        text=f'<span style="font-size:22px">📊</span><br>'
             f'<span style="color:{TEXT};font-size:14px">{reason}</span>',
        x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, align="center",
        font=dict(color=TEXT_DIM, size=13, family=FONT_BODY),
    )
    return fig


def _error_fig(title: str, error: str) -> go.Figure:
    """Return a styled error figure — never embed error text inside chart axes."""
    fig = go.Figure()
    layout = _base_layout(f"⚠ {title}")
    layout["height"] = 300
    fig.update_layout(**layout)
    short = str(error)[:180]
    fig.add_annotation(
        text=f'<span style="color:#ff3b5c;font-size:13px"><b>Error generating chart</b></span>'
             f'<br><span style="color:{TEXT_DIM};font-size:11px">{short}</span>',
        x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, align="center",
        font=dict(family=FONT_MONO),
    )
    return fig


def _valid_series(s: ChartSeries) -> bool:
    """Return True only if series has at least one renderable data point."""
    nums = [v for v in (s.y or []) if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]
    return len(nums) > 0


def build(spec: VisualizationSpec) -> go.Figure:
    """Build a Plotly Figure. Never raises — returns error/no-data figure on failure."""
    try:
        builders = {
            ChartType.BAR:            _bar,
            ChartType.HORIZONTAL_BAR: _horizontal_bar,
            ChartType.LINE:           _line,
            ChartType.AREA:           _area,
            ChartType.PIE:            _pie,
            ChartType.DONUT:          _donut,
            ChartType.SCATTER:        _scatter,
            ChartType.HISTOGRAM:      _histogram,
            ChartType.BOX:            _box,
            ChartType.RADAR:          _radar,
            ChartType.FUNNEL:         _funnel,
            ChartType.WATERFALL:      _waterfall,
            ChartType.SUNBURST:       _sunburst,
            ChartType.TREEMAP:        _treemap,
        }
        return builders[spec.chart_type](spec)
    except Exception as e:
        return _error_fig(spec.title, str(e))


# ── Chart builders ─────────────────────────────────────────────────────────────

def _bar(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        y_vals = s.y or []
        has_negatives = any(v is not None and v < 0 for v in y_vals)

        if has_negatives and len(valid) == 1:
            # Signed data — use semantic colors only when signs differ meaningfully
            bar_colors = [(_POS if (v is not None and v >= 0) else _NEG) for v in y_vals]
            marker = dict(color=bar_colors, opacity=0.88,
                          line=dict(color="rgba(0,0,0,0.2)", width=0.5))
        else:
            # Multi-series or pure positive: use palette colors per bar for visual variety
            if len(valid) == 1 and len(y_vals) <= 20:
                bar_colors = [COLORS[j % len(COLORS)] for j in range(len(y_vals))]
                marker = dict(color=bar_colors, opacity=0.88,
                              line=dict(color="rgba(0,0,0,0.2)", width=0.5))
            else:
                c = COLORS[i % len(COLORS)]
                marker = dict(color=c, opacity=0.88,
                              line=dict(color="rgba(0,0,0,0.2)", width=0.5))

        fig.add_trace(go.Bar(
            name=s.name, x=s.x, y=s.y,
            marker=marker,
            text=[_fmt(v) for v in y_vals],
            textposition="outside",
            textfont=dict(family=FONT_MONO, color=TEXT, size=9),
            hovertemplate="<b>%{x}</b><br>%{y:,.2~f}<extra></extra>",
            cliponaxis=False,
        ))

    barmode = "group" if len(valid) > 1 else "relative"
    layout = _base_layout(spec.title)
    layout.update(_xy_layout(spec.x_label, spec.y_label))
    layout["barmode"]              = barmode
    layout["bargap"]               = 0.28
    layout["uniformtext_minsize"]  = 7
    layout["uniformtext_mode"]     = "hide"
    # Give room above bars for labels
    layout["yaxis"] = {**layout.get("yaxis", {}),
                       "automargin": True}
    fig.update_layout(**layout)
    return fig


def _horizontal_bar(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        y_vals = s.y or []
        has_negatives = any(v is not None and v < 0 for v in y_vals)

        if has_negatives and len(valid) == 1:
            bar_colors = [(_POS if (v is not None and v >= 0) else _NEG) for v in y_vals]
            marker = dict(color=bar_colors, opacity=0.88,
                          line=dict(color="rgba(0,0,0,0.2)", width=0.5))
        elif len(valid) == 1:
            # Color each bar differently for rankings — visually engaging
            bar_colors = [COLORS[j % len(COLORS)] for j in range(len(y_vals))]
            marker = dict(color=bar_colors, opacity=0.88,
                          line=dict(color="rgba(0,0,0,0.15)", width=0.5))
        else:
            c = COLORS[i % len(COLORS)]
            marker = dict(color=c, opacity=0.88)

        fig.add_trace(go.Bar(
            name=s.name, x=s.y, y=s.x, orientation="h",
            marker=marker,
            text=[_fmt(v) for v in y_vals],
            textposition="outside",
            textfont=dict(family=FONT_MONO, color=TEXT, size=9),
            hovertemplate="<b>%{y}</b><br>%{x:,.2~f}<extra></extra>",
            cliponaxis=False,
        ))

    base = _base_layout(spec.title)
    base.pop("margin", None)
    fig.update_layout(
        **base,
        xaxis=dict(gridcolor=GRID, zerolinecolor=ZEROLINE,
                   title=dict(text=spec.y_label, font=dict(color=TEXT_DIM)),
                   tickfont=dict(family=FONT_MONO, color=TEXT_DIM, size=10),
                   automargin=True),
        yaxis=dict(gridcolor=GRID, categoryorder="total ascending",
                   title=dict(text=spec.x_label, font=dict(color=TEXT_DIM)),
                   tickfont=dict(family=FONT_MONO, color=TEXT_DIM, size=10),
                   automargin=True),
        bargap=0.22,
        margin=dict(l=180, r=80, t=50, b=50),
        uniformtext_minsize=7,
        uniformtext_mode="hide",
    )
    return fig


def _line(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        r, g, b = _hex_rgb(c)
        fig.add_trace(go.Scatter(
            name=s.name, x=s.x, y=s.y, mode="lines+markers",
            line=dict(color=c, width=2.5, shape="spline"),
            marker=dict(color=c, size=6, line=dict(color=BG, width=2)),
            fill="tozeroy" if len(valid) == 1 else "none",
            fillcolor=f"rgba({r},{g},{b},0.08)",
            hovertemplate="<b>%{x}</b><br>%{y:,.2~f}<extra></extra>",
        ))
    fig.update_layout(**_base_layout(spec.title), **_xy_layout(spec.x_label, spec.y_label))
    return fig


def _area(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        r, g, b = _hex_rgb(c)
        fig.add_trace(go.Scatter(
            name=s.name, x=s.x, y=s.y, mode="lines",
            line=dict(color=c, width=2),
            fill="tozeroy",
            fillcolor=f"rgba({r},{g},{b},0.15)",
            hovertemplate="<b>%{x}</b><br>%{y:,.2~f}<extra></extra>",
        ))
    fig.update_layout(**_base_layout(spec.title), **_xy_layout(spec.x_label, spec.y_label))
    return fig


def _pie(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not _valid_series(s):
        return _no_data_fig(spec.title)
    pairs = [(x, y) for x, y in zip(s.x, s.y) if y is not None and y > 0]
    if not pairs:
        return _no_data_fig(spec.title, "No positive values to plot")
    labels, values = zip(*pairs)
    colors = [COLORS[j % len(COLORS)] for j in range(len(labels))]
    fig = go.Figure(go.Pie(
        labels=list(labels), values=list(values),
        marker=dict(colors=colors, line=dict(color=BG, width=2)),
        textinfo="label+percent",
        textfont=dict(family=FONT_MONO, size=11),
        hovertemplate="<b>%{label}</b><br>%{value:,.2~f} (%{percent})<extra></extra>",
    ))
    fig.update_layout(**_base_layout(spec.title))
    return fig


def _donut(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not _valid_series(s):
        return _no_data_fig(spec.title)
    pairs = [(x, y) for x, y in zip(s.x, s.y) if y is not None and y > 0]
    if not pairs:
        return _no_data_fig(spec.title, "No positive values to plot")
    labels, values = zip(*pairs)
    total = sum(values)
    colors = [COLORS[j % len(COLORS)] for j in range(len(labels))]
    fig = go.Figure(go.Pie(
        labels=list(labels), values=list(values), hole=0.55,
        marker=dict(colors=colors, line=dict(color=BG, width=2)),
        textinfo="label+percent",
        textfont=dict(family=FONT_MONO, size=11),
        hovertemplate="<b>%{label}</b><br>%{value:,.2~f} (%{percent})<extra></extra>",
        pull=[0.03] * len(labels),   # slight pull for depth effect
    ))
    fig.add_annotation(
        text=f"<b>{_fmt(total)}</b>",
        x=0.5, y=0.5,
        font=dict(size=20, color=TEXT, family=FONT_BODY),
        showarrow=False,
    )
    fig.update_layout(**_base_layout(spec.title))
    return fig


def _scatter(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        x_vals = [_safe_float(v) for v in s.x]
        fig.add_trace(go.Scatter(
            name=s.name, x=x_vals, y=s.y, mode="markers",
            marker=dict(color=c, size=8, opacity=0.75, line=dict(color=BG, width=0.5)),
            hovertemplate=f"{s.name}<br>X: %{{x:.3g}}<br>Y: %{{y:.3g}}<extra></extra>",
        ))
    fig.update_layout(**_base_layout(spec.title), **_xy_layout(spec.x_label, spec.y_label))
    return fig


def _histogram(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        vals = [v for v in s.y if v is not None]
        fig.add_trace(go.Histogram(
            name=s.name, x=vals,
            marker=dict(color=c, opacity=0.8, line=dict(color=BG, width=0.5)),
        ))
    fig.update_layout(**_base_layout(spec.title),
                      **_xy_layout(spec.x_label or "Value", spec.y_label or "Frequency"),
                      barmode="overlay")
    return fig


def _box(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        r, g, b = _hex_rgb(c)
        fig.add_trace(go.Box(
            name=s.name, y=[v for v in s.y if v is not None],
            marker=dict(color=c, size=4),
            line=dict(color=c, width=1.5),
            fillcolor=f"rgba({r},{g},{b},0.15)",
            boxmean="sd",
        ))
    fig.update_layout(**_base_layout(spec.title), **_xy_layout(spec.x_label, spec.y_label))
    return fig


def _radar(spec: VisualizationSpec) -> go.Figure:
    valid = [s for s in spec.series if _valid_series(s)]
    if not valid:
        return _no_data_fig(spec.title)
    fig = go.Figure()
    for i, s in enumerate(valid):
        c = COLORS[i % len(COLORS)]
        r, g, b = _hex_rgb(c)
        cats = s.x or [f"C{j}" for j in range(len(s.y))]
        vals = list(s.y) + [s.y[0]] if s.y else []
        cats = list(cats) + [cats[0]] if cats else []
        fig.add_trace(go.Scatterpolar(
            name=s.name, r=vals, theta=cats, fill="toself",
            line=dict(color=c, width=1.5),
            fillcolor=f"rgba({r},{g},{b},0.12)",
        ))
    fig.update_layout(
        **_base_layout(spec.title),
        polar=dict(
            bgcolor=BG_PLOT,
            radialaxis=dict(visible=True, gridcolor=GRID, tickfont=dict(color=TEXT_DIM, size=9)),
            angularaxis=dict(gridcolor=GRID, tickfont=dict(color=TEXT_DIM, size=10)),
        ),
    )
    return fig


def _funnel(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not _valid_series(s):
        return _no_data_fig(spec.title)
    fig = go.Figure(go.Funnel(
        y=s.x, x=s.y,
        marker=dict(color=COLORS[:len(s.x)], line=dict(color=BG, width=1)),
        textfont=dict(family=FONT_MONO, color=TEXT, size=11),
        hovertemplate="<b>%{y}</b><br>%{x:,.2~f}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(spec.title))
    return fig


def _waterfall(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not _valid_series(s):
        return _no_data_fig(spec.title)
    measures = ["relative"] * len(s.x)
    if measures:
        measures[-1] = "total"
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measures,
        x=s.x, y=s.y,
        text=[_fmt(v) for v in s.y], textposition="outside",
        textfont=dict(family=FONT_MONO, color=TEXT, size=10),
        increasing=dict(marker=dict(color="#00ff88")),
        decreasing=dict(marker=dict(color="#ff3b5c")),
        totals=dict(marker=dict(color=COLORS[0])),
        connector=dict(line=dict(color=ZEROLINE, width=1, dash="dot")),
    ))
    fig.update_layout(**_base_layout(spec.title), **_xy_layout(spec.x_label, spec.y_label))
    return fig


def _sunburst(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not s.labels or len(s.labels) < 2:
        return _no_data_fig(spec.title, "No hierarchy data")

    display_labels = [str(l)[:_MAX_LABEL] for l in s.labels]
    n = len(display_labels)

    # Build parent display label map
    label_map = {old: new for old, new in zip(s.labels, display_labels)}
    display_parents = [label_map.get(p, p)[:_MAX_LABEL] if p else "" for p in (s.parents or [])]

    # CRITICAL FIX: branchvalues="total" renders BLANK when root value = 0.
    # Use branchvalues="remainder" — Plotly computes root from its children automatically.
    # This is the correct mode for knowledge hierarchies.
    raw_values = s.values or []
    # Ensure all values are positive floats
    safe_values = []
    for v in raw_values:
        try:
            f = float(v)
            safe_values.append(max(f, 0.01) if math.isfinite(f) else 1.0)
        except (TypeError, ValueError):
            safe_values.append(1.0)
    # Pad if needed
    safe_values = (safe_values + [1.0] * n)[:n]
    # Root node (parent="") should have value = 0 with remainder mode
    for i, p in enumerate(display_parents):
        if p == "":
            safe_values[i] = 0.0

    fig = go.Figure(go.Sunburst(
        labels=display_labels,
        parents=display_parents,
        values=safe_values,
        text=s.text or [""] * n,
        branchvalues="remainder",          # FIXED: was "total" which caused blank render
        hovertemplate="<b>%{label}</b><br>%{customdata}<br><extra></extra>",
        customdata=s.text or [""] * n,
        textfont=dict(family=FONT_BODY, size=10),
        insidetextorientation="auto",
        leaf=dict(opacity=0.9),
        marker=dict(
            colors=(COLORS * (n // len(COLORS) + 1))[:n],
            line=dict(color=BG, width=1.5),
        ),
        maxdepth=3,
    ))
    layout = _base_layout(spec.title)
    layout.pop("margin", None)         # remove default — set explicitly below
    layout["height"] = 520
    layout["margin"] = dict(l=10, r=10, t=55, b=10)
    fig.update_layout(**layout)
    return fig


def _treemap(spec: VisualizationSpec) -> go.Figure:
    s = spec.series[0] if spec.series else ChartSeries()
    if not s.labels or len(s.labels) < 2:
        return _no_data_fig(spec.title, "No hierarchy data")

    display_labels = [str(l)[:_MAX_LABEL] for l in s.labels]
    n = len(display_labels)
    label_map = {old: new for old, new in zip(s.labels, display_labels)}
    display_parents = [label_map.get(p, p)[:_MAX_LABEL] if p else "" for p in (s.parents or [])]

    raw_values = s.values or []
    safe_values = []
    for v in raw_values:
        try:
            f = float(v)
            safe_values.append(max(f, 0.01) if math.isfinite(f) else 1.0)
        except (TypeError, ValueError):
            safe_values.append(1.0)
    safe_values = (safe_values + [1.0] * n)[:n]
    for i, p in enumerate(display_parents):
        if p == "":
            safe_values[i] = 0.0

    fig = go.Figure(go.Treemap(
        labels=display_labels,
        parents=display_parents,
        values=safe_values,
        text=s.text or [""] * n,
        branchvalues="remainder",          # FIXED: same as sunburst
        hovertemplate="<b>%{label}</b><br>%{text}<br><extra></extra>",
        textfont=dict(family=FONT_BODY, size=12, color=TEXT),
        marker=dict(
            colors=(COLORS * (n // len(COLORS) + 1))[:n],
            line=dict(color=BG, width=2),
            pad=dict(t=5, l=4, r=4, b=4),
        ),
    ))
    layout = _base_layout(spec.title)
    layout.pop("margin", None)
    layout["height"] = 520
    layout["margin"] = dict(l=10, r=10, t=55, b=10)
    fig.update_layout(**layout)
    return fig


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _fmt(v) -> str:
    try:
        f = float(v)
        if abs(f) >= 1e9:  return f"{f/1e9:,.2f}B"
        if abs(f) >= 1e6:  return f"{f/1e6:,.2f}M"
        if abs(f) >= 1e3:  return f"{f/1e3:,.1f}K"
        return f"{int(f):,}" if f == int(f) else f"{f:,.2f}"
    except (TypeError, ValueError):
        return str(v)