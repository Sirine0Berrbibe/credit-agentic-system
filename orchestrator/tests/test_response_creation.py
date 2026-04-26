#!/usr/bin/env python
"""Test the API response creation"""
import asyncio
import json
from src.orchestrator_graph import create_orchestrator
from src.orchestrator_api import CreditDecisionResponse

async def test():
    orchestrator = await create_orchestrator()
    
    state = await orchestrator.process_application(
        client_id='TEST-API',
        client_data={
            'amount': 5000,
            'income': 15000,
            'age': 35,
            'employment_years': 5
        }
    )
    
    print("State keys:", list(state.keys()))
    print("\n=== xai_explanation ===")
    print(json.dumps(state.get('xai_explanation'), default=str, indent=2)[:500])
    
    print("\n=== Creating response ===")
    try:
        response = CreditDecisionResponse(
            application_id=state["application_id"],
            client_id=state["client_id"],
            final_decision=state["final_decision"],
            decision_summary=state["decision_summary"],
            next_action=state["next_action"],
            pd_score=state["final_pd_score"],
            pd_confidence=state["pd_confidence"],
            risk_band=state["risk_band"],
            rule_id=state["policy_decision"]["rule_id"],
            recommended_product=state["policy_decision"]["recommended_product"],
            top_factors=state["xai_explanation"]["top_factors"],
            counterfactuals=state["xai_explanation"]["counterfactuals"],
            explanation=state["xai_explanation"]["natural_explanation"],
            fraud_risk_score=(
                state["fraud_analysis"]["fraud_risk_score"]
                if state["fraud_analysis"]
                else 0.0
            ),
            is_application_blocked=state["is_application_blocked"],
            processing_time_ms=state["total_processing_time_ms"],
            created_at=state["created_at"],
            audit_trail_length=len(state["audit_trail"]),
        )
        print("Response top_factors:", len(response.top_factors))
        print("Response counterfactuals:", len(response.counterfactuals))
        print("Response as dict:", json.dumps(response.model_dump(), default=str, indent=2)[:500])
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test())
