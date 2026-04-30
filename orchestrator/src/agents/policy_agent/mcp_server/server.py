"""
MCP Server — Policy Agent
Expose le policy agent comme un service HTTP indépendant.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.agents.policy_agent.agent.policy_agent import PolicyAgent
from src.state import DEFAULT_STATE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/policy", tags=["policy-agent"])
_agent: Optional[PolicyAgent] = None


def get_agent() -> PolicyAgent:
    global _agent
    if _agent is None:
        _agent = PolicyAgent()
    return _agent


class PolicyRequest(BaseModel):
    application_id: str = ""
    client_id: str = ""
    final_pd_score: float = 0.0
    pd_confidence: float = 0.0
    risk_band: str = ""
    in_grey_zone: bool = False
    client_data: Dict[str, Any] = {}


class PolicyResponse(BaseModel):
    decision: str
    rule_id: str
    rule_name: str
    rules_matched: list
    confidence_score: float
    recommended_product: Optional[str]
    product_terms: Optional[Dict[str, Any]]
    regulatory_checks_passed: bool
    bct_rules_applied: list


@router.post("/decide", response_model=PolicyResponse)
async def decide(request: PolicyRequest) -> PolicyResponse:
    """Évalue les règles BCT et retourne une décision de conformité."""
    from copy import deepcopy
    import uuid

    state = deepcopy(DEFAULT_STATE)
    state["application_id"] = request.application_id or str(uuid.uuid4())
    state["client_id"] = request.client_id
    state["final_pd_score"] = request.final_pd_score
    state["pd_confidence"] = request.pd_confidence
    state["risk_band"] = request.risk_band
    state["in_grey_zone"] = request.in_grey_zone
    state["client_data"] = request.client_data

    try:
        agent = get_agent()
        updated_state = await agent.process(state)
        decision = updated_state["policy_decision"]
        return PolicyResponse(
            decision=decision["decision"],
            rule_id=decision["rule_id"],
            rule_name=decision["rule_name"],
            rules_matched=decision["rules_matched"],
            confidence_score=decision["confidence_score"],
            recommended_product=decision.get("recommended_product"),
            product_terms=decision.get("product_terms"),
            regulatory_checks_passed=updated_state["regulatory_checks_passed"],
            bct_rules_applied=updated_state["bct_rules_applied"],
        )
    except Exception as exc:
        logger.error("[POLICY-MCP] Error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "agent": "policy-agent"}


@router.get("/rules")
async def list_rules() -> Dict[str, Any]:
    """Retourne la liste des règles déterministes du HardRulesEngine."""
    from src.agents.policy_agent.agent.policy_agent import HardRulesEngine
    engine = HardRulesEngine()
    sample = engine.evaluate({
        "debt_ratio": 0.30, "client_age": 35, "credit_type": "consommation",
        "loan_amount": 20000, "monthly_income": 2000, "monthly_payment": 600,
        "loan_duration_months": 60, "employment_status": "salarie",
        "cr_bct_class": 0, "on_sanctions_list": False,
        "pd_score": 0.25, "pd_confidence": 0.85, "in_grey_zone": False,
    })
    return {
        "hard_rules": [
            {"rule_id": r["rule_id"], "rule_name": r["rule_name"], "blocking": r["blocking"]}
            for r in sample
        ]
    }
