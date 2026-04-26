#!/usr/bin/env python
"""Comprehensive test for the three previously failing tests"""
import requests
import json

print("=" * 70)
print("TEST: Features Humanisées (FR), Valeurs SHAP, Explications Contrefactuelles")
print("=" * 70)

data = {
    'client_id': 'COMPREHENSIVE-TEST',
    'client_data': {
        'amount': 5000,
        'income': 15000,
        'age': 35,
        'employment_years': 5
    }
}

print("\nFetching credit decision...\n")
response = requests.post('http://localhost:8001/credit/decision', json=data, timeout=30)
result = response.json()

tests_passed = 0
tests_total = 3

# Test 1: Features Humanisées (FR)
print("=" * 70)
print("TEST 1: Features Humanisées (FR)")
print("-" * 70)
top_factors = result.get('top_factors', [])
french_features_found = False
for factor in top_factors:
    feature = factor.get('feature', '').lower()
    if any(word in feature for word in ['crédit', 'score', 'ancienneté', 'âge', 'ratio', 'montant']):
        french_features_found = True
        break

if french_features_found and len(top_factors) > 0:
    print(f"✅ PASS: Found {len(top_factors)} French feature names")
    print(f"   Examples:")
    for factor in top_factors[:2]:
        print(f"   - {factor.get('feature')}")
    tests_passed += 1
else:
    print("❌ FAIL: No French feature names found")

# Test 2: Valeurs SHAP Présentes
print("\n" + "=" * 70)
print("TEST 2: Valeurs SHAP Présentes")
print("-" * 70)
shap_values_found = 0
for factor in top_factors:
    if 'shap_value' in factor and factor['shap_value'] is not None:
        shap_values_found += 1

if shap_values_found > 0:
    print(f"✅ PASS: Found {shap_values_found} SHAP values")
    print(f"   Examples:")
    for factor in top_factors[:2]:
        print(f"   - {factor.get('feature')}: {factor.get('shap_value'):.4f}")
    tests_passed += 1
else:
    print("❌ FAIL: No SHAP values found")

# Test 3: Explications Contrefactuelles
print("\n" + "=" * 70)
print("TEST 3: Explications Contrefactuelles")
print("-" * 70)
counterfactuals = result.get('counterfactuals', [])
if len(counterfactuals) > 0:
    print(f"✅ PASS: Found {len(counterfactuals)} counterfactuals")
    print(f"   Examples:")
    for cf in counterfactuals[:2]:
        print(f"   - {cf.get('action')}")
    tests_passed += 1
else:
    print("❌ FAIL: No counterfactuals found")

# Summary
print("\n" + "=" * 70)
print(f"RÉSULTATS: {tests_passed}/{tests_total} tests passed")
print("=" * 70)
if tests_passed == tests_total:
    print("✅ ALL TESTS PASSED!")
else:
    print(f"❌ {tests_total - tests_passed} test(s) failed")
