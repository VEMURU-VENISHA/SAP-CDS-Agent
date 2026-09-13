"""Tests for RequirementAgent dynamic natural-language concept extraction."""

import pytest
from src.agents.requirement_agent import RequirementAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import BusinessRequirement, TargetUseCase


@pytest.mark.asyncio
async def test_requirement_extraction_dimensions_and_measures():
    """Verifies that natural language text is decomposed into dimensions, measures, and attributes."""
    agent = RequirementAgent()
    req = BusinessRequirement(
        title="Sales Order Item Analytics",
        description="We need a sales report showing SalesOrder, NetAmount, Material, SoldToParty, and OrderQuantity where status is Completed.",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
    )
    state: CDSWorkflowState = {"requirement": req}
    result_state = await agent.run(state)

    structured = result_state.get("structured_requirement")
    assert structured is not None
    # Check concept extraction
    all_concepts_lower = [c.lower() for c in structured.all_requested_concepts]
    assert "salesorder" in all_concepts_lower or "sales order" in all_concepts_lower or any("sales" in c for c in all_concepts_lower)
    assert any("netamount" in c or "amount" in c for c in all_concepts_lower)
    assert any("material" in c for c in all_concepts_lower)

    # Check measures classification
    measures_lower = [m.lower() for m in structured.measures]
    assert any("amount" in m or "quantity" in m for m in measures_lower)

    # Check filter extraction
    assert len(structured.filters) > 0 or len(req.filter_criteria) > 0


@pytest.mark.asyncio
async def test_requirement_extraction_preserves_explicit_fields():
    """Explicitly specified fields must be preserved and included in concept list."""
    agent = RequirementAgent()
    req = BusinessRequirement(
        title="Customer Master Analysis",
        description="Analyze customer sales data by region",
        required_entities=["Customer"],
        required_fields=["CustomerID", "CustomerName", "Country", "TotalRevenue"],
    )
    state: CDSWorkflowState = {"requirement": req}
    result_state = await agent.run(state)

    structured = result_state.get("structured_requirement")
    assert structured is not None
    for field in ["CustomerID", "CustomerName", "Country", "TotalRevenue"]:
        assert field in structured.all_requested_concepts


@pytest.mark.asyncio
async def test_requirement_empty_error():
    """Verifies graceful handling when requirement is missing."""
    agent = RequirementAgent()
    state: CDSWorkflowState = {}
    result_state = await agent.run(state)
    assert "errors" in result_state
    assert any("No requirement" in e for e in result_state["errors"])
