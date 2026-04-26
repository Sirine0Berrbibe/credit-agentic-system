#!/usr/bin/env python
"""Test fallback scoring directly"""
from src.agents.scoring_agent import ScoringAgent

agent = ScoringAgent()

enriched_data = {
    'AMT_CREDIT': 5000,
    'AMT_INCOME_TOTAL': 15000,
    'DAYS_BIRTH': -45*365,
    'DAYS_EMPLOYED': -5*365,
    'CREDIT_TERM': 60
}

result = agent._fallback_scoring(enriched_data)
print("Result:", result)
print()
print("pd_score:", result.get('pd_score'))
print("confidence:", result.get('confidence'))
print("risk_band:", result.get('risk_band'))
print("decision:", result.get('decision'))
