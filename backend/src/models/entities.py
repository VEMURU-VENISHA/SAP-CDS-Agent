"""SQLAlchemy ORM Entities for persisted domain data."""

from sqlalchemy import Boolean, Float, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base, AuditMixin


class RequirementEntity(Base, AuditMixin):
    """Stores business requirements submitted to the platform."""

    __tablename__ = "requirements"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    business_domain: Mapped[str] = mapped_column(String(100), default="Sales & Distribution")
    target_use_case: Mapped[str] = mapped_column(String(50), default="ANALYTICAL_REPORT")
    required_entities: Mapped[dict] = mapped_column(JSON, default=list)
    required_fields: Mapped[dict] = mapped_column(JSON, default=list)
    filter_criteria: Mapped[dict] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(50), default="SUBMITTED")


class DecisionEntity(Base, AuditMixin):
    """Stores architectural decisions (REUSE, EXTEND, CREATE) with audit trail."""

    __tablename__ = "decisions"

    requirement_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # REUSE, EXTEND, CREATE
    recommended_view: Mapped[str] = mapped_column(String(100), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    fit_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    missing_fields: Mapped[dict] = mapped_column(JSON, default=list)
    tradeoffs: Mapped[dict] = mapped_column(JSON, default=list)
    human_approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str] = mapped_column(String(100), nullable=True)


class AuditLogEntity(Base, AuditMixin):
    """Immutable audit trail for all governance events, agent executions, and approvals."""

    __tablename__ = "audit_logs"

    event_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str] = mapped_column(String(50), nullable=True)
