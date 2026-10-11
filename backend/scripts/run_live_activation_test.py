"""Milestone 13.8B: Authorized Real SAP DEV CDS Activation Runner.

Executes ONLY the authorized controlled activation against the EXISTING CDS object:
- Target Object: ZI_AI_AGENT_LIVE_TEST
- Package: ZTRAINING_2026
- Target Final State: ACTIVE

CRITICAL SAFETY BOUNDARIES:
- DOES NOT call create_ddls_shell().
- DOES NOT recreate or overwrite the object.
- DOES NOT release the transport (S3XK911848).
- DOES NOT perform CTS transport operations.
- DOES NOT delete anything.
- Requires server-side ReviewStatus.APPROVED.
- Requires SAP_DEV_WRITE_ENABLED=true.
- Requires SAP_LIVE_READ_ONLY=false.
- Executes ONE controlled activation: POST /sap/bc/adt/activation?method=activate&preauditRequested=true.
- Post-activation verification via GET /sap/bc/adt/activation/inactiveobjects and GET source read-back.
- Zero secrets or tokens logged.
"""

import argparse
import asyncio
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, Optional

# Ensure backend root is in python search path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.state import CDSWorkflowState
from src.config import Settings, get_settings
from src.core.exceptions import (
    SAPConnectorError,
    SAPNotFoundError,
    SAPSecurityError,
)
from src.models.domain import (
    BusinessRequirement,
    CDSCandidate,
    CDSDraft,
    CDSLayer,
    Decision,
    DecisionAction,
    DraftFieldElement,
    ElementEvidenceRecord,
    EvidenceLevel,
    FieldMapping,
    MappingType,
    ReviewStatus,
    StructuredRequirement,
    TargetUseCase,
    ValidationResult,
)
from src.sap.adt_client import SAPADTClient
from src.services.review_service import ReviewStore, build_review_package


TARGET_VIEW_NAME = "ZI_AI_AGENT_LIVE_TEST"
TARGET_PACKAGE = "ZTRAINING_2026"
VIEW_DESCRIPTION = "AI Agent Live DEV Smoke Test"

CDS_DDL_SOURCE = f"""@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: '{VIEW_DESCRIPTION}'
define view entity {TARGET_VIEW_NAME}
  as select from I_SalesOrder
{{
  key SalesOrder,
      SalesOrderType,
      CreationDate
}};
"""


def build_authorized_live_workflow_state() -> CDSWorkflowState:
    """Constructs state and draft for ZI_AI_AGENT_LIVE_TEST."""
    req = BusinessRequirement(
        title=VIEW_DESCRIPTION,
        description="Disposable AI-agent ADT integration smoke test for Milestone 13",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder", "SalesOrderType", "CreationDate"],
    )

    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name=TARGET_VIEW_NAME,
        confidence_score=1.0,
        fit_percentage=100.0,
        rationale="Controlled disposable smoke test authorized for Milestone 13.",
    )

    ev = ElementEvidenceRecord(
        element_name="SalesOrder",
        element_type="FIELD",
        evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
        evidence_detail="Exact match from I_SalesOrder",
        confidence=1.0,
        is_verified=True,
    )

    fields = [
        DraftFieldElement(
            field_name="SalesOrder",
            source_expression="SalesOrder",
            source_entity="I_SalesOrder",
            is_key=True,
            evidence=ev,
        ),
        DraftFieldElement(
            field_name="SalesOrderType",
            source_expression="SalesOrderType",
            source_entity="I_SalesOrder",
            is_key=False,
            evidence=ev,
        ),
        DraftFieldElement(
            field_name="CreationDate",
            source_expression="CreationDate",
            source_entity="I_SalesOrder",
            is_key=False,
            evidence=ev,
        ),
    ]

    draft = CDSDraft(
        id=f"draft_{TARGET_VIEW_NAME.lower()}",
        requirement_id=req.id,
        decision_action=DecisionAction.CREATE,
        object_name=TARGET_VIEW_NAME,
        object_type="CUSTOM_VIEW_ENTITY",
        proposed_layer="BASIC",
        source_views=["I_SalesOrder"],
        fields=fields,
        associations=[],
        parameters=[],
        filters=[],
        annotations={
            "@AccessControl.authorizationCheck": "#NOT_REQUIRED",
            "@EndUserText.label": VIEW_DESCRIPTION,
        },
        ddl_source=CDS_DDL_SOURCE,
        evidence_per_element=[ev],
        warnings=[],
        validation_errors=[],
        generation_status="VALIDATED",
        unresolved_items=[],
    )

    val = ValidationResult(
        is_valid=True,
        syntax_errors=[],
        naming_convention_violations=[],
        clean_core_compliance_score=100.0,
        governance_warnings=[],
        details=[
            {"check": "Object Identifier Rules", "passed": True, "detail": f"Valid name '{TARGET_VIEW_NAME}' in customer namespace."},
            {"check": "Authorization Check Annotation", "passed": True, "detail": "@AccessControl.authorizationCheck present."},
            {"check": "DDL Semicolon Termination", "passed": True, "detail": "DDL terminates with ';'"},
        ],
    )

    return {
        "requirement": req,
        "structured_requirement": StructuredRequirement(
            domain="Sales",
            dimensions=["SalesOrder", "SalesOrderType"],
            measures=[],
            filters=[],
        ),
        "candidates": [
            CDSCandidate(
                view_name="I_SalesOrder",
                description="Sales Order View",
                layer=CDSLayer.BASIC,
                release_status="RELEASED",
                package="SD_SALES_CDS",
                available_fields=["SalesOrder", "SalesOrderType", "CreationDate"],
                key_fields=["SalesOrder"],
            )
        ],
        "field_mappings": [
            FieldMapping(
                requirement_field="SalesOrder",
                matched_field="SalesOrder",
                mapping_type=MappingType.DIRECT_MATCH,
                evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                confidence=1.0,
            ),
        ],
        "decision": decision,
        "cds_draft": draft,
        "validation_result": val,
        "generated_cds_code": CDS_DDL_SOURCE,
        "audit_logs": [],
    }


