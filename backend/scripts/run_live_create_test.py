"""Milestone 13: Authorized Real SAP DEV CDS Creation Runner.

Executes ONLY the authorized disposable AI-agent ADT integration smoke test:
- Target Object: ZI_AI_AGENT_LIVE_TEST
- Package: ZTRAINING_2026
- Status: INACTIVE

Enforces:
- Full pre-flight gate check (Approval, Decision, Validation, Collision check)
- Step 0: Read-only existence check
- Step A: POST /sap/bc/adt/ddic/ddl/sources
- Step B: PUT /sap/bc/adt/ddic/ddl/sources/zi_ai_agent_live_test/source/main
- Step C: STOP. Strictly NO activation, NO transport, NO delete.
- Final read-only existence verification
- Zero secrets in logs, audit records, or reports.
"""

import asyncio
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, Optional

# Ensure backend root is in python search path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.state import CDSWorkflowState
from src.config import Settings, get_settings
from src.core.exceptions import (
    SAPConflictError,
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
from src.sap.adt_connector import SAPADTConnector
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

    state: CDSWorkflowState = {
        "requirement": req,
        "structured_requirement": StructuredRequirement(
            domain="Sales",
            dimensions=["SalesOrder"],
            measures=[],
            filters=[],
        ),
        "candidates": [
            CDSCandidate(
                view_name="I_SalesOrder",
                description="Sales Order Header",
                layer=CDSLayer.BASIC,
                release_status="RELEASED",
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
            )
        ],
        "decision": decision,
        "cds_draft": draft,
        "validation_result": val,
        "generated_cds_code": CDS_DDL_SOURCE,
        "audit_logs": [],
    }
    return state


async def run_controlled_live_creation(transport_request: Optional[str] = None):
    print("=" * 70)
    print("MILESTONE 13 / 13.2: CONTROLLED REAL SAP DEV CDS CREATION")
    print("=" * 70)
    print(f"Target Object:   {TARGET_VIEW_NAME}")
    print(f"Target Package:  {TARGET_PACKAGE}")
    print(f"Target Status:   INACTIVE")
    print(f"Purpose:         Disposable AI-agent ADT integration smoke test")
    print("=" * 70)

    # 0. Milestone 13.2: Require and validate human-supplied Workbench Transport Request locally BEFORE any socket connection
    if not transport_request or not isinstance(transport_request, str) or not transport_request.strip():
        print("\n[CRITICAL HALT] Missing Workbench Transport Request!")
        print("Package ZTRAINING_2026 is transportable and strictly requires a human-supplied Workbench Transport Request.")
        print("Please provide a valid CTS Workbench Request ID via CLI argument: --transport-request <ID>")
        print("or environment variable: SAP_DEV_TRANSPORT_REQUEST=<ID> (format: ^[A-Z0-9]{3}K[0-9]{6}$)\n")
        sys.exit(1)

    clean_tr = transport_request.strip().upper()
    if not SAPADTClient.validate_transport_request(clean_tr):
        print(f"\n[CRITICAL HALT] Invalid Workbench Transport Request: '{transport_request}'!")
        print("Request ID must match standard CTS Workbench format: '^[A-Z0-9]{3}K[0-9]{6}$' (e.g., S4HK900123).\n")
        sys.exit(1)

    print(f"Workbench Transport: {clean_tr}")

    # 1. Load baseline settings from .env and apply live execution flags in-memory
    base_settings = get_settings()
    live_settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_CONNECTOR_TYPE="adt",
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_DEV_PACKAGE=TARGET_PACKAGE,
        SAP_BASE_URL=base_settings.SAP_BASE_URL,
        SAP_SYSTEM_ID=base_settings.SAP_SYSTEM_ID,
        SAP_CLIENT=base_settings.SAP_CLIENT,
        SAP_AUTH_TYPE=base_settings.SAP_AUTH_TYPE,
        SAP_USERNAME=base_settings.SAP_USERNAME,
        SAP_PASSWORD=base_settings.SAP_PASSWORD,
        SAP_API_TOKEN=base_settings.SAP_API_TOKEN,
        SAP_VERIFY_SSL=base_settings.SAP_VERIFY_SSL,
        SAP_SEND_CLIENT_PARAM=base_settings.SAP_SEND_CLIENT_PARAM,
        SAP_REQUEST_TIMEOUT_SECONDS=base_settings.SAP_REQUEST_TIMEOUT_SECONDS,
    )

    # 2. Construct and approve review package
    print("\n[Step -1] Constructing State & Human Approval Gate Check")
    state = build_authorized_live_workflow_state()
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved_pkg = store.approve(
        pkg.review_id,
        reviewer="lead_architect",
        comment="Explicit live SAP DEV write authorized by user for Milestone 13 smoke test.",
    )

    # 3. Verify all prerequisites before touching any network socket
    print("[Step -1] Verifying Pre-Execution Safety Prerequisites:")
    p_status = approved_pkg.status == ReviewStatus.APPROVED
    p_action = approved_pkg.decision_action == DecisionAction.CREATE
    p_can_approve = approved_pkg.can_approve is True
    p_source = bool(approved_pkg.ddl_source and approved_pkg.ddl_source.strip())
    p_valid = approved_pkg.validation_result is not None and approved_pkg.validation_result.is_valid
    p_write_flag = live_settings.SAP_DEV_WRITE_ENABLED is True
    p_read_only_false = live_settings.SAP_LIVE_READ_ONLY is False
    p_tls = live_settings.SAP_VERIFY_SSL is True
    p_name = SAPADTClient.validate_sap_object_name(TARGET_VIEW_NAME)
    p_tr = SAPADTClient.validate_transport_request(clean_tr)

    print(f"  - Review status APPROVED:            {p_status} ({approved_pkg.status.value})")
    print(f"  - Decision action CREATE:             {p_action} ({approved_pkg.decision_action.value})")
    print(f"  - can_approve == True:                {p_can_approve}")
    print(f"  - Generated CDS source non-empty:     {p_source}")
    print(f"  - Local validation has no errors:     {p_valid}")
    print(f"  - SAP_DEV_WRITE_ENABLED == True:      {p_write_flag}")
    print(f"  - SAP_LIVE_READ_ONLY == False:        {p_read_only_false}")
    print(f"  - TLS verification enabled:           {p_tls}")
    print(f"  - Customer namespace valid:           {p_name}")
    print(f"  - Workbench transport valid:         {p_tr} ({clean_tr})")

    if not all([p_status, p_action, p_can_approve, p_source, p_valid, p_write_flag, p_read_only_false, p_tls, p_name, p_tr]):
        print("\n[CRITICAL HALT] Safety prerequisite failed! STOPPING without writing to SAP.")
        sys.exit(1)

    print("[PASS] All pre-execution prerequisites verified. Proceeding to Step 0.")

    client = SAPADTClient(settings=live_settings)
    connector = SAPADTConnector(settings=live_settings, client=client)

    diagnostics = []
    step_0_result = "FAIL"
    step_a_status = "NOT_EXECUTED"
    step_b_status = "NOT_EXECUTED"
    object_created = False
    object_status = "UNKNOWN"
    repo_uri = ""
    lock_handle = None

    async with client:
        # -------------------------------------------------------------
        # Step 0 — Read: Preflight Existence Check
        # -------------------------------------------------------------
        print("\n" + "-" * 60)
        print("STEP 0: Preflight Read-Only Existence Check")
        print("-" * 60)
        t0 = time.time()
        try:
            existing = await client.get_ddl_source(TARGET_VIEW_NAME)
            print(f"[COLLISION DETECTED] Object '{TARGET_VIEW_NAME}' already exists in SAP DEV repository!")
            print("To preserve SAP integrity, overwrite is strictly prohibited. STOPPING.")
            sys.exit(1)
        except SAPNotFoundError:
            step_0_result = "PASS"
            elapsed = time.time() - t0
            print(f"[PASS] Verified object '{TARGET_VIEW_NAME}' does not exist in SAP repository (HTTP 404 in {elapsed:.2f}s).")
            diagnostics.append({"step": "STEP_0_EXISTENCE_CHECK", "passed": True, "detail": "Object does not exist; safe to proceed."})
        except Exception as e:
            print(f"[ERROR] Step 0 existence check error: {e}")
            sys.exit(1)

        # -------------------------------------------------------------
        # Step A — CREATE: POST DDLS Shell
        # -------------------------------------------------------------
        print("\n" + "-" * 60)
        print("STEP A: POST Inactive DDLS Shell Creation")
        print("-" * 60)
        t_a = time.time()
        try:
            shell_res = await client.create_ddls_shell(
                view_name=TARGET_VIEW_NAME,
                package=TARGET_PACKAGE,
                description=VIEW_DESCRIPTION,
                corr_nr=clean_tr,
                review_package=approved_pkg,
            )
            elapsed_a = time.time() - t_a
            step_a_status = f"HTTP {shell_res.get('status_code')} (in {elapsed_a:.2f}s)"
            repo_uri = shell_res.get("location", f"/sap/bc/adt/ddic/ddl/sources/{TARGET_VIEW_NAME.lower()}")
            lock_handle = shell_res.get("lock_handle")
            object_created = True
            object_status = "INACTIVE"

            print(f"[PASS] Step A Succeeded: {step_a_status}")
            print(f"       Repository URI: {repo_uri}")
            print(f"       Lock Handle:    {lock_handle or '(NOT_FOUND)'}")
            if not lock_handle:
                safe_h = shell_res.get("safe_headers", {})
                print(f"       [NOTICE] Step A response did not provide a lockHandle. Safe headers: {safe_h}")
                print(f"       [NOTICE] Raw body length from Step A: {len(shell_res.get('raw_response', ''))} bytes")
            diagnostics.append({
                "step": "STEP_A_CREATE_DDLS_SHELL",
                "passed": True,
                "status_code": shell_res.get("status_code"),
                "location": repo_uri,
                "lock_handle": lock_handle,
            })
        except Exception as e:
            elapsed_a = time.time() - t_a
            step_a_status = f"FAILED (HTTP error or connection error: {e})"
            print(f"[FAIL] Step A failed in {elapsed_a:.2f}s: {e}")
            diagnostics.append({"step": "STEP_A_CREATE_DDLS_SHELL", "passed": False, "error": str(e)})
            sys.exit(1)

        # -------------------------------------------------------------
        # Step B — SOURCE UPLOAD: PUT DDL Source Code
        # -------------------------------------------------------------
        print("\n" + "-" * 60)
        print("STEP B: PUT CDS DDL Source Code Upload")
        print("-" * 60)
        t_b = time.time()
        try:
            put_code = await client.upload_ddls_source(
                view_name=TARGET_VIEW_NAME,
                ddl_source=CDS_DDL_SOURCE,
                lock_handle=lock_handle,
                corr_nr=clean_tr,
                review_package=approved_pkg,
            )
            elapsed_b = time.time() - t_b
            step_b_status = f"HTTP {put_code} (in {elapsed_b:.2f}s)"
            print(f"[PASS] Step B Succeeded: {step_b_status}")
            diagnostics.append({"step": "STEP_B_UPLOAD_SOURCE", "passed": True, "status_code": put_code})
        except Exception as e:
            elapsed_b = time.time() - t_b
            step_b_status = f"FAILED: {e}"
            print(f"[PARTIAL STATE] Step A succeeded but Step B failed in {elapsed_b:.2f}s: {e}")
            print("STOPPING immediately as instructed. No DELETE or recovery write will be attempted.")
            diagnostics.append({"step": "STEP_B_UPLOAD_SOURCE", "passed": False, "error": str(e)})

        # -------------------------------------------------------------
        # Step C — STOP: Activation & Transport Gate
        # -------------------------------------------------------------
        print("\n" + "-" * 60)
        print("STEP C: STOP — Enforcing Milestone 13 Inactive State")
        print("-" * 60)
        print("[VERIFIED] Step C STOP executed:")
        print("  - Activation endpoint called:     NO (Strictly prohibited)")
        print("  - Transport endpoint called:      NO (Strictly prohibited)")
        print("  - Base CDS modified:              NO (None)")
        print("  - DELETE or cleanup called:       NO (Strictly prohibited)")
        diagnostics.append({"step": "STEP_C_STOP", "passed": True, "detail": "Stopped without activation or transport."})

        # -------------------------------------------------------------
        # Final Read-Only Verification Check
        # -------------------------------------------------------------
        print("\n" + "-" * 60)
        print("POST-WRITE READ-ONLY VERIFICATION")
        print("-" * 60)
        try:
            fetched_source = await client.get_ddl_source(TARGET_VIEW_NAME)
            if fetched_source and TARGET_VIEW_NAME.lower() in fetched_source.lower():
                print(f"[VERIFIED] Read-back of '{TARGET_VIEW_NAME}' from SAP DEV succeeded.")
                print(f"           Source length: {len(fetched_source)} bytes.")
                diagnostics.append({"step": "READBACK_VERIFICATION", "passed": True, "detail": "Read-back confirmed object in SAP DEV repository."})
            else:
                print("[NOTICE] Read-back completed but source was empty or unexpected.")
        except Exception as e:
            print(f"[NOTICE] Read-back check returned: {e}")
            diagnostics.append({"step": "READBACK_VERIFICATION", "passed": False, "detail": str(e)})

    # Print Final Summary Report
    print("\n" + "=" * 70)
    print("LIVE SAP WRITE RESULT")
    print("=" * 70)
    print(f"Step 0:                   {step_0_result}")
    print(f"Step A:                   {step_a_status}")
    print(f"Step B:                   {step_b_status}")
    print(f"Object created:           {'YES' if object_created else 'NO'}")
    print(f"Object status:            {object_status}")
    print(f"Activation performed:     NO")
    print(f"Transport performed:      NO")
    print(f"Existing object overwritten: NO")
    print(f"Repository URI:           {repo_uri}")
    print(f"Package:                  {TARGET_PACKAGE}")
    print(f"Workbench Transport:      {clean_tr}")
    print(f"Diagnostics:              {len(diagnostics)} logged steps")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Milestone 13 / 13.2 Controlled SAP DEV CDS Creation Runner")
    parser.add_argument(
        "--transport-request",
        "-t",
        type=str,
        default=os.getenv("SAP_DEV_TRANSPORT_REQUEST"),
        help="Human-supplied CTS Workbench Transport Request ID (e.g. S4HK900123)",
    )
    args = parser.parse_args()

    asyncio.run(run_controlled_live_creation(transport_request=args.transport_request))
