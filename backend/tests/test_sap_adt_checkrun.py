"""Milestone 7: Unit and Integration Tests for SAP ADT Checkrun Validation."""

import pytest
import re
import httpx
from unittest.mock import AsyncMock, patch

from src.agents.state import CDSWorkflowState
from src.agents.validation_agent import ValidationAgent
from src.config import Settings
from src.models.domain import (
    BusinessRequirement,
    CDSDraft,
    Decision,
    DecisionAction,
    DraftElementType,
    DraftFieldElement,
    ElementEvidenceRecord,
    EvidenceLevel,
    SAPCheckMessage,
    SAPCheckrunResult,
    SAPValidationStatus,
    TargetUseCase,
    ValidationResult,
)
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector


def get_mock_settings():
    return Settings(
        SAP_BASE_URL="https://sap-dev.corp.internal:44300",
        SAP_CLIENT="100",
        SAP_USERNAME="DEVELOPER",
        SAP_PASSWORD="SuperSecretPassword123!",
        SAP_AUTH_TYPE="basic",
        SAP_VERIFY_SSL=False,
    )


# 1. Correct checkrun XML generation
def test_checkrun_xml_generation():
    client = SAPADTClient(settings=get_mock_settings())
    xml = client._build_checkrun_xml("/sap/bc/adt/ddic/ddl/sources/i_salesorder", version="active")
    assert "<chkrun:checkObjectList" in xml
    assert 'xmlns:chkrun="http://www.sap.com/adt/checkrun"' in xml
    assert 'xmlns:adtcore="http://www.sap.com/adt/core"' in xml
    assert 'adtcore:uri="/sap/bc/adt/ddic/ddl/sources/i_salesorder"' in xml
    assert 'chkrun:version="active"' in xml


# 2. Correct POST path, Content-Type, Accept, and CSRF token headers
@pytest.mark.asyncio
async def test_checkrun_post_path_and_headers():
    settings = get_mock_settings()
    captured_requests = []

    def handler(request: httpx.Request):
        captured_requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "MOCK_CSRF_TOKEN_42"})
        return httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/i_salesorder" chkrun:status="processed" />
</chkrun:checkRunReports>""",
            headers={"Content-Type": "application/vnd.sap.adt.checkmessages+xml; charset=utf-8"},
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)

    result = await adt_client.run_checkrun("/sap/bc/adt/ddic/ddl/sources/i_salesorder")

    post_reqs = [r for r in captured_requests if r.method == "POST"]
    assert len(post_reqs) == 1
    post_req = post_reqs[0]
    assert post_req.url.path == "/sap/bc/adt/checkruns"
    assert post_req.url.query.decode("utf-8") == "reporters=abapCheckRun"
    assert post_req.headers["Content-Type"] == "application/vnd.sap.adt.checkobjects+xml"
    assert post_req.headers["Accept"] == "application/vnd.sap.adt.checkmessages+xml"
    assert post_req.headers["X-CSRF-Token"] == "MOCK_CSRF_TOKEN_42"
    assert result.status == SAPValidationStatus.PASS


# 3. Successful 200 clean pass
def test_checkrun_200_clean_pass():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/i_salesorder" chkrun:status="processed">
  </chkrun:checkReport>
</chkrun:checkRunReports>"""
    res = SAPADTClient._parse_checkrun_xml(xml, http_status=200)
    assert res.status == SAPValidationStatus.PASS
    assert res.reporter == "abapCheckRun"
    assert res.triggering_uri == "/sap/bc/adt/ddic/ddl/sources/i_salesorder"
    assert len(res.messages) == 0


# 4. Warning parsing
def test_checkrun_warning_parsing():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/i_salesorder" chkrun:status="processed">
    <chkrun:checkMessage
      chkrun:uri="/sap/bc/adt/ddic/ddl/sources/i_salesorder#start=14,2"
      chkrun:type="W"
      chkrun:shortText="Field NetAmount should have a currency reference annotation"
      chkrun:msgid="S_CDS"
      chkrun:msgno="105"
      chkrun:msgv1="NetAmount"/>
  </chkrun:checkReport>
