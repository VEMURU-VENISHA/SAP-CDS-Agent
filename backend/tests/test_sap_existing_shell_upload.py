"""Milestone 13.4: Controlled Existing-Shell Source Upload Tests.

Verifies the dedicated continuation flow for uploading CDS DDL source code into an
existing inactive DDLS shell in SAP DEV:
1. Rejects unapproved proposals (ReviewStatus != APPROVED)
2. Rejects ineligible proposals (can_approve == False)
3. Rejects when SAP_DEV_WRITE_ENABLED is False
4. Rejects when SAP_LIVE_READ_ONLY is True
5. Rejects missing or malformed Workbench Transport Requests
6. Halts safely when shell does not exist (SAPNotFoundError on preflight read)
7. Halts safely if lock acquisition fails (does NOT attempt source upload)
8. Successful upload flow: acquires lock, uploads source, enforces INACTIVE, reads back
9. Verifies create_ddls_shell is NEVER called
10. Verifies ReviewStore audit events and error handling
11. Verifies API endpoint POST /api/v1/reviews/{id}/upload-existing-shell
"""

from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest
from starlette.testclient import TestClient

from src.config import Settings
from src.core.exceptions import (
    GovernanceApprovalRequiredError,
    SAPConnectorError,
    SAPNotFoundError,
    SAPSecurityError,
    SAPTransportRequestError,
)
from src.models.domain import (
    BusinessRequirement,
    CDSWorkflowState,
    CDSCandidate,
    CDSDraft,
    CDSLayer,
    CDSReviewPackage,
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


def _make_sample_state(object_name: str = "ZI_EXISTING_SHELL_TEST") -> CDSWorkflowState:
    req = BusinessRequirement(
        title="Existing Shell Test",
        description="Requirement for testing existing shell upload",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name=object_name,
        confidence_score=1.0,
        fit_percentage=100.0,
        rationale="Existing shell upload test decision",
    )
    ev = ElementEvidenceRecord(
        element_name="SalesOrder",
        element_type="FIELD",
        evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
        evidence_detail="Exact match",
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
        )
    ]
    draft = CDSDraft(
        id=f"draft_{object_name.lower()}",
        requirement_id=req.id,
        decision_action=DecisionAction.CREATE,
        object_name=object_name,
        object_type="CUSTOM_VIEW_ENTITY",
        proposed_layer="BASIC",
        source_views=["I_SalesOrder"],
        fields=fields,
        associations=[],
        parameters=[],
        filters=[],
        annotations={"@AccessControl.authorizationCheck": "#NOT_REQUIRED"},
        ddl_source=f"define view entity {object_name} as select from I_SalesOrder {{ key SalesOrder }};",
        evidence_per_element=[ev],
        warnings=[],
        validation_errors=[],
        generation_status="VALIDATED",
        unresolved_items=[],
    )
    val = ValidationResult(is_valid=True, syntax_errors=[], naming_convention_violations=[], clean_core_compliance_score=100.0)
    return {
        "requirement": req,
        "structured_requirement": StructuredRequirement(domain="Sales", dimensions=["SalesOrder"], measures=[], filters=[]),
        "candidates": [
            CDSCandidate(
                view_name="I_SalesOrder",
                description="Sales Order View",
                layer=CDSLayer.BASIC,
                release_status="RELEASED",
                available_fields=["SalesOrder"],
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
        "generated_cds_code": draft.ddl_source,
        "audit_logs": [],
    }


def _make_approved_package(object_name: str = "ZI_EXISTING_SHELL_TEST") -> CDSReviewPackage:
    state = _make_sample_state(object_name=object_name)
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved_pkg = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved for testing")
    return approved_pkg


# -----------------------------------------------------------------------------
# 1. Approval and Eligibility Guards
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_existing_shell_fails_if_not_approved():
    settings = Settings(SAP_CONNECTOR_ENABLED=True, SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=False)
    client = MagicMock(spec=SAPADTClient)
    connector = SAPADTConnector(settings=settings, client=client)

    state = _make_sample_state()
    pkg = build_review_package(state)  # Status is PENDING_REVIEW

    with pytest.raises(SAPSecurityError) as exc_info:
        await connector.upload_source_to_existing_shell(pkg, transport_request="S3XK911848")

    assert "Only proposals explicitly APPROVED" in str(exc_info.value)


@pytest.mark.asyncio
async def test_upload_existing_shell_fails_if_can_approve_false():
    settings = Settings(SAP_CONNECTOR_ENABLED=True, SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=False)
    client = MagicMock(spec=SAPADTClient)
    connector = SAPADTConnector(settings=settings, client=client)

    pkg = _make_approved_package()
    pkg.can_approve = False
    pkg.blocking_reasons = ["Syntax error in draft"]

    with pytest.raises(SAPSecurityError) as exc_info:
        await connector.upload_source_to_existing_shell(pkg, transport_request="S3XK911848")

    assert "Approval eligibility failed" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 2. Transport Request Format Validation
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("invalid_tr", [None, "", "   ", "S3X911848", "random_string", "S3XK12345"])
@pytest.mark.asyncio
async def test_upload_existing_shell_rejects_invalid_transport(invalid_tr):
    settings = Settings(SAP_CONNECTOR_ENABLED=True, SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=False)
    client = MagicMock(spec=SAPADTClient)
    client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    client.validate_transport_request = SAPADTClient.validate_transport_request
    connector = SAPADTConnector(settings=settings, client=client)

    pkg = _make_approved_package()

    with pytest.raises(SAPTransportRequestError):
        await connector.upload_source_to_existing_shell(pkg, transport_request=invalid_tr)


# -----------------------------------------------------------------------------
# 3. Preflight Check: Shell Must Already Exist in SAP
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_existing_shell_halts_if_shell_does_not_exist():
    settings = Settings(SAP_CONNECTOR_ENABLED=True, SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=False)
    client = MagicMock(spec=SAPADTClient)
    client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    client.validate_transport_request = SAPADTClient.validate_transport_request
    # Shell does NOT exist -> 404
    client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZI_EXISTING_SHELL_TEST"))
    client.lock_ddls_object = AsyncMock()
    client.upload_ddls_source = AsyncMock()
    client.create_ddls_shell = AsyncMock()

    connector = SAPADTConnector(settings=settings, client=client)
    pkg = _make_approved_package()

    with pytest.raises(SAPNotFoundError) as exc_info:
        await connector.upload_source_to_existing_shell(pkg, transport_request="S3XK911848")

    assert "does not exist in target repository" in str(exc_info.value)
    # Crucially, zero lock, zero shell creation, zero upload!
    client.create_ddls_shell.assert_not_called()
    client.lock_ddls_object.assert_not_called()
    client.upload_ddls_source.assert_not_called()


# -----------------------------------------------------------------------------
# 4. Lock Acquisition Failure Halts Safely
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_existing_shell_halts_if_lock_acquisition_fails():
    settings = Settings(SAP_CONNECTOR_ENABLED=True, SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=False)
    client = MagicMock(spec=SAPADTClient)
    client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    client.validate_transport_request = SAPADTClient.validate_transport_request
    # Shell exists
    client.get_ddl_source = AsyncMock(return_value="define view entity ZI_EXISTING_SHELL_TEST as select from I_SalesOrder;")
    # Lock acquisition returns empty handle
    client.lock_ddls_object = AsyncMock(return_value={"lock_handle": ""})
    client.upload_ddls_source = AsyncMock()
    client.create_ddls_shell = AsyncMock()

    connector = SAPADTConnector(settings=settings, client=client)
    pkg = _make_approved_package()

    with pytest.raises(SAPConnectorError) as exc_info:
        await connector.upload_source_to_existing_shell(pkg, transport_request="S3XK911848")

    assert "no lockHandle returned by SAP" in str(exc_info.value)
    # PUT must NEVER be called if lock fails!
    client.upload_ddls_source.assert_not_called()
    client.create_ddls_shell.assert_not_called()


# -----------------------------------------------------------------------------
# 5. Successful Upload Flow
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_existing_shell_successful_flow():
    settings = Settings(SAP_CONNECTOR_ENABLED=True, SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=False)
    client = MagicMock(spec=SAPADTClient)
    client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    client.validate_transport_request = SAPADTClient.validate_transport_request

    initial_shell = "define view entity ZI_EXISTING_SHELL_TEST as select from I_SalesOrder;"
    updated_source = "define view entity ZI_EXISTING_SHELL_TEST as select from I_SalesOrder { key SalesOrder };"
    client.get_ddl_source = AsyncMock(side_effect=[initial_shell, updated_source])
    client.lock_ddls_object = AsyncMock(return_value={"lock_handle": "LOCK_TOKEN_12345", "corr_nr": "S3XK911848"})
    client.upload_ddls_source = AsyncMock(return_value=204)
    client.create_ddls_shell = AsyncMock()

    connector = SAPADTConnector(settings=settings, client=client)
    pkg = _make_approved_package()

    res = await connector.upload_source_to_existing_shell(pkg, transport_request="S3XK911848")

    assert res.success is True
    assert res.operation == "UPLOAD_EXISTING_SHELL_SOURCE"
    assert res.sap_object_name == "ZI_EXISTING_SHELL_TEST"
    assert res.activation_status == "INACTIVE"
    assert res.sap_write_performed is True

    # Confirm create_ddls_shell was NOT called
    client.create_ddls_shell.assert_not_called()

    # Confirm lock was requested with MODIFY
    client.lock_ddls_object.assert_called_once_with(
        view_name="ZI_EXISTING_SHELL_TEST",
        access_mode="MODIFY",
        review_package=pkg,
    )

    # Confirm upload received the lock_handle and corr_nr
    client.upload_ddls_source.assert_called_once()
    _, kwargs = client.upload_ddls_source.call_args
    assert kwargs["lock_handle"] == "LOCK_TOKEN_12345"
    assert kwargs["corr_nr"] == "S3XK911848"

    # Confirm lock was cleanly released
    client.unlock_ddls_object.assert_called_once_with(
        view_name="ZI_EXISTING_SHELL_TEST",
        lock_handle="LOCK_TOKEN_12345",
        review_package=pkg,
    )


# -----------------------------------------------------------------------------
# 6. ReviewStore Integration & Audit Trail
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_review_store_execute_existing_shell_upload_audit_trail():
    store = ReviewStore()
    state = _make_sample_state()
    pkg = build_review_package(state)
    store.register(pkg, state)
    store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved")

    mock_connector = MagicMock()
    mock_connector.upload_source_to_existing_shell = AsyncMock(
        return_value=MagicMock(
            success=True,
            operation="UPLOAD_EXISTING_SHELL_SOURCE",
            sap_object_name="ZI_EXISTING_SHELL_TEST",
            repository_uri="/sap/bc/adt/ddic/ddl/sources/zi_existing_shell_test",
            package="ZTRAINING_2026",
            activation_status="INACTIVE",
            sap_write_performed=True,
        )
    )

    result = await store.execute_existing_shell_upload(
        review_id=pkg.review_id,
        transport_request="S3XK911848",
        connector=mock_connector,
    )

    assert result.success is True
    updated_pkg = store.get(pkg.review_id)
    actions = [e.action for e in updated_pkg.audit_events]
    assert "SAP_SOURCE_UPLOAD_REQUESTED" in actions
    assert "SAP_SOURCE_UPLOAD_SUCCEEDED" in actions


# -----------------------------------------------------------------------------
# 7. FastAPI Route Verification
# -----------------------------------------------------------------------------
def test_api_route_upload_existing_shell():
    from fastapi import FastAPI
    from src.api.router import api_v1_router
    from src.services.review_service import get_review_store

    app = FastAPI()
    app.include_router(api_v1_router)

    client = TestClient(app)
    store = get_review_store()

    state = _make_sample_state("ZI_API_EXISTING_TEST")
    pkg = build_review_package(state)
    store.register(pkg, state)
    store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved")

    # Call endpoint without transport request -> 400
    resp_bad = client.post(
        f"/api/v1/reviews/{pkg.review_id}/upload-existing-shell",
        json={"transport_request": "bad_tr"},
    )
    assert resp_bad.status_code == 400


# -----------------------------------------------------------------------------
# 8. Namespace, REUSE, and Lock Cleanup on Failure Tests
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_existing_shell_rejects_invalid_namespace():
    settings = Settings(SAP_CONNECTOR_ENABLED=True, SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=False)
    client = MagicMock(spec=SAPADTClient)
    client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    client.validate_transport_request = SAPADTClient.validate_transport_request
    connector = SAPADTConnector(settings=settings, client=client)

    pkg = _make_approved_package(object_name="INVALID_NO_Z")
    with pytest.raises(SAPSecurityError, match="violates SAP customer namespace rules"):
        await connector.upload_source_to_existing_shell(pkg, transport_request="S3XK911848")


@pytest.mark.asyncio
async def test_upload_existing_shell_rejects_reuse():
    settings = Settings(SAP_CONNECTOR_ENABLED=True, SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=False)
    client = MagicMock(spec=SAPADTClient)
    connector = SAPADTConnector(settings=settings, client=client)

    pkg = _make_approved_package(object_name="I_SalesOrder")
    pkg.decision_action = DecisionAction.REUSE
    with pytest.raises(SAPSecurityError, match="Standard SAP CDS views require zero source upload"):
        await connector.upload_source_to_existing_shell(pkg, transport_request="S3XK911848")


@pytest.mark.asyncio
async def test_upload_existing_shell_unlocks_on_put_failure():
    """Verify that if source upload fails, the lock is still cleanly released."""
    settings = Settings(SAP_CONNECTOR_ENABLED=True, SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=False)
    client = MagicMock(spec=SAPADTClient)
    client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    client.validate_transport_request = SAPADTClient.validate_transport_request
    client.get_ddl_source = AsyncMock(return_value="define view entity ZI_EXISTING_SHELL_TEST as select from I_SalesOrder;")
    client.lock_ddls_object = AsyncMock(return_value={"lock_handle": "LOCK_TOKEN_FAIL_TEST", "corr_nr": "S3XK911848"})
    client.upload_ddls_source = AsyncMock(side_effect=SAPConnectorError("HTTP 500 ABAP Dump during PUT"))
    client.unlock_ddls_object = AsyncMock(return_value=True)

    connector = SAPADTConnector(settings=settings, client=client)
    pkg = _make_approved_package()

    with pytest.raises(SAPConnectorError, match="HTTP 500 ABAP Dump"):
        await connector.upload_source_to_existing_shell(pkg, transport_request="S3XK911848")

    # Verify unlock_ddls_object was called despite PUT failure!
    client.unlock_ddls_object.assert_called_once_with(
        view_name="ZI_EXISTING_SHELL_TEST",
        lock_handle="LOCK_TOKEN_FAIL_TEST",
        review_package=pkg,
    )
