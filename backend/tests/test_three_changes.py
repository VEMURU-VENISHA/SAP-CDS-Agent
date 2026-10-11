"""Test the 3 required changes:
Change 1: Live DDL source retrieval and field trace analysis
Change 2: Semantic search variants generation for added/edited fields
Change 3: Calculated/derived business fields evaluation
"""

import pytest
import asyncio
from src.services.gemini_service import GeminiService
from src.services.discovery_service import CDSDiscoveryService

@pytest.mark.asyncio
async def test_change2_generate_single_field_variants():
    service = GeminiService()
    
    # 1. Direct field
    res_direct = await service.generate_single_field_variants(
        field_name="Billing Type",
        requirement_text="Sales order processing",
        domain="Sales"
    )
    assert res_direct["name"] == "Billing Type"
    assert len(res_direct["variants"]) >= 4
    assert res_direct["field_type"] in ["DIRECT", "FILTER/CONDITION"]
    
    # 2. Calculated measure
    res_calc = await service.generate_single_field_variants(
        field_name="Overdue Amount",
        requirement_text="Track unpaid orders past payment term",
        domain="Sales"
    )
    assert res_calc["name"] == "Overdue Amount"
    assert res_calc["field_type"] == "CALCULATED"
    assert len(res_calc["underlying_concepts"]) >= 2
    assert any("amount" in c.lower() or "open" in c.lower() for c in res_calc["underlying_concepts"])
    assert any("date" in c.lower() or "due" in c.lower() for c in res_calc["underlying_concepts"])
    
    # 3. Filter condition
    res_filter = await service.generate_single_field_variants(
        field_name="Current Fiscal Year",
        requirement_text="Filter orders posted in current financial year",
        domain="Sales"
    )
    assert res_filter["name"] == "Current Fiscal Year"
    assert res_filter["field_type"] in ["FILTER/CONDITION", "DERIVED"]
    assert len(res_filter["underlying_concepts"]) >= 1


@pytest.mark.asyncio
async def test_change1_live_source_details():
    disc_service = CDSDiscoveryService()
    
    # Fetch real DDL for I_SalesOrder
    details = await disc_service.get_view_source_details(
        view_name="I_SalesOrder",
        requested_fields=["SalesOrder", "SoldToParty", "TotalNetAmount"]
    )
    
    assert details["view_name"] == "I_SalesOrder"
    assert details["source_status"] == "RETRIEVED"
    assert details["source"] and len(details["source"]) > 100
    assert details["adt_endpoint"] == "/sap/bc/adt/ddic/ddl/sources/i_salesorder/source/main"
    assert details["field_trace_status"] in ["CONFIRMED", "PARTIALLY_TRACED"]
    assert details["final_evidence"] in ["SOURCE_VERIFIED", "METADATA_ONLY"]
    assert details["field_traces"].get("SalesOrder") == "CONFIRMED_IN_DDL"


@pytest.mark.asyncio
async def test_change3_discovery_derived_fields():
    disc_service = CDSDiscoveryService()
    
    required_fields = [
        {"name": "Sales Order", "variants": ["SalesOrder", "VBELN"], "field_type": "DIRECT"},
        {"name": "Sold-to Party", "variants": ["SoldToParty", "Customer", "KUNNR"], "field_type": "DIRECT"},
        {
            "name": "Overdue Amount",
            "variants": ["OverdueAmount"],
            "field_type": "CALCULATED",
            "underlying_concepts": ["Open Amount", "Due Date"],
            "calculation_approach": "Open amount where due date < today"
        }
    ]
    
    res = await disc_service.run_discovery(
        requirement_text="Sales orders with overdue payment amount",
        required_fields=required_fields,
        use_cache=False
    )
    
    candidates = res["candidates"]
    assert len(candidates) > 0
    
    # Check that candidate structures contain the new fields
    top_cand = candidates[0]
    assert "direct_matched_count" in top_cand
    assert "derived_matched_count" in top_cand
    assert "derived_verified_fields" in top_cand
    assert "derived_unresolved_fields" in top_cand
    assert "views" in top_cand
    
    # Multi-CDS candidate
    multi_cands = [c for c in candidates if c["type"] == "Multi CDS"]
    if multi_cands:
        mc = multi_cands[0]
        assert len(mc["views"]) >= 2
        assert " + " in mc["cds_name"]
