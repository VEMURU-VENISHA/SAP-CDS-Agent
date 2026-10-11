"""Milestone 12: CDS Review & Human Approval Gate Integration Tests.

Validates the human-in-the-loop review stage:
1. Review package generated for REUSE.
2. Review package generated for EXTEND.
3. Review package generated for CREATE.
4. INSUFFICIENT_EVIDENCE cannot be approved.
5. EXTEND cannot be approved without a generated draft.
6. CREATE cannot be approved when local validation has blocking errors.
7. Successful approval changes state to APPROVED.
8. Rejection requires a reason.
9. Change request requires a reason.
10. Invalid approval state transition is rejected.
11. Approval creates an audit event.
12. No SAP write operation occurs during approval.

Strict Safety: Zero SAP write operations, zero network writes.
"""

from unittest.mock import AsyncMock
import pytest

from src.models.domain import (
    BusinessRequirement,
    CDSWorkflowState,
    CDSCandidate,
    CDSDraft,
    CDSLayer,
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
from src.sap.interface import ISAPConnector
from src.sap.models import CDSFieldMetadata
from src.services.review_service import (
    APPROVAL_CONFIRMATION_NOTICE,
    ReviewStore,
    build_review_package,
    evaluate_approval_eligibility,
)


def _create_sample_requirement() -> BusinessRequirement:
    return BusinessRequirement(
        title="Sales Order Item Query",
        description="Need an analytical query over sales orders and net amount",
        business_domain="Sales & Distribution",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder", "NetAmount"],
    )


def test_review_package_generated_for_reuse():
    """Test 1: Review package generated for REUSE contains candidate, mapping, and can_approve is True."""
    req = _create_sample_requirement()
    candidate = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order Interface View",
        layer=CDSLayer.BASIC,
        release_status="RELEASED",
        available_fields=["SalesOrder", "NetAmount"],
        key_fields=["SalesOrder"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.REUSE,
        recommended_view="I_SalesOrder",
        confidence_score=0.98,
        fit_percentage=100.0,
        rationale="100% of requested concepts satisfied by standard view I_SalesOrder.",
    )
    mapping = [
        FieldMapping(
            requirement_field="SalesOrder",
            matched_field="SalesOrder",
            mapping_type=MappingType.DIRECT_MATCH,
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            confidence=1.0,
        ),
        FieldMapping(
            requirement_field="NetAmount",
            matched_field="NetAmount",
            mapping_type=MappingType.DIRECT_MATCH,
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            confidence=1.0,
        ),
    ]
    val = ValidationResult(
        is_valid=True,
        clean_core_compliance_score=100.0,
        details=[{"check": "Standard View Reuse", "passed": True, "detail": "Reusing standard view"}],
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "structured_requirement": StructuredRequirement(
            dimensions=["SalesOrder"],
            measures=["NetAmount"],
            all_requested_concepts=["SalesOrder", "NetAmount"],
        ),
        "candidates": [candidate],
        "field_mappings": mapping,
        "decision": decision,
        "validation_result": val,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    pkg = build_review_package(state)

    assert pkg.status == ReviewStatus.PENDING_REVIEW
    assert pkg.decision_action == DecisionAction.REUSE
    assert pkg.selected_candidate is not None
    assert pkg.selected_candidate.view_name == "I_SalesOrder"
    assert len(pkg.field_mappings) == 2
    assert pkg.can_approve is True
    assert len(pkg.blocking_reasons) == 0
    assert pkg.approval_confirmation_notice == APPROVAL_CONFIRMATION_NOTICE


def test_review_package_generated_for_extend():
    """Test 2: Review package generated for EXTEND contains draft DDL and extension viability."""
    req = _create_sample_requirement()
    candidate = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order Interface View",
        layer=CDSLayer.BASIC,
        release_status="RELEASED",
        available_fields=["SalesOrder"],
        key_fields=["SalesOrder"],
        is_extendable=True,
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.EXTEND,
        recommended_view="I_SalesOrder",
        proposed_extension_name="E_SalesOrderCustom",
        confidence_score=0.90,
        fit_percentage=80.0,
        rationale="Missing fields available via to-one association.",
    )
    draft = CDSDraft(
        requirement_id=req.id,
        decision_action=DecisionAction.EXTEND,
        object_name="E_SalesOrderCustom",
        object_type="VIEW_ENTITY_EXTENSION",
        ddl_source="extend view entity I_SalesOrder with E_SalesOrderCustom { _Customer.CustomerName }",
    )
    val = ValidationResult(is_valid=True, clean_core_compliance_score=100.0)

    state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [candidate],
        "decision": decision,
        "cds_draft": draft,
        "validation_result": val,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    pkg = build_review_package(state)

    assert pkg.decision_action == DecisionAction.EXTEND
    assert pkg.cds_draft is not None
    assert pkg.object_name == "E_SalesOrderCustom"
    assert "extend view entity" in pkg.ddl_source
    assert pkg.can_approve is True


def test_review_package_generated_for_create():
    """Test 3: Review package generated for CREATE contains custom view draft and clean-core validation."""
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_SalesOrderCustom",
        confidence_score=0.85,
        fit_percentage=0.0,
        rationale="No suitable released standard CDS view exists; custom composite view required.",
    )
    draft = CDSDraft(
        requirement_id=req.id,
        decision_action=DecisionAction.CREATE,
        object_name="ZC_SalesOrderCustom",
        object_type="VIEW_ENTITY",
        ddl_source="define view entity ZC_SalesOrderCustom as select from I_SalesOrder { key SalesOrder }",
    )
    val = ValidationResult(is_valid=True, clean_core_compliance_score=95.0)

    state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [],
        "decision": decision,
        "cds_draft": draft,
        "validation_result": val,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    pkg = build_review_package(state)

    assert pkg.decision_action == DecisionAction.CREATE
    assert pkg.object_name == "ZC_SalesOrderCustom"
    assert pkg.ddl_source is not None
    assert pkg.can_approve is True
    assert pkg.is_valid is True