</chkrun:checkRunReports>"""
    res = SAPADTClient._parse_checkrun_xml(xml, http_status=200)
    assert res.status == SAPValidationStatus.WARNING
    assert len(res.messages) == 1
    msg = res.messages[0]
    assert msg.severity == "W"
    assert msg.line == 14
    assert msg.column == 2
    assert msg.short_text == "Field NetAmount should have a currency reference annotation"
    assert msg.msgid == "S_CDS"
    assert msg.msgno == "105"
    assert msg.variables == ["NetAmount"]


# 5. Error parsing
def test_checkrun_error_parsing():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/i_salesorder" chkrun:status="processed">
    <chkrun:checkMessage
      chkrun:uri="/sap/bc/adt/ddic/ddl/sources/i_salesorder#start=25,5"
      chkrun:type="E"
      chkrun:shortText="Field 'InvalidCol' does not exist in data source"
      chkrun:msgid="S_CDS"
      chkrun:msgno="042"
      chkrun:msgv1="InvalidCol"/>
  </chkrun:checkReport>
</chkrun:checkRunReports>"""
    res = SAPADTClient._parse_checkrun_xml(xml, http_status=200)
    assert res.status == SAPValidationStatus.ERROR
    assert len(res.messages) == 1
    assert res.messages[0].severity == "E"
    assert res.messages[0].line == 25
    assert res.messages[0].column == 5
    assert "InvalidCol" in res.messages[0].short_text


# 6. Multiple check messages (Error + Warning + Info)
def test_checkrun_multiple_check_messages():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/i_salesorder" chkrun:status="processed">
    <chkrun:checkMessage chkrun:uri="#start=5,1" chkrun:type="I" chkrun:shortText="Informational note" />
    <chkrun:checkMessage chkrun:uri="#start=10,2" chkrun:type="W" chkrun:shortText="Deprecated annotation" />
    <chkrun:checkMessage chkrun:uri="#start=20,4" chkrun:type="E" chkrun:shortText="Syntax error in expression" />
  </chkrun:checkReport>
</chkrun:checkRunReports>"""
    res = SAPADTClient._parse_checkrun_xml(xml, http_status=200)
    assert res.status == SAPValidationStatus.ERROR
    assert len(res.messages) == 3
    severities = [m.severity for m in res.messages]
    assert severities == ["I", "W", "E"]


# 7. Source line and column extraction
def test_checkrun_source_line_column_extraction():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun">
    <chkrun:checkMessage chkrun:uri="/path#start=42,15" chkrun:type="W" chkrun:shortText="Pos 1" />
    <chkrun:checkMessage chkrun:uri="/path#start=88" chkrun:type="W" chkrun:shortText="Pos 2" />
    <chkrun:checkMessage chkrun:type="W" chkrun:shortText="Pos 3" line="100" offset="4" />
  </chkrun:checkReport>
</chkrun:checkRunReports>"""
    res = SAPADTClient._parse_checkrun_xml(xml, http_status=200)
    assert res.messages[0].line == 42
    assert res.messages[0].column == 15
    assert res.messages[1].line == 88
    assert res.messages[1].column is None
    assert res.messages[2].line == 100
    assert res.messages[2].column == 4


# 8. Malformed XML handling
def test_checkrun_malformed_xml_handling():
    broken_xml = "<<chkrun:checkRunReports>BROKEN_CLOSING"
    res = SAPADTClient._parse_checkrun_xml(broken_xml, http_status=200)
    assert res.status == SAPValidationStatus.ERROR
    assert "Malformed XML" in (res.reason or "")


# 9. HTTP error handling (401, 403, 404, 500)
@pytest.mark.asyncio
async def test_checkrun_http_error_handling():
    settings = get_mock_settings()

    for code in (401, 403, 404, 500):
        def handler(request: httpx.Request):
            return httpx.Response(code, text=f"Error {code}")

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
        adt_client = SAPADTClient(settings=settings, client=mock_client)
        result = await adt_client.run_checkrun("/sap/bc/adt/ddic/ddl/sources/i_salesorder")

        assert result.status == SAPValidationStatus.UNAVAILABLE
        assert result.http_status == code


