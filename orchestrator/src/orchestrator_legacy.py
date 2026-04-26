"""
Orchestrator Agent - Coordinateur Principal
Route les demandes aux agents appropriés et consolide les résultats
Built for parallel execution and microservice architecture
"""
from typing import Any, Dict, Optional, List
from dataclasses import dataclass
from pydantic import BaseModel
from src.base_agent import BaseAgent, AgentRole, Tool, AgentThought, AgentAction
from src.llm_client import AzureOpenAIClient
from agents.scorer_agent import ScorerAgent
from agents.analyzer_agent import AnalyzerAgent
from agents.risk_assessor_agent import RiskAssessorAgent
from config.settings import get_config
import asyncio
import json


class CreditDecisionRequest(BaseModel):
    """Requête de décision de crédit"""
    client_id: str
    client_data: Dict[str, Any]
    decision_type: str = "full_assessment"  # full_assessment|quick_score|risk_only
    priority: str = "normal"  # normal|high|urgent


class CreditDecisionResponse(BaseModel):
    """Réponse de décision de crédit"""
    decision: str  # approved|rejected|review_required
    primary_score: float
    confidence: float
    risk_level: str
    analysis_summary: Dict[str, Any]
    recommendations: List[str]
    requires_human_review: bool
    orchestrator_notes: str


@dataclass
class DecisionRules:
    """Règles de décision basées sur scores et risques"""
    approve_score_threshold = 0.7
    reject_score_threshold = 0.3
    high_risk_threshold = 75
    review_required_threshold = 85


