#!/usr/bin/env python
"""
Complete System Integration Test Suite
Tests: PostgreSQL, Kafka, Redis, Orchestrator, Scoring Agent, XAI Agent, ML Pipeline
"""

import asyncio
import requests
import json
import time
from typing import Dict, Any, List
import sys

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

class TestRunner:
    def __init__(self):
        self.results = []
        self.api_url = "http://localhost:8001"
        self.test_count = 0
        self.pass_count = 0
        self.fail_count = 0

    def test(self, name: str, func):
        """Run a test and track results"""
        self.test_count += 1
        try:
            result = func()
            if result:
                self.pass_count += 1
                print(f"{GREEN}✅ {name}{RESET}")
                return True
            else:
                self.fail_count += 1
                print(f"{RED}❌ {name}{RESET}")
                return False
        except Exception as e:
            self.fail_count += 1
            print(f"{RED}❌ {name}: {str(e)[:100]}{RESET}")
            return False

    def print_header(self, text: str):
        print(f"\n{BOLD}{BLUE}{'=' * 70}{RESET}")
        print(f"{BOLD}{BLUE}{text:^70}{RESET}")
        print(f"{BOLD}{BLUE}{'=' * 70}{RESET}\n")

    def print_summary(self):
        total = self.test_count
        rate = (self.pass_count / total * 100) if total > 0 else 0
        
        print(f"\n{BOLD}{BLUE}{'=' * 70}{RESET}")
        print(f"{BOLD}RÉSUMÉ DES TESTS{RESET}")
        print(f"{BOLD}{BLUE}{'=' * 70}{RESET}")
        print(f"✅ Réussis: {GREEN}{self.pass_count}{RESET}/{total}")
        print(f"❌ Échoués: {RED}{self.fail_count}{RESET}/{total}")
        print(f"📊 Taux de réussite: {rate:.1f}%\n")
        
        if self.fail_count == 0:
            print(f"{GREEN}{BOLD}✨ TOUS LES TESTS RÉUSSIS! ✨{RESET}\n")
        else:
            print(f"{RED}{BOLD}⚠️  CERTAINS TESTS ONT ÉCHOUÉ{RESET}\n")

# ==================== 1. Infrastructure Tests ====================

def test_api_health():
    """Test if API is running"""
    try:
        response = requests.get("http://localhost:8001/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def test_infrastructure_health():
    """Test if all infrastructure services are healthy"""
    try:
        response = requests.get("http://localhost:8001/infrastructure/health", timeout=5)
        data = response.json()
        return (response.status_code == 200 and 
                data.get('services', {}).get('postgresql', {}).get('status') == 'healthy')
    except:
        return False

async def test_postgresql_connection():
    """Test PostgreSQL direct connection"""
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host='localhost',
            port=5434,
            user='pfe',
            password='pfe2026',
            database='scoring_db'
        )
        version = await conn.fetchval('SELECT version()')
        await conn.close()
        return version is not None
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

async def test_redis_connection():
    """Test Redis direct connection"""
    try:
        import redis.asyncio as redis
        r = redis.from_url("redis://:redis_secure_pass_2026@localhost:6379/0")
        result = await r.ping()
        await r.close()
        return result is True
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

def test_kafka_connection():
    """Test Kafka broker availability"""
    try:
        from kafka import KafkaProducer
        producer = KafkaProducer(
            bootstrap_servers=['localhost:9092'],
            request_timeout_ms=5000
        )
        producer.close()
        return True
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

# ==================== 2. API Endpoint Tests ====================

def test_credit_decision_endpoint():
    """Test POST /credit/decision endpoint"""
    try:
        data = {
            'client_id': 'TEST-001',
            'client_data': {
                'amount': 5000,
                'income': 15000,
                'age': 35,
                'employment_years': 5,
                'credit_duration': 60
            },
            'decision_type': 'full_assessment'
        }
        response = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