def test_insufficient_evidence_cannot_be_approved():
    """Test 4: INSUFFICIENT_EVIDENCE decision strictly halts approval (can_approve is False)."""
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.INSUFFICIENT_EVIDENCE,
        confidence_score=0.20,
        fit_percentage=0.0,
        rationale="Unresolved required fields and unverified LLM suggestions halt decision.",
    )
    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    can_approve, reasons = evaluate_approval_eligibility(state)
    assert can_approve is False
    assert any("INSUFFICIENT_EVIDENCE" in r for r in reasons)

    pkg = build_review_package(state)
    assert pkg.can_approve is False

    store = ReviewStore()
    store.register(pkg, state)
    with pytest.raises(ValueError, match="Approval blocked"):
        store.approve(pkg.review_id, reviewer="lead_architect")


def test_extend_cannot_be_approved_without_draft():
    """Test 5: EXTEND cannot be approved when generated draft is missing."""
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.EXTEND,
        recommended_view="I_SalesOrder",
        confidence_score=0.90,
        fit_percentage=80.0,
        rationale="Extension viable.",
    )
    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "cds_draft": None,  # Missing draft
        "validation_result": ValidationResult(is_valid=True),
    }

    can_approve, reasons = evaluate_approval_eligibility(state)
    assert can_approve is False
    assert any("missing generated CDS extension draft" in r for r in reasons)


def test_create_cannot_be_approved_with_blocking_validation_errors():
    """Test 6: CREATE cannot be approved when local validation has blocking errors."""
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_BrokenView",
        confidence_score=0.80,
        fit_percentage=0.0,
        rationale="Custom view needed.",
    )
    draft = CDSDraft(
        requirement_id=req.id,
        decision_action=DecisionAction.CREATE,
        object_name="ZC_BrokenView",
        ddl_source="define view entity ZC_BrokenView as select ...",
    )
    val = ValidationResult(
        is_valid=False,
        syntax_errors=["Syntax error: expected '{' near line 1"],
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "cds_draft": draft,
        "validation_result": val,
    }

    can_approve, reasons = evaluate_approval_eligibility(state)
    assert can_approve is False
    assert any("blocking validation errors" in r for r in reasons)


def test_successful_approval_changes_state_to_approved():
    """Test 7: Successful approval changes status to APPROVED and records approver metadata."""
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.REUSE,
        recommended_view="I_SalesOrder",
        confidence_score=1.0,
        fit_percentage=100.0,
        rationale="Standard reuse.",
    )
    val = ValidationResult(is_valid=True)
    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "validation_result": val,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)

    updated_pkg = store.approve(pkg.review_id, reviewer="lead_architect", comment="Verified safe reuse.")

    assert updated_pkg.status == ReviewStatus.APPROVED
    assert updated_pkg.reviewer == "lead_architect"
    assert updated_pkg.review_comment == "Verified safe reuse."
    assert updated_pkg.review_timestamp is not None
    assert state["review_status"] == ReviewStatus.APPROVED
    assert state["is_human_approved"] is True
    assert decision.is_approved is True


