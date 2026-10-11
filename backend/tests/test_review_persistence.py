"""Tests for Review Package and Workflow State Persistence across Restarts (Step 8G)."""

import os
from pathlib import Path
import pytest
import tempfile

from src.core.exceptions import EntityNotFoundError
from src.models.domain import (
    BusinessRequirement,
    CDSWorkflowState,
    CDSCandidate,
    CDSDraft,
    CDSReviewPackage,
    Decision,
    DecisionAction,
    DeploymentRequest,
    DeploymentStatus,
    EvidenceLevel,
    FieldMapping,
    MappingType,
    ReviewStatus,
    SAPCheckMessage,
    SAPReviewCheckrunResult,
    SAPValidationStatus,
    StructuredRequirement,
    ValidationResult,
)
from src.services.review_service import ReviewStore, build_review_package


@pytest.fixture
def temp_db_path(tmp_path):
    """Provides an isolated SQLite database path for testing persistence."""
    db_file = tmp_path / "test_persistence.db"
    return str(db_file)


def _create_sample_state() -> CDSWorkflowState:
    req = BusinessRequirement(
        id="REQ-PERSIST-001",
        title="Extend Sales Order",
        description="Extend I_SalesOrder with Billing Request Order Type",
        business_domain="Sales",
        required_entities=["I_SalesOrder"],
        required_fields=["SalesOrder", "OrderTypeForBillingRequest"],
        filter_criteria=[],
    )
    structured = StructuredRequirement(
        intent="Extend sales order view",
        entities=["I_SalesOrder"],
        fields=["SalesOrder", "OrderTypeForBillingRequest"],
        dimensions=["SalesOrder"],
        measures=[],
        filters=[],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.EXTEND,
        recommended_view="I_SalesOrder",
        confidence_score=0.96,
        fit_percentage=100.0,
        rationale="Extend view with append name ZA_SALESORD_EXT2",
        missing_fields=[],
    )
    draft = CDSDraft(
        requirement_id=req.id,
        decision_action=DecisionAction.EXTEND,
        object_name="ZI_SalesOrder_Ext2",
        object_type="DDLS/DF",
        sql_view_append_name="ZA_SALESORD_EXT2",
        ddl_source="@AbapCatalog.sqlViewAppendName: 'ZA_SALESORD_EXT2'\nextend view I_SalesOrder with ZI_SalesOrder_Ext2 { _SalesOrderType.OrderTypeForBillingRequest };",
    )
    validation = ValidationResult(
        is_valid=True,
        syntax_errors=[],
        governance_warnings=[],
        clean_core_compliance_score=100.0,
        sap_validation_status=SAPValidationStatus.PASS,
    )
    mappings = [
        FieldMapping(
            requirement_field="OrderTypeForBillingRequest",
            target_view="I_SalesOrder",
            target_field="OrderTypeForBillingRequest",
            mapping_type=MappingType.DIRECT_MATCH,
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            confidence=0.98,
        )
    ]
    deployment = DeploymentRequest(
        object_name="ZI_SalesOrder_Ext2",
        target_system="SAP DEV - Client 100",
        package="ZTRAINING_2026",
        transport_request="S3XK911848",
        requester="architect_lead",
        status=DeploymentStatus.PENDING_APPROVAL,
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "structured_requirement": structured,
        "decision": decision,
        "cds_draft": draft,
        "validation_result": validation,
        "field_mappings": mappings,
        "deployment_request": deployment,
        "review_status": ReviewStatus.PENDING_REVIEW,
        "audit_logs": [{"step": "INITIAL_PIPELINE", "status": "COMPLETED"}],
    }
    return state


def test_review_package_persists_across_store_restart(temp_db_path):
    """Verifies that a registered and approved review package survives store restart."""
    state = _create_sample_state()
    package = build_review_package(state)
    assert package.can_approve is True

    # Store 1: Register and Approve
    store1 = ReviewStore(db_path=temp_db_path)
    rev_id = store1.register(package, state)
    assert rev_id == package.review_id

    approved_pkg = store1.approve(
        review_id=rev_id,
        reviewer="senior_gatekeeper",
        comment="Explicit approval for DEV deployment",
    )
    assert approved_pkg.status == ReviewStatus.APPROVED
    assert approved_pkg.reviewer == "senior_gatekeeper"
    assert len(approved_pkg.audit_events) == 1

    # SIMULATE BACKEND RESTART: Instantiate a brand new ReviewStore pointing to same DB
    store2 = ReviewStore(db_path=temp_db_path)
    # Confirm in-memory cache is empty before querying
    assert len(store2._packages) == 0

    # Retrieve from fresh store instance
    rehydrated = store2.get(rev_id)
    assert rehydrated is not None
    assert rehydrated.review_id == rev_id
    assert rehydrated.requirement_id == "REQ-PERSIST-001"
    assert rehydrated.status == ReviewStatus.APPROVED
    assert rehydrated.reviewer == "senior_gatekeeper"
    assert rehydrated.review_comment == "Explicit approval for DEV deployment"
    assert rehydrated.can_approve is True
    assert rehydrated.decision_action == DecisionAction.EXTEND
    assert rehydrated.object_name == "ZI_SalesOrder_Ext2"
    assert rehydrated.sql_view_append_name == "ZA_SALESORD_EXT2"
    assert "ZA_SALESORD_EXT2" in rehydrated.ddl_source
    assert len(rehydrated.audit_events) == 1
    assert rehydrated.audit_events[0].action == "REVIEW_APPROVED"
    assert rehydrated.audit_events[0].reviewer == "senior_gatekeeper"

    # Verify workflow state also rehydrated
    rehydrated_state = store2.get_state(rev_id)
    assert rehydrated_state is not None
    assert rehydrated_state["review_status"] == ReviewStatus.APPROVED
    assert rehydrated_state["is_human_approved"] is True
    assert rehydrated_state["deployment_request"].transport_request == "S3XK911848"
    assert rehydrated_state["decision"].is_approved is True
    assert len(rehydrated_state["audit_logs"]) >= 1


