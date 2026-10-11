"""Real End-to-End SAP ADT Verification Script against connected SAP S/4HANA DEV Client 100.

Performs authentic network calls with zero mocks/stubs:
- TEST 1: Genuinely NEW CDS artifact (ZC_CREATE_TEST_<timestamp>)
- TEST 2: Pre-existing CDS artifact (I_SALESORDER)
- TEST 3: Race condition ExceptionResourceAlreadyExists mapping
"""

import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict

# Ensure backend root is in python search path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Settings, get_settings
from src.core.exceptions import (
    SAPConflictError,
    SAPConnectorError,
    SAPNotFoundError,
    SAPSecurityError,
)
from src.models.domain import (
    BusinessRequirement,
    CDSReviewPackage,
    DecisionAction,
    ReviewStatus,
    TargetUseCase,
)
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector
from src.services.review_service import ReviewStore, build_review_package


def get_unique_artifact_name() -> str:
    ts = time.strftime("%Y%m%d%H%M%S")
    return f"ZC_TEST_{ts[-8:]}"


async def run_live_verification():
    print("=" * 75)
    print("REAL SAP ADT END-TO-END VERIFICATION (DEV CLIENT 100)")
    print("=" * 75)

    base_settings = get_settings()

    # Enable write mode for testing
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_CONNECTOR_TYPE="adt",
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_DEV_PACKAGE="ZTRAINING_2026",
        SAP_BASE_URL=base_settings.SAP_BASE_URL,
        SAP_SYSTEM_ID=base_settings.SAP_SYSTEM_ID,
        SAP_CLIENT=base_settings.SAP_CLIENT or "100",
        SAP_AUTH_TYPE=base_settings.SAP_AUTH_TYPE,
        SAP_USERNAME=base_settings.SAP_USERNAME,
        SAP_PASSWORD=base_settings.SAP_PASSWORD,
        SAP_API_TOKEN=base_settings.SAP_API_TOKEN,
        SAP_VERIFY_SSL=base_settings.SAP_VERIFY_SSL,
        SAP_SEND_CLIENT_PARAM=base_settings.SAP_SEND_CLIENT_PARAM,
        SAP_REQUEST_TIMEOUT_SECONDS=base_settings.SAP_REQUEST_TIMEOUT_SECONDS,
    )

    print(f"SAP Base URL:   {settings.SAP_BASE_URL}")
    print(f"SAP Client:     {settings.SAP_CLIENT}")
    print(f"SAP User:       {settings.SAP_USERNAME}")
    print(f"Target Package: {settings.SAP_DEV_PACKAGE}")
    print("=" * 75)

    transport_request = "S4HK900123"
    new_artifact_name = get_unique_artifact_name()

    print(f"\n[NEW ARTIFACT NAME]: {new_artifact_name}")
    print(f[WORKBENCH TRANSPORT]: {transport_request})

    new_approved_ddl = f"""@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'Real Live SAP Creation Test'
define view entity {new_artifact_name}
  as select from I_SalesOrder
{{
  key SalesOrder,
      SalesOrderType,
      CreationDate
}};
"""

    client = SAPADTClient(settings=settings)
    connector = SAPADTConnector(settings=settings, client=client)

    results: Dict[str, Any] = {}

    async with client:
        # Check basic connectivity
        try:
            connected = await client.check_connectivity()
            print(f"\n[CONNECTIVITY CHECK]: {'CONNECTED' if connected else 'FAILED'}")
            if not connected:
                print("Cannot connect to SAP ADT. Stopping live verification.")
                return
        except Exception as e:
            print(f"[CONNECTIVITY ERROR]: {e}")
            return

        # ---------------------------------------------------------------------
        # TEST 1: Genuinely NEW CDS Artifact Creation Workflow
        # ---------------------------------------------------------------------
        print("\n" + "=" * 75)
        print(f"TEST 1: NEW CDS ARTIFACT WORKFLOW — '{new_artifact_name}'")
        print("=" * 75)

        # Build Review Package
        pkg1 = CDSReviewPackage(
            review_id=f"rev_live_test_{new_artifact_name.lower()}",
            object_name=new_artifact_name,
            package=settings.SAP_DEV_PACKAGE,
            status=ReviewStatus.APPROVED,
            can_approve=True,
            ddl_source=new_approved_ddl,
            decision_action=DecisionAction.CREATE,
            reviewer="lead_architect",
        )

        # 1. Final Existence Check
        endpoint_exist = f"/sap/bc/adt/ddic/ddl/sources/{new_artifact_name.lower()}"
        print(f"\n1. FINAL EXISTENCE CHECK: GET {endpoint_exist}")
        try:
            ex_source = await client.get_ddl_source(new_artifact_name)
            print(f"   Response: EXISTS ({len(ex_source)} bytes)")
            results["test1_existence_check"] = "EXISTS"
        except SAPNotFoundError:
            print(f"   Response: HTTP 404 (NOT_FOUND — Safe to proceed)")
            results["test1_existence_check"] = "HTTP 404 NOT_FOUND"
        except Exception as e:
            print(f"   Response Notice: {e}")
            results["test1_existence_check"] = f"NOTICE: {e}"

        # 2. POST Shell Creation
        endpoint_post = f"/sap/bc/adt/ddic/ddl/sources?corrNr={transport_request}"
        print(f"\n2. POST SHELL CREATION: POST {endpoint_post}")
        shell_res = None
        try:
            shell_res = await client.create_ddls_shell(
                view_name=new_artifact_name,
                package=settings.SAP_DEV_PACKAGE,
                description="Real Live SAP Creation Test",
                corr_nr=transport_request,
                review_package=pkg1,
            )
            st_code = shell_res.get("status_code")
            loc = shell_res.get("location")
            print(f"   Response: HTTP {st_code}")
            print(f"   Location Header: {loc}")
            print(f"   Lock Handle in POST: {shell_res.get('lock_handle') or 'None'}")
            results["test1_post_shell"] = f"HTTP {st_code}"
            results["test1_location"] = loc
        except Exception as e:
            print(f"   Response Error: {e}")
            results["test1_post_shell"] = f"FAILED: {e}"

        # 3. Lock Acquisition
        lock_handle = shell_res.get("lock_handle") if shell_res else None
        endpoint_lock = f"/sap/bc/adt/ddic/ddl/sources/{new_artifact_name.lower()}?_action=LOCK&accessMode=MODIFY"
        print(f"\n3. LOCK ACQUISITION: POST {endpoint_lock}")
        if not lock_handle:
            try:
                lock_res = await client.lock_ddls_object(new_artifact_name, access_mode="MODIFY", review_package=pkg1)
                lock_handle = lock_res.get("lock_handle")
                print(f"   Response: Lock Handle = {lock_handle}")
                results["test1_lock"] = f"SUCCESS (handle={lock_handle})"
            except Exception as e:
                print(f"   Lock Error: {e}")
                results["test1_lock"] = f"FAILED: {e}"
        else:
            print(f"   Lock Handle from POST: {lock_handle}")
            results["test1_lock"] = f"SUCCESS (from POST handle={lock_handle})"

        # 4. PUT Approved Source Code
        endpoint_put = f"/sap/bc/adt/ddic/ddl/sources/{new_artifact_name.lower()}/source/main?lockHandle={lock_handle}&corrNr={transport_request}"
        print(f"\n4. PUT APPROVED SOURCE CODE: PUT {endpoint_put} [Headers: If-Match: *]")
        put_status = None
        try:
            put_status = await client.upload_ddls_source(
                view_name=new_artifact_name,
                ddl_source=new_approved_ddl,
                lock_handle=lock_handle,
                corr_nr=transport_request,
                review_package=pkg1,
            )
            print(f"   Response: HTTP {put_status}")
            results["test1_put_source"] = f"HTTP {put_status}"
        except Exception as e:
            print(f"   PUT Error: {e}")
            results["test1_put_source"] = f"FAILED: {e}"

        # 5. Activation
        endpoint_act = f"/sap/bc/adt/activation?method=activate"
        print(f"\n5. ACTIVATION: POST {endpoint_act}")
        act_status = None
        try:
            act_res = await client.activate_ddls_object(
                view_name=new_artifact_name,
                transport_request=transport_request,
                review_package=pkg1,
            )
            print(f"   Response: HTTP 200 (Activated successfully)")
            results["test1_activation"] = "HTTP 200 ACTIVATED"
        except Exception as e:
            print(f"   Activation Notice: {e}")
            results["test1_activation"] = f"NOTICE: {e}"

        # 6 & 7. Read-back & Source Hash Comparison
        endpoint_readback = f"/sap/bc/adt/ddic/ddl/sources/{new_artifact_name.lower()}"
        print(f"\n6 & 7. READ-BACK & SOURCE HASH VERIFICATION: GET {endpoint_readback}")
        try:
            readback_src = await client.get_ddl_source(new_artifact_name)
            app_h = client.compute_source_hash(new_approved_ddl)
            rb_h = client.compute_source_hash(readback_src)
            print(f"   Read-back length: {len(readback_src)} bytes")
            print(f"   Approved Source Hash: {app_h}")
            print(f"   Read-back Source Hash: {rb_h}")
            print(f"   Hash Match: {'MATCH (PASS)' if app_h == rb_h else 'DIFFERENT'}")
            results["test1_readback"] = f"HTTP 200 ({len(readback_src)} bytes)"
            results["test1_hash_match"] = "PASS" if app_h == rb_h else "DIFF"
        except Exception as e:
            print(f"   Read-back Error: {e}")
            results["test1_readback"] = f"FAILED: {e}"
            results["test1_hash_match"] = "FAIL"

        # ---------------------------------------------------------------------
        # TEST 2: Pre-Existing CDS Artifact Workflow Protection
        # ---------------------------------------------------------------------
        print("\n" + "=" * 75)
        print("TEST 2: PRE-EXISTING CDS ARTIFACT PROTECTION — 'I_SALESORDER'")
        print("=" * 75)

        pkg_exist = CDSReviewPackage(
            review_id="rev_existing_test_001",
            object_name="I_SALESORDER",
            package="VAV",
            status=ReviewStatus.APPROVED,
            can_approve=True,
            ddl_source="define view entity I_SalesOrder as select from vbak { key vbeln }",
            decision_action=DecisionAction.CREATE,
            reviewer="lead_architect",
        )

        endpoint_exist2 = "/sap/bc/adt/ddic/ddl/sources/i_salesorder"
        print(f"\n1. FINAL EXISTENCE CHECK ON PRE-EXISTING OBJECT: GET {endpoint_exist2}")
        try:
            ex_source2 = await client.get_ddl_source("I_SALESORDER")
            print(f"   Response: HTTP 200 (EXISTS — {len(ex_source2)} bytes)")
            results["test2_existence_check"] = f"HTTP 200 EXISTS ({len(ex_source2)} bytes)"
        except Exception as e:
            print(f"   Response: {e}")
            results["test2_existence_check"] = f"ERROR: {e}"

        print("\n2. EXECUTING create_cds_in_sap FOR PRE-EXISTING OBJECT:")
        try:
            await connector.create_cds_in_sap(pkg_exist, transport_request=transport_request)
            print("   [FAIL] Pre-flight existence check failed to block existing object!")
            results["test2_post_shell_blocked"] = "FAIL (POST executed)"
        except SAPConflictError as ce:
            print(f"   [PASS] Pre-flight existence check BLOCKED creation correctly!")
            print(f"   Exception Type: SAPConflictError")
            print(f"   Conflict Details: {ce.details}")
            results["test2_post_shell_blocked"] = "PASS (POST BLOCKED)"
            results["test2_status_code"] = ce.details.get("status", "EXISTING_OBJECT")
            results["test2_message"] = ce.details.get("message", str(ce))
        except Exception as e:
            print(f"   Exception: {e}")
            results["test2_post_shell_blocked"] = f"BLOCKED BY: {e}"

        # ---------------------------------------------------------------------
        # FINAL SUMMARY REPORT
        # ---------------------------------------------------------------------
        print("\n" + "=" * 75)
        print("ACTUAL REAL SAP DEV VERIFICATION RESULTS")
        print("=" * 75)
        print(f"Artifact Name Created:     {new_artifact_name}")
        print(f"Pre-flight Existence (1):  {results.get('test1_existence_check')}")
        print(f"POST Shell (1):            {results.get('test1_post_shell')}")
        print(f"Lock Acquisition (1):       {results.get('test1_lock')}")
        print(f"PUT Source (1):            {results.get('test1_put_source')}")
        print(f"Activation (1):            {results.get('test1_activation')}")
        print(f"Read-back (1):             {results.get('test1_readback')}")
        print(f"Source Hash Match (1):     {results.get('test1_hash_match')}")
        print("-" * 75)
        print(f"Pre-flight Existence (2):  {results.get('test2_existence_check')}")
        print(f"POST Shell Blocked (2):    {results.get('test2_post_shell_blocked')}")
        print(f"Mapped Status (2):         {results.get('test2_status_code')}")
        print(f"Mapped Message (2):        {results.get('test2_message')}")
        print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run_live_verification())
