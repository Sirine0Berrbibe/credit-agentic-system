import base64
import json
import logging
import re
from typing import Any, Literal

from openai import AzureOpenAI
from pydantic import BaseModel, Field

try:
    from src.agents.guarantee_agent.config import settings
    from src.agents.guarantee_agent.agent.prompts import (
        DOCUMENT_INTELLIGENCE_SYSTEM_PROMPT,
        SYSTEM_PROMPT,
        build_document_intelligence_prompt,
        build_user_prompt,
    )
    from src.agents.guarantee_agent.mcp_server.validators import (
        DocumentResult,
        detect_document_languages,
        extract_document_text,
        validate_cin,
        validate_compromis_vente,
        validate_fiches_paie,
        validate_justificatif_domicile,
    )
    from src.agents.guarantee_agent.mcp_server.guarantee_rules import (
        GuaranteeInput,
        GuaranteeOutput,
        suggest_guarantee,
    )
    from src.agents.guarantee_agent.mcp_server.insurance_rules import (
        InsuranceInput,
        InsuranceOutput,
        check_insurance,
    )
except ImportError:
    from config import settings
    from agent.prompts import (
        DOCUMENT_INTELLIGENCE_SYSTEM_PROMPT,
        SYSTEM_PROMPT,
        build_document_intelligence_prompt,
        build_user_prompt,
    )
    from mcp_server.validators import (
        DocumentResult,
        detect_document_languages,
        extract_document_text,
        validate_cin,
        validate_compromis_vente,
        validate_fiches_paie,
        validate_justificatif_domicile,
    )
    from mcp_server.guarantee_rules import (
        GuaranteeInput,
        GuaranteeOutput,
        suggest_guarantee,
    )
    from mcp_server.insurance_rules import (
        InsuranceInput,
        InsuranceOutput,
        check_insurance,
    )

logger = logging.getLogger(__name__)


class GuaranteeAnalysis(BaseModel):
    verdict: Literal["OK", "CONDITIONNEL", "KO"]
    garantie_principale: str
    garantie_secondaire: str | None
    assurances_requises: list[str]
    assurances_presentes: list[str]
    documents_manquants: list[str]
    conditions_deblocage: list[str]
    note_comite: str
    ready_for_scoring: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    document_results: list[dict[str, Any]] = Field(default_factory=list)
    document_issues: dict[str, list[str]] = Field(default_factory=dict)
    document_status: dict[str, dict[str, Any]] = Field(default_factory=dict)
    extracted_features: dict[str, Any] = Field(default_factory=dict)
    document_intelligence: dict[str, Any] = Field(default_factory=dict)
    guarantee_details: dict[str, Any] = Field(default_factory=dict)
    insurance_details: dict[str, Any] = Field(default_factory=dict)
    frontend_payload: dict[str, Any] = Field(default_factory=dict)
    scoring_payload: dict[str, Any] = Field(default_factory=dict)


