"""Milestone 13.3: ADT lockHandle Acquisition and Propagation Offline Tests.

Validates the robust extraction, propagation, and safety guardrails for SAP ADT lockHandle:
1. Extraction from standard and SAP custom response headers
2. Extraction from XML attributes (with namespaces, single/double quotes)
3. Extraction from XML child elements
4. Sensitive header sanitization in Step A diagnostics
5. Pre-socket validation preventing source upload without lockHandle
6. Correct query parameter propagation when lockHandle is present
7. Connector-level halt when Step A yields no lockHandle
"""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.config import Settings
from src.core.exceptions import SAPConnectorError, SAPNotFoundError
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
    StructuredRequirement,
    TargetUseCase,
    ValidationResult,
)
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector
from src.services.review_service import ReviewStore, build_review_package


def _make_sample_state(object_name: str = "ZI_LOCK_TEST") -> CDSWorkflowState:
    req = BusinessRequirement(
        title="Lock Handle Test",
        description="Requirement for testing lock handle acquisition",
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
        rationale="Lock handle test decision",
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
        object_type="DDLS/DF",
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


def _make_approved_package(object_name: str = "ZI_LOCK_TEST") -> CDSReviewPackage:
    state = _make_sample_state(object_name=object_name)
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved_pkg = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved for testing")
    return approved_pkg


def _make_client(transport_handler) -> SAPADTClient:
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_CONNECTOR_TYPE="adt",
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_DEV_PACKAGE="ZTRAINING_2026",
    )
    mock_transport = httpx.MockTransport(transport_handler)
    mock_http_client = httpx.AsyncClient(transport=mock_transport, base_url="https://mock-sap:443")
    client = SAPADTClient(settings=settings)
    client._custom_client = mock_http_client
    return client


# -----------------------------------------------------------------------------
# 1. Header Variant Extraction Tests
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "header_name,header_value",
    [
        ("lockHandle", "LOCK_HDR_01"),
        ("Lock-Handle", "LOCK_HDR_02"),
        ("X-SAP-ADT-LockHandle", "LOCK_HDR_03"),
        ("x-sap-adt-lock-handle", "LOCK_HDR_04"),
        ("X-SAP-ADT-Session-Lock", "LOCK_HDR_05"),
    ],
)
@pytest.mark.asyncio
async def test_create_ddls_shell_extracts_lock_handle_from_headers(header_name: str, header_value: str):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF"}, text="<ok/>")
        if request.method == "POST":
            return httpx.Response(
                201,
                headers={
                    "Location": "/sap/bc/adt/ddic/ddl/sources/zi_lock_test",
                    header_name: header_value,
                },
                text="<ddl:ddlSource/>",
            )
        return httpx.Response(404)

    client = _make_client(handler)
    pkg = _make_approved_package()
    res = await client.create_ddls_shell("ZI_LOCK_TEST", "ZTRAINING_2026", corr_nr="S3XK911848", review_package=pkg)

    assert res["status_code"] == 201
    assert res["lock_handle"] == header_value


# -----------------------------------------------------------------------------
# 2. XML Attribute Extraction Tests
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "xml_body,expected_lock",
    [
        (
            '<?xml version="1.0"?><ddl:ddlSource xmlns:ddl="http://www.sap.com/adt/ddl" lockHandle="LOCK_ATTR_01"/>',
            "LOCK_ATTR_01",
        ),
        (
            '<?xml version="1.0"?><ddl:ddlSource xmlns:adtcore="http://www.sap.com/adt/core" adtcore:lockHandle="LOCK_ATTR_02"/>',
            "LOCK_ATTR_02",
        ),
        (
            "<?xml version=\"1.0\"?><ddl:ddlSource lockHandle='LOCK_ATTR_SINGLE_QUOTES'/>",
            "LOCK_ATTR_SINGLE_QUOTES",
        ),
        (
            '<?xml version="1.0"?><ddl:ddlSource><adtcore:objectReference xmlns:adtcore="http://www.sap.com/adt/core" adtcore:lockHandle="LOCK_NESTED_ATTR_03"/></ddl:ddlSource>',
            "LOCK_NESTED_ATTR_03",
        ),
    ],
)
@pytest.mark.asyncio
async def test_create_ddls_shell_extracts_lock_handle_from_xml_attributes(xml_body: str, expected_lock: str):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF"}, text="<ok/>")
        if request.method == "POST":
            return httpx.Response(
                201,
                headers={"Location": "/sap/bc/adt/ddic/ddl/sources/zi_lock_test"},
                text=xml_body,
            )
        return httpx.Response(404)

    client = _make_client(handler)
    pkg = _make_approved_package()
    res = await client.create_ddls_shell("ZI_LOCK_TEST", "ZTRAINING_2026", corr_nr="S3XK911848", review_package=pkg)

    assert res["status_code"] == 201
    assert res["lock_handle"] == expected_lock


