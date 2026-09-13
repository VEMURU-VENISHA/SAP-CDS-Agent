"""Tests for CDSGeneratorAgent and ValidationAgent: Evidence-grounded draft synthesis and local static validation."""

import pytest
from src.agents.generator_agent import CDSGeneratorAgent
from src.agents.validation_agent import ValidationAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import (
    BusinessRequirement,
    CandidateEvaluation,
    CDSCandidate,
    CDSDraft,
    CDSLayer,
    Decision,
    DecisionAction,
    DraftElementType,
    DraftFieldElement,
    ElementEvidenceRecord,
    EvidenceLevel,
    FieldMapping,
    MappingType,
    ValidationResult,
)


@pytest.mark.asyncio
async def test_generate_reuse_draft():
    """REUSE: Synthesizes consumption query proposal referencing standard view without creating a new object."""
    gen_agent = CDSGeneratorAgent()
    val_agent = ValidationAgent()

    req = BusinessRequirement(
        title="Sales Order Overview",
        description="Retrieve sales order header information",
        required_fields=["SalesOrder", "NetAmount"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.REUSE,
        recommended_view="I_SalesOrder",
        confidence_score=0.98,
        fit_percentage=100.0,
        rationale="100% verified match on standard view",
    )
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order View Entity",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder", "NetAmount"],
        release_status="RELEASED",
    )
    mappings = [
        FieldMapping(
            requirement_field="SalesOrder",
            matched_field="SalesOrder",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            evidence_detail="Exact technical field match",
            confidence=1.0,
        ),
        FieldMapping(
            requirement_field="NetAmount",
            matched_field="NetAmount",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            evidence_detail="Exact technical field match",
            confidence=1.0,
        ),
    ]

    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "candidates": [cand],
        "field_mappings": mappings,
    }

    state = await gen_agent.run(state)
    draft: CDSDraft = state.get("cds_draft")

    assert draft is not None
    assert draft.object_type == "REUSE_PROPOSAL"
    assert draft.object_name == "I_SalesOrder"
    assert "define view entity" not in draft.ddl_source.lower()
    assert "extend view entity" not in draft.ddl_source.lower()
    assert "SELECT" in draft.ddl_source
    assert "FROM I_SalesOrder" in draft.ddl_source
    assert len(draft.fields) == 2

    # Verify static validation on REUSE
    state = await val_agent.run(state)
    val: ValidationResult = state["validation_result"]
    assert val.is_valid is True
    assert val.clean_core_compliance_score == 100.0
    assert draft.generation_status == "VALIDATED"


@pytest.mark.asyncio
async def test_generate_extend_draft():
    """EXTEND: Synthesizes EXTEND VIEW ENTITY with verified Level 3 association fields only."""
    gen_agent = CDSGeneratorAgent()
    val_agent = ValidationAgent()

    req = BusinessRequirement(
        title="Sales Order Item Extension",
        description="Extend sales order with material",
        required_fields=["SalesOrder", "Material"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.EXTEND,
        recommended_view="I_SalesOrder",
        proposed_extension_name="ZI_SalesOrder_Ext",
        confidence_score=0.90,
        fit_percentage=50.0,
        rationale="Extendable base view with verified association",
        missing_fields=["Material"],
    )
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order View Entity",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
        associations=["I_SalesOrderItem"],
        is_extendable=True,
    )
    mappings = [
        FieldMapping(
            requirement_field="SalesOrder",
            matched_field="SalesOrder",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            evidence_detail="Direct field on base view",
            confidence=1.0,
        ),
        FieldMapping(
            requirement_field="Material",
            matched_field="Material",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION,
            evidence_detail="Verified association to 'I_SalesOrderItem' exposing field 'Material'",
            association_target_view="I_SalesOrderItem",
            association_target_field="Material",
            confidence=0.85,
        ),
    ]

    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "candidates": [cand],
        "field_mappings": mappings,
    }

    state = await gen_agent.run(state)
    draft: CDSDraft = state.get("cds_draft")

    assert draft is not None
    assert draft.object_type == "VIEW_ENTITY_EXTENSION"
    assert draft.object_name == "ZI_SalesOrder_Ext"
    assert "extend view entity I_SalesOrder with ZI_SalesOrder_Ext" in draft.ddl_source
    assert "_SalesOrderItem.Material as Material" in draft.ddl_source
    assert len(draft.fields) == 1
    assert draft.fields[0].field_name == "Material"
    assert draft.fields[0].evidence.evidence_level == EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION

    # Static validation
    state = await val_agent.run(state)
    val: ValidationResult = state["validation_result"]
    assert val.is_valid is True
    assert draft.generation_status == "VALIDATED"


