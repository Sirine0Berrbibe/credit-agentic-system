"""
AGENT B — Scoring Agent (ReAct Pattern: Reason + Act)
Pattern: ReAct avec itérations autonomes jusqu'à 3 tentatives
Boucle jusqu'à obtenir un score de confiance >= 0.85 ou atteindre 3 itérations

Architecture:
1. Vectorize client_data à partir du Feature Store (Feast/Redis)
2. Appel HTTP au ML Server (mcp_server /predict)
3. Si PD dans zone grise (0.35-0.65) ET confiance < threshold:
   - Identifie features manquantes influentes
   - Émet un signal request_features
   - Boucle pour itération suivante
4. Sinon: retourne le score avec SHAP values

Intégration:
- Feature Store: Redis (cache) + Feast (registry)
- ML Registry: MLflow (model versioning, metrics)
- ML Server: http://localhost:8000/predict
- SHAP values retournées par le serveur ML
"""

import asyncio
import httpx
import json
import logging
import time
from typing import Optional, List, Dict, Any
from datetime import datetime
import numpy as np

from src.state import (
    CreditApplicationState,
    ScoringIterationResult,
)
from src.simplified_scoring import SimplifiedScoringEngine

logger = logging.getLogger(__name__)


class FeatureStore:
    """
    Abstraction du Feature Store (Feast + Redis)
    Récupère les features du client depuis le cache ou la DB
    """

    def __init__(self, redis_client=None, mlflow_client=None, db_client=None):
        self.redis = redis_client
        self.mlflow = mlflow_client
        self.db_client = db_client
        # En production: initialiser Feast client
        # from feast import FeatureStore as FeastFS
        # self.feature_store = FeastFS("./feature_repo")

    async def get_client_features(
        self, client_id: str, client_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Fusionne features brutes + features enrichies du Feature Store
        Redis: hot cache pour accès rapide
        """
        cached_features: Dict[str, Any] = {}
        if self.db_client:
            try:
                cached_features = await self.db_client.get_features(client_id) or {}
            except Exception as exc:
                logger.warning("[FeatureStore] DB feature lookup failed: %s", exc)

        # Merging du client_data (formulaire) avec features enrichies.
        # The live payload wins over cached shared-db values.
        enriched_features = {
            **cached_features,
            **dict(client_data),
        }

        # En production: récupérer de Feast
        # features_dict = self.feature_store.get_online_features(
        #     features=[
        #         "client_demographics:age",
        #         "client_credit:total_credit_amount",
        #         ...
        #     ],
        #     entity_rows=[{"client_id": client_id}]
        # ).to_dict()
        # enriched_features.update(features_dict)

        return enriched_features

    def get_model_metadata(self, model_name: str = "credit_scoring") -> Dict[str, Any]:
        """Récupère metadata du modèle depuis MLflow"""
        if self.mlflow:
            try:
                model = self.mlflow.get_registered_model(model_name)
                return {
                    "version": model.latest_versions[0].version,
                    "stage": model.latest_versions[0].current_stage,
                    "created_at": model.latest_versions[0].creation_time,
                }
            except Exception as e:
                logger.warning(f"MLflow unavailable: {e}")
        return {"version": "unknown", "stage": "production"}


class ScoringAgent:
    """
    Agent B — Scoring Agent (ReAct pattern)
    Responsabilités:
    1. Enrichir les features depuis Feature Store
    2. Appeler le ML Server (/predict)
    3. Boucle réactive: si zone grise, demander features supplémentaires
    4. Retourner score final avec SHAP
    """

    MAX_ITERATIONS = 3
    GREY_ZONE_MIN = 0.35
    GREY_ZONE_MAX = 0.65
    CONFIDENCE_THRESHOLD = 0.85
    ML_SERVER_URL = "http://localhost:8000"

    def __init__(self, feature_store: Optional[FeatureStore] = None):
        self.feature_store = feature_store or FeatureStore()
        self.http_client = httpx.AsyncClient(timeout=10.0)

    async def process(self, state: CreditApplicationState) -> CreditApplicationState:
        """
        Main entry point du Scoring Agent
        Implémente la boucle ReAct
        """
        logger.info(
            f"[SCORING_B] Starting ReAct loop for application {state['application_id']}"
        )

        start_time = time.time()
        state["orchestrator_state"] = "SCORING"
        state["processing_steps_completed"].append("SCORING_B_START")

        try:
            # Préparer les features
            enriched_data = await self.feature_store.get_client_features(
                state["client_id"], state["client_data"]
            )

            # Boucle réactive: jusqu'à 3 itérations
            iteration = 0
            final_result = None

            while iteration < self.MAX_ITERATIONS:
                iteration += 1
                logger.info(f"[SCORING_B] Iteration {iteration}/{self.MAX_ITERATIONS}")

                # ═══════════════════════════════════════════════════════════
                # REASON: Analyser quelles features sont disponibles
                # ═══════════════════════════════════════════════════════════

                missing_features = self._identify_missing_features(enriched_data)
                logger.info(f"[SCORING_B] Missing features: {missing_features[:5]}")

                # ═══════════════════════════════════════════════════════════
                # ACT: Appeler le ML Server
                # ═══════════════════════════════════════════════════════════

                result = await self._call_ml_server(enriched_data)

                if result is None:
                    state["error_messages"].append(
                        "ML Server unavailable, using fallback scoring"
                    )
                    result = self._fallback_scoring(enriched_data)

                # Enregistrer l'itération
                iteration_result: ScoringIterationResult = {
                    "iteration": iteration,
                    "pd_score": result["pd_score"],
                    "confidence": result["confidence"],
                    "risk_band": result["risk_band"],
                    "missing_features": missing_features,
                    "shap_values": result.get("shap_top_features", {}),
                    "model_version": result.get("model_version", "unknown"),
                }
                state["scoring_iterations"].append(iteration_result)

                # ═══════════════════════════════════════════════════════════
                # DÉCISION: Continuer la boucle ou terminer?
                # ═══════════════════════════════════════════════════════════

                in_grey_zone = (
                    self.GREY_ZONE_MIN <= result["pd_score"] <= self.GREY_ZONE_MAX
                )
                sufficient_confidence = (
                    result["confidence"] >= self.CONFIDENCE_THRESHOLD
                )

                logger.info(
                    f"[SCORING_B] Score={result['pd_score']:.4f}, "
                    f"Confidence={result['confidence']:.4f}, "
                    f"GreyZone={in_grey_zone}"
                )

                if in_grey_zone and not sufficient_confidence and iteration < self.MAX_ITERATIONS:
                    # Continuer la boucle
                    logger.info(
                        f"[SCORING_B] Zone grise détectée - demande features supplémentaires"
                    )
                    requested_features = await self._request_additional_features(
                        enriched_data, result
                    )
                    state["requested_additional_features"].update(requested_features)
                    # En production: Kafka topic pour Document Agent
                    # await kafka_producer.send("feature.request", ...)
                    continue

                else:
                    # Score acceptable ou max itérations atteint
                    final_result = result
                    state["in_grey_zone"] = in_grey_zone
                    break

            # ════════════════════════════════════════════════════════════════
            # RÉSULTATS FINAUX
            # ════════════════════════════════════════════════════════════════

            if final_result:
                state["final_pd_score"] = final_result["pd_score"]
                state["pd_confidence"] = final_result["confidence"]
                state["risk_band"] = final_result["risk_band"]
                state["ml_model_version"] = final_result.get("model_version")
                state["ml_latency_ms"] = (time.time() - start_time) * 1000

                logger.info(
                    f"[SCORING_B] ✓ Final PD Score: {final_result['pd_score']:.4f} "
                    f"({final_result['risk_band']})"
                )
                state["processing_steps_completed"].append("SCORING_B_COMPLETE")

        except Exception as e:
            logger.error(f"[SCORING_B] Error: {e}")
            state["error_messages"].append(f"Scoring error: {str(e)}")

        return state

    async def _call_ml_server(self, enriched_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Appel HTTP au ML Server (mcp_server /predict)
        Retourne: {pd_score, confidence, risk_band, shap_top_features, ...}
        
        Returns None if:
        - Server is unavailable
        - Server returns an error
        - Server indicates insufficient features (< 10% of total required)
        """
        try:
            payload = {"client_data": enriched_data}

            logger.info(f"[SCORING_B] Calling ML Server: POST {self.ML_SERVER_URL}/predict")
            response = await self.http_client.post(
                f"{self.ML_SERVER_URL}/predict",
                json=payload,
                timeout=30.0,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    # Check if ML server has enough features to make a good prediction
                    n_features_provided = result.get("n_features_provided", 0)
                    n_features_total = result.get("n_features_total", 596)
                    feature_coverage = n_features_provided / max(1, n_features_total)
                    
                    # If less than 10% of features available, use fallback
                    if feature_coverage < 0.10:
                        logger.warning(
                            f"[SCORING_B] Insufficient features: {n_features_provided}/{n_features_total} "
                            f"({feature_coverage*100:.1f}%). Using fallback scoring."
                        )
                        return None
                    
                    logger.info(f"[SCORING_B] ML Server returned: {result}")
                    return result
                else:
                    logger.error(f"[SCORING_B] ML Server error: {result.get('error')}")
                    return None
            else:
                logger.error(f"[SCORING_B] ML Server returned {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"[SCORING_B] HTTP error calling ML Server: {e}")
            return None

    def _fallback_scoring(self, enriched_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fallback: use simplified scoring engine when ML Server is unavailable
        Works with 5 core features: amount, income, age, employment_years, credit_duration
        """
        
        # Extract the 5 core features from enriched_data
        client_data = {
            'amount': enriched_data.get('AMT_CREDIT', enriched_data.get('amount', 5000)),
            'income': enriched_data.get('AMT_INCOME_TOTAL', enriched_data.get('income', 20000)),
            'age': enriched_data.get('DAYS_BIRTH', enriched_data.get('age', 45)),
            'employment_years': enriched_data.get('DAYS_EMPLOYED', enriched_data.get('employment_years', 5)),
            'credit_duration': enriched_data.get('CREDIT_TERM', enriched_data.get('credit_duration', 60))
        }
        
        # Convert DAYS_* fields to proper values if needed
        # DAYS_BIRTH is negative (days from birth), DAYS_EMPLOYED is days worked
        if client_data['age'] < 0:  # If in DAYS_BIRTH format
            client_data['age'] = abs(client_data['age']) / 365
        if client_data['employment_years'] < 0:  # If in DAYS_EMPLOYED format
            client_data['employment_years'] = abs(client_data['employment_years']) / 365
        
        # Call simplified engine (static method)
        result = SimplifiedScoringEngine.calculate_pd_score(client_data)
        
        # Format SHAP values for the state
        # Convert dict to list format that XAI agent expects
        shap_top_features = []
        if result.get('shap_values'):
            for feature_name, shap_value in sorted(
                result.get('shap_values', {}).items(),
                key=lambda x: abs(x[1]),
                reverse=True
            ):
                shap_top_features.append({
                    'feature': feature_name,
                    'shap_value': float(shap_value),
                    'impact': 'positive' if shap_value > 0 else 'negative'
                })
        
        # Map result to expected format
        return {
            "success": True,
            "pd_score": result.get('pd_score', 0.5),
            "confidence": result.get('confidence', 0.8),
            "risk_band": result.get('risk_band', 'RISQUE_MODERE'),
            "decision": result.get('decision', 'REVIEW'),
            "model_version": "simplified_heuristic_v1",
            "latency_ms": 5,
            "source": "fallback_simplified_engine",
            "shap_top_features": shap_top_features  # Add formatted SHAP values
        }

    def _identify_missing_features(self, enriched_data: Dict[str, Any]) -> List[str]:
        """
        Identifie les features critiques manquantes
        Basé sur le SHAP importance du modèle
        """
        critical_features = [
            "EXT_SOURCE_MEAN",
            "CODE_GENDER",
            "CREDIT_TERM",
            "AMT_ANNUITY",
            "CREDIT_TO_GOODS",
            "DAYS_BIRTH",
            "DAYS_EMPLOYED",
            "AMT_INCOME_TOTAL",
            "AMT_CREDIT",
        ]

        missing = [f for f in critical_features if f not in enriched_data or enriched_data[f] is None]
        return missing

    async def _request_additional_features(
        self, enriched_data: Dict[str, Any], current_result: Dict[str, Any]
    ) -> Dict[str, bool]:
        """
        En zone grise et confiance insuffisante:
        Identifie quelles features supplémentaires aideraient
        Émet un signal vers Document Agent via Kafka ou HTTP
        """

        # Features qui ont le plus d'impact selon SHAP
        high_impact_missing = [
            f for f in self._identify_missing_features(enriched_data)
            if f in [
                "EXT_SOURCE_MEAN",
                "CREDIT_TERM",
                "BURO_DAYS_CREDIT_max",
            ]
        ]

        requested = {f: True for f in high_impact_missing[:3]}  # Max 3 features

        logger.info(f"[SCORING_B] Requesting additional features: {list(requested.keys())}")

        # En production: Kafka event
        # await kafka_producer.send(
        #     "feature.request",
        #     {
        #         "application_id": application_id,
        #         "requested_features": requested,
        #         "reason": "GREY_ZONE_DETECTED"
        #     }
        # )

        return requested
