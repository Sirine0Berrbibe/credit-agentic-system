#!/usr/bin/env python
import requests
import json

data = {
    'client_id': 'TEST',
    'client_data': {
        'amount': 5000,
        'income': 15000,
        'age': 35,
        'employment_years': 5
    }
}

try:
    response = requests.post('http://localhost:8001/credit/decision', json=data, timeout=30)
    print('Status:', response.status_code)
    result = response.json()
    print('Full Response:')
    print(json.dumps(result, indent=2))
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()

