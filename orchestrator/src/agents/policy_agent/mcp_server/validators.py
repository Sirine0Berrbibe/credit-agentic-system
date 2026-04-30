"""
Validators — Policy Agent
Valide les inputs reçus par le MCP server avant traitement.
"""

from typing import Any, Dict, List, Tuple


def validate_policy_request(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Valide la requête entrante du policy agent. Retourne (is_valid, errors)."""
    errors: List[str] = []

    pd_score = data.get("final_pd_score")
    if pd_score is not None:
        try:
            pd_f = float(pd_score)
            if not (0.0 <= pd_f <= 1.0):
                errors.append(f"final_pd_score={pd_f} doit être compris entre 0 et 1")
        except (TypeError, ValueError):
            errors.append(f"final_pd_score={pd_score!r} n'est pas un nombre valide")

    client_data = data.get("client_data", {})
    if not isinstance(client_data, dict):
        errors.append("client_data doit être un objet JSON")

    loan_amount = client_data.get("loan_amount", client_data.get("AMT_CREDIT", 0))
    try:
        if float(loan_amount) < 0:
            errors.append(f"loan_amount={loan_amount} ne peut pas être négatif")
    except (TypeError, ValueError):
        errors.append(f"loan_amount={loan_amount!r} n'est pas un nombre valide")

    age = client_data.get("client_age", client_data.get("age"))
    if age is not None:
        try:
            age_i = int(float(age))
            if not (0 < age_i < 120):
                errors.append(f"client_age={age_i} hors plage valide (1–120)")
        except (TypeError, ValueError):
            errors.append(f"client_age={age!r} n'est pas un entier valide")

    return len(errors) == 0, errors


def validate_dti(monthly_payment: float, monthly_income: float) -> Tuple[bool, float, str]:
    """
    Calcule et valide le taux d'endettement.
    Retourne (is_compliant, dti_ratio, message).
    """
    if monthly_income <= 0:
        return False, 0.0, "Revenu mensuel nul ou négatif — impossible de calculer le DTI"
    dti = monthly_payment / monthly_income
    if dti > 0.40:
        return False, dti, f"DTI={dti*100:.1f}% dépasse le plafond BCT de 40% (règle BCT-2024-DTI-001)"
    if dti > 0.35:
        return True, dti, f"DTI={dti*100:.1f}% entre 35% et 40% — zone d'attention"
    return True, dti, f"DTI={dti*100:.1f}% conforme au plafond BCT"


def validate_age_at_maturity(age: int, duration_months: int) -> Tuple[bool, float, str]:
    """Vérifie que l'emprunteur n'aura pas plus de 70 ans à l'échéance."""
    age_at_end = age + duration_months / 12
    if age_at_end > 70:
        return False, age_at_end, f"Âge à l'échéance={age_at_end:.1f} ans dépasse 70 ans (règle BCT-2024-AGE-002)"
    return True, age_at_end, f"Âge à l'échéance={age_at_end:.1f} ans conforme"
