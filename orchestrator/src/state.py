"""
CreditApplicationState - shared memory for the LangGraph orchestrator.
"""

from typing import TypedDict, Optional, List, Dict, Any


class DocumentExtractionResult(TypedDict):
    document_type: str
    extracted_fields: Dict[str, Any]
    confidence: float
    ocr_text: str
    named_entities: List[Dict[str, str]]
    request_doc: bool


class GuaranteeWorkflowResult(TypedDict, total=False):
    verdict: str
    garantie_principale: str
    garantie_secondaire: Optional[str]
    assurances_requises: List[str]
    assurances_presentes: List[str]
    documents_manquants: List[str]
    conditions_deblocage: List[str]
    note_comite: str
    ready_for_scoring: bool
    blocking_reasons: List[str]
    document_results: List[Dict[str, Any]]
    document_issues: Dict[str, List[str]]
    document_status: Dict[str, Dict[str, Any]]
    extracted_features: Dict[str, Any]
    document_intelligence: Dict[str, Any]
    guarantee_details: Dict[str, Any]
    insurance_details: Dict[str, Any]
    frontend_payload: Dict[str, Any]
    scoring_payload: Dict[str, Any]


class ScoringIterationResult(TypedDict):
    iteration: int
    pd_score: float
    confidence: float
    risk_band: str
    missing_features: List[str]
    shap_values: Dict[str, float]
    model_version: str


class PolicyDecisionResult(TypedDict):
    decision: str
    rule_id: str
    rule_name: str
    rules_matched: List[str]
    confidence_score: float
    recommended_product: Optional[str]
    product_terms: Optional[Dict[str, Any]]


class XAIExplanationResult(TypedDict):
    shap_values: Dict[str, float]
    top_factors: List[Dict[str, Any]]
    counterfactuals: List[Dict[str, Any]]
    natural_explanation: str
    decision_threshold: float
    distance_to_threshold: float


class FraudAnalysisResult(TypedDict):
    fraud_risk_score: float
    is_flagged: bool
    anomaly_type: Optional[str]
    velocity_metrics: Dict[str, int]
    biometric_verified: bool
    interrupt_signal: bool


class CreditApplicationState(TypedDict):
    application_id: str
    client_id: str
    created_at: str
    client_data: Dict[str, Any]

    documents: Dict[str, DocumentExtractionResult]
    documents_processed: bool
    missing_documents: List[str]
    document_quality_score: float
    guarantee_analysis: GuaranteeWorkflowResult
    guarantee_ready_for_scoring: bool
    extracted_document_features: Dict[str, Any]
    frontend_messages: List[str]
    frontend_payload: Dict[str, Any]

    scoring_iterations: List[ScoringIterationResult]
    final_pd_score: float
    pd_confidence: float
    risk_band: str
    in_grey_zone: bool
    requested_additional_features: Dict[str, bool]
    ml_model_version: str
    ml_latency_ms: float

    policy_decision: PolicyDecisionResult
    regulatory_checks_passed: bool
    bct_rules_applied: List[str]

    xai_explanation: XAIExplanationResult
    xai_latency_ms: float

    fraud_analysis: Optional[FraudAnalysisResult]
    fraud_check_completed: bool
    is_application_blocked: bool

    orchestrator_state: str
    processing_steps_completed: List[str]
    total_processing_time_ms: float
    error_messages: List[str]
    audit_trail: List[Dict[str, Any]]

    final_decision: str
    decision_summary: str
    next_action: Optional[str]


DEFAULT_STATE: CreditApplicationState = {
    "application_id": "",
    "client_id": "",
    "created_at": "",
    "client_data": {},
    "documents": {},
    "documents_processed": False,
    "missing_documents": [],
    "document_quality_score": 0.0,
    "guarantee_analysis": {
        "verdict": "",
        "garantie_principale": "",
        "garantie_secondaire": None,
        "assurances_requises": [],
        "assurances_presentes": [],
        "documents_manquants": [],
        "conditions_deblocage": [],
        "note_comite": "",
        "ready_for_scoring": False,
        "blocking_reasons": [],
        "document_results": [],
        "document_issues": {},
        "document_status": {},
        "extracted_features": {},
        "document_intelligence": {},
        "guarantee_details": {},
        "insurance_details": {},
        "frontend_payload": {},
        "scoring_payload": {},
    },
    "guarantee_ready_for_scoring": False,
    "extracted_document_features": {},
    "frontend_messages": [],
    "frontend_payload": {},
    "scoring_iterations": [],
    "final_pd_score": 0.0,
    "pd_confidence": 0.0,
    "risk_band": "",
    "in_grey_zone": False,
    "requested_additional_features": {},
    "ml_model_version": "",
    "ml_latency_ms": 0.0,
    "policy_decision": {
        "decision": "",
        "rule_id": "",
        "rule_name": "",
        "rules_matched": [],
        "confidence_score": 0.0,
        "recommended_product": None,
        "product_terms": None,
    },
    "regulatory_checks_passed": False,
    "bct_rules_applied": [],
    "xai_explanation": {
        "shap_values": {},
        "top_factors": [],
        "counterfactuals": [],
        "natural_explanation": "",
        "decision_threshold": 0.0,
        "distance_to_threshold": 0.0,
    },
    "xai_latency_ms": 0.0,
    "fraud_analysis": None,
    "fraud_check_completed": False,
    "is_application_blocked": False,
    "orchestrator_state": "INITIALIZED",
    "processing_steps_completed": [],
    "total_processing_time_ms": 0.0,
    "error_messages": [],
    "audit_trail": [],
    "final_decision": "",
    "decision_summary": "",
    "next_action": None,
}
