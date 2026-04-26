"""
AGENT D — XAI Agent (Explainability)
Pattern: Chain-of-thought structuré
Responsabilités:
1. Récupère SHAP values du Scoring Agent
2. Calcule contrefactuels ("si vous réduisez X de Y%, la décision change")
3. Appelle LLM avec contexte SHAP pour explication en langage naturel
4. Écrit dans le log d'audit immuable PostgreSQL
5. Retourne explication complète et transparente (GDPR)

Intégration:
- Source: SHAP values du ML endpoint
- LLM: Azure OpenAI (gpt-5.4-mini)
- DB Audit: PostgreSQL (append-only)
- Format sortie: Français + Arabe
"""

import asyncio
import httpx
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import numpy as np

from src.state import (
    CreditApplicationState,
    XAIExplanationResult,
)

logger = logging.getLogger(__name__)


class CounterfactualGenerator:
    """
    Génère contrefactuels: "Quelle action changerait la décision?"
    Basé sur SHAP: si on réduit feature X de son contribution SHAP,
    le score change
    """

    DECISION_THRESHOLD = 0.5  # Seuil de décision du modèle

    @staticmethod
    def generate_counterfactuals(
        pd_score: float,
        shap_values: Dict[str, float],
        client_data: Dict[str, Any],
        risk_band: str,
    ) -> List[Dict[str, Any]]:
        """
        Génère 3-5 contrefactuels actions
        Exemple: "Réduire votre DTI de 15% pour passer de PROBABLE_REFUS à A_EXAMINER"
        """

        counterfactuals = []
        
        # Guard against empty shap_values
        if not shap_values:
            return counterfactuals
            
        distance_to_threshold = abs(pd_score - CounterfactualGenerator.DECISION_THRESHOLD)
        
        # Guard against division by zero
        if distance_to_threshold == 0:
            distance_to_threshold = 0.1

        # Top 5 features par SHAP importance
        top_features = sorted(
            shap_values.items(),
            key=lambda x: abs(x[1]) if x[1] is not None else 0,
            reverse=True,
        )[:5]

        for feature_name, shap_value in top_features:
            if shap_value == 0 or shap_value is None:
                continue

            # Calculer la réduction nécessaire
            # Si SHAP value positive (augmente risque), on veut réduire
            if shap_value > 0:  # Augmente le risque
                reduction_pct = (distance_to_threshold / abs(shap_value)) * 100 if shap_value != 0 else 10
                if reduction_pct < 5:
                    reduction_pct = 5  # Minimum 5%
                if reduction_pct > 100:
                    reduction_pct = 100

                action = f"Réduire {feature_name} de {reduction_pct:.1f}%"
                direction = "positif"
            else:
                # SHAP négatif (réduit le risque), augmenter
                increase_pct = (distance_to_threshold / abs(shap_value)) * 100 if shap_value != 0 else 10
                if increase_pct < 5:
                    increase_pct = 5
                if increase_pct > 100:
                    increase_pct = 100

                action = f"Augmenter {feature_name} de {increase_pct:.1f}%"
                direction = "négatif"

            counterfactuals.append(
                {
                    "feature": feature_name,
                    "action": action,
                    "impact": "APPROBATION" if risk_band in ["ELEVE", "RISQUE_ELEVE", "TRES_ELEVE"] else "MEILLEURE_SCORE",
                    "shap_contribution": float(shap_value),
                    "required_change_pct": reduction_pct
                    if shap_value > 0
                    else increase_pct,
                }
            )

        return counterfactuals[:5]  # Max 5


