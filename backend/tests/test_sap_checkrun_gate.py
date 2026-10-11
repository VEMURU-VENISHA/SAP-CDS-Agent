"""Unit and integration tests for SAP ADT Checkrun Gate and Activation Gate.

Verifies:
1. Controlled SAP Checkrun execution (inactive version, SHA-256 source hash).
2. Diagnostic parsing (E/A/X errors, warnings, info).
3. Pre-flight security gates:
   - Human approval required (APPROVED status).
   - Approval eligibility must pass.
   - Customer namespace required (Z/Y).
   - REUSE invariant (REUSE strictly rejects checkrun and activation).
   - Object existence verification.
4. Dual checkrun gate enforcement on activation:
   - Activation blocked when no checkrun has run.
   - Activation blocked when checkrun reported blocking errors.
   - Activation blocked when checkrun is stale (source modified).
   - Activation allowed when checkrun passed with 0 blocking errors and matching hash.
5. ReviewStore integration & stale invalidation:
   - Audit logging (SAP_CHECKRUN_REQUESTED, SAP_CHECKRUN_SUCCEEDED, SAP_CHECKRUN_FAILED).
   - Re-upload clears latest_sap_checkrun to None.
6. REST API endpoint POST /api/v1/reviews/{review_id}/checkrun-sap.
"""

import hashlib
import httpx
import pytest
from unittest.mock import AsyncMock, patch

from src.config import Settings
from src.core.exceptions import (
    EntityNotFoundError,
    GovernanceApprovalRequiredError,
    SAPNotFoundError,
    SAPSecurityError,
)
from src.main import app
from src.models.domain import (
    BusinessRequirement,
    CDSDraft,
    CDSReviewPackage,
    Decision,
    DecisionAction,
    DraftFieldElement,
    ElementEvidenceRecord,
    EvidenceLevel,
    ReviewAuditEvent,
    ReviewStatus,
    SAPActivationResult,
    SAPCheckMessage,
    SAPCheckrunResult,
    SAPCreationResult,
    SAPReviewCheckrunResult,
    SAPValidationStatus,
    TargetUseCase,
    ValidationResult,
)
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector
from src.services.review_service import ReviewStore, build_review_package


def get_mock_settings():
    return Settings(
        SAP_BASE_URL="https://sap-dev.corp.internal:44300",
        SAP_CLIENT="100",
        SAP_USERNAME="DEVELOPER",
        SAP_PASSWORD="SuperSecretPassword123!",
        SAP_AUTH_TYPE="basic",
        SAP_VERIFY_SSL=False,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_ALLOW_ACTIVATE=True,
    )


def make_test_review_package(
    object_name: str = "ZI_CHECKRUN_TEST",
    action: DecisionAction = DecisionAction.CREATE,
    status: ReviewStatus = ReviewStatus.APPROVED,
    can_approve: bool = True,
    source: str = "define view entity ZI_CHECKRUN_TEST as select from I_SalesOrder { key SalesOrder };",
) -> CDSReviewPackage:
    req = BusinessRequirement(
        title="Checkrun Test",
        description="Requirement for checkrun test",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=action,
        proposed_new_view_name=object_name if action == DecisionAction.CREATE else None,
        proposed_extension_name=object_name if action == DecisionAction.EXTEND else None,
        confidence_score=1.0,
        fit_percentage=100.0,
        rationale="Checkrun test decision",
    )
    ev = ElementEvidenceRecord(
        element_name="SalesOrder",
        element_type="FIELD",
        evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
        evidence_detail="Exact match",
        confidence=1.0,
        is_verified=True,
    )
    draft = CDSDraft(
        id=f"draft_{object_name.lower()}",
        requirement_id=req.id,
        decision_action=action,
        object_name=object_name,
        object_type="CUSTOM_VIEW_ENTITY" if action == DecisionAction.CREATE else "CDS_EXTENSION",
        proposed_layer="BASIC",
        source_views=["I_SalesOrder"],
        fields=[
            DraftFieldElement(
                field_name="SalesOrder",
                source_expression="SalesOrder",
                source_entity="I_SalesOrder",
                is_key=True,
                evidence=ev,
            )
        ],
        associations=[],
        parameters=[],
        filters=[],
        annotations={},
        ddl_source=source,
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
    )
    state = {
        "requirement": req,
        "structured_requirement": None,
        "candidates": [],
        "field_mappings": [],
        "decision": decision,
        "cds_draft": draft,
        "validation_result": val,
        "generated_cds_code": source,
        "audit_logs": [],
    }
    pkg = build_review_package(state)
    pkg.status = status
    pkg.can_approve = can_approve
    pkg.object_name = object_name
    pkg.ddl_source = source
    if not can_approve:
        pkg.blocking_reasons = ["Ineligible for approval"]
    return pkg


