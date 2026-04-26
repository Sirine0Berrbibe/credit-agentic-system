"""
FastAPI Integration — Nouvelle endpoint pour orchestrator LangGraph
Route: POST /credit/decision (version 2 avec LangGraph)
Expose l'orchestrator à 5 agents via REST API
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import asyncio
import logging
from datetime import datetime

from config.settings import get_config
from src.state import CreditApplicationState
from src.orchestrator_graph import OrchestratorGraph, create_orchestrator
from src.agents.scoring_agent import FeatureStore
from src.infrastructure import get_infra_manager
from src.llm_client import AzureOpenAIClient

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ════════════════════════════════════════════════════════════════════════════


class CreditApplicationRequest(BaseModel):
    """Requête de demande de crédit"""

    client_id: str = Field(..., description="ID unique du client")
    client_data: Dict[str, Any] = Field(
        ..., description="Données du client du formulaire"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "client_id": "CLIENT_12345",
                "client_data": {
                    "AMT_INCOME_TOTAL": 300000,
                    "AMT_CREDIT": 100000,
                    "AMT_ANNUITY": 25000,
                    "DAYS_BIRTH": -16000,
                    "DAYS_EMPLOYED": -3000,
                    "CODE_GENDER": 0,
                },
            }
        }


class ScoringIterationResponse(BaseModel):
    """Détail d'une itération du Scoring Agent"""

    iteration: int
    pd_score: float
    confidence: float
    risk_band: str
    missing_features: List[str]


class XAIExplanationResponse(BaseModel):
    """Explication XAI pour le client"""

    top_factors: List[Dict[str, Any]]
    counterfactuals: List[Dict[str, Any]]
    natural_explanation: str


class CreditDecisionResponse(BaseModel):
    """Réponse complète d'une décision de crédit"""

    application_id: str
    client_id: str
    final_decision: str  # "APPROVE", "REJECT", "REVIEW_REQUIRED", "BLOCKED"
    decision_summary: str
    next_action: Optional[str]
    guarantee_ready_for_scoring: bool
    missing_documents: List[str]
    document_issues: Dict[str, List[str]]
    frontend_messages: List[str]
    frontend_payload: Dict[str, Any]

    # Scoring Results
    pd_score: float = Field(description="Probability of Default")
    pd_confidence: float = Field(description="Confiance du score PD")
    risk_band: str = Field(description="BAS, MODERE, ELEVE, CRITIQUE")

    # Policy Results
    rule_id: str = Field(description="ID de la règle qui a décidé")
    recommended_product: Optional[str]

    # XAI Results
    top_factors: List[Dict[str, Any]]
    counterfactuals: List[Dict[str, Any]]
    explanation: str

    # Fraud Results
    fraud_risk_score: float
    is_application_blocked: bool

    # Metadata
    processing_time_ms: float
    created_at: str
    audit_trail_length: int = Field(description="Nombre d'événements dans l'audit trail")

    class Config:
        json_schema_extra = {
            "example": {
                "application_id": "APP_abc123",
                "client_id": "CLIENT_12345",
                "final_decision": "APPROVE",
                "decision_summary": "✓ Demande approuvée",
                "next_action": "Attendez contact de notre équipe",
                "pd_score": 0.25,
                "pd_confidence": 0.95,
                "risk_band": "BAS",
                "rule_id": "SCORE_LOW_RISK",
                "recommended_product": "Crédit Auto",
                "top_factors": [
                    {
                        "feature": "EXT_SOURCE_MEAN",
                        "shap_value": 0.35,
                        "impact": "reduit_risque",
                    }
                ],
                "counterfactuals": [
                    {
                        "feature": "AMT_INCOME_TOTAL",
                        "action": "Augmenter de 20%",
                        "impact": "APPROBATION",
                    }
                ],
                "explanation": "Votre profil est solide...",
                "fraud_risk_score": 0.12,
                "is_application_blocked": False,
                "processing_time_ms": 2340.5,
                "created_at": "2026-04-10T15:30:00Z",
                "audit_trail_length": 8,
            }
        }


# ════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR ENDPOINT
# ════════════════════════════════════════════════════════════════════════════


