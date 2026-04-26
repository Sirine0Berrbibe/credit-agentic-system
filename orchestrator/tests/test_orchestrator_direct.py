#!/usr/bin/env python
"""Test orchestrator directly"""
import asyncio
import json
from src.orchestrator_graph import create_orchestrator

async def test():
    orchestrator = await create_orchestrator()
    
    state = await orchestrator.process_application(
        client_id='TEST',
        client_data={
            'amount': 5000,
            'income': 15000,
            'age': 35,
            'employment_years': 5
        }
    )
    
    print("Final PD Score:", state.get('final_pd_score'))
    print("PD Confidence:", state.get('pd_confidence'))
    print("Risk Band:", state.get('risk_band'))
    print("Final Decision:", state.get('final_decision'))
    print("Error Messages:", state.get('error_messages'))
    print("Scoring Iterations:", len(state.get('scoring_iterations', [])))
    if state.get('scoring_iterations'):
        for it in state['scoring_iterations']:
            print(f"  Iteration {it['iteration']}: score={it['pd_score']:.4f}, confidence={it['confidence']:.4f}")

asyncio.run(test())
