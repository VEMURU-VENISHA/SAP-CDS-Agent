"""SAP Connector Data Transfer Objects (DTOs) and metadata definitions."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from src.models.domain import CDSLayer, ValidationResult


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
