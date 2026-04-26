import pytest
from mcp_server.guarantee_rules import GuaranteeInput, suggest_guarantee

def make_input(**kwargs) -> GuaranteeInput:
    defaults = dict(
        credit_type="consommation",
        loan_amount=20_000,
        risk_class=1,
        debt_ratio=0.25,
        is_salary_domiciled=True,
        has_existing_guarantor=False,
    )
    defaults.update(kwargs)
    return GuaranteeInput(**defaults)

class TestCreditConsommation:

    def test_salaire_domicilie_retenue_directe(self):
        result = suggest_guarantee(make_input(is_salary_domiciled=True))
        assert "Retenue directe" in result.primary_guarantee
        assert result.risk_level == "FAIBLE"

    def test_salaire_non_domicilie_cession(self):
        result = suggest_guarantee(make_input(is_salary_domiciled=False))
        assert "Cession" in result.primary_guarantee
        assert "employeur" in result.recommendation_notes[0]

class TestCreditAuto:

    def test_garantie_principale_nantissement(self):
        result = suggest_guarantee(make_input(
            credit_type="auto", loan_amount=35_000
        ))
        assert "Nantissement" in result.primary_guarantee

    def test_montant_eleve_expertise_requise(self):
        result = suggest_guarantee(make_input(
            credit_type="auto", loan_amount=55_000
        ))
        assert any("expertise" in n for n in result.recommendation_notes)

class TestCreditImmobilier:

    def test_hypotheque_cpf_obligatoire(self):
        result = suggest_guarantee(make_input(
            credit_type="immobilier", loan_amount=180_000
        ))
        assert "Hypothèque" in result.primary_guarantee
        assert result.cpf_registration_required is True
        assert result.estimated_registration_days == 45

    def test_endettement_proche_limite_caution_secondaire(self):
        result = suggest_guarantee(make_input(
            credit_type="immobilier",
            loan_amount=150_000,
            debt_ratio=0.37,
        ))
        assert result.secondary_guarantee is not None
        assert "endettement" in result.secondary_guarantee.lower()

    def test_montant_tres_eleve_notaire(self):
        result = suggest_guarantee(make_input(
            credit_type="immobilier", loan_amount=350_000
        ))
        assert any("notaire" in n for n in result.recommendation_notes)

class TestClasseRisque:

    def test_classe_4_refus_direct(self):
        result = suggest_guarantee(make_input(risk_class=4))
        assert result.risk_level == "REFUS"
        assert "REFUS" in result.primary_guarantee

    def test_classe_3_caution_solidaire(self):
        result = suggest_guarantee(make_input(risk_class=3))
        assert result.secondary_guarantee is not None
        assert "solidaire" in result.secondary_guarantee.lower()

    def test_classe_1_faible_risque(self):
        result = suggest_guarantee(make_input(
            risk_class=1, debt_ratio=0.20
        ))
        assert result.risk_level == "FAIBLE"
