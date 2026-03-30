"""
engine.py — The public interface of sYsLens v2.

FIXED (Limitation 10 — No input length guard):
  Inputs longer than MAX_INPUT_CHARS are truncated before dispatch.
  Uses model_copy() so the original request object is never mutated.
"""

from __future__ import annotations
import base64
import hashlib
import logging
import traceback
from collections import OrderedDict
from typing import Callable, Optional

import plotly.graph_objects as go

from .models import AnalysisRequest, AnalysisResult, AgentMode
from .config import settings
from .memory.session import get_session, clear_session
from .utils import build_file_fingerprint
from .project_agents.router_agent import RouterAgent
from .project_agents.analyst_agent import AnalystAgent
from .project_agents.graph_agent import GraphAgent
from .project_agents.knowledge_agent import KnowledgeAgent
from .project_agents.vision_agent import VisionAgent
from .project_agents.pdf_agent import PdfAgent
from .project_agents.ocr_agent import OcrAgent
from .project_agents.greeting_agent import GreetingAgent
from .visualizations.kpi_builder import extract_kpis
from .visualizations.plotly_factory import build as build_figure

logger = logging.getLogger("syslens.engine")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

MAX_INPUT_CHARS = 8_000


class _FigureCache:
    def __init__(self, maxsize: int = 32):
        self._cache: OrderedDict[str, go.Figure] = OrderedDict()
        self._maxsize = maxsize

    def _key(self, spec_json: str) -> str:
        return hashlib.md5(spec_json.encode()).hexdigest()

    def get(self, spec_json: str) -> Optional[go.Figure]:
        key = self._key(spec_json)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, spec_json: str, fig: go.Figure) -> None:
        key = self._key(spec_json)
        self._cache[key] = fig
        self._cache.move_to_end(key)
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()


def _validate_result(result: AnalysisResult, mode: AgentMode, query: str) -> AnalysisResult:
    """
    Validation layer — ensures results have renderable data before reaching the UI.

    IMPORTANT: This never silently redirects to KnowledgeAgent.
    If data is missing, raise ValueError with a helpful user-facing message.
    Redirecting causes wrong chart types (sunburst for everything).
    """
    import math
    from .models import ChartType, ChartSeries

    # Greeting has no spec — already handled upstream
    if result.spec is None:
        return result

    spec = result.spec

    # Hierarchy charts — just check labels exist
    if spec.chart_type in (ChartType.SUNBURST, ChartType.TREEMAP):
        s = spec.series[0] if spec.series else None
        if not s or not s.labels or len(s.labels) < 2:
            raise ValueError(
                f"Knowledge map for '{query[:60]}' returned no nodes. "
                "Try rephrasing your question."
            )
        return result

    # Regular charts — check at least one series has real numbers
    def has_data(s: ChartSeries) -> bool:
        if not s.y:
            return False
        return any(
            v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))
            for v in s.y
        )

    valid_series = [s for s in spec.series if has_data(s)]

    if not valid_series:
        raise ValueError(
            f"No numeric data could be extracted for: '{query[:80]}'. "
            "Paste your data directly (e.g. 'Apple: $394B, Google: $282B') "
            "or upload a CSV/Excel file."
        )

    # Trim to only valid series — don't discard entire result
    if len(valid_series) < len(spec.series):
        result.spec.series = valid_series

    return result