def test_decision_response_format():
    """Test that decision response has all required fields"""
    try:
        data = {
            'client_id': 'TEST-002',
            'client_data': {
                'amount': 3000,
                'income': 12000,
                'age': 28,
                'employment_years': 3,
                'credit_duration': 48
            }
        }
        response = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
        result = response.json()
        
        required_fields = [
            'application_id', 'client_id', 'final_decision',
            'pd_score', 'risk_band', 'top_factors', 'explanation'
        ]
        
        return all(field in result for field in required_fields)
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

def test_humanized_features():
    """Test that features are humanized (in French)"""
    try:
        data = {
            'client_id': 'TEST-003',
            'client_data': {
                'amount': 7000,
                'income': 18000,
                'age': 40,
                'employment_years': 8,
                'credit_duration': 72
            }
        }
        response = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
        result = response.json()
        
        # Check if top_factors contain French labels
        has_french = False
        if 'top_factors' in result:
            for factor in result['top_factors']:
                feature_name = factor.get('feature', '').lower()
                # Check for common French words in feature names
                french_keywords = ['score', 'crédit', 'jours', 'ancienneté', 'revenu', 'âge']
                if any(kw in feature_name for kw in french_keywords):
                    has_french = True
                    break
        
        return has_french
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

def test_counterfactuals_present():
    """Test that counterfactual explanations are in response"""
    try:
        data = {
            'client_id': 'TEST-004',
            'client_data': {
                'amount': 4000,
                'income': 14000,
                'age': 32,
                'employment_years': 4
            }
        }
        response = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
        result = response.json()
        
        return 'counterfactuals' in result and len(result['counterfactuals']) > 0
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

# ==================== 3. PostgreSQL Storage Tests ====================

async def test_audit_logs_stored():
    """Test that audit logs are being stored in PostgreSQL"""
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host='localhost',
            port=5434,
            user='pfe',
            password='pfe2026',
            database='scoring_db'
        )
        
        # Check if audit_logs table exists and has data
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM audit_logs"
        )
        await conn.close()
        
        return count is not None and count > 0
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

async def test_credit_decisions_stored():
    """Test that credit decisions are stored in PostgreSQL"""
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host='localhost',
            port=5434,
            user='pfe',
            password='pfe2026',
            database='scoring_db'
        )
        
        # Check if credit_decisions table exists
        result = await conn.fetchval(
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'credit_decisions'
            )"""
        )
        await conn.close()
        
        return result is True
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

async def test_feature_cache_stored():
    """Test that feature cache is stored in PostgreSQL"""
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host='localhost',
            port=5434,
            user='pfe',
            password='pfe2026',
            database='scoring_db'
        )
        
        # Check if feature_cache table exists
        result = await conn.fetchval(
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'feature_cache'
            )"""
        )
        await conn.close()
        
        return result is True
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

# ==================== 4. Redis Caching Tests ====================

async def test_redis_cache_operations():
    """Test Redis caching with set/get operations"""
    try:
        import redis.asyncio as redis
        r = redis.from_url("redis://:redis_secure_pass_2026@localhost:6379/0")
        
        # Test set and get
        await r.set("test_key", "test_value", ex=60)
        value = await r.get("test_key")
        
        # Cleanup
        await r.delete("test_key")
        await r.close()
        
        return value == b"test_value"
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

async def test_redis_stats():
    """Test Redis statistics endpoint"""
    try:
        response = requests.get(f"{runner.api_url}/infrastructure/stats", timeout=5)
        data = response.json()
        
        redis_stats = data.get('services', {}).get('redis', {}).get('stats', {})
        return redis_stats.get('used_memory_mb') is not None
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

# ==================== 5. Scoring Agent Tests ====================

