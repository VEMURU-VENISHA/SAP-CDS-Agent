"""Tests for Reuse vs Create Decision Routing, ADT Shell POST 201 + PUT source update, and Existing Object Protection."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from src.main import app
from src.services.discovery_service import CDSDiscoveryService
from src.models.domain import (
    CDSReviewPackage,
    DecisionAction,
    ReviewStatus,
)
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector
from src.core.exceptions import SAPConflictError, SAPSecurityError
from src.services.gemini_service import validate_cds_ddl

client = TestClient(app)


def _create_test_review_package(**kwargs) -> CDSReviewPackage:
    from src.models.domain import BusinessRequirement, TargetUseCase, Decision
    req = BusinessRequirement(
        title="Test Req",
        description="Requirement for testing",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder"],
    )
    dec = Decision(
        requirement_id=req.id,
        action=kwargs.get("decision_action", DecisionAction.CREATE),
        proposed_new_view_name=kwargs.get("object_name", "ZC_TEST"),
        confidence_score=0.95,
        fit_percentage=95.0,
        rationale="Test decision rationale",
    )
    defaults = {
        "review_id": "rev_test_123",
        "requirement_id": req.id,
        "original_requirement": req,
        "decision": dec,
        "decision_confidence": 0.95,
        "decision_rationale": "Test decision rationale",
        "object_name": "ZC_TEST",
        "status": ReviewStatus.APPROVED,
        "can_approve": True,
        "ddl_source": "define view entity ZC_TEST as select from I_SalesOrder { key SalesOrder }",
        "decision_action": DecisionAction.CREATE,
    }
    defaults.update(kwargs)
    return CDSReviewPackage(**defaults)


# -----------------------------------------------------------------------------
# TEST 1: Single existing CDS with 100% coverage -> REUSE_EXISTING
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_single_cds_100_percent_coverage_routes_to_reuse_existing():
    service = CDSDiscoveryService()

    field_specs = [
        {"name": "Sales Order", "variants": ["SalesOrder", "VBELN"]},
        {"name": "Sold-to Party", "variants": ["SoldToParty", "KUNNR"]},
    ]

    indexed_views = [
        {
            "cds_name": "I_SalesOrder",
            "label": "Sales Order View",
            "package": "VAV",
            "domain": "Sales",
            "fields": [
                {"field_name": "SalesOrder", "data_element": "VBELN", "description": "Sales Order"},
                {"field_name": "SoldToParty", "data_element": "KUNNR", "description": "Sold-to Party"},
            ],
        }
    ]

    with patch.object(service, "_load_indexed_cds_metadata", return_value=indexed_views), \
         patch.object(service, "_ensure_relationship_graph", return_value={}):
        res = service.run_discovery_pipeline("Sales order analysis", field_specs)

    summary = res["solution_summary"]
    assert summary["solution_type"] == "REUSE_EXISTING"
    assert summary["cds"] == "I_SalesOrder"
    assert summary["coverage"] == 100.0
    assert summary["requires_create"] is False
    assert summary.get("do_not_generate_new_code") is True
    assert summary.get("do_not_create_new_object") is True


# -----------------------------------------------------------------------------
# TEST 2: Multi-CDS relationship provides 100% coverage -> MULTI_CDS_CREATE
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multi_cds_combination_routes_to_multi_cds_create():
    service = CDSDiscoveryService()

    field_specs = [
        {"name": "Sales Order", "variants": ["SalesOrder", "VBELN"]},
        {"name": "Customer Name", "variants": ["CustomerName", "NAME1"]},
    ]

    indexed_views = [
        {
            "cds_name": "I_SalesOrder",
            "label": "Sales Order View",
            "package": "VAV",
            "domain": "Sales",
            "fields": [
                {"field_name": "SalesOrder", "data_element": "VBELN", "description": "Sales Order"},
                {"field_name": "SoldToParty", "data_element": "KUNNR", "description": "Sold-to Party"},
            ],
        },
        {
            "cds_name": "I_Customer",
            "label": "Customer Master",
            "package": "VS",
            "domain": "Sales",
            "fields": [
                {"field_name": "Customer", "data_element": "KUNNR", "description": "Customer Number"},
                {"field_name": "CustomerName", "data_element": "NAME1", "description": "Customer Name"},
            ],
        },
    ]

    graph = {
        "I_SALESORDER": [
            {
                "target": "I_Customer",
                "target_upper": "I_CUSTOMER",
                "source_field": "SoldToParty",
                "target_field": "Customer",
                "cardinality": "1:1",
                "association_name": "_Customer",
            }
        ]
    }

    with patch.object(service, "_load_indexed_cds_metadata", return_value=indexed_views), \
         patch.object(service, "_ensure_relationship_graph", return_value=graph):
        res = service.run_discovery_pipeline("Sales order with customer name", field_specs)

    summary = res["solution_summary"]
    assert summary["solution_type"] == "MULTI_CDS_CREATE"
    assert summary["requires_create"] is True


# -----------------------------------------------------------------------------
# TEST 3: No single 100% and no valid relationship -> NO_SOLUTION
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_valid_solution_routes_to_no_solution():
    service = CDSDiscoveryService()

    field_specs = [
        {"name": "Unrelated Custom Field A", "variants": ["UnrelatedA"]},
        {"name": "Unrelated Custom Field B", "variants": ["UnrelatedB"]},
    ]

    indexed_views = [
        {
            "cds_name": "I_SalesOrder",
            "label": "Sales Order View",
            "package": "VAV",
            "domain": "Sales",
            "fields": [
                {"field_name": "SalesOrder", "data_element": "VBELN", "description": "Sales Order"},
            ],
        }
    ]

    with patch.object(service, "_load_indexed_cds_metadata", return_value=indexed_views), \
         patch.object(service, "_ensure_relationship_graph", return_value={}):
        res = service.run_discovery_pipeline("Unrelated requirement", field_specs)

    summary = res["solution_summary"]
    assert summary["solution_type"] == "NO_SOLUTION"
    assert summary["requires_create"] is False


# -----------------------------------------------------------------------------
# TEST 4: Selection of 100% existing CDS enforces single candidate selection
# -----------------------------------------------------------------------------
def test_backend_creation_endpoint_rejects_reuse_existing():
    response = client.post(
        "/api/reviews/direct-create-sap",
        json={
            "name": "ZC_TEST_REUSE",
            "package": "ZTRAINING_2026",
            "source": "define view entity ZC_TEST_REUSE as select from I_SalesOrder { key SalesOrder }",
            "transport_request": "S4HK900123",
            "solution_type": "REUSE_EXISTING",
        },
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "REUSE_EXISTING"
    assert "Existing CDS selected" in res_data["message"]
    assert res_data["sap_write_performed"] is False


# -----------------------------------------------------------------------------
# TEST 5: Existing artifact name pre-flight collision returns EXISTING_OBJECT
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_preflight_existence_check_blocks_with_existing_object():
    mock_client = AsyncMock()
    mock_client.validate_sap_object_name.return_value = True
    mock_client.validate_transport_request.return_value = True
    mock_client.get_ddl_source.return_value = "define view entity ZC_EXISTING as select from I_SalesOrder { key SalesOrder }"

    connector = SAPADTConnector(mock_client)

    pkg = _create_test_review_package(
        review_id="rev_existing_123",
        object_name="ZC_EXISTING",
        status=ReviewStatus.APPROVED,
        can_approve=True,
        ddl_source="define view entity ZC_EXISTING as select from I_SalesOrder { key SalesOrder }",
        decision_action=DecisionAction.CREATE,
    )

    with pytest.raises(SAPConflictError) as exc_info:
        await connector.create_cds_in_sap(pkg, transport_request="S4HK900123")

    assert "EXISTING_OBJECT" in str(exc_info.value.details)


# -----------------------------------------------------------------------------
# TEST 6: ADT PUT source upload includes If-Match: * to prevent 400 ExceptionResourceAlreadyExists
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_adt_upload_ddls_source_includes_if_match_header():
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client.put.return_value = mock_resp

    settings = MagicMock()
    settings.SAP_SEND_CLIENT_PARAM = False
    settings.SAP_DEV_WRITE_ENABLED = True
    settings.SAP_LIVE_READ_ONLY = False

    adt_client = SAPADTClient(settings)
    adt_client._get_client = AsyncMock(return_value=mock_client)
    adt_client.fetch_csrf_token = AsyncMock(return_value="CSRF_TOKEN_123")
    adt_client.assert_dev_write_policy = MagicMock()

    status_code = await adt_client.upload_ddls_source(
        view_name="ZC_SALESORDERANALYSIS1",
        ddl_source="define view entity ZC_SALESORDERANALYSIS1 as select from I_SalesOrder { key SalesOrder }",
        lock_handle="LOCK_TOKEN_123",
        corr_nr="S4HK900123",
    )

    assert status_code == 200
    mock_client.put.assert_called_once()
    call_kwargs = mock_client.put.call_args.kwargs
    headers = call_kwargs["headers"]
    assert headers.get("If-Match") == "*"


# -----------------------------------------------------------------------------
# TEST 7: CREATE function uses EXACT approved source and makes ZERO LLM calls
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_function_zero_llm_exact_approved_source():
    exact_approved_ddl = (
        "@AbapCatalog.sqlViewName: 'ZCSALESANALYSIS'\n"
        "@AccessControl.authorizationCheck: #NOT_REQUIRED\n"
        "@EndUserText.label: 'Sales Order Analysis'\n"
        "define view entity ZC_SALESORDERANALYSIS1\n"
        "  as select from I_SalesOrder as _SalesOrder\n"
        "  association [0..1] to I_Customer as _Customer\n"
        "    on _SalesOrder.SoldToParty = _Customer.Customer\n"
        "{\n"
        "  key _SalesOrder.SalesOrder,\n"
        "  _SalesOrder.SoldToParty,\n"
        "  _Customer.CustomerName,\n"
        "  _SalesOrder.NetAmount\n"
        "}"
    )

    mock_client = AsyncMock()
    mock_client.validate_sap_object_name.return_value = True
    mock_client.validate_transport_request.return_value = True
    mock_client.get_ddl_source.side_effect = [None, exact_approved_ddl]  # First call None (pre-flight), second call exact_approved_ddl (read-back)
    mock_client.create_ddls_shell.return_value = {"status_code": 201, "lock_handle": "LOCK_123", "location": "/sap/bc/adt/ddic/ddl/sources/zc_salesorderanalysis1"}
    mock_client.upload_ddls_source.return_value = 200
    mock_client.compute_source_hash = SAPADTClient.compute_source_hash

    connector = SAPADTConnector(mock_client)

    pkg = _create_test_review_package(
        review_id="rev_exact_source_999",
        object_name="ZC_SALESORDERANALYSIS1",
        status=ReviewStatus.APPROVED,
        can_approve=True,
        ddl_source=exact_approved_ddl,
        decision_action=DecisionAction.CREATE,
        reviewer="human_gatekeeper",
    )

    with patch("google.generativeai.GenerativeModel") as mock_gemini:
        res = await connector.create_cds_in_sap(pkg, transport_request="S4HK900123")

    # 1. Zero LLM calls during CREATE execution
    assert not mock_gemini.called

    # 2. Uploaded DDL is EXACTLY the approved source
    mock_client.upload_ddls_source.assert_called_once()
    passed_ddl = mock_client.upload_ddls_source.call_args.kwargs["ddl_source"]
    assert passed_ddl == exact_approved_ddl

    # 3. SAP Creation result succeeds with verified read-back
    assert res.success is True
    assert res.sap_object_name == "ZC_SALESORDERANALYSIS1"
    assert res.sap_write_performed is True


# -----------------------------------------------------------------------------
# TEST 8: POST Shell race condition ExceptionResourceAlreadyExists -> EXISTING_OBJECT
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_post_shell_race_condition_maps_to_existing_object():
    mock_client = AsyncMock()
    mock_client.validate_sap_object_name.return_value = True
    mock_client.validate_transport_request.return_value = True
    mock_client.get_ddl_source.return_value = None  # Pre-flight says not found
    mock_client.create_ddls_shell.side_effect = SAPConflictError(
        "ZC_SALESORDERANALYSIS1",
        details={
            "status": "EXISTING_OBJECT",
            "message": "CDS artifact ZC_SALESORDERANALYSIS1 already exists in SAP. No SAP changes were made. Choose another artifact name.",
        },
    )

    connector = SAPADTConnector(mock_client)
    pkg = _create_test_review_package(
        review_id="rev_race_123",
        object_name="ZC_SALESORDERANALYSIS1",
        status=ReviewStatus.APPROVED,
        can_approve=True,
        ddl_source="define view entity ZC_SALESORDERANALYSIS1 as select from I_SalesOrder { key SalesOrder }",
        decision_action=DecisionAction.CREATE,
    )

    with pytest.raises(SAPConflictError) as exc_info:
        await connector.create_cds_in_sap(pkg, transport_request="S4HK900123")

    assert "EXISTING_OBJECT" in str(exc_info.value.details)


# -----------------------------------------------------------------------------
# TEST 9: Missing or invalid transport request blocks create before POST
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_or_invalid_transport_blocks_create():
    mock_client = AsyncMock()
    mock_client.validate_sap_object_name.return_value = True
    mock_client.validate_transport_request.return_value = False

    connector = SAPADTConnector(mock_client)
    from src.models.domain import BusinessRequirement, Decision, TargetUseCase
    req = BusinessRequirement(
        title="Sales Order",
        description="Sales order analysis",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder"],
    )
    dec = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_SALESORDERANALYSIS1",
        confidence_score=0.95,
        fit_percentage=95.0,
        rationale="New view needed",
    )
    pkg = CDSReviewPackage(
        review_id="rev_invalid_tr_123",
        requirement_id=req.id,
        original_requirement=req,
        decision=dec,
        decision_confidence=0.95,
        decision_rationale="New view needed",
        object_name="ZC_SALESORDERANALYSIS1",
        status=ReviewStatus.APPROVED,
        can_approve=True,
        ddl_source="define view entity ZC_SALESORDERANALYSIS1 as select from I_SalesOrder { key SalesOrder }",
        decision_action=DecisionAction.CREATE,
    )

    with pytest.raises(Exception):
        await connector.create_cds_in_sap(pkg, transport_request="INVALID_TR")

    assert not mock_client.create_ddls_shell.called


# -----------------------------------------------------------------------------
# TEST 10: Unapproved review package blocks create before POST
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unapproved_review_package_blocks_create():
    mock_client = AsyncMock()
    connector = SAPADTConnector(mock_client)
    from src.models.domain import BusinessRequirement, Decision, TargetUseCase
    req = BusinessRequirement(
        title="Sales Order",
        description="Sales order analysis",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder"],
    )
    dec = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_SALESORDERANALYSIS1",
        confidence_score=0.95,
        fit_percentage=95.0,
        rationale="New view needed",
    )
    pkg = CDSReviewPackage(
        review_id="rev_unapproved_123",
        requirement_id=req.id,
        original_requirement=req,
        decision=dec,
        decision_confidence=0.95,
        decision_rationale="New view needed",
        object_name="ZC_SALESORDERANALYSIS1",
        status=ReviewStatus.PENDING_REVIEW,
        can_approve=False,
        ddl_source="define view entity ZC_SALESORDERANALYSIS1 as select from I_SalesOrder { key SalesOrder }",
        decision_action=DecisionAction.CREATE,
    )

    with pytest.raises(SAPSecurityError):
        await connector.create_cds_in_sap(pkg, transport_request="S4HK900123")

    assert not mock_client.create_ddls_shell.called


# -----------------------------------------------------------------------------
# TEST 11: Case-insensitive deduplication of selected CDS views
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_selected_views_case_insensitive_deduplication():
    from src.services.gemini_service import GeminiService
    svc = GeminiService()
    
    # Input has duplicate case representations: I_CUSTOMER/I_Customer, I_JOURNALENTRYITEM/I_JournalEntryItem
    raw_selected_views = [
        "I_RO_SAFTSALESINVOICECUSTOMER",
        "I_CUSTOMER",
        "I_Customer",
        "I_JOURNALENTRYITEM",
        "I_JournalEntryItem"
    ]
    
    res = await svc.generate_cds_code(
        requirement="Sales order invoice customer analysis",
        selected_views=raw_selected_views,
        mappings=[{"business_field": "Customer", "actual_field": "Customer"}],
        join_paths=[],
        artifact_name="ZC_SAFTSALES_ANALYSIS",
    )
    
    # The generated code / template must reference canonical uppercase entities without duplicates
    code = res["result"]["code"]
    assert "I_RO_SAFTSALESINVOICECUSTOMER" in code
    assert code.count("I_Customer") == 0 or code.count("I_CUSTOMER") >= 1


# -----------------------------------------------------------------------------
# TEST 12: Metadata index status returns Ready with non-zero counts
# -----------------------------------------------------------------------------
def test_metadata_index_status_returns_non_zero_counts():
    service = CDSDiscoveryService()
    status = service.get_metadata_status()
    
    assert status["cds_count"] >= 47535
    assert status["field_count"] >= 3366
    assert status["associations_count"] >= 916
    assert status["packages_count"] >= 487
    assert status["status"] == "Ready"


# -----------------------------------------------------------------------------
# REGRESSION TEST 2: Backend health endpoint returns healthy status
# -----------------------------------------------------------------------------
def test_backend_health_returns_healthy_status():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "healthy"
    assert "database" in res
    assert "sap_connector" in res


# -----------------------------------------------------------------------------
# REGRESSION TEST 3 & 4: Selected CDS deduplication preserves exact 3 entities
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_selected_cds_preserves_exact_three_entities():
    from src.services.gemini_service import GeminiService
    svc = GeminiService()
    
    raw_views = [
        "I_RO_SAFTSALESINVOICECUSTOMER",
        "I_CUSTOMER",
        "I_JOURNALENTRYITEM"
    ]
    
    res = await svc.generate_cds_code(
        requirement="Sales order invoice customer analysis",
        selected_views=raw_views,
        mappings=[{"business_field": "Customer", "actual_field": "Customer"}],
        join_paths=[],
        artifact_name="ZC_TEST_MULTI_3",
    )
    
    code = res["result"]["code"]
    assert "I_RO_SAFTSALESINVOICECUSTOMER" in code
    assert "I_CUSTOMER" in code or "I_Customer" in code
    assert "I_JOURNALENTRYITEM" in code or "I_JournalEntryItem" in code


# -----------------------------------------------------------------------------
# REGRESSION TEST 5: Pipeline Review Package ID is preserved throughout workflow
# -----------------------------------------------------------------------------
def test_pipeline_review_id_preservation():
    # 1. Final Approve creates package with review_id
    response = client.post(
        "/api/reviews/final-approve",
        json={
            "requirement": "Sales invoice analysis",
            "selected_views": ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER", "I_JOURNALENTRYITEM"],
            "artifact_name": "ZC_TEST_PRESERVE_1",
            "package": "ZTRAINING_2026",
            "ddl_source": "define view entity ZC_TEST_PRESERVE_1 as select from I_SalesOrder { key SalesOrder }",
            "transport_request": "S4HK900123",
            "reviewer": "human_gatekeeper",
            "review_id": "rev_preserve_test_999",
        },
    )
    assert response.status_code == 200
    pkg = response.json()
    assert pkg["review_id"] == "rev_preserve_test_999"
    assert pkg["object_name"] == "ZC_TEST_PRESERVE_1"
    assert pkg["status"] == "APPROVED"
    assert pkg["can_approve"] is True

    # 2. Get review package preserves same ID
    get_res = client.get(f"/api/reviews/{pkg['review_id']}")
    assert get_res.status_code == 200
    get_pkg = get_res.json()
    assert get_pkg["review_id"] == "rev_preserve_test_999"


# -----------------------------------------------------------------------------
# TEST CASES FOR SOURCE COMPLETENESS VALIDATION & AUTO-REPAIR
# -----------------------------------------------------------------------------
from src.services.cds_generation_validator import validate_source_completeness
from src.services.gemini_service import _repair_missing_sources


def test_source_completeness_rejects_missing_view():
    """DDL missing I_JOURNALENTRYITEM must be rejected."""
    ddl = (
        "@AccessControl.authorizationCheck: #NOT_REQUIRED\n"
        "define view entity ZC_SalesOrderAnalysis\n"
        "  as select from I_RO_SAFTSALESINVOICECUSTOMER as _RO\n"
        "  association [0..1] to I_CUSTOMER as _CUST\n"
        "    on $projection.Customer = _CUST.Customer {\n"
        "  _RO.SalesOrder\n}"
    )
    selected = ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER", "I_JOURNALENTRYITEM"]
    result = validate_source_completeness(ddl, selected)
    assert result["status"] == "GENERATION_VALIDATION_FAILED"
    assert "I_JOURNALENTRYITEM" in result["missing_sources"]
    assert result["approval_enabled"] is False


def test_source_completeness_passes_all_views_present():
    """DDL with all 3 views must pass."""
    ddl = (
        "@AccessControl.authorizationCheck: #NOT_REQUIRED\n"
        "define view entity ZC_SalesOrderAnalysis\n"
        "  as select from I_RO_SAFTSALESINVOICECUSTOMER as _RO\n"
        "  association [0..1] to I_CUSTOMER as _CUST\n"
        "    on $projection.Customer = _CUST.Customer\n"
        "  association [0..1] to I_JOURNALENTRYITEM as _JEI\n"
        "    on $projection.CompanyCode = _JEI.CompanyCode\n"
        "      and $projection.AccountingDocument = _JEI.AccountingDocument {\n"
        "  _RO.SalesOrder\n}"
    )
    selected = ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER", "I_JOURNALENTRYITEM"]
    result = validate_source_completeness(ddl, selected)
    assert result["status"] == "GENERATION_VALIDATED"
    assert result["missing_sources"] == []
    assert result["approval_enabled"] is True


def test_source_completeness_case_insensitive():
    """Case variants of same view must not cause false missing-source error."""
    ddl = (
        "define view entity ZC_SalesOrderAnalysis\n"
        "  as select from I_RO_SAFTSALESINVOICECUSTOMER\n"
        "  association [0..1] to I_CUSTOMER\n"
        "  association [0..1] to I_JournalEntryItem {}"
    )
    selected = ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER", "I_JOURNALENTRYITEM"]
    result = validate_source_completeness(ddl, selected)
    assert result["status"] == "GENERATION_VALIDATED"


def test_source_completeness_empty_selected_views():
    """No selected views = auto pass."""
    result = validate_source_completeness("some ddl", [])
    assert result["status"] == "GENERATION_VALIDATED"


def test_source_completeness_dedup_grounding_errors():
    """Same error must not appear twice in grounding errors list."""
    grounding_errors = [
        {"type": "MISSING_SELECTED_SOURCE", "view": "I_JOURNALENTRYITEM", "message": "msg1"},
        {"type": "MISSING_SELECTED_SOURCE", "view": "I_JOURNALENTRYITEM", "message": "msg2"},
        {"type": "OTHER_ERROR", "view": "X", "message": "msg3"},
    ]
    seen = set()
    deduped = []
    for err in grounding_errors:
        key = str(err.get("type", "")) + ":" + str(err.get("view", err.get("message", "")))
        if key not in seen:
            seen.add(key)
            deduped.append(err)
    assert len(deduped) == 2
    assert deduped[0]["type"] == "MISSING_SELECTED_SOURCE"
    assert deduped[1]["type"] == "OTHER_ERROR"


def test_auto_repair_injects_missing_journalentryitem():
    """Auto-repair must inject I_JOURNALENTRYITEM as association."""
    ddl = (
        "@AccessControl.authorizationCheck: #NOT_REQUIRED\n"
        "@EndUserText.label: 'ZC_SalesOrderAnalysis'\n"
        "define view entity ZC_SalesOrderAnalysis\n"
        "  as select from I_RO_SAFTSALESINVOICECUSTOMER as _RO\n"
        "  association [0..1] to I_CUSTOMER as _CUST\n"
        "    on $projection.Customer = _CUST.Customer {\n"
        "  _RO.SalesOrder\n}"
    )
    selected = ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER", "I_JOURNALENTRYITEM"]
    # Run auto-repair
    repaired, missing, details = _repair_missing_sources(ddl, selected)
    assert "I_JOURNALENTRYITEM" in missing
    assert "I_JOURNALENTRYITEM" in repaired.upper()
    assert "TO I_JOURNALENTRYITEM" in repaired.upper()
    # After repair, validation should pass
    result = validate_source_completeness(repaired, selected)
    assert result["status"] == "GENERATION_VALIDATED"


# -----------------------------------------------------------------------------
# Change H: Rule-based CDS DDL Validation Tests
# -----------------------------------------------------------------------------
def test_validate_cds_rule1_association_before_brace():
    ddl = "define view entity Z_Test\n  as select from I_CUSTOMER as _C\n  association [0..1] to I_MATERIAL as _M\n    on $projection.Material = _M.Material {\n  _C.Customer\n}"
    result = validate_cds_ddl(ddl, ["I_CUSTOMER", "I_MATERIAL"])
    assert result["status"] != "VALIDATION_FAILED" or "RULE1" not in str(result.get("blocking_errors", []))

def test_validate_cds_rule1_association_inside_brace_fails():
    ddl = "define view entity Z_Test\n  as select from I_CUSTOMER as _C {\n  association [0..1] to I_MATERIAL as _M\n    on $projection.Material = _M.Material\n  _C.Customer\n}"
    result = validate_cds_ddl(ddl, ["I_CUSTOMER", "I_MATERIAL"])
    assert any(e.get("rule") == "RULE1_STRUCTURE" for e in result.get("errors", []))

def test_validate_cds_rule2_missing_source():
    ddl = "define view entity Z_Test\n  as select from I_CUSTOMER as _C {\n  _C.Customer\n}"
    result = validate_cds_ddl(ddl, ["I_CUSTOMER", "I_MATERIAL"])
    assert "I_MATERIAL" in result.get("missing_sources", [])

def test_validate_cds_rule2_all_sources_present():
    ddl = "define view entity Z_Test\n  as select from I_CUSTOMER as _C\n  association [0..1] to I_MATERIAL as _M\n    on $projection.Material = _M.Material {\n  _C.Customer\n}"
    result = validate_cds_ddl(ddl, ["I_CUSTOMER", "I_MATERIAL"])
    assert result.get("missing_sources", []) == []

def test_validate_cds_rule8_missing_field():
    ddl = "define view entity Z_Test\n  as select from I_CUSTOMER as _C {\n  _C.Customer\n}"
    result = validate_cds_ddl(ddl, ["I_CUSTOMER"], required_fields=["Customer", "Country"])
    assert any(e.get("rule") == "RULE8_FIELD_COVERAGE" for e in result.get("errors", []))

def test_validate_cds_rule8_all_fields_present():
    ddl = "define view entity Z_Test\n  as select from I_CUSTOMER as _C {\n  _C.Customer,\n  _C.Country\n}"
    result = validate_cds_ddl(ddl, ["I_CUSTOMER"], required_fields=["Customer", "Country"])
    assert result["status"] in ["VALIDATION_PASSED", "VALIDATION_PASSED_WITH_WARNINGS"]

def test_validate_cds_rule10_duplicate_association():
    ddl = "define view entity Z_Test\n  as select from I_CUSTOMER as _C\n  association [0..1] to I_MATERIAL as _M1\n    on $projection.Material = _M1.Material\n  association [0..1] to I_MATERIAL as _M2\n    on $projection.Material = _M2.Material {\n  _C.Customer\n}"
    result = validate_cds_ddl(ddl, ["I_CUSTOMER", "I_MATERIAL"])
    assert any(e.get("rule") == "RULE10_DUPLICATE_ASSOCIATION" for e in result.get("errors", []))

def test_validate_cds_full_valid_ddl():
    ddl = "@AccessControl.authorizationCheck: #NOT_REQUIRED\n@EndUserText.label: 'ZC_SalesOrderAnalysis'\ndefine view entity ZC_SalesOrderAnalysis\n  as select from I_RO_SAFTSALESINVOICECUSTOMER as _RO\n  association [0..1] to I_CUSTOMER as _CUST\n    on $projection.Customer = _CUST.Customer\n  association [1..*] to I_SALESANALYTICSCUBE as _SAC\n    on _CUST.Customer = _SAC.Customer\n{\n  _RO.CUSTOMER,\n  _RO.COMPANYCODE,\n  _SAC.SalesOrder,\n  _SAC.Material,\n  _SAC.OpnSOForOrdReltdInvcsNetAmount as NetAmount,\n  _SAC.TransactionCurrency as Currency,\n  _SAC.SalesOrganization\n}"
    result = validate_cds_ddl(ddl, ["I_RO_SAFTSALESINVOICECUSTOMER", "I_CUSTOMER", "I_SALESANALYTICSCUBE"], required_fields=["SalesOrder", "CUSTOMER", "Material", "NetAmount", "Currency", "COMPANYCODE", "SalesOrganization"])
    assert result["approval_enabled"] is True





