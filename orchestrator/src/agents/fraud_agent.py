"""
AGENT E — Fraud Detection Agent
Pattern: Interruption asynchrone parallèle

Responsabilités :
1. Isolation Forest (anomalies comportementales sur profil financier)
2. Velocity Checker (même employeur sur 50+ dossiers, pics de demandes)
3. Document Inconsistency (âge CIN vs déclaré, revenus incohérents)
4. Produit fraud_score ∈ [0,1] et escalation_flag
5. interrupt_signal = True → bloque la décision finale

Tourne en parallèle — ne bloque pas les autres agents.
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.state import CreditApplicationState, FraudAnalysisResult
from src.langsmith_tracing import (
    annotate_current_run,
    build_trace_metadata,
    build_trace_tags,
    process_trace_inputs,
    process_trace_outputs,
    traceable,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Seuils de détection
# ─────────────────────────────────────────────────────────────
VELOCITY_EMPLOYER_THRESHOLD = 10   # demandes avec le même employeur / 24h
VELOCITY_INCOME_THRESHOLD = 20     # demandes dans la même tranche de revenu / 1h
FRAUD_ESCALATION_THRESHOLD = 0.50  # fraud_score ≥ seuil → escalation_flag


class IsolationForestEngine:
    """
    Isolation Forest pré-entraîné sur données synthétiques tunisiennes.
    Features : [income_log, loan_log, dti, age_norm, employment_ratio, lti]
    """

    FEATURE_NAMES = [
        "income_log",          # log(revenu mensuel)
        "loan_log",            # log(montant crédit)
        "dti",                 # ratio endettement
        "age_norm",            # âge / 70
        "employment_ratio",    # ancienneté emploi / âge
        "loan_to_income",      # crédit / (revenu × 12)
    ]

    def __init__(self) -> None:
        self._model = None
        self._trained = False
        self._init_model()

    def _init_model(self) -> None:
        try:
            from sklearn.ensemble import IsolationForest

            rng = np.random.default_rng(42)
            n = 2000

            # Profils tunisiens réalistes
            income = rng.normal(2800, 900, n).clip(500, 20000)
            loan = rng.normal(45000, 25000, n).clip(1000, 500000)
            dti = rng.beta(3, 8, n)                      # ~27 % en médiane
            age = rng.normal(38, 10, n).clip(20, 68)
            emp_years = rng.normal(6, 4, n).clip(0, 40)

            X = np.column_stack([
                np.log1p(income),
                np.log1p(loan),
                dti,
                age / 70,
                np.clip(emp_years / age, 0, 1),
                loan / (income * 12 + 1e-9),
            ]).astype(np.float32)

            self._model = IsolationForest(
                n_estimators=200,
                contamination=0.05,
                random_state=42,
                n_jobs=-1,
            )
            self._model.fit(X)
            self._trained = True
            logger.info("[FRAUD-IF] Isolation Forest trained on %d synthetic samples", n)
        except ImportError:
            logger.warning("[FRAUD-IF] scikit-learn not installed — IF scoring disabled")
        except Exception as exc:
            logger.warning("[FRAUD-IF] Training failed: %s", exc)

    def score(self, features: Dict[str, Any]) -> float:
        """Retourne un fraud score [0, 1] basé sur l'Isolation Forest."""
        if not self._trained or self._model is None:
            return 0.0

        income = float(features.get("monthly_income", 2000))
        loan = float(features.get("loan_amount", 30000))
        dti = float(features.get("debt_ratio", 0.25))
        age = float(features.get("client_age", 35))
        emp_years = float(features.get("employment_years", 5))

        x = np.array([[
            np.log1p(income),
            np.log1p(loan),
            np.clip(dti, 0, 1),
            age / 70,
            np.clip(emp_years / max(age, 1), 0, 1),
            loan / (income * 12 + 1e-9),
        ]], dtype=np.float32)

        # decision_function : plus négatif = plus anormal
        raw = float(self._model.decision_function(x)[0])
        # Normalise [−0.5, +0.3] → [1, 0] (scores observés typiques)
        fraud_score = float(np.clip((-raw - 0.1) / 0.5, 0.0, 1.0))
        return fraud_score


