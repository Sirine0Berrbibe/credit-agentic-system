"""
AGENT D — XAI Agent (Explainability)
Pattern: Chain-of-thought structuré
Responsabilités:
1. Récupère SHAP values du Scoring Agent
2. Calcule contrefactuels ("si vous réduisez X de Y%, la décision change")
3. Appelle LLM avec contexte SHAP pour explication en langage naturel (HUMANISÉ)
4. Écrit dans le log d'audit immuable PostgreSQL
5. Retourne explication complète et transparente (GDPR)

Intégration:
- Source: SHAP values du ML endpoint
- LLM: Azure OpenAI (gpt-5.4-mini)
- DB Audit: PostgreSQL (append-only)
- Format sortie: Français + labels humains (PAS de noms techniques)
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
from src.langsmith_tracing import (
    annotate_current_run,
    build_trace_metadata,
    build_trace_tags,
    process_trace_inputs,
    process_trace_outputs,
    traceable,
)

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# FEATURE NAME MAPPING — Traduction en langage humain
# ════════════════════════════════════════════════════════════════════════════

FEATURE_LABELS = {
    # Sources externes (très important pour le score)
    "EXT_SOURCE_MEAN": "Score de crédit moyen",
    "EXT_SOURCE_MIN": "Score de crédit minimum",
    "EXT_SOURCE_MAX": "Score de crédit maximum",
    "EXT_SOURCE_1": "Source 1 de vérification du crédit",
    "EXT_SOURCE_2": "Source 2 de vérification du crédit",
    "EXT_SOURCE_3": "Source 3 de vérification du crédit",
    "EXT_SOURCE_PROD": "Produit score crédit",
    
    # Informations personnelles
    "CODE_GENDER": "Genre",
    "DAYS_BIRTH": "Âge",
    "CNT_CHILDREN": "Nombre d'enfants",
    "CNT_FAM_MEMBERS": "Nombre de personnes à charge",
    "NAME_FAMILY_STATUS": "État civil",
    "NAME_EDUCATION_TYPE": "Niveau d'études",
    "NAME_HOUSING_TYPE": "Type de logement",
    
    # Informations financières
    "AMT_INCOME_TOTAL": "Revenu annuel",
    "AMT_CREDIT": "Montant du crédit demandé",
    "AMT_ANNUITY": "Mensualité du crédit",
    "AMT_GOODS_PRICE": "Prix du bien/service financé",
    "NAME_INCOME_TYPE": "Source de revenu",
    "NAME_TYPE_SUITE": "Type de relation",
    
    # Emploi
    "DAYS_EMPLOYED": "Ancienneté au poste",
    "OCCUPATION_TYPE": "Profession",
    "ORGANIZATION_TYPE": "Secteur d'activité",
    
    # Propriété
    "FLAG_OWN_CAR": "Propriétaire d'une voiture",
    "FLAG_OWN_REALTY": "Propriétaire d'un bien immobilier",
    "OWN_CAR_AGE": "Âge du véhicule",
    
    # Contact
    "FLAG_PHONE": "Possède un téléphone",
    "FLAG_EMAIL": "Possède une adresse email",
    "FLAG_MOBIL": "Possède un téléphone mobile",
    "FLAG_EMP_PHONE": "Téléphone professionnel fourni",
    "FLAG_WORK_PHONE": "Téléphone au travail",
    "FLAG_CONT_MOBILE": "Téléphone mobile enregistré",
    
    # Ratios calculés
    "CREDIT_TERM": "Durée du crédit",
    "CREDIT_TO_GOODS": "Rapport crédit/prix",
    "DTI": "Ratio d'endettement",
    "PAYMENT_RATE": "Taux de paiement",
    
    # Localisation
    "REG_REGION_NOT_LIVE_REGION": "Changement de région",
    "REG_CITY_NOT_LIVE_CITY": "Changement de ville",
    "LIVE_REGION_NOT_WORK_REGION": "Région de résidence ≠ région de travail",
    
    # Documents et identité
    "DAYS_ID_PUBLISH": "Jours depuis publication de l'ID",
    "DAYS_LAST_PHONE_CHANGE": "Jours depuis changement de téléphone",
    "DAYS_REGISTRATION": "Jours depuis enregistrement",
    "DAYS_LAST_DL_REISSUE": "Jours depuis rénovation du permis",
    
    # Enquêtes de crédit
    "BURO_DAYS_CREDIT_max": "Ancienneté du dernier crédit",
    "BURO_DAYS_CREDIT_min": "Ancienneté du crédit le plus ancien",
    "BURO_DAYS_CREDIT_ENDDATE_max": "Temps jusqu'à fin du dernier crédit",
    "BURO_DAYS_CREDIT_ENDDATE_min": "Temps jusqu'à fin du crédit le plus ancien",
    "BURO_CREDIT_ACTIVE_CNT": "Nombre de crédits actifs",
    "BURO_CREDIT_CLOSED_CNT": "Nombre de crédits clôturés",
    "BURO_CREDIT_CNT": "Nombre total de crédits",
    "BURO_CREDIT_SUM": "Montant total des crédits",
    "BURO_CREDIT_SUM_DEBT": "Solde total dû",
    "BURO_CREDIT_SUM_LIMIT": "Limite de crédit totale",
    "BURO_CREDIT_SUM_OVERDUE": "Retards totaux",
    "BURO_CNT_CREDIT_PROLONG": "Nombre de crédits prolongés",
    "BURO_AMT_CREDIT_SUM_DEBT_max": "Solde dû maximal",
    "BURO_CREDIT_LIMIT_SUM": "Somme des limites de crédit",
    
    # Demandes précédentes
    "PREV_CREDIT_GOODS_RATIO_std": "Variation du ratio crédit/bien",
    "PREV_CREDIT_GOODS_RATIO_mean": "Ratio crédit/bien moyen",
    "PREV_DAYS_DECISION_min": "Jours depuis dernière décision",
    "PREV_DAYS_FIRST_DRAWING_max": "Jours avant 1er tirage",
    "PREV_DAYS_FIRST_DUE_max": "Jours avant 1ère échéance",
    "PREV_DAYS_LAST_DUE_max": "Jours avant dernière échéance",
    "PREV_DAYS_TERMINATION_max": "Jours avant résiliation",
    "PREV_CNT_PAYMENT": "Nombre de paiements prévus",
    "PREV_RATE_DOWN_PAYMENT": "Taux d'acompte",
    "PREV_RATE_INTEREST_PRIMARY": "Taux d'intérêt primaire",
    "PREV_RATE_INTEREST_PRIVILEGED": "Taux d'intérêt préférentiel",
    
    # Client précédents
    "PREV_NAME_CASH_LOAN_PURPOSE": "Motif du prêt cash",
    "PREV_NAME_PAYMENT_TYPE": "Type de paiement",
    "PREV_NAME_CLIENT_TYPE": "Type de client antérieur",
    "PREV_NAME_GOODS_CATEGORY": "Catégorie du bien",
    "PREV_NAME_PRODUCT_TYPE": "Type de produit antérieur",
    "PREV_NAME_SELLER_INDUSTRY": "Secteur du vendeur",
    "PREV_NAME_YIELD_GROUP": "Groupe de rendement",
    
    # Arrêt de paiement (POS)
    "POS_COUNT": "Nombre de transactions POS",
    "POS_INSTALMENT_COUNT": "Nombre d'acomptes POS",
    "POS_CASH_COUNT": "Nombre de retraits POS",
    "POS_MONTHS_BALANCE_COUNT": "Mois avec solde POS",
    "POS_MONTHS_BALANCE_MAX": "Dernier solde POS",
    "POS_MONTHS_BALANCE_MEAN": "Solde POS moyen",
    
    # Autres demandes de crédit
    "APP_INQUIRY_TYPE": "Type d'enquête",
    "APP_INQUIRY_CNT": "Nombre d'enquêtes",
    "APP_CREDIT_TYPE": "Type de crédit demandé",
    "APP_RATE_UP": "Nombre de hausses de taux",
    "APP_RATE_DOWN": "Nombre de baisses de taux",
    
    # Escaliers de téléphone et d'email
    "ELEVATORS_AVG": "Nombre moyen d'escaliers",
    "ELEVATORS_MEDI": "Nombre médian d'escaliers",
    "COMMONAREA_AVG": "Zone commune moyenne",
    "COMMONAREA_MEDI": "Zone commune médiane",
    "LIVINGAPARTMENTS_AVG": "Appartements à vivre moyen",
    "LIVINGAPARTMENTS_MEDI": "Appartements à vivre médian",
}


def translate_feature_name(feature_name: str) -> str:
    """Traduit un nom de feature technique en label humain"""
    return FEATURE_LABELS.get(feature_name, feature_name.replace("_", " "))


class CounterfactualGenerator:
    """
    Génère contrefactuels en langage humain:
    "Quelle action changerait la décision?"
    Basé sur SHAP values
    """

    DECISION_THRESHOLD = 0.5
    NON_ACTIONABLE_PATTERNS = (
        "age",
        "âge",
        "days_birth",
        "naissance",
        "marital",
        "matrimonial",
        "enfants",
        "children",
        "gouvernorat",
        "governorate",
        "études",
        "education",
        "logement",
        "housing",
    )

    @classmethod
    def _is_non_actionable(cls, feature_name: str, human_label: str) -> bool:
        normalized = f"{feature_name} {human_label}".lower()
        return any(pattern in normalized for pattern in cls.NON_ACTIONABLE_PATTERNS)

    @classmethod
    def _build_action(cls, feature_name: str, human_label: str) -> str:
        normalized = f"{feature_name} {human_label}".lower()

        if cls._is_non_actionable(feature_name, human_label):
            return ""

        if any(token in normalized for token in ("amt_credit", "montant", "amount")):
            return "Réduire le montant demandé pour alléger le risque"

        if any(token in normalized for token in ("annuity", "mensual", "monthly_payment", "monthly payment", "dti", "charge")):
            return "Réduire vos charges mensuelles ou vos remboursements en cours"

        if any(token in normalized for token in ("income", "revenu", "salaire", "salary")):
            return "Mieux justifier des revenus réguliers ou augmenter votre revenu stable"

        if any(token in normalized for token in ("duration", "term", "durée")):
            return "Allonger légèrement la durée demandée pour réduire la mensualité"

        if any(token in normalized for token in ("apport", "contribution", "down payment")):
            return "Augmenter votre apport personnel"

        if any(token in normalized for token in ("existing_credit", "credits en cours", "nombre de crédits")):
            return "Réduire ou regrouper une partie de vos crédits en cours"

        if any(token in normalized for token in ("contract", "emploi", "employed", "employer", "anciennet")):
            return "Présenter une situation professionnelle plus stable ou une ancienneté mieux justifiée"

        if any(token in normalized for token in ("realty", "real estate", "propriété", "garantie")):
            return "Ajouter une garantie complémentaire ou un co-emprunteur solide"

        if any(token in normalized for token in ("car", "vehicle", "véhicule")):
            return "Renforcer le dossier avec une garantie complémentaire si disponible"

        return ""

    @staticmethod
    def generate_counterfactuals(
        pd_score: float,
        shap_values: Dict[str, float],
        client_data: Dict[str, Any],
        risk_band: str,
    ) -> List[Dict[str, Any]]:
        """
        Génère 3-5 contrefactuels EN LANGAGE HUMAIN
        Exemple: "Améliorer votre score de crédit de 15% → Approbation"
        """

        counterfactuals = []

        top_features = sorted(
            shap_values.items(),
            key=lambda x: abs(x[1]),
            reverse=True,
        )[:5]

        # Qualitative change magnitude based on feature rank (avoids cross-unit math)
        rank_to_pct = {0: 20, 1: 30, 2: 40, 3: 50, 4: 60}

        for rank, (feature_name, shap_value) in enumerate(top_features):
            if shap_value == 0:
                continue

            human_label = translate_feature_name(feature_name)
            pct_change = rank_to_pct.get(rank, 60)
            action = CounterfactualGenerator._build_action(feature_name, human_label)
            if not action:
                continue

            if shap_value > 0:  # feature increases risk → reduce it
                if "score" in human_label.lower() or "source" in human_label.lower():
                    action = f"Améliorer votre {human_label} de {pct_change}%"
                elif "revenu" in human_label.lower() or "salaire" in human_label.lower():
                    action = f"Augmenter votre {human_label} de {pct_change}%"
                else:
                    action = f"Réduire votre {human_label} de {pct_change}%"
            else:  # feature reduces risk → maintain or increase it
                if "score" in human_label.lower() or "source" in human_label.lower():
                    action = f"Maintenir votre {human_label} à ce niveau"
                else:
                    action = f"Augmenter votre {human_label} de {pct_change}%"

            action = CounterfactualGenerator._build_action(feature_name, human_label)

            if risk_band == "ELEVE":
                impact = "APPROBATION"
            elif risk_band == "MODERE":
                impact = "MEILLEURE_SCORE"
            else:
                impact = "MAINTENIR"

            counterfactuals.append(
                {
                    "technical_name": feature_name,
                    "feature": human_label,
                    "action": action,
                    "impact": impact,
                    "shap_contribution": float(shap_value),
                    "required_change_pct": pct_change,
                }
            )

        if not counterfactuals:
            counterfactuals.append(
                {
                    "technical_name": "DOSSIER_GLOBAL",
                    "feature": "Dossier global",
                    "action": "Ajouter des justificatifs solides et réduire les engagements mensuels avant une nouvelle demande",
                    "impact": "MEILLEURE_SCORE" if risk_band != "ELEVE" else "APPROBATION",
                    "shap_contribution": 0.0,
                    "required_change_pct": 0,
                }
            )

        unique_actions = []
        seen_actions = set()
        for counterfactual in counterfactuals:
            current_action = counterfactual.get("action", "")
            if not current_action or current_action in seen_actions:
                continue
            seen_actions.add(current_action)
            unique_actions.append(counterfactual)

        return unique_actions[:5]


class XAIAgent:
    """
    Agent D — XAI (Explainable AI)
    Génère explications humanisées pour les clients
    Conforme GDPR + BCT
    """

    def __init__(self, llm_client=None, db_client=None):
        self.llm_client = llm_client
        self.db_client = db_client
        self.http_client = httpx.AsyncClient(timeout=10.0)

    @traceable(
        name="XAI Agent",
        run_type="tool",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def process(self, state: CreditApplicationState) -> CreditApplicationState:
        """Main entry point — route vers mode client ou pro selon flux."""
        xai_mode = state.get("xai_mode", "pro")
        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="agent",
                operation="xai",
                application_id=state.get("application_id"),
                client_id=state.get("client_id"),
                flux_type=state.get("flux_type"),
                extra={"xai_mode": xai_mode},
            ),
            tags=build_trace_tags("agent", "xai", xai_mode),
        )
        logger.info(
            "[XAI_D] Starting (mode=%s) for application %s",
            xai_mode, state.get("application_id"),
        )
        start_time = asyncio.get_running_loop().time()

        try:
            shap_values = self._extract_shap_values(state.get("scoring_iterations", []))
            counterfactuals = CounterfactualGenerator.generate_counterfactuals(
                pd_score=state["final_pd_score"],
                shap_values=shap_values,
                client_data=state["client_data"],
                risk_band=state["risk_band"],
            )

            if xai_mode == "client":
                xai_result = await self._build_client_result(state, shap_values, counterfactuals)
            else:
                xai_result = await self._build_pro_result(state, shap_values, counterfactuals)

            state["xai_explanation"] = xai_result
            await self._write_to_audit_db(state, xai_result)
            state["audit_trail"].append({
                "timestamp": datetime.utcnow().isoformat(),
                "agent": "XAI_D",
                "action": "GENERATED_EXPLANATION",
                "details": {
                    "xai_mode": xai_mode,
                    "shap_features_count": len(shap_values),
                    "counterfactuals_count": len(counterfactuals),
                },
            })
            state["processing_steps_completed"].append("XAI_D_COMPLETE")

        except Exception as exc:
            logger.error("[XAI_D] Error: %s", exc)
            state["error_messages"].append(f"XAI error: {exc}")

        finally:
            state["xai_latency_ms"] = (asyncio.get_running_loop().time() - start_time) * 1000
            logger.info("[XAI_D] Done in %.1fms", state["xai_latency_ms"])

        return state

    # ──────────────────────────────────────────────────────────
    # CLIENT MODE — langage naturel, pas de PD brut, actionnable
    # ──────────────────────────────────────────────────────────

    async def _build_client_result(
        self,
        state: CreditApplicationState,
        shap_values: Dict[str, float],
        counterfactuals: List[Dict[str, Any]],
    ) -> XAIExplanationResult:
        pd_score = state["final_pd_score"]
        in_grey = state.get("in_grey_zone", False) or (0.35 <= pd_score <= 0.65)

        if in_grey:
            explanation = (
                "Votre dossier nécessite une analyse approfondie de la part de nos experts. "
                "Cette vérification complémentaire est une procédure standard qui nous permet "
                "de prendre la meilleure décision pour vous. Un conseiller vous contactera "
                "sous 2 jours ouvrables pour finaliser votre demande."
            )
            return XAIExplanationResult(
                shap_values={},           # masqué côté client
                top_factors=[],           # masqué côté client
                counterfactuals=[],       # masqué côté client
                natural_explanation=explanation,
                decision_threshold=0.5,
                distance_to_threshold=abs(pd_score - 0.5),
            )

        # Score clair → explication simple et actionnable
        top_factors_client = []
        for fname, value in sorted(shap_values.items(), key=lambda x: abs(x[1]), reverse=True)[:3]:
            top_factors_client.append({
                "feature": translate_feature_name(fname),
                "shap_value": float(value),
                "impact": "augmente le risque" if value > 0 else "réduit le risque",
            })

        actionable_cfs = []
        for cf in counterfactuals[:2]:
            actionable_cfs.append({
                "action": cf.get("action", ""),
                "impact": cf.get("impact", ""),
            })

        explanation = await self._generate_client_explanation(state, top_factors_client, actionable_cfs)

        return XAIExplanationResult(
            shap_values={},
            top_factors=top_factors_client,
            counterfactuals=actionable_cfs,
            natural_explanation=explanation,
            decision_threshold=0.5,
            distance_to_threshold=abs(pd_score - 0.5),
        )

    # ──────────────────────────────────────────────────────────
    # PRO MODE — SHAP bruts, PD score, counterfactuels, audit
    # ──────────────────────────────────────────────────────────

    async def _build_pro_result(
        self,
        state: CreditApplicationState,
        shap_values: Dict[str, float],
        counterfactuals: List[Dict[str, Any]],
    ) -> XAIExplanationResult:
        top_factors = []
        for fname, value in sorted(shap_values.items(), key=lambda x: abs(x[1]), reverse=True)[:5]:
            top_factors.append({
                "technical_name": fname,
                "feature": translate_feature_name(fname),
                "shap_value": float(value),
                "impact": "augmente le risque" if value > 0 else "réduit le risque",
            })

        explanation = await self._generate_explanation(state, shap_values, counterfactuals)
        # Append audit log reference for GDPR compliance
        explanation += (
            f"\n\n[Réf. audit : application_id={state.get('application_id', 'N/A')} | "
            f"PD={state['final_pd_score']:.4f} | "
            f"modèle={state.get('ml_model_version', 'N/A')} | "
            f"règle={state.get('policy_decision', {}).get('rule_id', 'N/A')}]"
        )

        return XAIExplanationResult(
            shap_values={k: float(v) for k, v in shap_values.items()},
            top_factors=top_factors,
            counterfactuals=counterfactuals,
            natural_explanation=explanation,
            decision_threshold=0.5,
            distance_to_threshold=abs(state["final_pd_score"] - 0.5),
        )

    async def _generate_client_explanation(
        self,
        state: CreditApplicationState,
        top_factors: List[Dict[str, Any]],
        counterfactuals: List[Dict[str, Any]],
    ) -> str:
        policy_decision = state.get("policy_decision", {}).get("decision", "")
        pd_score = state["final_pd_score"]

        if self.llm_client:
            try:
                factors_text = "\n".join(
                    f"- {f['feature']} : {f['impact']}" for f in top_factors
                )
                actions_text = "\n".join(
                    f"- {cf['action']} → {cf['impact']}" for cf in counterfactuals
                )
                prompt = f"""
