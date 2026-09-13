"""Tests for Agent Architecture and Skeletons."""

import pytest
from src.agents.audit_agent import ImpactAuditAgent
from src.agents.datamodel_agent import DataModelAgent
from src.agents.decision_agent import DecisionAgent
from src.agents.discovery_agent import SAPDiscoveryAgent
from src.agents.generator_agent import CDSGeneratorAgent
from src.agents.governance_agent import SecurityGovernanceAgent
from src.agents.mapping_agent import SemanticMappingAgent
from src.agents.orchestrator import CDSWorkflowOrchestrator
from src.agents.requirement_agent import RequirementAgent
from src.agents.state import CDSWorkflowState
from src.agents.validation_agent import ValidationAgent
from src.models.domain import BusinessRequirement, TargetUseCase


def test_agent_initializations():
    """Verifies that all 9 agents initialize with names and descriptions."""
    agents = [
        RequirementAgent(),
        SAPDiscoveryAgent(),
        SemanticMappingAgent(),
        DecisionAgent(),
        DataModelAgent(),
        CDSGeneratorAgent(),
        ValidationAgent(),
        SecurityGovernanceAgent(),
        ImpactAuditAgent(),
    ]
    assert len(agents) == 9
    for agent in agents:
        assert agent.name is not None
        assert len(agent.description) > 0


@pytest.mark.asyncio
async def test_full_pipeline_orchestration():
    """Verifies end-to-end execution of the multi-agent workflow state pipeline."""
    orchestrator = CDSWorkflowOrchestrator()

    req = BusinessRequirement(
        title="Customer Sales Analytics",
        description="Requirement for sales orders aggregated by customer with order values",
        business_domain="Sales & Distribution",
        target_use_case=TargetUseCase.ANALYTICAL_REPORT,
        required_entities=["SalesOrder", "Customer"],
        required_fields=["SalesOrderID", "GrossAmount", "CustomerNumber"],
    )

    initial_state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [],
        "field_mappings": [],
        "audit_logs": [],
        "errors": [],
        "current_step": "START",
        "is_human_approved": False,
    }

    final_state = await orchestrator.execute_pipeline(initial_state)

    # Assertions on pipeline progression
    assert final_state.get("current_step") == "COMPLETED"
    assert final_state.get("decision") is not None
    assert final_state["decision"].requirement_id == req.id
    assert final_state.get("data_model") is not None
    assert final_state.get("generated_cds_code") is not None
    assert final_state.get("validation_result") is not None
    assert final_state.get("deployment_request") is not None

    # Verify audit logs captured events across agents
    audit_logs = final_state.get("audit_logs", [])
    assert len(audit_logs) >= 5
    agent_names_logged = {log["agent"] for log in audit_logs}
    assert "RequirementAgent" in agent_names_logged
    assert "DecisionAgent" in agent_names_logged
    assert "ImpactAuditAgent" in agent_names_logged
