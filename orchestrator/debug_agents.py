#!/usr/bin/env python
"""
Script de debugging complet du système agentique AICredits.

Usage (depuis le dossier orchestrator) :
    python debug_agents.py              # tous les agents
    python debug_agents.py guarantee    # seulement GuaranteeAgent
    python debug_agents.py scoring      # seulement ScoringAgent
    python debug_agents.py fraud        # seulement FraudAgent
    python debug_agents.py xai          # seulement XAIAgent
    python debug_agents.py policy       # seulement PolicyAgent
    python debug_agents.py pipeline     # pipeline complet (Flux A puis Flux B)
    python debug_agents.py config       # vérification configuration
"""

import asyncio
import io
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Force UTF-8 output on Windows terminals
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Répertoire de travail ──────────────────────────────────────────────────
ORCHESTRATOR_DIR = Path(__file__).parent
sys.path.insert(0, str(ORCHESTRATOR_DIR))

# Charger le .env avant tout import de config
from dotenv import load_dotenv
load_dotenv(ORCHESTRATOR_DIR / ".env")

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(name)s  |  %(message)s",
    datefmt="%H:%M:%S",
)
# Nos loggers internes en INFO
for _ns in ("src", "config", "agent", "mcp_server"):
    logging.getLogger(_ns).setLevel(logging.INFO)

# ── Couleurs terminal ──────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):  print(f"  {GREEN}[OK]{RESET} {msg}")
def fail(msg): print(f"  {RED}[FAIL]{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}[WARN]{RESET} {msg}")
def info(msg): print(f"  {CYAN}->{RESET} {msg}")
def section(title):
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}  {title}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}")
def subsection(title):
    print(f"\n{BOLD}  -- {title} --{RESET}")


# ══════════════════════════════════════════════════════════════════════════
# DONNÉES DE TEST
# ══════════════════════════════════════════════════════════════════════════

def make_client_data(scenario: str = "normal") -> dict:
    base = {
        "client_id": "DEBUG-001",
        "credit_type": "consommation",
        "loan_amount": 25_000,
        "AMT_CREDIT": 25_000,
        "amount": 25_000,
        "monthly_salary": 3_200,
        "AMT_INCOME_TOTAL": 38_400,
        "income": 38_400,
        "client_age": 35,
        "age": 35,
        "DAYS_BIRTH": -12775,
        "employment_years": 7,
        "DAYS_EMPLOYED": -2555,
        "credit_duration": 60,
        "CREDIT_TERM": 60,
        "monthly_payment": 480,
        "AMT_ANNUITY": 480,
        "debt_ratio": 0.15,
        "DTI": 0.15,
        "risk_class": 1,
        "is_salary_domiciled": True,
        # Assurance décès-invalidité requise pour tout crédit consommation
        "insurance_subscribed": ["Assurance décès-invalidité"],
        "CODE_GENDER": "M",
        "NAME_EDUCATION_TYPE": "Higher education",
        "NAME_FAMILY_STATUS": "Married",
        "FLAG_OWN_REALTY": 1,
        "employer_name": "Tunisie Telecom",
        "document_workflow_enabled": False,   # Pas de vrais docs en debug
    }
    if scenario == "high_risk":
        base.update({
            # risk_class=4 → REFUS (KO) selon les règles BCT circulaire 91-24
            "risk_class": 4,
            "debt_ratio": 0.65,
            "DTI": 0.65,
            "monthly_salary": 800,
            "AMT_INCOME_TOTAL": 9_600,
            "income": 9_600,
            "loan_amount": 80_000,
            "AMT_CREDIT": 80_000,
            "amount": 80_000,
        })
    elif scenario == "grey_zone":
        base.update({
            "risk_class": 2,
            "debt_ratio": 0.45,
            "DTI": 0.45,
            "monthly_salary": 1_800,
            "AMT_INCOME_TOTAL": 21_600,
            "income": 21_600,
            "loan_amount": 40_000,
            "AMT_CREDIT": 40_000,
            "amount": 40_000,
        })
    elif scenario == "immobilier":
        base.update({
            "credit_type": "immobilier",
            "loan_amount": 180_000,
            "AMT_CREDIT": 180_000,
            "amount": 180_000,
            "monthly_salary": 5_000,
            "AMT_INCOME_TOTAL": 60_000,
            "income": 60_000,
            "client_age": 38,
            "age": 38,
            "risk_class": 1,
            "debt_ratio": 0.28,
            "DTI": 0.28,
            "insurance_subscribed": [
                "Assurance décès-invalidité",
                "Assurance multirisque habitation",
            ],
        })
    return base