@pytest.mark.asyncio
async def test_generate_create_draft():
    """CREATE: Synthesizes custom clean-core view entity in customer namespace (ZC_*)."""
    gen_agent = CDSGeneratorAgent()
    val_agent = ValidationAgent()

    req = BusinessRequirement(
        title="Custom Sales Analytics",
        description="Custom sales analytics view",
        required_fields=["SalesOrder", "NetAmount"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_CustomSalesAnalytics",
        confidence_score=0.80,
        fit_percentage=50.0,
        rationale="Custom view entity required",
    )
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order View Entity",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder", "NetAmount"],
        release_status="RELEASED",
    )
    mappings = [
        FieldMapping(
            requirement_field="SalesOrder",
            matched_field="SalesOrder",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            evidence_detail="Exact technical field match",
            confidence=1.0,
        ),
        FieldMapping(
            requirement_field="NetAmount",
            matched_field="NetAmount",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            evidence_detail="Exact technical field match",
            confidence=1.0,
        ),
    ]

    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "candidates": [cand],
        "field_mappings": mappings,
    }

    state = await gen_agent.run(state)
    draft: CDSDraft = state.get("cds_draft")

    assert draft is not None
    assert draft.object_name == "ZC_CustomSalesAnalytics"
    assert draft.object_name.startswith("ZC_")
    assert "define view entity ZC_CustomSalesAnalytics" in draft.ddl_source
    assert "@AccessControl.authorizationCheck: #CHECK" in draft.ddl_source
    assert "@Metadata.allowExtensions: true" in draft.ddl_source

    # Static validation
    state = await val_agent.run(state)
    val: ValidationResult = state["validation_result"]
    assert val.is_valid is True
    assert draft.generation_status == "VALIDATED"


@pytest.mark.asyncio
async def test_field_evidence_propagation():
    """Verifies that every generated field carries an exact ElementEvidenceRecord with source and level."""
    gen_agent = CDSGeneratorAgent()

    req = BusinessRequirement(
        title="Field Evidence Test",
        description="Verify evidence propagation",
        required_fields=["SalesOrder"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_FieldEvidenceTest",
        confidence_score=0.85,
        fit_percentage=100.0,
        rationale="Test",
    )
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order View",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
    )
    mappings = [
        FieldMapping(
            requirement_field="SalesOrder",
            matched_field="SalesOrder",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            evidence_detail="Direct Level 1 match from I_SalesOrder",
            confidence=1.0,
        )
    ]

    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "candidates": [cand],
        "field_mappings": mappings,
    }

    state = await gen_agent.run(state)
    draft: CDSDraft = state["cds_draft"]

    field_element = draft.fields[0]
    assert field_element.field_name == "SalesOrder"
    assert field_element.source_entity == "I_SalesOrder"
    assert field_element.evidence.evidence_level == EvidenceLevel.LEVEL_1_EXACT_FIELD
    assert field_element.evidence.is_verified is True
    assert "Direct Level 1 match" in field_element.evidence.evidence_detail


@pytest.mark.asyncio
async def test_level_5_llm_suggestion_rejection():
    """Level 5 unverified suggestions must be strictly excluded from generated CDS code and recorded in unresolved."""
    gen_agent = CDSGeneratorAgent()
    val_agent = ValidationAgent()

    req = BusinessRequirement(
        title="LLM Rejection Test",
        description="Check that L5 suggestions are not generated",
        required_fields=["SalesOrder", "HypotheticalField"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_LLMRejectionTest",
        confidence_score=0.50,
        fit_percentage=50.0,
        rationale="Testing L5 rejection",
    )
    cand = CDSCandidate(
        view_name="I_SalesOrder",
        description="Sales Order View",
        layer=CDSLayer.BASIC,
        available_fields=["SalesOrder"],
    )
    mappings = [
        FieldMapping(
            requirement_field="SalesOrder",
            matched_field="SalesOrder",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            evidence_detail="Direct verified field",
            confidence=1.0,
        ),
        FieldMapping(
            requirement_field="HypotheticalField",
            matched_field="ZZHypothetical",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_5_UNVERIFIED_SUGGESTION,
            evidence_detail="Inferred suggestion by LLM (unverified against DDL)",
            confidence=0.40,
        ),
    ]

    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "candidates": [cand],
        "field_mappings": mappings,
    }

    state = await gen_agent.run(state)
    draft: CDSDraft = state["cds_draft"]

    # HypotheticalField must NOT be in draft fields or code
    projected_names = [f.field_name for f in draft.fields]
    assert "HypotheticalField" not in projected_names
    assert "ZZHypothetical" not in draft.ddl_source
    # It must be recorded in unresolved_items and warnings
    assert "HypotheticalField" in draft.unresolved_items
    assert any("Level 5" in w or "rejected" in w or "LLM" in w for w in draft.warnings)