Tu es un conseiller bancaire bienveillant qui explique une décision de crédit à un particulier tunisien.
Décision : {policy_decision}
Facteurs principaux :
{factors_text}
Actions possibles :
{actions_text}
Écris une explication en 3–4 phrases : simple, empathique, orientée vers ce que le client peut faire.
N'utilise AUCUN terme technique. Écris en français tunisien accessible.
"""
                response = await self.llm_client.agenerate_text(prompt)
                return response.text
            except Exception:
                pass

        # Fallback template client
        top_label = top_factors[0]["feature"] if top_factors else "votre profil financier"
        action = counterfactuals[0]["action"] if counterfactuals else ""
        if policy_decision == "APPROVE":
            return (
                f"Bonne nouvelle ! Votre demande de crédit a été acceptée. "
                f"Votre dossier est solide, notamment grâce à {top_label}. "
                f"Nos équipes vous contacteront sous 24h pour les prochaines étapes."
            )
        elif policy_decision == "REJECT":
            return (
                f"Votre demande n'a pas pu être acceptée à ce stade. "
                f"Le principal facteur identifié est {top_label}. "
                f"{action + '. ' if action else ''}"
                f"Vous pouvez repostuler dans 3 mois après amélioration de votre dossier."
            )
        return (
            f"Votre dossier est en cours d'examen. "
            f"Un conseiller analysera {top_label} et vous contactera sous 2 jours ouvrables."
        )

    def _extract_shap_values(
        self, scoring_iterations: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Extract SHAP values from last scoring iteration"""
        if not scoring_iterations:
            return {}

        last_iteration = scoring_iterations[-1]
        shap_values = last_iteration.get("shap_values", {})

        if isinstance(shap_values, list):
            shap_dict = {}
            for item in shap_values:
                if isinstance(item, dict):
                    name = item.get("feature") or item.get("name")
                    value = item.get("shap_value") if item.get("shap_value") is not None else item.get("mean_abs_shap")
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
        Generate natural explanation with HUMANIZED labels
        NOT using technical feature names
        """

        if not self.llm_client:
            return self._generate_explanation_template(
                state, shap_values, counterfactuals
            )

        try:
            # Top 5 SHAP values with HUMAN labels
            top_5_shap = sorted(
                shap_values.items(),
                key=lambda x: abs(x[1]),
                reverse=True,
            )[:5]

            # Construire avec labels humains
            shap_text = "\n".join(
                [
                    f"- {translate_feature_name(feature)}: "
                    f"{value:+.4f} ({('augmente' if value > 0 else 'réduit')} le risque)"
                    for feature, value in top_5_shap
                ]
            )

            counterfactuals_text = "\n".join(
                [cf["action"] + f" → {cf['impact']}" for cf in counterfactuals[:3]]
            )

            decision_label = state.get("policy_decision", {}).get("decision") or state.get("final_decision") or "EN_COURS"
            prompt = f"""
            Vous êtes un expert en crédit très pédagogue. Expliquez simplement au client tunisien pourquoi sa demande a été REJETÉE ou APPROUVÉE.

            DECISION: {decision_label}
            Score de risque: {state['final_pd_score']:.1%}
            Niveau de confiance: {state['pd_confidence']:.0%}
            
            RAISONS PRINCIPALES (faciles à comprendre):
            {shap_text}
            
            COMMENT AMÉLIORER SA SITUATION:
            {counterfactuals_text}
            
            Écrivez une explication SIMPLE, EMPATHIQUE et DIRECTE (3-4 phrases).
            - N'utilisez PAS de termes techniques (pas de "DTI", "EXT_SOURCE", etc.)
            - Soyez encourageant si la décision peut s'améliorer
            - Répondez EN FRANÇAIS
            """

            response = await self.llm_client.agenerate_text(prompt)
            return response.text

        except Exception as e:
            logger.warning(f"[XAI_D] LLM unavailable: {e}")
            return self._generate_explanation_template(
                state, shap_values, counterfactuals
            )

    def _generate_explanation_template(
        self,
        state: CreditApplicationState,
        shap_values: Dict[str, float],
        counterfactuals: List[Dict[str, Any]],
    ) -> str:
        """Fallback explanation with human-readable labels"""

        decision = (
            state.get("policy_decision", {}).get("decision")
            or state.get("final_decision")
            or "REVIEW_REQUIRED"
        )

        if shap_values:
            top_feature_name = max(shap_values, key=lambda k: abs(shap_values[k]))
            top_feature_label = translate_feature_name(top_feature_name)
        else:
            top_feature_label = "votre profil financier"

        best_action = counterfactuals[0]["action"] if counterfactuals else ""

        if decision == "APPROVE":
            template = (
                f"Votre demande de crédit a été approuvée. "
                f"Votre profil de crédit est solide, notamment grâce à {top_feature_label}. "
                f"Les conditions du crédit vous seront communiquées sous 24 heures."
            )
        elif decision == "REJECT":
            action_text = f" {best_action}." if best_action else ""
            template = (
                f"Votre demande de crédit n'a pas pu être acceptée à ce stade. "
                f"Le facteur principal identifié est {top_feature_label}."
                f"{action_text} "
                f"Vous pourrez repostuler dans 3 mois après amélioration de votre dossier."
            )
        else:  # REVIEW_REQUIRED
            template = (
                f"Votre dossier a été transmis pour révision par un conseiller. "
                f"Nous souhaitons examiner plus attentivement {top_feature_label}. "
                f"Un expert vous contactera dans 2 jours ouvrables."
            )

        return template

    async def _write_to_audit_db(
        self, state: CreditApplicationState, xai_result: XAIExplanationResult
    ) -> None:
        """Write explanation to PostgreSQL (GDPR audit trail)"""

        if not self.db_client:
            logger.warning("[XAI_D] DB client not available")
            return

        try:
            await self.db_client.write_audit_log(
                application_id=state["application_id"],
                client_id=state["client_id"],
                agent="XAI_D",
                action="EXPLANATION_GENERATED",
                details={
                    "decision": state.get("final_decision"),
                    "top_factors": xai_result.get("top_factors", []),
                    "counterfactuals": xai_result.get("counterfactuals", []),
                    "natural_explanation": xai_result.get("natural_explanation", ""),
                    "distance_to_threshold": xai_result.get("distance_to_threshold"),
                },
            )
            logger.info("[XAI_D] Audit record written to DB")

        except Exception as e:
            logger.error("[XAI_D] Audit write failed: %s", e)
