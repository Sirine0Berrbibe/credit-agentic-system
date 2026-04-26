from copy import deepcopy
import asyncio

import pytest

from src.agents.guarantee_agent.agent.guarantee_agent import GuaranteeAgent
from src.orchestrator_graph import OrchestratorGraph
from src.state import DEFAULT_STATE


class FakeDbClient:
    def __init__(self):
        self.audit_logs = []
        self.snapshots = []
        self.features = []
        self.handoffs = []
        self.decisions = []
        self.cached_features = {}

    async def write_audit_log(self, **kwargs):
        self.audit_logs.append(kwargs)
        return True

    async def save_application_state(self, **kwargs):
        self.snapshots.append(kwargs)
        return True

    async def save_features(self, **kwargs):
        self.features.append(kwargs)
        self.cached_features[kwargs["client_id"]] = dict(kwargs["features"])
        return True

    async def save_agent_handoff(self, **kwargs):
        self.handoffs.append(kwargs)
        return True

    async def save_decision(self, **kwargs):
        self.decisions.append(kwargs)
        return True

    async def get_features(self, client_id):
        return deepcopy(self.cached_features.get(client_id))


class FakeKafkaProducer:
    def __init__(self):
        self.events = []

    async def send_event(self, **kwargs):
        self.events.append(kwargs)
        return True


def test_guarantee_agent_marks_missing_and_invalid_documents_for_frontend():
    agent = GuaranteeAgent(enable_llm=False)

    analysis = agent.analyze(
        {
            "client_id": "CLIENT-1",
            "credit_type": "immobilier",
            "loan_amount": 180_000,
            "client_age": 38,
            "risk_class": 1,
            "debt_ratio": 0.28,
            "insurance_subscribed": [],
        },
        require_documents=True,
    )

    assert analysis.ready_for_scoring is False
    assert "Compromis de vente" in analysis.documents_manquants
    assert analysis.frontend_payload["status"] == "ACTION_REQUIRED"
    assert analysis.frontend_payload["missing_documents"] == analysis.documents_manquants
    assert analysis.document_status["Compromis de vente"]["status"] == "missing"
    assert analysis.scoring_payload["ready_for_scoring"] is False


def test_orchestrator_preserves_application_id_and_saves_frontend_handoff():
    db_client = FakeDbClient()
    kafka = FakeKafkaProducer()
    orchestrator = OrchestratorGraph(db_client=db_client, kafka_producer=kafka)

    final_state = asyncio.run(
        orchestrator.process_application(
            client_id="CLIENT-2",
            client_data={
                "application_id": "APP-FRONT-001",
                "credit_type": "immobilier",
                "loan_amount": 220_000,
                "risk_class": 1,
                "debt_ratio": 0.32,
            },
        )
    )

    assert final_state["application_id"] == "APP-FRONT-001"
    assert final_state["guarantee_ready_for_scoring"] is False
    assert final_state["final_decision"] == "REVIEW_REQUIRED"
    assert final_state["frontend_payload"]["status"] == "ACTION_REQUIRED"
    assert db_client.handoffs[0]["target_agent"] == "FRONTEND"
    assert db_client.handoffs[0]["handoff_type"] == "GUARANTEE_TO_FRONTEND"
    assert db_client.features[0]["client_id"] == "CLIENT-2"
    assert any(
        event["event_type"] == "documents.review_required" for event in kafka.events
    )


