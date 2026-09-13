"""Milestone 8: Interactive Real SAP DEV Verification Script.

Executes the 5-phase controlled live verification sequence against SAP S/4HANA DEV:
    Phase 0: Offline Preflight & Safety Gate Verification
    Phase 1: Real SAP ADT Read-Only Smoke Test
    Phase 2: Real CDS Search
    Phase 3: Real DDL Source Retrieval
    Phase 4: Real Read-Only ADT Checkrun on Existing Repository Object

Usage:
    python scripts/verify_live_sap.py
"""

import asyncio
import sys
import time
from src.config import get_settings
from src.core.exceptions import SAPSecurityError, SAPConnectorError
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector


def print_step(step_num: int, title: str):
    print(f"\n[{step_num}/4] {title}")
    print("-" * 60)


async def main():
    print("=" * 60)
    print("SAP CDS Platform — Milestone 8 Live Integration Verifier")
    print("=" * 60)

    settings = get_settings()

    # --- Phase 0: Offline Preflight & Safety Checks ---
    print("\n[Phase 0] Offline Preflight & Safety Checks")
    print("-" * 60)
    print(f"SAP Base URL:        {settings.SAP_BASE_URL or '(not configured)'}")
    print(f"SAP Client:          {settings.SAP_CLIENT}")
    print(f"SAP Auth Type:       {settings.SAP_AUTH_TYPE}")
    print(f"SAP Username:        {settings.SAP_USERNAME or '(not configured)'}")
    print(f"SAP Password:        {'[CONFIGURED & MASKED]' if settings.SAP_PASSWORD.get_secret_value() else '(empty)'}")
    print(f"SAP Verify SSL:      {settings.SAP_VERIFY_SSL}")
    print(f"SAP Live Read-Only:  {settings.SAP_LIVE_READ_ONLY}")

    if not settings.SAP_LIVE_READ_ONLY:
        print("\n[ERROR] Safety Kill Switch active: SAP_LIVE_READ_ONLY must be set to 'true'.")
        print("To proceed safely, set $env:SAP_LIVE_READ_ONLY='true' or add to .env.")
        sys.exit(1)

    if not settings.SAP_BASE_URL:
        print("\n[ERROR] SAP_BASE_URL is not configured. Set SAP_BASE_URL in .env.")
        sys.exit(1)

    # Test pre-socket security guard offline
    client = SAPADTClient(settings=settings)
    try:
        client.assert_zero_write_policy("POST", "/sap/bc/adt/ddic/ddl/sources")
        print("[FAIL] Pre-socket security guard failed to block forbidden POST.")
        sys.exit(1)
    except SAPSecurityError:
        print("[PASS] Pre-socket zero-write security guard is ACTIVE and blocking modifications.")

    # --- Phase 1: Real SAP ADT Read-Only Smoke Test ---
    print_step(1, "Phase 1: Real SAP ADT Read-Only Smoke Test")
    t0 = time.time()
    try:
        is_connected = await client.check_connectivity()
        elapsed = time.time() - t0
        if is_connected:
            print(f"[PASS] Authenticated ADT smoke test succeeded in {elapsed:.2f}s.")
        else:
            print(f"[FAIL] ADT smoke test failed (returned False) in {elapsed:.2f}s.")
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        sys.exit(1)

    # --- Phase 2: Real CDS Search ---
    print_step(2, "Phase 2: Real CDS Repository Search (query=DDLSALES*)")
    t0 = time.time()
    try:
        search_results = await client.search_information_system("DDLSALES*", max_results=10)
        elapsed = time.time() - t0
        print(f"[PASS] Search returned {len(search_results)} objects in {elapsed:.2f}s:")
        for item in search_results[:5]:
            print(f"       - {item.get('name')} ({item.get('type')} in package '{item.get('package')}')")
        if len(search_results) > 5:
            print(f"       ... and {len(search_results) - 5} more")
    except Exception as e:
        print(f"[ERROR] Search failed: {e}")
        sys.exit(1)

    # --- Phase 3: Real DDL Source Retrieval ---
    print_step(3, "Phase 3: Real CDS DDL Source Retrieval (I_SalesOrder)")
    t0 = time.time()
    try:
        connector = SAPADTConnector(settings=settings)
        meta = await connector.get_cds_metadata("i_salesorder")
        elapsed = time.time() - t0
        print(f"[PASS] Retrieved and parsed DDL for '{meta.view_name}' in {elapsed:.2f}s:")
        print(f"       Fields:       {len(meta.fields)} fields extracted")
        print(f"       Associations: {len(meta.associations)} associations extracted")
        print(f"       Sample fields: {', '.join([f.field_name for f in meta.fields[:5]])}...")
    except Exception as e:
        print(f"[ERROR] DDL retrieval failed: {e}")
        sys.exit(1)

    # --- Phase 4: Real Read-Only ADT Checkrun ---
    print_step(4, "Phase 4: Real Read-Only ADT Checkrun on Repository Object")
    repo_uri = "/sap/bc/adt/ddic/ddl/sources/i_salesorder"
    t0 = time.time()
    try:
        checkrun_result = await client.run_checkrun(repo_uri)
        elapsed = time.time() - t0
        print(f"[PASS] Checkrun executed against {repo_uri} in {elapsed:.2f}s:")
        print(f"       Status:       {checkrun_result.status.value}")
        print(f"       Reporter:     {checkrun_result.reporter}")
        print(f"       Messages:     {len(checkrun_result.messages)} compiler diagnostic(s)")
        for msg in checkrun_result.messages[:3]:
            pos = f"L{msg.line}:{msg.column}" if msg.line else "Header"
            print(f"       [{msg.severity}] ({pos}) {msg.short_text} (ID: {msg.msgid})")
    except Exception as e:
        print(f"[ERROR] Checkrun failed: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("ALL 4 REAL SAP DEV VERIFICATION PHASES COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
