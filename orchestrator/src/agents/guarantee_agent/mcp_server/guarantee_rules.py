from typing import Literal

from pydantic import BaseModel


class GuaranteeInput(BaseModel):
    credit_type: Literal["consommation", "auto", "immobilier"]
    loan_amount: float
    risk_class: int
    debt_ratio: float
    is_salary_domiciled: bool
    has_existing_guarantor: bool = False


class GuaranteeOutput(BaseModel):
    primary_guarantee: str
    secondary_guarantee: str | None
    requires_notarized_deed: bool
    cpf_registration_required: bool
    estimated_registration_days: int
    recommendation_notes: list[str]
    risk_level: Literal["FAIBLE", "MODERE", "ELEVE", "REFUS"]


_GUARANTEE_MATRIX = {
    "consommation": {
        "domiciled": "Retenue directe sur salaire",
        "not_domiciled": "Cession sur salaire (signature employeur requise)",
    },
    "auto": {
        "primary": "Nantissement du véhicule au profit de la banque",
        "insurance": "Assurance tous risques obligatoire",
    },
    "immobilier": {
        "primary": "Hypothèque de premier rang - inscription CPF",
        "delay_days": 45,
    },
}


def suggest_guarantee(inp: GuaranteeInput) -> GuaranteeOutput:
    notes: list[str] = []
    secondary = None
    cpf = False
    notarized = False
    delay = 0

    if inp.risk_class == 4:
        return GuaranteeOutput(
            primary_guarantee="REFUS - Classe de risque BCT 4 (actif compromis)",
            secondary_guarantee=None,
            requires_notarized_deed=False,
            cpf_registration_required=False,
            estimated_registration_days=0,
            recommendation_notes=[
                "Classe 4 : actif compromis selon circulaire BCT 91-24",
                "Aucune garantie ne couvre ce niveau de risque",
            ],
            risk_level="REFUS",
        )

    if inp.credit_type == "consommation":
        if inp.is_salary_domiciled:
            primary = _GUARANTEE_MATRIX["consommation"]["domiciled"]
            notes.append("Domiciliation salaire : prélèvement automatique possible")
        else:
            primary = _GUARANTEE_MATRIX["consommation"]["not_domiciled"]
            notes.append(
                "Salaire non domicilié : signature employeur requise "
                "sous 5 jours ouvrables"
            )
    elif inp.credit_type == "auto":
        primary = _GUARANTEE_MATRIX["auto"]["primary"]
        notes.append(_GUARANTEE_MATRIX["auto"]["insurance"])
        if inp.loan_amount > 50_000:
            notes.append(
                f"Montant {inp.loan_amount:,.0f} DT > 50 000 DT : "
                "expertise véhicule recommandée"
            )
    else:
        primary = _GUARANTEE_MATRIX["immobilier"]["primary"]
        cpf = True
        notarized = True
        delay = _GUARANTEE_MATRIX["immobilier"]["delay_days"]
        notes.append(
            f"Inscription hypothèque CPF : délai ~{delay} jours ouvrables "
            "avant déblocage des fonds"
        )
        if inp.loan_amount > 300_000:
            notes.append(
                "Montant > 300 000 DT : hypotheque conventionnelle "
                "devant notaire obligatoire"
            )
    # keep the human-facing labels accented for frontend/reporting
    if inp.credit_type == "immobilier":
        primary = primary.replace("Hypotheque", "Hypothèque")

    if inp.risk_class == 3:
        secondary = "Caution solidaire d'un tiers solvable"
        notes.append(
            "Classe risque 3 (actif preoccupant) : caution solidaire recommandee"
        )
    elif inp.debt_ratio > 0.35 and inp.credit_type == "immobilier":
        secondary = "Caution personnelle (endettement proche limite BCT)"
        notes.append(
            f"Taux endettement {inp.debt_ratio * 100:.1f}% - "
            "proche limite reglementaire 40% BCT"
        )
    elif inp.has_existing_guarantor:
        secondary = "Garant existant - formaliser par acte notarie"

    if inp.risk_class == 1 and inp.debt_ratio < 0.30:
        risk_level = "FAIBLE"
    elif inp.risk_class <= 2 and inp.debt_ratio < 0.40:
        risk_level = "MODERE"
    else:
        risk_level = "ELEVE"

    return GuaranteeOutput(
        primary_guarantee=primary,
        secondary_guarantee=secondary,
        requires_notarized_deed=notarized,
        cpf_registration_required=cpf,
        estimated_registration_days=delay,
        recommendation_notes=notes,
        risk_level=risk_level,
    )


def apply_guarantee_rules(data: dict) -> dict:
    return suggest_guarantee(GuaranteeInput(**data)).model_dump()