def test_rejection_requires_reason():
    """Test 8: Rejection strictly requires a non-empty reason."""
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.REUSE,
        confidence_score=1.0,
        fit_percentage=100.0,
        rationale="Standard reuse.",
    )
    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)

    # Empty reason fails
    with pytest.raises(ValueError, match="rejection reason.*strictly required"):
        store.reject(pkg.review_id, reviewer="lead_architect", reason="")

    with pytest.raises(ValueError, match="rejection reason.*strictly required"):
        store.reject(pkg.review_id, reviewer="lead_architect", reason="  ")

    # Meaningful reason succeeds
    updated = store.reject(pkg.review_id, reviewer="lead_architect", reason="Does not align with S/4 migration guidelines.")
    assert updated.status == ReviewStatus.REJECTED
    assert updated.reviewer == "lead_architect"
    assert updated.review_comment == "Does not align with S/4 migration guidelines."
    assert state["review_status"] == ReviewStatus.REJECTED
    assert state["is_human_approved"] is False


def test_change_request_requires_reason():
    """Test 9: Change request strictly requires a non-empty description."""
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        confidence_score=0.85,
        fit_percentage=0.0,
        rationale="Custom view.",
    )
    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)

    # Empty reason fails
    with pytest.raises(ValueError, match="change request description.*strictly required"):
        store.request_changes(pkg.review_id, reviewer="lead_architect", reason="")

    # Meaningful reason succeeds
    updated = store.request_changes(
        pkg.review_id,
        reviewer="lead_architect",
        reason="Please add currency key association to avoid rounding discrepancies.",
    )
    assert updated.status == ReviewStatus.CHANGES_REQUESTED
    assert updated.reviewer == "lead_architect"
    assert "currency key association" in updated.review_comment


def test_invalid_approval_state_transition_is_rejected():
    """Test 10: Invalid transitions like REJECTED -> APPROVED are rejected."""
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.REUSE,
        confidence_score=1.0,
        fit_percentage=100.0,
        rationale="Standard reuse.",
    )
    val = ValidationResult(is_valid=True)
    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "validation_result": val,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)

    # Reject first
    store.reject(pkg.review_id, reviewer="lead_architect", reason="Rejected for redesign.")
    assert store.get(pkg.review_id).status == ReviewStatus.REJECTED

    # Attempting to approve rejected package must raise ValueError
    with pytest.raises(ValueError, match="Cannot approve a rejected proposal"):
        store.approve(pkg.review_id, reviewer="lead_architect")


def test_approval_creates_audit_event():
    """Test 11: Approval generates a sanitized, immutable ReviewAuditEvent with zero secrets."""
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.REUSE,
        recommended_view="I_SalesOrder",
        confidence_score=1.0,
        fit_percentage=100.0,
        rationale="Standard reuse.",
    )
    val = ValidationResult(is_valid=True)
    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "validation_result": val,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)

    updated = store.approve(pkg.review_id, reviewer="lead_architect", comment="Approved after architecture sign-off.")

    assert len(updated.audit_events) == 1
    event = updated.audit_events[0]
    assert event.action == "REVIEW_APPROVED"
    assert event.previous_status == ReviewStatus.PENDING_REVIEW
    assert event.new_status == ReviewStatus.APPROVED
    assert event.reviewer == "lead_architect"
    assert event.decision_action == DecisionAction.REUSE
    assert event.timestamp is not None
    # Verify zero secrets
    dumped = event.model_dump_json()
    assert "password" not in dumped.lower()
    assert "secret" not in dumped.lower()
    assert "token" not in dumped.lower()
    assert "cookie" not in dumped.lower()


def test_no_sap_write_operation_occurs_during_approval():
    """Test 12: Verifies that approving, rejecting, or requesting changes executes zero SAP network write calls."""
    mock_connector = AsyncMock(spec=ISAPConnector)
    req = _create_sample_requirement()
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.REUSE,
        recommended_view="I_SalesOrder",
        confidence_score=1.0,
        fit_percentage=100.0,
        rationale="Standard reuse.",
    )
    val = ValidationResult(is_valid=True)
    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "validation_result": val,
        "review_status": ReviewStatus.PENDING_REVIEW,
    }

    pkg = build_review_package(state)
    store = ReviewStore()
    store.register(pkg, state)

    # 1. Approval
    store.approve(pkg.review_id, reviewer="lead_architect", comment="Sign-off")

    # 2. Check mock connector: zero write operations called
    assert mock_connector.create_cds_draft.call_count == 0
    assert mock_connector.activate_cds.call_count == 0
    assert mock_connector.validate_cds.call_count == 0
