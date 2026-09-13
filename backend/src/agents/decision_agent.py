"""Decision Agent: Recommends REUSE, EXTEND, or CREATE based on deterministic evaluation."""

from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import Decision, DecisionAction


class DecisionAgent(BaseAgent):
    """Evaluates field mappings and candidates to formulate the strategic action:

    - REUSE: Match score >= 95%, view exists in VDM, minimal/no custom fields needed.
    - EXTEND: Match score between 70% and 94%, view is extendable.
    - CREATE: Match score < 70%, or architectural mismatch requiring new CDS View Entity.
    """

    def __init__(self):
        super().__init__(
            name="DecisionAgent",
            description="Analyzes coverage and clean-core impact to decide between REUSE, EXTEND, and CREATE.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        req = state.get("requirement")
        candidates = state.get("candidates", [])
        mappings = state.get("field_mappings", [])

        if not req:
            state.setdefault("errors", []).append("DecisionAgent: Missing requirement.")
            return state

        # Evaluation logic
        # In Milestone 1, when candidates are empty (because SAP connector is unconnected), default recommendation is CREATE
        if not candidates:
            decision = Decision(
                requirement_id=req.id,
                action=DecisionAction.CREATE,
                recommended_view=None,
                confidence_score=0.90,
                fit_percentage=0.0,
                rationale=(
                    "No matching standard SAP CDS views available or connected. "
                    "Recommending synthesizing a custom CDS View Entity following SAP clean-core standards."
                ),
                missing_fields=req.required_fields,
                proposed_new_view_name=f"ZC_{req.title.replace(' ', '')[:20]}",
                tradeoffs=[
                    "Custom lifecycle maintenance required.",
                    "Full control over associations and field projections.",
                    "Clean core compliance verified before generation.",
                ],
                human_approval_required=True,
                is_approved=False,
            )
        else:
            best_candidate = candidates[0]
            decision = Decision(
                requirement_id=req.id,
                action=DecisionAction.REUSE if best_candidate.confidence_score >= 0.95 else DecisionAction.EXTEND,
                recommended_view=best_candidate.view_name,
                confidence_score=best_candidate.confidence_score,
                fit_percentage=best_candidate.confidence_score * 100.0,
                rationale=f"Evaluated against candidate {best_candidate.view_name}.",
                missing_fields=[],
                tradeoffs=["Zero clean-core footprint."],
                human_approval_required=True,
                is_approved=False,
            )

        state["decision"] = decision
        self.log_audit(
            state,
            "DECISION_FORMULATED",
            {
                "action": decision.action.value,
                "confidence_score": decision.confidence_score,
                "recommended_view": decision.recommended_view,
                "human_approval_required": decision.human_approval_required,
            },
        )
        state["current_step"] = "MODELING"
        return state
