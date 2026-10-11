"""Milestone 13: Controlled Real SAP DEV CDS Creation Offline Tests.

Validates the controlled SAP DEV creation security architecture and 2-step ADT sequence:
1. test_creation_blocked_without_approval
2. test_creation_blocked_for_rejected_review
3. test_creation_blocked_for_changes_requested
4. test_creation_blocked_when_write_flag_disabled
5. test_creation_blocked_when_live_read_only_is_true
6. test_reuse_performs_zero_sap_writes
7. test_create_uses_approved_cds_source
8. test_existing_object_collision_is_blocked
9. test_invalid_sap_object_name_is_blocked
10. test_activation_endpoint_is_blocked
11. test_arbitrary_sap_endpoint_is_blocked
12. test_secrets_are_not_logged
13. test_successful_mock_creation_returns_repository_identity
14. test_failed_creation_is_represented_honestly
15. test_audit_event_is_generated
16. test_csrf_session_handling_preserved

Strict Boundary: Offline tests only. Zero live SAP network traffic.
"""

from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from src.config import Settings
from src.core.exceptions import (
    GovernanceApprovalRequiredError,
    SAPConflictError,
    SAPConnectorError,
    SAPNotFoundError,
    SAPSecurityError,
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
    SAPValidationStatus,
    StructuredRequirement,
    TargetUseCase,
    ValidationResult,
)
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector
from src.services.review_service import ReviewStore, build_review_package


def _make_sample_requirement() -> BusinessRequirement:
    return BusinessRequirement(
        title="Sales Order KPI Service",
        description="Requirement for custom sales order aggregate analytics",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder", "NetAmount"],
    )