# ---------------------------------------------------------------------------
# 1. SAPADTConnector.checkrun_cds_in_sap tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connector_checkrun_success_with_inactive_version():
    """Verify checkrun against inactive version produces SAPReviewCheckrunResult with source hash."""
    settings = get_mock_settings()
    source_content = "define view entity ZI_CHECKRUN_TEST as select from I_SalesOrder { key SalesOrder };"
    captured_requests = []

    def handler(request: httpx.Request):
        captured_requests.append(request)
        if request.method == "GET" and "/sap/bc/adt/ddic/ddl/sources/zi_checkrun_test" in request.url.path:
            return httpx.Response(200, text=source_content)
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF_TOKEN"})
        if request.method == "POST" and "/sap/bc/adt/checkruns" in request.url.path:
            return httpx.Response(
                200,
                text="""<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/zi_checkrun_test" chkrun:status="processed">
    <chkrun:checkMessage chkrun:type="W" chkrun:shortText="Warning: test warning message" />
  </chkrun:checkReport>
</chkrun:checkRunReports>""",
                headers={"Content-Type": "application/vnd.sap.adt.checkmessages+xml"},
            )
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)
    connector = SAPADTConnector(settings=settings, client=adt_client)

    package = make_test_review_package(object_name="ZI_CHECKRUN_TEST", source=source_content)
    result = await connector.checkrun_cds_in_sap(package)

    assert result.success is True
    assert result.blocking_errors == 0
    assert result.warnings == 1
    assert result.status == SAPValidationStatus.WARNING
    assert result.source_hash == hashlib.sha256(source_content.encode("utf-8")).hexdigest()

    # Verify checkrun POST payload included chkrun:version="inactive"
    post_requests = [r for r in captured_requests if r.method == "POST" and "/sap/bc/adt/checkruns" in r.url.path]
    assert len(post_requests) == 1
    post_body = post_requests[0].read().decode("utf-8")
    assert 'chkrun:version="inactive"' in post_body


@pytest.mark.asyncio
async def test_connector_checkrun_blocking_errors():
    """Verify checkrun with severity E/A/X produces success=False and status=ERROR."""
    settings = get_mock_settings()
    source_content = "define view entity ZI_ERROR_TEST as select from I_SalesOrder { key ErrorField };"

    def handler(request: httpx.Request):
        if request.method == "GET" and "/sap/bc/adt/ddic/ddl/sources/zi_error_test" in request.url.path:
            return httpx.Response(200, text=source_content)
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF_TOKEN"})
        if request.method == "POST":
            return httpx.Response(
                200,
                text="""<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/zi_error_test" chkrun:status="processed">
    <chkrun:checkMessage chkrun:type="E" chkrun:shortText="Field ErrorField does not exist in data source" />
  </chkrun:checkReport>
</chkrun:checkRunReports>""",
                headers={"Content-Type": "application/vnd.sap.adt.checkmessages+xml"},
            )
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)
    connector = SAPADTConnector(settings=settings, client=adt_client)

    package = make_test_review_package(object_name="ZI_ERROR_TEST", source=source_content)
    result = await connector.checkrun_cds_in_sap(package)

    assert result.success is False
    assert result.blocking_errors == 1
    assert result.status == SAPValidationStatus.ERROR