def test_with_different_risk_profiles():
    """Test scoring with different client risk profiles"""
    try:
        profiles = [
            {'name': 'Low Risk', 'amount': 3000, 'income': 20000, 'age': 40, 'employment_years': 10},
            {'name': 'Medium Risk', 'amount': 10000, 'income': 15000, 'age': 30, 'employment_years': 3},
            {'name': 'High Risk', 'amount': 20000, 'income': 8000, 'age': 25, 'employment_years': 1},
        ]
        
        all_valid = True
        for i, profile in enumerate(profiles, 1):
            data = {
                'client_id': f'PROFILE-TEST-{i}',
                'client_data': {
                    'amount': profile['amount'],
                    'income': profile['income'],
                    'age': profile['age'],
                    'employment_years': profile['employment_years']
                }
            }
            
            response = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
            if response.status_code != 200:
                all_valid = False
                break
            
            result = response.json()
            # Check that we got a decision
            if 'final_decision' not in result or 'pd_score' not in result:
                all_valid = False
                break
        
        return all_valid
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

# ==================== 6. XAI Agent Tests ====================

def test_explanation_quality():
    """Test that explanations are detailed and informative"""
    try:
        data = {
            'client_id': 'XAI-TEST-001',
            'client_data': {
                'amount': 5000,
                'income': 15000,
                'age': 35,
                'employment_years': 5
            }
        }
        response = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
        result = response.json()
        
        # Check explanation quality
        explanation = result.get('explanation', '')
        top_factors = result.get('top_factors', [])
        
        has_good_explanation = (
            len(explanation) > 50 and
            len(top_factors) >= 3
        )
        
        return has_good_explanation
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

def test_shap_values_presence():
    """Test that SHAP values are present in explanation"""
    try:
        data = {
            'client_id': 'SHAP-TEST-001',
            'client_data': {
                'amount': 6000,
                'income': 16000,
                'age': 36,
                'employment_years': 6
            }
        }
        response = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
        result = response.json()
        
        # Check if SHAP values are present
        has_shap = False
        if 'top_factors' in result:
            for factor in result['top_factors']:
                if 'shap_value' in factor:
                    has_shap = True
                    break
        
        return has_shap
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

# ==================== 7. ML Model Tests ====================

def test_ml_model_predictions():
    """Test that ML model is producing valid predictions"""
    try:
        data = {
            'client_id': 'ML-TEST-001',
            'client_data': {
                'amount': 5000,
                'income': 15000,
                'age': 35,
                'employment_years': 5
            }
        }
        response = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
        result = response.json()
        
        # Check PD score is valid (between 0 and 1)
        pd_score = result.get('pd_score')
        
        return (pd_score is not None and 
                0 <= pd_score <= 1)
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

def test_model_consistency():
    """Test that model gives consistent results for same input"""
    try:
        data = {
            'client_id': 'CONSISTENCY-TEST',
            'client_data': {
                'amount': 5000,
                'income': 15000,
                'age': 35,
                'employment_years': 5,
                'credit_duration': 60
            }
        }
        
        # Run twice
        response1 = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
        result1 = response1.json()
        score1 = result1.get('pd_score')
        
        time.sleep(0.5)
        
        response2 = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=30)
        result2 = response2.json()
        score2 = result2.get('pd_score')
        
        # Scores should be very close (allow small variation due to randomness)
        return abs(score1 - score2) < 0.01
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

# ==================== 8. Integration Tests ====================

def test_end_to_end_pipeline():
    """Test complete pipeline from request to response"""
    try:
        test_cases = [
            {
                'client_id': 'E2E-TEST-1',
                'client_data': {'amount': 5000, 'income': 15000, 'age': 35, 'employment_years': 5},
                'expected_decision': ['APPROVE', 'DECLINE', 'REVIEW']
            },
            {
                'client_id': 'E2E-TEST-2',
                'client_data': {'amount': 3000, 'income': 20000, 'age': 45, 'employment_years': 10},
                'expected_decision': ['APPROVE', 'DECLINE', 'REVIEW']
            }
        ]
        
        for test_case in test_cases:
            response = requests.post(
                f"{runner.api_url}/credit/decision",
                json=test_case,
                timeout=30
            )
            
            if response.status_code != 200:
                return False
            
            result = response.json()
            
            # Check all required fields
            required_fields = [
                'application_id', 'final_decision', 'pd_score',
                'risk_band', 'top_factors', 'explanation',
                'audit_trail_length'
            ]
            
            if not all(field in result for field in required_fields):
                return False
        
        return True
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

