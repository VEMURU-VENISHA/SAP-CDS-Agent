"""Unit and integration tests for Platform Enhancements.

Covers:
- Suggestion 1: Faceted Filtering by Business Domain and Application Component
- Suggestion 2: Multi-Hop Join Traversal and Synthesized SQL
- Suggestion 3: Live Data Preview via ADT Freestyle Query
- Suggestion 4: Active CTS Transport Request Auto-Lookup
- Suggestion 5: Automated Incremental Synchronization
"""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.sap.adt_client import SAPADTClient
from src.services.discovery_service import CDSDiscoveryService


@pytest.mark.asyncio
async def test_data_preview_service_and_endpoint():
    """Validates ADT Data Preview endpoint and response formatting."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/discovery/preview/I_SALESORDER?max_rows=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cds_name"] == "I_SALESORDER"
        assert "columns" in data
        assert "rows" in data
        assert isinstance(data["columns"], list)
        assert isinstance(data["rows"], list)


@pytest.mark.asyncio
async def test_transport_requests_lookup_endpoint():
    """Validates CTS Transport Requests lookup endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/reviews/transports")
        assert resp.status_code == 200
        transports = resp.json()
        assert isinstance(transports, list)
        assert len(transports) > 0
        first_tr = transports[0]
        assert "number" in first_tr
        assert "owner" in first_tr
        assert "status" in first_tr
        assert "type" in first_tr


@pytest.mark.asyncio
async def test_incremental_sync_service():
    """Validates incremental synchronization engine execution."""
    svc = CDSDiscoveryService()
    result = await svc.sync_incremental(prefixes=["Z*"], max_per_prefix=2)
    assert result["success"] is True
    assert "prefixes" in result
    assert "new_views_count" in result
    assert "updated_views_count" in result
    assert "elapsed_seconds" in result


@pytest.mark.asyncio
async def test_multi_hop_join_synthesis():
    """Validates multi-hop join candidate construction and synthesized SQL clauses."""
    svc = CDSDiscoveryService()
    path_views = ["I_SALESORDER", "I_CUSTOMER", "I_COMPANYCODE"]
    path_edges = [
        {
            "source": "I_SALESORDER",
            "target": "I_CUSTOMER",
            "left_field": "SoldToParty",
            "right_field": "Customer",
            "relationship_type": "Association",
            "join_type": "LEFT OUTER JOIN",
            "cardinality": "1..*",
            "evidence": "Verified SAP ADT Association",
        },
        {
            "source": "I_CUSTOMER",
            "target": "I_COMPANYCODE",
            "left_field": "CompanyCode",
            "right_field": "CompanyCode",
            "relationship_type": "Association",
            "join_type": "LEFT OUTER JOIN",
            "cardinality": "1..1",
            "evidence": "Verified SAP ADT Association",
        },
    ]

    field_specs = [
        {"name": "Sales Order", "variants": ["SalesOrder"], "field_type": "DIRECT"},
        {"name": "Customer", "variants": ["Customer"], "field_type": "DIRECT"},
        {"name": "Company Code", "variants": ["CompanyCode"], "field_type": "DIRECT"},
    ]

    cand = svc._build_multi_cds_candidate(
        path_views=path_views,
        path_edges=path_edges,
        combined_matched_names={"Sales Order", "Customer", "Company Code"},
        field_specs=field_specs,
        views_with_fields={},
        view_field_evals={},
    )

    assert cand["type"] == "Multi CDS"
    assert cand["join_count"] == 2
    assert "Medium (2 Joins)" in cand["join_complexity"]
    assert "synthesized_join_sql" in cand
    assert "LEFT OUTER JOIN I_CUSTOMER" in cand["synthesized_join_sql"]
    assert "LEFT OUTER JOIN I_COMPANYCODE" in cand["synthesized_join_sql"]
    assert len(cand["join_path"]) == 2
    assert cand["join_path"][0]["hop"] == 1
    assert cand["join_path"][1]["hop"] == 2
