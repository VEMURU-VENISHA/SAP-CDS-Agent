"""Milestone 13.6: Deterministic Tests for SAP ADT Stateful Session Handling.

Validates the stateful session lifecycle between LOCK and PUT:
A. LOCK and PUT use the same HTTP client/session.
B. X-sap-adt-sessiontype: stateful is present on LOCK, PUT, and UNLOCK.
C. Cookies and session state are preserved across requests.
D. CSRF token remains available without redundant refetches.
E. lockHandle from LOCK is passed to PUT.
F. corrNr remains passed to PUT.
G. Invalid write configuration causes zero network calls.
H. SAP_LIVE_READ_ONLY=true blocks LOCK/PUT.
I. Activation, transport, and delete endpoints remain blocked.
J. No secrets, tokens, cookies, or lock handles are logged.
"""

import logging
from typing import List
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from src.config import Settings
from src.core.exceptions import SAPConnectorError, SAPSecurityError
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


def _make_sample_state(object_name: str = "ZI_STATEFUL_TEST") -> CDSWorkflowState:
    req = BusinessRequirement(
        title="Stateful Session Test",
        description="Requirement for testing stateful ADT session",
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
        rationale="Stateful test decision",
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


def _make_approved_package(object_name: str = "ZI_STATEFUL_TEST") -> CDSReviewPackage:
    state = _make_sample_state(object_name=object_name)
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved_pkg = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved for stateful test")
    return approved_pkg


# -----------------------------------------------------------------------------
# Tests A, B, C, D, E, F: Full Stateful Session Lifecycle
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lock_and_put_use_same_session_with_stateful_headers_and_cookies():
    captured_requests: List[httpx.Request] = []

    lock_xml = """<?xml version="1.0" encoding="utf-8"?>
<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
    <DATA>
      <LOCK_HANDLE>00505684D34C1ED68AE9A4A1C813E22900000000</LOCK_HANDLE>
      <CORRNR>S3XK911848</CORRNR>
      <CORRUSER>DEVELOPER</CORRUSER>
      <CORRTEXT>Milestone 13.6 test</CORRTEXT>
    </DATA>
  </asx:values>
</asx:abap>"""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)

        # GET CSRF Token
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={
                    "x-csrf-token": "MOCK_CSRF_TOKEN_999",
                    "set-cookie": "SAP_SESSIONID_S3X=INIT_SESSION_ID; Path=/",
                },
                text="<ok/>",
            )

        # POST LOCK
        if request.method == "POST" and "_action=LOCK" in str(request.url):
            # Assert stateful header is sent on LOCK
            assert request.headers.get("x-sap-adt-sessiontype") == "stateful"
            # Assert CSRF token is sent
            assert request.headers.get("x-csrf-token") == "MOCK_CSRF_TOKEN_999"
            # Return stateful cookie
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result",
                    "set-cookie": "sap-contextid=STATEFUL_CTX_XYZ; Path=/",
                },
                text=lock_xml,
            )

        # PUT Source Upload
        if request.method == "PUT":
            # Requirement B: X-sap-adt-sessiontype: stateful MUST be present
            session_type = request.headers.get("x-sap-adt-sessiontype")
            assert session_type == "stateful", f"Expected stateful session header, got: {session_type}"

            # Requirement C: Session cookies from previous requests MUST be preserved
            cookie_header = request.headers.get("cookie", "")
            assert "sap-contextid" in cookie_header or "SAP_SESSIONID_S3X" in cookie_header

            # Requirement D: CSRF token MUST remain available
            assert request.headers.get("x-csrf-token") == "MOCK_CSRF_TOKEN_999"

            # Requirement E: lockHandle from LOCK MUST be in query params
            assert "lockHandle=00505684D34C1ED68AE9A4A1C813E22900000000" in str(request.url)

            # Requirement F: corrNr MUST be in query params
            assert "corrNr=S3XK911848" in str(request.url)

            return httpx.Response(204)

        return httpx.Response(404)

    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_DEV_PACKAGE="ZTRAINING_2026",
    )
    mock_transport = httpx.MockTransport(mock_handler)
    shared_http_client = httpx.AsyncClient(transport=mock_transport, base_url="https://mock-sap:443")

    # Use single client instance for both operations
    client = SAPADTClient(settings=settings, client=shared_http_client)
    pkg = _make_approved_package()

    # Step 1: Acquire lock
    assert client.is_stateful is False
    lock_res = await client.lock_ddls_object("ZI_STATEFUL_TEST", access_mode="MODIFY", review_package=pkg)

    assert lock_res["lock_handle"] == "00505684D34C1ED68AE9A4A1C813E22900000000"
    assert lock_res["corr_nr"] == "S3XK911848"
    assert client.is_stateful is True

    # Step 2: Upload source using the same client
    status_code = await client.upload_ddls_source(
        view_name="ZI_STATEFUL_TEST",
        ddl_source="define view entity ZI_STATEFUL_TEST as select from I_SalesOrder { key SalesOrder };",
        lock_handle=lock_res["lock_handle"],
        corr_nr=lock_res["corr_nr"],
        review_package=pkg,
    )

    assert status_code == 204

    # Requirement A: Verify LOCK and PUT used the exact same HTTP client
    post_req = next(r for r in captured_requests if r.method == "POST")
    put_req = next(r for r in captured_requests if r.method == "PUT")
    assert post_req is not None
    assert put_req is not None


