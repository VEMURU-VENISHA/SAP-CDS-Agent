"""Enterprise Domain Models for SAP CDS Intelligence & Automation Platform.

Contains core Pydantic domain models:
- BusinessRequirement
- CDSCandidate
- FieldMapping
- Decision
- DataModel
- ValidationResult
- DeploymentRequest
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ==============================================================================
# 1. Enums
# ==============================================================================

class TargetUseCase(str, Enum):
    ANALYTICAL_REPORT = "ANALYTICAL_REPORT"
    TRANSACTIONAL_APP = "TRANSACTIONAL_APP"
    INTEGRATION_API = "INTEGRATION_API"
    DATA_EXTRACTION = "DATA_EXTRACTION"
    SEARCH_MODEL = "SEARCH_MODEL"


class CDSLayer(str, Enum):
    BASIC = "BASIC"                  # Core interface view directly on tables (I_*)
    COMPOSITE = "COMPOSITE"          # Joins/unions across multiple interface views (I_*)
    CONSUMPTION = "CONSUMPTION"      # High-level consumption / analytical query (C_*)
    EXTENSION = "EXTENSION"          # CDS view entity extension (E_*)


class MappingType(str, Enum):
    DIRECT_MATCH = "DIRECT_MATCH"
    ASSOCIATION_HOP = "ASSOCIATION_HOP"
    CALCULATED = "CALCULATED"
    UNRESOLVED = "UNRESOLVED"
    MISSING = "MISSING"


class EvidenceLevel(str, Enum):
    LEVEL_1_EXACT_FIELD = "LEVEL_1_EXACT_FIELD"
    LEVEL_2_LABEL_MATCH = "LEVEL_2_LABEL_MATCH"
    LEVEL_3_VERIFIED_ASSOCIATION = "LEVEL_3_VERIFIED_ASSOCIATION"
    LEVEL_4_HEURISTIC_SYNONYM = "LEVEL_4_HEURISTIC_SYNONYM"
    LEVEL_5_UNVERIFIED_SUGGESTION = "LEVEL_5_UNVERIFIED_SUGGESTION"
    LEVEL_6_MISSING = "LEVEL_6_MISSING"


class DecisionAction(str, Enum):
    REUSE = "REUSE"                          # Standard SAP CDS view satisfies 100% of concepts
    EXTEND = "EXTEND"                        # Missing concepts verified obtainable via extension
    CREATE = "CREATE"                        # Custom CDS required or 0 suitable views
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"  # Ambiguous/incomplete metadata halts decision



class DeploymentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DRAFT_CREATED = "DRAFT_CREATED"
    ACTIVATED = "ACTIVATED"
    FAILED = "FAILED"


# ==============================================================================
# 2. Domain Models
# ==============================================================================

class BusinessRequirement(BaseModel):
    """Encapsulates a user business requirement with semantic extraction."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique requirement ID")
    title: str = Field(..., min_length=3, max_length=200, description="Concise requirement title")
    description: str = Field(..., min_length=10, description="Raw natural language requirement statement")
    business_domain: str = Field(default="Sales & Distribution", description="SAP business functional domain")
    target_use_case: TargetUseCase = Field(
        default=TargetUseCase.ANALYTICAL_REPORT,
        description="Intended architectural use-case",
    )
    required_entities: List[str] = Field(default_factory=list, description="Target business entities (e.g., SalesOrder, Product)")
    required_fields: List[str] = Field(default_factory=list, description="Requested business fields or attributes")
    filter_criteria: List[str] = Field(default_factory=list, description="Requested filter conditions or where clauses")
    granularity: Optional[str] = Field(default=None, description="Data grain or aggregation level (e.g., Item, Header)")
    submitted_by: str = Field(default="system_user", description="Author or requester identifier")
    created_at: datetime = Field(default_factory=utc_now)


