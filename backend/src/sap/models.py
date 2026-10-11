"""SAP Connector Data Transfer Objects (DTOs) and metadata definitions."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from src.models.domain import CDSConstructType, CDSLayer, EvidenceLevel, ValidationResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SAPSystemInfo(BaseModel):
    """Encapsulates target SAP S/4HANA system profile and baseline release metadata."""

    system_id: str = Field(default="DEV", description="SAP System ID (SID)")
    client: str = Field(default="100", description="SAP Mandant / Client number")
    s4hana_release: str = Field(default="2023", description="SAP S/4HANA release version")
    s4core_release: str = Field(default="108 SP03", description="S4CORE component version")
    basis_release: str = Field(default="758 SP03", description="SAP_BASIS component version")
    adt_endpoint_configured: bool = Field(default=False, description="Whether ADT discovery URL is configured")
    is_connected: bool = Field(default=False, description="Current connection state (strictly False in Milestone 1)")


class FieldDefinition(BaseModel):
    """ABAP Data Dictionary / CDS field definition."""

    field_name: str = Field(..., description="Field name in CDS or table")
    data_element: Optional[str] = Field(default=None, description="Data element (Rollname)")
    abap_type: str = Field(..., description="ABAP type (e.g., CHAR, NUMC, DATS, CURR, DEC)")
    length: int = Field(default=0, description="Field length in characters or bytes")
    decimals: int = Field(default=0, description="Decimal places if numeric")
    is_key: bool = Field(default=False, description="True if primary key component")
    description: str = Field(default="", description="Field label / business text")


class CDSAnnotationMetadata(BaseModel):
    """Structured CDS annotation extracted from DDL source or ADT metadata."""

    name: str = Field(..., description="Annotation name (e.g. EndUserText.label, VDM.viewType)")
    value: Any = Field(default=None, description="Parsed annotation value (string, boolean, numeric, or enum)")
    scope: str = Field(default="HEADER", description="Scope: HEADER, ELEMENT, PARAMETER")
    raw_text: Optional[str] = Field(default=None, description="Raw annotation text declaration")
    evidence_level: EvidenceLevel = Field(
        default=EvidenceLevel.LEVEL_1_EXACT_FIELD,
        description="Evidence hierarchy level for the extracted annotation",
    )


class CDSFieldMetadata(BaseModel):
    """Comprehensive field-level metadata extracted from authentic CDS DDL."""

    name: str = Field(..., description="Technical field name or alias")
    alias: Optional[str] = Field(default=None, description="Alias if explicitly renamed with 'as'")
    source_expression: Optional[str] = Field(default=None, description="Source expression (e.g. Header.vbeln or cast(...))")
    is_key: bool = Field(default=False, description="True if primary key component")
    data_type: Optional[str] = Field(default=None, description="Declared or cast data type (e.g. abap.char(10))")
    abap_type: str = Field(default="CHAR", description="Inferred or declared ABAP type (CHAR, DATS, CURR, etc.)")
    length: int = Field(default=0, description="Field length in characters or bytes")
    decimals: int = Field(default=0, description="Decimal places if numeric")
    description: str = Field(default="", description="Field label / business text from @EndUserText.label")
    annotations: Dict[str, Any] = Field(default_factory=dict, description="Field-level annotations")
    evidence_level: EvidenceLevel = Field(
        default=EvidenceLevel.LEVEL_1_EXACT_FIELD,
        description="Strict evidence tier for field verification",
    )
    evidence_source: str = Field(
        default="SAP_ADT_DDL_SOURCE",
        description="Authoritative source origin (SAP ADT DDL)",
    )
    evidence_detail: str = Field(
        default="",
        description="Human-readable justification for field evidence",
    )


class CDSAssociationMetadata(BaseModel):
    """Structured association definition extracted from authentic CDS DDL."""

    name: str = Field(..., description="Association name / alias (e.g. _Item)")
    target_entity: str = Field(..., description="Target CDS view entity or table")
    cardinality: str = Field(default="[0..1]", description="Cardinality expression (e.g. [0..*], [1..1], [0..1])")
    on_condition: str = Field(default="", description="Join ON clause condition expression")
    is_exposed: bool = Field(default=True, description="Whether the association is exposed in the SELECT list")
    evidence_level: EvidenceLevel = Field(
        default=EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION,
        description="Strict evidence tier for verified associations",
    )
    evidence_source: str = Field(
        default="SAP_ADT_DDL_SOURCE",
        description="Authoritative source origin (SAP ADT DDL)",
    )
    evidence_detail: str = Field(
        default="",
        description="Human-readable justification for association evidence",
    )


class CDSViewMetadata(BaseModel):
    """Authoritative structured metadata for an SAP CDS view entity extracted from SAP ADT."""

    view_name: str = Field(..., description="Technical CDS view entity name")
    description: str = Field(default="", description="CDS view description / label")
    object_type: str = Field(default="DDLS/DF", description="ADT repository object type")
    source_type: str = Field(default="view_entity", description="Source type: view_entity, view, projection_view")
    cds_construct_type: CDSConstructType = Field(
        default=CDSConstructType.UNKNOWN,
        description="Base CDS construct type: CLASSIC_VIEW, VIEW_ENTITY, or UNKNOWN",
    )
    version: str = Field(default="active", description="Repository version (active/inactive)")
    package: Optional[str] = Field(default=None, description="ABAP development package")
    layer: CDSLayer = Field(default=CDSLayer.BASIC, description="VDM architectural layer")
    sql_view_name: Optional[str] = Field(default=None, description="Classic SQL view name if older CDS")
    source_tables: List[str] = Field(default_factory=list, description="Underlying DB tables or joined entities")
    parameters: List[Dict[str, str]] = Field(default_factory=list, description="CDS view parameters")
    fields: List[CDSFieldMetadata] = Field(default_factory=list, description="Structured field metadata")
    associations: List[CDSAssociationMetadata] = Field(default_factory=list, description="Structured association metadata")
    annotations: List[CDSAnnotationMetadata] = Field(default_factory=list, description="Structured annotations")
    raw_source: Optional[str] = Field(default=None, description="Raw DDL source or XML text")
    evidence_level: EvidenceLevel = Field(
        default=EvidenceLevel.LEVEL_1_EXACT_FIELD,
        description="Top-level view entity evidence rating",
    )
    evidence_source: str = Field(
        default="SAP_ADT_DDL_SOURCE",
        description="Authoritative source origin (SAP ADT DDL)",
    )
    parsed_at: datetime = Field(default_factory=utc_now)


class CDSMetadata(BaseModel):
    """Detailed metadata representing a CDS View Entity extracted from SAP ADT / Data Dictionary."""

    view_name: str = Field(..., description="CDS view entity name")
    sql_view_name: Optional[str] = Field(default=None, description="Classical SQL view name if older CDS")
    package: Optional[str] = Field(default=None, description="ABAP development package")
    layer: CDSLayer = Field(default=CDSLayer.BASIC, description="VDM layer")
    description: str = Field(default="", description="CDS description text")
    annotations: Dict[str, Any] = Field(default_factory=dict, description="Parsed CDS annotations (e.g. @VDM, @AccessControl)")
    parameters: List[Dict[str, str]] = Field(default_factory=list, description="CDS view parameters with default values")
    fields: List[FieldDefinition] = Field(default_factory=list, description="Field definitions")
    associations: List[str] = Field(default_factory=list, description="Target entities of defined associations")
    source_tables: List[str] = Field(default_factory=list, description="Underlying DB tables or joined CDS entities")
    structured: Optional[CDSViewMetadata] = Field(default=None, description="Attached Milestone 9 structured view metadata")


class DependencyNode(BaseModel):
    """Node in a CDS dependency graph."""

    name: str = Field(..., description="Object name (table or CDS view)")
    object_type: str = Field(..., description="TABLE, CDS_VIEW_ENTITY, CDS_PROJECTION")
    layer: Optional[CDSLayer] = None


class DependencyGraph(BaseModel):
    """Directed dependency graph of CDS views and base tables."""

    root_view: str = Field(..., description="Root CDS view being inspected")
    nodes: List[DependencyNode] = Field(default_factory=list)
    direct_dependencies: List[str] = Field(default_factory=list, description="Direct views/tables queried")
    used_by_views: List[str] = Field(default_factory=list, description="Parent views consuming this view")


class DraftResult(BaseModel):
    """Result of creating a draft CDS object in SAP DEV."""

    object_name: str
    version: str = "inactive"
    package: str
    transport_request: str
    message: str
    created_at: datetime = Field(default_factory=utc_now)


class ActivationResult(BaseModel):
    """Result of activating a CDS object in SAP DEV."""

    object_name: str
    is_active: bool
    transport_request: str
    syntax_messages: List[str] = Field(default_factory=list)
    activated_at: datetime = Field(default_factory=utc_now)