def test_orchestrator_passes_document_features_to_scoring_and_saves_scoring_handoff():
    db_client = FakeDbClient()
    kafka = FakeKafkaProducer()
    orchestrator = OrchestratorGraph(db_client=db_client, kafka_producer=kafka)

    ready_analysis = deepcopy(DEFAULT_STATE["guarantee_analysis"])
    ready_analysis.update(
        {
            "verdict": "OK",
            "garantie_principale": "Retenue directe sur salaire",
            "garantie_secondaire": None,
            "assurances_requises": [],
            "assurances_presentes": [],
            "documents_manquants": [],
            "conditions_deblocage": [],
            "note_comite": "Dossier conforme.",
            "ready_for_scoring": True,
            "blocking_reasons": [],
            "document_results": [
                {
                    "document_type": "CIN",
                    "is_valid": True,
                    "issues": [],
                    "extracted_info": {"expiry_date": "2030-01-01"},
                }
            ],
            "document_issues": {},
            "document_status": {
                "CIN": {
                    "required": True,
                    "status": "valid",
                    "issues": [],
                    "extracted_info": {"expiry_date": "2030-01-01"},
                }
            },
            "extracted_features": {
                "document_quality_score": 1.0,
                "documents_complete": True,
                "cin_expiry_date": "2030-01-01",
                "doc_monthly_net_income": 3200.0,
            },
            "document_intelligence": {
                "applicant": {"cin_expiry_date": "2030-01-01"},
                "employment": {"monthly_net_income": 3200.0},
                "languages": ["fr", "ar"],
                "confidence": "high",
            },
            "guarantee_details": {"risk_level": "FAIBLE"},
            "insurance_details": {"is_compliant": True},
            "frontend_payload": {
                "status": "READY_FOR_SCORING",
                "conditions_deblocage": [],
            },
            "scoring_payload": {
                "target": "SCORING_B",
                "ready_for_scoring": True,
                "document_features": {
                    "document_quality_score": 1.0,
                    "documents_complete": True,
                    "cin_expiry_date": "2030-01-01",
                    "doc_monthly_net_income": 3200.0,
                },
                "document_intelligence": {
                    "languages": ["fr", "ar"],
                    "confidence": "high",
                },
                "combined_features": {
                    "credit_type": "consommation",
                    "loan_amount": 12_000,
                    "cin_expiry_date": "2030-01-01",
                    "doc_monthly_net_income": 3200.0,
                    "monthly_salary": 3200.0,
                    "AMT_INCOME_TOTAL": 38400.0,
                },
            },
        }
    )

    orchestrator.guarantee_agent.run = lambda dossier, require_documents: ready_analysis

    async def fake_scoring_process(state):
        assert state["client_data"]["cin_expiry_date"] == "2030-01-01"
        state["final_pd_score"] = 0.2
        state["pd_confidence"] = 0.92
        state["risk_band"] = "LOW_RISK"
        state["ml_model_version"] = "test-model"
        state["ml_latency_ms"] = 1.0
        state["scoring_iterations"].append(
            {
                "iteration": 1,
                "pd_score": 0.2,
                "confidence": 0.92,
                "risk_band": "LOW_RISK",
                "missing_features": [],
                "shap_values": {},
                "model_version": "test-model",
            }
        )
        return state

    async def fake_xai_process(state):
        state["xai_explanation"] = {
            "shap_values": {},
            "top_factors": [],
            "counterfactuals": [],
            "natural_explanation": "ok",
            "decision_threshold": 0.35,
            "distance_to_threshold": 0.15,
        }
        state["xai_latency_ms"] = 1.0
        return state

    orchestrator.scoring_agent.process = fake_scoring_process
    orchestrator.xai_agent.process = fake_xai_process

    final_state = asyncio.run(
        orchestrator.process_application(
            client_id="CLIENT-3",
            client_data={
                "application_id": "APP-SCORE-001",
                "credit_type": "consommation",
                "loan_amount": 12_000,
            },
        )
    )

    assert final_state["guarantee_ready_for_scoring"] is True
    assert final_state["client_data"]["cin_expiry_date"] == "2030-01-01"
    assert final_state["client_data"]["doc_monthly_net_income"] == 3200.0
    assert final_state["final_decision"] == "APPROVE"
    assert db_client.handoffs[0]["target_agent"] == "SCORING_B"
    assert db_client.handoffs[0]["handoff_type"] == "GUARANTEE_TO_SCORING"
    assert "cin_bytes" not in db_client.features[0]["features"]
    assert "fiches_paie_bytes" not in db_client.features[0]["features"]
    assert any(event["event_type"] == "guarantee.completed" for event in kafka.events)


def test_orchestrator_strips_document_blobs_before_shared_db_persistence():
    db_client = FakeDbClient()
    kafka = FakeKafkaProducer()
    orchestrator = OrchestratorGraph(db_client=db_client, kafka_producer=kafka)

    ready_analysis = deepcopy(DEFAULT_STATE["guarantee_analysis"])
    ready_analysis.update(
        {
            "verdict": "OK",
            "garantie_principale": "Retenue directe sur salaire",
            "garantie_secondaire": None,
            "assurances_requises": [],
            "assurances_presentes": [],
            "documents_manquants": [],
            "conditions_deblocage": [],
            "note_comite": "Dossier conforme.",
            "ready_for_scoring": True,
            "blocking_reasons": [],
            "document_results": [],
            "document_issues": {},
            "document_status": {},
            "extracted_features": {
                "doc_monthly_net_income": 4100.0,
            },
            "document_intelligence": {
                "employment": {"monthly_net_income": 4100.0},
                "languages": ["fr"],
                "confidence": "high",
            },
            "guarantee_details": {"risk_level": "FAIBLE"},
            "insurance_details": {"is_compliant": True},
            "frontend_payload": {"status": "READY_FOR_SCORING"},
            "scoring_payload": {
                "target": "SCORING_B",
                "ready_for_scoring": True,
                "combined_features": {
                    "monthly_salary": 4100.0,
                    "AMT_INCOME_TOTAL": 49200.0,
                    "doc_monthly_net_income": 4100.0,
                },
            },
        }
    )

    orchestrator.guarantee_agent.run = lambda dossier, require_documents: ready_analysis

    async def fake_scoring_process(state):
        state["final_pd_score"] = 0.21
        state["pd_confidence"] = 0.9
        state["risk_band"] = "LOW_RISK"
        state["ml_model_version"] = "test-model"
        state["ml_latency_ms"] = 1.0
        return state

    async def fake_xai_process(state):
        state["xai_explanation"] = {
            "shap_values": {},
            "top_factors": [],
            "counterfactuals": [],
            "natural_explanation": "ok",
            "decision_threshold": 0.35,
            "distance_to_threshold": 0.14,
        }
        state["xai_latency_ms"] = 1.0
        return state

    orchestrator.scoring_agent.process = fake_scoring_process
    orchestrator.xai_agent.process = fake_xai_process

    asyncio.run(
        orchestrator.process_application(
            client_id="CLIENT-4",
            client_data={
                "application_id": "APP-SANITIZE-001",
                "credit_type": "consommation",
                "loan_amount": 18_000,
                "cin_bytes": {
                    "filename": "cin.png",
                    "content_base64": "ZmFrZS1iaW5hcnk=",
                },
                "fiches_paie_bytes": [
                    {
                        "filename": "pay1.pdf",
                        "content_base64": "ZmFrZS1wYXlzbGlw",
                    }
                ],
            },
        )
    )

    saved_features = db_client.features[0]["features"]
    assert "cin_bytes" not in saved_features
    assert "fiches_paie_bytes" not in saved_features
    assert saved_features["monthly_salary"] == 4100.0
    assert saved_features["document_intelligence"]["confidence"] == "high"
