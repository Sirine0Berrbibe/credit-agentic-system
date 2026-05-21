"""
Agent Pipeline Stream Router
SSE endpoints for real-time visualization of the credit agent pipeline.

  POST /api/credit/analyze-stream   → demo simulation (no real agents)
  POST /api/credit/preview-stream   → Flux A real pipeline with SSE
  POST /api/credit/decision-stream  → Flux B real pipeline with SSE
  GET  /api/credit/audit/{id}/trace → reconstruct agent trace from audit log
"""
import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/credit", tags=["agent-stream"])


class DossierRequest(BaseModel):
    client_id: str = Field(default="demo-client-001")
    data: Dict[str, Any] = Field(default_factory=dict)


def _sse(data: Dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _pipeline_stream(dossier: Dict[str, Any]) -> AsyncGenerator[str, None]:
    """
    Simulates the full agent pipeline with realistic async delays.

    Execution order:
      Phase 1 (parallel): GuaranteeAgent ║ FraudAgent
      Phase 2:            ScoringAgent   (after GuaranteeAgent)
      Phase 3:            PolicyAgent    (after ScoringAgent)
      Phase 4:            XAIAgent       (after PolicyAgent)
      Final:              FINAL_DECISION
    """
    client_id = dossier.get("client_id", "unknown")
    logger.info("SSE pipeline started for client=%s", client_id)

    await asyncio.sleep(0.3)

    # ── Phase 1: parallel ──────────────────────────────────────────────
    yield _sse({"agent": "GuaranteeAgent", "status": "running",
                "duration_ms": None, "summary": None, "rule_id": None, "fallback_reason": None})
    await asyncio.sleep(0.12)
    yield _sse({"agent": "FraudAgent", "status": "running",
                "duration_ms": None, "summary": None, "rule_id": None, "fallback_reason": None})

    # GuaranteeAgent finishes at ~1.9s
    await asyncio.sleep(1.78)
    yield _sse({"agent": "GuaranteeAgent", "status": "done", "duration_ms": 1820,
                "summary": "doc_quality: 0.87 — 4 docs validés", "rule_id": None, "fallback_reason": None})

    # FraudAgent finishes ~0.35s later
    await asyncio.sleep(0.35)
    yield _sse({"agent": "FraudAgent", "status": "done", "duration_ms": 2190,
                "summary": "fraud_score: 0.03 — Aucune anomalie détectée", "rule_id": None, "fallback_reason": None})

    # ── Phase 2: ScoringAgent ──────────────────────────────────────────
    await asyncio.sleep(0.45)
    yield _sse({"agent": "ScoringAgent", "status": "running",
                "duration_ms": None, "summary": None, "rule_id": None, "fallback_reason": None})

    await asyncio.sleep(2.2)
    yield _sse({"agent": "ScoringAgent", "status": "done", "duration_ms": 2230,
                "summary": "PD: 0.231 — Band: LOW — Confidence: 0.89", "rule_id": None, "fallback_reason": None})

    # ── Phase 3: PolicyAgent ───────────────────────────────────────────
    await asyncio.sleep(0.4)
    yield _sse({"agent": "PolicyAgent", "status": "running",
                "duration_ms": None, "summary": None, "rule_id": None, "fallback_reason": None})

    await asyncio.sleep(1.3)
    yield _sse({"agent": "PolicyAgent", "status": "done", "duration_ms": 1320,
                "summary": "APPROVE — Crédit Auto 60 mois @ 4.5%", "rule_id": "BCT-LTI-001", "fallback_reason": None})

    # ── Phase 4: XAIAgent ─────────────────────────────────────────────
    await asyncio.sleep(0.4)
    yield _sse({"agent": "XAIAgent", "status": "running",
                "duration_ms": None, "summary": None, "rule_id": None, "fallback_reason": None})

    await asyncio.sleep(1.85)
    yield _sse({"agent": "XAIAgent", "status": "done", "duration_ms": 1870,
                "summary": "3 facteurs clés — 2 contrefactuels générés", "rule_id": None, "fallback_reason": None})

    # ── Final Decision ─────────────────────────────────────────────────
    await asyncio.sleep(0.3)
    yield _sse({
        "agent": "FINAL_DECISION",
        "decision": "APPROVED",
        "confidence": 0.91,
        "pd_score": 0.231,
        "main_reason": "Dossier complet, score dans la zone verte, conformité BCT validée",
    })

    logger.info("SSE pipeline completed for client=%s", client_id)


# ────────────────────────────────────────────────────────────────────
# Real pipeline SSE endpoints
# ────────────────────────────────────────────────────────────────────

class RealStreamRequest(BaseModel):
    client_id: str = Field(default="demo-client-001")
    client_data: Dict[str, Any] = Field(default_factory=dict)


async def _real_pipeline_stream(
    client_id: str,
    client_data: Dict[str, Any],
    flux_type: str,
) -> AsyncGenerator[str, None]:
    """Connect to the real OrchestratorGraph and yield SSE events."""
    try:
        from .orchestrator_api import api as langgraph_api
        await langgraph_api.initialize()
        orchestrator = langgraph_api.orchestrator
    except Exception as exc:
        logger.error("Orchestrator unavailable for stream: %s", exc)
        yield _sse({"agent": "FINAL_DECISION", "decision": "HUMAN_REVIEW",
                    "confidence": 0.0, "pd_score": 0.0,
                    "main_reason": f"Orchestrateur indisponible: {exc}"})
        return

    queue: asyncio.Queue = asyncio.Queue()

    async def _run():
        try:
            await orchestrator.stream_application(client_id, client_data, flux_type, queue)
        except Exception as exc:
            logger.error("stream_application failed: %s", exc)
            await queue.put(None)

    task = asyncio.create_task(_run())

    try:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=120)
            if event is None:
                break
            yield _sse(event)
    except asyncio.TimeoutError:
        logger.error("Pipeline stream timed out")
        yield _sse({"agent": "FINAL_DECISION", "decision": "HUMAN_REVIEW",
                    "confidence": 0.0, "pd_score": 0.0,
                    "main_reason": "Timeout — pipeline dépassé 120s"})
    finally:
        if not task.done():
            task.cancel()


