"""
sYsLens v2 — FastAPI REST interface
Run: uvicorn api:app --reload --port 8000

BUGS FIXED:
  1. result.mode is already a plain str — .value raised AttributeError
  2. _engine._sessions does not exist — use engine.clear_session() instead
  3. SessionStore has no get_or_create() — use get_session() from memory module
  4. ctx.last_result.mode is already str — .value raised AttributeError
"""
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.engine import SyslensEngine
from backend.models import AnalysisRequest, AnalysisResult
from backend.memory.session import get_session

logger = logging.getLogger("syslens.api")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

app = FastAPI(
    title="sYsLens v2 API",
    description="Autonomous Data Intelligence Engine — REST interface",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_engine = SyslensEngine()


class AnalyzeRequest(BaseModel):
    text: str
    session_id: str = "default"
    filename: Optional[str] = None


class KPIOut(BaseModel):
    label: str
    value: Optional[float] = None
    formatted: Optional[str] = None
    delta: Optional[float] = None
    color: str = "cyan"


class AnalyzeResponse(BaseModel):
    mode: str
    insight: str
    chart_type: str
    title: str
    kpis: list[KPIOut]
    spec: dict


@app.get("/health")
def health():
    return {"status": "ok", "service": "sYsLens v2"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(body: AnalyzeRequest):
    try:
        request = AnalysisRequest(
            text=body.text,
            session_id=body.session_id,
            filename=body.filename,
        )
        result: AnalysisResult = _engine.analyze(request)

        kpis_out = [
            KPIOut(
                label=k.label,
                value=float(k.value) if k.value is not None else None,
                formatted=k.formatted or None,
                delta=k.delta,
                color=k.color,
            )
            for k in (result.kpis or [])
        ]

        return AnalyzeResponse(
            mode=result.mode,           # FIX: already str, no .value
            insight=result.insight,
            chart_type=result.spec.chart_type.value,
            title=result.spec.title,
            kpis=kpis_out,
            spec=result.spec.model_dump(),
        )

    except Exception as e:
        logger.exception("analyze endpoint failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/session/{session_id}")
def clear_session(session_id: str):
    _engine.clear_session(session_id)   # FIX: engine public method
    return {"cleared": session_id}


@app.get("/session/{session_id}/history")
def get_history(session_id: str):
    session = get_session(session_id)   # FIX: module-level get_session
    ctx = session.get_context()
    return {
        "session_id": session_id,
        "turn_count": len(ctx.turns),
        "last_mode": ctx.last_result.mode if ctx.last_result else None,  # FIX: already str
    }