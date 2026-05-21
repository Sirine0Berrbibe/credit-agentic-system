"""
LangGraph orchestrator — dual-flux credit workflow.

Flux A (preview)  : guarantee_a → scoring_b → xai_d(client)  → finalize
Flux B (full)     : guarantee_a → scoring_b → policy_c → xai_d(pro) → finalize
                    + fraud_e tourne en parallèle (asyncio.Task)

Redis cache : score preview valide 24h si le dossier n'a pas changé.
"""

import asyncio
import hashlib
import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Optional
import uuid

from langgraph.graph import StateGraph, START, END

from config.settings import get_config
from src.application_ids import normalize_application_id
from src.state import CreditApplicationState, DEFAULT_STATE
from src.agents.scoring_agent import ScoringAgent, FeatureStore
from src.agents.xai_agent_v2 import XAIAgent
from src.agents.guarantee_agent.agent.guarantee_agent import GuaranteeAgent
from src.agents.policy_agent.agent.policy_agent import PolicyAgent
from src.agents.fraud_agent import FraudAgent
from src.langsmith_tracing import (
    annotate_current_run,
    build_trace_metadata,
    build_trace_tags,
    process_trace_inputs,
    process_trace_outputs,
    traceable,
)

logger = logging.getLogger(__name__)

PREVIEW_CACHE_TTL = 86_400  # 24h