# 10. Timeout handling
@pytest.mark.asyncio
async def test_checkrun_timeout_handling():
    settings = get_mock_settings()

    def handler(request: httpx.Request):
        raise httpx.TimeoutException("Connection timed out")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)
    result = await adt_client.run_checkrun("/sap/bc/adt/ddic/ddl/sources/i_salesorder")

    assert result.status == SAPValidationStatus.UNAVAILABLE
    assert "timed out" in (result.reason or "")


# 11. Unconfigured SAP handling
@pytest.mark.asyncio
async def test_checkrun_unconfigured_sap():
    settings = Settings(SAP_BASE_URL="")  # Empty URL
    adt_client = SAPADTClient(settings=settings)
    result = await adt_client.run_checkrun("/sap/bc/adt/ddic/ddl/sources/i_salesorder")

    assert result.status == SAPValidationStatus.UNAVAILABLE
    assert "configuration error" in (result.reason or "")


# 12. Unpersisted draft returns UNAVAILABLE
@pytest.mark.asyncio
async def test_unpersisted_draft_returns_unavailable():
    connector = SAPADTConnector(settings=get_mock_settings())
    # No repository_uri passed (in-memory unpersisted draft)
    val_res = await connector.validate_cds(view_definition="define view entity ZC_Test as select from ...", repository_uri=None)

    assert val_res.sap_validation_status == SAPValidationStatus.UNAVAILABLE
    assert "Unpersisted Draft" in (val_res.sap_checkrun_reason or "")
    assert "requires a repository object URI" in (val_res.sap_checkrun_reason or "")


# 13. ValidationAgent fails when SAP checkrun returns ERROR
@pytest.mark.asyncio
async def test_validation_agent_fails_on_sap_error():
    connector = AsyncMock(spec=SAPADTConnector)
    connector.is_connected.return_value = True

    err_msg = SAPCheckMessage(severity="E", line=10, short_text="Syntax error in DDL source")
    checkrun_res = SAPCheckrunResult(
        status=SAPValidationStatus.ERROR,
        messages=[err_msg],
        triggering_uri="/sap/bc/adt/ddic/ddl/sources/i_salesorder",
    )
    connector.validate_cds.return_value = ValidationResult(
        is_valid=False,
        syntax_errors=["SAP Compiler Error (Line 10): Syntax error in DDL source"],
        sap_validation_status=SAPValidationStatus.ERROR,
        sap_checkrun_result=checkrun_res,
        sap_checkrun_reason="SAP compiler errors detected.",
    )

    agent = ValidationAgent(connector=connector)

    req = BusinessRequirement(
        title="Sales Analysis",
        description="Standard order analysis",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.REUSE,
        recommended_view="I_SalesOrder",
        confidence_score=1.0,
        fit_percentage=100.0,
        rationale="Standard reuse",
        missing_fields=[],
        tradeoffs=[],
        human_approval_required=False,
        is_approved=True,
    )
    draft = CDSDraft(
        requirement_id=req.id,
        decision_action=DecisionAction.REUSE,
        object_name="I_SalesOrder",
        object_type="REUSE_PROPOSAL",
        ddl_source="SELECT * FROM I_SalesOrder;",
        source_views=["I_SalesOrder"],
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "cds_draft": draft,
        "generated_cds_code": draft.ddl_source,
        "candidates": [],
        "audit_logs": [],
        "errors": [],
        "current_step": "VALIDATION",
    }

    final_state = await agent.run(state)
    val = final_state.get("validation_result")
    assert val is not None
    assert val.is_valid is False
    assert val.sap_validation_status == SAPValidationStatus.ERROR
    assert len(val.syntax_errors) > 0
    assert final_state["cds_draft"].generation_status == "REJECTED"


# 14. No secret leakage in logs
def test_no_secret_leakage_in_logs():
    client = SAPADTClient(settings=get_mock_settings())
    sanitized = client._sanitize_url_for_logging("/sap/bc/adt/checkruns?token=SecretToken123&password=MyPassword")
    assert "SecretToken123" not in sanitized
    assert "MyPassword" not in sanitized
    assert "token=***" in sanitized
    assert "password=***" in sanitized