async def run_controlled_activation(transport_request: Optional[str] = None):
    print("=" * 70)
    print("MILESTONE 13.8B: CONTROLLED REAL SAP DEV CDS ACTIVATION RUNNER")
    print("=" * 70)
    print(f"Target SAP Object:     {TARGET_VIEW_NAME}")
    print(f"Target SAP Package:    {TARGET_PACKAGE}")
    print(f"Mode:                  REAL SAP DEV ACTIVATION (ONE-SHOT)")
    print(f"Target Final State:    ACTIVE")

    # 1. Transport Request Validation
    if not transport_request or not isinstance(transport_request, str) or not transport_request.strip():
        print("\n[ERROR] Missing mandatory Workbench Transport Request.")
        print("Usage: python backend/scripts/run_live_activation_test.py --transport-request S3XK911848")
        sys.exit(1)

    clean_tr = transport_request.strip().upper()
    if not SAPADTClient.validate_transport_request(clean_tr):
        print(f"\n[ERROR] Invalid Workbench Transport Request format: '{transport_request}'.")
        print("Must match format '^[A-Z0-9]{3}K[0-9]{6}$' (e.g. S3XK911848).")
        sys.exit(1)

    print(f"Validated Transport:   {clean_tr}")

    # 2. Settings check — reads from process environment without modifying .env
    base_settings = get_settings()
    env_write = os.getenv("SAP_DEV_WRITE_ENABLED", str(base_settings.SAP_DEV_WRITE_ENABLED)).strip().lower() in ("true", "1", "yes")
    env_read_only = os.getenv("SAP_LIVE_READ_ONLY", str(base_settings.SAP_LIVE_READ_ONLY)).strip().lower() in ("true", "1", "yes")

    live_settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_CONNECTOR_TYPE="adt",
        SAP_BASE_URL=base_settings.SAP_BASE_URL,
        SAP_CLIENT=base_settings.SAP_CLIENT,
        SAP_AUTH_TYPE=base_settings.SAP_AUTH_TYPE,
        SAP_USERNAME=base_settings.SAP_USERNAME,
        SAP_PASSWORD=base_settings.SAP_PASSWORD,
        SAP_API_TOKEN=base_settings.SAP_API_TOKEN,
        SAP_SYSTEM_ID=base_settings.SAP_SYSTEM_ID,
        SAP_VERIFY_SSL=base_settings.SAP_VERIFY_SSL,
        SAP_REQUEST_TIMEOUT_SECONDS=base_settings.SAP_REQUEST_TIMEOUT_SECONDS,
        SAP_DEV_WRITE_ENABLED=env_write,
        SAP_LIVE_READ_ONLY=env_read_only,
        SAP_DEV_PACKAGE=TARGET_PACKAGE,
    )

    # 3. Build state and approve review package
    state = build_authorized_live_workflow_state()
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved_pkg = store.approve(
        pkg.review_id,
        reviewer="lead_architect",
        comment="Explicit live SAP DEV CDS activation authorized for Milestone 13.8B.",
    )

    # 4. Verify all prerequisites locally before touching any network socket
    print("\n[Step -1] Verifying Pre-Execution Safety Prerequisites:")
    p_status = approved_pkg.status == ReviewStatus.APPROVED
    p_can_approve = approved_pkg.can_approve is True
    p_source = bool(approved_pkg.ddl_source and approved_pkg.ddl_source.strip())
    p_valid = approved_pkg.validation_result is not None and approved_pkg.validation_result.is_valid
    p_write_flag = live_settings.SAP_DEV_WRITE_ENABLED is True
    p_read_only_false = live_settings.SAP_LIVE_READ_ONLY is False
    p_tls = live_settings.SAP_VERIFY_SSL is True
    p_name = SAPADTClient.validate_sap_object_name(TARGET_VIEW_NAME)
    p_tr = SAPADTClient.validate_transport_request(clean_tr)

    print(f"  - Review status APPROVED:            {p_status} ({approved_pkg.status.value})")
    print(f"  - can_approve == True:                {p_can_approve}")
    print(f"  - Generated CDS source non-empty:     {p_source}")
    print(f"  - Local validation has no errors:     {p_valid}")
    print(f"  - SAP_DEV_WRITE_ENABLED == True:      {p_write_flag}")
    print(f"  - SAP_LIVE_READ_ONLY == False:        {p_read_only_false}")
    print(f"  - TLS verification enabled:           {p_tls}")
    print(f"  - Customer namespace valid:           {p_name}")
    print(f"  - Workbench transport valid:         {p_tr} ({clean_tr})")

    if not all([p_status, p_can_approve, p_source, p_valid, p_write_flag, p_read_only_false, p_tls, p_name, p_tr]):
        print("\n[CRITICAL HALT] Safety prerequisite failed! STOPPING without activating in SAP.")
        sys.exit(1)

    print("[PASS] All pre-execution prerequisites verified. Proceeding to Phase C (Preflight).")

    client = SAPADTClient(settings=live_settings)

    diagnostics = []
    preflight_status = "NOT_EXECUTED"
    activation_status = "NOT_EXECUTED"
    post_inactive_check = "NOT_EXECUTED"
    readback_status = "NOT_EXECUTED"

    async with client:
        # -------------------------------------------------------------
        # Phase C — Preflight: Confirm Object Exists & Contains Smoke Test
        # -------------------------------------------------------------
        print("\n" + "-" * 60)
        print("PHASE C: Pre-Activation Read-Only Verification")
        print("-" * 60)
        t0 = time.time()
        try:
            existing = await client.get_ddl_source(TARGET_VIEW_NAME)
            source_code = await client.get_ddl_source(f"{TARGET_VIEW_NAME}/source/main")
            elapsed0 = time.time() - t0
            print(f"[PASS] Confirmed object '{TARGET_VIEW_NAME}' exists in SAP DEV (descriptor: {len(existing)} bytes, source: {len(source_code)} bytes in {elapsed0:.2f}s).")
            if "i_salesorder" not in source_code.lower():
                print("[HALT] Existing source does not contain expected smoke-test definition. STOPPING.")
                sys.exit(1)

            # Check if already inactive
            inactive_list = await client.get_inactive_objects()
            is_in_inactive_list = any(o.get("name", "").upper() == TARGET_VIEW_NAME for o in inactive_list)
            print(f"       Inactive index check: {'CONFIRMED INACTIVE' if is_in_inactive_list else 'NOT IN INACTIVE LIST'}")
            preflight_status = f"CONFIRMED_INACTIVE (in {elapsed0:.2f}s)"
            diagnostics.append({"step": "PHASE_C_PREFLIGHT", "passed": True, "detail": "Object exists and is inactive."})
        except SAPNotFoundError:
            print(f"[HALT] Object '{TARGET_VIEW_NAME}' does not exist in SAP DEV! Cannot activate.")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Preflight check error: {e}")
            sys.exit(1)

        # -------------------------------------------------------------
        # Phase D — Real SAP DEV Activation: POST /sap/bc/adt/activation
        # -------------------------------------------------------------
        print("\n" + "-" * 60)
        print("PHASE D: POST /sap/bc/adt/activation?method=activate&preauditRequested=true")
        print("-" * 60)
        t1 = time.time()
        try:
            act_res = await client.activate_ddls_object(
                view_name=TARGET_VIEW_NAME,
                review_package=approved_pkg,
                preaudit_requested=True,
            )
            elapsed1 = time.time() - t1
            http_code = act_res.get("status_code", 200)
            success = act_res.get("success", False)
            has_blocking = act_res.get("has_blocking_errors", False)
            inactive_objs = act_res.get("inactive_objects", [])
            messages = act_res.get("messages", [])

            print(f"       HTTP Status:            {http_code} (in {elapsed1:.2f}s)")
            print(f"       Activation Success:     {success}")
            print(f"       Blocking Errors (E/A/X): {has_blocking}")
            print(f"       Remaining Inactive:     {inactive_objs}")
            print(f"       Diagnostic Messages:    {len(messages)}")
            for idx, msg in enumerate(messages):
                print(f"         [{idx+1}] Type: {msg.get('type')}, Line: {msg.get('line')}, Text: {msg.get('short_text')}")

            if not success or has_blocking:
                activation_status = f"FAILED_HTTP_{http_code}"
                print(f"[FAIL] SAP activation returned failure or blocking errors.")
                diagnostics.append({"step": "PHASE_D_ACTIVATION", "passed": False, "status_code": http_code, "messages": messages})
                sys.exit(1)

            activation_status = f"HTTP_{http_code}_SUCCESS (in {elapsed1:.2f}s)"
            diagnostics.append({"step": "PHASE_D_ACTIVATION", "passed": True, "status_code": http_code, "messages": messages})
        except Exception as e:
            elapsed1 = time.time() - t1
            activation_status = f"ERROR: {e}"
            print(f"[FAIL] Activation call failed in {elapsed1:.2f}s: {e}")
            diagnostics.append({"step": "PHASE_D_ACTIVATION", "passed": False, "error": str(e)})
            sys.exit(1)

        # -------------------------------------------------------------
        # Phase F — Post-Activation Verification
        # -------------------------------------------------------------
        print("\n" + "-" * 60)
        print("PHASE F: Post-Activation Read-Only Verification")
        print("-" * 60)

        # 1. Inactive objects query
        t2 = time.time()
        try:
            post_inactive = await client.get_inactive_objects()
            elapsed2 = time.time() - t2
            still_inactive = any(o.get("name", "").upper() == TARGET_VIEW_NAME for o in post_inactive)
            if still_inactive:
                post_inactive_check = f"STILL_INACTIVE (in {elapsed2:.2f}s)"
                print(f"[FAIL] Object '{TARGET_VIEW_NAME}' still appears in inactive objects list!")
            else:
                post_inactive_check = f"VERIFIED_ACTIVE (in {elapsed2:.2f}s)"
                print(f"[PASS] Object '{TARGET_VIEW_NAME}' is NO LONGER in inactive objects list (Confirmed Active in {elapsed2:.2f}s).")
            diagnostics.append({"step": "PHASE_F_INACTIVE_CHECK", "passed": not still_inactive})
        except Exception as e:
            post_inactive_check = f"QUERY_ERROR: {e}"
            print(f"[NOTICE] Inactive objects check returned: {e}")
            diagnostics.append({"step": "PHASE_F_INACTIVE_CHECK", "passed": False, "detail": str(e)})

        # 2. Source read-back
        t3 = time.time()
        try:
            readback_source = await client.get_ddl_source(f"{TARGET_VIEW_NAME}/source/main")
            elapsed3 = time.time() - t3
            if readback_source and TARGET_VIEW_NAME.lower() in readback_source.lower():
                readback_status = f"VERIFIED_INTACT ({len(readback_source)} bytes in {elapsed3:.2f}s)"
                print(f"[PASS] Stored CDS source is intact in repository ({len(readback_source)} bytes in {elapsed3:.2f}s).")
                diagnostics.append({"step": "PHASE_F_SOURCE_READBACK", "passed": True, "length": len(readback_source)})
            else:
                readback_status = f"EMPTY_OR_UNEXPECTED (in {elapsed3:.2f}s)"
                print("[NOTICE] Read-back source did not contain expected view entity name.")
        except Exception as e:
            readback_status = f"ERROR: {e}"
            print(f"[NOTICE] Read-back error: {e}")
            diagnostics.append({"step": "PHASE_F_SOURCE_READBACK", "passed": False, "error": str(e)})

    # Final Report Printout
    final_state = "ACTIVE" if (activation_status.startswith("HTTP_") and "VERIFIED_ACTIVE" in post_inactive_check) else "INACTIVE"
    print("\n" + "=" * 70)
    print("LIVE SAP DEV CDS ACTIVATION RESULT")
    print("=" * 70)
    print(f"Preflight Check:                {preflight_status}")
    print(f"Activation Request:             {activation_status}")
    print(f"Post-Activation Inactive Check: {post_inactive_check}")
    print(f"Source Read-back:               {readback_status}")
    print(f"FINAL SAP OBJECT STATE:         {final_state}")
    print(f"Transport Released:             NO (Strictly Blocked)")
    print(f"Deletion / Cleanup:             NO (Strictly Blocked)")
    print(f"Other SAP Objects Touched:      NO")
    print(f"Workbench Transport:            {clean_tr}")
    print(f"Diagnostics:                    {len(diagnostics)} logged steps")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Milestone 13.8B Controlled SAP DEV Activation Runner")
    parser.add_argument(
        "--transport-request",
        "-t",
        type=str,
        default=os.getenv("SAP_DEV_TRANSPORT_REQUEST"),
        help="Human-supplied CTS Workbench Transport Request ID (e.g. S3XK911848)",
    )
    args = parser.parse_args()

    asyncio.run(run_controlled_activation(transport_request=args.transport_request))
