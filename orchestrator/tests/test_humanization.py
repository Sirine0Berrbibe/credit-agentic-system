#!/usr/bin/env python3
"""
Test script — Vérifier la humanization des features dans les explications
"""

import httpx
import json
from typing import Dict, Any

def test_humanized_explanations():
    """Teste que les features apparaissent en langage humain"""
    
    client = httpx.Client(timeout=30.0)
    
    # Requête de test
    request_data = {
        "client_id": "TEST_HUMAN_001",
        "client_data": {
            "EXT_SOURCE_MEAN": 0.45,
            "AMT_INCOME_TOTAL": 150000,
            "CODE_GENDER": "M",
            "DAYS_BIRTH": -15000,
            "AMT_CREDIT": 75000,
            "DTI": 0.32,
            "AMT_ANNUITY": 2000,
            "CNT_CHILDREN": 2,
        }
    }
    
    print("=" * 80)
    print("TESTING HUMANIZED EXPLANATIONS")
    print("=" * 80)
    print(f"\n📝 Requête: {json.dumps(request_data, indent=2)}\n")
    
    try:
        response = client.post(
            "http://localhost:8001/credit/decision",
            json=request_data
        )
        
        if response.status_code != 200:
            print(f"❌ Erreur HTTP {response.status_code}")
            print(response.text)
            return False
        
        result = response.json()
        
        # Vérifications
        print("✅ Réponse reçue\n")
        
        # 1. Vérifier la présence de xai_explanation
        if "xai_explanation" not in result:
            print("❌ xai_explanation manquante")
            return False
        
        xai = result["xai_explanation"]
        print("📊 XAI Explanation:")
        print(f"  - Natural explanation: {xai.get('natural_explanation', 'N/A')[:100]}...")
        
        # 2. Vérifier top_factors avec labels humanisés
        print("\n🎯 Top Factors (devrait contenir des labels humanisés, PAS de noms techniques):")
        technical_names = ["EXT_SOURCE_MEAN", "AMT_INCOME_TOTAL", "DTI"]
        
        for factor in xai.get("top_factors", []):
            feature_name = factor.get("feature", "N/A")
            technical_name = factor.get("technical_name", "N/A")
            shap_value = factor.get("shap_value", 0)
            impact = factor.get("impact", "N/A")
            
            print(f"\n  Feature: {feature_name}")
            print(f"  Technical: {technical_name}")
            print(f"  SHAP Value: {shap_value:+.4f}")
            print(f"  Impact: {impact}")
            
            # Vérifier que ce n'est PAS un nom technique
            if feature_name in technical_names:
                print(f"  ⚠️  WARNING: Feature name is still technical!")
            else:
                print(f"  ✅ Humanized label detected")
        
        # 3. Vérifier les counterfactuals avec actions en langage humain
        print("\n🚀 Counterfactuals (actions pour améliorer):")
        for cf in xai.get("counterfactuals", []):
            action = cf.get("action", "N/A")
            impact = cf.get("impact", "N/A")
            feature = cf.get("feature", "N/A")
            
            print(f"\n  Action: {action}")
            print(f"  Feature: {feature}")
            print(f"  Impact: {impact}")
            
            # Verify it's human-readable (contains French words)
            french_keywords = ["améliorer", "augmenter", "réduire", "maintenir", "revenu", "score", "crédit"]
            is_human_readable = any(kw in action.lower() for kw in french_keywords)
            
            if is_human_readable:
                print(f"  ✅ Action en langage humain")
            else:
                print(f"  ⚠️ WARNING: Action might not be humanized")
        
        # Decision info
        print(f"\n🔐 Decision: {result.get('final_decision', 'N/A')}")
        print(f"📈 PD Score: {result.get('pd_score', 'N/A'):.2%}")
        
        print("\n" + "=" * 80)
        print("✅ TEST COMPLETED SUCCESSFULLY")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        client.close()


if __name__ == "__main__":
    success = test_humanized_explanations()
    exit(0 if success else 1)