class CDSCandidate(BaseModel):
    """Represents a discovered SAP CDS view candidate evaluated for reuse or extension."""

    view_name: str = Field(..., description="Technical CDS view entity name (e.g., I_SalesOrderAnalytics)")
    sql_view_name: Optional[str] = Field(default=None, description="Classic SQL view name if applicable")
    description: str = Field(..., description="Business text or description from SAP data dictionary")
    layer: CDSLayer = Field(default=CDSLayer.BASIC, description="VDM architectural layer")
    release_status: str = Field(default="RELEASED", description="SAP release status (RELEASED, DEPRECATED, INTERNAL)")
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Semantic match relevance score (0-1)")
    source_tables: List[str] = Field(default_factory=list, description="Underlying database tables (e.g., VBAK, VBAP)")
    associations: List[str] = Field(default_factory=list, description="Exposed associations to other views")
    available_fields: List[str] = Field(default_factory=list, description="Key and data elements available in the candidate")
    key_fields: List[str] = Field(default_factory=list, description="Primary key fields")
    is_extendable: bool = Field(default=True, description="Whether the CDS view entity supports extension")


class StructuredRequirement(BaseModel):
    """Fine-grained semantic representation of user requirements."""

    dimensions: List[str] = Field(default_factory=list, description="Business dimensions (e.g. SalesOrder, Customer)")
    measures: List[str] = Field(default_factory=list, description="Business measures (e.g. NetAmount, OrderQuantity)")
    attributes: List[str] = Field(default_factory=list, description="Descriptive attributes (e.g. CreationDate, Status)")
    parameters: List[str] = Field(default_factory=list, description="Input parameters (e.g. P_DisplayCurrency)")
    filters: List[str] = Field(default_factory=list, description="Requested filter conditions")
    all_requested_concepts: List[str] = Field(default_factory=list, description="Consolidated unique list of all requested concepts")


class FieldMapping(BaseModel):
    """Represents the semantic mapping between a requested requirement field and a candidate CDS field."""

    requirement_field: str = Field(..., description="Field requested in the business requirement")
    matched_field: Optional[str] = Field(default=None, description="Matched attribute in discovered CDS candidate")
    source_entity: Optional[str] = Field(default=None, description="Originating CDS view or joined table")
    data_type: Optional[str] = Field(default=None, description="ABAP dictionary data type (e.g., abap.char(10))")
    mapping_type: MappingType = Field(default=MappingType.MISSING, description="Mapping classification")
    evidence_level: EvidenceLevel = Field(default=EvidenceLevel.LEVEL_6_MISSING, description="Strict evidence tier (Level 1-6)")
    evidence_detail: str = Field(default="", description="Detailed human-readable evidence justifying the mapping")
    association_target_view: Optional[str] = Field(default=None, description="Target CDS view if verified association hop")
    association_target_field: Optional[str] = Field(default=None, description="Target field on verified association view")
    transformation_rule: Optional[str] = Field(default=None, description="Calculation formula or transformation expression")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Mapping confidence score")


class CandidateEvaluation(BaseModel):
    """Detailed multi-factor evaluation of a real SAP CDS view candidate."""

    candidate: CDSCandidate
    rank: int = Field(default=1, description="Rank among discovered candidates")
    rank_score: float = Field(default=0.0, description="Composite ranking score (0-100)")
    coverage_percentage: float = Field(default=0.0, description="Percentage of requested concepts satisfied")
    matched_concepts: List[str] = Field(default_factory=list, description="List of satisfied concept names")
    missing_concepts: List[str] = Field(default_factory=list, description="List of unsatisfied concept names")
    field_mappings: List[FieldMapping] = Field(default_factory=list, description="Itemized concept-to-field mappings")
    scoring_breakdown: Dict[str, float] = Field(default_factory=dict, description="Exposed heuristic scoring weights and components")
    is_extension_viable: bool = Field(default=False, description="Whether missing concepts are verified obtainable via extension")
    suitability_reason: str = Field(default="", description="Human-readable justification for candidate score and rank")


