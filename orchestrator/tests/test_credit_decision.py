#!/usr/bin/env python
"""Test credit decision endpoint with humanized features"""

import requests
import json
import time

time.sleep(2)

data = {
    'client_id': '12345',
    'client_data': {
        'amount': 5000,
        'income': 15000,
        'age': 35,
        'employment_years': 5,
        'credit_duration': 60
    },
    'decision_type': 'full_assessment'
}

print("=" * 60)
print("Testing Credit Decision Endpoint")
print("=" * 60)
print(f"\nRequest data: {json.dumps(data, indent=2)}\n")

response = requests.post('http://localhost:8001/credit/decision', json=data)

if response.status_code == 200:
    result = response.json()
    print(f"✅ Status Code: {response.status_code}")
    print(f"Status: {result.get('status')}")
    print(f"Approved: {result.get('approved')}")
    print(f"Score: {result.get('score')}")
    
    if 'explanation' in result and 'features' in result['explanation']:
        print(f"\n📊 Features (showing top 5):")
        for i, feature in enumerate(result['explanation']['features'][:5], 1):
            print(f"  {i}. {feature.get('name')}: {feature.get('value')}")
    
    print(f"\n📝 Full response:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
else:
    print(f"❌ Error {response.status_code}")
    print(f"Response: {response.text}")

print("\n" + "=" * 60)
