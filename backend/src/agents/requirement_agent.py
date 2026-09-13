from src.agents.base import BaseAgent
from src.agents.normalizer import extract_structured_requirement
from src.agents.state import CDSWorkflowState
from src.models.domain import BusinessRequirement, StructuredRequirement, TargetUseCase


class RequirementAgent(BaseAgent):
    """Parses natural-language user requests into structured business requirements.

    Extracts business entities, dimensions, measures, attributes, and filter criteria.
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

        # Dynamically extract structured business concepts from requirement title and description
        structured = extract_structured_requirement(
            text=req.description,
            title=req.title,
            explicit_entities=req.required_entities,
            explicit_fields=req.required_fields,
            explicit_filters=req.filter_criteria,
        )

        state["structured_requirement"] = structured

        # If required_entities or required_fields were initially empty, update them from extracted concepts
        if not req.required_entities and structured.dimensions:
            req.required_entities = structured.dimensions[:3]  # Focus discovery on primary entities
        if not req.required_fields and structured.all_requested_concepts:
            req.required_fields = structured.all_requested_concepts

        self.log_audit(
            state,
            "REQUIREMENT_ANALYZED",
            {
                "requirement_id": req.id,
                "domain": req.business_domain,
                "dimensions": structured.dimensions,
                "measures": structured.measures,
                "attributes": structured.attributes,
                "all_concepts_count": len(structured.all_requested_concepts),
            },
        )
        state["current_step"] = "DISCOVERY"
        return state

