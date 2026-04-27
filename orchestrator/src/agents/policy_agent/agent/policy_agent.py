"""
Policy Agent — RAG + FAISS + Azure OpenAI GPT-4.1
Vérifie les règles métier BCT : DTI, LTV, éligibilité produit,
Centrale des Risques, conformité réglementaire.
Retourne APPROVE / REFER / REJECT avec le rule_id déclenchant.
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from openai import AzureOpenAI
from pydantic import BaseModel

from src.agents.policy_agent.agent.prompts import DECISION_PROMPT_TEMPLATE, SYSTEM_PROMPT
from src.agents.policy_agent.config import settings
from src.state import CreditApplicationState

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "knowledge_base"
FAISS_CACHE_DIR = Path(__file__).parent.parent / ".faiss_cache"


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

class PolicyDecision(BaseModel):
    decision: str  # APPROVE | REFER | REJECT
    rule_id: str
    rule_name: str
    rules_matched: List[str]
    confidence_score: float
    recommended_product: Optional[str]
    product_terms: Optional[Dict[str, Any]]
    reasoning: str
    rag_chunks_used: List[str]
    hard_rules_triggered: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# RAG Engine
# ---------------------------------------------------------------------------

class RAGEngine:
    """Chunking, embedding et retrieval FAISS sur la knowledge base."""

    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2"):
        self._chunks: List[str] = []
        self._metadata: List[Dict[str, str]] = []
        self._index = None
        self._embedding_model = None
        self._model_name = embedding_model
        self._loaded = False

    def _lazy_load(self) -> None:
        if self._loaded:
            return
        try:
            from sentence_transformers import SentenceTransformer
            import faiss
            self._faiss = faiss
            self._embedding_model = SentenceTransformer(self._model_name)
            self._loaded = True
        except ImportError as exc:
            raise RuntimeError(
                "RAG dependencies missing. Run: pip install sentence-transformers faiss-cpu"
            ) from exc

    def build_index(self, kb_dir: Path) -> None:
        self._lazy_load()
        chunks, metadata = self._load_and_chunk(kb_dir)
        self._chunks = chunks
        self._metadata = metadata

        logger.info("[POLICY-RAG] Embedding %d chunks...", len(chunks))
        embeddings = self._embedding_model.encode(chunks, show_progress_bar=False)
        embeddings = np.array(embeddings, dtype=np.float32)

        dim = embeddings.shape[1]
        index = self._faiss.IndexFlatIP(dim)
        # Normalize for cosine similarity
        self._faiss.normalize_L2(embeddings)
        index.add(embeddings)
        self._index = index
        logger.info("[POLICY-RAG] FAISS index built with %d vectors (dim=%d)", len(chunks), dim)

    def save(self, cache_dir: Path) -> None:
        import faiss
        cache_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(cache_dir / "policy.faiss"))
        with open(cache_dir / "chunks.json", "w", encoding="utf-8") as f:
            json.dump({"chunks": self._chunks, "metadata": self._metadata}, f, ensure_ascii=False)
        logger.info("[POLICY-RAG] Index saved to %s", cache_dir)

    def load(self, cache_dir: Path) -> bool:
        try:
            self._lazy_load()
            import faiss
            self._index = faiss.read_index(str(cache_dir / "policy.faiss"))
            with open(cache_dir / "chunks.json", encoding="utf-8") as f:
                data = json.load(f)
            self._chunks = data["chunks"]
            self._metadata = data["metadata"]
            logger.info("[POLICY-RAG] Loaded index from cache (%d chunks)", len(self._chunks))
            return True
        except Exception:
            return False

    def retrieve(self, query: str, k: int = 6) -> List[Tuple[str, Dict[str, str], float]]:
        """Return top-k (chunk, metadata, score) tuples."""
        self._lazy_load()
        if self._index is None:
            return []
        q_emb = self._embedding_model.encode([query], show_progress_bar=False)
        q_emb = np.array(q_emb, dtype=np.float32)
        self._faiss.normalize_L2(q_emb)
        scores, indices = self._index.search(q_emb, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            results.append((self._chunks[idx], self._metadata[idx], float(score)))
        return results

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def _load_and_chunk(self, kb_dir: Path) -> Tuple[List[str], List[Dict[str, str]]]:
        chunks: List[str] = []
        metadata: List[Dict[str, str]] = []
        md_files = sorted(kb_dir.glob("*.md"))
        if not md_files:
            logger.warning("[POLICY-RAG] No markdown files found in %s", kb_dir)
            return chunks, metadata

        for md_file in md_files:
            text = md_file.read_text(encoding="utf-8")
            file_chunks = self._chunk_by_sections(text)
            for chunk in file_chunks:
                chunk = chunk.strip()
                if len(chunk) < 80:
                    continue
                chunks.append(chunk)
                metadata.append({"source": md_file.name, "preview": chunk[:80]})

        logger.info("[POLICY-RAG] Loaded %d chunks from %d files", len(chunks), len(md_files))
        return chunks, metadata

    def _chunk_by_sections(self, text: str) -> List[str]:
        """Split markdown on H2/H3 headers for clean RAG chunks."""
        sections = re.split(r"\n(?=#{1,3} )", text)
        return [s.strip() for s in sections if s.strip()]


# ---------------------------------------------------------------------------
# Hard Rules Engine
# ---------------------------------------------------------------------------

class HardRulesEngine:
    """Règles déterministes strictes — aucune intervention LLM."""

    BCT_MAX_DTI = 0.40
    BCT_MAX_DTI_INDEPENDENT = 0.33
    BCT_MIN_AGE = 18
    BCT_MAX_AGE_CONSO_AUTO = 65
    BCT_MAX_AGE_AT_MATURITY = 70
    GREY_ZONE_LOW = 0.35
    GREY_ZONE_HIGH = 0.65

    def evaluate(self, features: Dict[str, Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        # --- DTI ---
        dti = float(features.get("debt_ratio", 0.0))
        employment = str(features.get("employment_status", "")).lower()
        is_independent = any(k in employment for k in ("indépendant", "liberal", "indep", "professionnel"))
        dti_limit = self.BCT_MAX_DTI_INDEPENDENT if is_independent else self.BCT_MAX_DTI

        results.append({
            "rule_id": "BCT-2024-DTI-001",
            "rule_name": "Taux d'endettement maximal BCT",
            "passed": dti <= dti_limit,
            "value": f"{dti * 100:.1f} %",
            "threshold": f"{dti_limit * 100:.0f} %",
            "blocking": True,
            "decision_if_failed": "REJECT",
        })

        # --- Age minimum ---
        age = int(features.get("client_age", 0))
        results.append({
            "rule_id": "BCT-2024-AGE-001",
            "rule_name": "Âge minimum emprunteur",
            "passed": age >= self.BCT_MIN_AGE,
            "value": f"{age} ans",
            "threshold": f"{self.BCT_MIN_AGE} ans",
            "blocking": True,
            "decision_if_failed": "REJECT",
        })

        # --- Age consommation/auto ---
        credit_type = str(features.get("credit_type", "")).lower()
        if credit_type in ("auto", "consommation", "conso", "personnel"):
            results.append({
                "rule_id": "BCT-2024-AGE-003",
                "rule_name": "Âge maximum crédit consommation/auto",
                "passed": age <= self.BCT_MAX_AGE_CONSO_AUTO,
                "value": f"{age} ans",
                "threshold": f"{self.BCT_MAX_AGE_CONSO_AUTO} ans",
                "blocking": True,
                "decision_if_failed": "REJECT",
            })

        # --- Age à l'échéance ---
        duration_months = int(features.get("loan_duration_months", 60))
        age_at_maturity = age + duration_months / 12
        results.append({
            "rule_id": "BCT-2024-AGE-002",
            "rule_name": "Âge à l'échéance ≤ 70 ans",
            "passed": age_at_maturity <= self.BCT_MAX_AGE_AT_MATURITY,
            "value": f"{age_at_maturity:.1f} ans",
            "threshold": f"{self.BCT_MAX_AGE_AT_MATURITY} ans",
            "blocking": True,
            "decision_if_failed": "REJECT",
        })

        # --- CR-BCT classification ---
        cr_class = int(features.get("cr_bct_class", 0))
        results.append({
            "rule_id": "CR-BCT-CLASS-002",
            "rule_name": "Classification Centrale des Risques",
            "passed": cr_class <= 2,
            "value": f"Classe {cr_class}",
            "threshold": "Classe ≤ 2",
            "blocking": cr_class >= 3,
            "decision_if_failed": "REJECT" if cr_class >= 3 else "REFER",
        })

        # --- Sanctions check ---
        on_sanctions_list = bool(features.get("on_sanctions_list", False))
        results.append({
            "rule_id": "CR-BCT-SANC-001",
            "rule_name": "Vérification listes de sanctions",
            "passed": not on_sanctions_list,
            "value": "Oui" if on_sanctions_list else "Non",
            "threshold": "Non présent",
            "blocking": True,
            "decision_if_failed": "REJECT",
        })

        # --- Grey zone PD ---
        pd_score = float(features.get("pd_score", 0.0))
        in_grey = self.GREY_ZONE_LOW <= pd_score <= self.GREY_ZONE_HIGH
        results.append({
            "rule_id": "RISK-INT-GREY-001",
            "rule_name": "Zone grise PD — human-in-the-loop",
            "passed": not in_grey,
            "value": f"PD={pd_score:.4f}",
            "threshold": f"[{self.GREY_ZONE_LOW}, {self.GREY_ZONE_HIGH}]",
            "blocking": False,
            "decision_if_failed": "REFER",
        })

        # --- Model confidence ---
        confidence = float(features.get("pd_confidence", 1.0))
        results.append({
            "rule_id": "RISK-INT-CONF-001",
            "rule_name": "Confiance du modèle ≥ 0,70",
            "passed": confidence >= 0.70,
            "value": f"{confidence:.4f}",
            "threshold": "0,70",
            "blocking": False,
            "decision_if_failed": "REFER",
        })

        # --- Loan-to-income ratio ---
        loan_amount = float(features.get("loan_amount", 0.0))
        monthly_income = float(features.get("monthly_income", 1.0))
        annual_income = monthly_income * 12
        lti = loan_amount / annual_income if annual_income > 0 else 999
        lti_limit = 5.0 if credit_type in ("immobilier", "immo") else 8.0
        results.append({
            "rule_id": "RISK-INT-CUM-002",
            "rule_name": "Ratio prêt/revenu annuel",
            "passed": lti <= lti_limit,
            "value": f"{lti:.2f}×",
            "threshold": f"≤ {lti_limit}×",
            "blocking": lti > lti_limit * 1.1,
            "decision_if_failed": "REFER" if lti <= lti_limit * 1.1 else "REJECT",
        })

        return results

    def aggregate_decision(self, rule_results: List[Dict[str, Any]]) -> Tuple[str, str, List[str]]:
        """Return (decision, triggering_rule_id, all_matched_rule_ids)."""
        matched_ids = [r["rule_id"] for r in rule_results]

        # Blocking failures → REJECT
        for r in rule_results:
            if not r["passed"] and r["blocking"] and r.get("decision_if_failed") == "REJECT":
                return "REJECT", r["rule_id"], matched_ids

        # Non-blocking failures → REFER
        for r in rule_results:
            if not r["passed"] and r.get("decision_if_failed") == "REFER":
                return "REFER", r["rule_id"], matched_ids

        return "APPROVE", "RISK-INT-BAND-001", matched_ids


# ---------------------------------------------------------------------------
# PolicyAgent
# ---------------------------------------------------------------------------

class PolicyAgent:
    """Agent C — Policy, BCT Compliance & RAG"""

    def __init__(self) -> None:
        self._rag = RAGEngine(embedding_model=settings.embedding_model)
        self._hard_rules = HardRulesEngine()
        self._openai: Optional[AzureOpenAI] = None
        self._rag_ready = False
        self._initialize()

    def _initialize(self) -> None:
        # Azure OpenAI
        if settings.azure_openai_key and settings.azure_openai_endpoint:
            try:
                self._openai = AzureOpenAI(
                    azure_endpoint=settings.azure_openai_endpoint,
                    api_key=settings.azure_openai_key,
                    api_version=settings.azure_openai_api_version,
                )
                logger.info("[POLICY] Azure OpenAI client initialized")
            except Exception as exc:
                logger.warning("[POLICY] Could not initialize Azure OpenAI: %s", exc)

        # RAG index
        try:
            if not self._rag.load(FAISS_CACHE_DIR):
                logger.info("[POLICY] Building RAG index from knowledge base...")
                self._rag.build_index(KNOWLEDGE_BASE_DIR)
                self._rag.save(FAISS_CACHE_DIR)
            self._rag_ready = True
        except Exception as exc:
            logger.warning("[POLICY] RAG unavailable — will use hard rules only: %s", exc)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def process(self, state: CreditApplicationState) -> CreditApplicationState:
        logger.info("[POLICY_C] Processing application %s", state.get("application_id"))
        start = time.monotonic()

        features = self._extract_features(state)
        hard_results = self._hard_rules.evaluate(features)
        hard_decision, hard_rule_id, matched_ids = self._hard_rules.aggregate_decision(hard_results)

        # If hard rules already force a clear REJECT, skip LLM
        hard_reject = hard_decision == "REJECT"

        rag_chunks: List[str] = []
        if self._rag_ready and not hard_reject:
            query = self._build_rag_query(features)
            retrieved = self._rag.retrieve(query, k=settings.rag_top_k)
            rag_chunks = [chunk for chunk, _meta, _score in retrieved]

        decision_obj = self._decide(
            features=features,
            hard_results=hard_results,
            hard_decision=hard_decision,
            hard_rule_id=hard_rule_id,
            matched_ids=matched_ids,
            rag_chunks=rag_chunks,
        )

        elapsed_ms = (time.monotonic() - start) * 1000
        self._update_state(state, decision_obj, elapsed_ms)

        logger.info(
            "[POLICY_C] Decision=%s rule_id=%s (%.0fms)",
            decision_obj.decision,
            decision_obj.rule_id,
            elapsed_ms,
        )
        return state

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------

    def _decide(
        self,
        features: Dict[str, Any],
        hard_results: List[Dict[str, Any]],
        hard_decision: str,
        hard_rule_id: str,
        matched_ids: List[str],
        rag_chunks: List[str],
    ) -> PolicyDecision:
        failed_hard = [r for r in hard_results if not r["passed"]]

        # Pure hard-rule REJECT (no need for LLM)
        if hard_decision == "REJECT" and not rag_chunks:
            failed_blocking = next(
                (r for r in failed_hard if r.get("blocking") and r.get("decision_if_failed") == "REJECT"),
                failed_hard[0] if failed_hard else None,
            )
            rule_id = failed_blocking["rule_id"] if failed_blocking else hard_rule_id
            rule_name = failed_blocking["rule_name"] if failed_blocking else hard_rule_id
            return PolicyDecision(
                decision="REJECT",
                rule_id=rule_id,
                rule_name=rule_name,
                rules_matched=matched_ids,
                confidence_score=0.95,
                recommended_product=None,
                product_terms=None,
                reasoning=f"Rejet déterministe — règle {rule_id} : {self._format_hard_summary(failed_hard)}",
                rag_chunks_used=[],
                hard_rules_triggered=failed_hard,
            )

        # LLM-assisted decision
        if self._openai and rag_chunks:
            try:
                return self._llm_decide(features, hard_results, hard_decision, matched_ids, rag_chunks)
            except Exception as exc:
                logger.warning("[POLICY] LLM call failed, falling back to hard rules: %s", exc)

        # Fallback: hard rules only
        return self._hard_rules_only_decision(features, hard_decision, hard_rule_id, matched_ids, hard_results)

    def _llm_decide(
        self,
        features: Dict[str, Any],
        hard_results: List[Dict[str, Any]],
        hard_decision: str,
        matched_ids: List[str],
        rag_chunks: List[str],
    ) -> PolicyDecision:
        hard_summary = self._format_hard_summary_full(hard_results)
        rag_context = "\n\n---\n\n".join(rag_chunks[:settings.rag_top_k])

        monthly_income = float(features.get("monthly_income", 1.0))
        monthly_payment = float(features.get("monthly_payment", 0.0))
        dti = float(features.get("debt_ratio", 0.0))
        loan_amount = float(features.get("loan_amount", 0.0))
        dti_post = monthly_payment / monthly_income if monthly_income > 0 else dti

        prompt = DECISION_PROMPT_TEMPLATE.format(
            credit_type=features.get("credit_type", "non précisé"),
            loan_amount=f"{loan_amount:,.0f}",
            monthly_income=f"{monthly_income:,.0f}",
            monthly_payment=f"{monthly_payment:,.0f}",
            debt_ratio_pct=dti * 100,
            debt_ratio_post_pct=dti_post * 100,
            client_age=features.get("client_age", "?"),
            employment_status=features.get("employment_status", "non précisé"),
            seniority_years=features.get("seniority_years", "?"),
            salary_domiciled="Oui" if features.get("salary_domiciled") else "Non",
            pd_score=float(features.get("pd_score", 0.0)),
            risk_band=features.get("risk_band", "?"),
            pd_confidence=float(features.get("pd_confidence", 0.0)),
            in_grey_zone="Oui" if features.get("in_grey_zone") else "Non",
            hard_rules_summary=hard_summary,
            rag_context=rag_context,
        )

        response = self._openai.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=800,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)

        return PolicyDecision(
            decision=data.get("decision", hard_decision),
            rule_id=data.get("rule_id", "LLM-POLICY"),
            rule_name=data.get("rule_name", "Décision LLM"),
            rules_matched=data.get("rules_matched", matched_ids),
            confidence_score=float(data.get("confidence_score", 0.8)),
            recommended_product=data.get("recommended_product"),
            product_terms=data.get("product_terms"),
            reasoning=data.get("reasoning", ""),
            rag_chunks_used=[c[:120] for c in rag_chunks],
            hard_rules_triggered=[r for r in hard_results if not r["passed"]],
        )

    def _hard_rules_only_decision(
        self,
        features: Dict[str, Any],
        hard_decision: str,
        hard_rule_id: str,
        matched_ids: List[str],
        hard_results: List[Dict[str, Any]],
    ) -> PolicyDecision:
        pd_score = float(features.get("pd_score", 0.0))
        credit_type = str(features.get("credit_type", "")).lower()
        loan_amount = float(features.get("loan_amount", 0.0))

        product, terms = self._recommend_product(credit_type, pd_score, loan_amount)
        failed = [r for r in hard_results if not r["passed"]]

        return PolicyDecision(
            decision=hard_decision,
            rule_id=hard_rule_id,
            rule_name=hard_rule_id,
            rules_matched=matched_ids,
            confidence_score=0.85 if hard_decision != "REFER" else 0.70,
            recommended_product=product,
            product_terms=terms,
            reasoning=self._build_fallback_reasoning(hard_decision, failed, features),
            rag_chunks_used=[],
            hard_rules_triggered=failed,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_features(self, state: CreditApplicationState) -> Dict[str, Any]:
        cd = state.get("client_data", {})
        scoring = state.get("guarantee_analysis", {}).get("extracted_features", {})

        monthly_income = self._to_float(
            cd.get("monthly_salary") or cd.get("income") or scoring.get("monthly_income") or 0
        )
        monthly_payment = self._to_float(
            cd.get("monthly_payment") or cd.get("AMT_ANNUITY") or scoring.get("monthly_payment") or 0
        )
        dti = self._to_float(cd.get("debt_ratio") or cd.get("DTI") or cd.get("dti"))
        if dti == 0.0 and monthly_income > 0:
            dti = monthly_payment / monthly_income

        age = self._to_float(cd.get("client_age") or cd.get("age"))
        if age == 0 and cd.get("DAYS_BIRTH"):
            age = abs(self._to_float(cd.get("DAYS_BIRTH"))) / 365

        return {
            "credit_type": cd.get("credit_type", "consommation"),
            "loan_amount": self._to_float(cd.get("loan_amount") or cd.get("AMT_CREDIT") or 0),
            "monthly_income": monthly_income,
            "monthly_payment": monthly_payment,
            "debt_ratio": dti,
            "client_age": int(round(age)),
            "loan_duration_months": self._to_float(cd.get("loan_duration_months") or 60),
            "employment_status": cd.get("employment_status", cd.get("NAME_INCOME_TYPE", "")),
            "seniority_years": self._to_float(cd.get("seniority_years") or cd.get("DAYS_EMPLOYED", 0)) / 365
            if cd.get("DAYS_EMPLOYED") else self._to_float(cd.get("seniority_years") or 0),
            "salary_domiciled": cd.get("is_salary_domiciled", True),
            "cr_bct_class": int(cd.get("cr_bct_class", 0)),
            "on_sanctions_list": bool(cd.get("on_sanctions_list", False)),
            "pd_score": float(state.get("final_pd_score", 0.0)),
            "pd_confidence": float(state.get("pd_confidence", 0.0)),
            "risk_band": state.get("risk_band", ""),
            "in_grey_zone": bool(state.get("in_grey_zone", False)),
        }

    def _build_rag_query(self, features: Dict[str, Any]) -> str:
        credit_type = features.get("credit_type", "consommation")
        dti = features.get("debt_ratio", 0.0)
        age = features.get("client_age", 0)
        pd = features.get("pd_score", 0.0)
        return (
            f"Règles d'octroi crédit {credit_type} Tunisie BCT. "
            f"Taux endettement {dti*100:.0f}% age emprunteur {age} ans. "
            f"Score risque PD={pd:.3f}. Conditions éligibilité, taux intérêt, durée, garanties."
        )

    def _recommend_product(
        self, credit_type: str, pd_score: float, loan_amount: float
    ) -> Tuple[Optional[str], Optional[Dict]]:
        if pd_score >= 0.65:
            return None, None
        product_map = {
            "immobilier": ("Crédit Immobilier IMMO-RES-2024", {"taux": "9,97 % à 10,97 %", "durée_max": "25 ans", "montant_max": "500 000 TND"}),
            "immo": ("Crédit Immobilier IMMO-RES-2024", {"taux": "9,97 % à 10,97 %", "durée_max": "25 ans", "montant_max": "500 000 TND"}),
            "auto": ("Crédit Auto AUTO-VEH-2024", {"taux": "11,47 % à 11,97 %", "durée_max": "7 ans", "montant_max": "150 000 TND"}),
            "professionnel": ("Crédit Professionnel PRO-SME-2024", {"taux": "11,47 % à 12,47 %", "durée_max": "15 ans", "montant_max": "5 000 000 TND"}),
            "pro": ("Crédit Professionnel PRO-SME-2024", {"taux": "11,47 % à 12,47 %", "durée_max": "15 ans", "montant_max": "5 000 000 TND"}),
        }
        match = product_map.get(credit_type.lower())
        if match:
            return match
        return ("Crédit Consommation CONSO-PER-2024", {"taux": "12,47 % à 13,97 %", "durée_max": "7 ans", "montant_max": "80 000 TND"})

    def _format_hard_summary(self, failed: List[Dict[str, Any]]) -> str:
        if not failed:
            return "Toutes les règles déterministes respectées."
        lines = [f"- {r['rule_id']}: {r['rule_name']} (valeur={r['value']}, seuil={r['threshold']})" for r in failed]
        return "\n".join(lines)

    def _format_hard_summary_full(self, results: List[Dict[str, Any]]) -> str:
        lines = []
        for r in results:
            status = "✅ PASS" if r["passed"] else "❌ FAIL"
            lines.append(f"- [{status}] {r['rule_id']}: {r['rule_name']} | Valeur={r['value']} | Seuil={r['threshold']}")
        return "\n".join(lines)

    def _build_fallback_reasoning(
        self, decision: str, failed: List[Dict[str, Any]], features: Dict[str, Any]
    ) -> str:
        if decision == "APPROVE":
            return f"Toutes les règles BCT respectées. PD={features.get('pd_score', 0):.4f} < 0,35. DTI={features.get('debt_ratio', 0)*100:.1f} %."
        if decision == "REJECT":
            reasons = "; ".join(f"{r['rule_id']}" for r in failed)
            return f"Rejet pour non-conformité réglementaire : {reasons}."
        return f"Dossier en zone grise (PD={features.get('pd_score', 0):.4f}) — examen conseiller requis."

    def _update_state(
        self,
        state: CreditApplicationState,
        decision: PolicyDecision,
        elapsed_ms: float,
    ) -> None:
        state["policy_decision"] = {
            "decision": decision.decision,
            "rule_id": decision.rule_id,
            "rule_name": decision.rule_name,
            "rules_matched": decision.rules_matched,
            "confidence_score": decision.confidence_score,
            "recommended_product": decision.recommended_product,
            "product_terms": decision.product_terms,
        }
        state["regulatory_checks_passed"] = decision.decision in ("APPROVE", "REFER")
        state["bct_rules_applied"] = decision.rules_matched
        state["in_grey_zone"] = decision.decision == "REFER"

        from datetime import datetime
        state.setdefault("audit_trail", []).append({
            "timestamp": datetime.utcnow().isoformat(),
            "agent": "POLICY_C",
            "action": "DECISION_MADE",
            "details": {
                "decision": decision.decision,
                "rule_id": decision.rule_id,
                "confidence_score": decision.confidence_score,
                "elapsed_ms": round(elapsed_ms),
                "rag_chunks_used": len(decision.rag_chunks_used),
                "hard_rules_triggered": len(decision.hard_rules_triggered),
                "reasoning": decision.reasoning[:300],
            },
        })
        state.setdefault("processing_steps_completed", []).append("POLICY_C_COMPLETE")

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            if value is None or value == "":
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0
