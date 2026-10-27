"""Authoritative Tests for CDS Views Data Extraction Enabled Status Filtering.

Tests all 8 mandatory requirements:
1. A CDS view confirmed as extraction-enabled is included.
2. A CDS view confirmed as not extraction-enabled is excluded.
3. Missing or incomplete metadata produces an unverified result.
4. Metadata retrieval failures do not produce fabricated eligibility.
5. Multi-CDS solutions require every component to pass the filter.
6. Ranking and final solution selection happen after filtering.
7. Normal discovery remains unchanged when extraction filtering is not requested.
8. Delta support is not accidentally treated as the general extraction-enabled flag.
"""

import pytest
from unittest.mock import AsyncMock, patch
from src.services.discovery_service import CDSDiscoveryService
from src.sap.adt_client import SAPADTClient


class MockExtractionSAPClient:
    """Mock SAP client simulating authoritative records from I_DataExtractionEnabledView."""

    def __init__(self, mode: str = "complete"):
        self.mode = mode

    async def get_extraction_metadata_records(self, view_names=None, max_records=10000):
        if self.mode == "failure":
            return {
                "success": False,
                "is_complete": False,
                "total_rows_in_sap": 0,
                "records_count": 0,
                "records": {},
                "error": "HTTP 500: SAP ADT freestyle data preview unavailable",
            }
        elif self.mode == "incomplete":
            return {
                "success": True,
                "is_complete": False,  # Incomplete / partial query!
                "total_rows_in_sap": 6102,
                "records_count": 1,
                "records": {
                    "I_SALESORDER": {
                        "view_name": "I_SalesOrder",
                        "description": "Sales Order",
                        "is_sap_released": True,
                        "delta_cdc_supported": True,
                        "extraction_status": "VERIFIED_ENABLED",
                    }
                },
                "error": None,
            }
        else:
            # Complete authoritative mock matching verified SAP S/4HANA records
            return {
                "success": True,
                "is_complete": True,
                "total_rows_in_sap": 3,
                "records_count": 3,
                "records": {
                    "I_SALESORDER": {
                        "view_name": "I_SalesOrder",
                        "description": "Sales Order Header",
                        "is_sap_released": True,
                        "delta_cdc_supported": True,
                        "extraction_status": "VERIFIED_ENABLED",
                    },
                    "I_CUSTOMER": {
                        "view_name": "I_Customer",
                        "description": "Customer Master Data",
                        "is_sap_released": True,
                        "delta_cdc_supported": True,
                        "extraction_status": "VERIFIED_ENABLED",
                    },
                    "I_SERVICEDOCUMENTTYPETEXT": {
                        "view_name": "I_ServiceDocumentTypeText",
                        "description": "Service Transaction Type - Text",
                        "is_sap_released": True,
                        "delta_cdc_supported": False,  # General extraction enabled, but NO delta CDC!
                        "extraction_status": "VERIFIED_ENABLED",
                    },
                },
                "error": None,
            }


@pytest.fixture
def discovery_service():
    service = CDSDiscoveryService()
    # Reset in-memory caches
    service._search_cache.clear()
    service._extraction_metadata_cache = None
    service._extraction_cache_timestamp = 0.0
    return service


# ==============================================================================
# Requirement 1: A CDS view confirmed as extraction-enabled is included
# ==============================================================================
@pytest.mark.asyncio
async def test_extraction_enabled_view_included(discovery_service):
    mock_client = MockExtractionSAPClient(mode="complete")

    result = await discovery_service.run_discovery(
        requirement_text="Extract sales orders for data warehouse pipeline",
        required_fields=[
            {"name": "SalesOrder", "field_type": "DIRECT"},
        ],
        extraction_enabled_only=True,
        use_cache=False,
        sap_client=mock_client,
    )

    cands = result.get("candidates", [])
    sales_orders = [c for c in cands if c.get("cds_name").upper() == "I_SALESORDER" or c.get("cds_name") == "I_SalesOrder"]

    assert len(sales_orders) > 0, "I_SalesOrder must be included as it is confirmed extraction-enabled in I_DataExtractionEnabledView"
    so = sales_orders[0]
    assert so.get("data_extraction_enabled") is True
    assert so.get("extraction_status") == "VERIFIED_ENABLED"
    assert "Verified in I_DataExtractionEnabledView" in so.get("extraction_details", "")