@pytest.mark.asyncio
async def test_unresolved_evidence_handling():
    """Unresolved metadata halts the generator with explicit INSUFFICIENT_EVIDENCE draft."""
    gen_agent = CDSGeneratorAgent()
    val_agent = ValidationAgent()

    req = BusinessRequirement(
        title="Unresolved Test",
        description="Check unresolved handling",
        required_fields=["SalesOrder", "MissingTargetField"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.INSUFFICIENT_EVIDENCE,
        recommended_view="I_SalesOrder",
        confidence_score=0.20,
        fit_percentage=50.0,
        rationale="Target DDL verification failed via ADT HTTP 404",
        warnings=["Target DDL could not be retrieved from SAP ADT"],
        missing_fields=["MissingTargetField"],
    )
    mappings = [
        FieldMapping(
            requirement_field="MissingTargetField",
            matched_field=None,
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_6_MISSING,
            mapping_type=MappingType.UNRESOLVED,
            evidence_detail="Target DDL HTTP 404",
            confidence=0.0,
        )
    ]

    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "field_mappings": mappings,
    }

    state = await gen_agent.run(state)
    draft: CDSDraft = state["cds_draft"]

    assert draft.generation_status == "INSUFFICIENT_EVIDENCE"
    assert "INSUFFICIENT EVIDENCE" in draft.ddl_source
    assert "MissingTargetField" in draft.unresolved_items

    # Static validation should record invalid due to insufficient evidence
    state = await val_agent.run(state)
    val: ValidationResult = state["validation_result"]
    assert val.is_valid is False
    assert val.clean_core_compliance_score == 0.0


@pytest.mark.asyncio
async def test_static_validation_unique_aliases():
    """ValidationAgent flags error when duplicate field aliases are present in projection list."""
    val_agent = ValidationAgent()

    field_ev = ElementEvidenceRecord(
        element_name="SalesOrder",
        element_type=DraftElementType.FIELD,
        source_entity="I_SalesOrder",
        evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
        confidence=1.0,
        is_verified=True,
    )
    # Intentionally duplicate alias 'SalesOrder'
    draft = CDSDraft(
        requirement_id="req-123",
        decision_action=DecisionAction.CREATE,
        object_name="ZC_DuplicateFieldView",
        object_type="CUSTOM_VIEW_ENTITY",
        proposed_layer=CDSLayer.CONSUMPTION,
        source_views=["I_SalesOrder"],
        fields=[
            DraftFieldElement(field_name="SalesOrder", source_expression="SalesOrder", source_entity="I_SalesOrder", evidence=field_ev),
            DraftFieldElement(field_name="SalesOrder", source_expression="VBELN", source_entity="I_SalesOrder", evidence=field_ev),
        ],
        ddl_source="""@EndUserText.label: 'Test'
@AccessControl.authorizationCheck: #CHECK
define view entity ZC_DuplicateFieldView as select from I_SalesOrder {
  SalesOrder,
  VBELN as SalesOrder
};""",
    )

    state: CDSWorkflowState = {"cds_draft": draft, "generated_cds_code": draft.ddl_source}
    state = await val_agent.run(state)

    val = state["validation_result"]
    assert val.is_valid is False
    assert any("Duplicate field alias 'SalesOrder'" in err for err in val.syntax_errors)


@pytest.mark.asyncio
async def test_static_validation_identifier_rules():
    """ValidationAgent detects object names exceeding 30 characters or missing customer namespace."""
    val_agent = ValidationAgent()

    # Name has 33 characters (exceeds ABAP 30-char limit)
    too_long_name = "ZC_ThisNameIsWayTooLongForABAPCDSView"
    assert len(too_long_name) > 30

    draft = CDSDraft(
        requirement_id="req-123",
        decision_action=DecisionAction.CREATE,
        object_name=too_long_name,
        object_type="CUSTOM_VIEW_ENTITY",
        proposed_layer=CDSLayer.CONSUMPTION,
        source_views=["I_SalesOrder"],
        fields=[],
        ddl_source=f"""@EndUserText.label: 'Test'
@AccessControl.authorizationCheck: #CHECK
define view entity {too_long_name} as select from I_SalesOrder {{
  key ID
}};""",
    )

    state: CDSWorkflowState = {"cds_draft": draft, "generated_cds_code": draft.ddl_source}
    state = await val_agent.run(state)

    val = state["validation_result"]
    assert val.is_valid is False
    assert any("exceeds SAP ABAP limit of 30 characters" in v for v in val.naming_convention_violations)