class Decision(BaseModel):
    """Outcome of the Decision Agent: recommendation of REUSE, EXTEND, CREATE, or INSUFFICIENT_EVIDENCE."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    requirement_id: str = Field(..., description="ID of the evaluated BusinessRequirement")
    action: DecisionAction = Field(..., description="Recommended action: REUSE, EXTEND, CREATE, or INSUFFICIENT_EVIDENCE")
    recommended_view: Optional[str] = Field(default=None, description="Existing CDS view name to reuse or extend")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Agent confidence score")
    fit_percentage: float = Field(..., ge=0.0, le=100.0, description="Percentage of requirement fulfilled by base view")
    rationale: str = Field(..., description="Detailed technical justification for the recommended action")
    missing_fields: List[str] = Field(default_factory=list, description="Requested fields not present in base view")
    proposed_extension_name: Optional[str] = Field(default=None, description="Proposed extension name if action is EXTEND")
    proposed_new_view_name: Optional[str] = Field(default=None, description="Proposed new CDS view name if action is CREATE")
    requires_composition: bool = Field(default=False, description="True if multi-CDS composition is required")
    complementary_views: List[str] = Field(default_factory=list, description="Complementary CDS candidates for multi-CDS composition")
    evaluated_candidates: List[CandidateEvaluation] = Field(default_factory=list, description="Ranked evaluations of all considered SAP candidates")
    structured_requirement: Optional[StructuredRequirement] = Field(default=None, description="Structured breakdown of concepts")
    evidence_summary: List[str] = Field(default_factory=list, description="Summary of verified evidence items")
    warnings: List[str] = Field(default_factory=list, description="Governance, architectural, or ambiguity warnings")
    tradeoffs: List[str] = Field(default_factory=list, description="Architectural tradeoffs and clean core impact notes")
    human_approval_required: bool = Field(default=True, description="Enforces human gatekeeper before any code deployment")
    is_approved: bool = Field(default=False, description="Whether human reviewer has signed off")
    approved_by: Optional[str] = Field(default=None, description="Reviewer identifier")
    approval_timestamp: Optional[datetime] = Field(default=None, description="Timestamp of approval")
    rejection_reason: Optional[str] = Field(default=None, description="Reason if rejected by reviewer")


class DataModelEntity(BaseModel):
    """Entity node within a conceptual or logical CDS data model."""

    name: str = Field(..., description="Entity name (CDS view or table)")
    layer: Optional[CDSLayer] = None
    fields: List[str] = Field(default_factory=list)
    key_fields: List[str] = Field(default_factory=list)


class DataModelAssociation(BaseModel):
    """Association edge between two CDS entities."""

    source_entity: str = Field(..., description="Source entity")
    target_entity: str = Field(..., description="Target associated entity")
    cardinality: str = Field(default="[0..1]", description="Cardinality (e.g., [1..1], [0..*])")
    on_condition: str = Field(..., description="ON clause expression")
    alias: str = Field(..., description="Association alias name")


class DataModel(BaseModel):
    """Comprehensive representation of the target CDS data model (visual and relational)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="Data model name (e.g., ZC_SalesOrderAnalytics)")
    root_entity: str = Field(..., description="Root CDS view or primary data source")
    entities: List[DataModelEntity] = Field(default_factory=list)
    associations: List[DataModelAssociation] = Field(default_factory=list)
    visual_layout: Dict[str, Any] = Field(
        default_factory=dict,
        description="Coordinates and styling for React Flow graph rendering",
    )


class ValidationResult(BaseModel):
    """Syntactic, clean-core, and governance validation check result."""

    is_valid: bool = Field(..., description="True if no blocking validation errors exist")
    syntax_errors: List[str] = Field(default_factory=list, description="Syntax errors detected in CDS definition")
    naming_convention_violations: List[str] = Field(
        default_factory=list,
        description="Violations of clean-core naming standards (e.g. ZI_ / ZC_)",
    )
    clean_core_compliance_score: float = Field(
        default=100.0,
        ge=0.0,
        le=100.0,
        description="Clean core compliance rating (0-100%)",
    )
    governance_warnings: List[str] = Field(default_factory=list, description="Non-blocking architectural warnings")
    details: List[Dict[str, Any]] = Field(default_factory=list, description="Itemized validation checks")


class DeploymentRequest(BaseModel):
    """Formal deployment request for creating/activating CDS objects in SAP DEV."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    object_name: str = Field(..., description="CDS view entity name")
    object_type: str = Field(default="CDS_VIEW_ENTITY", description="Object type (VIEW_ENTITY, EXTENSION)")
    target_system: str = Field(default="SAP DEV - Client 100", description="Target SAP system identifier")
    package: str = Field(..., description="ABAP development package (e.g., ZSALES_ANALYTICS)")
    transport_request: str = Field(..., description="Workbench Transport Request (TR) number")
    requester: str = Field(..., description="Developer requesting deployment")
    approver: Optional[str] = Field(default=None, description="Senior reviewer who approved deployment")
    status: DeploymentStatus = Field(default=DeploymentStatus.PENDING_APPROVAL)
    created_at: datetime = Field(default_factory=utc_now)
    audit_trail_id: Optional[str] = Field(default=None, description="Audit ledger reference")
