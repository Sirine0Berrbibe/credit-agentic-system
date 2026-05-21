"""
FastAPI Microservice - Credit Decision Orchestration
Architecture agentic professionnelle exposée en tant que service
"""
import logging
import httpx
import os
import uuid
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from config.settings import get_config, Environment
try:
    from .orchestrator_legacy import (
        OrchestratorAgent,
        CreditDecisionRequest,
        CreditDecisionResponse,
    )
except Exception:
    OrchestratorAgent = None
    CreditDecisionRequest = None
    CreditDecisionResponse = None
try:
    from .agents.guarantee_agent.mcp_server.server import router as guarantee_agent_router
except Exception:
    guarantee_agent_router = None
try:
    from .agents.policy_agent.mcp_server.server import router as policy_agent_router
except Exception:
    policy_agent_router = None
from .orchestrator_api import setup_orchestrator_routes, api as langgraph_api
from .agent_stream_router import router as agent_stream_router
from .infrastructure import InfrastructureManager, get_infra_manager, shutdown_infra
from .agents.scoring_agent import ScoringAgent, FeatureStore
from .state import CreditApplicationState, DEFAULT_STATE
from .assistant_service import get_assistant_service, AssistantChatRequest, AssistantChatResponse
from .llm_chat_service import get_llm_chat_service, ChatRequest, ChatResponse
from .agent_chat_service import get_agent_chat_service, AgentChatRequest, AgentChatResponse
# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
config = get_config()


class HealthResponse(BaseModel):
    """Réponse de santé du service"""
    status: str
    uptime_seconds: int
    llm_configured: bool
    mcp_server: str
    environment: str
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    """Réponse d'erreur standardisée"""
    error: str
    details: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# State management
class AgentTestRequest(BaseModel):
    """Payload commun pour tester les agents individuellement"""
    client_id: str = Field(..., description="Identifiant unique du client")
    client_data: Dict[str, Any] = Field(..., description="Donnees client du formulaire")


class ScoringOnlyResponse(BaseModel):
    application_id: str
    client_id: str
    pd_score: float
    pd_confidence: float
    risk_band: str
    in_grey_zone: bool
    iterations: int
    requested_additional_features: Dict[str, bool]
    scoring_iterations: list
    processing_steps_completed: list
    error_messages: list


class XAIOnlyResponse(BaseModel):
    application_id: str
    client_id: str
    pd_score: float
    pd_confidence: float
    risk_band: str
    decision_preview: str
    top_factors: list
    counterfactuals: list
    explanation: str
    processing_steps_completed: list
    error_messages: list


class AppState:
    """État de l'application"""
    def __init__(self):
        self.orchestrator: Optional[Any] = None
        self.infra_manager: Optional[InfrastructureManager] = None
        self.start_time: Optional[datetime] = None
        self.request_count: int = 0


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gère le cycle de vie de l'application"""
    logger.info("Démarrage du service Orchestrator...")
    
    app_state.start_time = datetime.utcnow()
    
    # Initialiser l'infrastructure (PostgreSQL, Kafka, Redis)
    try:
        app_state.infra_manager = await get_infra_manager()
        logger.info("✓ Infrastructure initialized")
    except Exception as e:
        logger.warning(f"Infrastructure initialization warning: {e}")
        # Continue even if infrastructure fails (graceful degradation)
    
    if OrchestratorAgent is not None:
        app_state.orchestrator = OrchestratorAgent()
    else:
        app_state.orchestrator = "LANGGRAPH_READY"
        logger.warning(
            "Legacy orchestrator unavailable; continuing with LangGraph orchestrator only."
        )
    
    logger.info(f"Configuration: {config.env.value}")
    logger.info(f"LLM: {config.azure_openai.deployment}")
    logger.info(f"MCP Server: {config.mcp_server.base_url}")
    logger.info("Service Orchestrator prêt!")
    
    yield
    
    logger.info("Arrêt du service...")
    
    # Arrêter l'infrastructure
    try:
        await shutdown_infra()
    except Exception as e:
        logger.error(f"Infrastructure shutdown error: {e}")
    
    # Fermer le client LLM du nouvel orchestrateur LangGraph
    try:
        await langgraph_api.close()
    except Exception as e:
        logger.error(f"Erreur lors de la fermeture du LangGraph API: {e}")

    # Fermer le client LLM legacy
    if (
        app_state.orchestrator
        and hasattr(app_state.orchestrator, "llm_client")
        and app_state.orchestrator.llm_client
    ):
        try:
            await app_state.orchestrator.llm_client.close()
        except Exception as e:
            logger.error(f"Erreur lors de la fermeture: {e}")