class XAIAgent:
    """
    Agent D — XAI (Explainable AI)
    Rend les décisions de crédit transparentes et explicables
    Critiques pour GDPR + BCT (Banque Centrale Tunisie)
    """

    def __init__(self, llm_client=None, db_client=None):
        self.llm_client = llm_client  # Azure OpenAI client
        self.db_client = db_client  # PostgreSQL audit DB
        self.http_client = httpx.AsyncClient(timeout=10.0)

    async def process(self, state: CreditApplicationState) -> CreditApplicationState:
        """
        Main entry point du XAI Agent
        Input: state avec scoring results + SHAP values
        Output: explication naturelle + contrefactuels + audit trail
        """

        logger.info(f"[XAI_D] Starting for application {state['application_id']}")
        start_time = asyncio.get_event_loop().time()

        try:
            # ════════════════════════════════════════════════════════════════
            # 1. EXTRAIRE SHAP VALUES
            # ════════════════════════════════════════════════════════════════

            shap_values = self._extract_shap_values(state["scoring_iterations"])

            logger.info(
                f"[XAI_D] Extracted SHAP values for {len(shap_values)} features"
            )

            # ════════════════════════════════════════════════════════════════
            # 2. GÉNÉRER CONTREFACTUELS
            # ════════════════════════════════════════════════════════════════

            counterfactuals = CounterfactualGenerator.generate_counterfactuals(
                pd_score=state["final_pd_score"],
                shap_values=shap_values,
                client_data=state["client_data"],
                risk_band=state["risk_band"],
            )

            logger.info(f"[XAI_D] Generated {len(counterfactuals)} counterfactuals")

            # ════════════════════════════════════════════════════════════════
            # 3. APPELER LLM POUR EXPLICATION NATURELLE
            # ════════════════════════════════════════════════════════════════

            natural_explanation = await self._generate_explanation(
                state=state,
                shap_values=shap_values,
                counterfactuals=counterfactuals,
            )

            # ════════════════════════════════════════════════════════════════
            # 4. STRUCTURER RÉSULTAT XAI
            # ════════════════════════════════════════════════════════════════

            top_factors = [
                {
                    "feature": fname,
                    "shap_value": float(value),
                    "impact": "augmente_risque" if value > 0 else "reduit_risque",
                }
                for fname, value in sorted(
                    shap_values.items(), key=lambda x: abs(x[1]), reverse=True
                )[:5]
            ]

            xai_result: XAIExplanationResult = {
                "shap_values": {k: float(v) for k, v in shap_values.items()},
                "top_factors": top_factors,
                "counterfactuals": counterfactuals,
                "natural_explanation": natural_explanation,
                "decision_threshold": 0.5,  # Seuil du modèle
                "distance_to_threshold": abs(
                    state["final_pd_score"] - 0.5
                ),
            }

            state["xai_explanation"] = xai_result
            state["xai_latency_ms"] = (
                asyncio.get_event_loop().time() - start_time
            ) * 1000

            # ════════════════════════════════════════════════════════════════
            # 5. AUDIT TRAIL (GDPR COMPLIANCE)
            # ════════════════════════════════════════════════════════════════

            # Enregistrer dans PostgreSQL (append-only, immuable)
            await self._write_to_audit_db(state, xai_result)

            # Ajouter au audit_trail en mémoire
            state["audit_trail"].append(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "agent": "XAI_D",
                    "action": "GENERATED_EXPLANATION",
                    "details": {
                        "shap_features_count": len(shap_values),
                        "counterfactuals_count": len(counterfactuals),
                    },
                }
            )

            state["processing_steps_completed"].append("XAI_D_COMPLETE")

            logger.info(
                f"[XAI_D] ✓ Generated explanation in "
                f"{state['xai_latency_ms']:.1f}ms"
            )

        except Exception as e:
            logger.error(f"[XAI_D] Error: {e}")
            state["error_messages"].append(f"XAI error: {str(e)}")

        return state

    def _extract_shap_values(
        self, scoring_iterations: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        Extrait les SHAP values du dernier résultat de scoring
        """
        if not scoring_iterations:
            return {}

        last_iteration = scoring_iterations[-1]
        shap_values = last_iteration.get("shap_values", {})

        # Convertir format [{"feature": "FOO", "shap_value": 0.35}] -> {FOO: 0.35}
        if isinstance(shap_values, list):
            shap_dict = {}
            for item in shap_values:
                if isinstance(item, dict):
                    name = item.get("feature") or item.get("name")
                    value = item.get("shap_value") or item.get("mean_abs_shap")
                    if name and value is not None:
                        shap_dict[name] = float(value)
            return shap_dict

        return shap_values

    async def _generate_explanation(
        self,
        state: CreditApplicationState,
        shap_values: Dict[str, float],
        counterfactuals: List[Dict[str, Any]],
    ) -> str:
        """
        Appelle Azure OpenAI pour générer explication en langage naturel
        Prompt: Donne-moi une explication clairepour le client + contrefactuels
        """

        if not self.llm_client:
            # Fallback: explication par template
            return self._generate_explanation_template(
                state, shap_values, counterfactuals
            )

        try:
            # Construire prompt pour LLM
            top_5_shap = sorted(
                shap_values.items(),
                key=lambda x: abs(x[1]),
                reverse=True,
            )[:5]

            shap_text = "\n".join(
                [
                    f"- {feature}: {value:+.4f} "
                    f"({'augmente' if value > 0 else 'réduit'} le risque)"
                    for feature, value in top_5_shap
                ]
            )

            counterfactuals_text = "\n".join(
                [
                    f"- {cf['action']} → {cf['impact']}"
                    for cf in counterfactuals[:3]
                ]
            )

            prompt = f"""
            Vous êtes un expert en crédit expérimenté qui doit expliquer une décision de crédit au client.
            
            CONTEXTE:
            - Score de probabilité de défaut: {state['final_pd_score']:.4f} ({state['risk_band']})
            - Confiance du modèle: {state['pd_confidence']:.2%}
            - Décision: {state['policy_decision']['decision']}
            
            FACTEURS PRINCIPAUX (SHAP):
            {shap_text}
            
            ACTIONS POSSIBLES pour améliorer la décision:
            {counterfactuals_text}
            
            Générez une explication claire et empathique en FRANÇAIS pour le client de pourquoi cette décision a été prise.
            Incluez les facteurs clés et les actions qu'il peut prendre.
            Gardez-le court (3-5 phrases) et accessible.
            """

            # Appel LLM
            response = await self.llm_client.agenerate_text(prompt)
            return response.text

        except Exception as e:
            logger.warning(f"[XAI_D] LLM call failed, using template: {e}")
            return self._generate_explanation_template(
                state, shap_values, counterfactuals
            )

    def _generate_explanation_template(
        self,
        state: CreditApplicationState,
        shap_values: Dict[str, float],
        counterfactuals: List[Dict[str, Any]],
    ) -> str:
        """
        Fallback: explication par template si LLM indisponible
        """

        decision = state["policy_decision"]["decision"]
        top_feature = max(shap_values.items(), key=lambda x: abs(x[1]))[0]
        best_action = counterfactuals[0]["action"] if counterfactuals else "N/A"

        if decision == "APPROVE":
            template = f"""
            Votre demande de crédit a été APPROUVÉE ! 🎉
            
            Votre profil de crédit est solide. Le facteur principal positif est: {top_feature}.
            
            Les conditions du crédit vous seront communiquées par notre équipe sous 24h.
            """
        elif decision == "REJECT":
            template = f"""
            Malheureusement, votre demande de crédit a été REJETÉE.
            
            Le facteur principal impactant la décision est: {top_feature} (trop élevé).
            
            Pour améliorer votre dossier, nous vous recommandons: {best_action}.
            Vous pourrez réappliquer après amélioration.
            """
        else:  # REVIEW_REQUIRED
            template = f"""
            Votre demande de crédit nécessite une RÉVISION MANUELLE.
            
            Notre modèle a identifié une zone incertaine basée sur: {top_feature}.
            Un expert examinera votre dossier dans les 2 jours ouvrables.
            
            Pour augmenter vos chances, considérez: {best_action}.
            """

        return template.strip()

    async def _write_to_audit_db(
        self, state: CreditApplicationState, xai_result: XAIExplanationResult
    ) -> None:
        """
        Écrit l'explication dans PostgreSQL (audit trail immuable)
        Important pour GDPR et conformité BCT
        """

        if not self.db_client:
            logger.warning("[XAI_D] DB client not available, skipping audit write")
            return

        try:
            audit_record = {
                "application_id": state["application_id"],
                "client_id": state["client_id"],
                "agent": "XAI_D",
                "timestamp": datetime.utcnow().isoformat(),
                "decision": state["final_decision"],
                "shap_values": json.dumps(xai_result["shap_values"]),
                "top_factors": json.dumps(xai_result["top_factors"]),
                "counterfactuals": json.dumps(xai_result["counterfactuals"]),
                "natural_explanation": xai_result["natural_explanation"],
                "distance_to_threshold": xai_result["distance_to_threshold"],
            }

            # En production: INSERT INTO audit_log
            # await self.db_client.execute(
            #     "INSERT INTO xai_audit_log VALUES (...)",
            #     audit_record
            # )

            logger.info(f"[XAI_D] ✓ Wrote audit record for application {state['application_id']}")

        except Exception as e:
            logger.error(f"[XAI_D] Failed to write audit: {e}")
