"""Impact & Audit Agent: Calculates change impact and finalizes audit ledger entries."""

from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState


class ImpactAuditAgent(BaseAgent):
    """Calculates downstream blast radius, dependency risks, and seals the pipeline audit log."""

    def __init__(self):
        super().__init__(
            name="ImpactAuditAgent",
            description="Evaluates architectural impact, dependency risks, and writes final audit entries.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        decision = state.get("decision")
        req = state.get("requirement")

        # Determine impact score
        impact_level = "LOW"
        if decision:
            if decision.action.value == "CREATE":
                impact_level = "LOW"  # Net-new object, no downstream breakage
            elif decision.action.value == "EXTEND":
                impact_level = "MEDIUM"  # Appending fields to existing standard view
            elif decision.action.value == "REUSE":
                impact_level = "ZERO"

        self.log_audit(
            state,
            "PIPELINE_FINALIZED",
            {
                "requirement_title": req.title if req else "Unknown",
                "recommended_action": decision.action.value if decision else "UNKNOWN",
                "impact_level": impact_level,
                "total_audit_events": len(state.get("audit_logs", [])),
            },
        )
        state["current_step"] = "COMPLETED"
        return state
