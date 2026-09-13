"""LangGraph Multi-Agent Workflow Orchestrator for CDS Intelligence Pipeline."""

from typing import Any, Dict
from src.agents.audit_agent import ImpactAuditAgent
from src.agents.datamodel_agent import DataModelAgent
from src.agents.decision_agent import DecisionAgent
from src.agents.discovery_agent import SAPDiscoveryAgent
from src.agents.generator_agent import CDSGeneratorAgent
from src.agents.governance_agent import SecurityGovernanceAgent
from src.agents.mapping_agent import SemanticMappingAgent
from src.agents.requirement_agent import RequirementAgent
from src.agents.state import CDSWorkflowState
from src.agents.validation_agent import ValidationAgent
from src.logging_config import logger

try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False


class CDSWorkflowOrchestrator:
    """Orchestrates the 9 specialized agents across the CDS intelligence lifecycle."""

    def __init__(self):
        # Instantiate agents
        self.requirement_agent = RequirementAgent()
        self.discovery_agent = SAPDiscoveryAgent()
        self.mapping_agent = SemanticMappingAgent()
        self.decision_agent = DecisionAgent()
        self.datamodel_agent = DataModelAgent()
        self.generator_agent = CDSGeneratorAgent()
        self.validation_agent = ValidationAgent()
        self.governance_agent = SecurityGovernanceAgent()
        self.audit_agent = ImpactAuditAgent()

        self._graph = self._build_graph() if LANGGRAPH_AVAILABLE else None

    def _build_graph(self):
        """Constructs the LangGraph directed state graph."""
        builder = StateGraph(CDSWorkflowState)

        # Register nodes
        builder.add_node("requirement_step", self.requirement_agent.run)
        builder.add_node("discovery_step", self.discovery_agent.run)
        builder.add_node("mapping_step", self.mapping_agent.run)
        builder.add_node("decision_step", self.decision_agent.run)
        builder.add_node("datamodel_step", self.datamodel_agent.run)
        builder.add_node("generator_step", self.generator_agent.run)
        builder.add_node("validation_step", self.validation_agent.run)
        builder.add_node("governance_step", self.governance_agent.run)
        builder.add_node("audit_step", self.audit_agent.run)

        # Set entry point
        builder.set_entry_point("requirement_step")

        # Linear edges with conditional branching
        builder.add_edge("requirement_step", "discovery_step")
        builder.add_edge("discovery_step", "mapping_step")
        builder.add_edge("mapping_step", "decision_step")
        builder.add_edge("decision_step", "datamodel_step")
        builder.add_edge("datamodel_step", "generator_step")
        builder.add_edge("generator_step", "validation_step")
        builder.add_edge("validation_step", "governance_step")
        builder.add_edge("governance_step", "audit_step")
        builder.add_edge("audit_step", END)

        return builder.compile()

    async def execute_pipeline(self, initial_state: CDSWorkflowState) -> CDSWorkflowState:
        """Executes the complete multi-agent pipeline."""
        logger.info("Executing CDS Multi-Agent Workflow Pipeline")

        if self._graph is not None:
            try:
                result = await self._graph.ainvoke(initial_state)
                return result
            except Exception as e:
                logger.warning(f"LangGraph execution encountered error: {e}. Executing procedural pipeline.")

        # Resilient procedural fallback
        state = initial_state
        state = await self.requirement_agent.run(state)
        state = await self.discovery_agent.run(state)
        state = await self.mapping_agent.run(state)
        state = await self.decision_agent.run(state)
        state = await self.datamodel_agent.run(state)
        state = await self.generator_agent.run(state)
        state = await self.validation_agent.run(state)
        state = await self.governance_agent.run(state)
        state = await self.audit_agent.run(state)
        return state