def _make_sample_state(
    action: DecisionAction = DecisionAction.CREATE,
    object_name: str = "ZI_SalesOrderCustom",
    is_valid: bool = True,
) -> CDSWorkflowState:
    req = _make_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=action,
        recommended_view="I_SalesOrder" if action != DecisionAction.CREATE else None,
        proposed_new_view_name=object_name if action == DecisionAction.CREATE else None,
        proposed_extension_name=object_name if action == DecisionAction.EXTEND else None,
        confidence_score=0.92,
        fit_percentage=85.0,
        rationale="Automated test architectural decision.",
    )
    draft = None
    if action in (DecisionAction.CREATE, DecisionAction.EXTEND):
        ev = ElementEvidenceRecord(
            element_name="SalesOrder",
            element_type="FIELD",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            evidence_detail="Exact match",
            confidence=1.0,
            is_verified=True,
        )
        f = DraftFieldElement(
            field_name="SalesOrder",
            source_expression="SalesOrder",
            source_entity="I_SalesOrder",
            is_key=True,
            evidence=ev,
        )
        ddl = f"define view entity {object_name} as select from I_SalesOrder {{ key SalesOrder, NetAmount }};"
        draft = CDSDraft(
            id=f"draft_{object_name}",
            requirement_id=req.id,
            decision_action=action,
            object_name=object_name,
            object_type="DDLS/DF",
            proposed_layer="COMPOSITE",
            source_views=["I_SalesOrder"],
            fields=[f],
            associations=[],
            parameters=[],
            filters=[],
            annotations={},
            ddl_source=ddl,
            evidence_per_element=[ev],
            warnings=[],
            validation_errors=[],
            generation_status="SUCCESS",
            unresolved_items=[],
        )

    val = ValidationResult(
        is_valid=is_valid,
        syntax_errors=[] if is_valid else ["Syntax error in DDL"],
        naming_convention_violations=[],
        clean_core_compliance_score=100.0 if is_valid else 40.0,
        governance_warnings=[],
        details=[],
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "structured_requirement": StructuredRequirement(
            domain="Sales",
            dimensions=["SalesOrder"],
            measures=["NetAmount"],
            filters=[],
        ),
        "candidates": [
            CDSCandidate(
                view_name="I_SalesOrder",
                description="Sales Order View",
                layer=CDSLayer.BASIC,
                release_status="RELEASED",
                available_fields=["SalesOrder", "NetAmount"],
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
        "generated_cds_code": draft.ddl_source if draft else None,
        "audit_logs": [],
    }
    return state


def _make_approved_package(
    action: DecisionAction = DecisionAction.CREATE,
    object_name: str = "ZI_SalesOrderCustom",
) -> CDSReviewPackage:
    state = _make_sample_state(action=action, object_name=object_name)
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved_pkg = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved for testing")
    return approved_pkg


def _make_write_enabled_settings() -> Settings:
    return Settings(
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_CONNECTOR_ENABLED=True,
        SAP_CONNECTOR_TYPE="adt",
        SAP_DEV_PACKAGE="ZTRAINING_2026",
    )


# -------------------------------------------------------------------------
# Test 1: Creation blocked without approval
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_creation_blocked_without_approval():
    state = _make_sample_state()
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)

    assert pkg.status == ReviewStatus.PENDING_REVIEW

    # Gate 1: ReviewStore level
    with pytest.raises(GovernanceApprovalRequiredError) as exc_info:
        await store.execute_sap_creation(pkg.review_id)
    assert "requires explicit senior developer or architect approval" in str(exc_info.value)

    # Gate 2: ADT Connector level
    settings = _make_write_enabled_settings()
    client = MagicMock(spec=SAPADTClient)
    connector = SAPADTConnector(settings=settings, client=client)
    with pytest.raises(SAPSecurityError) as exc_info2:
        await connector.create_cds_in_sap(pkg)
    assert "Only proposals explicitly APPROVED" in str(exc_info2.value)


# -------------------------------------------------------------------------
# Test 2: Creation blocked for rejected review
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_creation_blocked_for_rejected_review():
    state = _make_sample_state()
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    store.reject(pkg.review_id, reviewer="lead_architect", reason="Architectural concerns with grain")

    assert pkg.status == ReviewStatus.REJECTED

    with pytest.raises(GovernanceApprovalRequiredError):
        await store.execute_sap_creation(pkg.review_id)

    settings = _make_write_enabled_settings()
    client = MagicMock(spec=SAPADTClient)
    connector = SAPADTConnector(settings=settings, client=client)
    with pytest.raises(SAPSecurityError):
        await connector.create_cds_in_sap(pkg)


# -------------------------------------------------------------------------
# Test 3: Creation blocked for changes requested
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_creation_blocked_for_changes_requested():
    state = _make_sample_state()
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    store.request_changes(pkg.review_id, reviewer="lead_architect", reason="Please add filter on DocumentDate")

    assert pkg.status == ReviewStatus.CHANGES_REQUESTED

    with pytest.raises(GovernanceApprovalRequiredError):
        await store.execute_sap_creation(pkg.review_id)

    settings = _make_write_enabled_settings()
    client = MagicMock(spec=SAPADTClient)
    connector = SAPADTConnector(settings=settings, client=client)
    with pytest.raises(SAPSecurityError):
        await connector.create_cds_in_sap(pkg)


# -------------------------------------------------------------------------
# Test 4: Creation blocked when write flag is disabled
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_creation_blocked_when_write_flag_disabled():
    pkg = _make_approved_package()
    # Default settings: SAP_DEV_WRITE_ENABLED is False
    settings = Settings(
        SAP_DEV_WRITE_ENABLED=False,
        SAP_LIVE_READ_ONLY=False,
    )
    client = SAPADTClient(settings=settings)
    connector = SAPADTConnector(settings=settings, client=client)

    with pytest.raises(SAPSecurityError) as exc_info:
        await connector.create_cds_in_sap(pkg, transport_request="DEVK900001")
    assert "SAP DEV write capability is disabled" in str(exc_info.value)
    assert "SAP_DEV_WRITE_ENABLED" in str(exc_info.value)


# -------------------------------------------------------------------------
# Test 5: Creation blocked when live read only is True
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_creation_blocked_when_live_read_only_is_true():
    pkg = _make_approved_package()
    settings = Settings(
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=True,
    )
    client = SAPADTClient(settings=settings)
    connector = SAPADTConnector(settings=settings, client=client)

    with pytest.raises(SAPSecurityError) as exc_info:
        await connector.create_cds_in_sap(pkg, transport_request="DEVK900001")
    assert "SAP_LIVE_READ_ONLY is enabled" in str(exc_info.value)


# -------------------------------------------------------------------------
# Test 6: REUSE performs zero SAP writes and rejects creation attempt
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reuse_performs_zero_sap_writes():
    state = _make_sample_state(action=DecisionAction.REUSE)
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved_pkg = store.approve(pkg.review_id, reviewer="lead_architect", comment="Standard reuse approved")

    settings = _make_write_enabled_settings()
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.create_ddls_shell = AsyncMock()
    mock_client.upload_ddls_source = AsyncMock()
    connector = SAPADTConnector(settings=settings, client=mock_client)

    # REUSE proposals must reject SAP creation attempts with SAPSecurityError
    with pytest.raises(SAPSecurityError) as exc_info:
        await connector.create_cds_in_sap(approved_pkg)

    assert "Standard SAP CDS views require zero custom object creation" in str(exc_info.value)

    # Verify zero network write calls were made
    assert not mock_client.create_ddls_shell.called
    assert not mock_client.upload_ddls_source.called


# -------------------------------------------------------------------------
# Test 7: CREATE uses approved CDS source
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_uses_approved_cds_source():
    pkg = _make_approved_package(action=DecisionAction.CREATE, object_name="ZI_SalesOrderCustom")
    settings = _make_write_enabled_settings()

    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    # Preflight check returns not found (safe to create)
    mock_client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZI_SALESORDERCUSTOM"))
    # Step A returns shell creation result with lock handle
    mock_client.create_ddls_shell = AsyncMock(
        return_value={
            "status_code": 201,
            "lock_handle": "LOCK_ABC123",
            "location": "/sap/bc/adt/ddic/ddl/sources/zi_salesordercustom",
        }
    )
    # Step B returns upload status 200
    mock_client.upload_ddls_source = AsyncMock(return_value=200)

    connector = SAPADTConnector(settings=settings, client=mock_client)
    res = await connector.create_cds_in_sap(pkg, transport_request="DEVK900001")

    assert res.success is True
    assert res.sap_write_performed is True
    assert res.activation_status == "INACTIVE"
    assert res.sap_object_name == "ZI_SALESORDERCUSTOM"
    assert res.package == "ZTRAINING_2026"
    assert res.transport_request == "DEVK900001"

    # Verify Step A invocation
    mock_client.create_ddls_shell.assert_called_once_with(
        view_name="ZI_SALESORDERCUSTOM",
        package="ZTRAINING_2026",
        description=pkg.original_requirement.title,
        corr_nr="DEVK900001",
        review_package=pkg,
    )

    # Verify Step B invocation
    mock_client.upload_ddls_source.assert_called_once_with(
        view_name="ZI_SALESORDERCUSTOM",
        ddl_source=pkg.ddl_source,
        lock_handle="LOCK_ABC123",
        corr_nr="DEVK900001",
        review_package=pkg,
    )


# -------------------------------------------------------------------------
# Test 8: Existing object collision is blocked
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_existing_object_collision_is_blocked():
    pkg = _make_approved_package(action=DecisionAction.CREATE, object_name="ZI_SalesOrderCustom")
    settings = _make_write_enabled_settings()

    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    # Object already exists in SAP
    mock_client.get_ddl_source = AsyncMock(return_value="define view entity ZI_SalesOrderCustom as select from ...")
    mock_client.create_ddls_shell = AsyncMock()
    mock_client.upload_ddls_source = AsyncMock()

    connector = SAPADTConnector(settings=settings, client=mock_client)

    with pytest.raises(SAPConflictError) as exc_info:
        await connector.create_cds_in_sap(pkg, transport_request="DEVK900001")

    assert "already exists" in str(exc_info.value).lower()
    assert exc_info.value.status_code == 409

    # Pre-flight blocked Step A and Step B
    assert not mock_client.create_ddls_shell.called
    assert not mock_client.upload_ddls_source.called


# -------------------------------------------------------------------------
# Test 9: Invalid SAP object name is blocked
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_sap_object_name_is_blocked():
    # Customer namespace requires starting with 'Z' or 'Y'
    pkg = _make_approved_package(action=DecisionAction.CREATE, object_name="I_ForbiddenStandardName")
    settings = _make_write_enabled_settings()

    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    connector = SAPADTConnector(settings=settings, client=mock_client)

    with pytest.raises(SAPSecurityError) as exc_info:
        await connector.create_cds_in_sap(pkg, transport_request="DEVK900001")

    assert "customer namespace" in str(exc_info.value).lower()


# -------------------------------------------------------------------------
# Test 10: Activation endpoint is blocked
# -------------------------------------------------------------------------
def test_activation_endpoint_is_blocked():
    pkg = _make_approved_package()
    settings = _make_write_enabled_settings()
    client = SAPADTClient(settings=settings)

    with pytest.raises(SAPSecurityError) as exc_info:
        client.assert_dev_write_policy("POST", "/sap/bc/adt/activation", review_package=pkg)

    assert "activation is strictly forbidden" in str(exc_info.value).lower()


# -------------------------------------------------------------------------
# Test 11: Arbitrary SAP endpoint is blocked
# -------------------------------------------------------------------------
def test_arbitrary_sap_endpoint_is_blocked():
    pkg = _make_approved_package()
    settings = _make_write_enabled_settings()
    client = SAPADTClient(settings=settings)

    # Attempt to call arbitrary CTS transport endpoint
    with pytest.raises(SAPSecurityError) as exc_info:
        client.assert_dev_write_policy("POST", "/sap/bc/adt/cts/transports", review_package=pkg)

    assert "strictly forbidden" in str(exc_info.value).lower()

    # Attempt to call arbitrary ABAP program endpoint
    with pytest.raises(SAPSecurityError) as exc_info2:
        client.assert_dev_write_policy("POST", "/sap/bc/adt/programs/programs", review_package=pkg)

    assert "unauthorized" in str(exc_info2.value).lower()


# -------------------------------------------------------------------------
# Test 12: Secrets are not logged
# -------------------------------------------------------------------------
def test_secrets_are_not_logged():
    settings = Settings(
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_PASSWORD="SuperSecretPassword123!",
    )
    client = SAPADTClient(settings=settings)

    # Verify query string sanitization
    dirty_url = "/sap/bc/adt/ddic/ddl/sources?token=my_secret_token_abc&password=SuperSecretPassword123!"
    clean_url = client._sanitize_url_for_logging(dirty_url)
    assert "my_secret_token_abc" not in clean_url
    assert "SuperSecretPassword123!" not in clean_url
    assert "token=***" in clean_url
    assert "password=***" in clean_url


# -------------------------------------------------------------------------
# Test 13: Successful mock creation returns repository identity
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_successful_mock_creation_returns_repository_identity():
    pkg = _make_approved_package(action=DecisionAction.CREATE, object_name="ZI_SalesOrderCustom")
    settings = _make_write_enabled_settings()

    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    mock_client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZI_SALESORDERCUSTOM"))
    mock_client.create_ddls_shell = AsyncMock(
        return_value={
            "status_code": 201,
            "lock_handle": "LOCK_12345",
            "location": "/sap/bc/adt/ddic/ddl/sources/zi_salesordercustom",
        }
    )
    mock_client.upload_ddls_source = AsyncMock(return_value=204)

    connector = SAPADTConnector(settings=settings, client=mock_client)
    res = await connector.create_cds_in_sap(pkg, transport_request="DEVK900001")

    assert res.success is True
    assert res.sap_object_name == "ZI_SALESORDERCUSTOM"
    assert res.repository_uri == "/sap/bc/adt/ddic/ddl/sources/zi_salesordercustom"
    assert res.package == "ZTRAINING_2026"
    assert res.activation_status == "INACTIVE"
    assert res.sap_write_performed is True
    assert len(res.diagnostics) >= 3


# -------------------------------------------------------------------------
# Test 14: Failed creation is represented honestly
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_creation_is_represented_honestly():
    state = _make_sample_state(action=DecisionAction.CREATE, object_name="ZI_SalesOrderCustom")
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved_pkg = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved")

    mock_connector = MagicMock(spec=SAPADTConnector)
    mock_connector.create_cds_in_sap = AsyncMock(
        side_effect=SAPConnectorError("SAP DEV ABAP error 500: Database table write timeout", status_code=500)
    )

    with pytest.raises(SAPConnectorError) as exc_info:
        await store.execute_sap_creation(approved_pkg.review_id, transport_request="DEVK900001", connector=mock_connector)

    assert "Database table write timeout" in str(exc_info.value)

    # Check that failed audit event was recorded
    fail_events = [e for e in approved_pkg.audit_events if e.action == "SAP_CREATE_FAILED"]
    assert len(fail_events) == 1
    assert "Database table write timeout" in fail_events[0].reason
    assert fail_events[0].details["error_type"] == "SAPConnectorError"


# -------------------------------------------------------------------------
# Test 15: Audit event is generated
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_event_is_generated():
    state = _make_sample_state(action=DecisionAction.CREATE, object_name="ZI_SalesOrderCustom")
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved_pkg = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved")

    settings = _make_write_enabled_settings()
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    mock_client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZI_SALESORDERCUSTOM"))
    mock_client.create_ddls_shell = AsyncMock(
        return_value={
            "status_code": 201,
            "lock_handle": "LOCK_12345",
            "location": "/sap/bc/adt/ddic/ddl/sources/zi_salesordercustom",
        }
    )
    mock_client.upload_ddls_source = AsyncMock(return_value=200)

    connector = SAPADTConnector(settings=settings, client=mock_client)
    res = await store.execute_sap_creation(approved_pkg.review_id, transport_request="DEVK900999", connector=connector)

    assert res.success is True

    # Audit events must include SAP_CREATE_REQUESTED and SAP_CREATE_SUCCEEDED
    actions = [e.action for e in approved_pkg.audit_events]
    assert "SAP_CREATE_REQUESTED" in actions
    assert "SAP_CREATE_SUCCEEDED" in actions

    req_event = next(e for e in approved_pkg.audit_events if e.action == "SAP_CREATE_REQUESTED")
    assert req_event.details["transport_request"] == "DEVK900999"

    succ_event = next(e for e in approved_pkg.audit_events if e.action == "SAP_CREATE_SUCCEEDED")
    assert succ_event.details["sap_object_name"] == "ZI_SALESORDERCUSTOM"
    assert succ_event.details["activation_status"] == "INACTIVE"
    assert succ_event.details["sap_write_performed"] is True


# -------------------------------------------------------------------------
# Test 16: CSRF session handling is preserved
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_csrf_session_handling_preserved():
    settings = _make_write_enabled_settings()
    client = SAPADTClient(settings=settings)

    # Mock persistent httpx client to inspect header forwarding
    captured_requests = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.method == "GET" and "informationsystem/search" in str(request.url):
            return httpx.Response(
                status_code=200,
                headers={"x-csrf-token": "MOCK_CSRF_TOKEN_999", "content-type": "application/xml"},
                text="<result/>",
            )
        if request.method == "POST" and "ddic/ddl/sources" in str(request.url):
            return httpx.Response(
                status_code=201,
                headers={"Location": "/sap/bc/adt/ddic/ddl/sources/zi_test", "lockHandle": "LOCK_1"},
                text="<ok/>",
            )
        return httpx.Response(status_code=404)

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http_client = httpx.AsyncClient(transport=mock_transport, base_url="https://sap-mock:443")
    client._custom_client = mock_http_client

    pkg = _make_approved_package(action=DecisionAction.CREATE, object_name="ZI_Test")

    res = await client.create_ddls_shell(
        view_name="ZI_Test",
        package="ZTRAINING_2026",
        description="Test shell",
        corr_nr="DEVK900001",
        review_package=pkg,
    )

    assert res["status_code"] == 201
    assert len(captured_requests) >= 2

    # Verify first request was CSRF fetch
    csrf_req = captured_requests[0]
    assert csrf_req.method == "GET"
    assert csrf_req.headers.get("x-csrf-token") == "Fetch"

    # Verify second request included negotiated CSRF token
    post_req = captured_requests[1]
    assert post_req.method == "POST"
    assert post_req.headers.get("x-csrf-token") == "MOCK_CSRF_TOKEN_999"