class OrchestratorAPI:
    """
    Wrapper pour intégrer OrchestratorGraph dans FastAPI
    """

    def __init__(self):
        self.orchestrator: Optional[OrchestratorGraph] = None
        self.llm_client: Optional[AzureOpenAIClient] = None
        self.feature_store: Optional[FeatureStore] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialise l'orchestrator avec dépendances"""
        if not self._initialized:
            config = get_config()

            infra_manager = None
            try:
                infra_manager = await get_infra_manager()
                logger.info("[API] Infrastructure manager available")
            except Exception as exc:
                logger.warning(
                    "[API] Infrastructure unavailable, continuing with degraded mode: %s",
                    exc,
                )

            self.feature_store = FeatureStore(
                redis_client=infra_manager.redis_client if infra_manager else None,
                db_client=infra_manager.db_client if infra_manager else None,
            )

            if config.azure_openai.validate():
                self.llm_client = AzureOpenAIClient(config.azure_openai)
                logger.info(
                    "[API] Azure OpenAI client configured for deployment %s",
                    config.azure_openai.deployment,
                )
            else:
                logger.warning(
                    "[API] Azure OpenAI config invalid, XAI explanations will use template fallback"
                )

            self.orchestrator = await create_orchestrator(
                feature_store=self.feature_store,
                llm_client=self.llm_client,
                db_client=infra_manager.db_client if infra_manager else None,
                kafka_producer=infra_manager.kafka_producer if infra_manager else None,
            )
            self._initialized = True
            logger.info(
                "[API] Orchestrator initialized (llm=%s, db=%s, kafka=%s, redis=%s)",
                "on" if self.llm_client else "off",
                "on" if infra_manager and infra_manager.db_client else "off",
                "on" if infra_manager and infra_manager.kafka_producer else "off",
                "on" if infra_manager and infra_manager.redis_client else "off",
            )

    async def close(self) -> None:
        """Libère les ressources propres à l'API."""
        if self.llm_client:
            await self.llm_client.close()
            self.llm_client = None

        self.orchestrator = None
        self.feature_store = None
        self._initialized = False

    async def process_credit_application(
        self, request: CreditApplicationRequest
    ) -> CreditDecisionResponse:
        """
        Traite une demande de crédit via orchestrator LangGraph
        Exécute workflow complet: A→B→C→D + E async
        """

        await self.initialize()

        logger.info(
            f"[API] Processing credit application for {request.client_id}"
        )

        # Exécuter le pipeline complet
        state: CreditApplicationState = (
            await self.orchestrator.process_application(
                client_id=request.client_id,
                client_data=request.client_data,
            )
        )

        # Transformer résultat en réponse API
        response = CreditDecisionResponse(
            application_id=state["application_id"],
            client_id=state["client_id"],
            final_decision=state["final_decision"],
            decision_summary=state["decision_summary"],
            next_action=state["next_action"],
            guarantee_ready_for_scoring=state["guarantee_ready_for_scoring"],
            missing_documents=state["missing_documents"],
            document_issues=state["guarantee_analysis"].get("document_issues", {}),
            frontend_messages=state["frontend_messages"],
            frontend_payload=state.get("frontend_payload", {}),
            pd_score=state["final_pd_score"],
            pd_confidence=state["pd_confidence"],
            risk_band=state["risk_band"],
            rule_id=state["policy_decision"]["rule_id"],
            recommended_product=state["policy_decision"]["recommended_product"],
            top_factors=state["xai_explanation"]["top_factors"],
            counterfactuals=state["xai_explanation"]["counterfactuals"],
            explanation=state["xai_explanation"]["natural_explanation"],
            fraud_risk_score=(
                state["fraud_analysis"]["fraud_risk_score"]
                if state["fraud_analysis"]
                else 0.0
            ),
            is_application_blocked=state["is_application_blocked"],
            processing_time_ms=state["total_processing_time_ms"],
            created_at=state["created_at"],
            audit_trail_length=len(state["audit_trail"]),
        )

        logger.info(
            f"[API] ✓ Application {state['application_id']} completed: "
            f"{state['final_decision']}"
        )

        return response


# ════════════════════════════════════════════════════════════════════════════
# SETUP FASTAPI ROUTES
# ════════════════════════════════════════════════════════════════════════════

api = OrchestratorAPI()


def setup_orchestrator_routes(app: FastAPI) -> None:
    """
    Attach orchestrator endpoints au FastAPI app
    À appeler depuis main.py après création de l'app
    """

    @app.post(
        "/credit/decision",
        response_model=CreditDecisionResponse,
        summary="Demande de crédit via Orchestrator LangGraph",
        tags=["Credit Decisions"],
    )
    async def credit_decision_v2(request: CreditApplicationRequest):
        """
        **Endpoint principal**: Traite une demande de crédit

        Workflow exécuté:
        1. Agent B (Scoring) — ReAct avec itérations jusqu'à confiance suffisante
        2. Agent C (Policy) — RAG + Rules Engine BCT
        3. Agent D (XAI) — SHAP values + contrefactuels + explication naturelle
        4. Agent E (Fraud) — Detectionasync + anomalies + velocity check (parallèle)

        Retourne: Décision complète avec explication + audit trail GDPR

        **Exemple requête:**
        ```json
        {
          "client_id": "CLIENT_12345",
          "client_data": {
            "AMT_INCOME_TOTAL": 300000,
            "AMT_CREDIT": 100000,
            "DAYS_BIRTH": -16000,
            "CODE_GENDER": 0
          }
        }
        ```
        """
        try:
            response = await api.process_credit_application(request)
            return response
        except Exception as e:
            logger.error(f"[API] Error processing credit application: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/orchestrator/health",
        tags=["Orchestrator"],
        summary="Health check de l'orchestrator",
    )
    async def orchestrator_health():
        """Vérifie l'état de l'orchestra"""
        return {
            "status": "healthy",
            "service": "orchestrator_langgraph",
            "agents": ["INIT", "SCORING_B", "POLICY_C", "XAI_D", "FRAUD_E"],
            "initialized": api._initialized,
            "dependencies": {
                "llm": api.llm_client is not None,
                "feature_store": api.feature_store is not None,
                "db_audit": bool(
                    api.orchestrator and api.orchestrator.db_client is not None
                ),
                "kafka": bool(
                    api.orchestrator and api.orchestrator.kafka_producer is not None
                ),
            },
        }

    logger.info("[API] Orchestrator routes registered")
