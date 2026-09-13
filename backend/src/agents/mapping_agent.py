"""Semantic Mapping Agent: Maps requirement fields to candidate CDS view elements."""

from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import FieldMapping, MappingType


class SemanticMappingAgent(BaseAgent):
    """Maps user-requested business fields to attributes and associations in discovered CDS views."""

    def __init__(self):
        super().__init__(
            name="SemanticMappingAgent",
            description="Performs semantic matching between requested fields and SAP CDS view attributes.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        req = state.get("requirement")
        candidates = state.get("candidates", [])

        if not req:
            state.setdefault("errors", []).append("SemanticMappingAgent: Missing requirement.")
            return state

        mappings = []
        # TODO (Future Milestone): Implement vector similarity and LLM semantic matching against candidate available_fields
        # Milestone 1: initialize mapping slots for each requested field
        for field in req.required_fields:
            mappings.append(
                FieldMapping(
                    requirement_field=field,
                    matched_field=None,
                    mapping_type=MappingType.MISSING,
                    confidence=0.0,
                )
            )

        state["field_mappings"] = mappings
        self.log_audit(
            state,
            "SEMANTIC_MAPPING_EVALUATED",
            {"total_fields": len(mappings), "candidate_views_considered": len(candidates)},
        )
        state["current_step"] = "DECISION"
        return state
