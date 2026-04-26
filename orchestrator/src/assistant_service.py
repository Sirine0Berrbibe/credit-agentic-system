"""
Assistant Service - Conversational guidance for credit applications
Integrates with the orchestrator for intelligent loan-aware responses
"""

import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime

logger = logging.getLogger(__name__)


class AssistantMessage(BaseModel):
    """Message in assistant conversation"""
    id: str
    role: str  # "user" or "assistant"
    content: str
    createdAt: str


class Insight(BaseModel):
    """Insight displayed with assistant message"""
    label: str
    value: str
    tone: str  # "positive", "neutral", "warning"


class SuggestedPrompt(BaseModel):
    """Suggested follow-up prompt"""
    label: str
    prompt: str


class AssistantChatRequest(BaseModel):
    """Request for assistant chat"""
    message: str
    conversation: List[AssistantMessage]
    userId: Optional[str] = None
    userRole: Optional[str] = None
    loanId: Optional[str] = None
    loanContext: Optional[Dict[str, Any]] = None


class AssistantChatResponse(BaseModel):
    """Response from assistant chat"""
    message: str
    insights: Optional[List[Insight]] = None
    suggestedPrompts: Optional[List[SuggestedPrompt]] = None
    status: str = "connected"


class AssistantService:
    """Service for intelligent credit guidance"""

    def __init__(self):
        """Initialize assistant service"""
        logger.info("✓ Assistant service initialized")

    async def chat(self, request: AssistantChatRequest) -> AssistantChatResponse:
        """
        Process assistant chat message with intelligent responses
        """
        try:
            loan = request.loanContext or {}
            message_lower = request.message.lower()

            # Generate intelligent response based on loan context and message
            response_text = self._generate_response(message_lower, loan, request.conversation)

            # Extract insights from loan data
            insights = self._extract_insights(loan, response_text)

            # Generate suggested follow-up prompts
            suggested_prompts = self._generate_suggested_prompts(message_lower, loan)

            return AssistantChatResponse(
                message=response_text,
                insights=insights,
                suggestedPrompts=suggested_prompts,
                status="connected"
            )

        except Exception as e:
            logger.error(f"Assistant error: {e}")
            return self._error_response()

    def _generate_response(
        self,
        message: str,
        loan: Dict[str, Any],
        conversation: List[AssistantMessage]
    ) -> str:
        """Generate contextual response based on message and loan data"""

        loan_status = loan.get('status', 'PENDING')
        loan_amount = loan.get('amount', 0)
        loan_purpose = loan.get('purpose', 'Credit')
        loan_income = loan.get('income', 0)
        pd_score = loan.get('pdScore')
        risk_band = loan.get('riskBand')

        # Score improvement
        if any(word in message for word in ['score', 'améliorer', 'improve', 'boost']):
            response = (
                f"Pour votre demande de **{loan_purpose}** ({loan_amount}€), voici comment améliorer votre dossier:\n\n"
                "**Points clés:**\n"
                "1. **Stabiliser vos paiements** - Assurez-vous que tous les paiements sont à jour\n"
                "2. **Réduire vos dettes** - Diminuez votre ratio d'endettement si possible\n"
                "3. **Documents complets** - Préparez tous les justificatifs (3 derniers bulletins de salaire, relevés bancaires)\n"
                "4. **Stabilité professionnelle** - Démontrez une continuité d'emploi\n\n"
            )
            if pd_score:
                if pd_score < 0.35:
                    response += f"✓ Votre score PD actuel ({pd_score:.2f}) est **excellent** (Risque **BAS**)\n"
                elif pd_score < 0.5:
                    response += f"→ Votre score PD ({pd_score:.2f}) peut encore être amélioré (Risque **MODÉRÉ**)\n"
                else:
                    response += f"⚠ Votre score PD ({pd_score:.2f}) nécessite une attention (Risque **ÉLEVÉ**)\n"
                response += "Ces actions pourraient réduire significativement votre probabilité de défaut.\n"
            return response

        # Document requirements
        elif any(word in message for word in ['document', 'pièce', 'fichier', 'justificatif', 'preuve']):
            response = (
                f"Pour votre demande de **{loan_purpose}**, préparez ces documents:\n\n"
                "**Documents requis:**\n"
                "• **Identité** - Carte d'identité nationale ou passeport\n"
                "• **Revenus** - 3 derniers bulletins de salaire ou déclaration fiscale\n"
                "• **Emploi** - Lettre d'employeur confirmant votre poste\n"
                "• **Banque** - 3-6 derniers relevés bancaires\n"
                "• **Raison du prêt** - Documentation spécifique au projet (ex: devis pour rénovation)\n\n"
            )
            if loan_income:
                ratio = (loan_amount * 12) / loan_income if loan_income > 0 else 0
                response += f"Avec un revenu mensuel de {loan_income}€, votre ratio d'endettement sera {ratio:.1f}x vos revenus annuels.\n"
                if ratio < 3:
                    response += "✓ Ce ratio est acceptable pour les prêteurs.\n"
                elif ratio < 5:
                    response += "→ Ce ratio est dans la normale mais nécessite une documentation solide.\n"
                else:
                    response += "⚠ Ce ratio est élevé - une documentation complète est essentielle.\n"
            return response

        # Application status
        elif any(word in message for word in ['statut', 'status', 'décision', 'décision', 'progrès', 'progression']):
            response = f"**Statut de votre demande: {loan_status}**\n\n"

            if loan_status == 'APPROVED':
                response += (
                    "✓ Votre demande a été **approuvée**!\n\n"
                    "Prochaines étapes:\n"
                    "1. Vérifiez les conditions d'accord (taux, durée, montant)\n"
                    "2. Signez les documents de crédit\n"
                    "3. Attendez le déblocage des fonds\n"
                    "4. Contactez notre équipe pour les détails\n"
                )
            elif loan_status == 'PENDING':
                response += (
                    "⏳ Votre demande est **en cours d'examen**.\n\n"
                    "Le processus comprend:\n"
                    "1. Analyse préliminaire de votre dossier\n"
                    "2. Évaluation du score de crédit\n"
                    "3. Vérification des politiques de crédit\n"
                    "4. Analyse des risques et fraude\n"
                    "5. Décision finale et communication\n\n"
                    "Durée estimée: 2-5 jours ouvrables\n"
                )
            elif loan_status == 'REJECTED':
                response += (
                    "✗ Malheureusement, votre demande n'a pas été approuvée cette fois.\n\n"
                    "Raisons possibles et actions:\n"
                    "1. Score de crédit insuffisant → Améliorez votre historique de paiement\n"
                    "2. Endettement trop élevé → Remboursez d'autres crédits en priorité\n"
                    "3. Documents manquants → Préparez une documentation plus complète\n"
                    "4. Risque de fraude détecté → Clarifiez les anomalies avec notre équipe\n\n"
                    "Vous pouvez réessayer après avoir amélioré votre profil.\n"
                )

            if pd_score and risk_band:
                response += f"\n**Votre profil:** Score PD = {pd_score:.2f} | Catégorie de risque = {risk_band}\n"

            return response

        # Next steps
        elif any(word in message for word in ['prochaine', 'suivant', 'quoi', 'next', 'what', 'faire']):
            response = f"**Prochaines étapes pour votre {loan_purpose}:**\n\n"

            if loan_status == 'PENDING':
                response += (
                    "1. **Assurez-vous que vos documents sont complets**\n"
                    "   - Vérifiez que tous les justificatifs ont été soumis\n\n"
                    "2. **Consultez notre équipe si vous avez des questions**\n"
                    "   - Ne pas répondre aux demandes non-officielles\n\n"
                    "3. **Restez joignable**\n"
                    "   - Nous vous contacterons pour les mises à jour\n\n"
                    "4. **Évitez les changements majeurs**\n"
                    "   - Ne changez pas d'emploi ou ne faites pas de nouveaux crédits pendant l'examen\n"
                )
            elif loan_status == 'APPROVED':
                response += (
                    "1. **Signez les documents d'accord**\n"
                    "   - Vérifiez tous les termes attentivement\n\n"
                    "2. **Attendez le déblocage des fonds**\n"
                    "   - Les fonds seront virés selon votre accord\n\n"
                    "3. **Commencez vos paiements à temps**\n"
                    "   - Respectez le calendrier de remboursement\n"
                )

            return response

        # General guidance
        else:
            response = (
                f"Je suis votre assistant crédit pour votre demande de **{loan_purpose}** ({loan_amount}€).\n\n"
                f"**Statut actuel:** {loan_status}\n"
                f"**Montant:** {loan_amount}€\n"
                f"**Revenu mensuel:** {loan_income}€\n\n"
                "Je peux vous aider avec:\n"
                "• **Améliorer votre score** - Conseils pour renforcer votre dossier\n"
                "• **Documents nécessaires** - Liste complète des pièces à préparer\n"
                "• **Statut de votre demande** - Où en êtes-vous dans le processus\n"
                "• **Prochaines étapes** - Ce qu'il faut faire maintenant\n"
                "• **Questions sur le crédit** - Clarifications sur l'accord\n\n"
                "Que puis-je faire pour vous?\n"
            )
            return response

    def _extract_insights(
        self,
        loan: Dict[str, Any],
        response: str
    ) -> Optional[List[Insight]]:
        """Extract insights from loan data"""
        insights = []

        status = loan.get('status', '').upper()
        if status == 'APPROVED':
            insights.append(Insight(label="Status", value="Approved ✓", tone="positive"))
        elif status == 'PENDING':
            insights.append(Insight(label="Status", value="Under Review", tone="neutral"))
        elif status == 'REJECTED':
            insights.append(Insight(label="Status", value="Not Approved", tone="warning"))

        # Risk assessment
        pd_score = loan.get('pdScore')
        risk_band = loan.get('riskBand')

        if pd_score is not None:
            if pd_score < 0.35:
                insights.append(Insight(
                    label="Risk",
                    value=f"Low ({pd_score:.2f})",
                    tone="positive"
                ))
            elif pd_score < 0.65:
                insights.append(Insight(
                    label="Risk",
                    value=f"Moderate ({pd_score:.2f})",
                    tone="neutral"
                ))
            else:
                insights.append(Insight(
                    label="Risk",
                    value=f"High ({pd_score:.2f})",
                    tone="warning"
                ))

        # Debt-to-income ratio
        amount = loan.get('amount', 0)
        income = loan.get('income', 0)
        if amount and income and income > 0:
            monthly_payment = (amount * 1.05) / (loan.get('duration', 60) or 60)  # Rough estimate
            ratio = (monthly_payment / income) * 100
            if ratio < 30:
                insights.append(Insight(
                    label="Debt Ratio",
                    value=f"{ratio:.1f}% (Good)",
                    tone="positive"
                ))
            elif ratio < 50:
                insights.append(Insight(
                    label="Debt Ratio",
                    value=f"{ratio:.1f}% (Fair)",
                    tone="neutral"
                ))
            else:
                insights.append(Insight(
                    label="Debt Ratio",
                    value=f"{ratio:.1f}% (High)",
                    tone="warning"
                ))

        return insights if insights else None

    def _generate_suggested_prompts(
        self,
        message: str,
        loan: Dict[str, Any]
    ) -> Optional[List[SuggestedPrompt]]:
        """Generate follow-up prompts"""
        prompts = []

        status = loan.get('status', '').upper()

        if status == 'PENDING':
            prompts.append(SuggestedPrompt(
                label="Statut",
                prompt="Où en est ma demande?"
            ))

        if any(word in message for word in ['score', 'améliorer', 'improve']):
            prompts.append(SuggestedPrompt(
                label="Documents",
                prompt="Quels documents dois-je préparer?"
            ))
        else:
            prompts.append(SuggestedPrompt(
                label="Score",
                prompt="Comment améliorer mon score?"
            ))

        prompts.append(SuggestedPrompt(
            label="Prochaines étapes",
            prompt="Que dois-je faire maintenant?"
        ))

        return prompts if prompts else None

    def _error_response(self) -> AssistantChatResponse:
        """Return error response"""
        return AssistantChatResponse(
            message="Je rencontre une difficulté temporaire. Veuillez réessayer.",
            insights=[Insight(label="Status", value="Error", tone="warning")],
            status="fallback"
        )


# Singleton instance
_assistant_service: Optional[AssistantService] = None


def get_assistant_service() -> AssistantService:
    """Get or create assistant service singleton"""
    global _assistant_service
    if _assistant_service is None:
        _assistant_service = AssistantService()
    return _assistant_service