# -----------------------------------------------------------------------------
# 3. XML Element Extraction Tests
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "xml_body,expected_lock",
    [
        (
            '<?xml version="1.0"?><ddl:ddlSource xmlns:adtcore="http://www.sap.com/adt/core"><adtcore:lockHandle>LOCK_TAG_01</adtcore:lockHandle></ddl:ddlSource>',
            "LOCK_TAG_01",
        ),
        (
            '<?xml version="1.0"?><ddl:ddlSource><lockHandle>LOCK_TAG_02</lockHandle></ddl:ddlSource>',
            "LOCK_TAG_02",
        ),
    ],
)
@pytest.mark.asyncio
async def test_create_ddls_shell_extracts_lock_handle_from_xml_elements(xml_body: str, expected_lock: str):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF"}, text="<ok/>")
        if request.method == "POST":
            return httpx.Response(
                201,
                headers={"Location": "/sap/bc/adt/ddic/ddl/sources/zi_lock_test"},
                text=xml_body,
            )
        return httpx.Response(404)

    client = _make_client(handler)
    pkg = _make_approved_package()
    res = await client.create_ddls_shell("ZI_LOCK_TEST", "ZTRAINING_2026", corr_nr="S3XK911848", review_package=pkg)

    assert res["status_code"] == 201
    assert res["lock_handle"] == expected_lock


# -----------------------------------------------------------------------------
# 4. Safe Diagnostic Headers Sanitization
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_ddls_shell_captures_safe_headers_without_secrets():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF"}, text="<ok/>")
        if request.method == "POST":
            return httpx.Response(
                201,
                headers={
                    "Location": "/sap/bc/adt/ddic/ddl/sources/zi_lock_test",
                    "etag": "202609130739410003",
                    "content-type": "application/vnd.sap.adt.ddlSource+xml",
                    "set-cookie": "SAP_SESSIONID_S3X=SECRET123; path=/",
                    "authorization": "Bearer super_secret_token",
                    "x-csrf-token": "csrf_token_secret",
                },
                text="<ddl:ddlSource lockHandle='LOCK_SAFE_01'/>",
            )
        return httpx.Response(404)

    client = _make_client(handler)
    pkg = _make_approved_package()
    res = await client.create_ddls_shell("ZI_LOCK_TEST", "ZTRAINING_2026", corr_nr="S3XK911848", review_package=pkg)

    safe_h = res["safe_headers"]
    assert "location" in safe_h or "Location" in safe_h
    assert "etag" in safe_h

    # Ensure zero sensitive headers in safe_headers
    for k in safe_h:
        k_lower = k.lower()
        assert "cookie" not in k_lower
        assert "auth" not in k_lower
        assert "token" not in k_lower
        assert "session" not in k_lower


# -----------------------------------------------------------------------------
# 5. Pre-Socket Validation: upload_ddls_source Rejects Missing lockHandle
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("bad_lock", [None, "", "   "])
@pytest.mark.asyncio
async def test_upload_ddls_source_rejects_missing_lock_handle(bad_lock):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    client = _make_client(handler)
    pkg = _make_approved_package()

    with pytest.raises(SAPConnectorError) as exc_info:
        await client.upload_ddls_source(
            view_name="ZI_LOCK_TEST",
            ddl_source="define view entity ZI_LOCK_TEST as select from I_SalesOrder { key SalesOrder };",
            lock_handle=bad_lock,
            corr_nr="S3XK911848",
            review_package=pkg,
        )

    assert "Missing mandatory lockHandle parameter" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 6. Propagation: upload_ddls_source Forwards lockHandle in Query Params
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_ddls_source_propagates_lock_handle_in_put_params():
    captured_requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF"}, text="<ok/>")
        if request.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(404)

    client = _make_client(handler)
    pkg = _make_approved_package()

    status = await client.upload_ddls_source(
        view_name="ZI_LOCK_TEST",
        ddl_source="define view entity ZI_LOCK_TEST as select from I_SalesOrder { key SalesOrder };",
        lock_handle="MY_EXTRACTED_LOCK_HANDLE_123",
        corr_nr="S3XK911848",
        review_package=pkg,
    )

    assert status == 204
    put_req = next(r for r in captured_requests if r.method == "PUT")
    assert "lockHandle=MY_EXTRACTED_LOCK_HANDLE_123" in str(put_req.url)
    assert "corrNr=S3XK911848" in str(put_req.url)


