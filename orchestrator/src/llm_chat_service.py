"""
LLM-based Chat Service for AICredits Assistant
Uses Azure OpenAI to generate intelligent, context-aware responses for credit applications
"""

import logging
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel

from config.settings import get_config
from .llm_client import AzureOpenAIClient

logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    """Message in conversation"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    """Request for LLM-based chat"""
    message: str
    conversation: Optional[List[ChatMessage]] = None
    userId: Optional[str] = None
    userRole: Optional[str] = None  # ROLE_CLIENT, ROLE_CONSEILLER, ROLE_ADMIN
    loanId: Optional[str] = None
    loanContext: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """Response from LLM-based chat"""
    message: str
    insights: Optional[List[Dict[str, str]]] = None
    suggestedPrompts: Optional[List[Dict[str, str]]] = None
    status: str = "connected"


class LLMChatService:
    """Service for intelligent credit guidance using LLM"""

    def __init__(self, llm_client: Optional[AzureOpenAIClient] = None):
        """Initialize chat service with LLM client"""
        self.config = get_config()
        self.llm_client = llm_client or AzureOpenAIClient(self.config.azure_openai)
        logger.info("✓ LLM Chat Service initialized")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        Process chat message with LLM-generated response
        """
        try:
            # Detect language
            is_arabic = self._is_arabic(request.message)
            language = "Arabic" if is_arabic else "French"

            # Build context from loan data
            loan_context = request.loanContext or {}
            context_summary = self._build_context_summary(loan_context, language)

            # Build conversation history for context
            conversation_history = self._build_conversation_history(request.conversation)

            # Determine if user is a client or advisor
            role = request.userRole or "ROLE_CLIENT"
            is_client = "CLIENT" in role.upper()

            # Generate response using LLM
            response_text = await self._generate_llm_response(
                user_message=request.message,
                context_summary=context_summary,
                conversation_history=conversation_history,
                is_client=is_client,
                language=language,
            )

            # Extract insights
            insights = self._extract_insights(loan_context, response_text, language)

            # Generate suggested prompts
            suggested_prompts = self._generate_suggested_prompts(request.message, loan_context, language)

            return ChatResponse(
                message=response_text,
                insights=insights,
                suggestedPrompts=suggested_prompts,
                status="connected"
            )

        except Exception as e:
            logger.error(f"LLM Chat error: {e}", exc_info=True)
            return self._error_response(request.userRole)

    def _is_arabic(self, text: str) -> bool:
        """Detect if text contains Arabic characters"""
        for char in text:
            if '\u0600' <= char <= '\u06FF':  # Arabic Unicode range
                return True
        return False

    def _build_context_summary(self, loan: Dict[str, Any], language: str) -> str:
        """Build a concise summary of loan context for LLM"""
        if not loan:
            if language == "Arabic":
                return "لا توجد معلومات عن القرض متاحة حالياً"
            else:
                return "No loan context available"

        purpose = loan.get("purpose", "Not specified")
        amount = loan.get("amount", 0)
        duration = loan.get("duration", 0)
        status = loan.get("status", "PENDING")
        dti = loan.get("dti")
        pd_score = loan.get("pdScore")
        risk_band = loan.get("riskBand")

        if language == "Arabic":
            summary = f"""
ملخص طلب القرض:
- الغرض: {purpose}
- المبلغ: {amount:,.0f} TND
- المدة: {duration} شهر
- الحالة: {status}
"""
        else:
            summary = f"""
Loan Application Summary:
- Purpose: {purpose}
- Amount: {amount:,.0f} TND
- Duration: {duration} months
- Status: {status}
"""

        if dti:
            if language == "Arabic":
                summary += f"- نسبة الدين إلى الدخل: {dti:.2%}\n"
            else:
                summary += f"- Debt-to-Income Ratio: {dti:.2%}\n"

        if pd_score:
            if language == "Arabic":
                summary += f"- درجة احتمال التخلف: {pd_score:.2%}\n"
                if risk_band:
                    summary += f"- فئة المخاطر: {risk_band}\n"
            else:
                summary += f"- Probability of Default: {pd_score:.2%}\n"
                if risk_band:
                    summary += f"- Risk Band: {risk_band}\n"

        decision_summary = loan.get("decisionSummary")
        if decision_summary:
            if language == "Arabic":
                summary += f"\nملخص القرار: {decision_summary}"
            else:
                summary += f"\nDecision Summary: {decision_summary}"

        return summary

    def _build_conversation_history(self, messages: Optional[List[ChatMessage]]) -> str:
        """Build conversation history for LLM context"""
        if not messages or len(messages) == 0:
            return ""

        history = "Recent conversation:\n"
        for msg in messages[-5:]:  # Last 5 messages for context
            role_label = "Client" if msg.role == "user" else "Assistant"
            history += f"{role_label}: {msg.content}\n"

        return history

    async def _generate_llm_response(
        self,
        user_message: str,
        context_summary: str,
        conversation_history: str,
        is_client: bool,
        language: str,
    ) -> str:
        """Generate response using Azure OpenAI LLM"""

        if language == "Arabic":
            system_prompt = self._get_arabic_system_prompt(is_client)
        else:
            system_prompt = self._get_french_system_prompt(is_client)

        full_context = f"""
{system_prompt}

{context_summary}

{conversation_history}

User message: {user_message}

Generate a helpful, professional response:
"""

        try:
            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{context_summary}\n\n{user_message}"}
                ],
                max_completion_tokens=1000,
                temperature=0.7,
            )
            return response.content.strip()
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return self._fallback_response(language)

    def _get_french_system_prompt(self, is_client: bool) -> str:
        """Get French system prompt for LLM"""
        if is_client:
            return """Tu es un assistant de crédit professionnel et bienveillant pour AICredits.
Tu aides les clients à comprendre l'état de leur demande de crédit, ce qu'ils doivent préparer, et comment améliorer leur profil.
Sois empathique, clair et pratique. Donne des conseils concrets et rassurants.
Réponds toujours en français, sauf si le client demande l'arabe.
Limite tes réponses à 2-3 paragraphes maximum."""
        else:
            return """Tu es un assistant technique professionnel pour les conseillers AICredits.
Fournis des analyses détaillées, des insights sur les risques, et des recommandations d'action.
Sois précis, factuel et appuie-toi sur les données disponibles.
Réponds en français ou en anglais selon le contexte."""

    def _get_arabic_system_prompt(self, is_client: bool) -> str:
        """Get Arabic system prompt for LLM"""
        if is_client:
            return """أنت مساعد قروض احترافي وودود لشركة AICredits.
تساعد العملاء على فهم حالة طلب القرض الخاص بهم وما يجب عليهم تحضيره وكيفية تحسين ملفهم.
كن متعاطفاً وواضحاً عملياً. أعط نصائح ملموسة ومطمئنة.
أجب دائماً باللغة العربية.
اقتصر ردودك على 2-3 فقرات كحد أقصى."""
        else:
            return """أنت مساعد تقني احترافي لمستشاري AICredits.
قدم تحليلات تفصيلية ورؤى حول المخاطر والتوصيات الإجرائية.
كن دقيقاً وواقعياً واعتمد على البيانات المتاحة.
أجب باللغة العربية."""

    def _extract_insights(
        self, loan: Dict[str, Any], response: str, language: str
    ) -> List[Dict[str, str]]:
        """Extract key insights from loan data"""
        insights = []

        status = loan.get("status", "PENDING")
        if status == "APPROVED":
            insights.append({
                "label": "Décision" if language == "French" else "القرار",
                "value": "Approuvée" if language == "French" else "موافق عليه",
                "tone": "positive"
            })
        elif status == "REJECTED":
            insights.append({
                "label": "Décision" if language == "French" else "القرار",
                "value": "Refusée" if language == "French" else "مرفوضة",
                "tone": "warning"
            })
        elif status == "REVIEW_REQUIRED":
            insights.append({
                "label": "Statut" if language == "French" else "الحالة",
                "value": "En révision" if language == "French" else "قيد المراجعة",
                "tone": "warning"
            })

        dti = loan.get("dti")
        if dti:
            tone = "positive" if dti < 0.40 else "warning"
            label = "DTI" if language == "French" else "نسبة الدين"
            insights.append({
                "label": label,
                "value": f"{dti:.1%}",
                "tone": tone
            })

        pd_score = loan.get("pdScore")
        if pd_score:
            if pd_score < 0.35:
                tone = "positive"
                risk_label = "Faible" if language == "French" else "منخفض"
            elif pd_score < 0.65:
                tone = "neutral"
                risk_label = "Modéré" if language == "French" else "متوسط"
            else:
                tone = "warning"
                risk_label = "Élevé" if language == "French" else "مرتفع"

            insights.append({
                "label": "Risque" if language == "French" else "الخطر",
                "value": risk_label,
                "tone": tone
            })

        return insights

    def _generate_suggested_prompts(
        self, user_message: str, loan: Dict[str, Any], language: str
    ) -> List[Dict[str, str]]:
        """Generate suggested follow-up prompts"""
        prompts = []

        if language == "French":
            prompts.append({"label": "Quels documents?", "prompt": "Quels documents dois-je préparer?"})
            prompts.append({"label": "Étapes suivantes", "prompt": "Quelles sont les prochaines étapes?"})
            if loan.get("status") != "APPROVED":
                prompts.append({"label": "Comment améliorer?", "prompt": "Comment puis-je améliorer mon profil?"})
        else:
            prompts.append({"label": "الوثائق", "prompt": "ما هي الوثائق التي يجب أن أحضرها؟"})
            prompts.append({"label": "الخطوات التالية", "prompt": "ما هي الخطوات التالية؟"})
            if loan.get("status") != "APPROVED":
                prompts.append({"label": "التحسين", "prompt": "كيف يمكنني تحسين ملفي؟"})

        return prompts

    def _error_response(self, user_role: Optional[str]) -> ChatResponse:
        """Generate error response"""
        is_french = "CLIENT" in (user_role or "ROLE_CLIENT").upper()
        message = (
            "Désolé, une erreur s'est produite. Veuillez réessayer."
            if is_french
            else "عذراً، حدث خطأ. يرجى المحاولة مرة أخرى."
        )
        return ChatResponse(
            message=message,
            status="error"
        )

    def _fallback_response(self, language: str) -> str:
        """Generate fallback response when LLM fails"""
        if language == "Arabic":
            return """عذراً، حدث تأخير مؤقت في معالجة طلبك. يرجى المحاولة مرة أخرى.
إذا استمرت المشكلة، يرجى الاتصال بفريق الدعم."""
        else:
            return """Désolé, un délai s'est produit dans le traitement de votre demande. Veuillez réessayer.
Si le problème persiste, veuillez contacter notre équipe d'assistance."""


# Singleton instance
_chat_service: Optional[LLMChatService] = None


def get_llm_chat_service() -> LLMChatService:
    """Get singleton instance of LLM chat service"""
    global _chat_service
    if _chat_service is None:
        _chat_service = LLMChatService()
    return _chat_service
