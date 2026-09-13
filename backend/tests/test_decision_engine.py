"""Tests for DecisionAgent: REUSE, EXTEND, CREATE, INSUFFICIENT_EVIDENCE, and Multi-CDS composition."""

import pytest
from src.agents.decision_agent import DecisionAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import (
    BusinessRequirement,
    CandidateEvaluation,
    CDSCandidate,
    CDSLayer,
    DecisionAction,
    EvidenceLevel,
    FieldMapping,
    MappingType,
    StructuredRequirement,
)


@pytest.mark.asyncio
async def test_decision_reuse_on_100_percent_direct_coverage():
    """REUSE: 100% of requested concepts satisfied directly with verified metadata on standard VDM view."""
    agent = DecisionAgent()
    req = BusinessRequirement(
        title="Sales Order Report",
        description="Retrieve sales order and net amount",
        required_fields=["SalesOrder", "NetAmount"],
    )
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order View",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder", "NetAmount"],
        release_status="RELEASED",
    )
    evaluation = CandidateEvaluation(
        candidate=cand,
        rank=1,
        rank_score=100.0,
        coverage_percentage=100.0,
        matched_concepts=["SalesOrder", "NetAmount"],
        missing_concepts=[],
        field_mappings=[
            FieldMapping(
                requirement_field="SalesOrder",
                matched_field="SalesOrder",
                source_entity="I_SalesOrder",
                evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                mapping_type=MappingType.DIRECT_MATCH,
            ),
            FieldMapping(
                requirement_field="NetAmount",
                matched_field="NetAmount",
                source_entity="I_SalesOrder",
                evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                mapping_type=MappingType.DIRECT_MATCH,
            ),
        ],
        scoring_breakdown={
            "direct_matches_count": 2,
            "extension_matches_count": 0,
            "missing_count": 0,
            "unresolved_count": 0,
        },
        is_extension_viable=False,
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [cand],
        "evaluated_candidates": [evaluation],
    }
    result = await agent.run(state)
    decision = result["decision"]

    assert decision.action == DecisionAction.REUSE
    assert decision.confidence_score >= 0.95
    assert decision.fit_percentage == 100.0
    assert decision.recommended_view == "I_SalesOrder"
    assert decision.missing_fields == []
    assert any("Zero clean-core footprint" in t for t in decision.tradeoffs)


@pytest.mark.asyncio
async def test_decision_extend_when_missing_concepts_verified_on_association():
    """EXTEND: Missing concepts are verified obtainable via Level 3 association on extendable view."""
    agent = DecisionAgent()
    req = BusinessRequirement(
        title="Sales Order Items",
        description="Sales order with material",
        required_fields=["SalesOrder", "Material"],
    )
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order View",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
        associations=["I_SalesOrderItem"],
        is_extendable=True,
    )
    evaluation = CandidateEvaluation(
        candidate=cand,
        rank=1,
        rank_score=85.0,
        coverage_percentage=50.0,
        matched_concepts=["SalesOrder", "Material"],
        missing_concepts=[],
        field_mappings=[
            FieldMapping(
                requirement_field="SalesOrder",
                matched_field="SalesOrder",
                source_entity="I_SalesOrder",
                evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                mapping_type=MappingType.DIRECT_MATCH,
            ),
            FieldMapping(
                requirement_field="Material",
                matched_field="Material",
                source_entity="I_SalesOrder",
                evidence_level=EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION,
                mapping_type=MappingType.ASSOCIATION_HOP,
                association_target_view="I_SalesOrderItem",
                association_target_field="Material",
            ),
        ],
        scoring_breakdown={
            "direct_matches_count": 1,
            "extension_matches_count": 1,
            "missing_count": 0,
            "unresolved_count": 0,
        },
        is_extension_viable=True,
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [cand],
        "evaluated_candidates": [evaluation],
    }
    result = await agent.run(state)
    decision = result["decision"]

    assert decision.action == DecisionAction.EXTEND
    assert decision.recommended_view == "I_SalesOrder"
    assert decision.proposed_extension_name is not None
    assert "Material" in decision.missing_fields
    assert any("Non-intrusive extension" in t for t in decision.tradeoffs)


@pytest.mark.asyncio
async def test_decision_rejects_extend_when_not_extendable():
    """CREATE: View entity does not permit extensions (is_extendable=False) -> Must CREATE."""
    agent = DecisionAgent()
    req = BusinessRequirement(
        title="Sales Order Custom",
        description="Sales order with custom field",
        required_fields=["SalesOrder", "CustomField"],
    )
    cand = CDSCandidate(
        view_name="I_SalesOrderClosed",
        description="Non-extendable Sales Order View",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
        is_extendable=False,
    )
    evaluation = CandidateEvaluation(
        candidate=cand,
        rank=1,
        rank_score=40.0,
        coverage_percentage=50.0,
        matched_concepts=["SalesOrder"],
        missing_concepts=["CustomField"],
        field_mappings=[],
        scoring_breakdown={
            "direct_matches_count": 1,
            "extension_matches_count": 0,
            "missing_count": 1,
            "unresolved_count": 0,
        },
        is_extension_viable=False,
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [cand],
        "evaluated_candidates": [evaluation],
    }
    result = await agent.run(state)
    decision = result["decision"]

    assert decision.action == DecisionAction.CREATE
    assert decision.proposed_new_view_name is not None
    assert "CustomField" in decision.missing_fields
    assert "does not permit extensions" in decision.rationale


