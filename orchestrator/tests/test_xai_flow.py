#!/usr/bin/env python
"""Test the full flow from scoring to XAI"""
import asyncio
import json
from src.orchestrator_graph import create_orchestrator

async def test():
    orchestrator = await create_orchestrator()
    
    state = await orchestrator.process_application(
        client_id='DEBUG-TEST',
        client_data={
            'amount': 5000,
            'income': 15000,
            'age': 35,
            'employment_years': 5
        }
    )
    
    print("=== SCORING ITERATIONS ===")
    for it in state.get('scoring_iterations', []):
        print(f"\nIteration {it.get('iteration')}:")
        print(f"  pd_score: {it.get('pd_score')}")
        print(f"  confidence: {it.get('confidence')}")
        print(f"  shap_values type: {type(it.get('shap_values'))}")
        print(f"  shap_values: {it.get('shap_values')}")
    
    print("\n=== XAI RESULT ===")
    xai = state.get('xai_explanation', {})
    print(f"SHAP values in XAI: {len(xai.get('shap_values', {}))} features")
    print(f"Top factors: {len(xai.get('top_factors', []))} factors")
    print(f"Counterfactuals: {len(xai.get('counterfactuals', []))} counterfactuals")
    
    if xai.get('top_factors'):
        print("\nTop factors:")
        for factor in xai['top_factors'][:3]:
            print(f"  {factor.get('feature')}: {factor.get('shap_value'):.4f}")
    
    if xai.get('counterfactuals'):
        print("\nCounterfactuals:")
        for cf in xai['counterfactuals'][:2]:
            print(f"  {cf.get('feature')}: {cf.get('action')}")
    
    print("\n=== API RESPONSE ===")
    print(f"final_decision: {state.get('final_decision')}")
    print(f"final_pd_score: {state.get('final_pd_score')}")

asyncio.run(test())
