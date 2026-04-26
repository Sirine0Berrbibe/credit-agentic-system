import pytest
from mcp_server.insurance_rules import InsuranceInput, check_insurance

def make_input(**kwargs) -> InsuranceInput:
    defaults = dict(
        credit_type="consommation",
        loan_amount=20_000,
        client_age=35,
        subscribed=[],
    )
    defaults.update(kwargs)
    return InsuranceInput(**defaults)

class TestAssuranceObligatoire:

    def test_conso_sans_assurance_bloquant(self):
        result = check_insurance(make_input())
        assert "Assurance décès-invalidité" in result.missing
        assert result.is_blocking is True

    def test_conso_avec_assurance_conforme(self):
        result = check_insurance(make_input(
            subscribed=["Assurance décès-invalidité"]
        ))
        assert result.is_compliant is True
        assert result.is_blocking is False

    def test_immobilier_deux_assurances_requises(self):
        result = check_insurance(make_input(credit_type="immobilier"))
        assert len(result.required) == 2
        assert "Assurance multirisque habitation" in result.required

    def test_immobilier_une_seule_fournie_bloquant(self):
        result = check_insurance(make_input(
            credit_type="immobilier",
            subscribed=["Assurance décès-invalidité"]
        ))
        assert result.is_blocking is True
        assert "Assurance multirisque habitation" in result.missing

    def test_auto_deux_assurances_requises(self):
        result = check_insurance(make_input(credit_type="auto"))
        assert "Assurance tous risques véhicule" in result.required

class TestAvertissementsAge:

    def test_age_55_avertissement_majoration(self):
        result = check_insurance(make_input(client_age=57))
        assert any("55 ans" in w or "majorée" in w for w in result.warnings)

    def test_age_66_avertissement_refus_possible(self):
        result = check_insurance(make_input(client_age=66))
        assert any("65 ans" in w or "refusent" in w for w in result.warnings)

class TestEstimationPrime:

    def test_immobilier_prime_estimee_presente(self):
        result = check_insurance(make_input(
            credit_type="immobilier", loan_amount=200_000
        ))
        assert "DT/an" in result.estimated_premium_note

    def test_montant_eleve_expertise_medicale(self):
        result = check_insurance(make_input(
            credit_type="immobilier", loan_amount=250_000
        ))
        assert any("médicale" in w for w in result.warnings)
