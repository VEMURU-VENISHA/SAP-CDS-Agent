"""Test verification script for Phase 1: Enhanced Discovery Service & API."""

import asyncio
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from src.config import get_settings
from src.services.discovery_service import CDSDiscoveryService
from src.services.gemini_service import GeminiService


async def test_phase1():
    print("=" * 60)
    print("PHASE 1 VERIFICATION: SAP CDS Discovery Engine")
    print("=" * 60)

    ds = CDSDiscoveryService()
    gem = GeminiService()

    # 1. Metadata status
    status = ds.get_metadata_status()
    print(f"[1/5] Metadata Status: {status['status']}")
    print(f"      CDS Views Indexed:      {status['cds_count']}")
    print(f"      Fields Indexed:         {status['field_count']}")
    print(f"      Associations Indexed:   {status['associations_count']}")
    print(f"      Relationships Indexed:  {status['relationships_count']}")
    print(f"      Connection:             {status['connection_status']}")
    assert status["cds_count"] > 0, "No CDS views indexed!"

    # 2. Direct search
    results = await ds.direct_search("SalesOrder")
    print(f"[2/5] Direct Search ('SalesOrder'): Found {len(results)} match(es)")
    for r in results[:3]:
        print(f"      - {r['cds_name']} ({r['description']}) [Fields: {r['total_fields']}]")
    assert len(results) > 0, "Direct search failed!"

    # 3. View details
    details = await ds.get_view_details("I_SalesOrder")
    print(f"[3/5] View Details ('I_SalesOrder'):")
    print(f"      Description:  {details['description']}")
    print(f"      Total Fields: {len(details['fields'])}")
    print(f"      Keys:         {details['keys']}")
    print(f"      OData Status: {details['odata_status']}")
    assert len(details["fields"]) > 0, "Failed to load fields for I_SalesOrder!"

    # 4. Two-stage discovery (Zero-cutoff check)
    required_fields = [
        {"name": "Sales Order", "variants": ["SalesOrder", "SalesDocument", "VBELN"]},
        {"name": "Sold-to Party", "variants": ["SoldToParty", "Customer", "Customer Number", "KUNNR"]},
        {"name": "Material", "variants": ["Material", "Product", "MATNR"]},
        {"name": "Net Amount", "variants": ["TotalNetAmount", "NetAmount", "NETWR"]},
        {"name": "Currency", "variants": ["TransactionCurrency", "Currency", "WAERK"]},
        {"name": "Company Code", "variants": ["CompanyCode", "BUKRS"]},
        {"name": "Sales Organization", "variants": ["SalesOrganization", "VKORG"]},
    ]
    disc_res = await ds.run_discovery(
        requirement_text="I need sales order analysis with sales order, customer, material, net amount, currency, company code and sales organization.",
        required_fields=required_fields,
        search_mode="fast",
        use_cache=False,
    )
    stats = disc_res["search_statistics"]
    candidates = disc_res["candidates"]
    print(f"[4/5] Two-Stage Discovery Results (Zero Cutoff Verification):")
    print(f"      Search Time:            {stats['search_time_ms']} ms")
    print(f"      Total Candidates Found: {len(candidates)} (Relevant: {stats['relevant_candidates']})")
    print(f"      Full Coverage (100%):   {stats['full_coverage_candidates']}")
    print(f"      High Coverage (70-99%): {stats['high_coverage_candidates']}")
    print(f"      Partial (40-69%):       {stats['partial_coverage_candidates']}")
    print(f"      Low (<40%):             {stats['low_coverage_candidates']}")
    print(f"      Valid Multi-CDS Joins:  {stats['valid_multi_cds_candidates']}")

    # Verify candidates are NOT limited to top 10 or 50
    print(f"      Top candidate: {candidates[0]['cds_name']} -> {candidates[0]['coverage_pct']}% ({candidates[0]['coverage_group']})")
    print(f"      Missing in top: {candidates[0]['missing_fields']}")
    assert len(candidates) > 10, f"Expected more than 10 candidates, found {len(candidates)}"

    # 5. Search Cache verification
    cache_res = await ds.run_discovery(
        requirement_text="I need sales order analysis with sales order, customer, material, net amount, currency, company code and sales organization.",
        required_fields=required_fields,
        search_mode="fast",
        use_cache=True,
    )
    print(f"[5/5] Search Cache Hit Verification: from_cache = {cache_res['search_statistics']['from_cache']}")
    assert cache_res["search_statistics"]["from_cache"] is True, "Cache did not hit on repeated query!"

    print("\n" + "=" * 60)
    print("PHASE 1 BACKEND VERIFICATION SUCCEEDED 100%!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_phase1())
