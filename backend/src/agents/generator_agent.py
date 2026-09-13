"""CDS Generator Agent: Generates clean-core ABAP CDS View Entity DDL code."""

from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import DecisionAction


class CDSGeneratorAgent(BaseAgent):
    """Synthesizes compliant ABAP CDS View Entity DDL code (S/4HANA 2023 release style).

    Supports:
    - CDS View Entities (`define view entity ...`)
    - CDS View Entity Extensions (`extend view entity ... with ...`)
    """

    def __init__(self):
        super().__init__(
            name="CDSGeneratorAgent",
            description="Generates standard ABAP CDS View Entity source code following clean-core guidelines.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        decision = state.get("decision")
        req = state.get("requirement")

        if not decision or not req:
            state.setdefault("errors", []).append("CDSGeneratorAgent: Missing decision or requirement.")
            return state

        if decision.action == DecisionAction.REUSE:
            state["generated_cds_code"] = f"/* REUSE recommendation: Consumes standard view {decision.recommended_view} */"
            state["current_step"] = "VALIDATION"
            return state

        # Synthesize clean CDS DDL draft structure
        view_name = decision.proposed_new_view_name or "ZC_CustomCDSView"
        field_projections = "\n  ".join([f"{f}," for f in req.required_fields]) if req.required_fields else "ID,"

        # Determine base entity from requirement hints without claiming fake SAP existence
        if req.required_entities:
            entity_hint = req.required_entities[0].strip()
            base_entity = entity_hint if entity_hint.startswith("I_") else f"I_{entity_hint}"
        else:
            base_entity = "I_BusinessEntityPlaceholder"

        code_template = f"""/* ========================================================================= */
/* DRAFT SKELETON: Synthesized in UNCONNECTED mode                           */
/* Live SAP metadata, fields, and joins will be validated upon SAP connect. */
/* ========================================================================= */
@EndUserText.label: '{req.title}'
@AccessControl.authorizationCheck: #CHECK
@Metadata.allowExtensions: true
define view entity {view_name}
  as select from {base_entity}
{{
  {field_projections}
  /* Associations to be resolved via SAP Discovery Agent upon connection */
}}
"""
        state["generated_cds_code"] = code_template
        self.log_audit(
            state,
            "CDS_CODE_GENERATED",
            {"view_name": view_name, "code_length": len(code_template)},
        )
        state["current_step"] = "VALIDATION"
        return state
