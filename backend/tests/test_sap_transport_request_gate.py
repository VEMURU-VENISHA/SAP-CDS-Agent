"""Milestone 13.2: Human-Supplied Workbench Transport Request Gate Tests.

Validates the local pre-socket validation of CTS Workbench Transport Requests:
1. Valid format accepted (^[A-Z0-9]{3}K[0-9]{6}$)
2. Empty/whitespace/None values rejected
3. Malformed values rejected (incorrect digits, missing 'K', invalid chars)
4. Arbitrary strings rejected
5. Invalid transport request causes ZERO SAP network calls (pre-flight blocked)
6. REUSE does not require transport request and performs zero writes
7. EXTEND strictly requires valid transport request
8. API endpoint returns HTTP 400 for missing/invalid transport request
9. Existing approval, write, and read-only gates remain enforced
"""

from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

from src.config import Settings
from src.core.exceptions import (
    GovernanceApprovalRequiredError,
    SAPNotFoundError,
    SAPSecurityError,
    SAPTransportRequestError,
)
from src.main import app
from src.models.domain import (
    BusinessRequirement,
    CDSWorkflowState,
    CDSCandidate,
    CDSDraft,
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
    TargetUseCase,
    ValidationResult,
)
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector
from src.services.review_service import ReviewStore, build_review_package, get_review_store


