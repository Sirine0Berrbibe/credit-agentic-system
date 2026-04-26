"""
LangGraph orchestrator for the credit workflow.
"""

import asyncio
import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Dict, Any, Optional
import uuid

from langgraph.graph import StateGraph, START, END

from src.state import CreditApplicationState, DEFAULT_STATE
from src.agents.scoring_agent import ScoringAgent, FeatureStore
from src.agents.xai_agent_v2 import XAIAgent
from src.agents.guarantee_agent.agent.guarantee_agent import GuaranteeAgent

logger = logging.getLogger(__name__)


class OrchestratorGraph:
    def __init__(
        self,
        feature_store: Optional[FeatureStore] = None,
        llm_client=None,
        db_client=None,
        kafka_producer=None,
    ):
        self.feature_store = feature_store or FeatureStore(db_client=db_client)
        self.llm_client = llm_client
        self.db_client = db_client
        self.kafka_producer = kafka_producer

        if self.db_client and hasattr(self.feature_store, "db_client"):
            self.feature_store.db_client = self.db_client

        self.guarantee_agent = GuaranteeAgent(
            enable_llm=True,
            enable_document_intelligence=True,
            enable_summary_llm=False,
        )
        self.scoring_agent = ScoringAgent(self.feature_store)
        self.xai_agent = XAIAgent(llm_client, db_client)

        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(CreditApplicationState)

        graph.add_node("_initialize", self._node_initialize)
        graph.add_node("guarantee_a", self._node_guarantee_a)
        graph.add_node("scoring_b", self._node_scoring_b)
        graph.add_node("policy_c", self._node_policy_c)
        graph.add_node("xai_d", self._node_xai_d)
        graph.add_node("_finalize", self._node_finalize)

        graph.add_edge(START, "_initialize")
        graph.add_edge("_initialize", "guarantee_a")
        graph.add_conditional_edges(
            "guarantee_a",
            self._route_after_guarantee,
            {
                "proceed": "scoring_b",
                "stop": "_finalize",
            },
        )
        graph.add_edge("scoring_b", "policy_c")
        graph.add_edge("policy_c", "xai_d")
        graph.add_edge("xai_d", "_finalize")
        graph.add_edge("_finalize", END)

        return graph.compile()

    async def _node_initialize(
        self, state: CreditApplicationState
    ) -> CreditApplicationState:
        logger.info("[ORCHESTRATOR] Initializing application state")

        if not state.get("application_id"):
            state["application_id"] = str(uuid.uuid4())
        if not state.get("created_at"):
            state["created_at"] = datetime.utcnow().isoformat()

        state["orchestrator_state"] = "INITIALIZED"
        state["processing_steps_completed"] = ["INIT"]
        state["audit_trail"] = [
            {
                "timestamp": state["created_at"],
                "agent": "ORCHESTRATOR",
                "action": "APPLICATION_RECEIVED",
                "details": {"application_id": state["application_id"]},
            }
        ]

        await self._write_audit(
            state,
            agent="ORCHESTRATOR",
            action="APPLICATION_RECEIVED",
            details={"client_data_keys": sorted(state["client_data"].keys())},
        )
        await self._persist_snapshot(state, "INITIALIZED")
        await self._emit_event(
            "application.received",
            {
                "application_id": state["application_id"],
                "client_id": state["client_id"],
            },
            state,
        )

        return state

    async def _node_guarantee_a(
        self, state: CreditApplicationState
    ) -> CreditApplicationState:
        logger.info("[ORCHESTRATOR] Running guarantee/document workflow")

        state["orchestrator_state"] = "DOCUMENT_PROCESSING"
        state["processing_steps_completed"].append("GUARANTEE_A_START")

        require_documents = self._should_require_document_validation(state["client_data"])
        dossier = self._build_guarantee_dossier(state)
        analysis = await asyncio.to_thread(
            self.guarantee_agent.run,
            dossier,
            require_documents,
        )

        logger.info(
            "[ORCHESTRATOR] GuaranteeAgent output for %s:\n%s",
            state["client_id"],
            json.dumps(analysis, ensure_ascii=False, indent=2, default=str),
        )

        state["guarantee_analysis"] = analysis
        state["guarantee_ready_for_scoring"] = analysis.get("ready_for_scoring", False)
        state["documents_processed"] = True
        state["missing_documents"] = analysis.get("documents_manquants", [])
        state["document_quality_score"] = analysis.get("extracted_features", {}).get(
            "document_quality_score",
            0.0,
        )
        state["extracted_document_features"] = analysis.get("extracted_features", {})
        state["frontend_messages"] = analysis.get("frontend_payload", {}).get(
            "conditions_deblocage",
            analysis.get("conditions_deblocage", []),
        )
        state["frontend_payload"] = analysis.get(
            "frontend_payload",
            {
                "status": "READY_FOR_SCORING"
                if analysis.get("ready_for_scoring")
                else "ACTION_REQUIRED",
                "conditions_deblocage": analysis.get("conditions_deblocage", []),
                "missing_documents": analysis.get("documents_manquants", []),
                "document_issues": analysis.get("document_issues", {}),
            },
        )

        state["documents"] = self._map_document_results_to_state(
            analysis.get("document_results", [])
        )

        # Keep only scoring-relevant shared features in the state/cache, not raw document blobs.
        state["client_data"] = self._build_shared_feature_payload(
            client_data=state["client_data"],
            analysis=analysis,
            frontend_payload=state["frontend_payload"],
        )

        state["audit_trail"].append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "agent": "GUARANTEE_A",
                "action": "DOSSIER_ANALYZED",
                "details": {
                    "verdict": analysis.get("verdict"),
                    "ready_for_scoring": analysis.get("ready_for_scoring"),
                    "missing_documents": analysis.get("documents_manquants", []),
                },
            }
        )
        state["processing_steps_completed"].append("GUARANTEE_A_COMPLETE")

        await self._write_audit(
            state,
            agent="GUARANTEE_A",
            action="DOSSIER_ANALYZED",
            details=analysis,
        )
        await self._persist_snapshot(state, "GUARANTEE_A")

        if self.db_client:
            await self.db_client.save_features(
                client_id=state["client_id"],
                features=state["client_data"],
                source="GUARANTEE_A",
            )
            await self._save_handoff(
                state=state,
                source_agent="GUARANTEE_A",
                target_agent="SCORING_B" if state["guarantee_ready_for_scoring"] else "FRONTEND",
                handoff_type=(
                    "GUARANTEE_TO_SCORING"
                    if state["guarantee_ready_for_scoring"]
                    else "GUARANTEE_TO_FRONTEND"
                ),
                status=(
                    "READY_FOR_SCORING"
                    if state["guarantee_ready_for_scoring"]
                    else "ACTION_REQUIRED"
                ),
                payload=(
                    analysis.get("scoring_payload", {})
                    if state["guarantee_ready_for_scoring"]
                    else state["frontend_payload"]
                ),
            )

        if state["guarantee_ready_for_scoring"]:
            await self._emit_event(
                "guarantee.completed",
                {
                    "application_id": state["application_id"],
                    "client_id": state["client_id"],
                    "verdict": analysis.get("verdict"),
                    "garantie_principale": analysis.get("garantie_principale"),
                    "scoring_payload": analysis.get("scoring_payload", {}),
                },
                state,
            )
        else:
            await self._emit_event(
                "documents.review_required",
                {
                    "application_id": state["application_id"],
                    "client_id": state["client_id"],
                    "verdict": analysis.get("verdict"),
                    "documents_manquants": analysis.get("documents_manquants", []),
                    "document_issues": analysis.get("document_issues", {}),
                    "conditions_deblocage": analysis.get("conditions_deblocage", []),
                    "frontend_payload": state["frontend_payload"],
                },
                state,
            )

        return state

    def _route_after_guarantee(self, state: CreditApplicationState) -> str:
        return "proceed" if state.get("guarantee_ready_for_scoring") else "stop"

    async def _node_scoring_b(
        self, state: CreditApplicationState
    ) -> CreditApplicationState:
        logger.info("[ORCHESTRATOR] Calling Scoring Agent for %s", state["application_id"])

        state = await self.scoring_agent.process(state)

        await self._write_audit(
            state,
            agent="SCORING_B",
            action="SCORING_COMPLETED",
            details={
                "pd_score": state["final_pd_score"],
                "risk_band": state["risk_band"],
                "iterations": len(state["scoring_iterations"]),
            },
        )
        await self._persist_snapshot(state, "SCORING_B")
        await self._emit_event(
            "scoring.completed",
            {
                "application_id": state["application_id"],
                "pd_score": state["final_pd_score"],
                "risk_band": state["risk_band"],
            },
            state,
        )

        return state

    async def _node_policy_c(
        self, state: CreditApplicationState
    ) -> CreditApplicationState:
        logger.info("[ORCHESTRATOR] Calling Policy Agent for %s", state["application_id"])

        if state["final_pd_score"] < 0.35:
            decision = "APPROVE"
            rule_id = "SCORE_LOW_RISK"
        elif state["final_pd_score"] > 0.65:
            decision = "REJECT"
            rule_id = "SCORE_HIGH_RISK"
        else:
            decision = "REVIEW_REQUIRED"
            rule_id = "SCORE_GREY_ZONE"

        state["policy_decision"] = {
            "decision": decision,
            "rule_id": rule_id,
            "rule_name": rule_id,
            "rules_matched": [rule_id],
            "confidence_score": state["pd_confidence"],
            "recommended_product": "Credit Auto" if decision == "APPROVE" else None,
            "product_terms": {"rate": 4.5, "term_months": 60}
            if decision == "APPROVE"
            else None,
        }
        state["regulatory_checks_passed"] = decision != "REJECT"
        state["bct_rules_applied"] = [rule_id]
        state["audit_trail"].append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "agent": "POLICY_C",
                "action": "DECISION_MADE",
                "details": {"decision": decision, "rule_id": rule_id},
            }
        )

        await self._write_audit(
            state,
            agent="POLICY_C",
            action="DECISION_MADE",
            details=state["policy_decision"],
        )
        await self._persist_snapshot(state, "POLICY_C")

        return state

    async def _node_xai_d(
        self, state: CreditApplicationState
    ) -> CreditApplicationState:
        logger.info("[ORCHESTRATOR] Calling XAI Agent for %s", state["application_id"])

        state = await self.xai_agent.process(state)
        await self._persist_snapshot(state, "XAI_D")
        await self._emit_event(
            "explainability.generated",
            {
                "application_id": state["application_id"],
                "top_factors": state["xai_explanation"]["top_factors"][:3],
            },
            state,
        )

        return state

    async def _node_fraud_e(
        self, state: CreditApplicationState
    ) -> CreditApplicationState:
        logger.info("[ORCHESTRATOR] Starting async Fraud Detection for %s", state["application_id"])

        fraud_result = {
            "fraud_risk_score": 0.15,
            "is_flagged": False,
            "anomaly_type": None,
            "velocity_metrics": {},
            "biometric_verified": True,
            "interrupt_signal": False,
        }

        state["fraud_analysis"] = fraud_result
        state["fraud_check_completed"] = True
        state["is_application_blocked"] = fraud_result["interrupt_signal"]
        return state

    async def _node_finalize(
        self, state: CreditApplicationState
    ) -> CreditApplicationState:
        logger.info("[ORCHESTRATOR] Finalizing application %s", state["application_id"])

        guarantee_analysis = state.get("guarantee_analysis", {})

        if not state.get("guarantee_ready_for_scoring", False):
            verdict = guarantee_analysis.get("verdict")
            if verdict == "KO":
                state["final_decision"] = "REJECT"
                state["decision_summary"] = guarantee_analysis.get(
                    "note_comite",
                    "Dossier rejete avant scoring.",
                )
                state["next_action"] = "Revoir le dossier avec un conseiller"
            else:
                state["final_decision"] = "REVIEW_REQUIRED"
                state["decision_summary"] = self._build_regularization_summary(
                    guarantee_analysis
                )
                state["next_action"] = (
                    "Televerser les documents ou assurances demandes puis relancer l'analyse"
                )
        elif state["is_application_blocked"]:
            state["final_decision"] = "BLOCKED"
            state["decision_summary"] = "Application bloquee pour suspicion de fraude."
            state["next_action"] = "Contacter le support"
        else:
            policy_decision = state["policy_decision"]["decision"]
            state["final_decision"] = policy_decision

            if policy_decision == "APPROVE":
                state["decision_summary"] = (
                    "Demande approuvee. Les conditions du credit vous seront communiquees."
                )
                state["next_action"] = "Attendre le contact de l'equipe"
            elif policy_decision == "REJECT":
                state["decision_summary"] = (
                    "Demande rejetee. Vous pouvez reappliquer apres amelioration du dossier."
                )
                state["next_action"] = "Ameliorer le dossier et reappliquer"
            else:
                state["decision_summary"] = (
                    "Demande en revision manuelle. Un expert examinera votre dossier."
                )
                state["next_action"] = "Rester disponible pour des justificatifs complementaires"

        state["orchestrator_state"] = "COMPLETE"
        state["total_processing_time_ms"] = sum(
            [
                state.get("ml_latency_ms", 0.0),
                state.get("xai_latency_ms", 0.0),
            ]
        )
        state["audit_trail"].append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "agent": "ORCHESTRATOR",
                "action": "APPLICATION_COMPLETE",
                "details": {
                    "final_decision": state["final_decision"],
                    "total_time_ms": state["total_processing_time_ms"],
                },
            }
        )

        await self._write_audit(
            state,
            agent="ORCHESTRATOR",
            action="APPLICATION_COMPLETE",
            details={
                "final_decision": state["final_decision"],
                "decision_summary": state["decision_summary"],
            },
        )
        await self._persist_snapshot(state, "FINALIZED")

        if self.db_client:
            await self.db_client.save_decision(
                application_id=state["application_id"],
                client_id=state["client_id"],
                decision=state["final_decision"],
                final_pd_score=state["final_pd_score"],
                pd_confidence=state["pd_confidence"],
                risk_band=state["risk_band"] or "PENDING_GUARANTEE",
                top_factors=state["xai_explanation"]["top_factors"],
                counterfactuals=state["xai_explanation"]["counterfactuals"],
                explanation=state["decision_summary"],
                fraud_risk_score=(
                    state["fraud_analysis"]["fraud_risk_score"]
                    if state["fraud_analysis"]
                    else None
                ),
                processing_time_ms=state["total_processing_time_ms"],
            )

        await self._emit_event(
            "application.completed",
            {
                "application_id": state["application_id"],
                "final_decision": state["final_decision"],
                "client_id": state["client_id"],
                "decision_summary": state["decision_summary"],
            },
            state,
        )

        return state

    async def process_application(
        self, client_id: str, client_data: Dict[str, Any]
    ) -> CreditApplicationState:
        application_id = (
            client_data.get("application_id")
            or client_data.get("applicationId")
            or str(uuid.uuid4())
        )
        created_at = client_data.get("created_at") or client_data.get("createdAt") or datetime.utcnow().isoformat()

        initial_state: CreditApplicationState = {
            **deepcopy(DEFAULT_STATE),
            "application_id": application_id,
            "client_id": client_id,
            "created_at": created_at,
            "client_data": client_data,
        }

        logger.info("[ORCHESTRATOR] Processing application for client %s", client_id)

        try:
            fraud_task = asyncio.create_task(self._node_fraud_e(deepcopy(initial_state)))
            final_state = await self.graph.ainvoke(initial_state)
            fraud_state = await fraud_task

            final_state["fraud_analysis"] = fraud_state.get("fraud_analysis")
            final_state["fraud_check_completed"] = fraud_state.get(
                "fraud_check_completed",
                False,
            )
            final_state["is_application_blocked"] = fraud_state.get(
                "is_application_blocked",
                False,
            )

            if final_state["is_application_blocked"] and final_state["final_decision"] != "BLOCKED":
                final_state["final_decision"] = "BLOCKED"
                final_state["decision_summary"] = (
                    "Application bloquee apres controle fraude asynchrone."
                )
                final_state["next_action"] = "Contacter le support"
                await self._write_audit(
                    final_state,
                    agent="FRAUD_E",
                    action="APPLICATION_BLOCKED",
                    details=fraud_state.get("fraud_analysis"),
                )
                await self._persist_snapshot(final_state, "FRAUD_OVERRIDE")

            return final_state
        except Exception as exc:
            logger.error("[ORCHESTRATOR] Error processing application: %s", exc)
            initial_state["error_messages"].append(str(exc))
            initial_state["final_decision"] = "ERROR"
            initial_state["decision_summary"] = "Une erreur est survenue pendant le traitement."
            return initial_state

    def _build_guarantee_dossier(self, state: CreditApplicationState) -> Dict[str, Any]:
        client_data = dict(state["client_data"])

        loan_amount = self._to_float(
            client_data.get("loan_amount", client_data.get("AMT_CREDIT", client_data.get("amount", 0)))
        )
        monthly_income = self._to_float(
            client_data.get("monthly_salary", client_data.get("income", 0))
        )
        monthly_payment = self._to_float(
            client_data.get("monthly_payment", client_data.get("AMT_ANNUITY", 0))
        )
        debt_ratio = client_data.get("debt_ratio", client_data.get("DTI", client_data.get("dti")))
        if debt_ratio is None and monthly_income > 0:
            debt_ratio = monthly_payment / monthly_income

        age = client_data.get("client_age", client_data.get("age"))
        if age is None and client_data.get("DAYS_BIRTH") is not None:
            age = abs(self._to_float(client_data.get("DAYS_BIRTH"))) / 365

        return {
            **client_data,
            "client_id": state["client_id"],
            "credit_type": client_data.get("credit_type", "consommation"),
            "loan_amount": loan_amount,
            "client_age": int(round(self._to_float(age or 0))),
            "risk_class": client_data.get("risk_class"),
            "debt_ratio": debt_ratio or 0.0,
            "is_salary_domiciled": client_data.get("is_salary_domiciled", True),
            "insurance_subscribed": client_data.get("insurance_subscribed", []),
            "cin_bytes": client_data.get("cin_bytes"),
            "fiches_paie_bytes": client_data.get("fiches_paie_bytes"),
            "domicile_bytes": client_data.get("domicile_bytes"),
            "compromis_vente_bytes": client_data.get("compromis_vente_bytes"),
        }

    def _should_require_document_validation(self, client_data: Dict[str, Any]) -> bool:
        if client_data.get("document_workflow_enabled") is False:
            return False
        return True

    def _map_document_results_to_state(
        self,
        document_results: list[dict[str, Any]],
    ) -> Dict[str, Any]:
        mapped: Dict[str, Any] = {}
        for result in document_results:
            key = result.get("document_type", "unknown").upper().replace(" ", "_")
            mapped[key] = {
                "document_type": result.get("document_type", ""),
                "extracted_fields": result.get("extracted_info", {}),
                "confidence": 1.0 if result.get("is_valid") else 0.5,
                "ocr_text": "",
                "named_entities": [],
                "request_doc": not result.get("is_valid", False),
            }
        return mapped

    def _build_regularization_summary(self, analysis: Dict[str, Any]) -> str:
        note = analysis.get("note_comite") or "Dossier a regulariser avant poursuite."
        conditions = analysis.get("conditions_deblocage", [])
        if not conditions:
            return note
        return f"{note} Actions requises: {'; '.join(conditions[:3])}."

    async def _write_audit(
        self,
        state: CreditApplicationState,
        agent: str,
        action: str,
        details: Dict[str, Any] | None = None,
    ) -> None:
        if not self.db_client:
            return
        await self.db_client.write_audit_log(
            application_id=state["application_id"],
            client_id=state["client_id"],
            agent=agent,
            action=action,
            details=self._safe_for_storage(details or {}),
        )

    async def _persist_snapshot(self, state: CreditApplicationState, stage: str) -> None:
        if not self.db_client:
            return
        await self.db_client.save_application_state(
            application_id=state["application_id"],
            client_id=state["client_id"],
            stage=stage,
            payload=self._safe_for_storage(state),
        )

    async def _save_handoff(
        self,
        state: CreditApplicationState,
        source_agent: str,
        target_agent: str,
        handoff_type: str,
        status: str,
        payload: Dict[str, Any],
    ) -> None:
        if not self.db_client:
            return
        await self.db_client.save_agent_handoff(
            application_id=state["application_id"],
            client_id=state["client_id"],
            source_agent=source_agent,
            target_agent=target_agent,
            handoff_type=handoff_type,
            status=status,
            payload=self._safe_for_storage(payload),
        )

    async def _emit_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        state: CreditApplicationState,
    ) -> None:
        if not self.kafka_producer:
            logger.debug("[ORCHESTRATOR] Event (no Kafka) %s = %s", event_type, data)
            return

        topic = self._topic_for_event(event_type)
        try:
            if hasattr(self.kafka_producer, "send_event"):
                await self.kafka_producer.send_event(
                    topic=topic,
                    application_id=state["application_id"],
                    client_id=state["client_id"],
                    event_type=event_type,
                    data=data,
                )
            else:
                await self.kafka_producer.send_and_wait(
                    topic,
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "event_type": event_type,
                        "data": data,
                    },
                )
        except Exception as exc:
            logger.warning("[ORCHESTRATOR] Failed to emit event %s: %s", event_type, exc)

    def _topic_for_event(self, event_type: str) -> str:
        mapping = {
            "application.received": "credit.application.started",
            "documents.review_required": "credit.documents.review_required",
            "guarantee.completed": "credit.guarantee.complete",
            "scoring.completed": "credit.scoring.complete",
            "explainability.generated": "credit.explanation.generated",
            "application.completed": "credit.decision.made",
        }
        return mapping.get(event_type, "credit.workflow.events")

    def _safe_for_storage(self, value: Any) -> Any:
        if isinstance(value, bytes):
            return {"type": "bytes", "length": len(value)}
        if isinstance(value, bytearray):
            return {"type": "bytes", "length": len(value)}
        if isinstance(value, tuple):
            return [self._safe_for_storage(item) for item in value]
        if isinstance(value, list):
            return [self._safe_for_storage(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._safe_for_storage(item) for key, item in value.items()}
        return value

    def _build_shared_feature_payload(
        self,
        client_data: Dict[str, Any],
        analysis: Dict[str, Any],
        frontend_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        combined_features = analysis.get("scoring_payload", {}).get("combined_features", {})
        payload = {
            **self._strip_document_blobs(client_data),
            **combined_features,
            "guarantee_ready_for_scoring": analysis.get("ready_for_scoring", False),
            "guarantee_verdict": analysis.get("verdict"),
            "document_status": analysis.get("document_status", {}),
            "document_intelligence": analysis.get("document_intelligence", {}),
            "frontend_payload": frontend_payload,
            "scoring_payload": analysis.get("scoring_payload", {}),
        }
        return payload

    def _strip_document_blobs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "cin_bytes",
                "domicile_bytes",
                "compromis_vente_bytes",
                "fiches_paie_bytes",
            }
        }

    def _to_float(self, value: Any) -> float:
        try:
            if value is None or value == "":
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0


async def create_orchestrator(
    feature_store: Optional[FeatureStore] = None,
    llm_client=None,
    db_client=None,
    kafka_producer=None,
) -> OrchestratorGraph:
    return OrchestratorGraph(
        feature_store=feature_store,
        llm_client=llm_client,
        db_client=db_client,
        kafka_producer=kafka_producer,
    )
