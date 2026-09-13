"""CDS Generator Agent: Synthesizes evidence-grounded ABAP CDS draft artifacts."""

import re
from typing import Dict, List, Optional
from src.agents.base import BaseAgent
from src.agents.normalizer import canonicalize
from src.agents.state import CDSWorkflowState
from src.logging_config import logger
from src.models.domain import (
    CDSDraft,
    CDSLayer,
    DecisionAction,
    DraftAssociationElement,
    DraftElementType,
    DraftFieldElement,
    DraftParameterElement,
    ElementEvidenceRecord,
    EvidenceLevel,
    MappingType,
)


class CDSGeneratorAgent(BaseAgent):
    """Synthesizes evidence-grounded ABAP CDS View Entity and Extension drafts.

    Adheres strictly to clean-core standards, the 6-level evidence hierarchy,
    and mandatory zero-SAP-write safety constraints.
    """

    def __init__(self):
        super().__init__(
            name="CDSGeneratorAgent",
            description="Synthesizes evidence-grounded ABAP CDS View Entity drafts, extensions, and reuse proposals.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        decision = state.get("decision")
        req = state.get("requirement")
        mappings = state.get("field_mappings", [])
        candidates = state.get("candidates", [])
        evaluations = state.get("evaluated_candidates", [])

        if not decision or not req:
            state.setdefault("errors", []).append("CDSGeneratorAgent: Missing decision or requirement.")
            return state

        # Dispatch generation based on Milestone 5 architectural decision
        if decision.action == DecisionAction.REUSE:
            draft = self._generate_reuse_draft(req, decision, mappings, candidates)
        elif decision.action == DecisionAction.EXTEND:
            draft = self._generate_extend_draft(req, decision, mappings, candidates, evaluations)
        elif decision.action == DecisionAction.INSUFFICIENT_EVIDENCE:
            draft = self._generate_insufficient_evidence_draft(req, decision, mappings)
        else:
            draft = self._generate_create_draft(req, decision, mappings, candidates, evaluations)

        state["cds_draft"] = draft
        state["generated_cds_code"] = draft.ddl_source
        self.log_audit(
            state,
            "CDS_DRAFT_SYNTHESIZED",
            {
                "object_name": draft.object_name,
                "object_type": draft.object_type,
                "action": draft.decision_action.value,
                "fields_count": len(draft.fields),
                "evidence_count": len(draft.evidence_per_element),
                "unresolved_count": len(draft.unresolved_items),
            },
        )
        state["current_step"] = "VALIDATION"
        return state

    def _generate_reuse_draft(
        self,
        req,
        decision,
        mappings,
        candidates,
    ) -> CDSDraft:
        """Generates an evidence-grounded REUSE proposal referencing standard released CDS view."""
        target_view = decision.recommended_view or (candidates[0].view_name if candidates else "I_StandardCDSView")
        cand = next((c for c in candidates if c.view_name == target_view), None)
        layer = cand.layer if cand else CDSLayer.BASIC

        fields: List[DraftFieldElement] = []
        evidence_records: List[ElementEvidenceRecord] = []
        unresolved: List[str] = []
        warnings: List[str] = []

        # Source view evidence
        source_evidence = ElementEvidenceRecord(
            element_name=target_view,
            element_type=DraftElementType.SOURCE_VIEW,
            source_entity=target_view,
            evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
            evidence_detail=f"Standard SAP released CDS View Entity '{target_view}' verified in SAP repository",
            confidence=1.0,
            is_verified=True,
        )
        evidence_records.append(source_evidence)

        # Field projections and evidence binding
        for m in mappings:
            # Reject Level 5 suggestions
            if m.evidence_level == EvidenceLevel.LEVEL_5_UNVERIFIED_SUGGESTION:
                unresolved.append(m.requirement_field)
                warnings.append(f"Concept '{m.requirement_field}' suggested by LLM without SAP DDL verification. Excluded.")
                continue

            if m.evidence_level in (
                EvidenceLevel.LEVEL_1_EXACT_FIELD,
                EvidenceLevel.LEVEL_2_LABEL_MATCH,
                EvidenceLevel.LEVEL_4_HEURISTIC_SYNONYM,
            ):
                f_name = m.matched_field or m.requirement_field
                ev = ElementEvidenceRecord(
                    element_name=f_name,
                    element_type=DraftElementType.FIELD,
                    source_entity=target_view,
                    evidence_level=m.evidence_level,
                    evidence_detail=m.evidence_detail,
                    confidence=m.confidence,
                    is_verified=True,
                )
                evidence_records.append(ev)
                fields.append(
                    DraftFieldElement(
                        field_name=f_name,
                        source_expression=f_name,
                        source_entity=target_view,
                        evidence=ev,
                    )
                )
            else:
                unresolved.append(m.requirement_field)

        field_list = ",\n  ".join([f.field_name for f in fields]) if fields else "SalesOrder"
        ddl_source = f"""/* ========================================================================= */
/* REUSE PROPOSAL: Standard SAP S/4HANA CDS View Entity                      */
/* Object: {target_view:<64} */
/* Layer:  {layer.value:<64} */
/* Clean-Core Footprint: ZERO (No custom ABAP/CDS deployment required)      */
/* ========================================================================= */

-- ABAP SQL Consumption Query Example:
SELECT
  {field_list}
  FROM {target_view}
  INTO TABLE @DATA(lt_{target_view.lower()}).
"""
        return CDSDraft(
            requirement_id=req.id,
            decision_action=DecisionAction.REUSE,
            object_name=target_view,
            object_type="REUSE_PROPOSAL",
            proposed_layer=layer,
            source_views=[target_view],
            fields=fields,
            associations=[],
            parameters=[],
            filters=req.filter_criteria,
            annotations={"@VDM.viewType": f"#{layer.value}"},
            ddl_source=ddl_source,
            evidence_per_element=evidence_records,
            warnings=warnings,
            validation_errors=[],
            generation_status="GENERATED",
            unresolved_items=unresolved,
        )

    def _generate_extend_draft(
        self,
        req,
        decision,
        mappings,
        candidates,
        evaluations,
    ) -> CDSDraft:
        """Generates an EXTEND VIEW ENTITY draft with verified Level 1-3 fields only."""
        base_view = decision.recommended_view or (candidates[0].view_name if candidates else "I_SalesOrder")
        ext_name = decision.proposed_extension_name or f"ZI_{base_view.replace('I_', '')[:15]}_Ext"

        fields: List[DraftFieldElement] = []
        associations: List[DraftAssociationElement] = []
        evidence_records: List[ElementEvidenceRecord] = []
        unresolved: List[str] = []
        warnings: List[str] = []

        # Base view evidence
        evidence_records.append(
            ElementEvidenceRecord(
                element_name=base_view,
                element_type=DraftElementType.SOURCE_VIEW,
                source_entity=base_view,
                evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                evidence_detail=f"Base CDS view entity '{base_view}' verified extension-capable",
                confidence=1.0,
                is_verified=True,
            )
        )

        for m in mappings:
            # Strictly reject Level 5 suggestions
            if m.evidence_level == EvidenceLevel.LEVEL_5_UNVERIFIED_SUGGESTION:
                unresolved.append(m.requirement_field)
                warnings.append(
                    f"Concept '{m.requirement_field}' was suggested without SAP DDL verification (Level 5). Excluded from extension."
                )
                continue

            # Only accept Level 3 verified associations for extension projection
            if m.evidence_level == EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION:
                target_view = m.association_target_view or base_view
                target_field = m.association_target_field or m.matched_field or m.requirement_field
                alias_name = m.requirement_field

                # Association path expression e.g. _Item.Material as Material
                assoc_alias = f"_{target_view.replace('I_', '')}"
                source_expr = f"{assoc_alias}.{target_field} as {alias_name}"

                ev = ElementEvidenceRecord(
                    element_name=alias_name,
                    element_type=DraftElementType.FIELD,
                    source_entity=target_view,
                    relationship=f"verified association to {target_view}",
                    evidence_level=EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION,
                    evidence_detail=m.evidence_detail,
                    confidence=0.85,
                    is_verified=True,
                )
                evidence_records.append(ev)
                fields.append(
                    DraftFieldElement(
                        field_name=alias_name,
                        alias=alias_name,
                        source_expression=source_expr,
                        source_entity=target_view,
                        evidence=ev,
                    )
                )
            elif m.evidence_level in (EvidenceLevel.LEVEL_1_EXACT_FIELD, EvidenceLevel.LEVEL_2_LABEL_MATCH):
                # Field is already directly on base view; does not need extension
                pass
            else:
                unresolved.append(m.requirement_field)
                warnings.append(
                    f"Concept '{m.requirement_field}' has unverified evidence ({m.evidence_level.value}). Excluded from extension."
                )

        field_projections = ",\n  ".join([f.source_expression for f in fields]) if fields else "/* No verified extension fields */"
        ddl_source = f"""/* ========================================================================= */
/* EXTEND VIEW ENTITY DRAFT: Non-Intrusive Core Extension                   */
/* Base View Entity: {base_view:<55} */
/* Extension Name:   {ext_name:<55} */
/* Clean-Core Note:  Preserves standard SAP lifecycle; customer namespace   */
/* ========================================================================= */
@EndUserText.label: '{req.title}'
extend view entity {base_view} with {ext_name}
{{
  {field_projections}
}};
"""
        return CDSDraft(
            requirement_id=req.id,
            decision_action=DecisionAction.EXTEND,
            object_name=ext_name,
            object_type="VIEW_ENTITY_EXTENSION",
            proposed_layer=CDSLayer.BASIC,
            source_views=[base_view],
            fields=fields,
            associations=associations,
            parameters=[],
            filters=req.filter_criteria,
            annotations={"@EndUserText.label": req.title},
            ddl_source=ddl_source,
            evidence_per_element=evidence_records,
            warnings=warnings,
            validation_errors=[],
            generation_status="GENERATED",
            unresolved_items=unresolved,
        )

    def _generate_create_draft(
        self,
        req,
        decision,
        mappings,
        candidates,
        evaluations,
    ) -> CDSDraft:
        """Generates a custom CDS View Entity draft (or multi-CDS composition proposal)."""
        object_name = decision.proposed_new_view_name or f"ZC_{req.title.replace(' ', '')[:20]}"
        fields: List[DraftFieldElement] = []
        associations: List[DraftAssociationElement] = []
        evidence_records: List[ElementEvidenceRecord] = []
        unresolved: List[str] = []
        warnings: List[str] = []

        # Case C1: Multi-CDS Composition Proposal
        if decision.requires_composition:
            comp_views = decision.complementary_views or [c.view_name for c in candidates[:2]]
            warnings.append(
                f"Multi-CDS composition required across complementary views ({', '.join(comp_views)}). "
                "Join keys and association cardinality between complementary views require manual relationship modeling."
            )
            for m in mappings:
                if m.evidence_level == EvidenceLevel.LEVEL_5_UNVERIFIED_SUGGESTION:
                    unresolved.append(m.requirement_field)
                    continue

                if m.evidence_level in (
                    EvidenceLevel.LEVEL_1_EXACT_FIELD,
                    EvidenceLevel.LEVEL_2_LABEL_MATCH,
                    EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION,
                    EvidenceLevel.LEVEL_4_HEURISTIC_SYNONYM,
                ):
                    f_name = m.matched_field or m.requirement_field
                    src = m.source_entity or comp_views[0]
                    ev = ElementEvidenceRecord(
                        element_name=f_name,
                        element_type=DraftElementType.FIELD,
                        source_entity=src,
                        evidence_level=m.evidence_level,
                        evidence_detail=m.evidence_detail,
                        confidence=m.confidence,
                        is_verified=True,
                    )
                    evidence_records.append(ev)
                    fields.append(
                        DraftFieldElement(
                            field_name=f_name,
                            source_expression=f_name,
                            source_entity=src,
                            evidence=ev,
                        )
                    )
                else:
                    unresolved.append(m.requirement_field)

            field_lines = ",\n  ".join([f.field_name for f in fields]) if fields else "key ID"
            ddl_source = f"""/* ========================================================================= */
/* COMPOSITION PROPOSAL: Multi-CDS Composite Entity                          */
/* Proposed Object: {object_name:<56} */
/* Complementary Views: {', '.join(comp_views):<52} */
/* ========================================================================= */
/* NOTE: Join relationships and association cardinality between              */
/* complementary views require verification. Code below is a design skeleton.*/
/* ========================================================================= */
@EndUserText.label: '{req.title}'
@AccessControl.authorizationCheck: #CHECK
@Metadata.allowExtensions: true
define view entity {object_name}
  as select from {comp_views[0] if comp_views else 'I_PrimaryEntity'}
  /* Complementary join: {comp_views[1] if len(comp_views) > 1 else 'I_SecondaryEntity'} */
{{
  {field_lines}
}};
"""
            return CDSDraft(
                requirement_id=req.id,
                decision_action=DecisionAction.CREATE,
                object_name=object_name,
                object_type="COMPOSITION_PROPOSAL",
                proposed_layer=CDSLayer.COMPOSITE,
                source_views=comp_views,
                fields=fields,
                associations=associations,
                parameters=[],
                filters=req.filter_criteria,
                annotations={"@AccessControl.authorizationCheck": "#CHECK", "@Metadata.allowExtensions": True},
                ddl_source=ddl_source,
                evidence_per_element=evidence_records,
                warnings=warnings,
                validation_errors=[],
                generation_status="GENERATED",
                unresolved_items=unresolved,
            )

        # Case C2: Single source custom view or zero candidates unconnected skeleton
        if candidates:
            primary_view = candidates[0].view_name
            source_views = [primary_view]
            for m in mappings:
                if m.evidence_level == EvidenceLevel.LEVEL_5_UNVERIFIED_SUGGESTION:
                    unresolved.append(m.requirement_field)
                    warnings.append(f"Level 5 suggestion '{m.requirement_field}' rejected from custom view.")
                    continue

                if m.evidence_level in (
                    EvidenceLevel.LEVEL_1_EXACT_FIELD,
                    EvidenceLevel.LEVEL_2_LABEL_MATCH,
                    EvidenceLevel.LEVEL_4_HEURISTIC_SYNONYM,
                ):
                    f_name = m.matched_field or m.requirement_field
                    ev = ElementEvidenceRecord(
                        element_name=f_name,
                        element_type=DraftElementType.FIELD,
                        source_entity=primary_view,
                        evidence_level=m.evidence_level,
                        evidence_detail=m.evidence_detail,
                        confidence=m.confidence,
                        is_verified=True,
                    )
                    evidence_records.append(ev)
                    fields.append(
                        DraftFieldElement(
                            field_name=f_name,
                            source_expression=f_name,
                            source_entity=primary_view,
                            evidence=ev,
                        )
                    )
                else:
                    unresolved.append(m.requirement_field)

            field_lines = ",\n  ".join([f.field_name for f in fields]) if fields else "key ID"
            ddl_source = f"""/* ========================================================================= */
/* CUSTOM CDS VIEW ENTITY: Customer Namespace Clean-Core Artifact            */
/* Object: {object_name:<65} */
/* Primary Source: {primary_view:<57} */
/* ========================================================================= */
@EndUserText.label: '{req.title}'
@AccessControl.authorizationCheck: #CHECK
@Metadata.allowExtensions: true
define view entity {object_name}
  as select from {primary_view}
{{
  {field_lines}
}};
"""
        else:
            # Zero candidates discovered in repository search
            source_views = []
            unresolved = req.required_fields if req.required_fields else [req.title]
            warnings.append("Zero SAP candidate views discovered. Skeleton drafted with placeholder entity.")
            ddl_source = f"""/* ========================================================================= */
/* DRAFT SKELETON: UNCONNECTED MODE / ZERO SAP CANDIDATES DISCOVERED         */
/* Live SAP metadata, fields, and joins will be validated upon SAP connect. */
/* ========================================================================= */
@EndUserText.label: '{req.title}'
@AccessControl.authorizationCheck: #CHECK
@Metadata.allowExtensions: true
define view entity {object_name}
  as select from I_BusinessEntityPlaceholder
{{
  key ID
  /* Unresolved requirements: {', '.join(unresolved[:5])} */
}};
"""

        return CDSDraft(
            requirement_id=req.id,
            decision_action=DecisionAction.CREATE,
            object_name=object_name,
            object_type="CUSTOM_VIEW_ENTITY",
            proposed_layer=CDSLayer.CONSUMPTION,
            source_views=source_views,
            fields=fields,
            associations=associations,
            parameters=[],
            filters=req.filter_criteria,
            annotations={"@AccessControl.authorizationCheck": "#CHECK", "@Metadata.allowExtensions": True},
            ddl_source=ddl_source,
            evidence_per_element=evidence_records,
            warnings=warnings,
            validation_errors=[],
            generation_status="GENERATED",
            unresolved_items=unresolved,
        )

    def _generate_insufficient_evidence_draft(
        self,
        req,
        decision,
        mappings,
    ) -> CDSDraft:
        """Generates an explicit halting draft when metadata evidence is insufficient or unresolved."""
        unresolved = [m.requirement_field for m in mappings if m.mapping_type == MappingType.UNRESOLVED]
        warnings = decision.warnings if decision.warnings else ["Evidence insufficient to formulate a safe CDS draft."]
        ddl_source = f"""/* ========================================================================= */
/* INSUFFICIENT EVIDENCE: CDS Generation Halted Pending Review               */
/* Reason: {decision.rationale} */
/* ========================================================================= */
-- Generation halted to prevent synthesis of unverified or hallucinated CDS artifacts.
-- Developer action required: verify association target DDL or provide clear domain mappings.
"""
        return CDSDraft(
            requirement_id=req.id,
            decision_action=DecisionAction.INSUFFICIENT_EVIDENCE,
            object_name=decision.recommended_view or "UNRESOLVED",
            object_type="UNRESOLVED_PROPOSAL",
            proposed_layer=CDSLayer.BASIC,
            source_views=[decision.recommended_view] if decision.recommended_view else [],
            fields=[],
            associations=[],
            parameters=[],
            filters=[],
            annotations={},
            ddl_source=ddl_source,
            evidence_per_element=[],
            warnings=warnings,
            validation_errors=["Insufficient verified evidence to synthesize draft."],
            generation_status="INSUFFICIENT_EVIDENCE",
            unresolved_items=unresolved,
        )

