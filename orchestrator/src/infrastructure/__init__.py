"""
Infrastructure Manager — Intégration centralisée
Gère PostgreSQL, Kafka, Redis
"""

import logging
import os
from typing import Optional

from src.infrastructure.db_client import DatabaseClient
from src.infrastructure.kafka_client import KafkaEventProducer, KafkaEventConsumer
from src.infrastructure.redis_client import RedisClient

logger = logging.getLogger(__name__)


class InfrastructureManager:
    """Gestionnaire centralisé d'infrastructure"""
    
    def __init__(
        self,
        postgres_url: Optional[str] = None,
        kafka_bootstrap: Optional[str] = None,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
        redis_password: Optional[str] = None,
    ):
        # Configuration par défaut depuis env
        self.postgres_url = postgres_url or os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://pfe:pfe2026@localhost:5434/scoring_db"
        )
        
        self.kafka_bootstrap = kafka_bootstrap or os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS",
            "localhost:9092"
        )
        
        self.redis_host = redis_host or os.getenv("REDIS_HOST", "localhost")
        self.redis_port = redis_port or int(os.getenv("REDIS_PORT", "6379"))
        self.redis_password = redis_password or os.getenv("REDIS_PASSWORD", "redis_secure_pass_2026")
        
        # Clients
        self.db_client: Optional[DatabaseClient] = None
        self.kafka_producer: Optional[KafkaEventProducer] = None
        self.kafka_consumer: Optional[KafkaEventConsumer] = None
        self.redis_client: Optional[RedisClient] = None
        
        self._initialized = False
    
    async def initialize(self, init_kafka: bool = True, init_consumer: bool = False):
        """
        Initialise l'infrastructure
        
        Args:
            init_kafka: Initialiser le producteur Kafka
            init_consumer: Initialiser le consommateur Kafka
        """
        
        try:
            # PostgreSQL
            self.db_client = DatabaseClient(self.postgres_url)
            await self.db_client.initialize()
            
            # Redis
            self.redis_client = RedisClient(
                host=self.redis_host,
                port=self.redis_port,
                password=self.redis_password,
            )
            await self.redis_client.initialize()
            
            # Kafka Producer
            if init_kafka:
                self.kafka_producer = KafkaEventProducer(self.kafka_bootstrap)
                await self.kafka_producer.initialize()
            
            # Kafka Consumer (optionnel)
            if init_consumer:
                self.kafka_consumer = KafkaEventConsumer(self.kafka_bootstrap)
                await self.kafka_consumer.initialize()
            
            self._initialized = True
            logger.info("✓ Infrastructure Manager initialized")
            
            return True
        
        except Exception as e:
            logger.error(f"Infrastructure initialization failed: {e}")
            raise
    
    async def health_check(self) -> dict:
        """Vérifie la santé de tous les services"""
        
        health = {
            "status": "healthy",
            "timestamp": str(None),
            "services": {},
        }
        
        # PostgreSQL
        try:
            stats = await self.db_client.get_statistics()
            health["services"]["postgresql"] = {
                "status": "healthy",
                "stats": stats,
            }
        except Exception as e:
            health["services"]["postgresql"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            health["status"] = "degraded"
        
        # Redis
        try:
            redis_health = await self.redis_client.health_check()
            redis_stats = await self.redis_client.get_stats()
            health["services"]["redis"] = {
                "status": "healthy" if redis_health else "unhealthy",
                "stats": redis_stats,
            }
        except Exception as e:
            health["services"]["redis"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            health["status"] = "degraded"
        
        # Kafka
        if self.kafka_producer:
            # Kafka health check is implicit (init succeeded)
            health["services"]["kafka"] = {
                "status": "healthy",
            }
        
        return health
    
    async def close(self):
        """Ferme tous les clients"""
        
        try:
            if self.db_client:
                await self.db_client.close()
            
            if self.redis_client:
                await self.redis_client.close()
            
            if self.kafka_producer:
                await self.kafka_producer.close()
            
            if self.kafka_consumer:
                await self.kafka_consumer.close()
            
            self._initialized = False
            logger.info("✓ Infrastructure Manager closed")
        
        except Exception as e:
            logger.error(f"Infrastructure shutdown failed: {e}")


# Singleton global
_infra_manager: Optional[InfrastructureManager] = None


async def get_infra_manager(
    force_init: bool = False,
) -> InfrastructureManager:
    """Obtient le gestionnaire d'infrastructure (singleton)"""
    
    global _infra_manager
    
    if _infra_manager is None:
        _infra_manager = InfrastructureManager()
        await _infra_manager.initialize()
    
    return _infra_manager


async def shutdown_infra():
    """Arrête l'infrastructure"""
    
    global _infra_manager
    
    if _infra_manager:
        await _infra_manager.close()
        _infra_manager = None