class OrchestratorAgent(BaseAgent):
    """
    Agent Orchestrateur - Coordinateur principal
    
    Responsabilités:
    1. Router requêtes aux agents spécialisés
    2. Paralléliser les analyses
    3. Consolider les résultats
    4. Prendre une décision finale
    5. Générer explications
    """

    def __init__(self):
        super().__init__(agent_id="orchestrator-main", role=AgentRole.ORCHESTRATOR)
        self.config = get_config()
        self.llm_client = AzureOpenAIClient(self.config.azure_openai)
        self.decision_rules = DecisionRules()
        
        # Agents spécialisés
        self.scorer_agent = ScorerAgent()
        self.analyzer_agent = AnalyzerAgent()
        self.risk_assessor = RiskAssessorAgent()
        
        self._register_tools()

    def _register_tools(self):
        """Enregistre les outils du coordinateur"""
        
        # Tool: Dispatch to specialized agents
        dispatch_tool = Tool(
            name="dispatch_analysis",
            description="Dépêche l'analyse aux agents spécialisés en parallèle",
            handler=self._dispatch_to_agents,
            parameters={
                "type": "object",
                "properties": {
                    "client_data": {"type": "object"},
                    "decision_type": {"type": "string", "enum": ["full_assessment", "quick_score", "risk_only"]}
                },
                "required": ["client_data"]
            }
        )
        self.register_tool(dispatch_tool)

        # Tool: Consolidate results
        consolidate_tool = Tool(
            name="consolidate_results",
            description="Consolide les résultats des agents spécialisés",
            handler=self._consolidate_results,
            parameters={
                "type": "object",
                "properties": {
                    "analysis_results": {"type": "object"},
                    "risk_results": {"type": "object"},
                    "scoring_results": {"type": "object"},
                },
                "required": ["analysis_results"]
            }
        )
        self.register_tool(consolidate_tool)

        # Tool: Make decision
        decision_tool = Tool(
            name="make_final_decision",
            description="Prend la décision finale basée sur les données consolidées",
            handler=self._make_final_decision,
            parameters={
                "type": "object",
                "properties": {
                    "consolidated_data": {"type": "object"}
                },
                "required": ["consolidated_data"]
            }
        )
        self.register_tool(decision_tool)

    async def _dispatch_to_agents(self, client_data: Dict[str, Any], decision_type: str = "full_assessment") -> Dict[str, Any]:
        """
        Dépêche l'analyse aux agents spécialisés
        Phase 1: Analyzer en premier (pour enrichir les données)
        Phase 2: Scorer + RiskAssessor en parallèle (avec données enrichies)
        """
        self.add_message("system", f"Dispatching analysis for decision type: {decision_type}")

        # ═══════════════════════════════════════════════════════════
        # PHASE 1: Analyzer (toujours en premier - enrichit les données)
        # ═══════════════════════════════════════════════════════════
        self.analyzer_agent.reset_state()
        self.analyzer_agent.state.metadata["client_data"] = client_data
        analyzer_result = await self.analyzer_agent.run_react_loop(
            input_data={"client_data": client_data}
        )
        
        # Enrichir client_data avec les résultats de l'analyse
        enriched_client_data = client_data.copy()
        if analyzer_result.get("success"):
            enriched_analysis = analyzer_result.get("analysis", {}).get("enriched_data", {})
            enriched_client_data.update(enriched_analysis)

        # ═══════════════════════════════════════════════════════════
        # PHASE 2: Scorer + RiskAssessor en parallèle
        # ═══════════════════════════════════════════════════════════
        tasks = []
        results = {"analysis": analyzer_result}

        # Task 1: Scoring (si full ou quick)
        if decision_type in ["full_assessment", "quick_score"]:
            self.scorer_agent.reset_state()
            self.scorer_agent.state.metadata["client_data"] = enriched_client_data
            tasks.append(
                self.scorer_agent.run_react_loop(input_data={"client_data": enriched_client_data})
            )

        # Task 2: Risk Assessment (si full ou risk_only)
        if decision_type in ["full_assessment", "risk_only"]:
            self.risk_assessor.reset_state()
            # ✅ Passer les résultats d'analyse au risk assessor
            self.risk_assessor.state.metadata["client_analysis"] = analyzer_result
            self.risk_assessor.state.metadata["client_data"] = enriched_client_data
            tasks.append(
                self.risk_assessor.run_react_loop(
                    input_data={
                        "client_data": enriched_client_data,
                        "analysis": analyzer_result
                    }
                )
            )

        # Exécution parallèle des tâches phase 2
        if tasks:
            parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Mapper les résultats
            task_idx = 0
            if decision_type in ["full_assessment", "quick_score"]:
                results["scoring"] = parallel_results[task_idx]
                task_idx += 1
            if decision_type in ["full_assessment", "risk_only"]:
                results["risk_assessment"] = parallel_results[task_idx]

        return results

    async def _consolidate_results(self, analysis_results: Dict[str, Any], 
                                    risk_results: Optional[Dict[str, Any]] = None,
                                    scoring_results: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Consolide les résultats des différents agents"""
        
        consolidated = {
            "client_analysis": analysis_results,
            "risk_assessment": risk_results or {},
            "scoring": scoring_results or {},
            "consolidation_timestamp": str(datetime.utcnow()),
        }

        # Extraire les métriques clés
        metrics = {
            "has_risk_data": bool(risk_results),
            "has_score": bool(scoring_results and scoring_results.get("success")),
            "analysis_success": analysis_results.get("success", False),
        }

        consolidated["metrics"] = metrics
        self.state.metadata["consolidated"] = consolidated

        return consolidated

    async def _make_final_decision(self, consolidated_data: Dict[str, Any]) -> Dict[str, Any]:
        """Applique les règles de décision pour créer la décision finale"""
        
        decision = "review_required"
        primary_score = 0.5
        confidence = 0.0
        risk_level = "medium"
        requires_review = False
        factors = []

        # Récupérer le score si disponible
        scoring = consolidated_data.get("scoring", {})
        if scoring.get("success"):
            primary_score = scoring.get("score", 0.5)
            confidence = scoring.get("confidence", 0.0)
            factors.append(f"ML Score: {primary_score:.2f}")

        # Récupérer l'évaluation des risques
        risk_assessment = consolidated_data.get("risk_assessment", {})
        if risk_assessment:
            risk_score = risk_assessment.get("risk_assessment", {}).get("score", {}).get("risk_score", 50)
            risk_level = risk_assessment.get("risk_assessment", {}).get("score", {}).get("risk_level", "medium")
            factors.append(f"Risk Score: {risk_score}")

            if risk_score > self.decision_rules.high_risk_threshold:
                requires_review = True

        # Appliquer la logique de décision
        if requires_review:
            decision = "review_required"
        elif primary_score >= self.decision_rules.approve_score_threshold:
            decision = "approved"
        elif primary_score <= self.decision_rules.reject_score_threshold:
            decision = "rejected"
        else:
            decision = "review_required"

        # Recommandations
        recommendations = []
        if risk_level in ["high", "very_high"]:
            recommendations.append("Réduction du montant de crédit recommandée")
            recommendations.append("Examen approfondi requis")
        if primary_score < 0.5:
            recommendations.append("Formation financière suggérée")

        return {
            "decision": decision,
            "primary_score": primary_score,
            "confidence": confidence,
            "risk_level": risk_level,
            "requires_review": requires_review,
            "factors": factors,
            "recommendations": recommendations,
        }

    async def think(self, input_data: Dict[str, Any]) -> AgentThought:
        """Réfléchit rapidement sur la stratégie (sans LLM)"""
        
        decision_type = input_data.get("decision_type", "full_assessment")
        
        # Pas besoin d'appeler le LLM - la décision est simple
        thought = f"Orchestrating {decision_type} analysis: will activate Analyzer, then parallel Scorer + RiskAssessor"

        return AgentThought(
            content=thought,
            confidence=1.0,
            reasoning_type="planning"
        )

    async def decide_action(self, thought: AgentThought) -> Optional[AgentAction]:
        """Décide déterministically le flux d'exécution"""
        num_actions = len(self.state.action_history)

        if num_actions == 0:
            # Étape 1: Lancer l'analyse parallèle
            return AgentAction(
                tool_name="dispatch_analysis",
                tool_input={
                    "client_data": self.state.metadata.get("client_data", {}),
                    "decision_type": self.state.metadata.get("decision_type", "full_assessment")
                },
                thought=thought.content
            )
        elif num_actions == 1:
            # Étape 2: Consolider les résultats
            parallel_results = self.state.observations[0].result if self.state.observations else {}
            return AgentAction(
                tool_name="consolidate_results",
                tool_input={
                    "analysis_results": parallel_results.get("analysis", {}),
                    "risk_results": parallel_results.get("risk_assessment", {}),
                    "scoring_results": parallel_results.get("scoring", {}),
                },
                thought=thought.content
            )
        elif num_actions == 2:
            # Étape 3: Prendre la décision finale
            consolidated = self.state.metadata.get("consolidated", {})
            return AgentAction(
                tool_name="make_final_decision",
                tool_input={"consolidated_data": consolidated},
                thought=thought.content
            )
        else:
            return None  # Fin

    async def process(self, input_data: Dict[str, Any]) -> CreditDecisionResponse:
        """Produit la réponse finale de décision"""
        
        final_decision = None
        for obs in self.state.observations:
            if obs.tool_name == "make_final_decision":
                final_decision = obs.result
                break

        if not final_decision:
            final_decision = {
                "decision": "review_required",
                "primary_score": 0.5,
                "confidence": 0.0,
                "risk_level": "unknown",
                "requires_review": True,
                "recommendations": ["Données insuffisantes pour décision automatique"],
            }

        response = CreditDecisionResponse(
            decision=final_decision.get("decision", "review_required"),
            primary_score=final_decision.get("primary_score", 0.5),
            confidence=final_decision.get("confidence", 0.0),
            risk_level=final_decision.get("risk_level", "medium"),
            analysis_summary=self.state.metadata.get("consolidated", {}),
            recommendations=final_decision.get("recommendations", []),
            requires_human_review=final_decision.get("requires_review", False),
            orchestrator_notes=f"Decision reached after {len(self.state.thought_chain)} thoughts and {len(self.state.action_history)} actions"
        )

        return response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.llm_client.close()


# Import datetime
from datetime import datetime
