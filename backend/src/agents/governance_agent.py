"""Security & Governance Agent: Enforces human-in-the-loop approval gates and Transport checks."""

from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import DeploymentRequest, DeploymentStatus


class SecurityGovernanceAgent(BaseAgent):
    """Enforces enterprise security, role-based governance, and human approval gates.

    Strict Rule: No automated deployment/activation occurs without explicit human sign-off.
    """

    def __init__(self):
        super().__init__(
            name="SecurityGovernanceAgent",
            description="Enforces human-in-the-loop sign-off, transport assignment, and compliance gating.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        decision = state.get("decision")
        validation = state.get("validation_result")
        is_approved = state.get("is_human_approved", False)

        if not decision:
            state.setdefault("errors", []).append("SecurityGovernanceAgent: Missing decision.")
            return state

        # Prepare deployment request structure
        dep_status = DeploymentStatus.APPROVED if is_approved else DeploymentStatus.PENDING_APPROVAL
        target_name = decision.proposed_new_view_name or decision.recommended_view or "Z_CDS_OBJECT"

        dep_request = DeploymentRequest(
            object_name=target_name,
            object_type="CDS_VIEW_ENTITY",
            target_system="SAP DEV - Client 100",
            package="Z_CDS_PLATFORM",
            transport_request="TR_REQUIRED",
            requester="ai_platform",
            approver=decision.approved_by if is_approved else None,
            status=dep_status,
        )

        state["deployment_request"] = dep_request
        self.log_audit(
            state,
            "GOVERNANCE_GATE_EVALUATED",
            {
                "status": dep_status.value,
                "is_human_approved": is_approved,
                "target_object": target_name,
            },
        )
        state["current_step"] = "AUDIT"
        return state