# Créer l'app FastAPI
app = FastAPI(
    title="AICredits Orchestrator - Agentic Architecture",
    description="Plateforme d'orchestration multi-agent pour décisions de crédit",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS — restrict to explicit origins in non-development environments.
# Set CORS_ALLOWED_ORIGINS env var as a comma-separated list for staging/production.
_cors_env = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
if _cors_env:
    _allowed_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
elif config.env == Environment.DEVELOPMENT:
    _allowed_origins = ["*"]
else:
    _allowed_origins = [
        "http://localhost:3000",
        "http://localhost:4200",
    ]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_allowed_origins != ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

if guarantee_agent_router is not None:
    app.include_router(guarantee_agent_router)
if policy_agent_router is not None:
    app.include_router(policy_agent_router)
else:
    logger.warning("Guarantee agent routes could not be loaded into the orchestrator app.")

# Agent pipeline SSE stream
app.include_router(agent_stream_router)

# Initialize LangGraph orchestrator routes
setup_orchestrator_routes(app)

# Servir les fichiers statiques (HTML, CSS, JS)
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ============================================================================
# ROUTES FRONTEND
# ============================================================================

@app.get("/")
async def root():
    """Retourne l'interface web frontend"""
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return {"message": "Frontend not available"}


# ============================================================================
# ROUTES HEALTH & MONITORING
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Vérification de santé du service"""
    try:
        uptime = (datetime.utcnow() - app_state.start_time).total_seconds() if app_state.start_time else 0
        
        llm_configured = False
        try:
            llm_configured = config.azure_openai.validate()
        except Exception as e:
            logger.warning(f"LLM validation check failed: {e}")
        
        return HealthResponse(
            status="healthy" if app_state.orchestrator else "initializing",
            uptime_seconds=int(uptime),
            llm_configured=llm_configured,
            mcp_server=config.mcp_server.base_url,
            environment=config.env.value
        )
    except Exception as e:
        logger.error(f"Health check error: {e}", exc_info=True)
        # Return minimal response even if something fails
        return HealthResponse(
            status="error",
            uptime_seconds=0,
            llm_configured=False,
            mcp_server="unknown",
            environment="unknown"
        )


@app.get("/readiness")
async def readiness_check():
    """Readiness probe pour Kubernetes"""
    if not app_state.orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")
    return {"status": "ready"}


# ============================================================================
# ROUTES INFRASTRUCTURE
# ============================================================================

@app.get("/infrastructure/health")
async def infrastructure_health():
    """Statut de santé de l'infrastructure (PostgreSQL, Kafka, Redis)"""
    
    if not app_state.infra_manager:
        return {
            "status": "unavailable",
            "message": "Infrastructure manager not initialized"
        }
    
    try:
        health = await app_state.infra_manager.health_check()
        return health
    except Exception as e:
        logger.error(f"Infrastructure health check failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/infrastructure/stats")
async def infrastructure_stats():
    """Statistiques de l'infrastructure"""
    
    if not app_state.infra_manager:
        return {"status": "unavailable"}
    
    stats = {}
    
    # PostgreSQL stats
    try:
        db_stats = await app_state.infra_manager.db_client.get_statistics()
        stats["database"] = db_stats
    except Exception as e:
        logger.warning(f"DB stats fetch failed: {e}")
    
    # Redis stats
    try:
        redis_stats = await app_state.infra_manager.redis_client.get_stats()
        stats["redis"] = redis_stats
    except Exception as e:
        logger.warning(f"Redis stats fetch failed: {e}")
    
    return stats


@app.get("/metrics/requests")
async def get_metrics():
    """Métriques de base du service"""
    return {
        "total_requests": app_state.request_count,
        "uptime_seconds": (datetime.utcnow() - app_state.start_time).total_seconds() if app_state.start_time else 0,
    }


# ============================================================================
# ROUTES PRINCIPALES
# ============================================================================
# NOTE: /credit/decision endpoint is now provided by setup_orchestrator_routes
# from orchestrator_api.py which uses the new LangGraph-based orchestrator.
# This ensures SHAP values, counterfactuals, and XAI explanations are available.

# @app.post("/credit/decision", response_model=CreditDecisionResponse)
# async def make_credit_decision(
#     request: CreditDecisionRequest,
#     background_tasks: BackgroundTasks
# ) -> CreditDecisionResponse:
#     """
#     DEPRECATED: Use the endpoint from orchestrator_api.py instead
#     This endpoint has been replaced by the LangGraph-based orchestrator
#     """
#     pass


# ============================================================================
# ROUTES ASSISTANT - AI CREDIT COPILOT
# ============================================================================

@app.post("/api/assistant/chat", response_model=AssistantChatResponse)
async def assistant_chat(request: AssistantChatRequest) -> AssistantChatResponse:
    """
    AI Assistant endpoint for credit guidance
    Provides intelligent, conversational guidance for credit applications
    """
    try:
        logger.info(f"Assistant chat - User: {request.userId}, Loan: {request.loanId}")

        assistant_service = get_assistant_service()
        response = await assistant_service.chat(request)

        logger.info(f"Assistant response generated (status: {response.status})")
        return response
    except Exception as e:
        logger.error(f"Assistant chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Assistant error: {str(e)}")


@app.post("/agent/chat", response_model=AgentChatResponse)
async def agent_chat(request: AgentChatRequest) -> AgentChatResponse:
    """
    Chat avec un agent IA spécifique (FRAUD | SCORING | GUARANTEE | POLICY | XAI).
    L'agent répond à partir de l'analyse réelle qu'il a effectuée sur ce dossier.
    Chaque agent reste strictement dans son périmètre d'expertise.
    """
    try:
        logger.info(
            f"Agent chat — type={request.agentType}, "
            f"message={request.userMessage[:60]}..."
        )
        service = get_agent_chat_service()
        response = await service.chat(request)
        logger.info(f"[{request.agentType}] Response generated (status={response.status})")
        return response
    except Exception as e:
        logger.error(f"Agent chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent chat error: {str(e)}")


@app.post("/orchestrator/chat", response_model=ChatResponse)
async def llm_chat(request: ChatRequest) -> ChatResponse:
    """
    LLM-powered chat endpoint for intelligent credit guidance
    Uses Azure OpenAI to generate context-aware responses
    Endpoint called by ai-gateway AssistantChatService
    """
    try:
        request_id = str(uuid.uuid4())
        logger.info(f"[{request_id}] LLM Chat - User: {request.userId}, Message: {request.message[:50]}...")

        chat_service = get_llm_chat_service()
        response = await chat_service.chat(request)

        logger.info(f"[{request_id}] LLM response generated (status: {response.status})")
        return response
    except Exception as e:
        logger.error(f"LLM chat error: {e}", exc_info=True)
        # Return graceful error response
        return ChatResponse(
            message="Désolé, une erreur s'est produite. Veuillez réessayer." 
            if "ROLE_CLIENT" in (request.userRole or "ROLE_CLIENT").upper()
            else "An error occurred processing your request. Please try again.",
            status="error"
        )


def build_test_state(request: AgentTestRequest) -> CreditApplicationState:
    """Construit un etat minimal et valide pour les tests d agents"""
    timestamp = datetime.utcnow().isoformat()
    return {
        **DEFAULT_STATE,
        "application_id": str(uuid.uuid4()),
        "client_id": request.client_id,
        "created_at": timestamp,
        "client_data": request.client_data,
        "audit_trail": [
            {
                "timestamp": timestamp,
                "agent": "TEST_HARNESS",
                "action": "TEST_REQUEST_RECEIVED",
                "details": {"client_id": request.client_id},
            }
        ],
    }


def infer_policy_decision(pd_score: float, pd_confidence: float) -> Dict[str, Any]:
    """Politique minimale pour permettre le test XAI sans tout l orchestrateur"""
    if pd_score < 0.35:
        decision = "APPROVE"
        rule_id = "SCORE_LOW_RISK"
    elif pd_score > 0.65:
        decision = "REJECT"
        rule_id = "SCORE_HIGH_RISK"
    else:
        decision = "REVIEW_REQUIRED"
        rule_id = "SCORE_GREY_ZONE"

    return {
        "decision": decision,
        "rule_id": rule_id,
        "rule_name": rule_id,
        "rules_matched": [rule_id],
        "confidence_score": pd_confidence,
        "recommended_product": "Credit Auto" if decision == "APPROVE" else None,
        "product_terms": {"rate": 4.5, "term_months": 60} if decision == "APPROVE" else None,
    }


@app.post("/credit/analyze")
async def analyze_client(client_data: dict):
    """
    Endpoint pour analyse complète sans décision finale
    """
    try:
        # Logique d'analyse uniquement
        logger.info(f"Analyse client: {client_data.get('client_id')}")
        
        # À implémenter avec agent analyzer uniquement
        return {
            "status": "ok",
            "analysis": {"message": "Analysis not yet implemented"}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/credit/score")
async def quick_score(client_data: dict):
    """
    Endpoint pour scoring rapide (sans analyse complète)
    """
    try:
        logger.info(f"Quick score: {client_data.get('client_id')}")
        
        # À implémenter avec agent scorer uniquement
        return {
            "status": "ok",
            "score": 0.5,
            "message": "Quick score not yet implemented"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/credit/score-agent", response_model=ScoringOnlyResponse)
async def score_agent_test(request: AgentTestRequest):
    """
    Route de test dediee a l agent scoring uniquement.
    """
    try:
        logger.info(f"Scoring agent test: {request.client_id}")

        infra_manager = None
        try:
            infra_manager = await get_infra_manager()
        except Exception as exc:
            logger.warning(f"Scoring test running without infrastructure manager: {exc}")

        feature_store = FeatureStore(
            redis_client=infra_manager.redis_client if infra_manager else None,
            db_client=infra_manager.db_client if infra_manager else None,
        )
        scoring_agent = ScoringAgent(feature_store)

        state = build_test_state(request)
        state["processing_steps_completed"].append("TEST_SCORING_START")
        state = await scoring_agent.process(state)

        return ScoringOnlyResponse(
            application_id=state["application_id"],
            client_id=state["client_id"],
            pd_score=state["final_pd_score"],
            pd_confidence=state["pd_confidence"],
            risk_band=state["risk_band"],
            in_grey_zone=state["in_grey_zone"],
            iterations=len(state["scoring_iterations"]),
            requested_additional_features=state["requested_additional_features"],
            scoring_iterations=state["scoring_iterations"],
            processing_steps_completed=state["processing_steps_completed"],
            error_messages=state["error_messages"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/credit/xai-agent", response_model=XAIOnlyResponse)
async def xai_agent_test(request: AgentTestRequest):
    """
    Route de test dediee a l agent XAI.
    Le scoring est prepare juste avant pour fournir les SHAP values necessaires.
    """
    try:
        logger.info(f"XAI agent test: {request.client_id}")

        await langgraph_api.initialize()

        state = build_test_state(request)
        state["processing_steps_completed"].append("TEST_XAI_START")

        state = await langgraph_api.orchestrator.scoring_agent.process(state)
        state["policy_decision"] = infer_policy_decision(
            state["final_pd_score"],
            state["pd_confidence"],
        )
        state["final_decision"] = state["policy_decision"]["decision"]
        state = await langgraph_api.orchestrator.xai_agent.process(state)

        return XAIOnlyResponse(
            application_id=state["application_id"],
            client_id=state["client_id"],
            pd_score=state["final_pd_score"],
            pd_confidence=state["pd_confidence"],
            risk_band=state["risk_band"],
            decision_preview=state["policy_decision"]["decision"],
            top_factors=state["xai_explanation"]["top_factors"],
            counterfactuals=state["xai_explanation"]["counterfactuals"],
            explanation=state["xai_explanation"]["natural_explanation"],
            processing_steps_completed=state["processing_steps_completed"],
            error_messages=state["error_messages"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ROUTES DEBUG & MONITORING (développement)
# ============================================================================

@app.get("/debug/agents")
async def debug_agents():
    """Infos sur les agents disponibles (DEV only)"""
    if config.env != Environment.DEVELOPMENT:
        raise HTTPException(status_code=403, detail="Not available in production")
    
    return {
        "orchestrator": "OrchestratorAgent - Coordinateur principal",
        "agents": [
            "ScorerAgent - Scoring ML via MCP",
            "AnalyzerAgent - Analyse données client",
            "RiskAssessorAgent - Évaluation risques",
        ]
    }


@app.get("/debug/config")
async def debug_config():
    """Affiche la configuration (DEV only, sanitized)"""
    if config.env != Environment.DEVELOPMENT:
        raise HTTPException(status_code=403, detail="Not available in production")
    
    return {
        "environment": config.env.value,
        "debug": config.debug,
        "llm": {
            "provider": "azure_openai",
            "endpoint": config.azure_openai.endpoint,
            "deployment": config.azure_openai.deployment,
            "api_version": config.azure_openai.api_version,
        },
        "mcp": {
            "base_url": config.mcp_server.base_url,
            "timeout": config.mcp_server.timeout,
        }
    }


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handler personnalisé pour HTTPException"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handler pour exceptions non prévues"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "details": str(exc) if config.debug else "Details hidden in production",
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    logger.info(f"Démarrage en mode {config.env.value}")
    
    uvicorn.run(
        "src.main:app",
        host=config.service_host,
        port=config.service_port,
        reload=config.debug,
        log_level=config.log_level.lower(),
        workers=1 if config.debug else 4,  # Uvicorn workers pour production
        access_log=config.debug
    )
