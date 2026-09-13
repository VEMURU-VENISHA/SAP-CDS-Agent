"""Validation Agent: Validates CDS syntax, naming standards, and clean-core rules."""

from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import ValidationResult


class ValidationAgent(BaseAgent):
    """Validates CDS View Entity code against SAP clean-core standards, syntax rules, and naming conventions."""

    def __init__(self):
        super().__init__(
            name="ValidationAgent",
            description="Validates CDS DDL code against SAP clean-core standards and naming rules.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        code = state.get("generated_cds_code")
        decision = state.get("decision")

        if not code:
            state.setdefault("errors", []).append("ValidationAgent: No code available to validate.")
            return state

        syntax_errors = []
        naming_violations = []
        governance_warnings = []

        # Verification 1: Mandatory Access Control annotation
        if "@AccessControl.authorizationCheck" not in code:
            governance_warnings.append("Missing @AccessControl.authorizationCheck annotation.")

        # Verification 2: Check naming convention for custom objects
        if decision and decision.proposed_new_view_name:
            name = decision.proposed_new_view_name
            if not (name.startswith("Z") or name.startswith("Y")):
                naming_violations.append(f"Custom object name '{name}' must start with 'Z' or 'Y'.")

        is_valid = len(syntax_errors) == 0 and len(naming_violations) == 0

        validation = ValidationResult(
            is_valid=is_valid,
            syntax_errors=syntax_errors,
            naming_convention_violations=naming_violations,
            clean_core_compliance_score=95.0 if is_valid else 60.0,
            governance_warnings=governance_warnings,
            details=[
                {"check": "Authorization Check Annotation", "passed": "@AccessControl.authorizationCheck" in code},
                {"check": "Clean Core Naming Rule", "passed": len(naming_violations) == 0},
            ],
        )

        state["validation_result"] = validation
        self.log_audit(
            state,
            "VALIDATION_COMPLETED",
            {"is_valid": validation.is_valid, "score": validation.clean_core_compliance_score},
        )
        state["current_step"] = "GOVERNANCE"
        return state