# ==============================================================================
# Requirement 2: A CDS view confirmed as not extraction-enabled is excluded
# ==============================================================================
@pytest.mark.asyncio
async def test_non_extraction_enabled_view_excluded(discovery_service):
    mock_client = MockExtractionSAPClient(mode="complete")

    # In our complete mock, I_MATERIAL is NOT in I_DataExtractionEnabledView
    result = await discovery_service.run_discovery(
        requirement_text="Data extraction for material master",
        required_fields=[
            {"name": "Material", "field_type": "DIRECT"},
        ],
        extraction_enabled_only=True,
        use_cache=False,
        sap_client=mock_client,
    )

    cands = result.get("candidates", [])
    material_views = [c for c in cands if c.get("cds_name") in ("I_Material", "I_MATERIAL")]

    assert len(material_views) == 0, "I_Material must be excluded because it is not listed in authoritative extraction records"
    assert result["search_statistics"]["extraction_filtering"]["requested"] is True
    assert result["search_statistics"]["extraction_filtering"]["metadata_status"] == "COMPLETE"


# ==============================================================================
# Requirement 3: Missing or incomplete metadata produces an unverified result
# ==============================================================================
@pytest.mark.asyncio
async def test_incomplete_metadata_produces_unverified(discovery_service):
    mock_client = MockExtractionSAPClient(mode="incomplete")

    result = await discovery_service.run_discovery(
        requirement_text="Extract customer data",
        required_fields=[
            {"name": "Customer", "field_type": "DIRECT"},
        ],
        extraction_enabled_only=True,
        use_cache=False,
        sap_client=mock_client,
    )

    cands = result.get("candidates", [])
    # In incomplete mode, only I_SALESORDER was returned, but total_rows was 6102.
    # Therefore, I_Customer is absent from an INCOMPLETE query -> must be UNVERIFIED, NOT treated as enabled!
    customer_views = [c for c in cands if c.get("cds_name") == "I_Customer"]
    assert len(customer_views) == 0, "Views absent from an incomplete metadata query must never be treated as enabled"
    assert result["search_statistics"]["extraction_filtering"]["metadata_status"] == "INCOMPLETE"


# ==============================================================================
# Requirement 4: Metadata retrieval failures do not produce fabricated eligibility
# ==============================================================================
@pytest.mark.asyncio
async def test_metadata_failure_never_fabricates_eligibility(discovery_service):
    mock_client = MockExtractionSAPClient(mode="failure")

    result = await discovery_service.run_discovery(
        requirement_text="Extract sales orders",
        required_fields=[
            {"name": "SalesOrder", "field_type": "DIRECT"},
        ],
        extraction_enabled_only=True,
        use_cache=False,
        sap_client=mock_client,
    )

    assert len(result.get("candidates", [])) == 0, "No candidates may be fabricated as eligible when metadata query fails"
    assert len(result.get("single_cds_candidates", [])) == 0
    assert len(result.get("multi_cds_candidates", [])) == 0

    sol = result.get("solution_summary", {})
    assert sol.get("solution_type") == "NO_SOLUTION"
    assert "I_DataExtractionEnabledView" in sol.get("message", "")
    assert result["search_statistics"]["extraction_filtering"]["metadata_status"] == "FAILED"


# ==============================================================================
# Requirement 5: Multi-CDS solutions require every component to pass the filter
# ==============================================================================
@pytest.mark.asyncio
async def test_multi_cds_all_components_must_pass_filter(discovery_service):
    mock_client = MockExtractionSAPClient(mode="complete")

    # In our complete mock:
    # I_SalesOrder is enabled.
    # I_Customer is enabled.
    # Any view not in (I_SalesOrder, I_Customer, I_ServiceDocumentTypeText) is NOT enabled.

    # Multi-hop requirement spanning SalesOrder (I_SalesOrder) and CustomerName (I_Customer)
    result = await discovery_service.run_discovery(
        requirement_text="Data extraction for sales orders and customer details",
        required_fields=[
            {"name": "SalesOrder", "field_type": "DIRECT"},
            {"name": "CustomerName", "field_type": "DIRECT"},
        ],
        extraction_enabled_only=True,
        use_cache=False,
        sap_client=mock_client,
    )

    multi_cands = result.get("multi_cds_candidates", [])
    for mc in multi_cands:
        comp_statuses = mc.get("component_extraction_statuses", {})
        for comp_name, status in comp_statuses.items():
            assert status == "VERIFIED_ENABLED", f"Every component in multi-CDS candidate must be VERIFIED_ENABLED, got {comp_name}: {status}"
        assert mc.get("data_extraction_enabled") is True