def make_state(scenario: str = "normal") -> dict:
    from src.state import DEFAULT_STATE
    import copy
    cd = make_client_data(scenario)
    ts = datetime.utcnow().isoformat()
    return {
        **copy.deepcopy(DEFAULT_STATE),
        "application_id": f"DEBUG-{scenario.upper()}-{int(time.time())}",
        "client_id": "DEBUG-001",
        "created_at": ts,
        "client_data": cd,
        "flux_type": "full",
        "xai_mode": "pro",
        "audit_trail": [{
            "timestamp": ts,
            "agent": "DEBUG_HARNESS",
            "action": "TEST_START",
            "details": {"scenario": scenario},
        }],
    }


# ══════════════════════════════════════════════════════════════════════════
# 0. VÉRIFICATION CONFIG
# ══════════════════════════════════════════════════════════════════════════

def debug_config():
    section("0. Configuration & Environnement")

    from config.settings import get_config
    cfg = get_config()

    subsection("Environnement")
    info(f"APP_ENV = {cfg.env.value}")
    info(f"DEBUG   = {cfg.debug}")
    info(f"LOG_LEVEL = {cfg.log_level}")

    subsection("Azure OpenAI")
    if cfg.azure_openai.validate():
        ok(f"Endpoint   : {cfg.azure_openai.endpoint}")
        ok(f"Deployment : {cfg.azure_openai.deployment}")
        ok(f"API Version: {cfg.azure_openai.api_version}")
        api_key = cfg.azure_openai.api_key
        masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"
        ok(f"API Key    : {masked}")
    else:
        errors = cfg.azure_openai.get_validation_errors()
        for e in errors:
            fail(f"LLM config: {e}")
        warn("Les agents LLM (GuaranteeAgent synthèse, XAI, PolicyAgent RAG) utiliseront le mode dégradé.")

    subsection("MCP Scoring Server")
    info(f"URL     : {cfg.mcp_server.base_url}")
    info(f"Timeout : {cfg.mcp_server.timeout}s")

    # Test de connectivité ML server
    import httpx
    try:
        r = httpx.get(f"{cfg.mcp_server.base_url}/health", timeout=3)
        if r.status_code == 200:
            ok("ML Server accessible (200 OK)")
        else:
            warn(f"ML Server répond {r.status_code} → fallback simplifié actif")
    except Exception as e:
        warn(f"ML Server inaccessible ({type(e).__name__}) → fallback simplifié actif")

    subsection("Infrastructure (PostgreSQL / Redis / Kafka)")
    db_url = os.getenv("DATABASE_URL", "")
    redis_host = os.getenv("REDIS_HOST", "localhost")
    kafka = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
    info(f"DATABASE_URL : {db_url[:40]}..." if len(db_url) > 40 else f"DATABASE_URL : {db_url or '(non défini)'}")
    info(f"REDIS_HOST   : {redis_host}")
    info(f"KAFKA        : {kafka or '(non défini)'}")
    warn("La connectivité infra sera testée au démarrage — les agents fonctionnent sans elle (dégradé).")

    subsection("Imports Python")
    _check_imports()


def _check_imports():
    checks = {
        "fastapi":       "FastAPI",
        "langgraph":     "LangGraph",
        "openai":        "openai SDK",
        "httpx":         "httpx",
        "numpy":         "numpy",
        "pydantic":      "pydantic",
        "langsmith":     "LangSmith",
        "sklearn":       "scikit-learn (IsolationForest)",
        "redis":         "redis",
        "sqlalchemy":    "SQLAlchemy",
        "aiokafka":      "aiokafka",
        "dotenv":        "python-dotenv",
    }
    for pkg, label in checks.items():
        try:
            __import__(pkg)
            ok(label)
        except ImportError:
            fail(f"{label} — MANQUANT (pip install {pkg})")


# ══════════════════════════════════════════════════════════════════════════
# 1. GUARANTEE AGENT
# ══════════════════════════════════════════════════════════════════════════