@pytest.mark.asyncio
async def test_connector_checkrun_preflight_security_guards():
    """Verify checkrun rejects unapproved packages, ineligible packages, invalid namespaces, and REUSE."""
    settings = get_mock_settings()
    adt_client = SAPADTClient(settings=settings)
    connector = SAPADTConnector(settings=settings, client=adt_client)

    # 1. Unapproved status
    pkg_draft = make_test_review_package(status=ReviewStatus.PENDING_REVIEW)
    with pytest.raises(SAPSecurityError, match="Review status is 'PENDING_REVIEW'"):
        await connector.checkrun_cds_in_sap(pkg_draft)

    # 2. Ineligible for approval
    pkg_ineligible = make_test_review_package(can_approve=False)
    with pytest.raises(SAPSecurityError, match="Approval eligibility failed"):
        await connector.checkrun_cds_in_sap(pkg_ineligible)

    # 3. REUSE decision
    pkg_reuse = make_test_review_package(object_name="I_SalesOrder", action=DecisionAction.REUSE)
    with pytest.raises(SAPSecurityError, match="Standard SAP CDS views are already verified"):
        await connector.checkrun_cds_in_sap(pkg_reuse)

    # 4. Invalid customer namespace
    pkg_bad_ns = make_test_review_package(object_name="BAD_NAME_NO_Z")
    with pytest.raises(SAPSecurityError, match="violates SAP customer namespace rules"):
        await connector.checkrun_cds_in_sap(pkg_bad_ns)


@pytest.mark.asyncio
async def test_connector_checkrun_preflight_existence_check():
    """Verify checkrun raises SAPNotFoundError if object does not exist in SAP repository."""
    settings = get_mock_settings()

    def handler(request: httpx.Request):
        if request.method == "GET" and "/sap/bc/adt/ddic/ddl/sources/zi_nonexistent" in request.url.path:
            return httpx.Response(404, text="Not Found")
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF_TOKEN"})
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)
    connector = SAPADTConnector(settings=settings, client=adt_client)

    pkg = make_test_review_package(object_name="ZI_NONEXISTENT")
    with pytest.raises(SAPNotFoundError, match="does not exist in target repository"):
        await connector.checkrun_cds_in_sap(pkg)


# ---------------------------------------------------------------------------
# 2. Dual Activation Gate & Stale Invalidation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activation_blocked_without_checkrun():
    """Verify activation is blocked if checkrun has not been performed."""
    settings = get_mock_settings()
    adt_client = SAPADTClient(settings=settings)
    connector = SAPADTConnector(settings=settings, client=adt_client)

    pkg = make_test_review_package(object_name="ZI_NO_CHECKRUN")
    pkg.latest_sap_checkrun = None

    with pytest.raises(SAPSecurityError, match="has not undergone SAP checkrun"):
        await connector.activate_cds_in_sap(pkg)


@pytest.mark.asyncio
async def test_activation_blocked_with_failing_checkrun():
    """Verify activation is blocked if the latest checkrun reported blocking errors."""
    settings = get_mock_settings()
    adt_client = SAPADTClient(settings=settings)
    connector = SAPADTConnector(settings=settings, client=adt_client)

    pkg = make_test_review_package(object_name="ZI_FAILED_CHECKRUN")
    pkg.latest_sap_checkrun = SAPReviewCheckrunResult(
        review_id=pkg.review_id,
        sap_object_name=pkg.object_name,
        status=SAPValidationStatus.ERROR,
        success=False,
        check_report_status="processed",
        blocking_errors=2,
        warnings=0,
        information=0,
        messages=[],
        timestamp="2026-09-14T00:00:00Z",
        source_hash="abcd1234",
    )

    with pytest.raises(SAPSecurityError, match="reported 2 blocking E/A/X error"):
        await connector.activate_cds_in_sap(pkg)


@pytest.mark.asyncio
async def test_activation_blocked_with_stale_checkrun_hash_mismatch():
    """Verify activation is blocked if repository source was modified after checkrun."""
    settings = get_mock_settings()
    original_source = "define view entity ZI_STALE_TEST as select from I_SalesOrder { key SalesOrder };"
    modified_source = "define view entity ZI_STALE_TEST as select from I_SalesOrder { key SalesOrder, key OrderType };"

    def handler(request: httpx.Request):
        if request.method == "GET" and "/sap/bc/adt/ddic/ddl/sources/zi_stale_test" in request.url.path:
            return httpx.Response(200, text=modified_source)
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF_TOKEN"})
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)
    connector = SAPADTConnector(settings=settings, client=adt_client)

    pkg = make_test_review_package(object_name="ZI_STALE_TEST", source=original_source)
    # Checkrun ran against original_source
    pkg.latest_sap_checkrun = SAPReviewCheckrunResult(
        review_id=pkg.review_id,
        sap_object_name=pkg.object_name,
        status=SAPValidationStatus.PASS,
        success=True,
        check_report_status="processed",
        blocking_errors=0,
        warnings=0,
        information=0,
        messages=[],
        timestamp="2026-09-14T00:00:00Z",
        source_hash=hashlib.sha256(original_source.encode("utf-8")).hexdigest(),
    )

    with pytest.raises(SAPSecurityError, match="Stale checkrun for 'ZI_STALE_TEST'"):
        await connector.activate_cds_in_sap(pkg)


