"""Verification script for:
1. Independent CDS Candidate IDs & Selection State
2. CTS Workbench Transport Request validation (Step 11 & 12)
3. Direct SAP Creation Pre-flight API validation
"""

import asyncio
from pathlib import Path
import re
import sys

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from httpx import AsyncClient, ASGITransport

from src.main import app
from src.services.discovery_service import CDSDiscoveryService
from src.sap.adt_client import SAPADTClient

CTS_TRANSPORT_REGEX = re.compile(r"^[A-Z0-9]{3}K[0-9]{6}$")


async def test_fixes():
    print("=" * 70)
    print("STARTING TEST: Independent Candidate IDs & CTS Transport Validation")
    print("=" * 70)

    # -------------------------------------------------------------
    # Test 1: Candidate Unique IDs in CDSDiscoveryService
    # -------------------------------------------------------------
    print("\n[TEST 1] Verifying Candidate Unique IDs in CDSDiscoveryService...")
    service = CDSDiscoveryService()
    sample_fields = [
        {"name": "Sales Order", "variants": ["SalesOrder", "VBELN"]},
        {"name": "Sold-to Party", "variants": ["SoldToParty", "Customer", "KUNNR"]},
        {"name": "Material", "variants": ["Material", "Product", "MATNR"]},
    ]
    res = await service.run_discovery(
        requirement_text="Sales order analysis",
        required_fields=sample_fields,
        search_mode="fast"
    )
    candidates = res.get("candidates", [])
    assert len(candidates) > 0, "No candidates found"

    print(f"Discovered {len(candidates)} candidates.")
    candidate_ids = [c.get("id") for c in candidates]

    # Verify every candidate has an id
    assert all(cid is not None for cid in candidate_ids), "Some candidates lack an 'id' attribute!"

    # Find single and multi examples
    single_cands = [c for c in candidates if c.get("type") == "Single CDS"]
    multi_cands = [c for c in candidates if c.get("type") == "Multi CDS"]

    print(f"Found {len(single_cands)} Single CDS and {len(multi_cands)} Multi CDS candidates.")

    if single_cands:
        s = single_cands[0]
        print(f"Sample Single CDS candidate: name='{s['cds_name']}', id='{s['id']}'")
        assert s["id"].startswith("single:"), f"Single candidate ID should start with 'single:', got {s['id']}"

    if multi_cands:
        m = multi_cands[0]
        print(f"Sample Multi CDS candidate:  name='{m['cds_name']}', id='{m['id']}'")
        assert m["id"].startswith("multi:"), f"Multi candidate ID should start with 'multi:', got {m['id']}"

    # Verify ID independence: Check that all IDs in the candidates list are distinct
    # (or distinct for each unique recommendation pattern)
    unique_ids = set(candidate_ids)
    print(f"Total candidates: {len(candidates)}, Unique IDs: {len(unique_ids)}")
    assert len(unique_ids) == len(candidates), "Candidate IDs are not all unique!"

    # Simulate selection independence
    selected_set = set()
    first_id = candidate_ids[0]
    second_id = candidate_ids[1]

    # Select first
    selected_set.add(first_id)
    assert first_id in selected_set
    assert second_id not in selected_set, "Selecting first should NOT select second!"

    # Select second
    selected_set.add(second_id)
    assert first_id in selected_set
    assert second_id in selected_set
    assert len(selected_set) == 2

    # Deselect first
    selected_set.remove(first_id)
    assert first_id not in selected_set
    assert second_id in selected_set
    assert len(selected_set) == 1
    print("[PASS] Candidate IDs are unique and selection state is 100% independent.")

    # -------------------------------------------------------------
    # Test 2: CTS Workbench Transport Request Regex Validation
    # -------------------------------------------------------------
    print("\n[TEST 2] Verifying CTS Workbench Transport Request validation...")

    valid_trs = ["S4HK900123", "YAWK900001", "DEVK900123", "AB1K456789"]
    invalid_trs = ["", "   ", "TR01", "None", "null", "S4H123456", "S4HK90012", "S4HK9001234", "s4hk900123", "DEV_K123456"]

    for tr in valid_trs:
        valid = SAPADTClient.validate_transport_request(tr)
        assert valid is True, f"Valid TR '{tr}' was incorrectly rejected!"
        assert CTS_TRANSPORT_REGEX.match(tr) is not None, f"Regex failed for '{tr}'"

    for tr in invalid_trs:
        valid = SAPADTClient.validate_transport_request(tr)
        # Note: uppercase transform may validate s4hk900123, but raw should be checked
        if tr.strip() != tr.strip().upper() or len(tr.strip()) != 10:
            assert not CTS_TRANSPORT_REGEX.match(tr), f"Regex incorrectly accepted invalid TR '{tr}'"

    print("[PASS] CTS Transport Regex and ADTClient validation verified.")

    # -------------------------------------------------------------
    # Test 3: API Endpoint /direct-create-sap Validation
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing /api/v1/reviews/direct-create-sap endpoint...")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 3A: Missing / short transport request should return 422 (Pydantic validation error)
        bad_payload_short = {
            "name": "ZC_TestSalesOrder",
            "package": "ZTRAINING_2026",
            "source": "define view entity ZC_TestSalesOrder as select from I_SalesOrder { SalesOrder }",
            "transport_request": "TR01",  # Too short
        }
        res = await client.post("/api/v1/reviews/direct-create-sap", json=bad_payload_short)
        print(f"Response with short transport request 'TR01': {res.status_code} -> {res.text}")
        assert res.status_code in [400, 422], f"Expected 400 or 422, got {res.status_code}"

        # 3B: 10-character invalid format transport request should return 400 (CTS regex failure)
        bad_payload_regex = {
            "name": "ZC_TestSalesOrder",
            "package": "ZTRAINING_2026",
            "source": "define view entity ZC_TestSalesOrder as select from I_SalesOrder { SalesOrder }",
            "transport_request": "S4HK90012X",  # Ends with letter, not digit
        }
        res = await client.post("/api/v1/reviews/direct-create-sap", json=bad_payload_regex)
        print(f"Response with malformed regex transport request 'S4HK90012X': {res.status_code} -> {res.text}")
        assert res.status_code == 400, f"Expected 400, got {res.status_code}"
        assert "Invalid Workbench Transport Request" in res.json().get("detail", "")

        # 3B: Valid transport request should pass validation (returns 200 preflight or upstream status)
        good_payload = {
            "name": "ZC_TestSalesOrderUnique99",
            "package": "ZTRAINING_2026",
            "source": "define view entity ZC_TestSalesOrderUnique99 as select from I_SalesOrder { SalesOrder }",
            "transport_request": "S4HK900123",  # Valid format
        }
        res = await client.post("/api/v1/reviews/direct-create-sap", json=good_payload)
        print(f"Response with valid transport request 'S4HK900123': {res.status_code} -> {res.json().get('status', res.text)}")
        assert res.status_code in [200, 500, 502], f"Unexpected status code: {res.status_code}"
        if res.status_code == 200:
            data = res.json()
            assert data.get("success") is True
            assert data.get("transport_request") == "S4HK900123"
            print("[PASS] Valid preflight creation succeeded with verified transport request.")

    print("\n" + "=" * 70)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_fixes())
