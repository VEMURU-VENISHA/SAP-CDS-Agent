"""Tests for SemanticMappingAgent: 6-level evidence hierarchy and association verification."""

from unittest.mock import AsyncMock
import pytest
from src.agents.mapping_agent import SemanticMappingAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import (
    BusinessRequirement,
    CDSCandidate,
    CDSLayer,
    EvidenceLevel,
    MappingType,
    StructuredRequirement,
    TargetUseCase,
)
from src.sap.models import CDSMetadata, FieldDefinition


@pytest.fixture
def mock_connector():
    connector = AsyncMock()
    return connector


@pytest.mark.asyncio
async def test_exact_field_match_level_1(mock_connector):
    """Level 1: Exact technical field name match in candidate available_fields."""
    agent = SemanticMappingAgent(connector=mock_connector)
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order Header",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder", "NetAmount", "SoldToParty"],
        key_fields=["SalesOrder"],
        associations=[],
    )
    req = BusinessRequirement(
        title="Sales Orders",
        description="Retrieve sales order and net amount",
        required_fields=["SalesOrder", "NetAmount"],
    )
    state: CDSWorkflowState = {"requirement": req, "candidates": [cand]}
    result = await agent.run(state)

    evaluations = result["evaluated_candidates"]
    assert len(evaluations) == 1
    assert evaluations[0].coverage_percentage == 100.0

    mappings = evaluations[0].field_mappings
    for m in mappings:
        assert m.evidence_level == EvidenceLevel.LEVEL_1_EXACT_FIELD
        assert m.mapping_type == MappingType.DIRECT_MATCH
        assert m.confidence == 1.0


@pytest.mark.asyncio
async def test_field_label_match_level_2(mock_connector):
    """Level 2: Field label / key match when view description matches."""
    agent = SemanticMappingAgent(connector=mock_connector)
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order Entity",
        layer=CDSLayer.BASIC,
        available_fields=["VBELN"],
        key_fields=["SalesOrder"],
        associations=[],
    )
    req = BusinessRequirement(
        title="Sales Orders",
        description="Retrieve sales order",
        required_fields=["SalesOrder"],
    )
    state: CDSWorkflowState = {"requirement": req, "candidates": [cand]}
    result = await agent.run(state)

    mappings = result["evaluated_candidates"][0].field_mappings
    assert mappings[0].evidence_level == EvidenceLevel.LEVEL_2_LABEL_MATCH
    assert mappings[0].matched_field == "SalesOrder"


@pytest.mark.asyncio
async def test_verified_association_target_inspection_level_3(mock_connector):
    """Level 3: Verified association target DDL inspected via verified ADT endpoint."""
    target_meta = CDSMetadata(
        view_name="I_SalesOrderItem",
        fields=[
            FieldDefinition(field_name="SalesOrder", abap_type="CHAR", length=10, is_key=True),
            FieldDefinition(field_name="SalesOrderItem", abap_type="NUMC", length=6, is_key=True),
            FieldDefinition(field_name="Material", abap_type="CHAR", length=40),
        ],
    )
    mock_connector.get_cds_metadata.return_value = target_meta

    agent = SemanticMappingAgent(connector=mock_connector)
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order Header",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder", "SoldToParty"],
        key_fields=["SalesOrder"],
        associations=["I_SalesOrderItem"],
        is_extendable=True,
    )
    req = BusinessRequirement(
        title="Sales Orders with Material",
        description="Sales order with material item",
        required_fields=["SalesOrder", "Material"],
    )
    state: CDSWorkflowState = {"requirement": req, "candidates": [cand]}
    result = await agent.run(state)

    evaluations = result["evaluated_candidates"]
    assert len(evaluations) == 1
    ev = evaluations[0]
    # Concept 'Material' must be Level 3
    mat_mapping = next(m for m in ev.field_mappings if m.requirement_field == "Material")
    assert mat_mapping.evidence_level == EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION
    assert mat_mapping.association_target_view == "I_SalesOrderItem"
    assert mat_mapping.association_target_field == "Material"
    assert mat_mapping.mapping_type == MappingType.ASSOCIATION_HOP
    assert ev.is_extension_viable is True