# 15. Guaranteed write refusal
@pytest.mark.asyncio
async def test_no_sap_write_operations_in_checkrun():
    connector = SAPADTConnector(settings=get_mock_settings())
    with pytest.raises(Exception) as exc_create:
        await connector.create_cds_draft("Z_Test", "view def", "Z_PKG", "TR123")
    assert "disabled" in str(exc_create.value).lower() or "read_only" in str(exc_create.value).lower()

    with pytest.raises(Exception) as exc_act:
        await connector.activate_cds("Z_Test", "TR123")
    assert "disabled" in str(exc_act.value).lower() or "read_only" in str(exc_act.value).lower()


# 16. Verified S/4HANA 2023 DEV captured response trace
def test_captured_real_sap_dev_checkrun_trace():
    """Verified against real Eclipse ADT trace from S/4HANA 2023 DEV system.

    Trace facts:
    - POST /sap/bc/adt/checkruns?reporters=abapCheckRun
    - HTTP 200 OK
    - Content-Type: application/vnd.sap.adt.checkmessages+xml; charset=utf-8
    - Root: checkRunReports
    - Reporter: abapCheckRun
    - Check report status: processed
    - Triggering URI: /sap/bc/adt/ddic/ddl/sources/i_salesorder
    - Diagnostic type: E -> SAPValidationStatus.ERROR
    - Message ID: SDDL_PARSER_MSG
    - Short text: Unexpected word ...
    - Position: #start=14,2
    """
    real_sap_response_xml = """<?xml version="1.0" encoding="utf-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun" xmlns:adtcore="http://www.sap.com/adt/core">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:status="processed" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/i_salesorder">
    <chkrun:checkMessage
      chkrun:uri="/sap/bc/adt/ddic/ddl/sources/i_salesorder#start=14,2"
      chkrun:type="E"
      chkrun:shortText="Unexpected word 'DEFINE'"
      chkrun:msgid="SDDL_PARSER_MSG" />
  </chkrun:checkReport>
</chkrun:checkRunReports>"""

    res = SAPADTClient._parse_checkrun_xml(
        real_sap_response_xml,
        http_status=200,
        content_type="application/vnd.sap.adt.checkmessages+xml; charset=utf-8",
    )

    # Verify status mapping: diagnostic type E -> ERROR
    assert res.status == SAPValidationStatus.ERROR
    assert res.reporter == "abapCheckRun"
    assert res.check_report_status == "processed"
    assert res.triggering_uri == "/sap/bc/adt/ddic/ddl/sources/i_salesorder"
    assert res.http_status == 200
    assert "application/vnd.sap.adt.checkmessages+xml" in (res.content_type or "")

    # Verify message attributes preserved
    assert len(res.messages) == 1
    msg = res.messages[0]
    assert msg.severity == "E"
    assert msg.msgid == "SDDL_PARSER_MSG"
    assert msg.short_text.startswith("Unexpected word")
    assert "Unexpected word 'DEFINE'" == msg.short_text
    assert msg.uri == "/sap/bc/adt/ddic/ddl/sources/i_salesorder#start=14,2"
    assert msg.line == 14
    assert msg.column == 2