@pytest.mark.asyncio
async def test_activation_allowed_with_fresh_passed_checkrun():
    """Verify activation proceeds when checkrun passed with 0 errors and hash matches."""
    settings = get_mock_settings()
    source_content = "define view entity ZI_FRESH_TEST as select from I_SalesOrder { key SalesOrder };"

    def handler(request: httpx.Request):
        if request.method == "GET" and "/sap/bc/adt/ddic/ddl/sources/zi_fresh_test" in request.url.path:
            return httpx.Response(200, text=source_content)
        if request.method == "GET" and "/activation/inactiveobjects" in request.url.path:
            return httpx.Response(200, text="""<?xml version="1.0" encoding="UTF-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core" />""")
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF_TOKEN"})
        if request.method == "POST" and "/activation" in request.url.path:
            return httpx.Response(
                200,
                text="""<?xml version="1.0" encoding="UTF-8"?>
<chkr:checkRunReports xmlns:chkr="http://www.sap.com/adt/checkrun" />""",
            )
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)
    connector = SAPADTConnector(settings=settings, client=adt_client)

    pkg = make_test_review_package(object_name="ZI_FRESH_TEST", source=source_content)
    pkg.latest_sap_checkrun = SAPReviewCheckrunResult(
        review_id=pkg.review_id,
        sap_object_name=pkg.object_name,
        status=SAPValidationStatus.PASS,
        success=True,
        check_report_status="processed",
        blocking_errors=0,
        warnings=1,
        information=0,
        messages=[],
        timestamp="2026-09-14T00:00:00Z",
        source_hash=hashlib.sha256(source_content.encode("utf-8")).hexdigest(),
    )

    result = await connector.activate_cds_in_sap(pkg)
    assert result.success is True
    assert result.activation_status == "ACTIVE"


# ---------------------------------------------------------------------------
# 3. ReviewStore Checkrun & Activation Gate Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_store_checkrun_and_activation_workflow():
    """Verify ReviewStore executes checkrun, writes audit events, and enforces activation gate."""
    store = ReviewStore()
    source_content = "define view entity ZI_STORE_GATE as select from I_SalesOrder { key SalesOrder };"
    pkg = make_test_review_package(object_name="ZI_STORE_GATE", source=source_content)
    store.register(pkg)

    # 1. Activation blocked before checkrun
    with pytest.raises(GovernanceApprovalRequiredError, match="SAP Checkrun required before activation"):
        await store.execute_sap_activation(pkg.review_id)

    # 2. Mock connector for checkrun
    mock_connector = AsyncMock()
    mock_checkrun_result = SAPReviewCheckrunResult(
        review_id=pkg.review_id,
        sap_object_name=pkg.object_name,
        status=SAPValidationStatus.PASS,
        success=True,
        check_report_status="processed",
        blocking_errors=0,
        warnings=0,
        information=0,
        messages=[],
        timestamp="2026-09-14T00:00:00Z",
        source_hash=hashlib.sha256(source_content.encode("utf-8")).hexdigest(),
    )
    mock_connector.checkrun_cds_in_sap.return_value = mock_checkrun_result

    # Execute checkrun via store
    res = await store.execute_sap_checkrun(pkg.review_id, connector=mock_connector)
    assert res.success is True
    assert pkg.latest_sap_checkrun is not None

    # Check audit events
    audit_actions = [e.action for e in pkg.audit_events]
    assert "SAP_CHECKRUN_REQUESTED" in audit_actions
    assert "SAP_CHECKRUN_SUCCEEDED" in audit_actions

    # 3. Now activation succeeds
    mock_activation_result = SAPActivationResult(
        review_id=pkg.review_id,
        sap_object_name=pkg.object_name,
        activation_status="ACTIVE",
        success=True,
        sap_http_status=200,
    )
    mock_connector.activate_cds_in_sap.return_value = mock_activation_result

    act_res = await store.execute_sap_activation(pkg.review_id, connector=mock_connector)
    assert act_res.success is True
    assert act_res.activation_status == "ACTIVE"