@pytest.mark.asyncio
async def test_decision_rejects_extend_on_unobtainable_fields():
    """CREATE: Missing concepts have no verified extension points -> Must CREATE."""
    agent = DecisionAgent()
    req = BusinessRequirement(
        title="Sales Order Report",
        description="Sales order with unknown field",
        required_fields=["SalesOrder", "UnknownExternalField"],
    )
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order View",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
        is_extendable=True,
    )
    evaluation = CandidateEvaluation(
        candidate=cand,
        rank=1,
        rank_score=45.0,
        coverage_percentage=50.0,
        matched_concepts=["SalesOrder"],
        missing_concepts=["UnknownExternalField"],
        field_mappings=[],
        scoring_breakdown={
            "direct_matches_count": 1,
            "extension_matches_count": 0,
            "missing_count": 1,
            "unresolved_count": 0,
        },
        is_extension_viable=False,
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [cand],
        "evaluated_candidates": [evaluation],
    }
    result = await agent.run(state)
    decision = result["decision"]

    assert decision.action == DecisionAction.CREATE
    assert "lack verified extension points" in decision.rationale


@pytest.mark.asyncio
async def test_decision_insufficient_evidence_halts_pipeline():
    """INSUFFICIENT_EVIDENCE: Association target DDL could not be retrieved -> Halts decision."""
    agent = DecisionAgent()
    req = BusinessRequirement(
        title="Sales Order Analytics",
        description="Sales order with unverified target",
        required_fields=["SalesOrder", "ItemStatus"],
    )
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order View",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
        associations=["I_SalesOrderItem"],
        is_extendable=True,
    )
    evaluation = CandidateEvaluation(
        candidate=cand,
        rank=1,
        rank_score=45.0,
        coverage_percentage=50.0,
        matched_concepts=["SalesOrder"],
        missing_concepts=["ItemStatus"],
        field_mappings=[
            FieldMapping(
                requirement_field="SalesOrder",
                matched_field="SalesOrder",
                source_entity="I_SalesOrder",
                evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                mapping_type=MappingType.DIRECT_MATCH,
            ),
            FieldMapping(
                requirement_field="ItemStatus",
                matched_field=None,
                source_entity="I_SalesOrder",
                evidence_level=EvidenceLevel.LEVEL_6_MISSING,
                mapping_type=MappingType.UNRESOLVED,
                evidence_detail="Target CDS 'I_SalesOrderItem' DDL could not be retrieved via ADT: HTTP 404",
                association_target_view="I_SalesOrderItem",
            ),
        ],
        scoring_breakdown={
            "direct_matches_count": 1,
            "extension_matches_count": 0,
            "missing_count": 1,
            "unresolved_count": 1,
        },
        is_extension_viable=False,
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [cand],
        "evaluated_candidates": [evaluation],
    }
    result = await agent.run(state)
    decision = result["decision"]

    assert decision.action == DecisionAction.INSUFFICIENT_EVIDENCE
    assert decision.confidence_score == 0.20
    assert "remain UNRESOLVED" in decision.rationale
    assert len(decision.warnings) > 0


@pytest.mark.asyncio
async def test_decision_multi_cds_composition_detection():
    """Multi-CDS: Complementary candidates cover disjoint subsets of requirement -> Composition detected."""
    agent = DecisionAgent()
    req = BusinessRequirement(
        title="Order and Delivery Status",
        description="Combined order and delivery report",
        required_fields=["SalesOrder", "DeliveryDocument"],
    )
    # Candidate 1: satisfies SalesOrder, misses DeliveryDocument
    cand_1 = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Orders",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
        is_extendable=False,
    )
    ev_1 = CandidateEvaluation(
        candidate=cand_1,
        rank=1,
        rank_score=50.0,
        coverage_percentage=50.0,
        matched_concepts=["SalesOrder"],
        missing_concepts=["DeliveryDocument"],
        field_mappings=[],
        scoring_breakdown={
            "direct_matches_count": 1,
            "extension_matches_count": 0,
            "missing_count": 1,
            "unresolved_count": 0,
        },
        is_extension_viable=False,
    )

    # Candidate 2: satisfies DeliveryDocument, misses SalesOrder
    cand_2 = CDSCandidate(
        view_name="I_DeliveryDocument",
        description="Deliveries",
        layer=CDSLayer.BASIC,
        available_fields=["DeliveryDocument"],
        is_extendable=False,
    )
    ev_2 = CandidateEvaluation(
        candidate=cand_2,
        rank=2,
        rank_score=50.0,
        coverage_percentage=50.0,
        matched_concepts=["DeliveryDocument"],
        missing_concepts=["SalesOrder"],
        field_mappings=[],
        scoring_breakdown={
            "direct_matches_count": 1,
            "extension_matches_count": 0,
            "missing_count": 1,
            "unresolved_count": 0,
        },
        is_extension_viable=False,
    )

    state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [cand_1, cand_2],
        "evaluated_candidates": [ev_1, ev_2],
    }
    result = await agent.run(state)
    decision = result["decision"]

    assert decision.action == DecisionAction.CREATE
    assert decision.requires_composition is True
    assert "I_SalesOrder" in decision.complementary_views
    assert "I_DeliveryDocument" in decision.complementary_views
    assert "composition across complementary views" in decision.rationale


@pytest.mark.asyncio
async def test_decision_create_on_zero_candidates():
    """Zero candidates found in SAP repository search -> CREATE with transparent rationale."""
    agent = DecisionAgent()
    req = BusinessRequirement(
        title="Unique Niche Entity",
        description="Custom special table",
        required_fields=["SpecialID", "CustomMetric"],
    )
    state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [],
        "evaluated_candidates": [],
    }
    result = await agent.run(state)
    decision = result["decision"]

    assert decision.action == DecisionAction.CREATE
    assert decision.fit_percentage == 0.0
    assert decision.recommended_view is None
    assert "Zero SAP CDS candidates discovered" in decision.rationale