@pytest.mark.asyncio
async def test_unverified_association_target_handled_as_unresolved(mock_connector):
    """Target DDL retrieval failure must result in UNRESOLVED and never be claimed as verified."""
    mock_connector.get_cds_metadata.side_effect = Exception("ADT HTTP 404: DDL source not found")

    agent = SemanticMappingAgent(connector=mock_connector)
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order Header",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
        key_fields=["SalesOrder"],
        associations=["I_UnverifiedTarget"],
        is_extendable=True,
    )
    req = BusinessRequirement(
        title="Sales Orders with Custom Field",
        description="Sales order with unverified field",
        required_fields=["SalesOrder", "CustomUnverifiedField"],
    )
    state: CDSWorkflowState = {"requirement": req, "candidates": [cand]}
    result = await agent.run(state)

    ev = result["evaluated_candidates"][0]
    unverified_mapping = next(m for m in ev.field_mappings if m.requirement_field == "CustomUnverifiedField")
    assert unverified_mapping.mapping_type == MappingType.UNRESOLVED
    assert unverified_mapping.evidence_level == EvidenceLevel.LEVEL_6_MISSING
    assert "could not be retrieved" in unverified_mapping.evidence_detail
    assert ev.is_extension_viable is False


@pytest.mark.asyncio
async def test_association_target_verified_but_field_missing(mock_connector):
    """Target DDL is verified via ADT, but the requested field is not present on target -> MISSING."""
    target_meta = CDSMetadata(
        view_name="I_SalesOrderItem",
        fields=[
            FieldDefinition(field_name="SalesOrder", abap_type="CHAR", length=10, is_key=True),
            FieldDefinition(field_name="Material", abap_type="CHAR", length=40),
        ],
    )
    mock_connector.get_cds_metadata.return_value = target_meta

    agent = SemanticMappingAgent(connector=mock_connector)
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order Header",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
        key_fields=["SalesOrder"],
        associations=["I_SalesOrderItem"],
        is_extendable=True,
    )
    req = BusinessRequirement(
        title="Sales Order with Nonexistent Target Field",
        description="Need profit center from item",
        required_fields=["SalesOrder", "ProfitCenter"],
    )
    state: CDSWorkflowState = {"requirement": req, "candidates": [cand]}
    result = await agent.run(state)

    ev = result["evaluated_candidates"][0]
    m = next(m for m in ev.field_mappings if m.requirement_field == "ProfitCenter")
    assert m.evidence_level == EvidenceLevel.LEVEL_6_MISSING
    assert m.mapping_type == MappingType.MISSING
    assert "was not found on target" in m.evidence_detail
    assert ev.is_extension_viable is False


@pytest.mark.asyncio
async def test_heuristic_synonym_level_4(mock_connector):
    """Level 4: Synonym match (e.g. VBELN <-> SalesOrder) supported by candidate technical fields."""
    agent = SemanticMappingAgent(connector=mock_connector)
    cand = CDSCandidate(
        view_name="I_SalesOrderRaw",
        description="Sales Order Raw Table",
        layer=CDSLayer.BASIC,
        available_fields=["VBELN", "NETWR"],
        key_fields=["VBELN"],
        associations=[],
    )
    req = BusinessRequirement(
        title="Sales Order Report",
        description="Sales order with net amount",
        required_fields=["SalesOrder", "NetAmount"],
    )
    state: CDSWorkflowState = {"requirement": req, "candidates": [cand]}
    result = await agent.run(state)

    ev = result["evaluated_candidates"][0]
    mappings = ev.field_mappings
    for m in mappings:
        assert m.evidence_level == EvidenceLevel.LEVEL_4_HEURISTIC_SYNONYM
        assert m.confidence == 0.80


@pytest.mark.asyncio
async def test_candidate_ranking_and_mandatory_override(mock_connector):
    """Multi-candidate ranking: candidate missing mandatory dimension is penalized."""
    agent = SemanticMappingAgent(connector=mock_connector)
    # Candidate A: Composite view with many fields, but misses mandatory dimension 'SalesOrder'
    cand_a = CDSCandidate(
        view_name="I_BillingDocumentItem",
        description="Billing Items",
        layer=CDSLayer.COMPOSITE,
        available_fields=["BillingDocument", "BillingItem", "NetAmount", "SoldToParty"],
        associations=["_Customer", "_Product"],
        is_extendable=True,
    )
    # Candidate B: Basic view with mandatory dimension 'SalesOrder' and fewer fields
    cand_b = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order Header",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder", "NetAmount"],
        key_fields=["SalesOrder"],
        associations=["_Item"],
        is_extendable=True,
    )

    req = BusinessRequirement(
        title="Sales Order Report",
        description="Sales order details",
        required_entities=["SalesOrder"],
        required_fields=["SalesOrder", "NetAmount", "SoldToParty"],
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
    )
    state: CDSWorkflowState = {"requirement": req, "candidates": [cand_a, cand_b]}
    result = await agent.run(state)

    evaluations = result["evaluated_candidates"]
    # Candidate B must rank #1 because Candidate A misses the mandatory dimension 'SalesOrder'
    assert evaluations[0].candidate.view_name == "I_SalesOrder"
    assert evaluations[0].rank == 1
    assert "coverage_score" in evaluations[0].scoring_breakdown
    assert "layer_suitability_score" in evaluations[0].scoring_breakdown
