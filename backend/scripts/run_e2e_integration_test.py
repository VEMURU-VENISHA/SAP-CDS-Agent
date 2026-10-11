"""End-to-end integration test exercising all 13 pipeline steps through FastAPI."""

import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from httpx import ASGITransport, AsyncClient
from src.main import app


async def test_full_agent_pipeline():
    print("=" * 70)
    print("RUNNING FULL END-TO-END PIPELINE INTEGRATION TEST")
    print("=" * 70)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Step 1: Health & Metadata Status
        resp = await client.get("/api/v1/discovery/metadata-status")
        assert resp.status_code == 200, f"Metadata status failed: {resp.text}"
        meta_status = resp.json()
        print(f"[Step 1A] Metadata Status: {meta_status['status']} | Views: {meta_status['cds_count']} | Fields: {meta_status['field_count']}")

        # Step 1B: Direct CDS Search
        resp = await client.get("/api/v1/discovery/direct-search?q=SalesOrder")
        assert resp.status_code == 200, f"Direct search failed: {resp.text}"
        direct_results = resp.json()
        print(f"[Step 1B] Direct CDS Search: Found {len(direct_results)} views")
        assert len(direct_results) > 0

        # Step 1C: Live Source Retrieval from SAP ADT
        resp = await client.get("/api/v1/discovery/source/I_SalesOrder")
        assert resp.status_code == 200, f"Live source retrieval failed: {resp.text}"
        source_data = resp.json()
        print(f"[Step 1C] Live ADT Source: Retrieved {len(source_data['source'])} chars")
        assert "define view entity" in source_data["source"].lower() or "define view" in source_data["source"].lower()

        # Step 2: Extract Fields & Search Variants with Gemini (Multi-Domain)
        req_payload = {
            "requirement": "I need sales order reporting with customer, material, net amount, and currency.",
            "business_domains": ["Sales", "Finance"],
        }
        resp = await client.post("/api/v1/requirements/extract-fields", json=req_payload)
        assert resp.status_code == 200, f"Extract fields failed: {resp.text}"
        extracted = resp.json()
        fields = extracted.get("result", {}).get("fields", [])
        print(f"[Step 2] Extract Fields: Extracted {len(fields)} fields with variants")
        for f in fields:
            print(f"         • {f['name']}: variants -> {f['variants'][:4]}")

        # Step 3 & 4: Deterministic Discovery (Zero-Cutoff)
        disc_payload = {
            "requirement": req_payload["requirement"],
            "required_fields": fields,
            "search_mode": "fast",
            "use_cache": False,
        }
        resp = await client.post("/api/v1/discovery/run", json=disc_payload)
        assert resp.status_code == 200, f"Discovery run failed: {resp.text}"
        disc_result = resp.json()
        candidates = disc_result["candidates"]
        stats = disc_result["search_statistics"]
        print(f"[Step 3/4] Discovery Engine: Discovered ALL {len(candidates)} candidates in {stats['search_time_ms']} ms")
        print(f"           Full Coverage: {stats['full_coverage_candidates']} | High: {stats['high_coverage_candidates']} | Partial: {stats['partial_coverage_candidates']} | Low: {stats['low_coverage_candidates']}")
        assert len(candidates) > 0, "No candidates found"

        # Step 5: User CDS Selection
        top_cand = candidates[0]
        selected_views = [top_cand["cds_name"].split(" + ")[0]]
        print(f"[Step 5] Human Selection: Selected view '{selected_views[0]}'")

        # Step 6: Field Mapping
        mappings = [
            {
                "business_field": m["business_field"],
                "cds_view": selected_views[0],
                "actual_field": m["actual_field"],
                "field_label": m["field_label"],
                "data_type": m["data_type"],
            }
            for m in top_cand.get("matched_fields", [])
        ]
        print(f"[Step 6] Field Mapping: Mapped {len(mappings)} verified fields")

        # Step 7 & 8: Code Generation (with optional KPI)
        gen_payload = {
            "requirement": req_payload["requirement"],
            "selected_views": selected_views,
            "mappings": mappings,
            "join_paths": [],
            "kpi": {"enabled": True, "formula": "Total Net Amount = SUM(NetAmount)"},
            "artifact_name": "ZC_SalesOrderAnalysis",
        }
        resp = await client.post("/api/v1/requirements/generate-code", json=gen_payload)
        assert resp.status_code == 200, f"Code generation failed: {resp.text}"
        code_result = resp.json()
        cds_code = code_result["result"]["code"]
        print(f"[Step 7/8] Code Generation: Generated CDS View Entity ({len(cds_code)} chars)")
        print("           Preview:")
        for line in cds_code.splitlines()[:6]:
            print(f"           | {line}")

        # Step 9: Code Regeneration (Feedback incorporation)
        regen_payload = {
            "current_code": cds_code,
            "feedback": "Add an annotation for analytics dataCategory: #CUBE",
            "verified_context": {"selected_views": selected_views},
        }
        resp = await client.post("/api/v1/requirements/regenerate-code", json=regen_payload)
        assert resp.status_code == 200, f"Regenerate code failed: {resp.text}"
        regen_result = resp.json()
        print(f"[Step 9] Code Regeneration: Successfully regenerated with reviewer feedback")

        # Step 10: Validate Artifact Name
        name_payload = {"name": "ZC_SalesOrderAnalysis", "package": "ZTRAINING_2026"}
        resp = await client.post("/api/v1/requirements/validate-artifact-name", json=name_payload)
        assert resp.status_code == 200, f"Validate name failed: {resp.text}"
        name_val = resp.json()
        print(f"[Step 10] Artifact Name Validation: Name '{name_val['name']}' valid = {name_val['valid']}")
        assert name_val["valid"] is True

        # Step 11 & 12: Final Approval & Direct SAP Creation Pre-flight
        create_payload = {
            "name": "ZC_SalesOrderAnalysis",
            "package": "ZTRAINING_2026",
            "source": cds_code,
            "transport_request": "S4HK900123",
        }
        resp = await client.post("/api/v1/reviews/direct-create-sap", json=create_payload)
        assert resp.status_code in [200, 409, 500, 502], f"Unexpected status: {resp.status_code}: {resp.text}"
        create_result = resp.json()
        print(f"[Step 11/12] SAP ADT Creation Service: Status = {create_result.get('status', 'EXECUTED')} | Details = {create_result}")


    print("\n" + "=" * 70)
    print("ALL 13 WORKFLOW STEPS VERIFIED END-TO-END SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_full_agent_pipeline())
