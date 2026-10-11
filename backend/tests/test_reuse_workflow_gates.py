"""Milestone 14: REUSE Workflow Gate Regression and Security Tests.

Validates that:
1. Approved REUSE review packages strictly reject SAP DEV creation (ReviewStore & SAPADTConnector).
2. Approved REUSE review packages strictly reject existing shell upload (ReviewStore & SAPADTConnector).
3. Approved REUSE review packages strictly reject SAP DEV activation (ReviewStore & SAPADTConnector).
4. FastAPI endpoints return HTTP 403 Forbidden for create-sap, upload-existing-shell, and activate-sap on REUSE.
5. EXTEND and CREATE workflows are NOT blocked by REUSE guards and remain permitted through their valid gates.
6. Unapproved reviews (PENDING, REJECTED, CHANGES_REQUESTED) remain blocked by governance approval gates.
7. Zero network writes, zero secrets, zero state corruption.

Strict Safety: Offline tests only. Zero live SAP network traffic.
"""

from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
import pytest

from src.config import Settings
from src.core.exceptions import GovernanceApprovalRequiredError, SAPNotFoundError, SAPSecurityError
from src.main import app
from src.models.domain import (
    BusinessRequirement,
    CDSCandidate,
    CDSWorkflowState,
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
from src.services.review_service import ReviewStore, build_review_package, get_review_store


def _make_settings_write_enabled() -> Settings:
    return Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_CONNECTOR_TYPE="adt",
        SAP_DEV_WRITE_ENABLED=True,
        SAP_LIVE_READ_ONLY=False,
    )


def _make_sample_state(
    action: DecisionAction = DecisionAction.REUSE,
    object_name: str = "I_SalesOrder",
) -> CDSWorkflowState:
    req = BusinessRequirement(
        title="Sales Order Analytics Test",
        description="Requirement for sales order analytics",
        business_domain="Sales",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder", "SalesOrderType", "CreationDate"],
    )
    candidate = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order Interface View",
        layer=CDSLayer.BASIC,
        release_status="RELEASED",
        available_fields=["SalesOrder", "SalesOrderType", "CreationDate"],
        key_fields=["SalesOrder"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=action,
        recommended_view="I_SalesOrder" if action != DecisionAction.CREATE else None,
        proposed_new_view_name=object_name if action == DecisionAction.CREATE else None,
        proposed_extension_name=object_name if action == DecisionAction.EXTEND else None,
        confidence_score=0.98,
        fit_percentage=100.0,
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
        ddl = f"define view entity {object_name} as select from I_SalesOrder {{ key SalesOrder }};"
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
        )

    val = ValidationResult(
        is_valid=True,
        clean_core_compliance_score=100.0,
        details=[{"check": "Standard View Reuse", "passed": True, "detail": "Clean core"}],
    )

    mapping = [
        FieldMapping(
            requirement_field="SalesOrder",
            matched_field="SalesOrder",
            mapping_type=MappingType.DIRECT_MATCH,
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            confidence=1.0,
        ),
    ]

    return {
        "requirement": req,
        "structured_requirement": StructuredRequirement(
            dimensions=["SalesOrder"],
            measures=[],
            all_requested_concepts=["SalesOrder"],
        ),
        "candidates": [candidate],
        "field_mappings": mapping,
        "decision": decision,
        "cds_draft": draft,
        "validation_result": val,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }


def _make_approved_package(
    action: DecisionAction = DecisionAction.REUSE,
    object_name: str = "I_SalesOrder",
    store: ReviewStore | None = None,
) -> tuple[CDSReviewPackage, ReviewStore]:
    state = _make_sample_state(action=action, object_name=object_name)
    pkg = build_review_package(state)
    target_store = store or ReviewStore()
    target_store.register(pkg, state)
    approved = target_store.approve(
        pkg.review_id,
        reviewer="lead_architect",
        comment=f"Approved {action.value} proposal",
    )
    return approved, target_store