# -----------------------------------------------------------------------------
# 7. Connector Safe Halt: create_cds_in_sap Aborts if Step A Yields No lockHandle
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_cds_in_sap_aborts_safely_if_step_a_yields_no_lock_handle():
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_DEV_PACKAGE="ZTRAINING_2026",
    )
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    mock_client.validate_transport_request = SAPADTClient.validate_transport_request
    mock_client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZI_LOCK_TEST"))

    # Step A succeeds with HTTP 201 but returns lock_handle=None
    mock_client.create_ddls_shell = AsyncMock(
        return_value={
            "status_code": 201,
            "lock_handle": None,
            "location": "/sap/bc/adt/ddic/ddl/sources/zi_lock_test",
        }
    )
    # Fallback lock acquisition also returns None or fails
    mock_client.lock_ddls_object = AsyncMock(return_value={"lock_handle": None})
    mock_client.upload_ddls_source = AsyncMock()

    connector = SAPADTConnector(settings=settings, client=mock_client)
    pkg = _make_approved_package()

    with pytest.raises(SAPConnectorError) as exc_info:
        await connector.create_cds_in_sap(pkg, transport_request="S3XK911848")

    assert "no lockHandle could be acquired from SAP" in str(exc_info.value)
    # Crucially, Step B must NEVER have been called!
    mock_client.upload_ddls_source.assert_not_called()


# -----------------------------------------------------------------------------
# 8. Connector Fallback: create_cds_in_sap Acquires Lock via lock_ddls_object
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_cds_in_sap_acquires_lock_via_lock_ddls_object_when_step_a_has_no_lock():
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_DEV_PACKAGE="ZTRAINING_2026",
    )
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    mock_client.validate_transport_request = SAPADTClient.validate_transport_request
    mock_client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZI_LOCK_TEST"))

    # Step A succeeds with HTTP 201 but returns lock_handle=None (as observed in real SAP DEV)
    mock_client.create_ddls_shell = AsyncMock(
        return_value={
            "status_code": 201,
            "lock_handle": None,
            "location": "/sap/bc/adt/ddic/ddl/sources/zi_lock_test",
        }
    )
    # lock_ddls_object acquires the lock
    mock_client.lock_ddls_object = AsyncMock(
        return_value={
            "lock_handle": "TOKEN_ACQUIRED_FROM_LOCK_SERVICE",
            "corr_nr": "S3XK911848",
            "status_code": 200,
        }
    )
    mock_client.upload_ddls_source = AsyncMock(return_value=204)

    connector = SAPADTConnector(settings=settings, client=mock_client)
    pkg = _make_approved_package()

    res = await connector.create_cds_in_sap(pkg, transport_request="S3XK911848")

    assert res.success is True
    # Verify lock_ddls_object was called with correct parameters
    mock_client.lock_ddls_object.assert_called_once_with(
        view_name="ZI_LOCK_TEST",
        access_mode="MODIFY",
        review_package=pkg,
    )
    # Verify upload_ddls_source received the acquired lock handle
    mock_client.upload_ddls_source.assert_called_once()
    _, kwargs = mock_client.upload_ddls_source.call_args
    assert kwargs["lock_handle"] == "TOKEN_ACQUIRED_FROM_LOCK_SERVICE"
    assert kwargs["corr_nr"] == "S3XK911848"


# -----------------------------------------------------------------------------
# 9. Connector Propagation: create_cds_in_sap Passes lock_handle to Step B
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_cds_in_sap_propagates_lock_handle_to_upload():
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_DEV_PACKAGE="ZTRAINING_2026",
    )
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    mock_client.validate_transport_request = SAPADTClient.validate_transport_request
    mock_client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZI_LOCK_TEST"))

    mock_client.create_ddls_shell = AsyncMock(
        return_value={
            "status_code": 201,
            "lock_handle": "TOKEN_ABC_789",
            "location": "/sap/bc/adt/ddic/ddl/sources/zi_lock_test",
        }
    )
    mock_client.upload_ddls_source = AsyncMock(return_value=204)

    connector = SAPADTConnector(settings=settings, client=mock_client)
    pkg = _make_approved_package()

    res = await connector.create_cds_in_sap(pkg, transport_request="S3XK911848")

    assert res.success is True
    mock_client.upload_ddls_source.assert_called_once()
    _, kwargs = mock_client.upload_ddls_source.call_args
    assert kwargs["lock_handle"] == "TOKEN_ABC_789"
    assert kwargs["corr_nr"] == "S3XK911848"


