#!/usr/bin/env python
"""
Quick System Health Check
Fast verification of all components
"""

import requests
import time
import json
import sys

print("=" * 70)
print("VÉRIFICATION RAPIDE DU SYSTÈME".center(70))
print("=" * 70)

tests_passed = 0
tests_total = 0

def check(name: str, func):
    global tests_passed, tests_total
    tests_total += 1
    try:
        if func():
            print(f"✅ {name}")
            tests_passed += 1
            return True
        else:
            print(f"❌ {name}")
            return False
    except Exception as e:
        print(f"❌ {name}: {str(e)[:60]}")
        return False

print("\n📡 INFRASTRUCTURE\n")

check("API Health", lambda: requests.get("http://localhost:8001/health", timeout=5).status_code == 200)

def infra_health():
    r = requests.get("http://localhost:8001/infrastructure/health", timeout=5)
    return r.json().get('services', {}).get('postgresql', {}).get('status') == 'healthy'

check("PostgreSQL Health", infra_health)
check("Redis Health", lambda: requests.get("http://localhost:8001/infrastructure/health", timeout=5).json().get('services', {}).get('redis', {}).get('status') == 'healthy')
check("Kafka Health", lambda: requests.get("http://localhost:8001/infrastructure/health", timeout=5).json().get('services', {}).get('kafka', {}).get('status') == 'healthy')

print("\n🏦 CREDIT DECISION\n")

def test_decision():
    data = {
        'client_id': 'QUICK-TEST',
        'client_data': {
            'amount': 5000,
            'income': 15000,
            'age': 35,
            'employment_years': 5
        }
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    return r.status_code == 200

check("Credit Decision API", test_decision)

def test_features():
    data = {
        'client_id': 'FEATURE-TEST',
        'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5}
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    result = r.json()
    
    # Check for French labels
    for factor in result.get('top_factors', []):
        if 'crédit' in factor.get('feature', '').lower():
            return True
    return False

check("Features Humanisées (FR)", test_features)

def test_explanation():
    data = {
        'client_id': 'XAI-TEST',
        'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5}
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    result = r.json()
    return len(result.get('explanation', '')) > 50

check("Explications Détaillées", test_explanation)

def test_counterfactual():
    data = {
        'client_id': 'CF-TEST',
        'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5}
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    result = r.json()
    return len(result.get('counterfactuals', [])) > 0

check("Explications Contrefactuelles", test_counterfactual)

print("\n" + "=" * 70)
print(f"RÉSULTAT: {tests_passed}/{tests_total} tests réussis ({tests_passed/tests_total*100:.0f}%)")
print("=" * 70 + "\n")

if tests_passed == tests_total:
    print("✨ TOUS LES TESTS RÉUSSIS! ✨\n")
else:
    print(f"⚠️  {tests_total - tests_passed} test(s) échoué(s)\n")

sys.exit(0 if tests_passed == tests_total else 1)