class VelocityChecker:
    """Vérification de la vélocité via Redis."""

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client

    async def check_employer_velocity(self, employer: str) -> int:
        """Retourne le nombre de demandes avec le même employeur dans les 24h."""
        if not self._redis or not employer:
            return 0
        key = f"fraud:velocity:employer:{hashlib.md5(employer.lower().encode()).hexdigest()[:12]}"
        return await self._incr_with_ttl(key, ttl=86400)

    async def check_income_band_velocity(self, monthly_income: float) -> int:
        """Retourne le nb de demandes dans la même tranche de revenu dans la dernière heure."""
        if not self._redis or monthly_income <= 0:
            return 0
        band = int(monthly_income // 500) * 500  # tranche 500 TND
        key = f"fraud:velocity:income:{band}"
        return await self._incr_with_ttl(key, ttl=3600)

    async def _incr_with_ttl(self, key: str, ttl: int) -> int:
        try:
            r = self._redis._redis
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, ttl)
            return int(count)
        except Exception:
            return 0


class DocumentInconsistencyChecker:
    """Détecte les incohérences entre documents et données déclarées."""

    def check(self, state: CreditApplicationState) -> Tuple[bool, List[str]]:
        """Retourne (has_inconsistency, list_of_issues)."""
        issues: List[str] = []
        cd = state.get("client_data", {})
        doc_intel = state.get("guarantee_analysis", {}).get("document_intelligence", {})

        # ── Vérification d'âge ──────────────────────────────────────
        declared_age = self._to_float(cd.get("client_age") or cd.get("age"))
        doc_age = self._to_float(doc_intel.get("applicant_info", {}).get("age"))
        if declared_age > 0 and doc_age > 0 and abs(declared_age - doc_age) > 5:
            issues.append(
                f"Incohérence d'âge : déclaré={declared_age:.0f} ans, document={doc_age:.0f} ans"
            )

        # ── Vérification revenu ──────────────────────────────────────
        declared_income = self._to_float(
            cd.get("monthly_salary") or cd.get("income") or cd.get("AMT_INCOME_TOTAL", 0) / 12
        )
        doc_income = self._to_float(
            doc_intel.get("employment_info", {}).get("net_salary")
        )
        if declared_income > 0 and doc_income > 0:
            ratio = abs(declared_income - doc_income) / max(declared_income, 1)
            if ratio > 0.30:
                issues.append(
                    f"Incohérence de revenu : déclaré={declared_income:.0f} TND, "
                    f"document={doc_income:.0f} TND (écart {ratio*100:.0f}%)"
                )

        # ── Ratio emploi/âge aberrant ────────────────────────────────
        emp_years = self._to_float(cd.get("seniority_years"))
        if declared_age > 0 and emp_years > 0 and emp_years > declared_age - 15:
            issues.append(
                f"Ancienneté incohérente : {emp_years:.0f} ans d'emploi pour {declared_age:.0f} ans"
            )

        return len(issues) > 0, issues

    @staticmethod
    def _to_float(v: Any) -> float:
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0


# ─────────────────────────────────────────────────────────────
# FraudAgent principal
# ─────────────────────────────────────────────────────────────