def test_nonexistent_review_id_returns_none(temp_db_path):
    """Verifies that non-existent review IDs return None (yielding 404)."""
    store = ReviewStore(db_path=temp_db_path)
    assert store.get("non-existent-uuid-1234") is None
    assert store.get_by_requirement("REQ-DOES-NOT-EXIST") is None
    assert store.get_by_decision("DEC-DOES-NOT-EXIST") is None
    assert store.get_state("non-existent-uuid-1234") is None


def test_get_by_requirement_and_decision_after_restart(temp_db_path):
    """Verifies lookup by requirement_id and decision_id survives restart."""
    state = _create_sample_state()
    package = build_review_package(state)

    store1 = ReviewStore(db_path=temp_db_path)
    store1.register(package, state)

    # Fresh store
    store2 = ReviewStore(db_path=temp_db_path)
    by_req = store2.get_by_requirement("REQ-PERSIST-001")
    assert by_req is not None
    assert by_req.review_id == package.review_id

    by_dec = store2.get_by_decision(package.decision.id)
    assert by_dec is not None
    assert by_dec.review_id == package.review_id


def test_checkrun_result_persists_across_restart(temp_db_path):
    """Verifies that checkrun diagnostics attached to review package survive restart."""
    state = _create_sample_state()
    package = build_review_package(state)

    store1 = ReviewStore(db_path=temp_db_path)
    store1.register(package, state)
    store1.approve(package.review_id, reviewer="lead_dev")

    # Attach checkrun result directly and persist
    package.latest_sap_checkrun = SAPReviewCheckrunResult(
        review_id=package.review_id,
        sap_object_name="ZI_SalesOrder_Ext2",
        status=SAPValidationStatus.WARNING,
        success=True,
        blocking_errors=0,
        warnings=1,
        information=0,
        messages=[
            SAPCheckMessage(
                severity="W",
                short_text="DDIC-based CDS views are obsolete",
                line=1,
                column=1,
            )
        ],
    )
    store1._save_to_db(package, store1._states.get(package.review_id))

    # Restart
    store2 = ReviewStore(db_path=temp_db_path)
    reloaded = store2.get(package.review_id)
    assert reloaded is not None
    assert reloaded.latest_sap_checkrun is not None
    assert reloaded.latest_sap_checkrun.blocking_errors == 0
    assert reloaded.latest_sap_checkrun.warnings == 1
    assert len(reloaded.latest_sap_checkrun.messages) == 1
    assert reloaded.latest_sap_checkrun.messages[0].short_text == "DDIC-based CDS views are obsolete"


@pytest.mark.asyncio
async def test_api_review_persistence_across_restart(async_client):
    """Verifies that API endpoint /api/v1/reviews/{id} serves rehydrated package after memory wipe."""
    from src.services.review_service import get_review_store
    store = get_review_store()

    state = _create_sample_state()
    package = build_review_package(state)
    rev_id = store.register(package, state)

    # Approve via API
    approve_resp = await async_client.post(
        f"/api/v1/reviews/{rev_id}/approve",
        json={"reviewer": "arch_lead", "comment": "API Approval test"},
    )
    assert approve_resp.status_code == 200
    data = approve_resp.json()
    assert data["status"] == "APPROVED"
    assert data["reviewer"] == "arch_lead"

    # WIPE IN-MEMORY CACHES ONLY (simulating server process memory loss while preserving DB)
    with store._lock:
        store._packages.clear()
        store._req_to_review.clear()
        store._dec_to_review.clear()
        store._states.clear()

    # Query via API after memory wipe
    get_resp = await async_client.get(f"/api/v1/reviews/{rev_id}")
    assert get_resp.status_code == 200
    reloaded_data = get_resp.json()
    assert reloaded_data["review_id"] == rev_id
    assert reloaded_data["status"] == "APPROVED"
    assert reloaded_data["reviewer"] == "arch_lead"
    assert reloaded_data["review_comment"] == "API Approval test"
    assert reloaded_data["object_name"] == "ZI_SalesOrder_Ext2"

    # Nonexistent review ID returns 404
    bad_resp = await async_client.get("/api/v1/reviews/00000000-0000-0000-0000-000000000000")
    assert bad_resp.status_code == 404