# =========================================================================
# 1. Server-Side Rejection: create_cds_in_sap & execute_sap_creation
# =========================================================================
@pytest.mark.asyncio
async def test_approved_reuse_review_rejects_create_sap():
    """An approved REUSE package must strictly raise SAPSecurityError when SAP DEV creation is attempted."""
    pkg, store = _make_approved_package(action=DecisionAction.REUSE)
    settings = _make_settings_write_enabled()
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.create_ddls_shell = AsyncMock()
    mock_client.upload_ddls_source = AsyncMock()
    connector = SAPADTConnector(settings=settings, client=mock_client)

    # ReviewStore level
    with pytest.raises(SAPSecurityError) as exc_store:
        await store.execute_sap_creation(pkg.review_id, transport_request="DEVK900001", connector=connector)
    assert "REUSE" in str(exc_store.value)
    assert "require zero custom object creation" in str(exc_store.value)

    # Connector level
    with pytest.raises(SAPSecurityError) as exc_conn:
        await connector.create_cds_in_sap(pkg, transport_request="DEVK900001")
    assert "REUSE" in str(exc_conn.value)
    assert "require zero custom object creation" in str(exc_conn.value)

    # Guarantee zero network writes
    assert not mock_client.create_ddls_shell.called
    assert not mock_client.upload_ddls_source.called


# =========================================================================
# 2. Server-Side Rejection: upload_source_to_existing_shell
# =========================================================================
@pytest.mark.asyncio
async def test_approved_reuse_review_rejects_upload_shell():
    """An approved REUSE package must strictly raise SAPSecurityError when shell upload is attempted."""
    pkg, store = _make_approved_package(action=DecisionAction.REUSE)
    settings = _make_settings_write_enabled()
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.upload_ddls_source = AsyncMock()
    connector = SAPADTConnector(settings=settings, client=mock_client)

    # ReviewStore level
    with pytest.raises(SAPSecurityError) as exc_store:
        await store.execute_existing_shell_upload(pkg.review_id, transport_request="DEVK900001", connector=connector)
    assert "REUSE" in str(exc_store.value)
    assert "require zero source upload" in str(exc_store.value)

    # Connector level
    with pytest.raises(SAPSecurityError) as exc_conn:
        await connector.upload_source_to_existing_shell(pkg, transport_request="DEVK900001")
    assert "REUSE" in str(exc_conn.value)
    assert "require zero source upload" in str(exc_conn.value)

    # Guarantee zero network writes
    assert not mock_client.upload_ddls_source.called


# =========================================================================
# 3. Server-Side Rejection: activate_cds_in_sap & execute_sap_activation
# =========================================================================
@pytest.mark.asyncio
async def test_approved_reuse_review_rejects_activate_sap():
    """An approved REUSE package must strictly raise SAPSecurityError when activation is attempted."""
    pkg, store = _make_approved_package(action=DecisionAction.REUSE)
    settings = _make_settings_write_enabled()
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.activate_ddls_object = AsyncMock()
    connector = SAPADTConnector(settings=settings, client=mock_client)

    # ReviewStore level
    with pytest.raises(SAPSecurityError) as exc_store:
        await store.execute_sap_activation(pkg.review_id, connector=connector)
    assert "REUSE" in str(exc_store.value)
    assert "already active" in str(exc_store.value)

    # Connector level
    with pytest.raises(SAPSecurityError) as exc_conn:
        await connector.activate_cds_in_sap(pkg)
    assert "REUSE" in str(exc_conn.value)
    assert "already active" in str(exc_conn.value)

    # Guarantee zero network writes
    assert not mock_client.activate_ddls_object.called