def _print_guarantee_result(result: dict, elapsed_ms: int, expected_verdict: str) -> None:
    """Affiche le résultat complet d'un scénario GuaranteeAgent."""
    verdict    = result.get("verdict", "?")
    ready      = result.get("ready_for_scoring")
    g_princ    = result.get("garantie_principale", "?")
    g_sec      = result.get("garantie_secondaire")
    missing    = result.get("documents_manquants", [])
    conditions = result.get("conditions_deblocage", [])
    blocking   = result.get("blocking_reasons", [])
    note       = result.get("note_comite", "")
    assur_req  = result.get("assurances_requises", [])
    assur_ok   = result.get("assurances_presentes", [])
    llm_used   = result.get("_llm_used")
    llm_model  = result.get("_llm_model", "")
    llm_err    = result.get("_llm_skip_reason", "")

    # --- Verdict ---
    if verdict == expected_verdict:
        ok(f"Verdict = {verdict}  ({elapsed_ms}ms)")
    else:
        warn(f"Verdict = {verdict}  (attendu: {expected_verdict})  ({elapsed_ms}ms)")

    # --- LLM status ---
    if llm_used is True:
        ok(f"LLM synthesis : OUI  ({llm_model})")
    elif llm_used is False:
        warn(f"LLM synthesis : FALLBACK  → {llm_err}")
    else:
        info("LLM synthesis : non renseigné")

    # --- Champs clés ---
    info(f"ready_for_scoring   = {ready}")
    info(f"garantie_principale = {g_princ}")
    if g_sec:
        info(f"garantie_secondaire = {g_sec}")
    info(f"assurances requises = {assur_req}")
    info(f"assurances présentes= {assur_ok}")
    if note:
        info(f"note_comite         = {note}")

    # --- Blocages ---
    if blocking:
        for b in blocking:
            warn(f"[BLOCKING] {b}")
    if conditions:
        for c in conditions[:5]:
            warn(f"[CONDITION] {c}")
    if missing:
        for m in missing:
            warn(f"[DOC MANQUANT] {m}")

    # --- Structure ---
    required_keys = [
        "verdict", "garantie_principale", "garantie_secondaire",
        "assurances_requises", "assurances_presentes",
        "documents_manquants", "conditions_deblocage",
        "note_comite", "ready_for_scoring",
        "frontend_payload", "scoring_payload",
    ]
    missing_keys = [k for k in required_keys if k not in result]
    if missing_keys:
        fail(f"Clés manquantes dans la réponse: {missing_keys}")
    else:
        ok("Structure de réponse complète")


def debug_guarantee_agent():
    section("1. GuaranteeAgent (Agent A) — Mode 100% LLM")

    from src.agents.guarantee_agent.agent.guarantee_agent import GuaranteeAgent
    from config.settings import get_config

    cfg = get_config()
    llm_ok = cfg.azure_openai.validate()

    # Activer le logger du guarantee agent en DEBUG pour voir input/output LLM
    logging.getLogger("src.agents.guarantee_agent").setLevel(logging.DEBUG)

    if llm_ok:
        ok(f"Azure OpenAI configuré : {cfg.azure_openai.deployment} @ {cfg.azure_openai.endpoint}")
        agent = GuaranteeAgent(
            enable_llm=True,
            enable_document_intelligence=True,
            enable_summary_llm=True,
        )
        ok("GuaranteeAgent instancié en mode LLM complet (synthesis + document intelligence)")
    else:
        errors = cfg.azure_openai.get_validation_errors()
        for e in errors:
            warn(f"Azure OpenAI: {e}")
        warn("Azure OpenAI non disponible → mode déterministe (fallback attendu dans les logs)")
        agent = GuaranteeAgent(
            enable_llm=False,
            enable_document_intelligence=False,
            enable_summary_llm=False,
        )

    scenarios = [
        # normal: assurance incluse → garantie salaire → OK
        ("consommation OK",  make_client_data("normal"),     "OK"),
        # immobilier: assurances présentes mais hypothèque → conditions notariales → CONDITIONNEL
        ("immobilier CONDITIONNEL", make_client_data("immobilier"), "CONDITIONNEL"),
        # high_risk: risk_class=4 → REFUS BCT → KO
        ("haut risque KO",   make_client_data("high_risk"),  "KO"),
        # grey_zone: risque modéré → CONDITIONNEL ou OK
        ("zone grise",       make_client_data("grey_zone"),  "OK"),
    ]

    for label, cd, expected_verdict in scenarios:
        subsection(f"Scénario: {label}")
        t0 = time.monotonic()
        try:
            dossier = {**cd, "document_workflow_enabled": False}
            result = agent.run(dossier, require_documents=False)
            elapsed = int((time.monotonic() - t0) * 1000)
            _print_guarantee_result(result, elapsed, expected_verdict)
        except Exception as e:
            fail(f"ERREUR: {e}")
            traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════
