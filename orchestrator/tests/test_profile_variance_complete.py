#!/usr/bin/env python
"""Test: Décisions Varient par Profil"""
import requests
import json

print("=" * 70)
print("TEST: Décisions Varient par Profil")
print("=" * 70)

# Test with 3 different risk profiles
profiles = {
    'LOW_RISK': {
        'client_id': 'PROFILE-LOW',
        'client_data': {
            'amount': 3000,  # Small loan
            'income': 20000,  # Good income
            'age': 45,  # Good age
            'employment_years': 10  # Stable job
        }
    },
    'HIGH_RISK': {
        'client_id': 'PROFILE-HIGH',
        'client_data': {
            'amount': 20000,  # Large loan
            'income': 8000,  # Low income
            'age': 25,  # Young
            'employment_years': 1  # NEW job
        }
    },
    'MEDIUM_RISK': {
        'client_id': 'PROFILE-MEDIUM',
        'client_data': {
            'amount': 10000,
            'income': 15000,
            'age': 35,
            'employment_years': 5
        }
    }
}

scores = {}
print("\n📊 Profile Scores:\n")

for profile_name, profile_data in profiles.items():
    try:
        response = requests.post(
            'http://localhost:8001/credit/decision',
            json=profile_data,
            timeout=30
        )
        result = response.json()
        score = result.get('pd_score', 0)
        scores[profile_name] = score
        print(f"{profile_name:12s}: pd_score={score:.4f}, decision={result.get('final_decision')}, risk={result.get('risk_band')}")
    except Exception as e:
        print(f"{profile_name:12s}: ERROR - {str(e)[:40]}")
        scores[profile_name] = 0

# Test if scores vary
print("\n" + "=" * 70)
print("RÉSULTATS:")
print("=" * 70)

if len(scores) >= 2:
    low_risk_score = scores.get('LOW_RISK', 0)
    high_risk_score = scores.get('HIGH_RISK', 0)
    variance = abs(high_risk_score - low_risk_score)
    
    print(f"\nVariance (HIGH_RISK - LOW_RISK): {variance:.4f}")
    print(f"Requirement: > 0.0100")
    
    if variance > 0.01:
        print("✅ PASS: Décisions Varient par Profil")
    else:
        print(f"❌ FAIL: Variance {variance:.4f} is less than 0.01")
else:
    print("❌ FAIL: Could not get sufficient profiles")