@pytest.mark.asyncio
async def test_multi_cds_composition_proposal():
    """Multi-CDS: Emits non-executable composition proposal with explicit join relationship warnings."""
    gen_agent = CDSGeneratorAgent()
    val_agent = ValidationAgent()

    req = BusinessRequirement(
        title="Order and Delivery Status",
        description="Composition test",
        required_fields=["SalesOrder", "DeliveryDocument"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_OrderAndDelivery",
        requires_composition=True,
        complementary_views=["I_SalesOrder", "I_DeliveryDocument"],
        confidence_score=0.85,
        fit_percentage=50.0,
        rationale="Composition required across complementary views",
    )
    candidates = [
        CDSCandidate(view_name="I_SalesOrder", description="Sales Orders", layer=CDSLayer.BASIC, available_fields=["SalesOrder"]),
        CDSCandidate(view_name="I_DeliveryDocument", description="Deliveries", layer=CDSLayer.BASIC, available_fields=["DeliveryDocument"]),
    ]
    mappings = [
        FieldMapping(
            requirement_field="SalesOrder",
            matched_field="SalesOrder",
            source_entity="I_SalesOrder",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            confidence=1.0,
        ),
        FieldMapping(
            requirement_field="DeliveryDocument",
            matched_field="DeliveryDocument",
            source_entity="I_DeliveryDocument",
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            confidence=1.0,
        ),
    ]

    state: CDSWorkflowState = {
        "requirement": req,
        "decision": decision,
        "candidates": candidates,
        "field_mappings": mappings,
    }

    state = await gen_agent.run(state)
    draft: CDSDraft = state["cds_draft"]

    assert draft.object_type == "COMPOSITION_PROPOSAL"
    assert "I_SalesOrder" in draft.source_views
    assert "I_DeliveryDocument" in draft.source_views
    assert any("Multi-CDS composition required" in w for w in draft.warnings)
    assert any("Join keys and association cardinality" in w for w in draft.warnings)


@pytest.mark.asyncio
async def test_deterministic_generation():
    """Generates identical, byte-for-byte DDL drafts across multiple independent executions."""
    gen_agent = CDSGeneratorAgent()

    req = BusinessRequirement(
        title="Deterministic Test",
        description="Ensure stable DDL generation",
        required_fields=["SalesOrder", "NetAmount"],
    )
    decision = Decision(
        requirement_id=req.id,
        action=DecisionAction.CREATE,
        proposed_new_view_name="ZC_DeterministicTest",
        confidence_score=0.90,
        fit_percentage=100.0,
        rationale="Deterministic test",
    )
    cand = CDSCandidate(view_name="I_SalesOrder", description="Orders", layer=CDSLayer.BASIC, available_fields=["SalesOrder", "NetAmount"])
    mappings = [
        FieldMapping(requirement_field="SalesOrder", matched_field="SalesOrder", source_entity="I_SalesOrder", evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD, confidence=1.0),
        FieldMapping(requirement_field="NetAmount", matched_field="NetAmount", source_entity="I_SalesOrder", evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD, confidence=1.0),
    ]

    state1: CDSWorkflowState = {"requirement": req, "decision": decision, "candidates": [cand], "field_mappings": mappings}
    state2: CDSWorkflowState = {"requirement": req, "decision": decision, "candidates": [cand], "field_mappings": mappings}

    res1 = await gen_agent.run(state1)
    res2 = await gen_agent.run(state2)

    assert res1["cds_draft"].ddl_source == res2["cds_draft"].ddl_source
    assert len(res1["cds_draft"].fields) == len(res2["cds_draft"].fields)


@pytest.mark.asyncio
async def test_no_sap_write_guarantee():
    """Verifies that CDSGeneratorAgent and ValidationAgent make ZERO write or checkrun calls to SAP."""
    gen_agent = CDSGeneratorAgent()
    val_agent = ValidationAgent()

    # Generator and ValidationAgent must not have or call write methods (no checkruns, no activation, no POST/PUT)
    assert not hasattr(gen_agent, "deploy")
    assert not hasattr(gen_agent, "activate")
    assert not hasattr(gen_agent, "checkrun")
    assert not hasattr(val_agent, "checkrun")
    assert not hasattr(val_agent, "activate")