# 17. Captured real SAP trace integration through Connector & ValidationAgent
@pytest.mark.asyncio
async def test_captured_real_sap_trace_connector_and_validation_agent():
    settings = get_mock_settings()
    real_sap_response_xml = """<?xml version="1.0" encoding="utf-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun" xmlns:adtcore="http://www.sap.com/adt/core">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:status="processed" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/i_salesorder">
    <chkrun:checkMessage
      chkrun:uri="/sap/bc/adt/ddic/ddl/sources/i_salesorder#start=14,2"
      chkrun:type="E"
      chkrun:shortText="Unexpected word 'DEFINE'"
      chkrun:msgid="SDDL_PARSER_MSG" />
  </chkrun:checkReport>
</chkrun:checkRunReports>"""

    def handler(request: httpx.Request):
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "TRACE_CSRF_TOKEN"})
        assert request.method == "POST"
        assert request.url.path == "/sap/bc/adt/checkruns"
        assert request.url.query.decode("utf-8") == "reporters=abapCheckRun"
        assert request.headers["Content-Type"] == "application/vnd.sap.adt.checkobjects+xml"
        assert request.headers.get("X-CSRF-Token") == "TRACE_CSRF_TOKEN"
        return httpx.Response(
            200,
            text=real_sap_response_xml,
            headers={"Content-Type": "application/vnd.sap.adt.checkmessages+xml; charset=utf-8"},
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    connector = SAPADTConnector(settings=settings)
    connector.client = SAPADTClient(settings=settings, client=mock_client)

    # Validate against existing repository object
    val_res = await connector.validate_cds(
        view_definition="SELECT * FROM I_SalesOrder;",
        repository_uri="/sap/bc/adt/ddic/ddl/sources/i_salesorder",
    )

    assert val_res.is_valid is False
    assert val_res.sap_validation_status == SAPValidationStatus.ERROR
    assert len(val_res.syntax_errors) == 1
    assert "Unexpected word 'DEFINE'" in val_res.syntax_errors[0]
    assert "Line 14" in val_res.syntax_errors[0]
    assert val_res.sap_checkrun_result is not None
    assert val_res.sap_checkrun_result.check_report_status == "processed"
    assert val_res.sap_checkrun_result.messages[0].msgid == "SDDL_PARSER_MSG"


# 18. Guarantee that unpersisted drafts remain UNAVAILABLE and never claim SAP compilation
@pytest.mark.asyncio
async def test_unpersisted_drafts_guaranteed_unavailable_no_network():
    settings = get_mock_settings()
    network_called = False

    def handler(request: httpx.Request):
        nonlocal network_called
        network_called = True
        return httpx.Response(500, text="Should never be called")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    connector = SAPADTConnector(settings=settings)
    connector.client = SAPADTClient(settings=settings, client=mock_client)

    # In-memory unpersisted draft without repository_uri
    val_res = await connector.validate_cds(
        view_definition="define view entity ZC_Test as select from I_SalesOrder { SalesOrder };",
        repository_uri=None,
    )

    assert network_called is False
    assert val_res.sap_validation_status == SAPValidationStatus.UNAVAILABLE
    assert "Unpersisted Draft" in (val_res.sap_checkrun_reason or "")


# 19. CSRF token fetch negotiation and caching
@pytest.mark.asyncio
async def test_csrf_token_fetch_and_extraction():
    settings = get_mock_settings()
    captured_get = None

    def handler(request: httpx.Request):
        nonlocal captured_get
        captured_get = request
        return httpx.Response(
            200,
            headers={"x-csrf-token": "FETCHED_TOKEN_XYZ_123"},
            text="<?xml version=\"1.0\" encoding=\"utf-8\"?><adtcore:objectReferences xmlns:adtcore=\"http://www.sap.com/adt/core\"/>",
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)

    token = await adt_client.fetch_csrf_token()

    assert token == "FETCHED_TOKEN_XYZ_123"
    assert adt_client._csrf_token == "FETCHED_TOKEN_XYZ_123"
    assert captured_get is not None
    assert captured_get.method == "GET"
    assert captured_get.url.path == "/sap/bc/adt/repository/informationsystem/search"
    assert captured_get.headers["X-CSRF-Token"] == "Fetch"


# 20. Cookie preservation between CSRF GET and checkrun POST
@pytest.mark.asyncio
async def test_csrf_cookie_preservation():
    settings = get_mock_settings()
    session_cookies_seen_on_post = []

    def handler(request: httpx.Request):
        if request.method == "GET":
            resp = httpx.Response(200, headers={"x-csrf-token": "COOKIE_TEST_TOKEN"})
            resp.headers["Set-Cookie"] = "SAP_SESSIONID_S3X_100=session_val_abc; path=/"
            return resp
        elif request.method == "POST":
            # Inspect cookie header sent by client on subsequent POST
            cookie_hdr = request.headers.get("Cookie", "")
            session_cookies_seen_on_post.append(cookie_hdr)
            return httpx.Response(
                200,
                text="""<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/i_salesorder" chkrun:status="processed" />
</chkrun:checkRunReports>""",
                headers={"Content-Type": "application/vnd.sap.adt.checkmessages+xml; charset=utf-8"},
            )
        return httpx.Response(400)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)

    result = await adt_client.run_checkrun("/sap/bc/adt/ddic/ddl/sources/i_salesorder")

    assert result.status == SAPValidationStatus.PASS
    assert len(session_cookies_seen_on_post) == 1
    assert "SAP_SESSIONID_S3X_100=session_val_abc" in session_cookies_seen_on_post[0]


