"""
Redis Client — Caching & Session Storage
Gère le cache et les sessions
"""

import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

import redis.asyncio as redis
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RedisClient:
    """Client Redis pour cache et session store"""
    
    # Clés Redis patterns
    PREFIX_DECISION = "decision:"
    PREFIX_FEATURES = "features:"
    PREFIX_SESSION = "session:"
    PREFIX_APPLICATION = "app:"
    PREFIX_CACHE = "cache:"
    
    def __init__(self, host: str = "localhost", port: int = 6379, password: Optional[str] = None):
        """
        Args:
            host: Adresse Redis
            port: Port Redis
            password: Mot de passe Redis
        """
        self.host = host
        self.port = port
        self.password = password
        self.redis: Optional[Redis] = None
    
    async def initialize(self):
        """Initialise la connexion Redis"""
        try:
            self.redis = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                socket_keepalive_options={
                    1: 3,  # TCP_KEEPIDLE
                    2: 3,  # TCP_KEEPINTVL
                    3: 3,  # TCP_KEEPCNT
                },
            )
            
            # Test connection
            await self.redis.ping()
            
            logger.info(f"✓ Redis Client initialized: redis://{self.host}:{self.port}")
            return True
        
        except Exception as e:
            logger.error(f"Redis initialization failed: {e}")
            raise
    
    def _serialize(self, obj: Any) -> str:
        """Sérialise un objet en JSON"""
        return json.dumps(obj, default=str)
    
    def _deserialize(self, data: str) -> Any:
        """Désérialise un JSON"""
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data
    
    # ────────────────────────────────────────────────────────────────
    # DECISION CACHING
    # ────────────────────────────────────────────────────────────────
    
    async def cache_decision(
        self,
        application_id: str,
        decision_data: Dict[str, Any],
        ttl_minutes: int = 60,
    ) -> bool:
        """Cache une décision"""
        
        try:
            key = f"{self.PREFIX_DECISION}{application_id}"
            value = self._serialize(decision_data)
            
            await self.redis.setex(
                key,
                timedelta(minutes=ttl_minutes),
                value,
            )
            
            logger.debug(f"[REDIS] Cached decision: {application_id} (TTL: {ttl_minutes}m)")
            return True
        
        except Exception as e:
            logger.warning(f"Decision cache failed: {e}")
            return False
    
    async def get_cached_decision(self, application_id: str) -> Optional[Dict[str, Any]]:
        """Récupère une décision en cache"""
        
        try:
            key = f"{self.PREFIX_DECISION}{application_id}"
            data = await self.redis.get(key)
            
            if not data:
                return None
            
            return self._deserialize(data)
        
        except Exception as e:
            logger.warning(f"Decision cache get failed: {e}")
            return None
    
    async def invalidate_decision(self, application_id: str) -> bool:
        """Invalide le cache d'une décision"""
        
        try:
            key = f"{self.PREFIX_DECISION}{application_id}"
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Decision cache invalidation failed: {e}")
            return False
    
    # ────────────────────────────────────────────────────────────────
    # FEATURE CACHING
    # ────────────────────────────────────────────────────────────────
    
    async def cache_features(
        self,
        client_id: str,
        features: Dict[str, Any],
        ttl_hours: int = 24,
    ) -> bool:
        """Cache les features d'un client"""
        
        try:
            key = f"{self.PREFIX_FEATURES}{client_id}"
            value = self._serialize(features)
            
            await self.redis.setex(
                key,
                timedelta(hours=ttl_hours),
                value,
            )
            
            logger.debug(f"[REDIS] Cached features: {client_id} ({len(features)} keys)")
            return True
        
        except Exception as e:
            logger.warning(f"Features cache failed: {e}")
            return False
    
    async def get_cached_features(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Récupère les features en cache"""
        
        try:
            key = f"{self.PREFIX_FEATURES}{client_id}"
            data = await self.redis.get(key)
            
            if not data:
                return None
            
            return self._deserialize(data)
        
        except Exception as e:
            logger.warning(f"Features cache get failed: {e}")
            return None
    
    # ────────────────────────────────────────────────────────────────
    # SESSION MANAGEMENT
    # ────────────────────────────────────────────────────────────────
    
    async def create_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_hours: int = 24,
    ) -> bool:
        """Crée une session utilisateur"""
        
        try:
            key = f"{self.PREFIX_SESSION}{session_id}"
            session_data = {
                "user_id": user_id,
                "created_at": datetime.utcnow().isoformat(),
                "metadata": metadata or {},
            }
            
            await self.redis.setex(
                key,
                timedelta(hours=ttl_hours),
                self._serialize(session_data),
            )
            
            logger.debug(f"[REDIS] Session created: {session_id}")
            return True
        
        except Exception as e:
            logger.warning(f"Session creation failed: {e}")
            return False
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Récupère une session"""
        
        try:
            key = f"{self.PREFIX_SESSION}{session_id}"
            data = await self.redis.get(key)
            
            if not data:
                return None
            
            return self._deserialize(data)
        
        except Exception as e:
            logger.warning(f"Session get failed: {e}")
            return None
    
    async def delete_session(self, session_id: str) -> bool:
        """Supprime une session"""
        
        try:
            key = f"{self.PREFIX_SESSION}{session_id}"
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Session deletion failed: {e}")
            return False
    
    # ────────────────────────────────────────────────────────────────
    # RATE LIMITING
    # ────────────────────────────────────────────────────────────────
    
    async def check_rate_limit(
        self,
        client_id: str,
        max_requests: int = 10,
        window_seconds: int = 60,
    ) -> bool:
        """
        Vérifie le rate limiting (sliding window)
        Retourne True si la requête est autorisée
        """
        
        try:
            key = f"ratelimit:{client_id}"
            current = await self.redis.incr(key)
            
            if current == 1:
                await self.redis.expire(key, window_seconds)
            
            return current <= max_requests
        
        except Exception as e:
            logger.warning(f"Rate limit check failed: {e}")
            return True  # Autoriser si Redis est down
    
    async def get_rate_limit_status(
        self,
        client_id: str,
        max_requests: int = 10,
    ) -> Dict[str, int]:
        """Retourne le statut du rate limiting"""
        
        try:
            key = f"ratelimit:{client_id}"
            current = await self.redis.get(key)
            current = int(current) if current else 0
            
            return {
                "requests_used": current,
                "requests_remaining": max(0, max_requests - current),
                "requests_limit": max_requests,
            }
        
        except Exception as e:
            logger.warning(f"Rate limit status failed: {e}")
            return {}
    
    # ────────────────────────────────────────────────────────────────
    # METRICS & ANALYTICS
    # ────────────────────────────────────────────────────────────────
    
    async def increment_metric(self, metric_name: str, value: int = 1) -> bool:
        """Incrémente une métrique"""
        
        try:
            key = f"metric:{metric_name}"
            await self.redis.incrby(key, value)
            await self.redis.expire(key, 86400)  # 24h TTL
            return True
        except Exception as e:
            logger.warning(f"Metric increment failed: {e}")
            return False
    
    async def get_metrics(self, pattern: str = "*") -> Dict[str, int]:
        """Récupère les métriques"""
        
        try:
            metrics = {}
            keys = await self.redis.keys(f"metric:{pattern}")
            
            for key in keys:
                value = await self.redis.get(key)
                metric_name = key.replace("metric:", "")
                metrics[metric_name] = int(value) if value else 0
            
            return metrics
        
        except Exception as e:
            logger.warning(f"Metrics get failed: {e}")
            return {}
    
    # ────────────────────────────────────────────────────────────────
    # UTILITY
    # ────────────────────────────────────────────────────────────────
    
    async def health_check(self) -> bool:
        """Vérifie la santé de Redis"""
        
        try:
            result = await self.redis.ping()
            return result == True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
    
    async def get_stats(self) -> Dict[str, Any]:
        """Récupère les stats Redis"""
        
        try:
            info = await self.redis.info()
            return {
                "connected_clients": info.get("connected_clients"),
                "used_memory_mb": info.get("used_memory", 0) / 1024 / 1024,
                "total_commands_processed": info.get("total_commands_processed"),
                "keyspace_hits": info.get("keyspace_hits"),
                "keyspace_misses": info.get("keyspace_misses"),
            }
        except Exception as e:
            logger.warning(f"Stats fetch failed: {e}")
            return {}
    
    async def close(self):
        """Ferme la connexion Redis"""
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")