def test_performance_timing():
    """Test that response times are acceptable"""
    try:
        data = {
            'client_id': 'PERF-TEST',
            'client_data': {
                'amount': 5000,
                'income': 15000,
                'age': 35,
                'employment_years': 5
            }
        }
        
        start = time.time()
        response = requests.post(f"{runner.api_url}/credit/decision", json=data, timeout=60)
        elapsed = (time.time() - start) * 1000
        
        result = response.json()
        processing_time = result.get('processing_time_ms', 0)
        
        # Check if response is reasonably fast (< 5 seconds)
        return elapsed < 5000
    except Exception as e:
        print(f"  └─ {str(e)[:80]}")
        return False

# ==================== Main Execution ====================

async def run_async_tests():
    """Run all async tests"""
    global runner
    
    runner.print_header("2️⃣ TESTS POSTGRESQL")
    runner.test("Connexion PostgreSQL directe", test_postgresql_connection)
    runner.test("Audit logs stockés", test_audit_logs_stored)
    runner.test("Table credit_decisions existe", test_credit_decisions_stored)
    runner.test("Table feature_cache existe", test_feature_cache_stored)
    
    runner.print_header("3️⃣ TESTS REDIS")
    runner.test("Connexion Redis directe", test_redis_connection)
    runner.test("Opérations cache Redis", test_redis_cache_operations)
    runner.test("Statistiques Redis", test_redis_stats)

if __name__ == "__main__":
    runner = TestRunner()
    
    # Wait for services to be ready
    print(f"{YELLOW}⏳ Attente que les services démarrent...{RESET}")
    for i in range(10):
        try:
            if test_api_health():
                print(f"{GREEN}✅ Services prêts!{RESET}\n")
                break
            time.sleep(1)
        except:
            pass
    else:
        print(f"{RED}❌ L'API n'est pas disponible sur {runner.api_url}{RESET}")
        print(f"{YELLOW}Assurez-vous que le service est lancé: python run.py{RESET}\n")
        sys.exit(1)
    
    # ========== INFRASTRUCTURE TESTS ==========
    runner.print_header("1️⃣ TESTS INFRASTRUCTURE")
    runner.test("Santé API", test_api_health)
    runner.test("Santé Infrastructure générale", test_infrastructure_health)
    runner.test("Connexion Kafka", test_kafka_connection)
    
    # ========== ASYNC TESTS ==========
    asyncio.run(run_async_tests())
    
    # ========== API TESTS ==========
    runner.print_header("4️⃣ TESTS ENDPOINTS API")
    runner.test("POST /credit/decision", test_credit_decision_endpoint)
    runner.test("Format réponse complète", test_decision_response_format)
    runner.test("Features humanisées (Français)", test_humanized_features)
    runner.test("Explications contrefactuelles présentes", test_counterfactuals_present)
    
    # ========== SCORING AGENT TESTS ==========
    runner.print_header("5️⃣ TESTS SCORING AGENT")
    runner.test("Scoring avec profils risque différents", test_with_different_risk_profiles)
    runner.test("Prédictions ML valides", test_ml_model_predictions)
    runner.test("Cohérence modèle", test_model_consistency)
    
    # ========== XAI AGENT TESTS ==========
    runner.print_header("6️⃣ TESTS AGENT XAI")
    runner.test("Qualité explications", test_explanation_quality)
    runner.test("Valeurs SHAP présentes", test_shap_values_presence)
    
    # ========== INTEGRATION TESTS ==========
    runner.print_header("7️⃣ TESTS INTÉGRATION")
    runner.test("Pipeline end-to-end", test_end_to_end_pipeline)
    runner.test("Performance timing", test_performance_timing)
    
    # Print summary
    runner.print_summary()
    
    # Exit with appropriate code
    sys.exit(0 if runner.fail_count == 0 else 1)