class FraudAgent:
    """
    Agent E — Fraud Detection (async interrupt pattern).
    Tourne en parallèle du pipeline principal.
    """

    def __init__(self, redis_client=None) -> None:
        self._iso = IsolationForestEngine()
        self._velocity = VelocityChecker(redis_client)
        self._doc_checker = DocumentInconsistencyChecker()

    @traceable(
        name="Fraud Agent",
        run_type="tool",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    async def process(self, state: CreditApplicationState) -> CreditApplicationState:
        annotate_current_run(
            metadata=build_trace_metadata(
                service="aicredits-orchestrator",
                component="agent",
                operation="fraud",
                application_id=state.get("application_id"),
                client_id=state.get("client_id"),
                flux_type=state.get("flux_type"),
            ),
            tags=build_trace_tags("agent", "fraud", state.get("flux_type")),
        )
        logger.info("[FRAUD_E] Checking fraud for application %s", state.get("application_id"))
        start = time.monotonic()

        features = self._extract_features(state)

        # ── 1. Isolation Forest ──────────────────────────────────────
        iso_score = self._iso.score(features)

        # ── 2. Velocity checks ───────────────────────────────────────
        employer = str(features.get("employer", "")).strip()
        monthly_income = float(features.get("monthly_income", 0))
        employer_count, income_count = await asyncio.gather(
            self._velocity.check_employer_velocity(employer),
            self._velocity.check_income_band_velocity(monthly_income),
        )

        velocity_anomaly = employer_count >= VELOCITY_EMPLOYER_THRESHOLD
        velocity_metrics = {
            "employer_applications_24h": employer_count,
            "income_band_applications_1h": income_count,
            "velocity_anomaly": int(velocity_anomaly),
        }

        # ── 3. Document inconsistency ────────────────────────────────
        doc_inconsistency, doc_issues = self._doc_checker.check(state)

        # ── 4. Aggregate fraud score ─────────────────────────────────
        velocity_score = min(1.0, employer_count / VELOCITY_EMPLOYER_THRESHOLD)
        doc_score = 0.4 if doc_inconsistency else 0.0
        fraud_score = round(
            0.50 * iso_score + 0.35 * velocity_score + 0.15 * doc_score, 4
        )

        escalation_flag = (
            fraud_score >= FRAUD_ESCALATION_THRESHOLD
            or velocity_anomaly
            or doc_inconsistency
        )

        # ── 5. Anomaly type ──────────────────────────────────────────
        anomaly_type: Optional[str] = None
        if velocity_anomaly and doc_inconsistency:
            anomaly_type = "VELOCITY_AND_DOCUMENT_INCONSISTENCY"
        elif velocity_anomaly:
            anomaly_type = "EMPLOYER_VELOCITY_ANOMALY"
        elif doc_inconsistency:
            anomaly_type = "DOCUMENT_INCONSISTENCY"
        elif iso_score >= 0.6:
            anomaly_type = "BEHAVIORAL_ANOMALY_IF"

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "[FRAUD_E] fraud_score=%.4f escalation=%s anomaly=%s (%.0fms)",
            fraud_score, escalation_flag, anomaly_type, elapsed_ms,
        )

        fraud_result: FraudAnalysisResult = {
            "fraud_risk_score": fraud_score,
            "is_flagged": escalation_flag,
            "anomaly_type": anomaly_type,
            "velocity_metrics": velocity_metrics,
            "biometric_verified": not doc_inconsistency,
            "interrupt_signal": escalation_flag,
        }

        state["fraud_analysis"] = fraud_result
        state["fraud_check_completed"] = True
        state["is_application_blocked"] = escalation_flag

        if escalation_flag:
            state.setdefault("human_review_reasons", []).append(
                f"Fraude suspectée — score={fraud_score:.2f} ({anomaly_type or 'IF'})"
            )
            state["human_review_required"] = True

        if doc_issues:
            state.setdefault("error_messages", [])
            state["error_messages"].extend([f"[FRAUD] {issue}" for issue in doc_issues])

        from datetime import datetime
        state.setdefault("audit_trail", []).append({
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "FRAUD_E",
            "action": "FRAUD_CHECK_COMPLETED",
            "details": {
                "fraud_score": fraud_score,
                "escalation_flag": escalation_flag,
                "anomaly_type": anomaly_type,
                "iso_score": round(iso_score, 4),
                "velocity_employer": employer_count,
                "doc_inconsistency": doc_inconsistency,
                "elapsed_ms": round(elapsed_ms),
            },
        })
        state.setdefault("processing_steps_completed", []).append("FRAUD_E_COMPLETE")
        return state

    def _extract_features(self, state: CreditApplicationState) -> Dict[str, Any]:
        cd = state.get("client_data", {})
        extracted = state.get("extracted_document_features", {})

        monthly_income = self._to_float(
            cd.get("monthly_salary") or cd.get("income") or
            (self._to_float(cd.get("AMT_INCOME_TOTAL")) / 12) or
            extracted.get("monthly_income") or 2000
        )
        loan_amount = self._to_float(
            cd.get("loan_amount") or cd.get("AMT_CREDIT") or extracted.get("loan_amount") or 0
        )
        dti = self._to_float(cd.get("debt_ratio") or cd.get("DTI") or cd.get("dti") or 0)
        age = self._to_float(cd.get("client_age") or cd.get("age") or 35)
        if age == 0 and cd.get("DAYS_BIRTH"):
            age = abs(self._to_float(cd.get("DAYS_BIRTH"))) / 365
        emp_days = self._to_float(cd.get("DAYS_EMPLOYED") or 0)
        emp_years = self._to_float(cd.get("seniority_years") or (emp_days / 365 if emp_days else 3))
        employer = str(
            cd.get("employer") or cd.get("ORGANIZATION_TYPE") or
            cd.get("employment_status") or ""
        )

        return {
            "monthly_income": monthly_income,
            "loan_amount": loan_amount,
            "debt_ratio": dti,
            "client_age": age,
            "employment_years": emp_years,
            "employer": employer,
        }

    @staticmethod
    def _to_float(v: Any) -> float:
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