# 2. SCORING AGENT
# ══════════════════════════════════════════════════════════════════════════

async def debug_scoring_agent():
    section("2. ScoringAgent (Agent B)")

    from src.agents.scoring_agent import ScoringAgent, FeatureStore

    feature_store = FeatureStore()
    agent = ScoringAgent(feature_store)
    ok("ScoringAgent instancié (sans Feature Store externe)")

    scenarios = [
        ("normal",    "full"),
        ("high_risk", "full"),
        ("grey_zone", "full"),
    ]

    for scenario, flux in scenarios:
        subsection(f"Scénario: {scenario}")
        state = make_state(scenario)
        state["flux_type"] = flux

        t0 = time.monotonic()
        try:
            state = await agent.process(state)
            elapsed = int((time.monotonic() - t0) * 1000)

            pd_score   = state.get("final_pd_score", 0.0)
            confidence = state.get("pd_confidence", 0.0)
            risk_band  = state.get("risk_band", "?")
            grey_zone  = state.get("in_grey_zone", False)
            iterations = len(state.get("scoring_iterations", []))
            errors     = state.get("error_messages", [])
            model_ver  = state.get("ml_model_version", "?")

            if pd_score > 0 or confidence > 0:
                ok(f"PD Score = {pd_score:.4f}  ({elapsed}ms)")
            else:
                warn(f"PD Score = {pd_score:.4f} — vérifier le ML server  ({elapsed}ms)")

            info(f"Risk Band  = {risk_band}")
            info(f"Confidence = {confidence:.4f}")
            info(f"Grey Zone  = {grey_zone}")
            info(f"Iterations = {iterations}")
            info(f"Model Ver. = {model_ver}")

            if errors:
                for e in errors:
                    warn(f"Erreur signalée: {e}")
            else:
                ok("Aucune erreur signalée")

            # Vérification SHAP dans les itérations
            iters = state.get("scoring_iterations", [])
            if iters and iters[-1].get("shap_values"):
                shap = iters[-1]["shap_values"]
                top3 = list(shap.items())[:3] if isinstance(shap, dict) else shap[:3]
                ok(f"SHAP values présentes ({len(shap)} features)")
                for item in top3:
                    if isinstance(item, tuple):
                        info(f"  SHAP {item[0]}: {item[1]:.4f}")
                    elif isinstance(item, dict):
                        info(f"  SHAP {item.get('feature', '?')}: {item.get('shap_value', 0):.4f}")
            else:
                warn("Pas de SHAP values dans les itérations")

        except Exception as e:
            fail(f"ERREUR: {e}")
            traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════
# 3. FRAUD AGENT
# ══════════════════════════════════════════════════════════════════════════

async def debug_fraud_agent():
    section("3. FraudAgent (Agent E)")

    from src.agents.fraud_agent import FraudAgent

    agent = FraudAgent(redis_client=None)
    ok("FraudAgent instancié (sans Redis)")

    scenarios = [
        ("normal",    "Profil normal → faible risque fraude"),
        ("high_risk", "Profil à risque → potentielle anomalie"),
    ]

    for scenario, desc in scenarios:
        subsection(f"Scénario: {scenario} — {desc}")
        state = make_state(scenario)

        # Pré-remplir le scoring pour que le fraud agent ait des données
        state["final_pd_score"] = 0.2 if scenario == "normal" else 0.75
        state["pd_confidence"]  = 0.9
        state["risk_band"]      = "FAIBLE" if scenario == "normal" else "ELEVE"
        state["guarantee_analysis"] = {
            "verdict": "OK",
            "ready_for_scoring": True,
            "documents_manquants": [],
        }

        t0 = time.monotonic()
        try:
            state = await agent.process(state)
            elapsed = int((time.monotonic() - t0) * 1000)

            fa = state.get("fraud_analysis") or {}
            fraud_score = fa.get("fraud_risk_score", 0.0)
            is_flagged  = fa.get("is_flagged", False)
            anomaly     = fa.get("anomaly_type")
            blocked     = state.get("is_application_blocked", False)
            completed   = state.get("fraud_check_completed", False)

            if completed:
                ok(f"fraud_check_completed = True  ({elapsed}ms)")
            else:
                warn(f"fraud_check_completed = False  ({elapsed}ms)")

            info(f"fraud_risk_score = {fraud_score:.4f}")
            info(f"is_flagged       = {is_flagged}")
            info(f"anomaly_type     = {anomaly or 'aucune'}")
            info(f"is_blocked       = {blocked}")

            if fraud_score < 0.5 and not is_flagged:
                ok("Profil considéré comme légitime")
            elif is_flagged:
                warn(f"Fraude détectée: {anomaly}")

        except Exception as e:
            fail(f"ERREUR: {e}")
            traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════
