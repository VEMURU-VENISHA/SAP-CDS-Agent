"""Data Model Agent: Synthesizes relational data models, associations, and cardinalities."""

from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import CDSLayer, DataModel, DataModelAssociation, DataModelEntity, DecisionAction


class DataModelAgent(BaseAgent):
    """Synthesizes CDS entity relationships, associations, cardinalities, and join layouts.

    Constructs data models suitable for visual diagramming (React Flow) and code generation.
    """

    def __init__(self):
        super().__init__(
            name="DataModelAgent",
            description="Designs CDS entity structures, associations, cardinality, and visual layout coordinates.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        decision = state.get("decision")
        req = state.get("requirement")

        if not decision or not req:
            state.setdefault("errors", []).append("DataModelAgent: Missing decision or requirement.")
            return state

        # If decision is REUSE, no new data model generation is required
        if decision.action == DecisionAction.REUSE:
            self.log_audit(state, "DATA_MODEL_SKIPPED", {"reason": "Action is REUSE, existing model reused."})
            state["current_step"] = "GOVERNANCE"
            return state

        # Build conceptual data model for EXTEND or CREATE
        root_name = decision.proposed_new_view_name or f"ZC_{req.title.replace(' ', '')[:16]}"
        model = DataModel(
            name=root_name,
            root_entity=root_name,
            entities=[
                DataModelEntity(
                    name=root_name,
                    layer=CDSLayer.CONSUMPTION,
                    fields=req.required_fields,
                    key_fields=[req.required_fields[0]] if req.required_fields else ["ID"],
                )
            ],
            associations=[],
            visual_layout={
                "nodes": [
                    {
                        "id": root_name,
                        "type": "cdsEntityNode",
                        "position": {"x": 250, "y": 100},
                        "data": {"label": root_name, "layer": "CONSUMPTION", "fields": req.required_fields},
                    }
                ],
                "edges": [],
            },
        )

        state["data_model"] = model
        self.log_audit(state, "DATA_MODEL_SYNTHESIZED", {"model_name": model.name, "root_entity": model.root_entity})
        state["current_step"] = "GENERATION"
        return state