class OrchestratorGraph:
    def __init__(
        self,
        feature_store: Optional[FeatureStore] = None,
        llm_client=None,
        db_client=None,
        kafka_producer=None,
        redis_client=None,
    ):
        self.llm_client = llm_client
        self.db_client = db_client
        self.kafka_producer = kafka_producer
        self.redis_client = redis_client

        self.feature_store = feature_store or FeatureStore(db_client=db_client)
        if self.db_client and hasattr(self.feature_store, "db_client"):
            self.feature_store.db_client = self.db_client

        # Agents
        self.guarantee_agent = GuaranteeAgent(
            enable_llm=True,
            enable_document_intelligence=True,
            enable_summary_llm=True,
        )
        self.scoring_agent = ScoringAgent(self.feature_store)
        self.policy_agent = PolicyAgent()
        self.xai_agent = XAIAgent(llm_client, db_client)
        self.fraud_agent = FraudAgent(redis_client=redis_client)

        self.graph = self._build_graph()

    # ──────────────────────────────────────────────────────────
    # Graph construction
    # ──────────────────────────────────────────────────────────

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
            {"proceed": "scoring_b", "stop": "_finalize"},
        )
        # Flux A → xai_d direct ; Flux B → policy_c first
        graph.add_conditional_edges(
            "scoring_b",
            self._route_after_scoring,
            {"preview": "xai_d", "full": "policy_c"},
        )
        graph.add_edge("policy_c", "xai_d")
        graph.add_edge("xai_d", "_finalize")
        graph.add_edge("_finalize", END)

        return graph.compile()

    # ──────────────────────────────────────────────────────────
    # Routing helpers
    # ──────────────────────────────────────────────────────────

    def _route_after_guarantee(self, state: CreditApplicationState) -> str:
        if state.get("guarantee_ready_for_scoring"):
            return "proceed"
        verdict = state.get("guarantee_analysis", {}).get("verdict")
        # Hard KO always stops — document fraud, sanctions, hard eligibility failure
        if verdict == "KO":
            return "stop"
        # CONDITIONNEL: proceed in both Flux A and Flux B so that scoring, policy, and XAI
        # all run. _node_finalize will set the final decision to REVIEW_REQUIRED and surface
        # the guarantee conditions alongside the AI analysis to the consultant.
        return "proceed"

    def _route_after_scoring(self, state: CreditApplicationState) -> str:
        return "preview" if state.get("flux_type") == "preview" else "full"

    # ──────────────────────────────────────────────────────────
    # Nodes
    # ──────────────────────────────────────────────────────────

    @traceable(
        name="Node Initialize",
        run_type="tool",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def _node_initialize(self, state: CreditApplicationState) -> CreditApplicationState:
        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="langgraph-node",
                operation="initialize",
                application_id=state.get("application_id"),
                client_id=state.get("client_id"),
                flux_type=state.get("flux_type"),
                env=get_config().env.value,
            ),
            tags=build_trace_tags("langgraph", "initialize", state.get("flux_type")),
        )
        logger.info("[ORCHESTRATOR] Initializing (%s)", state.get("flux_type", "full"))
        if not state.get("application_id"):
            state["application_id"] = str(uuid.uuid4())
        if not state.get("created_at"):
            state["created_at"] = datetime.utcnow().isoformat()

        state["orchestrator_state"] = "INITIALIZED"
        state["processing_steps_completed"] = ["INIT"]
        state["audit_trail"] = [{
            "timestamp": state["created_at"],
            "agent": "ORCHESTRATOR",
            "action": "APPLICATION_RECEIVED",
            "details": {
                "application_id": state["application_id"],
                "flux_type": state.get("flux_type", "full"),
            },
        }]
        await self._write_audit(state, "ORCHESTRATOR", "APPLICATION_RECEIVED",
                                {"client_data_keys": sorted(state["client_data"].keys())})
        await self._persist_snapshot(state, "INITIALIZED")
        await self._emit_event("application.received",
                               {"application_id": state["application_id"],
                                "client_id": state["client_id"],
                                "flux_type": state.get("flux_type")}, state)
        return state

    @traceable(
        name="Node Guarantee",
        run_type="tool",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def _node_guarantee_a(self, state: CreditApplicationState) -> CreditApplicationState:
        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="langgraph-node",
                operation="guarantee_a",
                application_id=state.get("application_id"),
                client_id=state.get("client_id"),
                flux_type=state.get("flux_type"),
                env=get_config().env.value,
            ),
            tags=build_trace_tags("langgraph", "guarantee", state.get("flux_type")),
        )
        logger.info("[ORCHESTRATOR] Running guarantee/document workflow")
        state["orchestrator_state"] = "DOCUMENT_PROCESSING"
        state["processing_steps_completed"].append("GUARANTEE_A_START")

        require_docs = self._should_require_document_validation(state["client_data"])
        dossier = self._build_guarantee_dossier(state)
        analysis = await asyncio.to_thread(self.guarantee_agent.run, dossier, require_docs)

        logger.info("[ORCHESTRATOR] GuaranteeAgent verdict=%s ready=%s",
                    analysis.get("verdict"), analysis.get("ready_for_scoring"))

        state["guarantee_analysis"] = analysis
        state["guarantee_ready_for_scoring"] = analysis.get("ready_for_scoring", False)
        state["documents_processed"] = True
        state["missing_documents"] = analysis.get("documents_manquants", [])
        state["document_quality_score"] = (
            analysis.get("extracted_features", {}).get("document_quality_score", 0.0)
        )
        state["extracted_document_features"] = analysis.get("extracted_features", {})
        state["frontend_messages"] = (
            analysis.get("frontend_payload", {}).get("conditions_deblocage",
                                                      analysis.get("conditions_deblocage", []))
        )
        state["frontend_payload"] = analysis.get("frontend_payload", {
            "status": "READY_FOR_SCORING" if analysis.get("ready_for_scoring") else "ACTION_REQUIRED",
            "conditions_deblocage": analysis.get("conditions_deblocage", []),
            "missing_documents": analysis.get("documents_manquants", []),
        })
        state["documents"] = self._map_document_results_to_state(analysis.get("document_results", []))
        state["client_data"] = self._build_shared_feature_payload(
            state["client_data"], analysis, state["frontend_payload"]
        )

        state["audit_trail"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "GUARANTEE_A",
            "action": "DOSSIER_ANALYZED",
            "details": {
                "verdict": analysis.get("verdict"),
                "ready_for_scoring": analysis.get("ready_for_scoring"),
                "missing_documents": analysis.get("documents_manquants", []),
            },
        })
        state["processing_steps_completed"].append("GUARANTEE_A_COMPLETE")

        await self._write_audit(state, "GUARANTEE_A", "DOSSIER_ANALYZED", analysis)
        await self._persist_snapshot(state, "GUARANTEE_A")

        if self.db_client:
            await self.db_client.save_features(state["client_id"], state["client_data"], "GUARANTEE_A")
            # CONDITIONNEL routes to scoring in both Flux A and Flux B
            proceeds_to_scoring = (
                state["guarantee_ready_for_scoring"]
                or analysis.get("verdict") not in (None, "KO")
            )
            await self._save_handoff(
                state, "GUARANTEE_A",
                "SCORING_B" if proceeds_to_scoring else "FRONTEND",
                "GUARANTEE_TO_SCORING" if proceeds_to_scoring else "GUARANTEE_TO_FRONTEND",
                "READY_FOR_SCORING" if state["guarantee_ready_for_scoring"] else (
                    "CONDITIONAL_SCORING" if proceeds_to_scoring else "ACTION_REQUIRED"
                ),
                analysis.get("scoring_payload", {}) if proceeds_to_scoring else state["frontend_payload"],
            )
        return state

    @traceable(
        name="Node Scoring",
        run_type="tool",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def _node_scoring_b(self, state: CreditApplicationState) -> CreditApplicationState:
        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="langgraph-node",
                operation="scoring_b",
                application_id=state.get("application_id"),
                client_id=state.get("client_id"),
                flux_type=state.get("flux_type"),
                env=get_config().env.value,
            ),
            tags=build_trace_tags("langgraph", "scoring", state.get("flux_type")),
        )
        logger.info("[ORCHESTRATOR] Calling Scoring Agent for %s", state["application_id"])
        state = await self.scoring_agent.process(state)

        # Human-in-the-loop: low confidence
        if state.get("pd_confidence", 1.0) < 0.70:
            state["human_review_required"] = True
            state.setdefault("human_review_reasons", []).append(
                f"Confiance modèle insuffisante : {state['pd_confidence']:.2f} < 0,70"
            )

        # Human-in-the-loop: grey zone
        if state.get("in_grey_zone"):
            state["human_review_required"] = True
            state.setdefault("human_review_reasons", []).append(
                f"Score en zone grise : PD={state['final_pd_score']:.4f}"
            )

        await self._write_audit(state, "SCORING_B", "SCORING_COMPLETED", {
            "pd_score": state["final_pd_score"],
            "risk_band": state["risk_band"],
            "iterations": len(state["scoring_iterations"]),
        })
        await self._persist_snapshot(state, "SCORING_B")
        await self._emit_event("scoring.completed", {
            "application_id": state["application_id"],
            "pd_score": state["final_pd_score"],
            "risk_band": state["risk_band"],
            "flux_type": state.get("flux_type"),
        }, state)
        return state

    @traceable(
        name="Node Policy",
        run_type="tool",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def _node_policy_c(self, state: CreditApplicationState) -> CreditApplicationState:
        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="langgraph-node",
                operation="policy_c",
                application_id=state.get("application_id"),
                client_id=state.get("client_id"),
                flux_type=state.get("flux_type"),
                env=get_config().env.value,
            ),
            tags=build_trace_tags("langgraph", "policy", state.get("flux_type")),
        )
        logger.info("[ORCHESTRATOR] Calling Policy Agent for %s", state["application_id"])
        state = await self.policy_agent.process(state)

        await self._write_audit(state, "POLICY_C", "DECISION_MADE", state["policy_decision"])
        await self._persist_snapshot(state, "POLICY_C")
        await self._emit_event("policy.decided", {
            "application_id": state["application_id"],
            "decision": state["policy_decision"].get("decision"),
            "rule_id": state["policy_decision"].get("rule_id"),
            "flux_type": state.get("flux_type"),
        }, state)
        return state

    @traceable(
        name="Node XAI",
        run_type="tool",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def _node_xai_d(self, state: CreditApplicationState) -> CreditApplicationState:
        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="langgraph-node",
                operation="xai_d",
                application_id=state.get("application_id"),
                client_id=state.get("client_id"),
                flux_type=state.get("flux_type"),
                env=get_config().env.value,
                extra={"xai_mode": state.get("xai_mode")},
            ),
            tags=build_trace_tags("langgraph", "xai", state.get("xai_mode")),
        )
        logger.info("[ORCHESTRATOR] Calling XAI Agent (mode=%s) for %s",
                    state.get("xai_mode", "pro"), state["application_id"])
        state = await self.xai_agent.process(state)

        await self._persist_snapshot(state, "XAI_D")
        await self._emit_event("explainability.generated", {
            "application_id": state["application_id"],
            "xai_mode": state.get("xai_mode"),
            "top_factors": state["xai_explanation"]["top_factors"][:3],
        }, state)
        return state

    @traceable(
        name="Node Finalize",
        run_type="tool",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def _node_finalize(self, state: CreditApplicationState) -> CreditApplicationState:
        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="langgraph-node",
                operation="finalize",
                application_id=state.get("application_id"),
                client_id=state.get("client_id"),
                flux_type=state.get("flux_type"),
                env=get_config().env.value,
            ),
            tags=build_trace_tags("langgraph", "finalize", state.get("flux_type")),
        )
        logger.info("[ORCHESTRATOR] Finalizing application %s", state["application_id"])
        guarantee_analysis = state.get("guarantee_analysis", {})
        guarantee_ready = state.get("guarantee_ready_for_scoring", False)
        guarantee_verdict = guarantee_analysis.get("verdict")

        # Hard guarantee failure: only a KO verdict (document fraud, sanctions, hard eligibility).
        # CONDITIONNEL verdicts now proceed through the full pipeline so that XAI and policy
        # agents run; the final decision is overridden to REVIEW_REQUIRED after scoring below.
        is_hard_guarantee_fail = not guarantee_ready and guarantee_verdict == "KO"

        if is_hard_guarantee_fail:
            if guarantee_verdict == "KO":
                state["final_decision"] = "REJECT"
                state["decision_summary"] = guarantee_analysis.get(
                    "note_comite", "Dossier rejeté avant scoring."
                )
                state["next_action"] = "Revoir le dossier avec un conseiller"
            else:
                state["final_decision"] = "REVIEW_REQUIRED"
                state["decision_summary"] = self._build_regularization_summary(guarantee_analysis)
                # Distinguish insurance conditions (form fields) from missing documents (uploads).
                has_only_insurance_conditions = (
                    not guarantee_analysis.get("documents_manquants")
                    and guarantee_analysis.get("insurance_details", {}).get("is_blocking")
                )
                state["next_action"] = (
                    "Souscrire les assurances requises puis relancer l'analyse"
                    if has_only_insurance_conditions
                    else "Régulariser le dossier (documents et/ou assurances) puis relancer l'analyse"
                )

        elif state.get("is_application_blocked"):
            state["final_decision"] = "BLOCKED"
            state["decision_summary"] = (
                "Application bloquée — suspicion de fraude détectée. "
                f"Score fraude={state.get('fraud_analysis', {}).get('fraud_risk_score', 0):.2f}."
            )
            state["next_action"] = "Contacter le support bancaire"

        else:
            # Flux A (preview) — pas de policy_decision
            if state.get("flux_type") == "preview":
                pd = state["final_pd_score"]
                # Conditions from a conditional guarantee (e.g. missing insurance)
                conditions = guarantee_analysis.get("conditions_deblocage", []) if not guarantee_ready else []
                conditions_suffix = (
                    f" Conditions requises avant finalisation : {'; '.join(conditions[:3])}."
                    if conditions else ""
                )
                # Guard: only treat as critical error when scoring truly failed (pd=0.0).
                # Fallback heuristic scoring is not a failure — it leaves a valid pd > 0.
                scoring_failed = state.get("error_messages") and pd == 0.0
                if scoring_failed:
                    state["final_decision"] = "REVIEW_REQUIRED"
                    state["decision_summary"] = (
                        "Une erreur est survenue pendant l'analyse. "
                        "Un conseiller examinera votre dossier manuellement."
                    )
                    state["next_action"] = "Contacter votre conseiller"
                elif state.get("in_grey_zone") or (0.35 <= pd <= 0.65):
                    state["final_decision"] = "REVIEW_REQUIRED"
                    state["decision_summary"] = (
                        "Analyse approfondie requise. "
                        f"Un conseiller examinera votre dossier sous 2 jours ouvrables.{conditions_suffix}"
                    )
                    state["next_action"] = "Soumettre une demande officielle pour une analyse complète"
                elif pd < 0.35:
                    state["final_decision"] = "APPROVE"
                    state["decision_summary"] = (
                        f"Votre profil est favorable. Soumettez une demande officielle.{conditions_suffix}"
                    )
                    state["next_action"] = "Soumettre une demande officielle"
                else:
                    state["final_decision"] = "REJECT"
                    state["decision_summary"] = (
                        f"Votre profil ne remplit pas les conditions actuelles.{conditions_suffix}"
                    )
                    state["next_action"] = "Améliorer votre dossier et réessayer"
            else:
                # Flux B (full)
                policy_decision = state["policy_decision"]["decision"]
                state["final_decision"] = policy_decision

                if policy_decision == "APPROVE":
                    state["decision_summary"] = "Demande approuvée. Conditions de crédit à venir."
                    state["next_action"] = "Attendre le contact de l'équipe commerciale"
                elif policy_decision == "REJECT":
                    state["decision_summary"] = (
                        f"Demande rejetée — règle {state['policy_decision']['rule_id']}. "
                        "Le client peut réappliquer après amélioration du dossier."
                    )
                    state["next_action"] = "Améliorer le dossier et réappliquer"
                else:  # REFER / REVIEW_REQUIRED
                    state["final_decision"] = "REVIEW_REQUIRED"
                    state["decision_summary"] = (
                        "Dossier transmis au comité de crédit pour révision humaine. "
                        f"Raison(s) : {'; '.join(state.get('human_review_reasons', ['Zone grise']))}"
                    )
                    state["next_action"] = "Rester disponible pour des justificatifs complémentaires"

                # Guarantee conditions override: even if policy says APPROVE/REJECT, the file
                # cannot be disbursed while guarantee conditions remain unresolved (CONDITIONNEL).
                if not guarantee_ready and guarantee_verdict != "KO":
                    state["final_decision"] = "REVIEW_REQUIRED"
                    conditions_note = self._build_regularization_summary(guarantee_analysis)
                    base_summary = state.get("decision_summary", "")
                    state["decision_summary"] = (
                        f"{base_summary} — {conditions_note}" if base_summary else conditions_note
                    )
                    state.setdefault("human_review_reasons", []).append(
                        "Garantie conditionnelle — conditions à régulariser avant déblocage"
                    )
                    state["next_action"] = (
                        "Régulariser les conditions de garantie (assurances / documents) avant déblocage"
                    )

        # Human-in-the-loop final check
        if state.get("human_review_required") and state["final_decision"] not in ("REJECT", "BLOCKED"):
            state["final_decision"] = "REVIEW_REQUIRED"

        state["orchestrator_state"] = "COMPLETE"
        state["total_processing_time_ms"] = sum([
            state.get("ml_latency_ms", 0.0),
            state.get("xai_latency_ms", 0.0),
        ])
        state["audit_trail"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "ORCHESTRATOR",
            "action": "APPLICATION_COMPLETE",
            "details": {
                "final_decision": state["final_decision"],
                "flux_type": state.get("flux_type"),
                "human_review_required": state.get("human_review_required"),
                "total_time_ms": state["total_processing_time_ms"],
            },
        })

        await self._write_audit(state, "ORCHESTRATOR", "APPLICATION_COMPLETE", {
            "final_decision": state["final_decision"],
            "decision_summary": state["decision_summary"],
            "human_review_required": state.get("human_review_required"),
        })
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
                explanation=(
                    state["xai_explanation"].get("natural_explanation")
                    or state["decision_summary"]
                ),
                fraud_risk_score=(state["fraud_analysis"]["fraud_risk_score"]
                                  if state["fraud_analysis"] else None),
                processing_time_ms=state["total_processing_time_ms"],
            )

        await self._emit_event("application.completed", {
            "application_id": state["application_id"],
            "final_decision": state["final_decision"],
            "client_id": state["client_id"],
            "flux_type": state.get("flux_type"),
        }, state)
        annotate_current_run(
            metadata={
                "final_decision": state.get("final_decision"),
                "risk_band": state.get("risk_band"),
                "human_review_required": state.get("human_review_required", False),
                "is_application_blocked": state.get("is_application_blocked", False),
            }
        )
        return state

    # ──────────────────────────────────────────────────────────
    # Streaming entry points (SSE)
    # ──────────────────────────────────────────────────────────

    async def stream_application(
        self,
        client_id: str,
        client_data: Dict[str, Any],
        flux_type: str,
        queue: "asyncio.Queue",
    ) -> CreditApplicationState:
        """
        Runs the credit pipeline and pushes SSE event dicts into *queue*.
        Pushes None as sentinel when done (success or error).

        flux_type='preview' → Flux A (no FraudAgent, no PolicyAgent)
        flux_type='full'    → Flux B (FraudAgent parallel + PolicyAgent)
        """
        import time

        state: CreditApplicationState = {
            **deepcopy(DEFAULT_STATE),
            "application_id": str(uuid.uuid4()),
            "client_id": client_id,
            "created_at": datetime.utcnow().isoformat(),
            "client_data": client_data,
            "flux_type": flux_type,
            "xai_mode": "client" if flux_type == "preview" else "pro",
        }

        async def evt(agent: str, status: str, **kw: Any) -> None:
            await queue.put({"agent": agent, "status": status,
                             "duration_ms": None, "summary": None,
                             "rule_id": None, "fallback_reason": None, **kw})

        try:
            state = await self._node_initialize(state)

            # ── GuaranteeAgent ────────────────────────────────
            t0 = time.monotonic()
            await evt("GuaranteeAgent", "running")
            state = await self._node_guarantee_a(state)
            g_ms = int((time.monotonic() - t0) * 1000)
            dq = state.get("document_quality_score", 0.0)
            verdict = (state.get("guarantee_analysis") or {}).get("verdict", "OK")
            g_ok = state.get("guarantee_ready_for_scoring") or verdict not in (None, "KO")
            if g_ok:
                await evt("GuaranteeAgent", "done", duration_ms=g_ms,
                          summary=f"doc_quality: {dq:.2f} — verdict: {verdict}")
            else:
                await evt("GuaranteeAgent", "fallback", duration_ms=g_ms,
                          summary=f"verdict: {verdict}",
                          fallback_reason=(state.get("guarantee_analysis") or {}).get(
                              "note_comite", "Dossier incomplet"))

            if not g_ok:
                skipped = (["FraudAgent"] if flux_type == "full" else []) + \
                          ["ScoringAgent"] + (["PolicyAgent"] if flux_type == "full" else []) + \
                          ["XAIAgent"]
                for s in skipped:
                    await evt(s, "skipped")
                state = await self._node_finalize(state)
                await queue.put(self._make_final_event(state))
                await queue.put(None)
                return state

            # ── FraudAgent background (Flux B only) ───────────
            fraud_task: Optional[asyncio.Task] = None
            t_fraud: float = 0.0
            if flux_type == "full":
                await evt("FraudAgent", "running")
                t_fraud = time.monotonic()
                fraud_task = asyncio.create_task(
                    self.fraud_agent.process(deepcopy(state))
                )
            else:
                await evt("FraudAgent", "skipped")

            # ── ScoringAgent ──────────────────────────────────
            t_s = time.monotonic()
            await evt("ScoringAgent", "running")
            state = await self._node_scoring_b(state)
            s_ms = int((time.monotonic() - t_s) * 1000)
            await evt("ScoringAgent", "done", duration_ms=s_ms,
                      summary=(f"PD: {state.get('final_pd_score', 0):.3f} — "
                                f"Band: {state.get('risk_band', '?')} — "
                                f"Conf: {state.get('pd_confidence', 0):.2f}"))

            # ── Await FraudAgent ──────────────────────────────
            if fraud_task is not None:
                try:
                    fraud_result = await fraud_task
                    f_ms = int((time.monotonic() - t_fraud) * 1000)
                    fa = fraud_result.get("fraud_analysis") or {}
                    state["fraud_analysis"] = fa
                    state["fraud_check_completed"] = fraud_result.get("fraud_check_completed", False)
                    if fraud_result.get("is_application_blocked"):
                        state["is_application_blocked"] = True
                    await evt("FraudAgent", "done", duration_ms=f_ms,
                              summary=f"fraud_score: {fa.get('fraud_risk_score', 0):.3f} — "
                                      f"detected: {fa.get('fraud_detected', False)}")
                except Exception as fe:
                    logger.error("[STREAM] FraudAgent failed: %s", fe)
                    await evt("FraudAgent", "error", fallback_reason=str(fe)[:100])

            if state.get("is_application_blocked"):
                for s in (["PolicyAgent"] if flux_type == "full" else []) + ["XAIAgent"]:
                    await evt(s, "skipped")
                state["final_decision"] = "BLOCKED"
                state["decision_summary"] = (
                    "Application bloquée — suspicion de fraude. "
                    f"Score fraude: {(state.get('fraud_analysis') or {}).get('fraud_risk_score', 0):.2f}"
                )
                await queue.put(self._make_final_event(state))
                await queue.put(None)
                return state

            # ── PolicyAgent (Flux B only) ─────────────────────
            if flux_type == "full":
                t_p = time.monotonic()
                await evt("PolicyAgent", "running")
                state = await self._node_policy_c(state)
                p_ms = int((time.monotonic() - t_p) * 1000)
                pd_dec = state.get("policy_decision") or {}
                prod = pd_dec.get("recommended_product", "")
                await evt("PolicyAgent", "done", duration_ms=p_ms,
                          summary=(f"{pd_dec.get('decision', '?')} — {prod}" if prod
                                   else pd_dec.get("decision", "?")),
                          rule_id=pd_dec.get("rule_id"))
            else:
                await evt("PolicyAgent", "skipped")

            # ── XAIAgent ──────────────────────────────────────
            t_x = time.monotonic()
            await evt("XAIAgent", "running")
            state = await self._node_xai_d(state)
            x_ms = int((time.monotonic() - t_x) * 1000)
            xai = state.get("xai_explanation") or {}
            await evt("XAIAgent", "done", duration_ms=x_ms,
                      summary=f"{len(xai.get('top_factors', []))} facteurs — "
                               f"{len(xai.get('counterfactuals', []))} contrefactuels")

            # ── Finalize ──────────────────────────────────────
            state = await self._node_finalize(state)
            await queue.put(self._make_final_event(state))

        except Exception as exc:
            logger.error("[STREAM] Pipeline error: %s", exc, exc_info=True)
            await queue.put({
                "agent": "FINAL_DECISION", "decision": "HUMAN_REVIEW",
                "confidence": 0.0, "pd_score": 0.0,
                "main_reason": f"Erreur système: {str(exc)[:120]}",
            })

        await queue.put(None)
        return state

    def _make_final_event(self, state: CreditApplicationState) -> Dict[str, Any]:
        _map = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "BLOCKED": "REJECTED"}
        raw = state.get("final_decision", "REVIEW_REQUIRED")
        return {
            "agent": "FINAL_DECISION",
            "decision": _map.get(raw, "HUMAN_REVIEW"),
            "confidence": round(state.get("pd_confidence", 0.0), 4),
            "pd_score": round(state.get("final_pd_score", 0.0), 4),
            "main_reason": state.get("decision_summary", ""),
        }

    # ──────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────

    @traceable(
        name="Process Credit Application",
        run_type="chain",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def process_application(
        self,
        client_id: str,
        client_data: Dict[str, Any],
        flux_type: str = "full",
    ) -> CreditApplicationState:
        client_data = dict(client_data)
        application_id = normalize_application_id(
            client_data.get("application_id") or client_data.get("applicationId")
        )
        client_data["application_id"] = application_id
        created_at = (
            client_data.get("created_at") or
            client_data.get("createdAt") or
            datetime.utcnow().isoformat()
        )
        xai_mode = "client" if flux_type == "preview" else "pro"

        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="langgraph",
                operation="process_application",
                application_id=application_id,
                client_id=client_id,
                flux_type=flux_type,
                env=get_config().env.value,
                extra={"xai_mode": xai_mode},
            ),
            tags=build_trace_tags("langgraph", flux_type, "credit-decision"),
        )

        # ── Redis preview cache ─────────────────────────────
        cache_key: Optional[str] = None
        if flux_type == "preview" and self.redis_client:
            cache_key = self._preview_cache_key(client_id, client_data)
            cached = await self._get_preview_cache(cache_key)
            if cached:
                logger.info("[ORCHESTRATOR] Preview cache HIT for client %s", client_id)
                cached["score_preview_cached"] = True
                annotate_current_run(metadata={"score_preview_cached": True})
                return cached

        initial_state: CreditApplicationState = {
            **deepcopy(DEFAULT_STATE),
            "application_id": application_id,
            "client_id": client_id,
            "created_at": created_at,
            "client_data": client_data,
            "flux_type": flux_type,
            "xai_mode": xai_mode,
        }

        logger.info("[ORCHESTRATOR] Processing application %s (flux=%s)", application_id, flux_type)

        fraud_task: Optional[asyncio.Task] = None
        try:
            final_state = await self.graph.ainvoke(initial_state)

            # Fraud runs on Flux B after the graph — it needs guarantee_analysis populated by
            # guarantee_a, so it cannot start before the graph completes.
            if flux_type == "full":
                fraud_task = asyncio.create_task(
                    self.fraud_agent.process(deepcopy(final_state))
                )

            if fraud_task is not None:
                try:
                    fraud_state = await fraud_task
                except Exception as fraud_exc:
                    logger.error("[ORCHESTRATOR] FraudTask failed: %s", fraud_exc)
                    fraud_state = {}

                final_state["fraud_analysis"] = fraud_state.get("fraud_analysis")
                final_state["fraud_check_completed"] = fraud_state.get("fraud_check_completed", False)

                if fraud_state.get("is_application_blocked") and final_state["final_decision"] != "BLOCKED":
                    final_state["is_application_blocked"] = True
                    final_state["final_decision"] = "BLOCKED"
                    final_state["decision_summary"] = (
                        "Application bloquée après contrôle fraude asynchrone. "
                        f"Score fraude={fraud_state['fraud_analysis']['fraud_risk_score']:.2f}."
                    )
                    final_state["next_action"] = "Contacter le support bancaire"
                    final_state["audit_trail"].append({
                        "timestamp": datetime.utcnow().isoformat(),
                        "agent": "FRAUD_E",
                        "action": "APPLICATION_BLOCKED",
                        "details": fraud_state.get("fraud_analysis", {}),
                    })
                    await self._write_audit(final_state, "FRAUD_E", "APPLICATION_BLOCKED",
                                            fraud_state.get("fraud_analysis"))
                    await self._persist_snapshot(final_state, "FRAUD_OVERRIDE")

            # Cache the preview result
            if flux_type == "preview" and cache_key and self.redis_client:
                await self._set_preview_cache(cache_key, final_state)

            annotate_current_run(
                metadata={
                    "final_decision": final_state.get("final_decision"),
                    "risk_band": final_state.get("risk_band"),
                    "human_review_required": final_state.get("human_review_required", False),
                    "is_application_blocked": final_state.get("is_application_blocked", False),
                }
            )

            return final_state

        except Exception as exc:
            logger.error("[ORCHESTRATOR] Error processing application: %s", exc)
            if fraud_task is not None and not fraud_task.done():
                fraud_task.cancel()
            initial_state["error_messages"].append(str(exc))
            initial_state["final_decision"] = "REVIEW_REQUIRED"
            initial_state["decision_summary"] = "Une erreur est survenue pendant le traitement. Un conseiller examinera votre dossier."
            return initial_state

    # ──────────────────────────────────────────────────────────
    # Redis preview cache helpers
    # ──────────────────────────────────────────────────────────

    def _preview_cache_key(self, client_id: str, client_data: Dict[str, Any]) -> str:
        clean = {k: v for k, v in client_data.items()
                 if k not in {"cin_bytes", "domicile_bytes", "compromis_vente_bytes", "fiches_paie_bytes"}}
        payload = json.dumps(clean, sort_keys=True, default=str)
        digest = hashlib.sha256(f"{client_id}:{payload}".encode()).hexdigest()[:20]
        return f"preview:{digest}"

    async def _get_preview_cache(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            raw = await self.redis_client._redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _set_preview_cache(self, key: str, state: CreditApplicationState) -> None:
        try:
            safe = self._safe_for_storage(state)
            await self.redis_client._redis.setex(key, PREVIEW_CACHE_TTL, json.dumps(safe, default=str))
            logger.info("[ORCHESTRATOR] Preview cached (key=%s, ttl=24h)", key)
        except Exception as exc:
            logger.warning("[ORCHESTRATOR] Preview cache write failed: %s", exc)

    # ──────────────────────────────────────────────────────────
    # Infrastructure helpers (unchanged)
    # ──────────────────────────────────────────────────────────

    def _build_guarantee_dossier(self, state: CreditApplicationState) -> Dict[str, Any]:
        cd = dict(state["client_data"])
        loan_amount = self._to_float(cd.get("loan_amount", cd.get("AMT_CREDIT", cd.get("amount", 0))))
        monthly_income = self._to_float(cd.get("monthly_salary", cd.get("income", 0)))
        monthly_payment = self._to_float(cd.get("monthly_payment", cd.get("AMT_ANNUITY", 0)))
        debt_ratio = cd.get("debt_ratio", cd.get("DTI", cd.get("dti")))
        if debt_ratio is None and monthly_income > 0:
            debt_ratio = monthly_payment / monthly_income
        age = cd.get("client_age", cd.get("age"))
        if age is None and cd.get("DAYS_BIRTH") is not None:
            age = abs(self._to_float(cd.get("DAYS_BIRTH"))) / 365
        return {
            **cd,
            "client_id": state["client_id"],
            "credit_type": cd.get("credit_type", "consommation"),
            "loan_amount": loan_amount,
            "client_age": int(round(self._to_float(age or 0))),
            "risk_class": cd.get("risk_class"),
            "debt_ratio": debt_ratio or 0.0,
            "is_salary_domiciled": cd.get("is_salary_domiciled", True),
            "insurance_subscribed": cd.get("insurance_subscribed", []),
            "cin_bytes": cd.get("cin_bytes"),
            "fiches_paie_bytes": cd.get("fiches_paie_bytes"),
            "domicile_bytes": cd.get("domicile_bytes"),
            "compromis_vente_bytes": cd.get("compromis_vente_bytes"),
        }

    def _should_require_document_validation(self, client_data: Dict[str, Any]) -> bool:
        return client_data.get("document_workflow_enabled") is not False

    def _map_document_results_to_state(self, document_results: list) -> Dict[str, Any]:
        mapped = {}
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
        note = analysis.get("note_comite") or "Dossier à régulariser avant poursuite."
        conditions = analysis.get("conditions_deblocage", [])
        if not conditions:
            return note
        return f"{note} Actions requises : {'; '.join(conditions[:3])}."

    def _build_shared_feature_payload(self, client_data, analysis, frontend_payload):
        # Only merge actual financial features extracted by guarantee_a.
        # Orchestration metadata (verdict, frontend_payload, scoring_payload, etc.) is stored
        # in dedicated top-level state fields and must NOT flow into client_data to avoid
        # contaminating the feature vector sent to the ML server.
        combined = analysis.get("scoring_payload", {}).get("combined_features", {})
        return {
            **self._strip_document_blobs(client_data),
            **combined,
        }

    def _strip_document_blobs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in payload.items()
                if k not in {"cin_bytes", "domicile_bytes", "compromis_vente_bytes", "fiches_paie_bytes"}}

    async def _write_audit(self, state, agent, action, details=None):
        if not self.db_client:
            return
        await self.db_client.write_audit_log(
            application_id=state["application_id"],
            client_id=state["client_id"],
            agent=agent,
            action=action,
            details=self._safe_for_storage(details or {}),
        )

    async def _persist_snapshot(self, state, stage):
        if not self.db_client:
            return
        await self.db_client.save_application_state(
            application_id=state["application_id"],
            client_id=state["client_id"],
            stage=stage,
            payload=self._safe_for_storage(state),
        )

    async def _save_handoff(self, state, source_agent, target_agent, handoff_type, status, payload):
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

    async def _emit_event(self, event_type, data, state):
        if not self.kafka_producer:
            logger.debug("[ORCHESTRATOR] Event (no Kafka) %s", event_type)
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
                await self.kafka_producer.send_and_wait(topic, {
                    "timestamp": datetime.utcnow().isoformat(),
                    "event_type": event_type,
                    "data": data,
                })
        except Exception as exc:
            logger.warning("[ORCHESTRATOR] Event emit failed %s: %s", event_type, exc)

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
        if isinstance(value, (list, tuple)):
            return [self._safe_for_storage(item) for item in value]
        if isinstance(value, dict):
            return {str(k): self._safe_for_storage(v) for k, v in value.items()}
        return value

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value) if value not in (None, "") else 0.0
        except (TypeError, ValueError):
            return 0.0


async def create_orchestrator(
    feature_store=None,
    llm_client=None,
    db_client=None,
    kafka_producer=None,
    redis_client=None,
) -> OrchestratorGraph:
    return OrchestratorGraph(
        feature_store=feature_store,
        llm_client=llm_client,
        db_client=db_client,
        kafka_producer=kafka_producer,
        redis_client=redis_client,
    )
