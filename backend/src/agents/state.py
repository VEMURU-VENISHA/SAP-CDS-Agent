"""Shared Workflow State for LangGraph Multi-Agent Orchestration."""

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict
from src.models.domain import (
    BusinessRequirement,
    CDSCandidate,
    DataModel,
    Decision,
    DeploymentRequest,
    FieldMapping,
    ValidationResult,
)


class CDSWorkflowState(TypedDict, total=False):
    """Encapsulates the complete lifecycle state flowing through the CDS Agent Graph."""

    # 1. Input Stage
    requirement: Optional[BusinessRequirement]

    # 2. Discovery & Mapping Stage
    candidates: List[CDSCandidate]
    field_mappings: List[FieldMapping]

    # 3. Decision Stage
    decision: Optional[Decision]

    # 4. Modeling & Generation Stage (EXTEND or CREATE)
    data_model: Optional[DataModel]
    generated_cds_code: Optional[str]

    # 5. Validation Stage
    validation_result: Optional[ValidationResult]

    # 6. Governance & Deployment Stage
    deployment_request: Optional[DeploymentRequest]
    is_human_approved: bool

    # 7. Audit & Pipeline Execution Metadata
    audit_logs: List[Dict[str, Any]]
    errors: List[str]
    current_step: str
