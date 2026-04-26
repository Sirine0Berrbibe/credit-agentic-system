#!/usr/bin/env python
"""Test des agents individuels sans la boucle ReAct"""

import asyncio
import json
import sys
sys.path.insert(0, '.')

from src.llm_client import AzureOpenAIClient
from config.settings import get_config
from agents.analyzer_agent import AnalyzerAgent
from agents.risk_assessor_agent import RiskAssessorAgent
from agents.scorer_agent import ScorerAgent

async def test_agents():
    """Test les agents individuellement"""
    
    config = get_config()
    client_data = {
        "age": 35,
        "income": 55000,
        "expenses": 25000,
        "employment_type": "permanent",
        "has_credit_history": True,
        "loan_amount": 20000,
        "loan_term_months": 60,
        "purpose": "consolidation"
    }
    
    print("=" * 60)
    print("TEST AGENTS INDIVIDUELS")
    print("=" * 60)
    
    # Test Analyzer
    print("\n1. TESTING ANALYZER...")
    try:
        analyzer = AnalyzerAgent()
        result = await analyzer.process({"client_data": client_data})
        print(f"✓ Analyzer SUCCESS")
        print(f"  Analysis: {json.dumps(result.get('analysis', {}), indent=2)}")
    except Exception as e:
        print(f"✗ Analyzer ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    # Test Risk Assessor
    print("\n2. TESTING RISK ASSESSOR...")
    try:
        risk = RiskAssessorAgent()
        risk_result = await risk.process({
            "client_data": client_data,
            "analysis": result.get("analysis", {})
        })
        print(f"✓ Risk Assessor SUCCESS")
        print(f"  Risk Score: {risk_result.get('risk_score')}")
        print(f"  Risk Level: {risk_result.get('risk_level')}")
    except Exception as e:
        print(f"✗ Risk Assessor ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    # Test Scorer
    print("\n3. TESTING SCORER...")
    try:
        scorer = ScorerAgent()
        score_result = await scorer.process({
            "client_data": client_data
        })
        print(f"✓ Scorer SUCCESS")
        print(f"  Score: {score_result.get('score')}")
        print(f"  Decision: {score_result.get('decision')}")
    except Exception as e:
        print(f"✗ Scorer ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(test_agents())