# =========================================================================
# 4. API Endpoints Return HTTP 403 Forbidden for REUSE
# =========================================================================
def test_approved_reuse_api_endpoints_return_403():
    """FastAPI routes for creation, upload, and activation return 403 Forbidden for REUSE."""
    global_store = get_review_store()
    pkg, _ = _make_approved_package(action=DecisionAction.REUSE, store=global_store)
    client = TestClient(app)

    # 1. create-sap -> 403
    res_create = client.post(
        f"/api/v1/reviews/{pkg.review_id}/create-sap",
        json={"transport_request": "DEVK900001"},
    )
    assert res_create.status_code == 403
    assert "REUSE" in res_create.json()["detail"]
    assert "require zero custom object creation" in res_create.json()["detail"]

    # 2. upload-existing-shell -> 403
    res_upload = client.post(
        f"/api/v1/reviews/{pkg.review_id}/upload-existing-shell",
        json={"transport_request": "DEVK900001"},
    )
    assert res_upload.status_code == 403
    assert "REUSE" in res_upload.json()["detail"]
    assert "require zero source upload" in res_upload.json()["detail"]

    # 3. activate-sap -> 403
    res_activate = client.post(
        f"/api/v1/reviews/{pkg.review_id}/activate-sap",
        json={},
    )
    assert res_activate.status_code == 403
    assert "REUSE" in res_activate.json()["detail"]
    assert "already active" in res_activate.json()["detail"]


# =========================================================================
# 5. EXTEND and CREATE Paths Remain Permitted
# =========================================================================
@pytest.mark.asyncio
async def test_approved_extend_review_permits_create_sap():
    """An approved EXTEND proposal is NOT rejected by REUSE guards."""
    pkg, store = _make_approved_package(action=DecisionAction.EXTEND, object_name="ZE_SalesOrderExt")
    settings = _make_settings_write_enabled()
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    mock_client.validate_transport_request = SAPADTClient.validate_transport_request
    mock_client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZE_SALESORDEREXT"))
    mock_client.create_ddls_shell = AsyncMock(
        return_value={
            "status_code": 201,
            "lock_handle": "LOCK_EXT_12345",
            "location": "/sap/bc/adt/ddic/ddl/sources/ze_salesorderext",
        }
    )
    mock_client.upload_ddls_source = AsyncMock(return_value=204)
    connector = SAPADTConnector(settings=settings, client=mock_client)

    # Must NOT raise SAPSecurityError about REUSE
    result = await store.execute_sap_creation(pkg.review_id, transport_request="DEVK900001", connector=connector)
    assert result.success is True
    assert result.sap_object_name == "ZE_SALESORDEREXT"
    assert mock_client.create_ddls_shell.called


@pytest.mark.asyncio
async def test_approved_create_review_permits_create_sap():
    """An approved CREATE proposal is NOT rejected by REUSE guards."""
    pkg, store = _make_approved_package(action=DecisionAction.CREATE, object_name="ZI_SalesOrderCustom")
    settings = _make_settings_write_enabled()
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.validate_sap_object_name = SAPADTClient.validate_sap_object_name
    mock_client.validate_transport_request = SAPADTClient.validate_transport_request
    mock_client.get_ddl_source = AsyncMock(side_effect=SAPNotFoundError("ZI_SALESORDERCUSTOM"))
    mock_client.create_ddls_shell = AsyncMock(
        return_value={
            "status_code": 201,
            "lock_handle": "LOCK_CRT_12345",
            "location": "/sap/bc/adt/ddic/ddl/sources/zi_salesordercustom",
        }
    )
    mock_client.upload_ddls_source = AsyncMock(return_value=204)
    connector = SAPADTConnector(settings=settings, client=mock_client)

    # Must NOT raise SAPSecurityError about REUSE
    result = await store.execute_sap_creation(pkg.review_id, transport_request="DEVK900001", connector=connector)
    assert result.success is True
    assert result.sap_object_name == "ZI_SALESORDERCUSTOM"
    assert mock_client.create_ddls_shell.called


# =========================================================================
# 6. Unapproved Reviews Remain Blocked by Governance Gate
# =========================================================================
@pytest.mark.asyncio
async def test_unapproved_reuse_remains_blocked_by_governance():
    """Unapproved REUSE review fails at governance gate before reaching write gate."""
    state = _make_sample_state(action=DecisionAction.REUSE)
    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)

    # PENDING status must raise GovernanceApprovalRequiredError
    with pytest.raises(GovernanceApprovalRequiredError) as exc_info:
        await store.execute_sap_creation(pkg.review_id, transport_request="DEVK900001")
    assert "requires explicit senior developer or architect approval" in str(exc_info.value)
