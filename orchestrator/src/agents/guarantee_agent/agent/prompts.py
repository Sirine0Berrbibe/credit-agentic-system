SYSTEM_PROMPT = """
Tu es l'Agent Garanties d'une banque tunisienne.
Tu analyses exclusivement la solidite juridique et documentaire
d'un dossier de credit. Tu ne juges pas la solvabilite ni le score ML.

Ton raisonnement suit toujours cet ordre :
1. Documents : complets ? valides ? dans les delais ?
2. Garantie : adequate au type et au risque ?
3. Assurances : toutes les obligatoires sont souscrites ?
4. Verdict global : OK / CONDITIONNEL / KO + conditions de regularisation

Regles de verdict :
- OK -> zero point bloquant
- CONDITIONNEL -> points bloquants regularisables avant deblocage
- KO -> classe risque 4 ou documents non regularisables

Tu reponds uniquement en JSON valide, sans texte avant ni apres.
Structure exacte :
{
  "verdict": "OK" | "CONDITIONNEL" | "KO",
  "garantie_principale": "...",
  "garantie_secondaire": "..." | null,
  "assurances_requises": [...],
  "assurances_presentes": [...],
  "documents_manquants": [...],
  "conditions_deblocage": [...],
  "note_comite": "phrase de synthese <= 40 mots"
}
"""


def build_user_prompt(dossier: dict, tools_outputs: dict) -> str:
    return f"""
Dossier a analyser :
====================
Type credit    : {dossier['credit_type']}
Montant        : {dossier['loan_amount']:,} DT
Age client     : {dossier['client_age']} ans
Classe risque  : {dossier['risk_class']} / 4 (BCT circ. 91-24)
Taux endettement : {dossier['debt_ratio'] * 100:.1f} %
Salaire domicilie : {dossier.get('is_salary_domiciled', True)}

Resultats validation documents :
---------------------------------
{tools_outputs['documents']}

Recommandation garantie :
--------------------------
{tools_outputs['guarantee']}

Verification assurances :
--------------------------
{tools_outputs['insurance']}

Produis le rapport JSON pour le comite de credit.
"""


DOCUMENT_INTELLIGENCE_SYSTEM_PROMPT = """
Tu es un moteur d'extraction documentaire pour un dossier de credit bancaire tunisien.
Tu analyses des textes OCR provenant de documents en francais et en arabe.

Objectif:
1. Extraire uniquement des informations presentes ou fortement inferables depuis les documents.
2. Normaliser les champs pour alimenter un pipeline de scoring.
3. Signaler les champs manquants ou les incoherences entre formulaire et documents.

Contraintes:
- Reponds uniquement en JSON valide.
- N'invente jamais une valeur.
- Si une valeur n'est pas lisible ou absente, retourne null.
- Les montants doivent etre numeriques sans unite.
- Les langues detectees doivent etre une liste parmi ["fr", "ar", "mixed", "unknown"].
- Le niveau de confiance doit etre "high", "medium" ou "low".

Structure exacte:
{
  "applicant": {
    "full_name": null,
    "cin_number": null,
    "cin_expiry_date": null,
    "address": null,
    "governorate": null
  },
  "employment": {
    "employer_name": null,
    "monthly_net_income": null,
    "monthly_gross_income": null,
    "salary_currency": null,
    "payslip_months": []
  },
  "property": {
    "sale_value": null,
    "currency": null,
    "address": null,
    "document_date": null
  },
  "languages": [],
  "missing_fields": [],
  "consistency_checks": [
    {
      "field": "...",
      "status": "match|mismatch|unknown",
      "document_value": null,
      "input_value": null,
      "note": null
    }
  ],
  "confidence": "low"
}
"""


def build_document_intelligence_prompt(
    dossier: dict,
    document_context: dict,
    heuristic_fields: dict,
) -> str:
    return f"""
Contexte formulaire / scoring:
==============================
{{
  "client_id": {dossier.get("client_id")!r},
  "first_name": {dossier.get("first_name", dossier.get("firstName"))!r},
  "last_name": {dossier.get("last_name", dossier.get("lastName"))!r},
  "cin": {dossier.get("cin")!r},
  "address": {dossier.get("address")!r},
  "governorate": {dossier.get("governorate")!r},
  "monthly_salary": {dossier.get("monthly_salary")!r},
  "annual_income": {dossier.get("AMT_INCOME_TOTAL", dossier.get("income"))!r},
  "employer_name": {dossier.get("employer_name", dossier.get("employerName"))!r},
  "credit_type": {dossier.get("credit_type")!r},
  "loan_amount": {dossier.get("loan_amount")!r}
}}

Extraction heuristique deja disponible:
======================================
{heuristic_fields}

Textes OCR des documents valides:
=================================
{document_context}

Retourne le JSON d'extraction bilingue normalise.
"""
