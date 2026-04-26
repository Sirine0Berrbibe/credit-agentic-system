#!/usr/bin/env python
"""Final verification of all system components"""

import requests
import json

print("\n" + "="*70)
print("VÉRIFICATION FINALE DU SYSTÈME".center(70))
print("="*70 + "\n")

# Counter
passed = 0
total = 0

def test(name, func):
    global passed, total
    total += 1
    try:
        if func():
            print(f"✅ {name}")
            passed += 1
            return True
        else:
            print(f"❌ {name}")
            return False
    except Exception as e:
        print(f"❌ {name} - {str(e)[:50]}")
        return False

# 1. Infrastructure Tests
print("📡 INFRASTRUCTURE")
print("-" * 70)

test("API Health", lambda: requests.get("http://localhost:8001/health", timeout=5).status_code == 200)

def pg_health():
    r = requests.get("http://localhost:8001/infrastructure/health", timeout=5).json()
    return r.get('services', {}).get('postgresql', {}).get('status') == 'healthy'

def redis_health():
    r = requests.get("http://localhost:8001/infrastructure/health", timeout=5).json()
    return r.get('services', {}).get('redis', {}).get('status') == 'healthy'

def kafka_health():
    r = requests.get("http://localhost:8001/infrastructure/health", timeout=5).json()
    return r.get('services', {}).get('kafka', {}).get('status') == 'healthy'

test("PostgreSQL Health", pg_health)
test("Redis Health", redis_health)
test("Kafka Health", kafka_health)

# 2. API Tests
print("\n🏦 CREDIT DECISION")
print("-" * 70)

def test_api():
    data = {
        'client_id': 'FINAL-TEST-1',
        'client_data': {
            'amount': 5000,
            'income': 15000,
            'age': 35,
            'employment_years': 5
        }
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    return r.status_code == 200

test("POST /credit/decision", test_api)

def test_response_fields():
    data = {
        'client_id': 'FINAL-TEST-2',
        'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5}
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    result = r.json()
    
    required = ['application_id', 'final_decision', 'pd_score', 'risk_band', 'top_factors', 'explanation']
    return all(field in result for field in required)

test("Response Format Complet", test_response_fields)

def test_humanized():
    data = {
        'client_id': 'FINAL-TEST-3',
        'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5}
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    result = r.json()
    
    # Look for French feature names
    for factor in result.get('top_factors', []):
        feature = factor.get('feature', '').lower()
        if 'crédit' in feature or 'score' in feature or 'ancienneté' in feature:
            return True
    return False

test("Features Humanisées (FR)", test_humanized)

def test_shap():
    data = {
        'client_id': 'FINAL-TEST-4',
        'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5}
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    result = r.json()
    
    # Check SHAP values
    for factor in result.get('top_factors', []):
        if 'shap_value' in factor:
            return True
    return False

test("Valeurs SHAP Présentes", test_shap)

def test_counterfactuals():
    data = {
        'client_id': 'FINAL-TEST-5',
        'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5}
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    result = r.json()
    
    cf = result.get('counterfactuals', [])
    return len(cf) > 0

test("Explications Contrefactuelles", test_counterfactuals)

# 3. Data Storage Tests
print("\n💾 STOCKAGE DONNÉES")
print("-" * 70)

def test_audit_trail():
    data = {
        'client_id': 'FINAL-TEST-6',
        'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5}
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    result = r.json()
    
    # Check audit trail
    return result.get('audit_trail_length', 0) > 0

test("Audit Trail Stocké", test_audit_trail)

def test_stats():
    r = requests.get("http://localhost:8001/infrastructure/stats", timeout=5)
    data = r.json()
    
    pg_stats = data.get('services', {}).get('postgresql', {}).get('stats', {})
    return pg_stats.get('total_decisions') is not None

test("Statistiques PostgreSQL", test_stats)

# 3. ML & Performance Tests
print("\n⚙️  MODÈLE ML & PERFORMANCE")
print("-" * 70)

def test_score_valid():
    data = {
        'client_id': 'FINAL-TEST-7',
        'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5}
    }
    r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
    result = r.json()
    
    score = result.get('pd_score')
    return score is not None and 0 <= score <= 1

test("Score ML Valide (0-1)", test_score_valid)

def test_decisions_vary():
    """Test that different profiles get different decisions"""
    profiles = [
        {'amount': 3000, 'income': 20000, 'age': 45, 'employment_years': 10},
        {'amount': 20000, 'income': 8000, 'age': 25, 'employment_years': 1},
    ]
    
    decisions = []
    for i, profile in enumerate(profiles):
        data = {
            'client_id': f'VARY-TEST-{i}',
            'client_data': profile
        }
        r = requests.post("http://localhost:8001/credit/decision", json=data, timeout=30)
        result = r.json()
        decisions.append(result.get('pd_score'))
    
    # Scores should be different
    return abs(decisions[0] - decisions[1]) > 0.01

test("Décisions Varient par Profil", test_decisions_vary)

# Summary
print("\n" + "="*70)
print(f"RÉSULTAT: {passed}/{total} tests réussis ({passed/total*100:.0f}%)")
print("="*70)

if passed == total:
    print("\n✨ TOUS LES TESTS RÉUSSIS! ✨\n")
    print("Votre système est complètement opérationnel :")
    print("  ✅ Orchestrator      - Fonctionnel")
    print("  ✅ Scoring Agent     - Prédictions ML valides")
    print("  ✅ XAI Agent         - Explications + SHAP + Contrefactuels")
    print("  ✅ PostgreSQL        - Audit trail + Statistiques")
    print("  ✅ Redis             - Cache opérationnel")
    print("  ✅ Kafka             - Events streaming")
    print("  ✅ Features          - Humanisées en Français\n")
else:
    print(f"\n⚠️  {total - passed} test(s) échoué(s)\n")