def _make_sample_state(
    action: DecisionAction = DecisionAction.CREATE,
    object_name: str = "ZI_CustomOrder",
) -> CDSWorkflowState:
    req = BusinessRequirement(
        title="Custom Sales Analysis",
        description="Custom sales CDS view definition",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=action,
        recommended_view="I_SalesOrder" if action != DecisionAction.CREATE else None,
        proposed_new_view_name=object_name if action == DecisionAction.CREATE else None,
        proposed_extension_name=object_name if action == DecisionAction.EXTEND else None,
        confidence_score=0.95,
        fit_percentage=90.0,
        rationale="Automated test decision.",
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
            ddl_source=f"define view entity {object_name} as select from I_SalesOrder {{ key SalesOrder }};",
            primary_entity="I_SalesOrder",
        )

    val = ValidationResult(
        is_valid=True,
        sap_validation_status=SAPValidationStatus.PASS,
        details=[{"message": "Syntax clean"}],
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "selected_candidate": CDSCandidate(
            view_name="I_SalesOrder",
            package="VBAK_PKG",
            description="Sales Order Root",
            relevance_score=0.9,
            field_count=1,
            association_count=0,
        ),
        "candidates": [],
        "evidence_records": [
            ElementEvidenceRecord(
                element_name="SalesOrder",
                element_type="FIELD",
                evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                evidence_detail="Exact match",
                confidence=1.0,
                is_verified=True,
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


def _make_approved_package(action: DecisionAction = DecisionAction.CREATE, object_name: str = "ZI_CustomOrder") -> CDSReviewPackage:
    state = _make_sample_state(action=action, object_name=object_name)
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved for test")
    return approved


def _make_write_enabled_settings() -> Settings:
    return Settings(
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
        SAP_DEV_PACKAGE="ZTRAINING_2026",
    )


# =========================================================================
# 1. Format Validation Unit Tests
# =========================================================================
@pytest.mark.parametrize(
    "valid_request",
    [
        "S4HK900123",
        "YAWK900001",
        "DEVK900123",
        "D01K999999",
        "NPLK900000",
        "TSTK123456",
        " s4hk900123 ",  # Stripped and normalized to uppercase
        "devk900010\n",
    ],
)
def test_valid_transport_request_accepted(valid_request: str):
    """Validates that CTS Workbench requests matching ^[A-Z0-9]{3}K[0-9]{6}$ are accepted."""
    assert SAPADTClient.validate_transport_request(valid_request) is True


@pytest.mark.parametrize(
    "empty_val",
    [
        None,
        "",
        "   ",
        "\t\n",
    ],
)
def test_empty_transport_request_rejected(empty_val):
    """Empty or whitespace values must be strictly rejected."""
    assert SAPADTClient.validate_transport_request(empty_val) is False


@pytest.mark.parametrize(
    "malformed_val",
    [
        "S4HK90012",     # 5 digits instead of 6 (total 9 chars)
        "S4HK9001234",   # 7 digits instead of 6 (total 11 chars)
        "S4HX900123",    # 'X' instead of 'K'
        "S4H-900123",    # hyphen instead of 'K'
        "S4HK90012A",    # alphanumeric in last 6 chars
        "S4H_K900123",   # extra underscore
        "SHK900123",     # 2 char system ID instead of 3
        "S4HAK900123",   # 4 char system ID instead of 3
        "TRK900001",     # 9 chars total
    ],
)
def test_malformed_transport_request_rejected(malformed_val: str):
    """Malformed values violating the CTS Workbench format must be rejected."""
    assert SAPADTClient.validate_transport_request(malformed_val) is False


@pytest.mark.parametrize(
    "arbitrary_str",
    [
        "random_text",
        "MY_TRANSPORT",
        "SELECT * FROM TADIR",
        "<script>alert(1)</script>",
        "DROP TABLE VBAK",
        "1234567890",
        "CORR_NR_12345",
    ],
)
def test_arbitrary_string_rejected(arbitrary_str: str):
    """Arbitrary non-CTS strings must be strictly rejected."""
    assert SAPADTClient.validate_transport_request(arbitrary_str) is False


# =========================================================================
# 2. Connector Level: Zero Network Calls on Invalid Request
# =========================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_request",
    [
        None,
        "",
        "   ",
        "INVALID_TR",
        "TRK900001",
        "random_string_123",
    ],
)
async def test_invalid_request_causes_zero_sap_network_calls_in_connector(bad_request):
    """Proves that missing or invalid transport request halts locally with zero network calls."""
    pkg = _make_approved_package(action=DecisionAction.CREATE, object_name="ZI_CustomOrder")
    settings = _make_write_enabled_settings()

    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    mock_client.validate_transport_request = SAPADTClient.validate_transport_request
    mock_client.get_ddl_source = AsyncMock()
    mock_client.create_ddls_shell = AsyncMock()
    mock_client.upload_ddls_source = AsyncMock()

    connector = SAPADTConnector(settings=settings, client=mock_client)

    with pytest.raises(SAPTransportRequestError) as exc_info:
        await connector.create_cds_in_sap(pkg, transport_request=bad_request)

    assert exc_info.value.status_code == 400
    assert "Workbench Transport Request" in str(exc_info.value)

    # STRICT ZERO NETWORK CALLS: Preflight, Step A, and Step B must NOT have been called
    assert not mock_client.get_ddl_source.called
    assert not mock_client.create_ddls_shell.called
    assert not mock_client.upload_ddls_source.called


# =========================================================================
# 3. ReviewStore Level: Local Validation Before Execution
# =========================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_request",
    [
        None,
        "",
        "BAD_REQUEST_123",
    ],
)
async def test_invalid_request_blocked_at_review_store_level(bad_request):
    """Proves ReviewStore.execute_sap_creation validates before invoking connector."""
    state = _make_sample_state(action=DecisionAction.CREATE, object_name="ZI_CustomOrder")
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved")

    mock_connector = MagicMock(spec=SAPADTConnector)
    mock_connector.create_cds_in_sap = AsyncMock()

    with pytest.raises(SAPTransportRequestError) as exc_info:
        await store.execute_sap_creation(approved.review_id, transport_request=bad_request, connector=mock_connector)

    assert exc_info.value.status_code == 400
    assert not mock_connector.create_cds_in_sap.called


# =========================================================================
# 4. REUSE Proposal Does NOT Require Transport Request & Rejects Creation
# =========================================================================
@pytest.mark.asyncio
async def test_reuse_does_not_require_transport_request():
    """REUSE proposals perform zero SAP writes and reject SAP DEV creation calls."""
    state = _make_sample_state(action=DecisionAction.REUSE)
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved REUSE")

    settings = _make_write_enabled_settings()
    mock_client = MagicMock(spec=SAPADTClient)
    connector = SAPADTConnector(settings=settings, client=mock_client)

    # Calling execute_sap_creation on REUSE must be blocked with SAPSecurityError
    with pytest.raises(SAPSecurityError) as exc_info:
        await store.execute_sap_creation(approved.review_id, transport_request=None, connector=connector)

    assert "REUSE" in str(exc_info.value)
    assert "require zero custom object creation" in str(exc_info.value)
    assert not mock_client.create_ddls_shell.called


# =========================================================================
# 5. EXTEND Strictly Requires Transport Request
# =========================================================================
@pytest.mark.asyncio
async def test_extend_requires_valid_transport_request():
    """EXTEND proposals create an extension object in DEV and require a valid transport request."""
    state = _make_sample_state(action=DecisionAction.EXTEND, object_name="ZE_SalesExtension")
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)
    approved = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved EXTEND")

    settings = _make_write_enabled_settings()
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    mock_client.validate_transport_request = SAPADTClient.validate_transport_request
    mock_client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZE_SALESEXTENSION"))
    mock_client.create_ddls_shell = AsyncMock(return_value={"status_code": 201, "lock_handle": "LOCK_EXT", "location": "/sap/bc/adt/ddic/ddl/sources/ze_salesextension"})
    mock_client.upload_ddls_source = AsyncMock(return_value=204)
    connector = SAPADTConnector(settings=settings, client=mock_client)

    # Missing transport request raises error
    with pytest.raises(SAPTransportRequestError):
        await store.execute_sap_creation(approved.review_id, transport_request=None, connector=connector)

    # Valid transport request succeeds
    res = await store.execute_sap_creation(approved.review_id, transport_request="DEVK900123", connector=connector)
    assert res.success is True
    assert res.sap_write_performed is True
    assert res.transport_request == "DEVK900123"