class GuaranteeAgent:
    BASE_REQUIRED_DOCUMENTS = [
        ("cin_bytes", "CIN"),
        ("fiches_paie_bytes", "Fiches de paie"),
        ("domicile_bytes", "Justificatif domicile"),
    ]

    CONDITIONAL_REQUIRED_DOCUMENTS = {
        "immobilier": [
            ("compromis_vente_bytes", "Compromis de vente"),
        ],
    }

    OPTIONAL_DOCUMENTS = [
        ("compromis_vente_bytes", "Compromis de vente"),
    ]

    def __init__(
        self,
        enable_llm: bool = True,
        enable_document_intelligence: bool = False,
        enable_summary_llm: bool = True,
        llm_client: Any | None = None,
        deployment: str | None = None,
    ):
        self.llm = llm_client
        self.deployment = deployment
        self.enable_document_intelligence = enable_document_intelligence
        self.enable_summary_llm = enable_summary_llm

        if self.llm is None and enable_llm:
            try:
                self.llm = AzureOpenAI(
                    azure_endpoint=settings.azure_openai_endpoint,
                    api_key=settings.azure_openai_key,
                    api_version=settings.azure_openai_api_version,
                )
                self.deployment = deployment or settings.azure_openai_deployment
            except Exception as exc:
                logger.warning(
                    "GuaranteeAgent LLM unavailable, using deterministic fallback: %s",
                    exc,
                )
                self.llm = None
                self.deployment = deployment

    def run(self, dossier: dict, require_documents: bool = True) -> dict:
        analysis = self.analyze(dossier, require_documents=require_documents)

        if self.enable_document_intelligence:
            try:
                analysis = self._enrich_with_document_intelligence(dossier, analysis)
            except Exception as exc:
                logger.warning(
                    "GuaranteeAgent document intelligence enrichment failed, using deterministic extraction: %s",
                    exc,
                )

        if not self.enable_summary_llm or not self.llm or not self.deployment:
            return analysis.model_dump()

        try:
            return self._synthesize_with_llm(dossier, analysis)
        except Exception as exc:
            logger.warning("GuaranteeAgent LLM synthesis failed, using fallback: %s", exc)
            return analysis.model_dump()

    def analyze(self, dossier: dict, require_documents: bool = True) -> GuaranteeAnalysis:
        dossier = self._normalize_dossier(dossier)

        logger.info(
            "GuaranteeAgent starting deterministic analysis for dossier %s",
            dossier.get("client_id", "?"),
        )

        document_results, document_issues, missing_documents = self._run_document_validation(
            dossier,
            require_documents=require_documents,
        )
        guarantee_result = self._run_guarantee_selection(dossier)
        insurance_result = self._run_insurance_check(dossier)

        conditions_deblocage = self._build_conditions(
            missing_documents,
            document_issues,
            insurance_result,
        )

        blocking_reasons = []
        if guarantee_result.risk_level == "REFUS":
            blocking_reasons.append(guarantee_result.primary_guarantee)
        if insurance_result.is_blocking:
            blocking_reasons.extend(
                [f"Assurance manquante: {item}" for item in insurance_result.missing]
            )
        for doc_type, issues in document_issues.items():
            blocking_reasons.extend([f"{doc_type}: {issue}" for issue in issues])

        verdict = self._compute_verdict(
            guarantee_result=guarantee_result,
            insurance_result=insurance_result,
            missing_documents=missing_documents,
            document_issues=document_issues,
        )
        ready_for_scoring = verdict == "OK"

        extracted_features = self._build_extracted_features(
            dossier=dossier,
            document_results=document_results,
            guarantee_result=guarantee_result,
            insurance_result=insurance_result,
            missing_documents=missing_documents,
            document_issues=document_issues,
            verdict=verdict,
        )
        note_comite = self._build_note(
            verdict=verdict,
            missing_documents=missing_documents,
            insurance_result=insurance_result,
            guarantee_result=guarantee_result,
        )
        document_status = self._build_document_status(
            dossier=dossier,
            document_results=document_results,
            missing_documents=missing_documents,
            document_issues=document_issues,
        )
        frontend_payload = self._build_frontend_payload(
            verdict=verdict,
            ready_for_scoring=ready_for_scoring,
            note_comite=note_comite,
            missing_documents=missing_documents,
            document_issues=document_issues,
            document_status=document_status,
            conditions_deblocage=conditions_deblocage,
            blocking_reasons=blocking_reasons,
        )
        scoring_payload = self._build_scoring_payload(
            dossier=dossier,
            verdict=verdict,
            ready_for_scoring=ready_for_scoring,
            extracted_features=extracted_features,
            guarantee_result=guarantee_result,
            insurance_result=insurance_result,
            document_status=document_status,
        )

        analysis = GuaranteeAnalysis(
            verdict=verdict,
            garantie_principale=guarantee_result.primary_guarantee,
            garantie_secondaire=guarantee_result.secondary_guarantee,
            assurances_requises=insurance_result.required,
            assurances_presentes=insurance_result.present,
            documents_manquants=missing_documents,
            conditions_deblocage=conditions_deblocage,
            note_comite=note_comite,
            ready_for_scoring=ready_for_scoring,
            blocking_reasons=blocking_reasons,
            document_results=[result.model_dump() for result in document_results],
            document_issues=document_issues,
            document_status=document_status,
            extracted_features=extracted_features,
            guarantee_details=guarantee_result.model_dump(),
            insurance_details=insurance_result.model_dump(),
            frontend_payload=frontend_payload,
            scoring_payload=scoring_payload,
        )

        logger.info(
            "GuaranteeAgent deterministic verdict for %s: %s",
            dossier.get("client_id", "?"),
            analysis.verdict,
        )

        return analysis

    def _synthesize_with_llm(
        self,
        dossier: dict,
        analysis: GuaranteeAnalysis,
    ) -> dict:
        tools_outputs = {
            "documents": json.dumps(
                analysis.document_results,
                ensure_ascii=False,
                indent=2,
            ),
            "guarantee": json.dumps(
                analysis.guarantee_details,
                ensure_ascii=False,
                indent=2,
            ),
            "insurance": json.dumps(
                analysis.insurance_details,
                ensure_ascii=False,
                indent=2,
            ),
        }

        response = self.llm.chat.completions.create(
            model=self.deployment,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(dossier, tools_outputs)},
            ],
            temperature=0,
            max_tokens=800,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        synthesized = json.loads(raw)

        # Preserve deterministic orchestration fields even when LLM is used.
        synthesized.update(
            {
                "ready_for_scoring": analysis.ready_for_scoring,
                "blocking_reasons": analysis.blocking_reasons,
                "document_results": analysis.document_results,
                "document_issues": analysis.document_issues,
                "document_status": analysis.document_status,
                "extracted_features": analysis.extracted_features,
                "document_intelligence": analysis.document_intelligence,
                "guarantee_details": analysis.guarantee_details,
                "insurance_details": analysis.insurance_details,
                "frontend_payload": analysis.frontend_payload,
                "scoring_payload": analysis.scoring_payload,
            }
        )

        return synthesized

    def _enrich_with_document_intelligence(
        self,
        dossier: dict,
        analysis: GuaranteeAnalysis,
    ) -> GuaranteeAnalysis:
        normalized_dossier = self._normalize_dossier(dossier)
        heuristic_intelligence = self._build_heuristic_document_intelligence(
            dossier=normalized_dossier,
            analysis=analysis,
        )

        document_intelligence = heuristic_intelligence
        if (
            self.llm
            and self.deployment
            and self._should_extract_document_intelligence(analysis)
        ):
            llm_document_intelligence = self._extract_document_intelligence_with_llm(
                dossier=normalized_dossier,
                analysis=analysis,
                heuristic_intelligence=heuristic_intelligence,
            )
            document_intelligence = self._merge_document_intelligence(
                heuristic_intelligence,
                llm_document_intelligence,
            )

        flattened_features = self._flatten_document_intelligence(document_intelligence)
        extracted_features = {
            **analysis.extracted_features,
            **flattened_features,
        }
        combined_features = self._build_combined_scoring_features(
            dossier=normalized_dossier,
            extracted_features=extracted_features,
            document_intelligence=document_intelligence,
        )
        scoring_payload = {
            **analysis.scoring_payload,
            "document_features": extracted_features,
            "document_intelligence": document_intelligence,
            "combined_features": combined_features,
        }

        return analysis.model_copy(
            update={
                "extracted_features": extracted_features,
                "document_intelligence": document_intelligence,
                "scoring_payload": scoring_payload,
            }
        )

    def _should_extract_document_intelligence(
        self,
        analysis: GuaranteeAnalysis,
    ) -> bool:
        return not analysis.documents_manquants and not analysis.document_issues

    def _build_heuristic_document_intelligence(
        self,
        dossier: dict,
        analysis: GuaranteeAnalysis,
    ) -> dict[str, Any]:
        applicant = {
            "full_name": self._join_non_empty(
                dossier.get("first_name", dossier.get("firstName")),
                dossier.get("last_name", dossier.get("lastName")),
            ),
            "cin_number": analysis.extracted_features.get("cin_cin_number")
            or dossier.get("cin"),
            "cin_expiry_date": analysis.extracted_features.get("cin_expiry_date"),
            "address": dossier.get("address"),
            "governorate": dossier.get("governorate"),
        }
        employment = {
            "employer_name": dossier.get("employer_name", dossier.get("employerName")),
            "monthly_net_income": self._to_optional_float(dossier.get("monthly_salary")),
            "monthly_gross_income": None,
            "salary_currency": "TND"
            if dossier.get("monthly_salary") is not None or dossier.get("AMT_INCOME_TOTAL") is not None
            else None,
            "payslip_months": analysis.extracted_features.get(
                "fiches_de_paie_months_found",
                [],
            )
            or [],
        }
        property_data = {
            "sale_value": None,
            "currency": "TND" if dossier.get("credit_type") == "immobilier" else None,
            "address": None,
            "document_date": analysis.extracted_features.get(
                "compromis_de_vente_compromis_date"
            ),
        }

        languages: list[str] = []
        if dossier.get("cin_bytes"):
            languages.extend(self._detect_languages_for_file(*dossier["cin_bytes"]))
        if dossier.get("domicile_bytes"):
            languages.extend(self._detect_languages_for_file(*dossier["domicile_bytes"]))
        for payslip in dossier.get("fiches_paie_bytes", []):
            languages.extend(self._detect_languages_for_file(*payslip))
        if dossier.get("compromis_vente_bytes"):
            languages.extend(
                self._detect_languages_for_file(*dossier["compromis_vente_bytes"])
            )

        languages = self._dedupe_preserve_order(languages) or ["unknown"]
        missing_fields = [
            field_name
            for field_name, value in {
                "cin_number": applicant["cin_number"],
                "cin_expiry_date": applicant["cin_expiry_date"],
                "monthly_net_income": employment["monthly_net_income"],
            }.items()
            if value in (None, "", [])
        ]

        consistency_checks = self._build_consistency_checks(
            dossier=dossier,
            applicant=applicant,
            employment=employment,
            property_data=property_data,
        )

        return {
            "applicant": applicant,
            "employment": employment,
            "property": property_data,
            "languages": languages,
            "missing_fields": missing_fields,
            "consistency_checks": consistency_checks,
            "confidence": "medium" if analysis.document_results else "low",
        }

    def _extract_document_intelligence_with_llm(
        self,
        dossier: dict,
        analysis: GuaranteeAnalysis,
        heuristic_intelligence: dict[str, Any],
    ) -> dict[str, Any]:
        document_context = self._build_document_context(dossier)
        if not document_context:
            return heuristic_intelligence

        response = self.llm.chat.completions.create(
            model=self.deployment,
            messages=[
                {
                    "role": "system",
                    "content": DOCUMENT_INTELLIGENCE_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": build_document_intelligence_prompt(
                        dossier=dossier,
                        document_context=json.dumps(
                            document_context,
                            ensure_ascii=False,
                            indent=2,
                        ),
                        heuristic_fields=json.dumps(
                            heuristic_intelligence,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    ),
                },
            ],
            temperature=0,
            max_tokens=1200,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        return {
            "applicant": parsed.get("applicant", {}) or {},
            "employment": parsed.get("employment", {}) or {},
            "property": parsed.get("property", {}) or {},
            "languages": parsed.get("languages", []) or [],
            "missing_fields": parsed.get("missing_fields", []) or [],
            "consistency_checks": parsed.get("consistency_checks", []) or [],
            "confidence": parsed.get("confidence", "low") or "low",
        }

    def _build_document_context(self, dossier: dict) -> dict[str, Any]:
        context: dict[str, Any] = {}

        if dossier.get("cin_bytes"):
            filename, content = dossier["cin_bytes"]
            context["CIN"] = self._document_context_item(filename, content)

        if dossier.get("domicile_bytes"):
            filename, content = dossier["domicile_bytes"]
            context["Justificatif domicile"] = self._document_context_item(
                filename,
                content,
            )

        if dossier.get("compromis_vente_bytes"):
            filename, content = dossier["compromis_vente_bytes"]
            context["Compromis de vente"] = self._document_context_item(
                filename,
                content,
            )

        payslip_context = []
        for filename, content in dossier.get("fiches_paie_bytes", []):
            payslip_context.append(self._document_context_item(filename, content))
        if payslip_context:
            context["Fiches de paie"] = payslip_context

        return context

    def _document_context_item(self, filename: str, content: bytes) -> dict[str, Any]:
        text = extract_document_text(content, filename)
        compact_text = re.sub(r"\s+", " ", text or "").strip()
        return {
            "filename": filename,
            "languages": detect_document_languages(text),
            "text_excerpt": compact_text[:3500],
        }

    def _merge_document_intelligence(
        self,
        heuristic_intelligence: dict[str, Any],
        llm_intelligence: dict[str, Any],
    ) -> dict[str, Any]:
        heuristic = heuristic_intelligence or {}
        llm = llm_intelligence or {}

        merged_applicant = {
            key: llm.get("applicant", {}).get(key)
            or heuristic.get("applicant", {}).get(key)
            for key in {
                "full_name",
                "cin_number",
                "cin_expiry_date",
                "address",
                "governorate",
            }
        }
        merged_employment = {
            "employer_name": llm.get("employment", {}).get("employer_name")
            or heuristic.get("employment", {}).get("employer_name"),
            "monthly_net_income": self._to_optional_float(
                llm.get("employment", {}).get("monthly_net_income")
            )
            if llm.get("employment", {}).get("monthly_net_income") is not None
            else heuristic.get("employment", {}).get("monthly_net_income"),
            "monthly_gross_income": self._to_optional_float(
                llm.get("employment", {}).get("monthly_gross_income")
            )
            if llm.get("employment", {}).get("monthly_gross_income") is not None
            else heuristic.get("employment", {}).get("monthly_gross_income"),
            "salary_currency": llm.get("employment", {}).get("salary_currency")
            or heuristic.get("employment", {}).get("salary_currency"),
            "payslip_months": self._dedupe_preserve_order(
                (llm.get("employment", {}).get("payslip_months") or [])
                + (heuristic.get("employment", {}).get("payslip_months") or [])
            ),
        }
        merged_property = {
            "sale_value": self._to_optional_float(
                llm.get("property", {}).get("sale_value")
            )
            if llm.get("property", {}).get("sale_value") is not None
            else heuristic.get("property", {}).get("sale_value"),
            "currency": llm.get("property", {}).get("currency")
            or heuristic.get("property", {}).get("currency"),
            "address": llm.get("property", {}).get("address")
            or heuristic.get("property", {}).get("address"),
            "document_date": llm.get("property", {}).get("document_date")
            or heuristic.get("property", {}).get("document_date"),
        }

        return {
            "applicant": merged_applicant,
            "employment": merged_employment,
            "property": merged_property,
            "languages": self._dedupe_preserve_order(
                (llm.get("languages") or []) + (heuristic.get("languages") or [])
            )
            or ["unknown"],
            "missing_fields": self._dedupe_preserve_order(
                (llm.get("missing_fields") or []) + (heuristic.get("missing_fields") or [])
            ),
            "consistency_checks": llm.get("consistency_checks")
            or heuristic.get("consistency_checks")
            or [],
            "confidence": llm.get("confidence")
            or heuristic.get("confidence")
            or "low",
        }

    def _flatten_document_intelligence(
        self,
        document_intelligence: dict[str, Any],
    ) -> dict[str, Any]:
        applicant = document_intelligence.get("applicant", {})
        employment = document_intelligence.get("employment", {})
        property_data = document_intelligence.get("property", {})
        consistency_checks = document_intelligence.get("consistency_checks", [])
        mismatch_count = sum(
            1 for check in consistency_checks if check.get("status") == "mismatch"
        )
        total_checks = len(consistency_checks)
        consistency_score = (
            round(max(0.0, 1 - (mismatch_count / total_checks)), 3)
            if total_checks
            else 1.0
        )

        return {
            "doc_borrower_full_name": applicant.get("full_name"),
            "doc_cin_number": applicant.get("cin_number"),
            "doc_cin_expiry_date": applicant.get("cin_expiry_date"),
            "doc_domicile_address": applicant.get("address"),
            "doc_domicile_governorate": applicant.get("governorate"),
            "doc_employer_name": employment.get("employer_name"),
            "doc_monthly_net_income": employment.get("monthly_net_income"),
            "doc_monthly_gross_income": employment.get("monthly_gross_income"),
            "doc_salary_currency": employment.get("salary_currency"),
            "doc_payslip_months": employment.get("payslip_months", []),
            "doc_property_sale_value": property_data.get("sale_value"),
            "doc_property_currency": property_data.get("currency"),
            "doc_property_address": property_data.get("address"),
            "doc_property_document_date": property_data.get("document_date"),
            "doc_detected_languages": document_intelligence.get("languages", []),
            "doc_extraction_confidence": document_intelligence.get("confidence", "low"),
            "doc_extraction_missing_fields": document_intelligence.get(
                "missing_fields",
                [],
            ),
            "doc_consistency_checks": consistency_checks,
            "doc_consistency_score": consistency_score,
        }

    def _build_combined_scoring_features(
        self,
        dossier: dict,
        extracted_features: dict[str, Any],
        document_intelligence: dict[str, Any],
    ) -> dict[str, Any]:
        combined = {
            key: value
            for key, value in dossier.items()
            if key
            not in {
                "cin_bytes",
                "domicile_bytes",
                "compromis_vente_bytes",
                "fiches_paie_bytes",
            }
        }
        combined.update(extracted_features)
        combined["document_intelligence"] = document_intelligence

        monthly_salary = self._to_optional_float(
            combined.get("monthly_salary")
            or combined.get("monthly_income")
            or combined.get("doc_monthly_net_income")
        )
        if monthly_salary is not None:
            combined.setdefault("monthly_salary", monthly_salary)
            combined.setdefault("monthly_income", monthly_salary)

        annual_income = self._to_optional_float(
            combined.get("AMT_INCOME_TOTAL")
            or combined.get("income")
        )
        if annual_income is None and monthly_salary is not None:
            annual_income = round(monthly_salary * 12, 2)
        if annual_income is not None:
            combined.setdefault("AMT_INCOME_TOTAL", annual_income)
            combined.setdefault("income", annual_income)

        if extracted_features.get("doc_property_sale_value") is not None:
            combined.setdefault(
                "estimated_property_value",
                extracted_features.get("doc_property_sale_value"),
            )
        if extracted_features.get("doc_employer_name"):
            combined.setdefault(
                "employer_name",
                extracted_features.get("doc_employer_name"),
            )

        combined["document_identity_verified"] = bool(
            extracted_features.get("doc_cin_number")
        )
        combined["document_address_verified"] = bool(
            extracted_features.get("doc_domicile_address")
        )
        combined["document_income_verified"] = monthly_salary is not None

        return combined

    def _build_consistency_checks(
        self,
        dossier: dict,
        applicant: dict[str, Any],
        employment: dict[str, Any],
        property_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        checks = [
            self._build_check(
                field="cin_number",
                document_value=applicant.get("cin_number"),
                input_value=dossier.get("cin"),
            ),
            self._build_check(
                field="address",
                document_value=applicant.get("address"),
                input_value=dossier.get("address"),
            ),
            self._build_check(
                field="employer_name",
                document_value=employment.get("employer_name"),
                input_value=dossier.get("employer_name", dossier.get("employerName")),
            ),
            self._build_check(
                field="property_sale_value",
                document_value=property_data.get("sale_value"),
                input_value=dossier.get("property_value"),
            ),
        ]
        return [check for check in checks if check]

    def _build_check(
        self,
        field: str,
        document_value: Any,
        input_value: Any,
    ) -> dict[str, Any] | None:
        if document_value in (None, "", []) and input_value in (None, "", []):
            return None
        if document_value in (None, "", []) or input_value in (None, "", []):
            status = "unknown"
        elif str(document_value).strip().lower() == str(input_value).strip().lower():
            status = "match"
        else:
            status = "mismatch"
        return {
            "field": field,
            "status": status,
            "document_value": document_value,
            "input_value": input_value,
            "note": None,
        }

    def _detect_languages_for_file(self, filename: str, content: bytes) -> list[str]:
        try:
            text = extract_document_text(content, filename)
        except Exception:
            return ["unknown"]
        return detect_document_languages(text)

    def _join_non_empty(self, *values: Any) -> str | None:
        parts = [str(value).strip() for value in values if value not in (None, "")]
        return " ".join(parts) if parts else None

    def _dedupe_preserve_order(self, values: list[Any]) -> list[Any]:
        seen: list[Any] = []
        for value in values:
            if value in (None, "", []):
                continue
            if value not in seen:
                seen.append(value)
        return seen

    def _to_optional_float(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _run_document_validation(
        self,
        dossier: dict,
        require_documents: bool,
    ) -> tuple[list[DocumentResult], dict[str, list[str]], list[str]]:
        results: list[DocumentResult] = []
        document_issues: dict[str, list[str]] = {}
        missing_documents: list[str] = []

        validators = {
            "cin_bytes": lambda value: validate_cin(value[1], value[0]),
            "fiches_paie_bytes": validate_fiches_paie,
            "domicile_bytes": lambda value: validate_justificatif_domicile(value[1], value[0]),
            "compromis_vente_bytes": lambda value: validate_compromis_vente(value[1], value[0]),
        }

        required_keys = self._required_documents_for(dossier)
        for key, label in required_keys:
            value = dossier.get(key)
            if not value:
                if require_documents:
                    missing_documents.append(label)
                continue

            result = validators[key](value)
            results.append(result)
            if result.issues:
                document_issues[result.document_type] = result.issues

        for key, _label in self.OPTIONAL_DOCUMENTS:
            if key in {required_key for required_key, _ in required_keys}:
                continue
            value = dossier.get(key)
            if not value:
                continue
            result = validators[key](value)
            results.append(result)
            if result.issues:
                document_issues[result.document_type] = result.issues

        return results, document_issues, missing_documents

    def _required_documents_for(self, dossier: dict) -> list[tuple[str, str]]:
        required_documents = list(self.BASE_REQUIRED_DOCUMENTS)
        required_documents.extend(
            self.CONDITIONAL_REQUIRED_DOCUMENTS.get(dossier["credit_type"], [])
        )
        return required_documents

    def _run_guarantee_selection(self, dossier: dict) -> GuaranteeOutput:
        return suggest_guarantee(
            GuaranteeInput(
                credit_type=dossier["credit_type"],
                loan_amount=dossier["loan_amount"],
                risk_class=dossier["risk_class"],
                debt_ratio=dossier["debt_ratio"],
                is_salary_domiciled=dossier.get("is_salary_domiciled", True),
            )
        )

    def _run_insurance_check(self, dossier: dict) -> InsuranceOutput:
        return check_insurance(
            InsuranceInput(
                credit_type=dossier["credit_type"],
                loan_amount=dossier["loan_amount"],
                client_age=dossier["client_age"],
                subscribed=dossier.get("insurance_subscribed", []),
            )
        )

    def _build_conditions(
        self,
        missing_documents: list[str],
        document_issues: dict[str, list[str]],
        insurance_result: InsuranceOutput,
    ) -> list[str]:
        conditions: list[str] = []

        for document_name in missing_documents:
            conditions.append(f"Fournir le document manquant: {document_name}")

        for doc_type, issues in document_issues.items():
            for issue in issues:
                conditions.append(f"Corriger {doc_type}: {issue}")

        for insurance_name in insurance_result.missing:
            conditions.append(f"Souscrire l'assurance obligatoire: {insurance_name}")

        return list(dict.fromkeys(conditions))

    def _compute_verdict(
        self,
        guarantee_result: GuaranteeOutput,
        insurance_result: InsuranceOutput,
        missing_documents: list[str],
        document_issues: dict[str, list[str]],
    ) -> Literal["OK", "CONDITIONNEL", "KO"]:
        if guarantee_result.risk_level == "REFUS":
            return "KO"

        if missing_documents or document_issues or insurance_result.is_blocking:
            return "CONDITIONNEL"

        return "OK"

    def _build_note(
        self,
        verdict: str,
        missing_documents: list[str],
        insurance_result: InsuranceOutput,
        guarantee_result: GuaranteeOutput,
    ) -> str:
        if verdict == "KO":
            return "Refus immediat selon le niveau de risque de la garantie."

        if verdict == "CONDITIONNEL":
            reasons: list[str] = []
            if missing_documents:
                reasons.append(f"documents a regulariser: {', '.join(missing_documents[:2])}")
            if insurance_result.missing:
                reasons.append(
                    f"assurances manquantes: {', '.join(insurance_result.missing[:2])}"
                )
            if not reasons:
                reasons.append("dossier a completer avant scoring")
            return "Dossier conditionnel, " + "; ".join(reasons) + "."

        return (
            "Dossier documentaire conforme, garantie "
            f"{guarantee_result.risk_level.lower()} et pret pour scoring."
        )

    def _build_document_status(
        self,
        dossier: dict,
        document_results: list[DocumentResult],
        missing_documents: list[str],
        document_issues: dict[str, list[str]],
    ) -> dict[str, dict[str, Any]]:
        results_by_type = {result.document_type: result for result in document_results}
        required_labels = {
            label for _, label in self._required_documents_for(dossier)
        }
        known_documents = [label for _, label in self._required_documents_for(dossier)]
        known_documents.extend(
            label for _, label in self.OPTIONAL_DOCUMENTS if label not in required_labels
        )

        status_by_document: dict[str, dict[str, Any]] = {}
        for document_name in known_documents:
            result = results_by_type.get(document_name)
            if document_name in missing_documents:
                status = "missing"
                issues = [f"{document_name} non fourni"]
                warnings = []
                extracted_info: dict[str, Any] = {}
            elif result is None:
                status = "not_provided"
                issues = []
                warnings = []
                extracted_info = {}
            elif result.is_valid:
                status = "valid"
                issues = []
                warnings = result.warnings
                extracted_info = result.extracted_info
            else:
                status = "invalid"
                issues = document_issues.get(document_name, result.issues)
                warnings = result.warnings
                extracted_info = result.extracted_info

            status_by_document[document_name] = {
                "required": document_name in required_labels,
                "status": status,
                "issues": issues,
                "warnings": warnings,
                "extracted_info": extracted_info,
            }

        return status_by_document

    def _build_frontend_payload(
        self,
        verdict: str,
        ready_for_scoring: bool,
        note_comite: str,
        missing_documents: list[str],
        document_issues: dict[str, list[str]],
        document_status: dict[str, dict[str, Any]],
        conditions_deblocage: list[str],
        blocking_reasons: list[str],
    ) -> dict[str, Any]:
        return {
            "target": "FRONTEND",
            "status": "READY_FOR_SCORING" if ready_for_scoring else "ACTION_REQUIRED",
            "verdict": verdict,
            "ready_for_scoring": ready_for_scoring,
            "note_comite": note_comite,
            "missing_documents": missing_documents,
            "invalid_documents": sorted(document_issues.keys()),
            "document_issues": document_issues,
            "document_status": document_status,
            "conditions_deblocage": conditions_deblocage,
            "blocking_reasons": blocking_reasons,
        }

    def _build_scoring_payload(
        self,
        dossier: dict,
        verdict: str,
        ready_for_scoring: bool,
        extracted_features: dict[str, Any],
        guarantee_result: GuaranteeOutput,
        insurance_result: InsuranceOutput,
        document_status: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "target": "SCORING_B",
            "ready_for_scoring": ready_for_scoring,
            "verdict": verdict,
            "client_id": dossier.get("client_id"),
            "credit_type": dossier["credit_type"],
            "loan_amount": dossier["loan_amount"],
            "document_features": extracted_features,
            "document_status": document_status,
            "guarantee": guarantee_result.model_dump(),
            "insurance": insurance_result.model_dump(),
        }

    def _build_extracted_features(
        self,
        dossier: dict,
        document_results: list[DocumentResult],
        guarantee_result: GuaranteeOutput,
        insurance_result: InsuranceOutput,
        missing_documents: list[str],
        document_issues: dict[str, list[str]],
        verdict: str,
    ) -> dict[str, Any]:
        extracted: dict[str, Any] = {
            "documents_complete": len(missing_documents) == 0 and len(document_issues) == 0,
            "documents_missing_count": len(missing_documents),
            "document_issue_count": sum(len(items) for items in document_issues.values()),
            "document_quality_score": self._compute_document_quality_score(
                document_results=document_results,
                missing_documents=missing_documents,
                document_issues=document_issues,
            ),
            "insurance_compliant": insurance_result.is_compliant,
            "guarantee_risk_level": guarantee_result.risk_level,
            "guarantee_requires_notarized_deed": guarantee_result.requires_notarized_deed,
            "guarantee_cpf_registration_required": guarantee_result.cpf_registration_required,
            "guarantee_estimated_registration_days": guarantee_result.estimated_registration_days,
            "guarantee_verdict": verdict,
            "credit_type": dossier["credit_type"],
            "loan_amount": dossier["loan_amount"],
            "client_age": dossier["client_age"],
            "debt_ratio": dossier["debt_ratio"],
        }

        for result in document_results:
            prefix = result.document_type.lower().replace(" ", "_")
            for key, value in result.extracted_info.items():
                extracted[f"{prefix}_{key}"] = value

        return extracted

    def _compute_document_quality_score(
        self,
        document_results: list[DocumentResult],
        missing_documents: list[str],
        document_issues: dict[str, list[str]],
    ) -> float:
        base_required = max(1, len(document_results) + len(missing_documents))
        valid_documents = sum(1 for result in document_results if result.is_valid)
        issue_penalty = sum(len(items) for items in document_issues.values()) * 0.05
        missing_penalty = len(missing_documents) * 0.2

        raw_score = (valid_documents / max(1, base_required)) - issue_penalty - missing_penalty
        return round(max(0.0, min(1.0, raw_score)), 3)

    def _normalize_dossier(self, dossier: dict) -> dict:
        normalized = dict(dossier)

        normalized["loan_amount"] = self._to_float(
            dossier.get("loan_amount", dossier.get("AMT_CREDIT", dossier.get("amount", 0.0)))
        )
        normalized["client_age"] = self._normalize_age(dossier)
        normalized["risk_class"] = self._normalize_risk_class(dossier)
        normalized["debt_ratio"] = self._normalize_debt_ratio(dossier)
        normalized["credit_type"] = self._normalize_credit_type(
            dossier.get("credit_type", "consommation")
        )
        normalized["is_salary_domiciled"] = bool(
            dossier.get("is_salary_domiciled", True)
        )
        insurance_subscribed = dossier.get("insurance_subscribed", [])
        if isinstance(insurance_subscribed, str):
            insurance_subscribed = [insurance_subscribed]
        normalized["insurance_subscribed"] = list(insurance_subscribed)

        normalized["cin_bytes"] = self._coerce_named_file(
            dossier.get("cin_bytes"),
            "cin.jpg",
        )
        normalized["domicile_bytes"] = self._coerce_named_file(
            dossier.get("domicile_bytes"),
            "domicile.pdf",
        )
        normalized["compromis_vente_bytes"] = self._coerce_named_file(
            dossier.get("compromis_vente_bytes")
            ,
            "compromis_vente.pdf",
        )
        normalized["fiches_paie_bytes"] = self._coerce_file_pairs(
            dossier.get("fiches_paie_bytes")
        )

        return normalized

    def _normalize_credit_type(self, value: Any) -> str:
        text = str(value or "consommation").strip().lower()
        aliases = {
            "conso": "consommation",
            "consommation": "consommation",
            "consumer": "consommation",
            "professional": "consommation",
            "auto": "auto",
            "automobile": "auto",
            "vehicule": "auto",
            "vehicle": "auto",
            "immobilier": "immobilier",
            "real_estate": "immobilier",
            "housing": "immobilier",
            "mortgage": "immobilier",
        }
        return aliases.get(text, "consommation")

    def _normalize_age(self, dossier: dict) -> int:
        age = dossier.get("client_age", dossier.get("age"))
        if age is None and dossier.get("DAYS_BIRTH") is not None:
            age = abs(self._to_float(dossier["DAYS_BIRTH"])) / 365
        age = self._to_float(age or 0)
        return int(round(age)) if age else 0

    def _normalize_risk_class(self, dossier: dict) -> int:
        if dossier.get("risk_class") is not None:
            try:
                return int(dossier["risk_class"])
            except (TypeError, ValueError):
                pass

        debt_ratio = self._normalize_debt_ratio(dossier)
        if debt_ratio >= 0.55:
            return 3
        if debt_ratio >= 0.35:
            return 2
        return 1

    def _normalize_debt_ratio(self, dossier: dict) -> float:
        if dossier.get("debt_ratio") is not None:
            ratio = self._to_float(dossier["debt_ratio"])
        elif dossier.get("DTI") is not None:
            ratio = self._to_float(dossier["DTI"])
        elif dossier.get("dti") is not None:
            ratio = self._to_float(dossier["dti"])
        else:
            monthly_payment = self._to_float(
                dossier.get("monthly_payment", dossier.get("AMT_ANNUITY", 0))
            )
            monthly_income = self._to_float(
                dossier.get("monthly_salary", dossier.get("income", 0))
            )
            ratio = monthly_payment / monthly_income if monthly_income > 0 else 0.0

        if ratio > 1:
            ratio = ratio / 100

        return round(max(0.0, min(1.0, ratio)), 4)

    def _coerce_file_pairs(self, value: Any) -> list[tuple[str, bytes]]:
        if not value:
            return []

        if isinstance(value, (bytes, bytearray, str, dict)):
            items = [value]
        elif isinstance(value, tuple) and len(value) == 2:
            items = [value]
        else:
            items = list(value)

        normalized: list[tuple[str, bytes]] = []
        for index, item in enumerate(items):
            if isinstance(item, tuple) and len(item) == 2:
                filename, content = item
                content_bytes = self._coerce_bytes(content)
                if content_bytes:
                    normalized.append((str(filename), content_bytes))
            elif isinstance(item, list) and len(item) == 2:
                filename, content = item
                content_bytes = self._coerce_bytes(content)
                if content_bytes:
                    normalized.append((str(filename), content_bytes))
            elif isinstance(item, dict):
                filename = item.get("filename") or item.get("name") or f"file_{index}.bin"
                content_bytes = self._coerce_bytes(
                    item.get("content") or item.get("content_base64") or item.get("bytes")
                )
                if content_bytes:
                    normalized.append((str(filename), content_bytes))
            else:
                content_bytes = self._coerce_bytes(item)
                if content_bytes:
                    normalized.append((f"file_{index}.bin", content_bytes))
        return normalized

    def _coerce_named_file(self, value: Any, default_filename: str) -> tuple[str, bytes] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            filename = value.get("filename") or value.get("name") or default_filename
            content_bytes = self._coerce_bytes(
                value.get("content") or value.get("content_base64") or value.get("bytes")
            )
            if content_bytes:
                return (str(filename), content_bytes)
            return None

        content_bytes = self._coerce_bytes(value)
        if content_bytes:
            return (default_filename, content_bytes)
        return None

    def _coerce_bytes(self, value: Any) -> bytes | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if "," in stripped and ";base64" in stripped:
                stripped = stripped.split(",", 1)[1]
            try:
                return base64.b64decode(stripped, validate=True)
            except Exception:
                return stripped.encode("utf-8")
        return None

    def _to_float(self, value: Any) -> float:
        try:
            if value is None or value == "":
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0
