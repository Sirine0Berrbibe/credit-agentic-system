#!/usr/bin/env python3
"""
Test Infrastructure Integration
Vérifie que PostgreSQL, Kafka et Redis fonctionnent correctement
"""

import asyncio
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_infrastructure():
    """Test tous les services d'infrastructure"""
    
    print("\n" + "="*80)
    print("INFRASTRUCTURE INTEGRATION TEST")
    print("="*80 + "\n")
    
    test_results: Dict[str, bool] = {
        "PostgreSQL": False,
        "Kafka": False,
        "Redis": False,
    }
    
    # Test PostgreSQL
    print("1️⃣  Testing PostgreSQL...")
    try:
        from src.infrastructure.db_client import DatabaseClient
        
        db = DatabaseClient("postgresql+asyncpg://pfe:pfe2026@localhost:5434/scoring_db")
        await db.initialize()
        
        # Test write audit log
        await db.write_audit_log(
            application_id="test-app-001",
            client_id="test-client-001",
            agent="TEST",
            action="INFRASTRUCTURE_TEST",
            details={"test": True}
        )
        
        # Test statistics
        stats = await db.get_statistics()
        logger.info(f"   ✅ PostgreSQL OK - Stats: {stats}")
        test_results["PostgreSQL"] = True
        
        await db.close()
    
    except Exception as e:
        logger.error(f"   ❌ PostgreSQL FAILED: {e}")
        test_results["PostgreSQL"] = False
    
    print()
    
    # Test Kafka
    print("2️⃣  Testing Kafka...")
    try:
        from src.infrastructure.kafka_client import KafkaEventProducer
        
        producer = KafkaEventProducer("localhost:9092")
        await producer.initialize()
        
        # Send test event
        result = await producer.send_event(
            topic="test.topic.test",
            application_id="test-app-001",
            client_id="test-client-001",
            event_type="TEST_EVENT",
            data={"test": True}
        )
        
        logger.info(f"   ✅ Kafka OK - Event sent: {result}")
        test_results["Kafka"] = True
        
        await producer.close()
    
    except Exception as e:
        logger.error(f"   ❌ Kafka FAILED: {e}")
        test_results["Kafka"] = False
    
    print()
    
    # Test Redis
    print("3️⃣  Testing Redis...")
    try:
        from src.infrastructure.redis_client import RedisClient
        
        redis = RedisClient(
            host="localhost",
            port=6379,
            password="redis_secure_pass_2026"
        )
        await redis.initialize()
        
        # Test health check
        health = await redis.health_check()
        logger.info(f"   ✅ Redis OK - Health: {health}")
        test_results["Redis"] = True
        
        # Test cache
        await redis.cache_decision(
            application_id="test-app-001",
            decision_data={"decision": "APPROVE", "test": True}
        )
        
        # Retrieve from cache
        cached = await redis.get_cached_decision("test-app-001")
        logger.info(f"   ✅ Redis Cache OK - Cached: {bool(cached)}")
        
        # Test rate limiting
        allowed = await redis.check_rate_limit("test-client-001", max_requests=5)
        logger.info(f"   ✅ Redis Rate Limiting OK - Allowed: {allowed}")
        
        await redis.close()
    
    except Exception as e:
        logger.error(f"   ❌ Redis FAILED: {e}")
        test_results["Redis"] = False
    
    print()
    
    # Summary
    print("="*80)
    print("TEST RESULTS")
    print("="*80)
    
    for service, passed in test_results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{service:.<40} {status}")
    
    print()
    
    all_passed = all(test_results.values())
    
    if all_passed:
        print("✅ ALL INFRASTRUCTURE TESTS PASSED!")
        print("\nYou can now start the Orchestrator service:")
        print("  cd credit_agents/orchestrator")
        print("  python run.py")
    else:
        print("❌ SOME TESTS FAILED")
        print("\nPlease check:")
        print("  1. Docker services are running: docker-compose ps")
        print("  2. PostgreSQL is accessible on localhost:5434")
        print("  3. Kafka is accessible on localhost:9092")
        print("  4. Redis is accessible on localhost:6379")
    
    print()
    print("="*80)
    
    return all_passed


if __name__ == "__main__":
    result = asyncio.run(test_infrastructure())
    exit(0 if result else 1)