class SyslensEngine:
    def __init__(self):
        self._router    = RouterAgent()
        self._analyst   = AnalystAgent()
        self._graph     = GraphAgent()
        self._knowledge = KnowledgeAgent()
        self._vision    = VisionAgent()
        self._pdf       = PdfAgent()
        self._ocr       = OcrAgent()
        self._greeting  = GreetingAgent()
        self._cache     = _FigureCache(maxsize=settings.FIGURE_CACHE_SIZE)

    def analyze(
        self,
        request: AnalysisRequest,
        progress_cb: Callable[[str], None] | None = None,
    ) -> AnalysisResult:

        def log(msg: str):
            logger.info(msg)
            if progress_cb:
                progress_cb(msg)

        session_id = request.session_id or "default"
        session    = get_session(session_id)
        ctx        = session.get_context()

        # FIX: input length guard — truncate before sending to any agent
        if request.text and len(request.text) > MAX_INPUT_CHARS:
            log(f"Input truncated: {len(request.text)} -> {MAX_INPUT_CHARS} chars")
            request = request.model_copy(update={"text": request.text[:MAX_INPUT_CHARS]})

        has_file  = bool(request.file_bytes and request.filename)
        has_image = bool(request.image_bytes)

        mode = self._router.route(
            text      = request.text,
            ctx       = ctx,
            has_file  = has_file,
            has_image = has_image,
            filename  = request.filename or "",
        )
        log(f"[{session_id}] mode={mode.value}")

        try:
            result = self._dispatch(mode, request, ctx, log)
        except Exception as exc:
            logger.error(
                f"[{session_id}] Agent dispatch FAILED -- mode={mode.value}\n"
                f"{traceback.format_exc()}"
            )
            raise

        # ── Greeting mode: skip all chart processing ────────────────────────
        if mode == AgentMode.GREETING:
            session.add_turn("user", request.text or "[greeting]", mode=mode.value)
            session.add_turn("assistant", result.insight or "Hello!", mode=mode.value)
            return result

        # ── Validation layer ─────────────────────────────────────────────────
        # Skip for modes that produce their own guaranteed valid output:
        #   VISION      → vision_agent already parsed image into chart spec
        #   OCR_IMAGE   → ocr_agent extracted text then ran analyst
        #   FILE_ANALYSIS → graph_agent ran sandbox code, got explicit output
        #   PDF         → pdf_agent extracted structured content
        # Running _validate_result on these would wrongly redirect to knowledge_map
        # because the query text ("Visualize this image") triggers the >6-word heuristic.
        _skip_validation = {
            AgentMode.VISION, AgentMode.OCR_IMAGE,
            AgentMode.FILE_ANALYSIS, AgentMode.PDF,
        }
        if mode not in _skip_validation:
            result = _validate_result(result, mode, request.text)

        if not result.kpis:
            log("Extracting KPIs...")
            try:
                result.kpis = extract_kpis(result)
                log(f"Extracted {len(result.kpis)} KPIs")
            except Exception as e:
                log(f"KPI extraction skipped: {e}")

        spec_json = result.spec.model_dump_json()
        if not self._cache.get(spec_json):
            fig = build_figure(result.spec)
            self._cache.put(spec_json, fig)

        session.add_turn("user",      request.text or f"[{mode.value}]", mode=mode.value)
        session.add_turn("assistant", result.insight or "Visualization ready.", mode=mode.value)
        session.set_last_result(result)

        return result

    def get_figure(self, result: AnalysisResult) -> go.Figure:
        if result.spec is None:
            return go.Figure()
        spec_json = result.spec.model_dump_json()
        fig = self._cache.get(spec_json)
        if fig is None:
            fig = build_figure(result.spec)
            self._cache.put(spec_json, fig)
        return fig

    def clear_session(self, session_id: str = "default") -> None:
        clear_session(session_id)

    def clear_cache(self) -> None:
        self._cache.clear()

    def _dispatch(self, mode, request, ctx, log) -> AnalysisResult:
        if mode == AgentMode.GREETING:
            log("GreetingAgent: conversational response")
            return self._greeting.run(request.text, ctx)

        if mode == AgentMode.DIRECT_DATA:
            log("AnalystAgent: extracting from text")
            return self._analyst.run(request.text, ctx)

        if mode == AgentMode.KNOWLEDGE_MAP:
            log("KnowledgeAgent: building concept hierarchy")
            return self._knowledge.run(request.text, ctx)

        if mode == AgentMode.VISION:
            if not request.image_bytes:
                raise ValueError("Vision mode requires an uploaded image.")
            log("VisionAgent: LLM reading image")
            image_b64  = base64.b64encode(request.image_bytes).decode()
            media_type = request.image_type or "image/png"
            return self._vision.run(request.text, image_b64, media_type, ctx)

        if mode == AgentMode.OCR_IMAGE:
            if not request.image_bytes:
                raise ValueError("OCR mode requires an uploaded image.")
            log("OcrAgent: Tesseract extracting text from image")
            return self._ocr.run(request.image_bytes, request.text, ctx)

        if mode == AgentMode.PDF:
            if not request.file_bytes:
                raise ValueError("PDF mode requires file_bytes.")
            log(f"PdfAgent: extracting from PDF '{request.filename}'")
            return self._pdf.run(request.file_bytes, request.text, ctx)

        if mode == AgentMode.FILE_ANALYSIS:
            if not request.file_bytes or not request.filename:
                raise ValueError("File analysis requires file_bytes and filename.")
            log(f"GraphAgent: analysing '{request.filename}'")
            fingerprint = build_file_fingerprint(request.file_bytes, request.filename)
            return self._graph.run(
                text        = request.text,
                file_bytes  = request.file_bytes,
                filename    = request.filename,
                fingerprint = fingerprint,
                ctx         = ctx,
                progress_cb = log,
            )

        if mode == AgentMode.FOLLOWUP:
            last = ctx.last_result
            if not last:
                log("No previous result -- falling back to AnalystAgent")
                return self._analyst.run(request.text, ctx)
            log(f"FollowUp: modifying previous {last.mode} visualization")
            last_mode = AgentMode(last.mode)
            if last_mode == AgentMode.KNOWLEDGE_MAP:
                return self._knowledge.run_followup(request.text, last, ctx)
            return self._analyst.run_followup(request.text, last, ctx)

        raise ValueError(f"Unknown agent mode: {mode}")