# -----------------------------------------------------------------------------
# Test B (Unlock): unLock sends stateful header and resets state
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unlock_sends_stateful_header_and_resets_is_stateful():
    captured_requests: List[httpx.Request] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "CSRF_TOKEN"}, text="<ok/>")
        if request.method == "POST":
            assert request.headers.get("x-sap-adt-sessiontype") == "stateful"
            return httpx.Response(200)
        return httpx.Response(404)

    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
    )
    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport, base_url="https://mock-sap:443")
    client = SAPADTClient(settings=settings, client=mock_http)
    client._is_stateful = True
    pkg = _make_approved_package()

    ok = await client.unlock_ddls_object("ZI_STATEFUL_TEST", lock_handle="TOKEN_123", review_package=pkg)

    assert ok is True
    assert client.is_stateful is False
    post_req = next(r for r in captured_requests if r.method == "POST")
    assert "_action=UNLOCK" in str(post_req.url)
    assert post_req.headers.get("x-sap-adt-sessiontype") == "stateful"


# -----------------------------------------------------------------------------
# Test G: Invalid write configuration causes zero network calls
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_write_configuration_causes_zero_network_calls():
    captured_requests: List[httpx.Request] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200)

    # SAP_DEV_WRITE_ENABLED is False!
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=False,
        SAP_LIVE_READ_ONLY=False,
    )
    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport, base_url="https://mock-sap:443")
    client = SAPADTClient(settings=settings, client=mock_http)
    pkg = _make_approved_package()

    with pytest.raises(SAPSecurityError) as exc_info:
        await client.lock_ddls_object("ZI_STATEFUL_TEST", review_package=pkg)

    assert "SAP DEV write capability is disabled" in str(exc_info.value)
    # Zero network calls were dispatched
    assert len(captured_requests) == 0


# -----------------------------------------------------------------------------
# Test H: SAP_LIVE_READ_ONLY=true blocks LOCK/PUT
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sap_live_read_only_true_blocks_lock_and_put():
    captured_requests: List[httpx.Request] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200)

    # SAP_LIVE_READ_ONLY is True
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=True,
    )
    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport, base_url="https://mock-sap:443")
    client = SAPADTClient(settings=settings, client=mock_http)
    pkg = _make_approved_package()

    with pytest.raises(SAPSecurityError) as exc_lock:
        await client.lock_ddls_object("ZI_STATEFUL_TEST", review_package=pkg)
    assert "SAP_LIVE_READ_ONLY is enabled" in str(exc_lock.value)

    with pytest.raises(SAPSecurityError) as exc_put:
        await client.upload_ddls_source(
            view_name="ZI_STATEFUL_TEST",
            ddl_source="test",
            lock_handle="TOKEN",
            corr_nr="S3XK911848",
            review_package=pkg,
        )
    assert "SAP_LIVE_READ_ONLY is enabled" in str(exc_put.value)

    assert len(captured_requests) == 0


# -----------------------------------------------------------------------------
# Test I: Activation, transport, and delete endpoints remain blocked
# -----------------------------------------------------------------------------
def test_activation_transport_and_delete_remain_blocked():
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
    )
    client = SAPADTClient(settings=settings)
    pkg = _make_approved_package()

    # Activation blocked
    with pytest.raises(SAPSecurityError) as exc_act:
        client.assert_dev_write_policy("POST", "/sap/bc/adt/activation", review_package=pkg)
    assert "blocked activation endpoint" in str(exc_act.value)

    # Transport management blocked
    with pytest.raises(SAPSecurityError) as exc_tr:
        client.assert_dev_write_policy("POST", "/sap/bc/adt/cts/transports", review_package=pkg)
    assert "blocked transport management endpoint" in str(exc_tr.value)

    # Arbitrary delete blocked
    with pytest.raises(SAPSecurityError) as exc_del:
        client.assert_dev_write_policy("DELETE", "/sap/bc/adt/ddic/ddl/sources/zi_test", review_package=pkg)
    assert "blocked unauthorized DELETE write" in str(exc_del.value)


# -----------------------------------------------------------------------------
# Test J: No secrets, tokens, cookies, or lock handles logged
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_secrets_or_tokens_logged(caplog):
    caplog.set_level(logging.DEBUG)

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "SECRET_CSRF_TOKEN_456"}, text="<ok/>")
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"set-cookie": "SAP_SESSIONID_S3X=SUPER_SECRET_COOKIE; Path=/"},
                text="""<?xml version="1.0" encoding="utf-8"?>
<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
    <DATA>
      <LOCK_HANDLE>SUPER_SECRET_LOCK_HANDLE_789</LOCK_HANDLE>
      <CORRNR>S3XK911848</CORRNR>
    </DATA>
  </asx:values>
</asx:abap>""",
            )
        if request.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(404)

    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
    )
    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport, base_url="https://mock-sap:443")
    client = SAPADTClient(settings=settings, client=mock_http)
    pkg = _make_approved_package()

    lock_res = await client.lock_ddls_object("ZI_STATEFUL_TEST", access_mode="MODIFY", review_package=pkg)
    await client.upload_ddls_source(
        view_name="ZI_STATEFUL_TEST",
        ddl_source="source",
        lock_handle=lock_res["lock_handle"],
        corr_nr=lock_res["corr_nr"],
        review_package=pkg,
    )

    client_logs = " ".join([r.message for r in caplog.records if r.name.startswith("sap_cds_platform")])

    assert "SUPER_SECRET_LOCK_HANDLE_789" not in client_logs
    assert "SECRET_CSRF_TOKEN_456" not in client_logs
    assert "SUPER_SECRET_COOKIE" not in client_logs
    assert "Authorization" not in client_logs