# =========================================================================
# 6. Existing Approval, Write, and Read-Only Gates Remain Enforced
# =========================================================================
@pytest.mark.asyncio
async def test_existing_gates_remain_enforced_even_with_valid_transport():
    """Even when a valid transport request is provided, all existing safety gates must hold."""
    state = _make_sample_state(action=DecisionAction.CREATE, object_name="ZI_CustomOrder")
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)

    # Gate 1: Unapproved review cannot be written
    with pytest.raises(GovernanceApprovalRequiredError):
        await store.execute_sap_creation(pkg.review_id, transport_request="DEVK900123")

    # Gate 2: Rejected review cannot be written
    store.reject(pkg.review_id, reviewer="arch", reason="Not feasible")
    with pytest.raises(GovernanceApprovalRequiredError):
        await store.execute_sap_creation(pkg.review_id, transport_request="DEVK900123")

    # Fresh approved package for write-policy gate tests
    approved = _make_approved_package(action=DecisionAction.CREATE, object_name="ZI_CustomOrder")

    # Gate 3: Write capability disabled
    disabled_settings = Settings(SAP_DEV_WRITE_ENABLED=False, SAP_LIVE_READ_ONLY=False)
    client_disabled = SAPADTClient(settings=disabled_settings)
    connector_disabled = SAPADTConnector(settings=disabled_settings, client=client_disabled)
    with pytest.raises(SAPSecurityError) as exc_w:
        await connector_disabled.create_cds_in_sap(approved, transport_request="DEVK900123")
    assert "SAP_DEV_WRITE_ENABLED is false" in str(exc_w.value)

    # Gate 4: Read-only kill switch
    ro_settings = Settings(SAP_DEV_WRITE_ENABLED=True, SAP_LIVE_READ_ONLY=True)
    client_ro = SAPADTClient(settings=ro_settings)
    connector_ro = SAPADTConnector(settings=ro_settings, client=client_ro)
    with pytest.raises(SAPSecurityError) as exc_ro:
        await connector_ro.create_cds_in_sap(approved, transport_request="DEVK900123")
    assert "SAP_LIVE_READ_ONLY is enabled" in str(exc_ro.value)


# =========================================================================
# 7. API Route Level Tests
# =========================================================================
def test_api_route_rejects_missing_or_invalid_transport_request():
    """FastAPI endpoint returns HTTP 400 Bad Request when transport request is missing or invalid."""
    global_store = get_review_store()
    state = _make_sample_state(action=DecisionAction.CREATE, object_name="ZI_ApiTest")
    pkg = build_review_package(state)
    global_store.register(pkg, state)
    global_store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved for API test")

    client = TestClient(app)

    # 1. No payload / empty JSON
    res1 = client.post(f"/api/v1/reviews/{pkg.review_id}/create-sap", json={})
    assert res1.status_code == 400
    assert "Workbench Transport Request" in res1.json()["detail"]

    # 2. Invalid transport request
    res2 = client.post(
        f"/api/v1/reviews/{pkg.review_id}/create-sap",
        json={"transport_request": "INVALID_FORMAT"},
    )
    assert res2.status_code == 400
    assert "Invalid Workbench Transport Request" in res2.json()["detail"]
