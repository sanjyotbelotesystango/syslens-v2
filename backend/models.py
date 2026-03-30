"""
models.py — All data models for sYsLens v2.
"""

from __future__ import annotations
import math
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class AgentMode(str, Enum):
    DIRECT_DATA   = "direct_data"
    KNOWLEDGE_MAP = "knowledge_map"
    VISION        = "vision"
    OCR_IMAGE     = "ocr_image"
    FILE_ANALYSIS = "file_analysis"
    PDF           = "pdf"
    FOLLOWUP      = "followup"
    GREETING      = "greeting"       # NEW: conversational / no-chart responses


class ChartType(str, Enum):
    BAR            = "bar"
    HORIZONTAL_BAR = "horizontal_bar"
    LINE           = "line"
    AREA           = "area"
    PIE            = "pie"
    DONUT          = "donut"
    SCATTER        = "scatter"
    HISTOGRAM      = "histogram"
    BOX            = "box"
    RADAR          = "radar"
    FUNNEL         = "funnel"
    WATERFALL      = "waterfall"
    SUNBURST       = "sunburst"
    TREEMAP        = "treemap"


class KPICard(BaseModel):
    label:       str
    value:       Union[float, int, str]
    formatted:   str = ""
    delta:       Optional[float] = None
    delta_label: str = ""
    prefix:      str = ""
    suffix:      str = ""
    color:       str = "cyan"

    def display_value(self) -> str:
        if self.formatted:
            return self.formatted
        try:
            n = float(self.value)
            if abs(n) >= 1_000_000_000: return f"{self.prefix}{n/1e9:.2f}B{self.suffix}"
            if abs(n) >= 1_000_000:     return f"{self.prefix}{n/1e6:.2f}M{self.suffix}"
            if abs(n) >= 1_000:         return f"{self.prefix}{n/1e3:.1f}K{self.suffix}"
            return f"{self.prefix}{int(n) if n == int(n) else round(n,2)}{self.suffix}"
        except (TypeError, ValueError):
            return str(self.value)


class ChartSeries(BaseModel):
    name: str = "Series"
    x: List[Union[str, float, int, None]] = Field(default_factory=list)
    y: List[Union[float, int, None]]      = Field(default_factory=list)
    labels:  Optional[List[str]]   = None
    parents: Optional[List[str]]   = None
    values:  Optional[List[float]] = None
    text:    Optional[List[str]]   = None

    @field_validator("y", mode="before")
    @classmethod
    def clean_y_values(cls, values):
        if not isinstance(values, list):
            return []
        cleaned = []
        for v in values:
            if v is None:
                cleaned.append(None)
            else:
                try:
                    f = float(v)
                    cleaned.append(None if (math.isnan(f) or math.isinf(f)) else round(f, 6))
                except (TypeError, ValueError):
                    cleaned.append(None)
        return cleaned

    @field_validator("x", mode="before")
    @classmethod
    def clean_x_values(cls, values):
        if not isinstance(values, list):
            return []
        return [str(v) if v is not None else "" for v in values]


class VisualizationSpec(BaseModel):
    chart_type: ChartType
    title:      str = "Analysis"
    x_label:    str = ""
    y_label:    str = ""
    series:     List[ChartSeries] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lengths(self) -> "VisualizationSpec":
        hierarchy = {ChartType.SUNBURST, ChartType.TREEMAP}
        for s in self.series:
            if self.chart_type in hierarchy:
                if not s.labels:
                    raise ValueError("Hierarchy chart requires series.labels")
                n = len(s.labels)
                s.parents = (s.parents or [])[:n]
                s.values  = ((s.values or []) + [1.0] * n)[:n]
            else:
                if s.y and s.x and len(s.x) != len(s.y):
                    min_len = min(len(s.x), len(s.y))
                    s.x = s.x[:min_len]
                    s.y = s.y[:min_len]
                elif s.y and not s.x:
                    s.x = [str(i) for i in range(len(s.y))]
        return self


class AnalysisResult(BaseModel):
    mode:           str
    spec:           Optional[VisualizationSpec] = None   # None for GREETING mode
    insight:        str = ""
    cleaning_steps: List[str]  = Field(default_factory=list)
    stats:          Dict[str, Union[str, int, float]] = Field(default_factory=dict)
    kpis:           List[KPICard] = Field(default_factory=list)
    generated_code: str = ""


class AnalysisRequest(BaseModel):
    text:        str            = ""
    file_bytes:  Optional[bytes] = None
    filename:    Optional[str]   = None
    image_bytes: Optional[bytes] = None
    image_type:  Optional[str]   = None
    session_id:  Optional[str]   = None

    class Config:
        arbitrary_types_allowed = True


class ConversationTurn(BaseModel):
    role:    Literal["user", "assistant"]
    content: str
    mode:    Optional[str] = None


class SessionContext(BaseModel):
    turns:       List[ConversationTurn] = Field(default_factory=list)
    last_result: Optional[AnalysisResult] = None
    last_mode:   Optional[str] = None

    def recent_messages(self, n: int = 8) -> List[Dict[str, str]]:
        return [{"role": t.role, "content": t.content} for t in self.turns[-n:]]


class SandboxResult(BaseModel):
    success:     bool
    stdout:      str = ""
    stderr:      str = ""
    exit_code:   int = 0
    output_json: Optional[Dict[str, Any]] = None


# ── Legacy models ──────────────────────────────────────────────────────────────

class GraphType(str, Enum):
    bar = "bar"; line = "line"; pie = "pie"
    scatter = "scatter"; histogram = "histogram"; box = "box"

class GraphDefinition(BaseModel):
    title: str; description: str; graph_type: GraphType
    x_axis_column: Optional[str] = None; y_axis_column: Optional[str] = None
    category_column: Optional[str] = None; aggregation: Optional[str] = None

class AnalysisPlan(BaseModel):
    summary: str; proposed_graphs: List[GraphDefinition]

class GraphDataPoint(BaseModel):
    label: Union[str, float, int]; value: Union[str, float, int, List[float]]
    group: Optional[str] = None

class GraphOutput(BaseModel):
    id: str; title: str; description: str; graph_type: GraphType
    x_label: str; y_label: str; data: List[GraphDataPoint]

class FinalAnalysisOutput(BaseModel):
    file_name: str; generated_at: str; graphs: List[GraphOutput]

class DatasetMetadata(BaseModel):
    file_path: str; columns: List[str]
    sample_data: List[Dict[str, Any]]; column_types: Dict[str, str]