# 4. XAI AGENT
# ══════════════════════════════════════════════════════════════════════════

async def debug_xai_agent():
    section("4. XAIAgent (Agent D)")

    from src.agents.xai_agent_v2 import XAIAgent

    agent = XAIAgent(llm_client=None, db_client=None)
    ok("XAIAgent instancié (sans LLM, sans DB)")

    for xai_mode in ("client", "pro"):
        subsection(f"Mode: {xai_mode}")
        state = make_state("normal")
        state["xai_mode"] = xai_mode
        state["flux_type"] = "preview" if xai_mode == "client" else "full"

        # Pré-remplir le scoring — le XAI agent en a besoin
        state["final_pd_score"] = 0.28
        state["pd_confidence"]  = 0.91
        state["risk_band"]      = "FAIBLE"
        state["in_grey_zone"]   = False
        state["final_decision"] = "APPROVE"
        state["policy_decision"] = {
            "decision": "APPROVE",
            "rule_id": "SCORE_LOW_RISK",
            "rule_name": "Score faible risque",
            "rules_matched": ["SCORE_LOW_RISK"],
            "confidence_score": 0.91,
            "recommended_product": "Crédit consommation",
            "product_terms": {"rate": 4.5, "term_months": 60},
        }
        state["scoring_iterations"] = [{
            "iteration": 1,
            "pd_score": 0.28,
            "confidence": 0.91,
            "risk_band": "FAIBLE",
            "missing_features": [],
            "shap_values": {
                "AMT_INCOME_TOTAL": -0.12,
                "DAYS_EMPLOYED":    -0.09,
                "DTI":               0.07,
                "AMT_CREDIT":        0.05,
                "client_age":       -0.04,
            },
            "model_version": "simplified_heuristic_v1",
        }]

        t0 = time.monotonic()
        try:
            state = await agent.process(state)
            elapsed = int((time.monotonic() - t0) * 1000)

            xai = state.get("xai_explanation") or {}
            top_factors    = xai.get("top_factors", [])
            counterfactuals = xai.get("counterfactuals", [])
            explanation    = xai.get("natural_explanation", "")
            threshold      = xai.get("decision_threshold", 0.5)
            distance       = xai.get("distance_to_threshold", 0.0)

            ok(f"XAI généré en {elapsed}ms")
            info(f"Top factors      : {len(top_factors)}")
            info(f"Counterfactuals  : {len(counterfactuals)}")
            info(f"Threshold        : {threshold}")
            info(f"Distance to thr. : {distance:.4f}")

            if top_factors:
                ok("Top 3 facteurs:")
                for f in top_factors[:3]:
                    label  = f.get("feature", f.get("feature_name", "?"))
                    impact = f.get("impact", "?")
                    info(f"  [{impact}] {label}")
            else:
                warn("Aucun top_factor retourné")

            if counterfactuals:
                action = counterfactuals[0].get("action", counterfactuals[0].get("suggestion", ""))
                ok(f"Contrefactuel exemple: {action[:80]}")
            else:
                warn("Aucun contrefactuel retourné")

            if explanation:
                ok(f"Explication naturelle: {explanation[:100]}...")
            else:
                warn("Explication naturelle vide")

        except Exception as e:
            fail(f"ERREUR: {e}")
            traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════
# 5. POLICY AGENT
# ══════════════════════════════════════════════════════════════════════════

