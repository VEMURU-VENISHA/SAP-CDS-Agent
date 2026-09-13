"""SAP Discovery API Routes."""

from typing import List, Optional
from fastapi import APIRouter, Query
from src.models.domain import CDSCandidate, CDSLayer
from src.sap.connector import get_sap_connector
from src.sap.models import SAPSystemInfo

router = APIRouter(prefix="/discovery", tags=["SAP Discovery"])


@router.get(
    "/system-profile",
    response_model=SAPSystemInfo,
    summary="Returns SAP target system metadata profile",
)
async def get_sap_profile():
    """Returns the baseline SAP S/4HANA target system profile."""
    connector = get_sap_connector()
    return await connector.get_system_info()


@router.get(
    "/search",
    response_model=List[CDSCandidate],
    summary="Searches CDS views in SAP (enforces unconnected guardrail in Milestone 1)",
)
async def search_cds_views(
    q: str = Query(..., min_length=2, description="Search term for view name or business description"),
    package: Optional[str] = Query(None, description="Optional ABAP package filter"),
    layer: Optional[CDSLayer] = Query(None, description="VDM layer filter"),
):
    """Invokes the SAP connector to locate CDS candidates."""
    connector = get_sap_connector()
    # In Milestone 1, this raises SAPNotConnectedError
    return await connector.search_cds(query=q, package=package, layer=layer)
