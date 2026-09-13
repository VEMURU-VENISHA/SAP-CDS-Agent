"""Requirement Agent: Parses and structures natural-language SAP data requirements."""

from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import BusinessRequirement, TargetUseCase


class RequirementAgent(BaseAgent):
    """Parses natural-language user requests into structured business requirements.

    Extracts business entities (e.g. SalesOrder), target fields, filters, and use-case type.
    """

    def __init__(self):
        super().__init__(
            name="RequirementAgent",
            description="Parses natural language requirements into structured domain entities and fields.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        req = state.get("requirement")
        if not req:
            state.setdefault("errors", []).append("RequirementAgent: No requirement supplied in state.")
            return state

        # TODO (Future Milestone): Integrate LLM reasoning prompt to extract fine-grained semantic intent
        # For Milestone 1 skeleton, ensure required structure exists and log audit step
        self.log_audit(
            state,
            "REQUIREMENT_ANALYZED",
            {
                "requirement_id": req.id,
                "domain": req.business_domain,
                "entities_count": len(req.required_entities),
                "fields_count": len(req.required_fields),
            },
        )
        state["current_step"] = "DISCOVERY"
        return state
