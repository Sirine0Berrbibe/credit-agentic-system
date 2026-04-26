import json
from unittest.mock import MagicMock, patch

import pytest
from openai import APIConnectionError

from agent.guarantee_agent import GuaranteeAgent


def dossier_immo_ok():
    return dict(
        client_id="TEST-001",
        credit_type="immobilier",
        loan_amount=180_000,
        client_age=38,
        risk_class=1,
        debt_ratio=0.28,
        is_salary_domiciled=True,
        insurance_subscribed=[
            "Assurance décès-invalidité",
            "Assurance multirisque habitation",
        ],
        cin_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        fiches_paie_bytes=[
            ("f1.jpg", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100),
            ("f2.jpg", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100),
            ("f3.jpg", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100),
        ],
        domicile_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
    )


def dossier_immo_incomplet():
    dossier = dossier_immo_ok()
    dossier["insurance_subscribed"] = []
    dossier["fiches_paie_bytes"] = [
        ("f1.jpg", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100),
        ("f2.jpg", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100),
    ]
    return dossier


def dossier_classe4():
    dossier = dossier_immo_ok()
    dossier["risk_class"] = 4
    return dossier


def mock_llm_response(verdict: str, note: str) -> MagicMock:
    payload = {
        "verdict": verdict,
        "garantie_principale": "Hypotheque de premier rang (CPF)",
        "garantie_secondaire": None,
        "assurances_requises": [
            "Assurance décès-invalidité",
            "Assurance multirisque habitation",
        ],
        "assurances_presentes": [],
        "documents_manquants": [],
        "conditions_deblocage": [],
        "note_comite": note,
    }
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def run_integration_or_skip(dossier: dict) -> dict:
    try:
        agent = GuaranteeAgent()
        return agent.run(dossier)
    except APIConnectionError as exc:
        pytest.skip(f"Azure OpenAI unavailable for integration test: {exc}")


class TestGuaranteeAgentUnit:
    @patch("agent.guarantee_agent.AzureOpenAI")
    @patch.object(GuaranteeAgent, "_run_document_validation", return_value=([], {}, []))
    def test_dossier_complet_verdict_ok(self, _mock_validation, mock_azure):
        mock_azure.return_value.chat.completions.create.return_value = (
            mock_llm_response("OK", "Garanties conformes.")
        )

        agent = GuaranteeAgent()
        result = agent.run(dossier_immo_ok())

        assert result["verdict"] == "OK"
        assert "garantie_principale" in result
        assert "note_comite" in result

    @patch("agent.guarantee_agent.AzureOpenAI")
    def test_dossier_incomplet_verdict_conditionnel(self, mock_azure):
        payload = {
            "verdict": "CONDITIONNEL",
            "garantie_principale": "Hypotheque de premier rang (CPF)",
            "garantie_secondaire": None,
            "assurances_requises": [
                "Assurance décès-invalidité",
                "Assurance multirisque habitation",
            ],
            "assurances_presentes": [],
            "documents_manquants": ["Fiches de paie"],
            "conditions_deblocage": [
                "Fournir 3eme fiche de paie",
                "Souscrire assurances obligatoires",
            ],
            "note_comite": "2 points bloquants a regulariser avant deblocage.",
        }
        message = MagicMock()
        message.content = json.dumps(payload)
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        mock_azure.return_value.chat.completions.create.return_value = response

        agent = GuaranteeAgent()
        result = agent.run(dossier_immo_incomplet())

        assert result["verdict"] == "CONDITIONNEL"
        assert len(result["conditions_deblocage"]) > 0

    @patch("agent.guarantee_agent.AzureOpenAI")
    def test_classe4_verdict_ko(self, mock_azure):
        payload = {
            "verdict": "KO",
            "garantie_principale": "REFUS - Classe risque 4",
            "garantie_secondaire": None,
            "assurances_requises": [],
            "assurances_presentes": [],
            "documents_manquants": [],
            "conditions_deblocage": ["Classe risque 4 - refus definitif"],
            "note_comite": "Classe BCT 4: actif compromis. Refus recommande.",
        }
        message = MagicMock()
        message.content = json.dumps(payload)
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        mock_azure.return_value.chat.completions.create.return_value = response

        agent = GuaranteeAgent()
        result = agent.run(dossier_classe4())

        assert result["verdict"] == "KO"

    @patch("agent.guarantee_agent.AzureOpenAI")
    def test_json_structure_complete(self, mock_azure):
        mock_azure.return_value.chat.completions.create.return_value = (
            mock_llm_response("OK", "Dossier conforme.")
        )

        agent = GuaranteeAgent()
        result = agent.run(dossier_immo_ok())

        required_keys = [
            "verdict",
            "garantie_principale",
            "garantie_secondaire",
            "assurances_requises",
            "assurances_presentes",
            "documents_manquants",
            "conditions_deblocage",
            "note_comite",
        ]
        for key in required_keys:
            assert key in result, f"Cle manquante: {key}"

    @patch("agent.guarantee_agent.AzureOpenAI")
    def test_verdict_valeur_autorisee(self, mock_azure):
        mock_azure.return_value.chat.completions.create.return_value = (
            mock_llm_response("OK", "OK.")
        )

        agent = GuaranteeAgent()
        result = agent.run(dossier_immo_ok())

        assert result["verdict"] in ("OK", "CONDITIONNEL", "KO")


@pytest.mark.integration
class TestGuaranteeAgentIntegration:
    @pytest.mark.integration
    def test_reel_dossier_ok(self):
        result = run_integration_or_skip(dossier_immo_ok())
        assert result["verdict"] in ("OK", "CONDITIONNEL", "KO")
        assert len(result["note_comite"]) > 10

    @pytest.mark.integration
    def test_reel_dossier_incomplet(self):
        result = run_integration_or_skip(dossier_immo_incomplet())
        assert result["verdict"] in ("CONDITIONNEL", "KO")
