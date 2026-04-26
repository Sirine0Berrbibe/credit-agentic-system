"""
Database client - PostgreSQL integration for orchestrator shared data.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    timestamp = sa.Column(sa.DateTime, nullable=False, default=datetime.utcnow)
    application_id = sa.Column(sa.UUID, nullable=False, index=True)
    client_id = sa.Column(sa.String(255), nullable=False, index=True)
    agent = sa.Column(sa.String(50), nullable=False)
    action = sa.Column(sa.String(255), nullable=False)
    details = sa.Column(sa.JSON, nullable=True)
    user_ip = sa.Column(sa.String(50), nullable=True)
    created_at = sa.Column(sa.DateTime, nullable=False, default=datetime.utcnow)


class ApplicationDecisionModel(Base):
    __tablename__ = "credit_decisions"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    application_id = sa.Column(sa.UUID, nullable=False, unique=True, index=True)
    client_id = sa.Column(sa.String(255), nullable=False, index=True)
    decision = sa.Column(sa.String(50), nullable=False)
    final_pd_score = sa.Column(sa.Float, nullable=False)
    pd_confidence = sa.Column(sa.Float, nullable=False)
    risk_band = sa.Column(sa.String(50), nullable=False)
    top_factors = sa.Column(sa.JSON, nullable=True)
    counterfactuals = sa.Column(sa.JSON, nullable=True)
    explanation = sa.Column(sa.Text, nullable=True)
    fraud_risk_score = sa.Column(sa.Float, nullable=True)
    processing_time_ms = sa.Column(sa.Float, nullable=True)
    created_at = sa.Column(sa.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = sa.Column(
        sa.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class FeatureStoreModel(Base):
    __tablename__ = "feature_cache"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    client_id = sa.Column(sa.String(255), nullable=False, unique=True, index=True)
    features = sa.Column(sa.JSON, nullable=False)
    last_updated = sa.Column(sa.DateTime, nullable=False, default=datetime.utcnow)
    source = sa.Column(sa.String(50), nullable=True)
    expires_at = sa.Column(sa.DateTime, nullable=True)


class ApplicationStateSnapshotModel(Base):
    __tablename__ = "application_state_snapshots"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    application_id = sa.Column(sa.String(64), nullable=False, index=True)
    client_id = sa.Column(sa.String(255), nullable=False, index=True)
    stage = sa.Column(sa.String(64), nullable=False, index=True)
    payload = sa.Column(sa.JSON, nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, default=datetime.utcnow)


class AgentHandoffModel(Base):
    __tablename__ = "agent_handoffs"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    application_id = sa.Column(sa.String(64), nullable=False, index=True)
    client_id = sa.Column(sa.String(255), nullable=False, index=True)
    source_agent = sa.Column(sa.String(64), nullable=False, index=True)
    target_agent = sa.Column(sa.String(64), nullable=False, index=True)
    handoff_type = sa.Column(sa.String(64), nullable=False, index=True)
    status = sa.Column(sa.String(64), nullable=False)
    payload = sa.Column(sa.JSON, nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, default=datetime.utcnow)


class DatabaseClient:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None
        self.session_factory = None

    async def initialize(self):
        try:
            self.engine = create_async_engine(
                self.database_url,
                echo=False,
                pool_size=20,
                max_overflow=10,
                pool_pre_ping=True,
            )

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            self.session_factory = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            logger.info(
                "Database initialized: %s",
                self.database_url.split("@")[1] if "@" in self.database_url else "local",
            )
        except Exception as exc:
            logger.error("Database initialization failed: %s", exc)
            raise

    @asynccontextmanager
    async def get_session(self):
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def write_audit_log(
        self,
        application_id: str,
        client_id: str,
        agent: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        user_ip: Optional[str] = None,
    ) -> bool:
        try:
            async with self.get_session() as session:
                session.add(
                    AuditLogModel(
                        application_id=application_id,
                        client_id=client_id,
                        agent=agent,
                        action=action,
                        details=details or {},
                        user_ip=user_ip,
                    )
                )
                await session.commit()
            return True
        except Exception as exc:
            logger.error("Audit log write failed: %s", exc)
            return False

    async def save_application_state(
        self,
        application_id: str,
        client_id: str,
        stage: str,
        payload: Dict[str, Any],
    ) -> bool:
        try:
            async with self.get_session() as session:
                session.add(
                    ApplicationStateSnapshotModel(
                        application_id=application_id,
                        client_id=client_id,
                        stage=stage,
                        payload=payload,
                    )
                )
                await session.commit()
            logger.debug("[DB] Saved application snapshot %s/%s", application_id, stage)
            return True
        except Exception as exc:
            logger.error("Application snapshot save failed: %s", exc)
            return False

    async def save_agent_handoff(
        self,
        application_id: str,
        client_id: str,
        source_agent: str,
        target_agent: str,
        handoff_type: str,
        status: str,
        payload: Dict[str, Any],
    ) -> bool:
        try:
            async with self.get_session() as session:
                session.add(
                    AgentHandoffModel(
                        application_id=application_id,
                        client_id=client_id,
                        source_agent=source_agent,
                        target_agent=target_agent,
                        handoff_type=handoff_type,
                        status=status,
                        payload=payload,
                    )
                )
                await session.commit()
            logger.debug(
                "[DB] Saved handoff %s -> %s for %s",
                source_agent,
                target_agent,
                application_id,
            )
            return True
        except Exception as exc:
            logger.error("Agent handoff save failed: %s", exc)
            return False

    async def save_decision(
        self,
        application_id: str,
        client_id: str,
        decision: str,
        final_pd_score: float,
        pd_confidence: float,
        risk_band: str,
        top_factors: List[Dict],
        counterfactuals: List[Dict],
        explanation: str,
        fraud_risk_score: Optional[float] = None,
        processing_time_ms: Optional[float] = None,
    ) -> bool:
        try:
            async with self.get_session() as session:
                await session.execute(
                    sa.delete(ApplicationDecisionModel).where(
                        ApplicationDecisionModel.application_id == application_id
                    )
                )
                session.add(
                    ApplicationDecisionModel(
                        application_id=application_id,
                        client_id=client_id,
                        decision=decision,
                        final_pd_score=final_pd_score,
                        pd_confidence=pd_confidence,
                        risk_band=risk_band,
                        top_factors=top_factors,
                        counterfactuals=counterfactuals,
                        explanation=explanation,
                        fraud_risk_score=fraud_risk_score,
                        processing_time_ms=processing_time_ms,
                    )
                )
                await session.commit()
            logger.info("[DB] Saved decision: %s -> %s", application_id, decision)
            return True
        except Exception as exc:
            logger.error("Decision save failed: %s", exc)
            return False

    async def get_decision(self, application_id: str) -> Optional[Dict[str, Any]]:
        try:
            async with self.get_session() as session:
                stmt = sa.select(ApplicationDecisionModel).where(
                    ApplicationDecisionModel.application_id == application_id
                )
                result = await session.execute(stmt)
                record = result.scalars().first()

                if not record:
                    return None

                return {
                    "application_id": str(record.application_id),
                    "client_id": record.client_id,
                    "decision": record.decision,
                    "final_pd_score": record.final_pd_score,
                    "pd_confidence": record.pd_confidence,
                    "risk_band": record.risk_band,
                    "explanation": record.explanation,
                    "created_at": record.created_at.isoformat(),
                }
        except Exception as exc:
            logger.warning("Decision fetch failed: %s", exc)
            return None

    async def get_client_history(self, client_id: str, limit: int = 10) -> List[Dict]:
        try:
            async with self.get_session() as session:
                stmt = (
                    sa.select(ApplicationDecisionModel)
                    .where(ApplicationDecisionModel.client_id == client_id)
                    .order_by(ApplicationDecisionModel.created_at.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                records = result.scalars().all()

                return [
                    {
                        "application_id": str(record.application_id),
                        "decision": record.decision,
                        "pd_score": record.final_pd_score,
                        "created_at": record.created_at.isoformat(),
                    }
                    for record in records
                ]
        except Exception as exc:
            logger.warning("History fetch failed: %s", exc)
            return []

    async def save_features(
        self,
        client_id: str,
        features: Dict[str, Any],
        source: str = "API",
        ttl_hours: int = 24,
    ) -> bool:
        try:
            async with self.get_session() as session:
                await session.execute(
                    sa.delete(FeatureStoreModel).where(
                        FeatureStoreModel.client_id == client_id
                    )
                )
                session.add(
                    FeatureStoreModel(
                        client_id=client_id,
                        features=features,
                        source=source,
                        expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
                    )
                )
                await session.commit()
            logger.debug("[FeatureStore] Saved %s features for %s", len(features), client_id)
            return True
        except Exception as exc:
            logger.warning("Feature save failed: %s", exc)
            return False

    async def get_features(self, client_id: str) -> Optional[Dict[str, Any]]:
        try:
            async with self.get_session() as session:
                stmt = sa.select(FeatureStoreModel).where(
                    FeatureStoreModel.client_id == client_id,
                    FeatureStoreModel.expires_at > datetime.utcnow(),
                )
                result = await session.execute(stmt)
                record = result.scalars().first()
                return record.features if record else None
        except Exception as exc:
            logger.warning("Feature fetch failed: %s", exc)
            return None

    async def get_statistics(self) -> Dict[str, Any]:
        try:
            async with self.get_session() as session:
                total_stmt = sa.select(sa.func.count()).select_from(ApplicationDecisionModel)
                approval_stmt = (
                    sa.select(sa.func.count())
                    .select_from(ApplicationDecisionModel)
                    .where(ApplicationDecisionModel.decision == "APPROVE")
                )
                snapshot_stmt = sa.select(sa.func.count()).select_from(
                    ApplicationStateSnapshotModel
                )
                handoff_stmt = sa.select(sa.func.count()).select_from(AgentHandoffModel)

                total_count = (await session.execute(total_stmt)).scalar() or 0
                approval_count = (await session.execute(approval_stmt)).scalar() or 0
                snapshot_count = (await session.execute(snapshot_stmt)).scalar() or 0
                handoff_count = (await session.execute(handoff_stmt)).scalar() or 0

                approval_rate = (approval_count / total_count * 100) if total_count > 0 else 0

                return {
                    "total_decisions": total_count,
                    "approvals": approval_count,
                    "approval_rate_pct": round(approval_rate, 2),
                    "application_snapshots": snapshot_count,
                    "agent_handoffs": handoff_count,
                }
        except Exception as exc:
            logger.warning("Statistics fetch failed: %s", exc)
            return {}

    async def close(self):
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connection closed")
