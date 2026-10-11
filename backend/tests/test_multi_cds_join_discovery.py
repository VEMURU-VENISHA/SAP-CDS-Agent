"""Test Multi-CDS Relationship Graph and Multi-Hop Join Discovery Engine."""

import pytest
from src.services.discovery_service import CDSDiscoveryService


@pytest.mark.asyncio
async def test_relationship_graph_construction():
    """Verifies that the CDS Relationship Graph is built from verified ADT tables."""
    service = CDSDiscoveryService()
    graph = service._ensure_relationship_graph()
    meta = service._graph_metadata

    assert len(graph) > 100
    assert meta["total_association_edges"] >= 916
    assert meta["relationship_graph_nodes"] >= 400
    assert meta["relationship_graph_edges"] > 1000
    assert meta["cds_with_associations"] > 400

    # Verify verified edges for I_SALESORDER
    sales_order_edges = graph.get("I_SALESORDER", [])
    assert len(sales_order_edges) > 0

    target_views = [e["target_upper"] for e in sales_order_edges]
    assert "I_SALESORDERITEM" in target_views
    assert "I_CUSTOMER" in target_views or "I_CUSTOMERSALESAREA" in target_views


@pytest.mark.asyncio
async def test_multi_hop_join_discovery_on_business_requirement():
    """Verifies multi-hop path discovery with 1-hop, 2-hop, and 3-hop join candidates."""
    service = CDSDiscoveryService()

    query = (
        "Analyze sales revenue and outstanding customer receivables by customer and sales "
        "organization for the current fiscal year. Show the total sales amount, invoiced amount, "
        "outstanding amount, and overdue amount. Filter the results for sales organization 1000 "
        "and transactions with posting date in the current fiscal year."
    )

    field_specs = [
        {"name": "Customer", "variants": ["Customer", "KUNNR", "SoldToParty", "CustomerNumber"]},
        {"name": "SalesOrganization", "variants": ["SalesOrganization", "VKORG", "SalesOrg"]},
        {"name": "SalesAmount", "variants": ["TotalNetAmount", "NetPriceAmount", "NetAmount", "GrossAmount", "SalesOrderAmount"]},
        {"name": "InvoicedAmount", "variants": ["TotalInvoiceAmount", "InvoicedAmount", "BillingAmount", "GrossAmount"]},
        {"name": "OutstandingAmount", "variants": ["OutstandingAmount", "DueAmount", "AmountInCompanyCodeCurrency", "BalanceAmount"]},
        {"name": "OverdueAmount", "variants": ["OverdueAmount", "OverdueBalance", "AmountInCompanyCodeCurrency"]},
        {"name": "FiscalYear", "variants": ["FiscalYear", "GJAHR"]},
        {"name": "PostingDate", "variants": ["PostingDate", "BUDAT", "CreationDate"]},
    ]

    result = await service.run_discovery(
        requirement_text=query,
        required_fields=field_specs,
        search_mode="deep",
        use_cache=False,
    )

    stats = result["search_statistics"]

    # Verify graph metrics in statistics
    assert stats["total_indexed_cds"] >= 47535
    assert stats["cds_indexed"] >= 47535
    assert stats["associations_indexed"] >= 916
    assert stats["relationship_graph_nodes"] >= 400
    assert stats["relationship_graph_edges"] > 1000
    assert stats["cds_with_associations"] > 400

    # Verify multi-hop paths are discovered across 1, 2, and 3 hops
    assert stats["1_hop_paths"] > 0
    assert stats["2_hop_paths"] > 0
    assert stats["3_hop_paths"] > 0

    # Total multi-CDS candidates must be substantially larger than 6
    assert stats["valid_multi_cds_candidates"] > 100
    assert len(result["multi_cds_candidates"]) > 100

    # Verify candidate properties
    for cand in result["multi_cds_candidates"][:10]:
        assert cand["type"] == "Multi CDS"
        assert len(cand["views"]) >= 2
        assert " + " in cand["cds_name"]
        assert len(cand["join_path"]) >= 1
        for hop in cand["join_path"]:
            assert "hop" in hop
            assert "left_view" in hop
            assert "right_view" in hop
            assert "left_field" in hop
            assert "right_field" in hop
            assert "relationship_type" in hop
            assert "source" in hop
            assert hop["source"] == "ADT metadata"

    # Verify that full coverage candidates exist via joins (e.g. 8/8 fields)
    full_cov = [c for c in result["multi_cds_candidates"] if c["coverage_pct"] >= 100.0]
    assert len(full_cov) > 0
    sample_full = full_cov[0]
    assert sample_full["coverage_ratio"] == "8/8"
    assert sample_full["coverage_group"] == "Full Coverage"
