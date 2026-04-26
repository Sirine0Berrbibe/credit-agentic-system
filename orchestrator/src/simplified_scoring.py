#!/usr/bin/env python
"""
Simplified ML Scoring for AICredits
Uses only form data (5 features) without full Home Credit dataset
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class SimplifiedScoringEngine:
    """
    Calculates PD (Probability of Default) score based on simple features
    Without external ML model or full feature set
    """
    
    @staticmethod
    def calculate_pd_score(client_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate probability of default using heuristic model
        
        Features:
        - amount: Requested credit amount
        - income: Monthly income
        - age: Applicant age
        - employment_years: Years employed
        - credit_duration: Requested duration (months)
        """
        
        try:
            # Extract features
            amount = float(client_data.get('amount', 0))
            income = float(client_data.get('income', 1))  # Avoid division by zero
            age = float(client_data.get('age', 30))
            employment_years = float(client_data.get('employment_years', 0))
            credit_duration = float(client_data.get('credit_duration', 60))
            
            # ═══════════════════════════════════════════════════════════
            # SCORING RULES (Heuristic Model)
            # ═══════════════════════════════════════════════════════════
            
            # 1. DEBT-TO-INCOME RATIO (most important)
            # Higher ratio = higher risk
            monthly_payment = (amount / credit_duration) if credit_duration > 0 else amount
            debt_to_income = monthly_payment / income if income > 0 else 1.0
            # Calibrate: 10% = 0.1 risk, 50% = 0.5 risk, 100% = 0.9 risk
            dti_component = min(0.9, max(0.1, debt_to_income * 0.9))
            
            # 2. AGE RISK
            # Young people (< 25) and very old (> 65) are higher risk
            age_component = 0.1  # Base risk
            if age < 25:
                age_component += (25 - age) / 25 * 0.3  # Add up to 0.3
            elif age > 65:
                age_component += (age - 65) / 20 * 0.3  # Add up to 0.3
            age_component = min(0.9, age_component)
            
            # 3. EMPLOYMENT STABILITY
            # Less than 1 year = very high risk
            employment_component = 0.1  # Base risk
            if employment_years < 1:
                employment_component += (1 - employment_years) * 0.5  # Add up to 0.5
            elif employment_years < 3:
                employment_component += (3 - employment_years) / 3 * 0.3  # Add up to 0.3
            employment_component = min(0.9, employment_component)
            
            # 4. CREDIT DURATION RISK
            # Very long duration = more months to default
            duration_component = min(0.9, max(0.1, credit_duration / 200))
            
            # 5. AMOUNT SIZE
            # Relative to annual income
            amount_ratio = amount / max(1, income * 12)
            amount_component = min(0.9, max(0.1, amount_ratio * 0.8))
            
            # ═══════════════════════════════════════════════════════════
            # FINAL SCORE (PD)
            # ═══════════════════════════════════════════════════════════
            # Weighted combination
            pd_score = (
                dti_component * 0.35 +         # Debt-to-income: 35%
                age_component * 0.20 +         # Age: 20%
                employment_component * 0.25 + # Employment: 25%
                duration_component * 0.10 +   # Duration: 10%
                amount_component * 0.10       # Amount: 10%
            )
            
            # ═══════════════════════════════════════════════════════════
            # SHAP-LIKE VALUES (Feature Contributions)
            # ═══════════════════════════════════════════════════════════
            # Convert components to SHAP-like values (contribution to score)
            # These represent how much each factor contributes to the final score
            
            shap_values = {
                "Ratio d'Endettement (DTI)": dti_component * 0.35,  # French: Debt-to-Income Ratio
                "Ancienneté Employé (Années)": employment_component * 0.25,  # French: Employment Years
                "Âge du Demandeur": age_component * 0.20,  # French: Age
                "Durée du Crédit (Mois)": duration_component * 0.10,  # French: Credit Duration
                "Montant du Crédit Demandé": amount_component * 0.10,  # French: Loan Amount
            }
            
            # ═══════════════════════════════════════════════════════════
            # CONFIDENCE & RISK BAND
            # ═══════════════════════════════════════════════════════════
            
            # Confidence based on employment stability
            confidence = 0.95 - (employment_component * 0.30)
            
            # Risk band
            if pd_score < 0.30:
                risk_band = "FAIBLE_RISQUE"
            elif pd_score < 0.50:
                risk_band = "RISQUE_MODERE"
            elif pd_score < 0.70:
                risk_band = "RISQUE_ELEVE"
            else:
                risk_band = "RISQUE_TRES_ELEVE"
            
            # ═══════════════════════════════════════════════════════════
            # DECISION
            # ═══════════════════════════════════════════════════════════
            
            if pd_score < 0.35:
                decision = "APPROVE"
            elif pd_score < 0.65:
                decision = "REVIEW"
            else:
                decision = "REJECT"
            
            return {
                'pd_score': pd_score,
                'confidence': confidence,
                'risk_band': risk_band,
                'decision': decision,
                'shap_values': shap_values,  # Add SHAP values for XAI
                'details': {
                    'dti_component': dti_component,
                    'age_component': age_component,
                    'employment_component': employment_component,
                    'duration_component': duration_component,
                    'amount_component': amount_component,
                }
            }
            
        except Exception as e:
            logger.error(f"Scoring error: {e}")
            return {
                'pd_score': 0.5,
                'confidence': 0.5,
                'risk_band': 'RISQUE_MODERE',
                'decision': 'REVIEW',
                'error': str(e)
            }


# Test
if __name__ == "__main__":
    engine = SimplifiedScoringEngine()
    
    print("\n" + "="*70)
    print("SIMPLIFIED SCORING ENGINE TEST".center(70))
    print("="*70 + "\n")
    
    profiles = [
        {
            'name': 'LOW RISK (Excellent credit)',
            'amount': 3000,
            'income': 20000,
            'age': 45,
            'employment_years': 10,
            'credit_duration': 60
        },
        {
            'name': 'HIGH RISK (Poor credit)',
            'amount': 20000,
            'income': 8000,
            'age': 25,
            'employment_years': 1,
            'credit_duration': 120
        },
        {
            'name': 'MEDIUM RISK',
            'amount': 10000,
            'income': 15000,
            'age': 35,
            'employment_years': 5,
            'credit_duration': 48
        }
    ]
    
    for profile in profiles:
        result = engine.calculate_pd_score(profile)
        print(f"{profile['name']}:")
        print(f"  Input: Amount={profile['amount']}, Income={profile['income']}, Age={profile['age']}, Years={profile['employment_years']}")
        print(f"  Score: {result['pd_score']:.4f}")
        print(f"  Decision: {result['decision']}")
        print(f"  Risk: {result['risk_band']}")
        print()