# -----------------------------------------------------------------------------
# 10. lock_ddls_object Protocol and AS-XML Parsing
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lock_ddls_object_parses_as_xml_response():
    sample_asx_body = """<?xml version="1.0" encoding="utf-8"?>
<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
    <DATA>
      <LOCK_HANDLE>LOCK_HANDLE_ASXML_9999</LOCK_HANDLE>
      <CORRNR>S3XK911848</CORRNR>
      <CORRUSER>DEVELOPER</CORRUSER>
      <CORRTEXT>Dev CDS modification lock</CORRTEXT>
    </DATA>
  </asx:values>
</asx:abap>"""

    captured_requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF"}, text="<ok/>")
        if request.method == "POST":
            return httpx.Response(200, text=sample_asx_body)
        return httpx.Response(404)

    client = _make_client(handler)
    pkg = _make_approved_package()

    res = await client.lock_ddls_object(
        view_name="ZI_LOCK_TEST",
        access_mode="MODIFY",
        review_package=pkg,
    )

    assert res["status_code"] == 200
    assert res["lock_handle"] == "LOCK_HANDLE_ASXML_9999"
    assert res["corr_nr"] == "S3XK911848"

    # Verify request URI, query params and Accept header
    post_req = next(r for r in captured_requests if r.method == "POST")
    assert "/sap/bc/adt/ddic/ddl/sources/zi_lock_test" in post_req.url.path
    assert "_action=LOCK" in str(post_req.url)
    assert "accessMode=MODIFY" in str(post_req.url)
    assert "com.sap.adt.lock.result" in post_req.headers["Accept"]


# -----------------------------------------------------------------------------
# 11. unlock_ddls_object Protocol
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unlock_ddls_object_sends_correct_action_and_lock_handle():
    captured_requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF"}, text="<ok/>")
        if request.method == "POST":
            return httpx.Response(200)
        return httpx.Response(404)

    client = _make_client(handler)
    pkg = _make_approved_package()

    ok = await client.unlock_ddls_object(
        view_name="ZI_LOCK_TEST",
        lock_handle="LOCK_HANDLE_ASXML_9999",
        review_package=pkg,
    )

    assert ok is True
    post_req = next(r for r in captured_requests if r.method == "POST")
    assert "/sap/bc/adt/ddic/ddl/sources/zi_lock_test" in post_req.url.path
    assert "_action=UNLOCK" in str(post_req.url)
    assert "lockHandle=LOCK_HANDLE_ASXML_9999" in str(post_req.url)


# -----------------------------------------------------------------------------
# 12. Pre-Socket Security Interceptor for Lock and Unlock
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lock_ddls_object_blocked_when_write_disabled():
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=False,  # Disabled!
        SAP_LIVE_READ_ONLY=True,
    )
    client = SAPADTClient(settings=settings)
    pkg = _make_approved_package()

    with pytest.raises(Exception) as exc_info:
        await client.lock_ddls_object("ZI_LOCK_TEST", review_package=pkg)
    assert "SAP DEV write capability is disabled" in str(exc_info.value)


@pytest.mark.asyncio
async def test_lock_ddls_object_blocked_when_read_only_true():
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=True,  # Read-only flag is active!
    )
    client = SAPADTClient(settings=settings)
    pkg = _make_approved_package()

    with pytest.raises(Exception) as exc_info:
        await client.lock_ddls_object("ZI_LOCK_TEST", review_package=pkg)
    assert "SAP_LIVE_READ_ONLY is enabled" in str(exc_info.value)


@pytest.mark.asyncio
async def test_lock_ddls_object_blocked_without_approved_review():
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
    )
    client = SAPADTClient(settings=settings)

    # Missing review package
    with pytest.raises(Exception) as exc_info:
        await client.lock_ddls_object("ZI_LOCK_TEST", review_package=None)
    assert "Missing human review package" in str(exc_info.value)