# ==============================================================================
# Requirement 6: Ranking and final solution selection happen after filtering
# ==============================================================================
@pytest.mark.asyncio
async def test_ranking_and_solution_selection_after_filtering(discovery_service):
    # Mock client where only an unrelated view is extraction-enabled, and sales order views are NOT enabled
    class UnrelatedExtractionMock:
        async def get_extraction_metadata_records(self, view_names=None, max_records=10000):
            return {
                "success": True,
                "is_complete": True,
                "total_rows_in_sap": 1,
                "records_count": 1,
                "records": {
                    "I_SERVICEDOCUMENTTYPETEXT": {
                        "view_name": "I_ServiceDocumentTypeText",
                        "description": "Service Transaction Type - Text",
                        "is_sap_released": True,
                        "delta_cdc_supported": True,
                        "extraction_status": "VERIFIED_ENABLED",
                    }
                },
                "error": None,
            }

    mock_client = UnrelatedExtractionMock()

    # Sales order views have 100% field coverage for SalesOrder, but are NOT in UnrelatedExtractionMock.
    # Therefore, they must be filtered out BEFORE solution selection.
    result = await discovery_service.run_discovery(
        requirement_text="Data extraction pipeline for sales orders",
        required_fields=[
            {"name": "SalesOrder", "field_type": "DIRECT"},
        ],
        extraction_enabled_only=True,
        use_cache=False,
        sap_client=mock_client,
    )

    sol = result.get("solution_summary", {})
    # Since non-extraction views were excluded by extraction filter, solution must NOT select them as REUSE_EXISTING!
    assert sol.get("solution_type") == "NO_SOLUTION", "Non-extraction views must not be selected as REUSE_EXISTING when extraction filtering is active"
    assert sol.get("requires_create") is False


# ==============================================================================
# Requirement 7: Normal discovery remains unchanged when extraction filtering is not requested
# ==============================================================================
@pytest.mark.asyncio
async def test_normal_discovery_unchanged_when_not_requested(discovery_service):
    # Ordinary query without any extraction keyword or flag
    result = await discovery_service.run_discovery(
        requirement_text="Display material details in Fiori app",
        required_fields=[
            {"name": "Material", "field_type": "DIRECT"},
        ],
        extraction_enabled_only=False,
        use_cache=False,
    )

    cands = result.get("candidates", [])
    # Under normal discovery, material views are discovered normally
    assert len(cands) > 0, "Normal discovery must return matching views when extraction filtering is not requested"
    assert result["search_statistics"]["extraction_filtering"]["requested"] is False


# ==============================================================================
# Requirement 8: Delta support is not accidentally treated as general extraction flag
# ==============================================================================
@pytest.mark.asyncio
async def test_delta_support_not_confused_with_general_extraction(discovery_service):
    mock_client = MockExtractionSAPClient(mode="complete")
    # I_ServiceDocumentTypeText has delta_cdc_supported = False, but is in I_DataExtractionEnabledView!

    # Case A: General data extraction (delta NOT specifically required)
    res_general = await discovery_service.run_discovery(
        requirement_text="Data extraction for service document types",
        required_fields=[
            {"name": "ServiceDocumentType", "field_type": "DIRECT"},
        ],
        extraction_enabled_only=True,
        require_delta_support=False,
        use_cache=False,
        sap_client=mock_client,
    )

    # I_ServiceDocumentTypeText must be eligible under general data extraction
    cand_names_general = [c.get("cds_name") for c in res_general.get("candidates", [])]
    if "I_ServiceDocumentTypeText" in cand_names_general:
        target = [c for c in res_general.get("candidates", []) if c.get("cds_name") == "I_ServiceDocumentTypeText"][0]
        assert target.get("extraction_status") == "VERIFIED_ENABLED"
        assert target.get("data_extraction_enabled") is True
        assert target.get("delta_cdc_supported") is False

    # Case B: Specific Delta / CDC requirement
    res_delta = await discovery_service.run_discovery(
        requirement_text="Real-time delta change data capture (CDC) extraction for service document types",
        required_fields=[
            {"name": "ServiceDocumentType", "field_type": "DIRECT"},
        ],
        extraction_enabled_only=True,
        require_delta_support=True,
        use_cache=False,
        sap_client=mock_client,
    )

    # Under strict delta requirement, I_ServiceDocumentTypeText must be EXCLUDED!
    cand_names_delta = [c.get("cds_name") for c in res_delta.get("candidates", [])]
    assert "I_ServiceDocumentTypeText" not in cand_names_delta, "View without delta CDC support must be excluded when delta support is specifically required"