# 21. Checkrun 403 CSRF token required triggers refresh and succeeds on retry
@pytest.mark.asyncio
async def test_checkrun_403_csrf_refresh_and_retry_once():
    settings = get_mock_settings()
    call_count = 0

    def handler(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        if request.method == "GET":
            # Token fetch endpoint
            token_val = f"FRESH_TOKEN_{call_count}"
            return httpx.Response(200, headers={"x-csrf-token": token_val})
        elif request.method == "POST":
            # First POST fails with CSRF Required; second POST succeeds
            if call_count <= 2:
                return httpx.Response(
                    403,
                    headers={"x-csrf-token": "Required"},
                    text="CSRF token validation failed",
                )
            else:
                return httpx.Response(
                    200,
                    text="""<?xml version="1.0" encoding="UTF-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport chkrun:reporter="abapCheckRun" chkrun:triggeringuri="/sap/bc/adt/ddic/ddl/sources/i_salesorder" chkrun:status="processed" />
</chkrun:checkRunReports>""",
                    headers={"Content-Type": "application/vnd.sap.adt.checkmessages+xml; charset=utf-8"},
                )
        return httpx.Response(400)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)

    result = await adt_client.run_checkrun("/sap/bc/adt/ddic/ddl/sources/i_salesorder")

    # Call sequence: 1. GET (initial fetch) -> 2. POST (403 required) -> 3. GET (refresh) -> 4. POST (200 OK)
    assert result.status == SAPValidationStatus.PASS
    assert call_count == 4


# 22. Checkrun 403 fails cleanly after exactly one retry (no infinite loop)
@pytest.mark.asyncio
async def test_checkrun_403_csrf_refresh_fails_after_one_retry():
    settings = get_mock_settings()
    post_count = 0

    def handler(request: httpx.Request):
        nonlocal post_count
        if request.method == "GET":
            return httpx.Response(200, headers={"x-csrf-token": "STILL_INVALID_TOKEN"})
        elif request.method == "POST":
            post_count += 1
            return httpx.Response(
                403,
                headers={"x-csrf-token": "Required"},
                text="CSRF token validation failed",
            )
        return httpx.Response(400)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=settings.SAP_BASE_URL)
    adt_client = SAPADTClient(settings=settings, client=mock_client)

    result = await adt_client.run_checkrun("/sap/bc/adt/ddic/ddl/sources/i_salesorder")

    # Exactly 2 POST attempts (initial + 1 retry)
    assert post_count == 2
    assert result.status == SAPValidationStatus.UNAVAILABLE
    assert result.http_status == 403


# 23. Client session cleanup with aclose
@pytest.mark.asyncio
async def test_client_session_cleanup_aclose():
    settings = get_mock_settings()
    adt_client = SAPADTClient(settings=settings)
    adt_client._csrf_token = "SOME_CACHED_TOKEN"

    # Simulate active session
    fake_session = httpx.AsyncClient()
    adt_client._session = fake_session
    assert not fake_session.is_closed

    await adt_client.aclose()

    assert fake_session.is_closed
    assert adt_client._session is None
    assert adt_client._csrf_token is None


# 24. Zero-write security policy blocks unauthorized operations unchanged
def test_zero_write_policy_remains_strictly_enforced():
    from src.core.exceptions import SAPSecurityError

    settings = get_mock_settings()
    adt_client = SAPADTClient(settings=settings)

    # 1. Modifying methods unconditionally blocked
    for verb in ("PUT", "DELETE", "PATCH"):
        with pytest.raises(SAPSecurityError):
            adt_client.assert_zero_write_policy(verb, "/sap/bc/adt/checkruns")

    # 2. Arbitrary POST blocked
    with pytest.raises(SAPSecurityError):
        adt_client.assert_zero_write_policy("POST", "/sap/bc/adt/ddic/ddl/sources")

    with pytest.raises(SAPSecurityError):
        adt_client.assert_zero_write_policy("POST", "/sap/bc/adt/discovery")

    # 3. Only verified checkrun POST allowed
    adt_client.assert_zero_write_policy("POST", "/sap/bc/adt/checkruns", {"reporters": "abapCheckRun"})