@pytest.mark.asyncio
async def test_review_store_reupload_invalidates_checkrun():
    """Verify that re-uploading an existing shell resets latest_sap_checkrun to None."""
    store = ReviewStore()
    source_content = "extend view I_SalesOrder with ZI_EXT_INVALIDATE { _SalesOrderType.OrderType as OrderType };"
    pkg = make_test_review_package(
        object_name="ZI_EXT_INVALIDATE",
        action=DecisionAction.EXTEND,
        source=source_content,
    )
    pkg.latest_sap_checkrun = SAPReviewCheckrunResult(
        review_id=pkg.review_id,
        sap_object_name=pkg.object_name,
        status=SAPValidationStatus.PASS,
        success=True,
        check_report_status="processed",
        blocking_errors=0,
        warnings=0,
        information=0,
        messages=[],
        timestamp="2026-09-14T00:00:00Z",
        source_hash=hashlib.sha256(source_content.encode("utf-8")).hexdigest(),
    )
    store.register(pkg)

    mock_connector = AsyncMock()
    mock_connector.upload_existing_cds_in_sap.return_value = {
        "success": True,
        "object_name": pkg.object_name,
        "status": "CREATED_INACTIVE",
    }

    await store.execute_existing_shell_upload(
        pkg.review_id,
        transport_request="S3XK911848",
        connector=mock_connector,
    )

    # Checkrun must have been invalidated
    assert pkg.latest_sap_checkrun is None

    # Activation must be blocked now
    with pytest.raises(GovernanceApprovalRequiredError, match="SAP Checkrun required before activation"):
        await store.execute_sap_activation(pkg.review_id, connector=mock_connector)


@pytest.mark.asyncio
async def test_upload_checkrun_activation_lifecycle_accepts_unchanged_source():
    """Verify upload -> checkrun -> activation accepts fresh checkrun even with repository newline/whitespace variations,
    and correctly flags genuine source code modifications as stale."""
    store = ReviewStore()
    source_generated = "/* Generated CDS */\r\nextend view I_SalesOrder with ZI_REGRESSION_EXT {\r\n  _SalesOrderType.OrderTypeForBillingRequest as OrderTypeForBillingRequest\r\n};\r\n"
    pkg = make_test_review_package(
        object_name="ZI_REGRESSION_EXT",
        action=DecisionAction.EXTEND,
        source=source_generated,
        status=ReviewStatus.APPROVED,
    )
    store.register(pkg)

    mock_connector = AsyncMock()
    mock_connector.upload_source_to_existing_shell.return_value = SAPCreationResult(
        success=True,
        operation="UPLOAD_EXISTING_SHELL_SOURCE",
        review_id=pkg.review_id,
        sap_object_name=pkg.object_name,
        repository_uri="/sap/bc/adt/ddic/ddl/sources/zi_regression_ext",
        object_type="CUSTOM_VIEW_ENTITY",
        package="ZTRAINING_2026",
        activation_status="INACTIVE",
        transport_request="S3XK911848",
        sap_http_status=200,
        sap_write_performed=True,
    )

    # 1. Upload to existing shell
    await store.execute_existing_shell_upload(
        pkg.review_id,
        transport_request="S3XK911848",
        connector=mock_connector,
    )
    # Checkrun must be reset to None after upload
    assert pkg.latest_sap_checkrun is None

    # Activation must be blocked because checkrun is missing
    with pytest.raises(GovernanceApprovalRequiredError, match="SAP Checkrun required before activation"):
        await store.execute_sap_activation(pkg.review_id, connector=mock_connector)

    # 2. Checkrun executed against inactive SAP draft (SAP trims trailing newline and normalizes)
    sap_stored_source = source_generated.replace("\r\n", "\n").strip()
    checkrun_source_hash = SAPADTClient.compute_source_hash(sap_stored_source)

    mock_checkrun_result = SAPReviewCheckrunResult(
        review_id=pkg.review_id,
        sap_object_name=pkg.object_name,
        status=SAPValidationStatus.WARNING,
        success=True,
        check_report_status="processed",
        blocking_errors=0,
        warnings=1,
        information=0,
        messages=[],
        timestamp="2026-09-14T16:24:36Z",
        source_hash=checkrun_source_hash,
    )
    mock_connector.checkrun_cds_in_sap.return_value = mock_checkrun_result

    checkrun_res = await store.execute_sap_checkrun(pkg.review_id, connector=mock_connector)
    assert checkrun_res.success is True
    assert checkrun_res.blocking_errors == 0
    assert pkg.latest_sap_checkrun is not None
    assert pkg.latest_sap_checkrun.source_hash == checkrun_source_hash

    # 3. Activation must SUCCEED because source is unchanged (no stale error!)
    mock_activation_result = SAPActivationResult(
        success=True,
        operation="ACTIVATE_CDS_VIEW",
        review_id=pkg.review_id,
        sap_object_name=pkg.object_name,
        repository_uri="/sap/bc/adt/ddic/ddl/sources/zi_regression_ext",
        object_type="CUSTOM_VIEW_ENTITY",
        package="ZTRAINING_2026",
        activation_status="ACTIVE",
        transport_request="S3XK911848",
        sap_http_status=200,
        sap_write_performed=True,
    )
    mock_connector.activate_cds_in_sap.return_value = mock_activation_result

    act_res = await store.execute_sap_activation(
        pkg.review_id,
        transport_request="S3XK911848",
        connector=mock_connector,
    )
    assert act_res.success is True
    assert act_res.activation_status == "ACTIVE"

    # 4. If source is legitimately modified, activation must be rejected as STALE
    pkg.ddl_source = source_generated + "\n  _Extra.ModifiedField as ModifiedField\n"
    with pytest.raises(GovernanceApprovalRequiredError, match="Stale checkrun: CDS source code was modified after checkrun"):
        await store.execute_sap_activation(
            pkg.review_id,
            transport_request="S3XK911848",
            connector=mock_connector,
        )