async def debug_policy_agent():
    section("5. PolicyAgent (Agent C)")

    try:
        from src.agents.policy_agent.agent.policy_agent import PolicyAgent
    except ImportError as e:
        fail(f"Import PolicyAgent échoué: {e}")
        warn("Vérifier que policy_agent/ existe dans src/agents/")
        return

    try:
        agent = PolicyAgent()
        ok("PolicyAgent instancié")
    except Exception as e:
        fail(f"PolicyAgent init échoué: {e}")
        traceback.print_exc()
        return

    scenarios = [
        ("normal",    0.28, "APPROVE"),
        ("grey_zone", 0.50, "REFER"),
        ("high_risk", 0.72, "REJECT"),
    ]

    for scenario, pd_score, expected in scenarios:
        subsection(f"Scénario: {scenario}  (PD={pd_score})")
        state = make_state(scenario)
        state["final_pd_score"] = pd_score
        state["pd_confidence"]  = 0.88
        state["risk_band"]      = "FAIBLE" if pd_score < 0.35 else ("MOYEN" if pd_score < 0.65 else "ELEVE")
        state["in_grey_zone"]   = 0.35 <= pd_score <= 0.65
        state["guarantee_analysis"] = {"verdict": "OK", "ready_for_scoring": True}
        state["guarantee_ready_for_scoring"] = True
        state["scoring_iterations"] = [{
            "iteration": 1,
            "pd_score": pd_score,
            "confidence": 0.88,
            "risk_band": state["risk_band"],
            "missing_features": [],
            "shap_values": {"AMT_INCOME_TOTAL": -0.1, "DTI": 0.08},
            "model_version": "simplified_heuristic_v1",
        }]

        t0 = time.monotonic()
        try:
            state = await agent.process(state)
            elapsed = int((time.monotonic() - t0) * 1000)

            pd = state.get("policy_decision") or {}
            decision   = pd.get("decision", "?")
            rule_id    = pd.get("rule_id", "?")
            confidence = pd.get("confidence_score", 0.0)
            product    = pd.get("recommended_product")

            if decision == expected:
                ok(f"Décision = {decision}  ({elapsed}ms)")
            else:
                warn(f"Décision = {decision}  (attendu: {expected})  ({elapsed}ms)")

            info(f"Rule ID    = {rule_id}")
            info(f"Confidence = {confidence:.4f}")
            info(f"Produit    = {product or '(aucun)'}")

        except Exception as e:
            fail(f"ERREUR: {e}")
            traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════
# 6. PIPELINE COMPLET
# ══════════════════════════════════════════════════════════════════════════

async def debug_full_pipeline():
    section("6. Pipeline Complet (OrchestratorGraph)")

    from src.orchestrator_graph import OrchestratorGraph

    orchestrator = OrchestratorGraph(
        feature_store=None,
        llm_client=None,
        db_client=None,
        kafka_producer=None,
        redis_client=None,
    )
    ok("OrchestratorGraph instancié (sans infra externe)")

    for flux_type in ("preview", "full"):
        for scenario in ("normal", "high_risk"):
            subsection(f"Flux {flux_type.upper()} — Scénario {scenario}")
            cd = make_client_data(scenario)

            t0 = time.monotonic()
            try:
                final_state = await orchestrator.process_application(
                    client_id="DEBUG-001",
                    client_data=cd,
                    flux_type=flux_type,
                )
                elapsed = int((time.monotonic() - t0) * 1000)

                decision  = final_state.get("final_decision", "?")
                pd_score  = final_state.get("final_pd_score", 0.0)
                risk_band = final_state.get("risk_band", "?")
                steps     = final_state.get("processing_steps_completed", [])
                errors    = final_state.get("error_messages", [])
                summary   = final_state.get("decision_summary", "")
                next_act  = final_state.get("next_action", "")
                human_rev = final_state.get("human_review_required", False)
                xai_ok    = bool(final_state.get("xai_explanation"))
                guarantee = (final_state.get("guarantee_analysis") or {}).get("verdict", "?")

                ok(f"Pipeline terminé en {elapsed}ms")
                info(f"Décision finale  : {decision}")
                info(f"PD Score         : {pd_score:.4f}")
                info(f"Risk Band        : {risk_band}")
                info(f"Verdict garantie : {guarantee}")
                info(f"Human review     : {human_rev}")
                info(f"XAI généré       : {xai_ok}")
                info(f"Étapes complétées: {steps}")
                if summary:
                    info(f"Résumé           : {summary[:100]}")
                if next_act:
                    info(f"Prochaine action : {next_act}")

                if errors:
                    for e in errors:
                        warn(f"Erreur pipeline  : {e}")
                else:
                    ok("Aucune erreur pipeline")

                # Validation de la décision attendue
                expected = {
                    "normal":    {"APPROVE", "REVIEW_REQUIRED"},
                    "high_risk": {"REJECT",  "REVIEW_REQUIRED"},
                }
                if decision in expected[scenario]:
                    ok(f"Décision cohérente avec le scénario '{scenario}'")
                else:
                    warn(f"Décision '{decision}' inattendue pour '{scenario}'")

            except Exception as e:
                fail(f"ERREUR pipeline: {e}")
                traceback.print_exc()

    # Test SSE streaming (Flux B seulement)
    subsection("Test SSE Streaming (Flux B)")
    try:
        import asyncio
        queue = asyncio.Queue()
        cd = make_client_data("normal")

        stream_task = asyncio.create_task(
            orchestrator.stream_application("DEBUG-001", cd, "full", queue)
        )

        events = []
        timeout_at = asyncio.get_event_loop().time() + 60  # 60s max
        while True:
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=5)
                if evt is None:
                    break
                events.append(evt)
            except asyncio.TimeoutError:
                if asyncio.get_event_loop().time() > timeout_at:
                    warn("Streaming timeout (60s)")
                    stream_task.cancel()
                    break

        ok(f"Streaming terminé — {len(events)} événements reçus")
        for evt in events:
            agent_name = evt.get("agent", "?")
            status     = evt.get("status", "?")
            duration   = evt.get("duration_ms")
            dur_str    = f" ({duration}ms)" if duration else ""
            decision   = evt.get("decision")
            if decision:
                info(f"  [FINAL] decision={decision}  pd={evt.get('pd_score', 0):.4f}  confidence={evt.get('confidence', 0):.4f}")
            else:
                sym = "+" if status == "done" else ("!" if status in ("fallback", "error") else "-")
                info(f"  [{sym}] {agent_name}: {status}{dur_str}")

    except Exception as e:
        fail(f"ERREUR streaming: {e}")
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════
# RÉSUMÉ FINAL
# ══════════════════════════════════════════════════════════════════════════

