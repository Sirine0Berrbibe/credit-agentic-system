#!/usr/bin/env python
import requests
import json

# Create 3 different profiles
profiles = [
    {
        'client_id': 'LOW_RISK',
        'client_data': {
            'amount': 3000,
            'income': 20000,
            'age': 45,
            'employment_years': 10
        }
    },
    {
        'client_id': 'HIGH_RISK',
        'client_data': {
            'amount': 20000,
            'income': 8000,
            'age': 25,
            'employment_years': 1
        }
    },
    {
        'client_id': 'MID_RISK',
        'client_data': {
            'amount': 10000,
            'income': 15000,
            'age': 35,
            'employment_years': 5
        }
    }
]

scores = []
for profile in profiles:
    try:
        response = requests.post('http://localhost:8001/credit/decision', json=profile, timeout=30)
        result = response.json()
        score = result.get('pd_score', 0)
        scores.append((profile['client_id'], score))
        print(f"{profile['client_id']}: pd_score={score:.4f}, decision={result.get('final_decision')}")
    except Exception as e:
        print(f"{profile['client_id']}: Error - {str(e)[:50]}")

if len(scores) >= 2:
    diff = abs(scores[0][1] - scores[1][1])
    print(f"\nScore Variance: {diff:.4f}")
    if diff > 0.01:
        print("✅ PASS: Profiles have sufficient variance!")
    else:
        print(f"❌ FAIL: Variance {diff:.4f} < 0.01 threshold")