# ---------------------------------------------------------------------------
# 4. REST API Endpoint Tests: POST /api/v1/reviews/{review_id}/checkrun-sap
# ---------------------------------------------------------------------------


def test_api_checkrun_success_and_errors():
    """Verify REST API endpoint handles checkrun, not found, unapproved, and REUSE scenarios."""
    from fastapi.testclient import TestClient
    from src.api.routes.reviews import get_review_store

    client = TestClient(app)
    store = get_review_store()

    # 1. 404 for unknown review
    resp = client.post("/api/v1/reviews/rev_nonexistent/checkrun-sap")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()

    # 2. 403 for unapproved review
    pkg_draft = make_test_review_package(object_name="ZI_DRAFT_PKG", status=ReviewStatus.PENDING_REVIEW)
    store.register(pkg_draft)
    resp = client.post(f"/api/v1/reviews/{pkg_draft.review_id}/checkrun-sap")
    assert resp.status_code == 403
    assert "approval" in resp.json()["detail"].lower()

    # 3. 403 for REUSE review
    pkg_reuse = make_test_review_package(
        object_name="I_SalesOrder",
        action=DecisionAction.REUSE,
        status=ReviewStatus.APPROVED,
    )
    store.register(pkg_reuse)
    resp = client.post(f"/api/v1/reviews/{pkg_reuse.review_id}/checkrun-sap")
    assert resp.status_code == 403
    assert "reuse" in resp.json()["detail"].lower()

    # 4. Successful checkrun execution with mock connector
    source_content = "define view entity ZI_API_CHECKRUN as select from I_SalesOrder { key SalesOrder };"
    pkg_approved = make_test_review_package(object_name="ZI_API_CHECKRUN", source=source_content)
    store.register(pkg_approved)

    mock_result = SAPReviewCheckrunResult(
        review_id=pkg_approved.review_id,
        sap_object_name=pkg_approved.object_name,
        status=SAPValidationStatus.PASS,
        success=True,
        check_report_status="processed",
        blocking_errors=0,
        warnings=1,
        information=0,
        messages=[],
        timestamp="2026-09-14T00:00:00Z",
        source_hash=hashlib.sha256(source_content.encode("utf-8")).hexdigest(),
    )

    with patch.object(store, "execute_sap_checkrun", new=AsyncMock(return_value=mock_result)):
        resp = client.post(f"/api/v1/reviews/{pkg_approved.review_id}/checkrun-sap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["sap_object_name"] == "ZI_API_CHECKRUN"
        assert data["blocking_errors"] == 0
        assert data["warnings"] == 1
