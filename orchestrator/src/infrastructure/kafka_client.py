"""
Kafka Producer & Consumer — Event Streaming
Gère l'événementiel temps réel pour le frontend WebSocket
"""

import logging
import json
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

logger = logging.getLogger(__name__)


class KafkaEventProducer:
    """Producteur Kafka pour événements métier"""
    
    # Topics d'événements
    TOPIC_APPLICATION_STARTED = "credit.application.started"
    TOPIC_DOCUMENTS_REVIEW_REQUIRED = "credit.documents.review_required"
    TOPIC_GUARANTEE_COMPLETE = "credit.guarantee.complete"
    TOPIC_SCORING_COMPLETE = "credit.scoring.complete"
    TOPIC_DECISION_MADE = "credit.decision.made"
    TOPIC_FRAUD_DETECTED = "credit.fraud.detected"
    TOPIC_EXPLANATION_GENERATED = "credit.explanation.generated"
    
    def __init__(self, bootstrap_servers: str = "localhost:9092"):
        """
        Args:
            bootstrap_servers: "host1:9092,host2:9092"
        """
        self.bootstrap_servers = bootstrap_servers
        self.producer: Optional[AIOKafkaProducer] = None
    
    async def initialize(self):
        """Initialise le producteur"""
        try:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=self._serialize_json,
            )
            await self.producer.start()
            logger.info(f"✓ Kafka Producer initialized: {self.bootstrap_servers}")
        except Exception as e:
            logger.error(f"Kafka Producer initialization failed: {e}")
            raise
    
    @staticmethod
    def _serialize_json(value: Dict[str, Any]) -> bytes:
        """Sérialise un dict en JSON"""
        return json.dumps(value, default=str).encode("utf-8")
    
    async def send_event(
        self,
        topic: str,
        application_id: str,
        event_type: str,
        data: Dict[str, Any],
        client_id: Optional[str] = None,
    ) -> bool:
        """Envoie un événement"""
        
        try:
            event_payload = {
                "timestamp": datetime.utcnow().isoformat(),
                "application_id": application_id,
                "client_id": client_id,
                "event_type": event_type,
                "data": data,
            }
            
            await self.producer.send_and_wait(
                topic,
                value=event_payload,
                key=application_id.encode("utf-8"),
            )
            
            logger.debug(f"[KAFKA] Event sent: {topic}/{event_type} ({application_id})")
            return True
        
        except Exception as e:
            logger.error(f"Kafka send failed: {e}")
            return False
    
    async def application_started(
        self,
        application_id: str,
        client_id: str,
        client_data: Dict[str, Any],
    ):
        """Événement: Application démarrée"""
        return await self.send_event(
            self.TOPIC_APPLICATION_STARTED,
            application_id=application_id,
            client_id=client_id,
            event_type="APPLICATION_STARTED",
            data={
                "client_id": client_id,
                "data_keys": list(client_data.keys()),
            },
        )
    
    async def scoring_complete(
        self,
        application_id: str,
        client_id: str,
        pd_score: float,
        risk_band: str,
        iterations: int,
    ):
        """Événement: Scoring complété"""
        return await self.send_event(
            self.TOPIC_SCORING_COMPLETE,
            application_id=application_id,
            client_id=client_id,
            event_type="SCORING_COMPLETE",
            data={
                "pd_score": pd_score,
                "risk_band": risk_band,
                "scoring_iterations": iterations,
            },
        )
    
    async def decision_made(
        self,
        application_id: str,
        client_id: str,
        decision: str,
        pd_score: float,
    ):
        """Événement: Décision prise"""
        return await self.send_event(
            self.TOPIC_DECISION_MADE,
            application_id=application_id,
            client_id=client_id,
            event_type="DECISION_MADE",
            data={
                "decision": decision,
                "pd_score": pd_score,
            },
        )
    
    async def fraud_detected(
        self,
        application_id: str,
        client_id: str,
        fraud_risk_score: float,
        anomalies: list,
    ):
        """Événement: Fraude détectée"""
        return await self.send_event(
            self.TOPIC_FRAUD_DETECTED,
            application_id=application_id,
            client_id=client_id,
            event_type="FRAUD_DETECTED",
            data={
                "fraud_risk_score": fraud_risk_score,
                "anomalies_count": len(anomalies),
            },
        )
    
    async def explanation_generated(
        self,
        application_id: str,
        client_id: str,
        top_factors_count: int,
        counterfactuals_count: int,
    ):
        """Événement: Explication générée"""
        return await self.send_event(
            self.TOPIC_EXPLANATION_GENERATED,
            application_id=application_id,
            client_id=client_id,
            event_type="EXPLANATION_GENERATED",
            data={
                "top_factors_count": top_factors_count,
                "counterfactuals_count": counterfactuals_count,
            },
        )
    
    async def close(self):
        """Ferme le producteur"""
        if self.producer:
            await self.producer.stop()
            logger.info("Kafka Producer closed")


class KafkaEventConsumer:
    """Consommateur Kafka pour WebSocket"""
    
    def __init__(self, bootstrap_servers: str = "localhost:9092"):
        self.bootstrap_servers = bootstrap_servers
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.topics = [
            KafkaEventProducer.TOPIC_APPLICATION_STARTED,
            KafkaEventProducer.TOPIC_DOCUMENTS_REVIEW_REQUIRED,
            KafkaEventProducer.TOPIC_GUARANTEE_COMPLETE,
            KafkaEventProducer.TOPIC_SCORING_COMPLETE,
            KafkaEventProducer.TOPIC_DECISION_MADE,
            KafkaEventProducer.TOPIC_FRAUD_DETECTED,
            KafkaEventProducer.TOPIC_EXPLANATION_GENERATED,
        ]
    
    async def initialize(self, group_id: str = "aicredits-orchestrator"):
        """Initialise le consommateur"""
        try:
            self.consumer = AIOKafkaConsumer(
                *self.topics,
                bootstrap_servers=self.bootstrap_servers,
                group_id=group_id,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                auto_offset_reset="latest",
                enable_auto_commit=True,
            )
            await self.consumer.start()
            logger.info(f"✓ Kafka Consumer initialized: {self.bootstrap_servers}")
        except Exception as e:
            logger.error(f"Kafka Consumer initialization failed: {e}")
            raise
    
    async def consume_events(
        self,
        callback: Callable[[str, Dict[str, Any]], None],
    ):
        """Consomme les événements (boucle infinie)"""
        try:
            async for msg in self.consumer:
                try:
                    event = msg.value
                    await callback(msg.topic, event)
                except Exception as e:
                    logger.error(f"Event processing failed: {e}")
        
        except Exception as e:
            logger.error(f"Kafka consumption error: {e}")
    
    async def close(self):
        """Ferme le consommateur"""
        if self.consumer:
            await self.consumer.stop()
            logger.info("Kafka Consumer closed")


# Convenience functions
async def emit_event(
    producer: KafkaEventProducer,
    topic: str,
    application_id: str,
    event_type: str,
    data: Dict[str, Any],
    client_id: Optional[str] = None,
) -> bool:
    """Helper pour émettre un événement"""
    return await producer.send_event(
        topic=topic,
        application_id=application_id,
        event_type=event_type,
        data=data,
        client_id=client_id,
    )