@router.post("/preview-stream", summary="Flux A real pipeline via SSE")
async def preview_stream(req: RealStreamRequest) -> StreamingResponse:
    """
    Runs the real Flux A credit pipeline (GuaranteeAgent → ScoringAgent → XAIAgent)
    and streams each agent status as a Server-Sent Event.
    """
    logger.info("SSE preview-stream for client=%s", req.client_id)
    return StreamingResponse(
        _real_pipeline_stream(req.client_id, req.client_data, "preview"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


@router.post("/decision-stream", summary="Flux B real pipeline via SSE")
async def decision_stream(req: RealStreamRequest) -> StreamingResponse:
    """
    Runs the real Flux B credit pipeline (all 5 agents) and streams each
    agent status as a Server-Sent Event.
    """
    logger.info("SSE decision-stream for client=%s", req.client_id)
    return StreamingResponse(
        _real_pipeline_stream(req.client_id, req.client_data, "full"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


# ────────────────────────────────────────────────────────────────────
# Audit trace reconstruction (admin use)
# ────────────────────────────────────────────────────────────────────

@router.get("/audit/{application_id}/trace", summary="Reconstruct agent trace from audit log")
async def get_agent_trace(application_id: str):
    """
    Returns a reconstructed per-agent execution trace from the stored audit log
    entry for the given application.  Used by the admin Pipeline IA view.
    """
    try:
        from .orchestrator_api import api as langgraph_api
        await langgraph_api.initialize()
        db = langgraph_api.orchestrator.db_client
        if db is None:
            raise HTTPException(status_code=503, detail="DB not available")
        row = await db.get_audit_log_by_application(application_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Audit log not found")
        return _reconstruct_trace(row)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to fetch audit trace: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _reconstruct_trace(row: Dict[str, Any]) -> Dict[str, Any]:
    """Build a pipeline trace dict from an audit log row."""
    agents = []

    # GuaranteeAgent — always present if scoring ran
    dq = row.get("document_quality_score") or row.get("doc_quality")
    agents.append({
        "name": "GuaranteeAgent", "label": "Guarantee Agent",
        "status": "done" if row.get("pd_score") is not None else "skipped",
        "summary": f"doc_quality: {dq:.2f}" if dq is not None else None,
        "rule_id": None, "fallback_reason": None, "duration_ms": None,
    })

    # FraudAgent
    fraud = row.get("fraud_risk_score")
    agents.append({
        "name": "FraudAgent", "label": "Fraud Detection",
        "status": "done" if fraud is not None else "skipped",
        "summary": f"fraud_score: {fraud:.3f}" if fraud is not None else None,
        "rule_id": None, "fallback_reason": None, "duration_ms": None,
    })

    # ScoringAgent
    pd_score = row.get("pd_score")
    risk_band = row.get("risk_band")
    pd_conf = row.get("pd_confidence")
    agents.append({
        "name": "ScoringAgent", "label": "Scoring Agent",
        "status": "done" if pd_score is not None else "skipped",
        "summary": (
            f"PD: {pd_score:.3f} — Band: {risk_band or '?'}"
            + (f" — Conf: {pd_conf:.2f}" if pd_conf is not None else "")
        ) if pd_score is not None else None,
        "rule_id": None, "fallback_reason": None, "duration_ms": None,
    })

    # PolicyAgent
    rule = row.get("rule_applied")
    agents.append({
        "name": "PolicyAgent", "label": "Policy Agent",
        "status": "done" if rule else "skipped",
        "summary": f"Decision: {row.get('decision', '?')}" if rule else None,
        "rule_id": rule,
        "fallback_reason": None, "duration_ms": None,
    })

    # XAIAgent
    summary_text = row.get("decision_summary")
    agents.append({
        "name": "XAIAgent", "label": "XAI Explainability",
        "status": "done" if summary_text else "skipped",
        "summary": (summary_text[:80] + "…") if summary_text and len(summary_text) > 80
                   else summary_text,
        "rule_id": None, "fallback_reason": None, "duration_ms": None,
    })

    _dec_map = {"APPROVE": "APPROVED", "REJECT": "REJECTED"}
    raw_dec = (row.get("decision") or "REVIEW_REQUIRED").upper()
    return {
        "application_id": row.get("application_id") or row.get("applicationId"),
        "application_reference": row.get("application_reference") or row.get("applicationReference"),
        "client_id": row.get("client_id") or row.get("clientId"),
        "credit_type": row.get("credit_type") or row.get("creditType"),
        "created_at": row.get("created_at") or row.get("createdAt"),
        "agents": agents,
        "final_decision": {
            "decision": _dec_map.get(raw_dec, "HUMAN_REVIEW"),
            "confidence": round(float(row.get("pd_confidence") or 0), 4),
            "pd_score": round(float(row.get("pd_score") or 0), 4),
            "main_reason": row.get("decision_summary") or "",
        },
    }


# ────────────────────────────────────────────────────────────────────
# Demo simulation endpoint (kept for standalone testing)
# ────────────────────────────────────────────────────────────────────

@router.post("/analyze-stream", summary="Stream agent pipeline via SSE")
async def analyze_stream(dossier: DossierRequest) -> StreamingResponse:
    """
    Returns a text/event-stream response where each SSE event is a JSON object
    representing an agent status update or the final credit decision.
    """
    return StreamingResponse(
        _pipeline_stream(dossier.model_dump()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
