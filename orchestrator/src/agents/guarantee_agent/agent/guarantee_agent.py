import base64
import json
import logging
import re
from typing import Any, Literal

from openai import AzureOpenAI, BadRequestError as OpenAIBadRequestError
from pydantic import BaseModel, Field

try:
    from src.langsmith_tracing import (
        annotate_current_run,
        process_trace_inputs,
        process_trace_outputs,
        traceable,
    )
    from src.agents.guarantee_agent.config import settings
    from src.agents.guarantee_agent.agent.prompts import (
        DOCUMENT_INTELLIGENCE_SYSTEM_PROMPT,
        SYSTEM_PROMPT,
        VISION_VALIDATION_SYSTEM_PROMPT,
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
    from langsmith_tracing import (
        annotate_current_run,
        process_trace_inputs,
        process_trace_outputs,
        traceable,
    )
    from config import settings
    from agent.prompts import (
        DOCUMENT_INTELLIGENCE_SYSTEM_PROMPT,
        SYSTEM_PROMPT,
        VISION_VALIDATION_SYSTEM_PROMPT,
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
        """
        Args:
            enable_llm: Initialise le client Azure OpenAI. Prérequis pour les deux
                fonctionnalités LLM ci-dessous.
            enable_document_intelligence: Utilise le LLM pour extraire des champs
                structurés depuis le texte des documents (nom, revenu, CIN, …).
                Nécessite ``enable_llm=True`` ou un ``llm_client`` pré-construit.
            enable_summary_llm: Utilise le LLM pour synthétiser le narratif final
                de la garantie à partir des résultats déterministes. Désactiver sur
                les chemins sensibles à la latence. Nécessite ``enable_llm=True``.
        """
        self.llm = llm_client
        self.deployment = deployment
        self.enable_document_intelligence = enable_document_intelligence
        self.enable_summary_llm = enable_summary_llm

        if enable_document_intelligence and not enable_llm and llm_client is None:
            logger.warning(
                "GuaranteeAgent: enable_document_intelligence=True sans LLM disponible "
                "— l'extraction documentaire LLM sera ignorée."
            )

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

    @traceable(
        name="Guarantee Agent",
        run_type="tool",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
    def run(self, dossier: dict, require_documents: bool = True) -> dict:
        normalized = self._normalize_dossier(dossier)
        client_id = normalized.get("client_id", "?")
        annotate_current_run(
            metadata={
                "operation": "guarantee",
                "client_id": client_id,
                "require_documents": require_documents,
            }
        )

        logger.info(
            "[GUARANTEE_A] ── START client=%s | llm=%s | doc_intel=%s | summary_llm=%s",
            client_id,
            "ON" if self.llm else "OFF",
            "ON" if self.enable_document_intelligence else "OFF",
            "ON" if self.enable_summary_llm else "OFF",
        )

        analysis = self.analyze(normalized, require_documents=require_documents)
        logger.info(
            "[GUARANTEE_A] Deterministic verdict=%s | ready=%s | blocking=%d",
            analysis.verdict,
            analysis.ready_for_scoring,
            len(analysis.blocking_reasons),
        )
        if analysis.blocking_reasons:
            logger.info("[GUARANTEE_A] Blocking reasons: %s", analysis.blocking_reasons)

        if self.enable_document_intelligence:
            logger.info("[GUARANTEE_A] Running document intelligence extraction…")
            try:
                analysis = self._enrich_with_document_intelligence(normalized, analysis)
                extracted = analysis.extracted_features
                logger.info(
                    "[GUARANTEE_A] Document intelligence OK | "
                    "quality_score=%.3f | identity_verified=%s | income_verified=%s",
                    extracted.get("document_quality_score", 0.0),
                    extracted.get("document_identity_verified", False),
                    extracted.get("document_income_verified", False),
                )
            except Exception as exc:
                logger.warning(
                    "[GUARANTEE_A] [FALLBACK] Document intelligence failed → "
                    "using heuristic extraction. Reason: %s",
                    exc,
                )

        if not self.enable_summary_llm:
            logger.warning(
                "[GUARANTEE_A] [FALLBACK] LLM synthesis DISABLED (enable_summary_llm=False)"
                " → returning deterministic result."
            )
            result = analysis.model_dump()
            result["_llm_used"] = False
            result["_llm_skip_reason"] = "enable_summary_llm=False"
            return result

        if not self.llm or not self.deployment:
            logger.warning(
                "[GUARANTEE_A] [FALLBACK] LLM not available (llm=%s, deployment=%s)"
                " → returning deterministic result.",
                self.llm,
                self.deployment,
            )
            result = analysis.model_dump()
            result["_llm_used"] = False
            result["_llm_skip_reason"] = "LLM client or deployment not configured"
            return result

        logger.info(
            "[GUARANTEE_A] Calling LLM synthesis | model=%s", self.deployment
        )
        try:
            result = self._synthesize_with_llm(normalized, analysis)
            result["_llm_used"] = True
            result["_llm_model"] = self.deployment
            logger.info(
                "[GUARANTEE_A] LLM synthesis SUCCESS | verdict=%s | note_comite=%r",
                result.get("verdict"),
                (result.get("note_comite") or "")[:80],
            )
            return result
        except Exception as exc:
            logger.error(
                "[GUARANTEE_A] [FALLBACK] LLM synthesis FAILED → deterministic result. "
                "Error: %s: %s",
                type(exc).__name__,
                exc,
            )
            result = analysis.model_dump()
            result["_llm_used"] = False
            result["_llm_skip_reason"] = f"{type(exc).__name__}: {exc}"
            return result

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

    @traceable(
        name="Guarantee LLM Synthesis",
        run_type="llm",
        process_inputs=process_trace_inputs,
        process_outputs=process_trace_outputs,
    )
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

        user_prompt = build_user_prompt(dossier, tools_outputs)
        logger.info(
            "[GUARANTEE_A][LLM] INPUT → system=%d chars | user=%d chars",
            len(SYSTEM_PROMPT),
            len(user_prompt),
        )
        logger.debug(
            "[GUARANTEE_A][LLM] USER PROMPT (first 800 chars):\n%s",
            user_prompt[:800],
        )

        response = self._create_chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_output_tokens=800,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        logger.info(
            "[GUARANTEE_A][LLM] OUTPUT → %d chars | tokens: prompt=%s completion=%s",
            len(raw or ""),
            getattr(usage, "prompt_tokens", "?"),
            getattr(usage, "completion_tokens", "?"),
        )
        logger.debug("[GUARANTEE_A][LLM] RAW OUTPUT:\n%s", raw)

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

    def _create_chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
        max_output_tokens: int,
        response_format: dict[str, Any] | None = None,
    ) -> Any:
        create_kwargs: dict[str, Any] = {
            "model": self.deployment,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            create_kwargs["response_format"] = response_format

        def _is_param_rejection(exc: Exception, param: str) -> bool:
            msg = str(exc).lower()
            return param.lower() in msg or "unsupported" in msg or "unrecognized" in msg or "unknown" in msg

        # Attempt 1: max_completion_tokens (o-series / gpt-5+ models)
        try:
            resp = self.llm.chat.completions.create(
                **create_kwargs,
                max_completion_tokens=max_output_tokens,
            )
            logger.debug("[GUARANTEE_A][LLM] API call OK via max_completion_tokens")
            return resp
        except (TypeError, OpenAIBadRequestError) as exc:
            if isinstance(exc, OpenAIBadRequestError) and not _is_param_rejection(exc, "max_completion_tokens"):
                raise
            logger.debug("[GUARANTEE_A][LLM] max_completion_tokens not accepted (%s) → trying max_tokens", exc)

        # Attempt 2: max_tokens (gpt-3.5 / gpt-4 / older Azure deployments)
        try:
            resp = self.llm.chat.completions.create(
                **create_kwargs,
                max_tokens=max_output_tokens,
            )
            logger.debug("[GUARANTEE_A][LLM] API call OK via max_tokens")
            return resp
        except (TypeError, OpenAIBadRequestError) as exc:
            if isinstance(exc, OpenAIBadRequestError) and not _is_param_rejection(exc, "max_tokens"):
                raise
            logger.debug("[GUARANTEE_A][LLM] max_tokens not accepted (%s) → calling without token limit", exc)

        # Attempt 3: no token limit — rely on model default
        logger.debug("[GUARANTEE_A][LLM] API call without explicit token limit")
        return self.llm.chat.completions.create(**create_kwargs)

    def _enrich_with_document_intelligence(
        self,
        dossier: dict,
        analysis: GuaranteeAnalysis,
    ) -> GuaranteeAnalysis:
        # Expects a pre-normalized dossier (caller's responsibility).
        heuristic_intelligence = self._build_heuristic_document_intelligence(
            dossier=dossier,
            analysis=analysis,
        )

        document_intelligence = heuristic_intelligence
        if (
            self.llm
            and self.deployment
            and self._should_extract_document_intelligence(analysis)
        ):
            llm_document_intelligence = self._extract_document_intelligence_with_llm(
                dossier=dossier,
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
            dossier=dossier,
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
        # Skip on hard KO (guarantee rules decided — document extraction won't help)
        # or when no documents were actually submitted (nothing to extract from).
        if analysis.verdict == "KO":
            return False
        return any(
            info.get("status") not in ("missing", "not_provided")
            for info in analysis.document_status.values()
        )

    def _build_heuristic_document_intelligence(
        self,
        dossier: dict,
        analysis: GuaranteeAnalysis,
    ) -> dict[str, Any]:
        feats = analysis.extracted_features

        # Pull structured fields already extracted by the validators
        cin_birth_date = feats.get("cin_birth_date")
        cin_gender = feats.get("cin_code_gender") or feats.get("cin_gender")
        cin_full_name = feats.get("cin_full_name")
        cin_last_name = feats.get("cin_last_name")
        cin_first_name = feats.get("cin_first_name")
        cin_expiry = feats.get("cin_expiry_date")

        payslip_net = feats.get("fiches_de_paie_monthly_net_salary")
        payslip_gross = feats.get("fiches_de_paie_monthly_gross_salary")
        payslip_employer = feats.get("fiches_de_paie_employer_name")
        payslip_employee = feats.get("fiches_de_paie_employee_name")
        payslip_emp_start = feats.get("fiches_de_paie_employment_start_date")
        payslip_months = feats.get("fiches_de_paie_months_found", [])

        applicant = {
            "full_name": cin_full_name or self._join_non_empty(
                cin_first_name or dossier.get("first_name", dossier.get("firstName")),
                cin_last_name or dossier.get("last_name", dossier.get("lastName")),
            ),
            "last_name": cin_last_name or dossier.get("last_name", dossier.get("lastName")),
            "first_name": cin_first_name or dossier.get("first_name", dossier.get("firstName")),
            "cin_number": feats.get("cin_cin_number") or dossier.get("cin"),
            "birth_date": cin_birth_date,
            "cin_expiry_date": cin_expiry,
            "gender": cin_gender,
            "address": dossier.get("address"),
            "governorate": dossier.get("governorate"),
        }
        employment = {
            "employer_name": payslip_employer or dossier.get("employer_name", dossier.get("employerName")),
            "employee_name": payslip_employee,
            "monthly_net_income": self._to_optional_float(payslip_net or dossier.get("monthly_salary")),
            "monthly_gross_income": self._to_optional_float(payslip_gross),
            "employment_start_date": payslip_emp_start,
            "salary_currency": "TND",
            "payslip_months": payslip_months or [],
            "cnss_number": feats.get("fiches_de_paie_cnss_number"),
        }

        # ── Pre-compute ML features from heuristic extraction ────────────────
        from datetime import date as _date, datetime as _dt
        today = _date.today()
        ml_features: dict[str, Any] = {
            "DAYS_BIRTH": None,
            "DAYS_EMPLOYED": None,
            "AMT_INCOME_TOTAL": None,
            "CODE_GENDER": cin_gender,
        }

        if cin_birth_date:
            try:
                bd = _dt.strptime(cin_birth_date, "%Y-%m-%d").date()
                ml_features["DAYS_BIRTH"] = -(today - bd).days
                logger.info(
                    "[GUARANTEE_A][HEURISTIC] birth_date=%s → DAYS_BIRTH=%d",
                    cin_birth_date, ml_features["DAYS_BIRTH"],
                )
            except (ValueError, TypeError):
                pass

        if payslip_emp_start:
            try:
                ed = _dt.strptime(payslip_emp_start, "%Y-%m-%d").date()
                ml_features["DAYS_EMPLOYED"] = -(today - ed).days
            except (ValueError, TypeError):
                pass

        net_income = self._to_optional_float(payslip_net or dossier.get("monthly_salary"))
        if net_income:
            ml_features["AMT_INCOME_TOTAL"] = round(net_income * 12, 2)
        property_data = {
            "sale_value": None,
            "currency": "TND" if dossier.get("credit_type") == "immobilier" else None,
            "address": None,
            "document_date": analysis.extracted_features.get(
                "compromis_de_vente_compromis_date"
            ),
        }

        languages: list[str] = []
        for cin_page in dossier.get("cin_bytes") or []:
            languages.extend(self._detect_languages_for_file(*cin_page))
        if dossier.get("domicile_bytes"):
            languages.extend(self._detect_languages_for_file(*dossier["domicile_bytes"]))
        for payslip in dossier.get("fiches_paie_bytes", []):
            languages.extend(self._detect_languages_for_file(*payslip))
        if dossier.get("compromis_vente_bytes"):
            languages.extend(
                self._detect_languages_for_file(*dossier["compromis_vente_bytes"])
            )

        languages = self._dedupe_preserve_order(languages) or ["unknown"]
        cin_has_verso = len(dossier.get("cin_bytes") or []) > 1
        missing_field_checks: dict[str, Any] = {
            "cin_number": applicant["cin_number"],
            "monthly_net_income": employment["monthly_net_income"],
        }
        # Only flag expiry date as missing if verso was provided but didn't yield a date.
        # Without verso, the absence is expected and already covered by a validator warning.
        if cin_has_verso:
            missing_field_checks["cin_expiry_date"] = applicant["cin_expiry_date"]
        # Flag birth_date extraction as missing if not found
        if not applicant.get("birth_date"):
            missing_field_checks["birth_date"] = None
        missing_fields = [
            field_name
            for field_name, value in missing_field_checks.items()
            if value in (None, "", [])
        ]

        consistency_checks = self._build_consistency_checks(
            dossier=dossier,
            applicant=applicant,
            employment=employment,
            property_data=property_data,
        )

        # Heuristic document verification flags
        document_verification: dict[str, Any] = {
            "cin_validity": (
                "valid" if applicant.get("cin_number") else "unreadable"
            ),
            "cin_authentic_signals": (
                ["numéro 8 chiffres présent"] if applicant.get("cin_number") else []
            ),
            "payslips_validity": (
                "valid" if employment.get("monthly_net_income") else "unknown"
            ),
            "payslips_salary_consistent": True,
            "domicile_validity": "unknown",
            "cross_document_coherent": True,
            "anomalies": [],
        }

        return {
            "applicant": applicant,
            "employment": employment,
            "property": property_data,
            "ml_features": ml_features,
            "document_verification": document_verification,
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
            logger.info(
                "[GUARANTEE_A][DOC_INTEL] No document bytes provided → "
                "heuristic extraction used (no LLM call)"
            )
            return heuristic_intelligence

        doc_keys = list(document_context.keys())
        logger.info(
            "[GUARANTEE_A][DOC_INTEL] LLM extraction for %d document(s): %s",
            len(doc_keys),
            doc_keys,
        )

        doc_prompt = build_document_intelligence_prompt(
            dossier=dossier,
            document_context=json.dumps(document_context, ensure_ascii=False, indent=2),
            heuristic_fields=json.dumps(heuristic_intelligence, ensure_ascii=False, indent=2),
        )
        logger.debug(
            "[GUARANTEE_A][DOC_INTEL] Prompt length: %d chars (first 600):\n%s",
            len(doc_prompt),
            doc_prompt[:600],
        )

        # Build vision parts (direct image reading — much more accurate than OCR text)
        vision_images = self._collect_vision_images(dossier)
        vision_parts = self._build_vision_parts(vision_images) if vision_images else []

        if vision_parts:
            logger.info(
                "[GUARANTEE_A][DOC_INTEL] Vision mode: sending %d image(s) directly to LLM",
                len(vision_images),
            )
            user_content: Any = [{"type": "text", "text": doc_prompt}] + vision_parts
        else:
            user_content = doc_prompt

        messages = [
            {"role": "system", "content": DOCUMENT_INTELLIGENCE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            response = self._create_chat_completion(
                messages=messages,
                temperature=0,
                max_output_tokens=1500,
                response_format={"type": "json_object"},
            )
        except OpenAIBadRequestError as exc:
            # Some Azure deployments reject response_format=json_object with vision input.
            logger.warning(
                "[GUARANTEE_A][DOC_INTEL] response_format rejected with vision (%s) → retrying without",
                exc,
            )
            response = self._create_chat_completion(
                messages=messages,
                temperature=0,
                max_output_tokens=1500,
            )

        raw = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        logger.info(
            "[GUARANTEE_A][DOC_INTEL] LLM extraction OK → %d chars | "
            "tokens: prompt=%s completion=%s",
            len(raw or ""),
            getattr(usage, "prompt_tokens", "?"),
            getattr(usage, "completion_tokens", "?"),
        )
        logger.debug("[GUARANTEE_A][DOC_INTEL] RAW OUTPUT:\n%s", raw)

        parsed = json.loads(raw)
        logger.info(
            "[GUARANTEE_A][DOC_INTEL] Extracted: name=%r | cin=%r | income=%r | confidence=%r",
            (parsed.get("applicant") or {}).get("full_name"),
            (parsed.get("applicant") or {}).get("cin_number"),
            (parsed.get("employment") or {}).get("monthly_net_income"),
            parsed.get("confidence"),
        )
        return {
            "applicant": parsed.get("applicant", {}) or {},
            "employment": parsed.get("employment", {}) or {},
            "property": parsed.get("property", {}) or {},
            "ml_features": parsed.get("ml_features", {}) or {},
            "document_verification": parsed.get("document_verification", {}) or {},
            "languages": parsed.get("languages", []) or [],
            "missing_fields": parsed.get("missing_fields", []) or [],
            "consistency_checks": parsed.get("consistency_checks", []) or [],
            "confidence": parsed.get("confidence", "low") or "low",
        }

    def _build_document_context(self, dossier: dict) -> dict[str, Any]:
        context: dict[str, Any] = {}

        cin_pages = dossier.get("cin_bytes") or []
        for i, (filename, content) in enumerate(cin_pages[:2]):
            label = "CIN recto" if i == 0 else "CIN verso"
            context[label] = self._document_context_item(filename, content)

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

    # ─────────────────────────────────────────────────────────────────────────
    # LLM Vision-only document validation (no Tesseract)
    # ─────────────────────────────────────────────────────────────────────────

    def validate_with_vision(self, data: dict) -> dict:
        """Validate a single document type using GPT-4o Vision — no Tesseract needed.

        Falls back to Tesseract-based validation when:
        - LLM is not configured
        - No image bytes are found (all PDFs and fitz is unavailable)
        """
        if not self.llm or not self.deployment:
            logger.warning("[GUARANTEE_A][VISION] LLM not configured → Tesseract fallback")
            from .mcp_server.validators import validate_documents
            return self._wrap_validate_docs_format(validate_documents(data))

        document_label = self._detect_document_label(data)
        vision_parts = self._build_all_vision_parts(data)

        if not vision_parts:
            logger.info("[GUARANTEE_A][VISION] No renderable images → Tesseract fallback")
            from .mcp_server.validators import validate_documents
            return self._wrap_validate_docs_format(validate_documents(data))

        logger.info(
            "[GUARANTEE_A][VISION] Validating '%s' with %d image part(s)",
            document_label, len([p for p in vision_parts if p.get("type") == "image_url"]),
        )

        prompt = (
            f"Valide le(s) document(s) soumis. Type attendu : {document_label}.\n"
            f"Date du jour : {__import__('datetime').date.today().isoformat()}"
        )
        messages = [
            {"role": "system", "content": VISION_VALIDATION_SYSTEM_PROMPT},
            {"role": "user", "content": [{"type": "text", "text": prompt}] + vision_parts},
        ]

        try:
            response = self._create_chat_completion(
                messages=messages,
                temperature=0,
                max_output_tokens=800,
                response_format={"type": "json_object"},
            )
        except OpenAIBadRequestError:
            response = self._create_chat_completion(
                messages=messages,
                temperature=0,
                max_output_tokens=800,
            )

        raw = response.choices[0].message.content or ""
        logger.info("[GUARANTEE_A][VISION] Response: %d chars", len(raw))

        try:
            llm_result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            llm_result = json.loads(m.group(0)) if m else {}

        return self._format_vision_result(llm_result, document_label)

    def _detect_document_label(self, data: dict) -> str:
        if data.get("cin_bytes"):
            return "CIN"
        if data.get("fiches_paie_bytes"):
            return "Fiches de paie"
        if data.get("domicile_bytes"):
            return "Justificatif domicile"
        if data.get("compromis_vente_bytes"):
            return "Compromis de vente"
        return "Document"

    def _build_all_vision_parts(self, data: dict) -> list[dict]:
        """Collect all document bytes as OpenAI vision content parts."""
        parts: list[dict] = []

        # CIN (recto + optional verso)
        cin_items = data.get("cin_bytes") or []
        if isinstance(cin_items, (dict, str, bytes)):
            cin_items = [cin_items]
        for i, item in enumerate(cin_items[:2]):
            fn, raw = self._coerce_item_to_bytes(item, f"cin_{i}.jpg")
            if raw:
                label = "CIN recto" if i == 0 else "CIN verso"
                img = self._ensure_image(raw, fn)
                if img:
                    parts += [{"type": "text", "text": f"[{label}]"}]
                    parts += [self._make_vision_image_part(img)]

        # Single-file documents
        for key, label in [
            ("domicile_bytes", "Justificatif domicile"),
            ("compromis_vente_bytes", "Compromis de vente"),
        ]:
            item = data.get(key)
            if not item:
                continue
            fn, raw = self._coerce_item_to_bytes(item, f"{key}.pdf")
            if raw:
                img = self._ensure_image(raw, fn)
                if img:
                    parts += [{"type": "text", "text": f"[{label}]"}]
                    parts += [self._make_vision_image_part(img)]

        # Payslips (up to 3)
        paie_items = data.get("fiches_paie_bytes") or []
        if isinstance(paie_items, (dict, str, bytes)):
            paie_items = [paie_items]
        for i, item in enumerate(paie_items[:3]):
            fn, raw = self._coerce_item_to_bytes(item, f"paie_{i}.pdf")
            if raw:
                img = self._ensure_image(raw, fn)
                if img:
                    parts += [{"type": "text", "text": f"[Fiche de paie {i + 1}]"}]
                    parts += [self._make_vision_image_part(img)]

        return parts

    def _coerce_item_to_bytes(self, item, default_fn: str) -> tuple[str, bytes | None]:
        if item is None:
            return default_fn, None
        if isinstance(item, dict):
            fn = item.get("filename") or item.get("name") or default_fn
            raw = item.get("content_base64") or item.get("content") or item.get("bytes")
        elif isinstance(item, (bytes, bytearray)):
            return default_fn, bytes(item)
        elif isinstance(item, str):
            try:
                return default_fn, base64.b64decode(item)
            except Exception:
                return default_fn, item.encode()
        else:
            return default_fn, None

        if isinstance(raw, str):
            try:
                return fn, base64.b64decode(raw)
            except Exception:
                return fn, raw.encode()
        if isinstance(raw, (bytes, bytearray)):
            return fn, bytes(raw)
        return fn, None

    def _ensure_image(self, content: bytes, filename: str) -> bytes | None:
        """Return image bytes — renders first PDF page to JPEG if needed."""
        if not self._is_pdf(content, filename):
            return content
        try:
            import io
            import fitz  # PyMuPDF
            from PIL import Image
            with fitz.open(stream=content, filetype="pdf") as pdf:
                pix = pdf[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                return buf.getvalue()
        except Exception as exc:
            logger.warning("[GUARANTEE_A][VISION] PDF→image failed: %s", exc)
            return None

    @staticmethod
    def _make_vision_image_part(content: bytes) -> dict:
        if content[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif content[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        else:
            mime = "image/jpeg"
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{base64.b64encode(content).decode()}", "detail": "high"},
        }

    @staticmethod
    def _format_vision_result(llm_result: dict, document_label: str) -> dict:
        """Transform LLM output → format expected by Java DocumentService."""
        status = llm_result.get("status", "invalid")
        issues = llm_result.get("issues") or []
        return {
            "document_status": {
                document_label: {
                    "status": status,
                    "is_valid": status == "valid",
                    "extracted_info": llm_result.get("extracted_info") or {},
                    "issues": issues,
                    "warnings": llm_result.get("warnings") or [],
                }
            },
            "document_issues": {document_label: issues},
            "ready_for_scoring": status == "valid",
            "_vision_used": True,
        }

    @staticmethod
    def _wrap_validate_docs_format(validate_result: dict) -> dict:
        """Convert /validate-documents format → /run-agent format."""
        document_status: dict = {}
        document_issues: dict = {}
        for r in validate_result.get("results", []):
            label = r.get("document_type", "Unknown")
            issues = r.get("issues") or []
            document_status[label] = {
                "status": "valid" if r.get("is_valid") else "invalid",
                "is_valid": r.get("is_valid", False),
                "extracted_info": r.get("extracted_info") or {},
                "issues": issues,
                "warnings": r.get("warnings") or [],
            }
            document_issues[label] = issues
        return {
            "document_status": document_status,
            "document_issues": document_issues,
            "ready_for_scoring": validate_result.get("documents_complete", False),
        }

    @staticmethod
    def _is_pdf(content: bytes, filename: str) -> bool:
        return content[:4] == b"%PDF" or (filename or "").lower().endswith(".pdf")

    def _collect_vision_images(self, dossier: dict) -> dict[str, tuple[str, bytes]]:
        """Returns {label: (filename, raw_bytes)} for image (non-PDF) documents."""
        images: dict[str, tuple[str, bytes]] = {}
        for i, (fn, content) in enumerate((dossier.get("cin_bytes") or [])[:2]):
            if not self._is_pdf(content, fn):
                images["CIN recto" if i == 0 else "CIN verso"] = (fn, content)
        for key, label in [("domicile_bytes", "Justificatif domicile"),
                            ("compromis_vente_bytes", "Compromis de vente")]:
            pair = dossier.get(key)
            if pair:
                fn, content = pair
                if not self._is_pdf(content, fn):
                    images[label] = (fn, content)
        return images

    def _build_vision_parts(self, images: dict[str, tuple[str, bytes]]) -> list[dict]:
        """Build OpenAI vision content parts from {label: (filename, bytes)}."""
        parts: list[dict] = []
        for label, (filename, content) in images.items():
            if content[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            elif content[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif content[:4] == b"RIFF":
                mime = "image/webp"
            else:
                mime = "image/jpeg"
            b64 = base64.b64encode(content).decode()
            parts.append({"type": "text", "text": f"[Document: {label} — {filename}]"})
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
            })
        return parts

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
                "last_name",
                "first_name",
                "cin_number",
                "birth_date",
                "cin_expiry_date",
                "gender",
                "address",
                "governorate",
            }
        }
        def _llm_or_heuristic_float(key: str) -> "float | None":
            llm_val = llm.get("employment", {}).get(key)
            return (
                self._to_optional_float(llm_val)
                if llm_val is not None
                else heuristic.get("employment", {}).get(key)
            )

        merged_employment = {
            "employer_name": llm.get("employment", {}).get("employer_name")
            or heuristic.get("employment", {}).get("employer_name"),
            "employee_name": llm.get("employment", {}).get("employee_name")
            or heuristic.get("employment", {}).get("employee_name"),
            "monthly_net_income": _llm_or_heuristic_float("monthly_net_income"),
            "monthly_gross_income": _llm_or_heuristic_float("monthly_gross_income"),
            "employment_start_date": llm.get("employment", {}).get("employment_start_date")
            or heuristic.get("employment", {}).get("employment_start_date"),
            "salary_currency": llm.get("employment", {}).get("salary_currency")
            or heuristic.get("employment", {}).get("salary_currency"),
            "payslip_months": self._dedupe_preserve_order(
                (llm.get("employment", {}).get("payslip_months") or [])
                + (heuristic.get("employment", {}).get("payslip_months") or [])
            ),
            "cnss_number": llm.get("employment", {}).get("cnss_number")
            or heuristic.get("employment", {}).get("cnss_number"),
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

        # Merge ml_features: LLM wins for non-null values, heuristic fills the rest
        heuristic_ml = heuristic.get("ml_features") or {}
        llm_ml = llm.get("ml_features") or {}
        merged_ml: dict[str, Any] = {}
        for key in ("DAYS_BIRTH", "DAYS_EMPLOYED", "AMT_INCOME_TOTAL", "CODE_GENDER"):
            merged_ml[key] = llm_ml.get(key) if llm_ml.get(key) is not None else heuristic_ml.get(key)

        # Merge document_verification: LLM is more complete
        merged_verification = heuristic.get("document_verification") or {}
        llm_verification = llm.get("document_verification") or {}
        if llm_verification:
            merged_verification = {**merged_verification, **llm_verification}

        return {
            "applicant": merged_applicant,
            "employment": merged_employment,
            "property": merged_property,
            "ml_features": merged_ml,
            "document_verification": merged_verification,
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
        from datetime import date as _date

        applicant = document_intelligence.get("applicant", {}) or {}
        employment = document_intelligence.get("employment", {}) or {}
        property_data = document_intelligence.get("property", {}) or {}
        ml_features = document_intelligence.get("ml_features", {}) or {}
        verification = document_intelligence.get("document_verification", {}) or {}
        consistency_checks = document_intelligence.get("consistency_checks", []) or []

        mismatch_count = sum(
            1 for check in consistency_checks if check.get("status") == "mismatch"
        )
        total_checks = len(consistency_checks)
        consistency_score = (
            round(max(0.0, 1 - (mismatch_count / total_checks)), 3)
            if total_checks
            else 1.0
        )

        today = _date.today()

        # ── Standard doc fields ────────────────────────────────────────────
        flat: dict[str, Any] = {
            "doc_borrower_full_name": applicant.get("full_name"),
            "doc_borrower_last_name": applicant.get("last_name"),
            "doc_borrower_first_name": applicant.get("first_name"),
            "doc_cin_number": applicant.get("cin_number"),
            "doc_cin_expiry_date": applicant.get("cin_expiry_date"),
            "doc_birth_date": applicant.get("birth_date"),
            "doc_gender": applicant.get("gender"),
            "doc_domicile_address": applicant.get("address"),
            "doc_domicile_governorate": applicant.get("governorate"),
            "doc_employer_name": employment.get("employer_name"),
            "doc_employee_name": employment.get("employee_name"),
            "doc_monthly_net_income": employment.get("monthly_net_income"),
            "doc_monthly_gross_income": employment.get("monthly_gross_income"),
            "doc_employment_start_date": employment.get("employment_start_date"),
            "doc_salary_currency": employment.get("salary_currency"),
            "doc_payslip_months": employment.get("payslip_months", []),
            "doc_cnss_number": employment.get("cnss_number"),
            "doc_property_sale_value": property_data.get("sale_value"),
            "doc_property_currency": property_data.get("currency"),
            "doc_property_address": property_data.get("address"),
            "doc_property_document_date": property_data.get("document_date"),
            "doc_detected_languages": document_intelligence.get("languages", []),
            "doc_extraction_confidence": document_intelligence.get("confidence", "low"),
            "doc_extraction_missing_fields": document_intelligence.get("missing_fields", []),
            "doc_consistency_checks": consistency_checks,
            "doc_consistency_score": consistency_score,
            # Document verification flags
            "doc_cin_validity": verification.get("cin_validity"),
            "doc_payslips_validity": verification.get("payslips_validity"),
            "doc_cross_coherent": verification.get("cross_document_coherent", True),
            "doc_anomalies": verification.get("anomalies", []),
        }

        # ── ML feature mapping from LLM extraction ────────────────────────
        # Priority: LLM ml_features > computed from extracted fields > None

        # DAYS_BIRTH
        days_birth = ml_features.get("DAYS_BIRTH")
        if days_birth is None and applicant.get("birth_date"):
            try:
                from datetime import datetime as _dt
                bd = _dt.strptime(applicant["birth_date"], "%Y-%m-%d").date()
                days_birth = -(today - bd).days
            except (ValueError, TypeError):
                pass
        flat["DAYS_BIRTH"] = days_birth

        # age_years derived from DAYS_BIRTH
        if days_birth is not None:
            flat["doc_age_years"] = round(abs(days_birth) / 365.25, 1)

        # DAYS_EMPLOYED
        days_employed = ml_features.get("DAYS_EMPLOYED")
        if days_employed is None and employment.get("employment_start_date"):
            try:
                from datetime import datetime as _dt
                ed = _dt.strptime(employment["employment_start_date"], "%Y-%m-%d").date()
                days_employed = -(today - ed).days
            except (ValueError, TypeError):
                pass
        flat["DAYS_EMPLOYED"] = days_employed

        # AMT_INCOME_TOTAL (annual income)
        amt_income = ml_features.get("AMT_INCOME_TOTAL")
        if amt_income is None:
            net_monthly = employment.get("monthly_net_income")
            if net_monthly:
                try:
                    amt_income = round(float(net_monthly) * 12, 2)
                except (TypeError, ValueError):
                    pass
        flat["AMT_INCOME_TOTAL"] = amt_income

        # CODE_GENDER
        code_gender = ml_features.get("CODE_GENDER") or applicant.get("gender")
        flat["CODE_GENDER"] = code_gender

        # Log what was extracted for the ML model
        ml_summary = {
            k: flat[k] for k in ("DAYS_BIRTH", "DAYS_EMPLOYED", "AMT_INCOME_TOTAL", "CODE_GENDER")
        }
        logger.info(
            "[GUARANTEE_A][DOC_INTEL] ML features extracted: %s",
            {k: v for k, v in ml_summary.items() if v is not None},
        )
        missing_ml = [k for k, v in ml_summary.items() if v is None]
        if missing_ml:
            logger.warning(
                "[GUARANTEE_A][DOC_INTEL] ML features NOT extracted (will use form data fallback): %s",
                missing_ml,
            )

        return flat

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

        # ── Monthly salary: document value takes priority over form declaration ──
        monthly_salary = self._to_optional_float(
            extracted_features.get("doc_monthly_net_income")
            or combined.get("monthly_salary")
            or combined.get("monthly_income")
        )
        if monthly_salary is not None:
            combined["monthly_salary"] = monthly_salary
            combined["monthly_income"] = monthly_salary

        # ── Annual income (AMT_INCOME_TOTAL) ─────────────────────────────────
        # Priority: extracted ML feature > form value > computed from monthly
        annual_income = self._to_optional_float(
            extracted_features.get("AMT_INCOME_TOTAL")
            or combined.get("AMT_INCOME_TOTAL")
            or combined.get("income")
        )
        if annual_income is None and monthly_salary is not None:
            annual_income = round(monthly_salary * 12, 2)
        if annual_income is not None:
            combined["AMT_INCOME_TOTAL"] = annual_income
            combined["income"] = annual_income

        # ── DAYS_BIRTH: document value overrides form value ───────────────────
        days_birth = extracted_features.get("DAYS_BIRTH")
        if days_birth is not None:
            combined["DAYS_BIRTH"] = int(days_birth)
            # Recompute client_age from document birth date (more reliable)
            combined["client_age"] = round(abs(int(days_birth)) / 365.25)
            combined["age"] = combined["client_age"]
            logger.info(
                "[GUARANTEE_A] DAYS_BIRTH from document: %d → age=%d years",
                int(days_birth),
                combined["client_age"],
            )

        # ── DAYS_EMPLOYED ─────────────────────────────────────────────────────
        days_employed = extracted_features.get("DAYS_EMPLOYED")
        if days_employed is not None:
            combined["DAYS_EMPLOYED"] = int(days_employed)
            combined["employment_years"] = round(abs(int(days_employed)) / 365.25, 1)
            logger.info(
                "[GUARANTEE_A] DAYS_EMPLOYED from document: %d → %.1f years",
                int(days_employed),
                combined["employment_years"],
            )

        # ── CODE_GENDER ────────────────────────────────────────────────────────
        code_gender = extracted_features.get("CODE_GENDER")
        if code_gender:
            combined["CODE_GENDER"] = code_gender

        # ── Property and employer ─────────────────────────────────────────────
        if extracted_features.get("doc_property_sale_value") is not None:
            combined.setdefault(
                "estimated_property_value",
                extracted_features.get("doc_property_sale_value"),
            )
        if extracted_features.get("doc_employer_name"):
            combined.setdefault("employer_name", extracted_features["doc_employer_name"])

        # ── Document verification flags ────────────────────────────────────────
        combined["document_identity_verified"] = bool(extracted_features.get("doc_cin_number"))
        combined["document_address_verified"] = bool(extracted_features.get("doc_domicile_address"))
        combined["document_income_verified"] = monthly_salary is not None
        combined["document_age_verified"] = extracted_features.get("DAYS_BIRTH") is not None
        combined["document_anomalies"] = extracted_features.get("doc_anomalies", [])

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
            # validate_cin accepts list[tuple[str, bytes]]: files[0]=recto, files[1]=verso (opt.)
            "cin_bytes": validate_cin,
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

        # Champs identité — Java peut envoyer camelCase ou snake_case
        normalized["first_name"] = (
            dossier.get("first_name") or dossier.get("firstName") or dossier.get("prenom")
        )
        normalized["last_name"] = (
            dossier.get("last_name") or dossier.get("lastName") or dossier.get("nom")
        )
        normalized["cin"] = (
            dossier.get("cin") or dossier.get("cinNumber") or dossier.get("cin_number")
        )
        normalized["address"] = dossier.get("address") or dossier.get("adresse")
        normalized["governorate"] = dossier.get("governorate") or dossier.get("gouvernorat")
        normalized["employer_name"] = (
            dossier.get("employer_name") or dossier.get("employerName") or dossier.get("employeur")
        )
        normalized["monthly_salary"] = self._to_float(
            dossier.get("monthly_salary") or dossier.get("monthlySalary")
            or dossier.get("income") or dossier.get("monthly_income") or 0.0
        ) or None

        # CIN accepte [recto] ou [recto, verso] — même convention que fiches_paie_bytes.
        # Un seul fichier (recto) suffit ; le verso permet de vérifier la date d'expiration.
        normalized["cin_bytes"] = self._coerce_file_pairs(dossier.get("cin_bytes"))
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
                logger.warning(
                    "GuaranteeAgent: valeur risk_class invalide %r — classe inférée depuis debt_ratio",
                    dossier["risk_class"],
                )

        debt_ratio = self._normalize_debt_ratio(dossier)
        inferred = 3 if debt_ratio >= 0.55 else (2 if debt_ratio >= 0.35 else 1)
        logger.debug(
            "GuaranteeAgent: risk_class absent — classe %d inférée (debt_ratio=%.4f)",
            inferred,
            debt_ratio,
        )
        return inferred

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
        # Passthrough for already-normalized (filename, bytes) tuples so that
        # calling _normalize_dossier() twice remains idempotent.
        if isinstance(value, tuple) and len(value) == 2:
            filename, content = value
            if isinstance(content, bytes):
                return (str(filename), content)
            if isinstance(content, bytearray):
                return (str(filename), bytes(content))
            # content is not bytes — fall through to generic coercion below
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
                logger.warning(
                    "GuaranteeAgent: décodage base64 échoué (len=%d) — donnée ignorée",
                    len(stripped),
                )
                return None
        return None

    def _to_float(self, value: Any) -> float:
        try:
            if value is None or value == "":
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0
