from fastapi import APIRouter, FastAPI

from .guarantee_rules import apply_guarantee_rules
from .insurance_rules import apply_insurance_rules
from .validators import validate_documents

try:
    from src.agents.guarantee_agent.agent.guarantee_agent import GuaranteeAgent
except ImportError:
    from agent.guarantee_agent import GuaranteeAgent


agent = GuaranteeAgent(
    enable_llm=True,
    enable_document_intelligence=True,
    enable_summary_llm=False,
)
router = APIRouter(tags=["guarantee-agent"])


app = FastAPI(title="Guarantee Agent MCP Server")
app.include_router(router)


@router.post("/validate-documents")
def validate_docs(data: dict):
    return validate_documents(data)


@router.post("/apply-guarantee-rules")
def guarantee_rules(data: dict):
    return apply_guarantee_rules(data)


@router.post("/apply-insurance-rules")
def insurance_rules(data: dict):
    return apply_insurance_rules(data)


@router.post("/run-agent")
def run_agent(dossier: dict):
    return agent.run(dossier)