def print_summary(sections_run: list[str]):
    section("RÉSUMÉ")
    print(f"\n  Sections exécutées : {', '.join(sections_run)}")
    print(f"\n  {BOLD}Points d'attention courants :{RESET}")
    print(f"  * ML Server non demarre      -> ScoringAgent utilise le moteur heuristique simplifie")
    print(f"  * Azure OpenAI non configure -> GuaranteeAgent et XAI sans LLM (degrade)")
    print(f"  * PostgreSQL/Redis/Kafka off  -> infra desactivee (audit trail en memoire seulement)")
    print(f"\n  {BOLD}Pour lancer le service :{RESET}")
    print(f"    cd credit_agents/orchestrator")
    print(f"    uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload")
    print(f"\n  {BOLD}Endpoints de debug disponibles (dev seulement) :{RESET}")
    print(f"    GET  /debug/config")
    print(f"    GET  /debug/agents")
    print(f"    GET  /health")
    print(f"    GET  /infrastructure/health")
    print(f"    POST /credit/score-agent   - test ScoringAgent isole")
    print(f"    POST /credit/xai-agent     - test XAIAgent isole")
    print()


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

async def main_async(targets: list[str]):
    all_targets = {"config", "guarantee", "scoring", "fraud", "xai", "policy", "pipeline"}
    run_all = not targets or targets == ["all"]
    run = lambda t: run_all or t in targets

    sections_run = []

    if run("config"):
        debug_config()
        sections_run.append("config")

    if run("guarantee"):
        debug_guarantee_agent()
        sections_run.append("guarantee")

    if run("scoring"):
        await debug_scoring_agent()
        sections_run.append("scoring")

    if run("fraud"):
        await debug_fraud_agent()
        sections_run.append("fraud")

    if run("xai"):
        await debug_xai_agent()
        sections_run.append("xai")

    if run("policy"):
        await debug_policy_agent()
        sections_run.append("policy")

    if run("pipeline"):
        await debug_full_pipeline()
        sections_run.append("pipeline")

    print_summary(sections_run)


def main():
    args = [a.lower() for a in sys.argv[1:]]
    unknown = [a for a in args if a not in {"config","guarantee","scoring","fraud","xai","policy","pipeline","all"}]
    if unknown:
        print(f"Arguments inconnus: {unknown}")
        print(__doc__)
        sys.exit(1)

    print(f"\n{BOLD}{CYAN}{'='*60}")
    print(f"  AICredits - Debug Agents  [{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC]")
    print(f"{'='*60}{RESET}")

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
