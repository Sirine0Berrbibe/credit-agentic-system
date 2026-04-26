import unicodedata

from pydantic import BaseModel


class InsuranceInput(BaseModel):
    credit_type: str
    loan_amount: float
    client_age: int
    subscribed: list[str]


class InsuranceOutput(BaseModel):
    required: list[str]
    missing: list[str]
    present: list[str]
    is_compliant: bool
    is_blocking: bool
    warnings: list[str]
    estimated_premium_note: str


_REQUIRED_BY_TYPE = {
    "consommation": ["Assurance décès-invalidité"],
    "auto": [
        "Assurance décès-invalidité",
        "Assurance tous risques véhicule",
    ],
    "immobilier": [
        "Assurance décès-invalidité",
        "Assurance multirisque habitation",
    ],
}


def check_insurance(inp: InsuranceInput) -> InsuranceOutput:
    required = _REQUIRED_BY_TYPE.get(inp.credit_type, [])
    normalized_subscribed = {
        _normalize_label(item): item for item in inp.subscribed
    }
    missing = [
        item for item in required if _normalize_label(item) not in normalized_subscribed
    ]
    present = [
        item for item in required if _normalize_label(item) in normalized_subscribed
    ]
    warnings: list[str] = []

    if inp.client_age > 55:
        warnings.append(
            f"Assuré de {inp.client_age} ans - prime majorée probable, "
            "questionnaire médical requis par certains assureurs"
        )
    if inp.client_age > 65:
        warnings.append(
            "Assure > 65 ans - certains assureurs refusent la couverture, "
            "verifier acceptabilite avant engagement"
        )

    if inp.loan_amount > 200_000:
        warnings.append(
            f"Montant {inp.loan_amount:,.0f} DT - expertise médicale "
            "et bilan de santé probablement exigés"
        )

    if inp.credit_type == "immobilier":
        base_rate = 0.003 if inp.client_age < 45 else 0.005
        annual = inp.loan_amount * base_rate
        note = (
            f"Prime assurance vie estimee : ~{annual:,.0f} DT/an "
            f"(taux indicatif {base_rate * 100:.1f}%/an selon age)"
        )
    elif inp.credit_type == "auto":
        note = "Prime tous risques : depend du modele et de la valeur du vehicule"
    else:
        note = "Prime deces-invalidite : negligeable sur petits montants"

    return InsuranceOutput(
        required=required,
        missing=missing,
        present=present,
        is_compliant=len(missing) == 0,
        is_blocking=len(missing) > 0,
        warnings=warnings,
        estimated_premium_note=note,
    )


def apply_insurance_rules(data: dict) -> dict:
    return check_insurance(InsuranceInput(**data)).model_dump()


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()
