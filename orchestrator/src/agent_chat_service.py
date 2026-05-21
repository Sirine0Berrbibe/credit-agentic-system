"""
Agent Chat Service — AICredits
Chaque agent IA (Fraude, Scoring, Garanties, Politique, XAI) dispose d'un endpoint
conversationnel : le conseiller interagit directement avec l'agent qui a produit la
décision, à partir des données réelles qu'il a calculées.
"""

import logging
from typing import Optional, Dict, Any, List

from pydantic import BaseModel

from config.settings import get_config
from .llm_client import AzureOpenAIClient

logger = logging.getLogger(__name__)

SUPPORTED_AGENTS = {"FRAUD", "SCORING", "GUARANTEE", "POLICY", "XAI"}


# ── Pydantic models ──────────────────────────────────────────────────────────

class AgentChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class AgentChatRequest(BaseModel):
    agentType: str
    agentAnalysisData: Optional[Dict[str, Any]] = None   # données brutes du clientServicePayload
    userMessage: str
    conversation: Optional[List[AgentChatMessage]] = None
    loanContext: Optional[Dict[str, Any]] = None


class AgentChatResponse(BaseModel):
    message: str
    agentType: str
    status: str = "connected"


# ── Service ──────────────────────────────────────────────────────────────────

class AgentChatService:
    """
    Fait parler le vrai agent qui a produit la décision.
    Chaque agent dispose de son identité propre, de ses méthodes et de l'analyse
    réelle qu'il a effectuée — le LLM répond EN TANT QUE cet agent.
    """

    def __init__(self, llm_client: Optional[AzureOpenAIClient] = None):
        self.config = get_config()
        self.llm_client = llm_client or AzureOpenAIClient(self.config.azure_openai)
        logger.info("✓ Agent Chat Service initialized")

    async def chat(self, request: AgentChatRequest) -> AgentChatResponse:
        agent_type = request.agentType.upper()
        if agent_type not in SUPPORTED_AGENTS:
            return AgentChatResponse(
                message=f"Agent inconnu : {request.agentType}. Agents disponibles : {', '.join(SUPPORTED_AGENTS)}.",
                agentType=request.agentType,
                status="error",
            )

        data = request.agentAnalysisData or {}
        loan = request.loanContext or {}

        system_prompt = self._build_system_prompt(agent_type, data, loan)
        history = self._format_history(request.conversation)

        try:
            messages = [{"role": "system", "content": system_prompt}]
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": request.userMessage})

            response = await self.llm_client.chat_completion(
                messages=messages,
                max_completion_tokens=800,
                temperature=0.4,   # plus déterministe pour un expert technique
            )
            answer = response.content.strip()
            logger.info(f"[{agent_type}] Chat response generated ({len(answer)} chars)")
            return AgentChatResponse(message=answer, agentType=agent_type)

        except Exception as e:
            logger.error(f"[{agent_type}] Chat error: {e}", exc_info=True)
            return AgentChatResponse(
                message="Je rencontre une difficulté technique. Veuillez réessayer.",
                agentType=agent_type,
                status="fallback",
            )

    # ── System prompt builders ────────────────────────────────────────────────

    def _build_system_prompt(
        self, agent_type: str, data: Dict[str, Any], loan: Dict[str, Any]
    ) -> str:
        builders = {
            "FRAUD":     self._fraud_prompt,
            "SCORING":   self._scoring_prompt,
            "GUARANTEE": self._guarantee_prompt,
            "POLICY":    self._policy_prompt,
            "XAI":       self._xai_prompt,
        }
        return builders[agent_type](data, loan)

    def _fraud_prompt(self, data: Dict[str, Any], loan: Dict[str, Any]) -> str:
        fraud_score  = data.get("fraud_risk_score") or data.get("fraudScore") or data.get("fraud_score")
        is_flagged   = data.get("is_flagged", False)
        anomaly_type = data.get("anomaly_type")
        doc_ok       = data.get("document_consistency_verified")
        velocity     = data.get("velocity_metrics") or {}

        pct = f"{fraud_score * 100:.1f}%" if isinstance(fraud_score, (int, float)) else "non calculé"

        analysis_block = f"""
RÉSULTATS DE TON ANALYSE SUR CE DOSSIER :
- Score de fraude : {pct}
- Dossier signalé : {'OUI — escalade requise' if is_flagged else 'Non'}
- Type d'anomalie détectée : {anomaly_type or 'Aucune'}
- Cohérence documentaire : {'Vérifiée ✓' if doc_ok else ('Problème détecté ✗' if doc_ok is False else 'Non évaluée')}
- Demandes même employeur / 24h : {velocity.get('employer_applications_24h', 'N/A')}
- Demandes même tranche revenu / 1h : {velocity.get('income_band_applications_1h', 'N/A')}
- Anomalie vélocité détectée : {'Oui' if velocity.get('velocity_anomaly') else 'Non'}
"""

        return f"""Tu es l'Agent de Détection de Fraude d'AICredits.

IDENTITÉ ET MÉTHODES :
Tu es un système IA spécialisé dans la détection de fraude pour les dossiers de crédit.
Tu utilises trois mécanismes d'analyse :
1. Isolation Forest — détection d'anomalies comportementales sur le profil financier
   (features : revenu_log, montant_log, DTI, âge normalisé, ancienneté emploi, ratio crédit/revenu)
2. Velocity Checker — surveillance des pics de demandes (même employeur > 10/24h, même tranche revenu > 20/1h)
3. Document Inconsistency — contrôle de cohérence (âge CIN vs déclaré, revenus vs profil, ratio emploi)

Tu produis un fraud_score ∈ [0, 1] — au-delà de 0.50 tu déclenches un interrupt_signal qui bloque la décision finale.

{analysis_block}

RÈGLES DE COMPORTEMENT :
- Réponds UNIQUEMENT aux questions sur la fraude, les anomalies, la cohérence documentaire, la vélocité.
- Si la question concerne le scoring PD, les garanties, la politique BCT ou les explications SHAP :
  réponds poliment "Cette question concerne [Agent Scoring / Agent Garanties / Agent Politique / Agent XAI] — veuillez le consulter."
- Utilise un langage technique précis, adapté à un conseiller bancaire expert.
- Appuie-toi sur les données réelles ci-dessus. Ne les invente pas.
- Réponds en français. Maximum 3 paragraphes."""

    def _scoring_prompt(self, data: Dict[str, Any], loan: Dict[str, Any]) -> str:
        pd_score  = data.get("pd_score") or data.get("pdScore") or loan.get("pdScore")
        conf      = data.get("pd_confidence") or data.get("confidence") or loan.get("confidence")
        risk_band = data.get("risk_band") or data.get("riskBand") or loan.get("riskBand")
        grey      = data.get("in_grey_zone", False)
        iterations = data.get("scoring_iterations")
        shap_raw  = data.get("top_factors") or data.get("shap_top_features") or data.get("shapTopFeatures") or []

        pd_pct   = f"{pd_score * 100:.2f}%" if isinstance(pd_score, (int, float)) else "non calculé"
        conf_pct = f"{conf * 100:.1f}%"     if isinstance(conf, (int, float))     else "non calculée"

        shap_lines = ""
        if shap_raw:
            shap_lines = "\nTop facteurs SHAP :\n"
            for f in shap_raw[:5]:
                if isinstance(f, dict):
                    feat   = f.get("feature", "?")
                    impact = f.get("impact", "?")
                    val    = f.get("shap_value", "")
                    shap_lines += f"  • {feat}: impact={impact}, valeur SHAP={val}\n"

        analysis_block = f"""
RÉSULTATS DE TON ANALYSE SUR CE DOSSIER :
- Score PD (probabilité de défaut) : {pd_pct}
- Confiance du modèle : {conf_pct}
- Bande de risque : {risk_band or 'non définie'}
- Zone grise (PD 0.35–0.65) : {'Oui — itérations supplémentaires effectuées' if grey else 'Non'}
- Nombre d'itérations de scoring : {len(iterations) if isinstance(iterations, list) else 'N/A'}
{shap_lines}"""

        return f"""Tu es l'Agent de Scoring ML d'AICredits.

IDENTITÉ ET MÉTHODES :
Tu es un système IA de scoring crédit basé sur un modèle de Machine Learning (gradient boosting).
Tu calcules la probabilité de défaut (PD) selon un processus itératif ReAct (max 3 itérations).
En zone grise (PD entre 0.35 et 0.65), tu demandes des features supplémentaires pour affiner.
Tu produis des valeurs SHAP pour expliquer l'impact de chaque feature sur le score.
Classification de risque : LOW (PD < 0.35) | MEDIUM (0.35 ≤ PD ≤ 0.65) | HIGH (PD > 0.65).

{analysis_block}

RÈGLES DE COMPORTEMENT :
- Réponds UNIQUEMENT aux questions sur le PD, la confiance, la bande de risque, les features SHAP, les itérations.
- Si la question concerne la fraude, les garanties, la politique BCT ou les contrefactuels :
  réponds "Cette question concerne [Agent Fraude / Agent Garanties / Agent Politique / Agent XAI]."
- Explique tes calculs avec rigueur, en t'appuyant sur les valeurs réelles ci-dessus.
- Réponds en français. Maximum 3 paragraphes."""

    def _guarantee_prompt(self, data: Dict[str, Any], loan: Dict[str, Any]) -> str:
        ready      = data.get("guarantee_ready_for_scoring") or data.get("ready_for_scoring")
        missing    = data.get("missing_documents") or data.get("documents_manquants") or []
        issues     = data.get("document_issues") or {}
        verdict    = data.get("verdict", "non évalué")
        note       = data.get("note_comite", "")
        blocking   = data.get("blocking_reasons") or []

        # Guarantee details
        gd         = data.get("guarantee_details") or {}
        g_primary  = gd.get("primary_guarantee") or data.get("garantie_principale", "non spécifiée")
        g_second   = gd.get("secondary_guarantee") or data.get("garantie_secondaire")
        g_risk     = gd.get("risk_level") or data.get("extracted_features", {}).get("guarantee_risk_level", "non évalué")
        g_notary   = gd.get("requires_notarized_deed", False)
        g_cpf      = gd.get("cpf_registration_required", False)

        # Insurance details
        ins        = data.get("insurance_details") or {}
        ins_req    = ins.get("required") or data.get("assurances_requises") or []
        ins_pres   = ins.get("present") or data.get("assurances_presentes") or []
        ins_miss   = ins.get("missing") or []
        ins_ok     = ins.get("is_compliant", len(ins_miss) == 0)

        # Document intelligence — extracted fields from CIN, payslips, etc.
        doc_intel  = data.get("document_intelligence") or {}
        applicant  = doc_intel.get("applicant") or {}
        employment = doc_intel.get("employment") or {}
        doc_verif  = doc_intel.get("document_verification") or {}
        consistency= doc_intel.get("consistency_checks") or []
        confidence = doc_intel.get("confidence", "non évalué")

        missing_str  = ", ".join(missing) if missing else "aucun"
        issues_str   = "; ".join(f"{k}: {', '.join(v) if isinstance(v, list) else v}"
                                  for k, v in issues.items()) if issues else "aucun"
        blocking_str = "\n".join(f"  • {r}" for r in blocking) if blocking else "  Aucun"
        ins_req_str  = ", ".join(ins_req) if ins_req else "aucune"
        ins_pres_str = ", ".join(ins_pres) if ins_pres else "aucune"
        ins_miss_str = ", ".join(ins_miss) if ins_miss else "aucune"

        # CIN / identity extraction
        cin_block = ""
        if applicant:
            cin_block = f"""
DONNÉES EXTRAITES DE LA CIN / IDENTITÉ :
- Nom complet     : {applicant.get('full_name') or 'non extrait'}
- Nom             : {applicant.get('last_name') or 'non extrait'}
- Prénom          : {applicant.get('first_name') or 'non extrait'}
- Numéro CIN      : {applicant.get('cin_number') or 'non extrait'}
- Date naissance  : {applicant.get('birth_date') or 'non extraite'}
- Date expiration CIN : {applicant.get('cin_expiry_date') or 'non extraite'}
- Genre           : {applicant.get('gender') or 'non extrait'}
- Adresse         : {applicant.get('address') or 'non extraite'}
- Gouvernorat     : {applicant.get('governorate') or 'non extrait'}
- Validité CIN    : {doc_verif.get('cin_validity', 'non évaluée')}
"""

        # Payslip / employment extraction
        emp_block = ""
        if employment:
            months = employment.get("payslip_months") or []
            emp_block = f"""
DONNÉES EXTRAITES DES FICHES DE PAIE :
- Employeur       : {employment.get('employer_name') or 'non extrait'}
- Nom employé     : {employment.get('employee_name') or 'non extrait'}
- Salaire net/mois: {employment.get('monthly_net_income') or 'non extrait'} TND
- Salaire brut/m  : {employment.get('monthly_gross_income') or 'non extrait'} TND
- Date embauche   : {employment.get('employment_start_date') or 'non extraite'}
- Mois de paie    : {', '.join(str(m) for m in months) if months else 'non détectés'}
- N° CNSS         : {employment.get('cnss_number') or 'non extrait'}
- Validité fiches : {doc_verif.get('payslips_validity', 'non évaluée')}
"""

        # Consistency checks
        consistency_str = ""
        if consistency:
            lines = []
            for c in consistency:
                if isinstance(c, dict):
                    lines.append(f"  • {c.get('field','?')}: {c.get('status','?')} "
                                 f"(doc={c.get('document_value','?')} / formulaire={c.get('input_value','?')})")
            if lines:
                consistency_str = "\nCOHÉRENCE DOCUMENT ↔ FORMULAIRE :\n" + "\n".join(lines)

        analysis_block = f"""
RÉSULTATS DE TON ANALYSE SUR CE DOSSIER :
- Verdict documentaire   : {verdict}
- Prêt pour scoring      : {'OUI ✓' if ready else ('NON ✗' if ready is False else 'Non évalué')}
- Note comité            : {note or 'non disponible'}
- Documents manquants    : {missing_str}
- Problèmes documentaires: {issues_str}
- Points bloquants       :
{blocking_str}

GARANTIES RECOMMANDÉES :
- Garantie principale    : {g_primary}
- Garantie secondaire    : {g_second or 'aucune'}
- Niveau de risque garanti: {g_risk}
- Acte notarié requis    : {'Oui' if g_notary else 'Non'}
- Inscription CPF requise : {'Oui' if g_cpf else 'Non'}

ASSURANCES :
- Requises               : {ins_req_str}
- Présentes              : {ins_pres_str}
- Manquantes             : {ins_miss_str}
- Conformité assurance   : {'Conforme ✓' if ins_ok else 'Non conforme ✗'}
{cin_block}{emp_block}{consistency_str}
- Confiance extraction   : {confidence}
"""

        return f"""Tu es l'Agent de Validation des Garanties et Documents d'AICredits.

IDENTITÉ ET MÉTHODES :
Tu valides les garanties et la complétude des dossiers de crédit selon les règles BCT et la politique AICredits.
Tu extrais et vérifies les données des documents fournis (CIN, fiches de paie, compromis de vente, justificatif de domicile).
Tu contrôles : identité (CIN/passeport), revenus (fiches de paie), domicile, garanties réelles/personnelles, assurances.
Tu bloques la transmission au scoring si des documents critiques sont absents, invalides ou incohérents.
Tu produis le verdict (OK / CONDITIONNEL / KO) et la liste des conditions de déblocage.

{analysis_block}

RÈGLES DE COMPORTEMENT :
- Tu réponds aux questions sur : garanties, assurances, documents (CIN, fiches de paie, compromis, domicile),
  données extraites des documents, cohérence documentaire, verdict, conditions de déblocage.
- C'est TOI qui as extrait les données de la CIN et des fiches de paie — réponds précisément aux questions
  sur ces données en citant les valeurs ci-dessus.
- Si la question concerne la fraude (anomalies comportementales), le scoring PD/SHAP, la politique DTI/BCT
  réglementaire ou les contrefactuels : réponds "Cette question concerne [Agent Fraude / Agent Scoring / Agent Politique / Agent XAI]."
- Cite les valeurs extraites réelles. Si une valeur est 'non extrait', dis-le clairement.
- Réponds en français. Maximum 3 paragraphes."""

    def _policy_prompt(self, data: Dict[str, Any], loan: Dict[str, Any]) -> str:
        fp            = data.get("frontend_payload") or data.get("frontendPayload") or {}
        blocking      = fp.get("blocking_reasons") or fp.get("blockingReasons") or []
        conditions    = fp.get("conditions_deblocage") or fp.get("conditionsDeblocage") or []
        rule_applied  = data.get("rule_applied") or data.get("ruleApplied") or "non spécifiée"
        decision      = (data.get("final_decision") or data.get("decision")
                         or loan.get("decision") or "non déterminée")
        dti           = loan.get("dti")
        dti_str       = f"{dti * 100:.1f}%" if isinstance(dti, (int, float)) else "non calculé"

        blocking_str   = "\n".join(f"  • {r}" for r in blocking) if blocking else "  Aucun"
        conditions_str = "\n".join(f"  • {c}" for c in conditions) if conditions else "  Aucune"

        analysis_block = f"""
RÉSULTATS DE TON ANALYSE SUR CE DOSSIER :
- Décision recommandée : {decision}
- Règle déclenchée : {rule_applied}
- Taux d'endettement (DTI) : {dti_str}
- Points bloquants identifiés :
{blocking_str}
- Conditions de déblocage :
{conditions_str}
"""

        return f"""Tu es l'Agent de Politique Crédit d'AICredits.

IDENTITÉ ET MÉTHODES :
Tu appliques les règles réglementaires de la Banque Centrale de Tunisie (BCT) et la politique interne AICredits.
Règles clés que tu contrôles :
- DTI (taux d'endettement) : seuil réglementaire BCT ≤ 40%
- Historique crédit : aucun incident de paiement actif
- Montant/durée : cohérence avec le type de crédit et le profil client
- Garanties : niveau de sûreté réelle ou personnelle requis
Tu produis la décision finale (APPROVE / REJECT / REVIEW_REQUIRED) et identifies les règles déclenchées.

{analysis_block}

RÈGLES DE COMPORTEMENT :
- Réponds UNIQUEMENT aux questions sur la politique crédit, les règles BCT, les points bloquants, les conditions de déblocage.
- Si la question concerne la fraude, le scoring PD, les garanties ou les explications SHAP :
  réponds "Cette question concerne [Agent Fraude / Agent Scoring / Agent Garanties / Agent XAI]."
- Cite les règles et articles réglementaires précis si possible.
- Réponds en français. Maximum 3 paragraphes."""

    def _xai_prompt(self, data: Dict[str, Any], loan: Dict[str, Any]) -> str:
        top_factors     = data.get("top_factors") or data.get("shap_top_features") or data.get("shapTopFeatures") or []
        counterfactuals = data.get("counterfactuals") or []
        explanation     = data.get("explanation") or loan.get("decisionSummary") or ""

        shap_lines = ""
        if top_factors:
            shap_lines = "Top facteurs SHAP :\n"
            for f in top_factors[:6]:
                if isinstance(f, dict):
                    name   = f.get("feature", "?")
                    impact = f.get("impact", "?")
                    val    = f.get("shap_value", "")
                    shap_lines += f"  • {name}: impact={impact}, SHAP={val}\n"

        cf_lines = ""
        if counterfactuals:
            cf_lines = "Contrefactuels (leviers d'amélioration) :\n"
            for cf in counterfactuals[:4]:
                if isinstance(cf, dict):
                    feat  = cf.get("feature", "?")
                    action = cf.get("action", "?")
                    curr  = cf.get("current_value") or cf.get("currentValue", "?")
                    rec   = cf.get("recommended_value") or cf.get("recommendedValue", "?")
                    cf_lines += f"  • {feat}: {action} (actuel={curr} → recommandé={rec})\n"

        analysis_block = f"""
RÉSULTATS DE TON ANALYSE SUR CE DOSSIER :
{shap_lines}
{cf_lines}
Explication naturelle : {explanation[:500] if explanation else 'Non disponible'}
"""

        return f"""Tu es l'Agent XAI (Explicabilité IA) d'AICredits.

IDENTITÉ ET MÉTHODES :
Tu génères des explications compréhensibles de la décision IA pour les conseillers.
Tu utilises les valeurs SHAP (SHapley Additive exPlanations) pour quantifier l'impact de chaque feature.
Tu produis des contrefactuels : "Si X changeait de A à B, la décision passerait de REJECT à APPROVE".
Ton rôle est de rendre la décision IA transparente, auditée et actionnable.

{analysis_block}

RÈGLES DE COMPORTEMENT :
- Réponds UNIQUEMENT aux questions sur les explications SHAP, les contrefactuels, les leviers d'amélioration, la transparence de la décision.
- Si la question concerne la fraude, le scoring brut, les garanties ou la politique BCT :
  réponds "Cette question concerne [Agent Fraude / Agent Scoring / Agent Garanties / Agent Politique]."
- Traduis les valeurs SHAP en langage clair, actionnable pour le conseiller.
- Réponds en français. Maximum 3 paragraphes."""

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _format_history(
        self, messages: Optional[List[AgentChatMessage]]
    ) -> List[Dict[str, str]]:
        if not messages:
            return []
        return [
            {"role": m.role, "content": m.content}
            for m in messages[-8:]   # 8 derniers messages
        ]


# ── Singleton ─────────────────────────────────────────────────────────────────

_agent_chat_service: Optional[AgentChatService] = None


def get_agent_chat_service() -> AgentChatService:
    global _agent_chat_service
    if _agent_chat_service is None:
        _agent_chat_service = AgentChatService()
    return _agent_chat_service
