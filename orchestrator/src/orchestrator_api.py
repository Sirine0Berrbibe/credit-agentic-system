"""
FastAPI Integration — Orchestrator LangGraph
Routes:
  POST /credit/preview   → Flux A (client, avant soumission)
  POST /credit/decision  → Flux B (complet, conseiller/admin)
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime
import uuid

from config.settings import get_config
from src.state import CreditApplicationState
from src.orchestrator_graph import OrchestratorGraph, create_orchestrator
from src.agents.scoring_agent import FeatureStore
from src.infrastructure import get_infra_manager
from src.llm_client import AzureOpenAIClient
from src.langsmith_tracing import (
    annotate_current_run,
    build_trace_metadata,
    build_trace_tags,
    process_trace_inputs,
    process_trace_outputs,
    traceable,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ════════════════════════════════════════════════════════════════════════════

class CreditApplicationRequest(BaseModel):
    """Requête Flux B — décision complète (conseiller / admin)"""
    client_id: str = Field(..., description="ID unique du client")
    client_data: Dict[str, Any] = Field(..., description="Données du client")

    class Config:
        json_schema_extra = {
            "example": {
                "client_id": "CLIENT_12345",
                "client_data": {
                    "credit_type": "auto",
                    "loan_amount": 40000,
                    "monthly_salary": 2200,
                    "monthly_payment": 650,
                    "client_age": 34,
                    "employment_status": "salarie_prive",
                    "seniority_years": 3,
                    "debt_ratio": 0.30,
                    "cr_bct_class": 0,
                    "on_sanctions_list": False,
                    "AMT_INCOME_TOTAL": 26400,
                    "AMT_CREDIT": 40000,
                    "AMT_ANNUITY": 650,
                    "DAYS_BIRTH": -12410,
                    "DAYS_EMPLOYED": -1095,
                },
            }
        }


class ScorePreviewRequest(BaseModel):
    """Requête Flux A — simulation avant soumission officielle"""
    client_id: str = Field(..., description="ID unique du client")
    client_data: Dict[str, Any] = Field(..., description="Données du client (simplifiées)")

    class Config:
        json_schema_extra = {
            "example": {
                "client_id": "CLIENT_12345",
                "client_data": {
                    "credit_type": "consommation",
                    "loan_amount": 15000,
                    "monthly_salary": 1800,
                    "client_age": 30,
                    "employment_status": "salarie_public",
                    "debt_ratio": 0.25,
                },
            }
        }


# ════════════════════════════════════════════════════════════════════════════
# RESPONSE MODELS
# ════════════════════════════════════════════════════════════════════════════

class ScorePreviewResponse(BaseModel):
    """Réponse Flux A — orientée client, pas de PD brut si zone grise"""
    application_id: str
    client_id: str
    flux_type: str = "preview"
    cached: bool = False

    # Décision client-friendly
    status: str           # "FAVORABLE" | "APPROFONDIE_REQUISE" | "DEFAVORABLE"
    message: str          # Explication naturelle (langage client)
    next_action: str

    # XAI client (sans PD brut si zone grise)
    top_factors: List[Dict[str, Any]]       # masqué si zone grise
    recommendations: List[str]              # actions actionnables

    # Metadata
    guarantee_ready: bool
    missing_documents: List[str]
    processing_time_ms: float
    created_at: str


class CreditDecisionResponse(BaseModel):
    """Réponse Flux B — complète pour conseiller / comité"""
    application_id: str
    client_id: str
    flux_type: str = "full"

    # Décision finale
    final_decision: str           # APPROVE | REJECT | REVIEW_REQUIRED | BLOCKED
    decision_summary: str
    next_action: Optional[str]

    # Documents
    guarantee_ready_for_scoring: bool
    missing_documents: List[str]
    document_issues: Dict[str, List[str]]
    frontend_messages: List[str]
    frontend_payload: Dict[str, Any]

    # Scoring (pro)
    pd_score: float
    pd_confidence: float
    risk_band: str
    in_grey_zone: bool

    # Policy (pro)
    rule_id: str
    recommended_product: Optional[str]
    product_terms: Optional[Dict[str, Any]]

    # XAI (pro)
    shap_values: Dict[str, float]
    top_factors: List[Dict[str, Any]]
    counterfactuals: List[Dict[str, Any]]
    explanation: str

    # Fraud (pro)
    fraud_risk_score: float
    is_application_blocked: bool
    fraud_anomaly_type: Optional[str]

    # Human-in-the-loop
    human_review_required: bool
    human_review_reasons: List[str]

    # Audit
    processing_time_ms: float
    created_at: str
    audit_trail_length: int


# ════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR API
# ════════════════════════════════════════════════════════════════════════════

class OrchestratorAPI:
    def __init__(self):
        self.orchestrator: Optional[OrchestratorGraph] = None
        self.llm_client: Optional[AzureOpenAIClient] = None
        self.feature_store: Optional[FeatureStore] = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        config = get_config()
        infra_manager = None
        try:
            infra_manager = await get_infra_manager()
            logger.info("[API] Infrastructure manager available")
        except Exception as exc:
            logger.warning("[API] Infrastructure unavailable (degraded mode): %s", exc)

        self.feature_store = FeatureStore(
            redis_client=infra_manager.redis_client if infra_manager else None,
            db_client=infra_manager.db_client if infra_manager else None,
        )

        if config.azure_openai.validate():
            self.llm_client = AzureOpenAIClient(config.azure_openai)
            logger.info("[API] Azure OpenAI configured (%s)", config.azure_openai.deployment)
        else:
            logger.warning("[API] Azure OpenAI not configured — XAI will use template fallback")

        self.orchestrator = await create_orchestrator(
            feature_store=self.feature_store,
            llm_client=self.llm_client,
            db_client=infra_manager.db_client if infra_manager else None,
            kafka_producer=infra_manager.kafka_producer if infra_manager else None,
            redis_client=infra_manager.redis_client if infra_manager else None,
        )
        self._initialized = True
        logger.info("[API] Orchestrator ready (llm=%s db=%s redis=%s kafka=%s)",
                    bool(self.llm_client),
                    bool(infra_manager and infra_manager.db_client),
                    bool(infra_manager and infra_manager.redis_client),
                    bool(infra_manager and infra_manager.kafka_producer))

    async def close(self) -> None:
        if self.llm_client:
            await self.llm_client.close()
        self.orchestrator = None
        self.feature_store = None
        self._initialized = False

    # ── Flux A — Score Preview ────────────────────────────────
    @traceable(
        name="API Score Preview",
        run_type="chain",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def score_preview(self, request: ScorePreviewRequest) -> ScorePreviewResponse:
        await self.initialize()
        client_data = dict(request.client_data)
        application_id = (
            client_data.get("application_id")
            or client_data.get("applicationId")
            or str(uuid.uuid4())
        )
        client_data.setdefault("application_id", application_id)
        client_data.setdefault("created_at", datetime.utcnow().isoformat())

        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="api",
                operation="score_preview",
                application_id=application_id,
                client_id=request.client_id,
                flux_type="preview",
                env=get_config().env.value,
            ),
            tags=build_trace_tags("api", "preview", "credit"),
        )

        state: CreditApplicationState = await self.orchestrator.process_application(
            client_id=request.client_id,
            client_data=client_data,
            flux_type="preview",
        )

        pd = state["final_pd_score"]
        in_grey = state.get("in_grey_zone") or (0.35 <= pd <= 0.65)

        if state["final_decision"] == "APPROVE" and not in_grey:
            status = "FAVORABLE"
        elif state["final_decision"] == "REJECT":
            status = "DEFAVORABLE"
        else:
            status = "APPROFONDIE_REQUISE"

        # Top factors only if not grey zone (GDPR: don't expose internals without explanation)
        top_factors = [] if in_grey else state["xai_explanation"].get("top_factors", [])
        recommendations = [
            cf.get("action", "") for cf in state["xai_explanation"].get("counterfactuals", [])[:3]
            if cf.get("action")
        ] if not in_grey else []

        annotate_current_run(
            metadata={
                "final_decision": state.get("final_decision"),
                "score_preview_cached": state.get("score_preview_cached", False),
                "human_review_required": state.get("human_review_required", False),
            }
        )

        return ScorePreviewResponse(
            application_id=state["application_id"],
            client_id=state["client_id"],
            cached=state.get("score_preview_cached", False),
            status=status,
            message=state["xai_explanation"].get("natural_explanation", state["decision_summary"]),
            next_action=state.get("next_action", ""),
            top_factors=top_factors,
            recommendations=recommendations,
            guarantee_ready=state.get("guarantee_ready_for_scoring", False),
            missing_documents=state.get("missing_documents", []),
            processing_time_ms=state.get("total_processing_time_ms", 0.0),
            created_at=state.get("created_at", datetime.utcnow().isoformat()),
        )

    # ── Flux B — Full Decision ────────────────────────────────
    @traceable(
        name="API Full Decision",
        run_type="chain",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def full_decision(self, request: CreditApplicationRequest) -> CreditDecisionResponse:
        await self.initialize()
        client_data = dict(request.client_data)
        application_id = (
            client_data.get("application_id")
            or client_data.get("applicationId")
            or str(uuid.uuid4())
        )
        client_data.setdefault("application_id", application_id)
        client_data.setdefault("created_at", datetime.utcnow().isoformat())

        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="api",
                operation="full_decision",
                application_id=application_id,
                client_id=request.client_id,
                flux_type="full",
                env=get_config().env.value,
            ),
            tags=build_trace_tags("api", "full", "credit"),
        )

        state: CreditApplicationState = await self.orchestrator.process_application(
            client_id=request.client_id,
            client_data=client_data,
            flux_type="full",
        )

        fraud = state.get("fraud_analysis") or {}
        policy = state.get("policy_decision", {})
        xai = state.get("xai_explanation", {})

        annotate_current_run(
            metadata={
                "final_decision": state.get("final_decision"),
                "risk_band": state.get("risk_band"),
                "human_review_required": state.get("human_review_required", False),
                "is_application_blocked": state.get("is_application_blocked", False),
            }
        )

        return CreditDecisionResponse(
            application_id=state["application_id"],
            client_id=state["client_id"],
            final_decision=state["final_decision"],
            decision_summary=state["decision_summary"],
            next_action=state.get("next_action"),
            guarantee_ready_for_scoring=state.get("guarantee_ready_for_scoring", False),
            missing_documents=state.get("missing_documents", []),
            document_issues=state.get("guarantee_analysis", {}).get("document_issues", {}),
            frontend_messages=state.get("frontend_messages", []),
            frontend_payload=state.get("frontend_payload", {}),
            pd_score=state["final_pd_score"],
            pd_confidence=state["pd_confidence"],
            risk_band=state["risk_band"],
            in_grey_zone=state.get("in_grey_zone", False),
            rule_id=policy.get("rule_id", ""),
            recommended_product=policy.get("recommended_product"),
            product_terms=policy.get("product_terms"),
            shap_values=xai.get("shap_values", {}),
            top_factors=xai.get("top_factors", []),
            counterfactuals=xai.get("counterfactuals", []),
            explanation=xai.get("natural_explanation", ""),
            fraud_risk_score=fraud.get("fraud_risk_score", 0.0),
            is_application_blocked=state.get("is_application_blocked", False),
            fraud_anomaly_type=fraud.get("anomaly_type"),
            human_review_required=state.get("human_review_required", False),
            human_review_reasons=state.get("human_review_reasons", []),
            processing_time_ms=state.get("total_processing_time_ms", 0.0),
            created_at=state.get("created_at", datetime.utcnow().isoformat()),
            audit_trail_length=len(state.get("audit_trail", [])),
        )


# ════════════════════════════════════════════════════════════════════════════
# SETUP ROUTES
# ════════════════════════════════════════════════════════════════════════════

api = OrchestratorAPI()


def setup_orchestrator_routes(app: FastAPI) -> None:

    @app.post(
        "/credit/preview",
        response_model=ScorePreviewResponse,
        summary="Simulation score (Flux A — client avant soumission)",
        tags=["Credit — Flux A"],
    )
    async def credit_preview(request: ScorePreviewRequest):
        """
        **Flux A — Score Preview (mode client)**

        Exécute : guarantee-agent → scoring-agent → xai-agent (mode client)
        - Pas de policy-agent ni fraud-agent
        - Si zone grise (0,35 ≤ PD ≤ 0,65) : réponse générique sans score brut
        - Score preview mis en cache Redis 24h (invalidé si le dossier change)
        """
        try:
            return await api.score_preview(request)
        except Exception as exc:
            logger.error("[API] /credit/preview error: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post(
        "/credit/decision",
        response_model=CreditDecisionResponse,
        summary="Décision complète (Flux B — conseiller / admin)",
        tags=["Credit — Flux B"],
    )
    async def credit_decision(request: CreditApplicationRequest):
        """
        **Flux B — Décision complète (mode pro)**

        Exécute : guarantee-agent → scoring-agent → policy-agent → xai-agent (pro)
                  + fraud-agent en parallèle

        - Si zone grise : escalade human-in-the-loop vers conseiller
        - XAI : SHAP values brutes, PD, counterfactuels, référence audit log
        - Fraud : Isolation Forest + velocity check + cohérence documentaire
        """
        try:
            return await api.full_decision(request)
        except Exception as exc:
            logger.error("[API] /credit/decision error: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get(
        "/orchestrator/health",
        tags=["Orchestrator"],
        summary="Health check orchestrator",
    )
    async def orchestrator_health():
        return {
            "status": "healthy",
            "service": "orchestrator_langgraph",
            "agents": {
                "guarantee_a": "active",
                "scoring_b": "active",
                "policy_c": "active (RAG+FAISS+GPT-4.1)",
                "xai_d": "active (client+pro modes)",
                "fraud_e": "active (IsolationForest+velocity)",
            },
            "flux": {
                "A_preview": "guarantee → scoring → xai(client)",
                "B_full": "guarantee → scoring → policy → xai(pro) + fraud(parallel)",
            },
            "initialized": api._initialized,
            "dependencies": {
                "llm": api.llm_client is not None,
                "feature_store": api.feature_store is not None,
                "db": bool(api.orchestrator and api.orchestrator.db_client),
                "redis": bool(api.orchestrator and api.orchestrator.redis_client),
                "kafka": bool(api.orchestrator and api.orchestrator.kafka_producer),
            },
        }

    logger.info("[API] Orchestrator routes registered (preview + decision)")
