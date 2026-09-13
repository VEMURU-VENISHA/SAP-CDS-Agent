"""Decision Agent: Recommends REUSE, EXTEND, CREATE, or INSUFFICIENT_EVIDENCE based on deterministic evidence."""

from typing import List, Optional
from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.logging_config import logger
from src.models.domain import (
    CandidateEvaluation,
    Decision,
    DecisionAction,
    EvidenceLevel,
    MappingType,
)


class DecisionAgent(BaseAgent):
    """Evaluates field mappings and candidates to formulate a deterministic architectural decision:

    - REUSE: 100% of concepts satisfied directly with verified Level 1/2 metadata on standard VDM.
    - EXTEND: Base view is extendable, and missing concepts are demonstrably obtainable via verified Level 3 associations.
    - CREATE: Missing concepts lack verified extension points, view is not extendable, low coverage, or zero candidates.
    - INSUFFICIENT_EVIDENCE: Ambiguous metadata or unverified association target DDL halts the pipeline for human review.
    - Multi-CDS Composition: Detects when complementary candidates cover disjoint subsets of the requirement.
    """

    def __init__(self):
        super().__init__(
            name="DecisionAgent",
            description="Formulates deterministic REUSE, EXTEND, CREATE, or INSUFFICIENT_EVIDENCE decisions based on verified SAP evidence.",
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        req = state.get("requirement")
        structured = state.get("structured_requirement")
        evaluations: List[CandidateEvaluation] = state.get("evaluated_candidates", [])
        candidates = state.get("candidates", [])

        if not req:
            state.setdefault("errors", []).append("DecisionAgent: Missing requirement.")
            return state

        # Case 1: Zero SAP candidates returned (unconnected mode or 0 hits in repository search)
        if not candidates or not evaluations:
            all_concepts = (
                structured.all_requested_concepts
                if structured and structured.all_requested_concepts
                else (req.required_fields if req.required_fields else [req.title])
            )
            proposed_name = f"ZC_{req.title.replace(' ', '')[:20]}"
            decision = Decision(
                requirement_id=req.id,
                action=DecisionAction.CREATE,
                recommended_view=None,
                confidence_score=0.50,
                fit_percentage=0.0,
                rationale=(
                    "Zero SAP CDS candidates discovered in repository search. "
                    "Cannot verify standard SAP S/4HANA VDM view reuse. "
                    f"Recommending custom CDS View Entity draft '{proposed_name}' in customer namespace."
                ),
                missing_fields=all_concepts,
                proposed_new_view_name=proposed_name,
                requires_composition=False,
                complementary_views=[],
                evaluated_candidates=[],
                structured_requirement=structured,
                evidence_summary=["Zero candidate views returned from SAP repository search."],
                warnings=["No existing standard VDM view matched the requirement criteria."],
                tradeoffs=[
                    "Custom lifecycle maintenance required.",
                    "Full control over associations and field projections.",
                    "Clean-core compliance verified prior to deployment.",
                ],
                human_approval_required=True,
                is_approved=False,
            )
            state["decision"] = decision
            self._log_and_advance(state, decision)
            return state

        # Case 2: Candidates evaluated against 6-level evidence hierarchy
        best_ev = evaluations[0]
        best_cand = best_ev.candidate
        breakdown = best_ev.scoring_breakdown

        direct_count = int(breakdown.get("direct_matches_count", 0))
        extension_count = int(breakdown.get("extension_matches_count", 0))
        missing_count = int(breakdown.get("missing_count", 0))
        unresolved_count = int(breakdown.get("unresolved_count", 0))

        all_concepts = (
            structured.all_requested_concepts
            if structured and structured.all_requested_concepts
            else (req.required_fields if req.required_fields else [req.title])
        )
        total_concepts = max(1, len(all_concepts))

        # Check A: INSUFFICIENT_EVIDENCE
        # If any concept mapping is UNRESOLVED (e.g. association target DDL failed retrieval)
        if unresolved_count > 0:
            unresolved_mappings = [
                m for m in best_ev.field_mappings if m.mapping_type == MappingType.UNRESOLVED
            ]
            unresolved_details = [m.evidence_detail for m in unresolved_mappings]
            decision = Decision(
                requirement_id=req.id,
                action=DecisionAction.INSUFFICIENT_EVIDENCE,
                recommended_view=best_cand.view_name,
                confidence_score=0.20,
                fit_percentage=best_ev.coverage_percentage,
                rationale=(
                    f"Association target DDL verification failed on candidate '{best_cand.view_name}'. "
                    f"{unresolved_count} concept(s) remain UNRESOLVED because target metadata could not be verified via SAP ADT. "
                    "Execution halted to avoid unverified architectural recommendations. Developer review required."
                ),
                missing_fields=best_ev.missing_concepts,
                requires_composition=False,
                complementary_views=[],
                evaluated_candidates=evaluations,
                structured_requirement=structured,
                evidence_summary=[
                    f"Candidate '{best_cand.view_name}' evaluated with {unresolved_count} unresolved target DDL error(s)."
                ],
                warnings=unresolved_details,
                tradeoffs=[
                    "Halting pipeline prevents generating hallucinated or unverified CDS artifacts.",
                    "Requires network or authorization verification for ADT DDL endpoint.",
                ],
                human_approval_required=True,
                is_approved=False,
            )
            state["decision"] = decision
            self._log_and_advance(state, decision)
            return state

        # Check B: REUSE
        # 100% of requested concepts are satisfied with Level 1/2/4 direct evidence on base view
        if direct_count == total_concepts and missing_count == 0 and extension_count == 0:
            decision = Decision(
                requirement_id=req.id,
                action=DecisionAction.REUSE,
                recommended_view=best_cand.view_name,
                confidence_score=0.98,
                fit_percentage=100.0,
                rationale=(
                    f"Standard SAP CDS View Entity '{best_cand.view_name}' directly satisfies 100% of requested concepts "
                    f"({direct_count}/{total_concepts}) with verified metadata evidence. "
                    f"Layer: {best_cand.layer.value}, Release Status: {best_cand.release_status}. "
                    "Recommending direct reuse with zero clean-core footprint."
                ),
                missing_fields=[],
                requires_composition=False,
                complementary_views=[],
                evaluated_candidates=evaluations,
                structured_requirement=structured,
                evidence_summary=[
                    f"All {total_concepts} concept(s) directly verified on standard CDS View Entity '{best_cand.view_name}'.",
                    f"View Entity layer '{best_cand.layer.value}' is released for consumption/analytical reporting.",
                ],
                warnings=[],
                tradeoffs=[
                    "Zero clean-core footprint.",
                    "Preserves standard SAP lifecycle management.",
                    "Zero maintenance overhead for custom CDS code.",
                ],
                human_approval_required=True,
                is_approved=False,
            )
            state["decision"] = decision
            self._log_and_advance(state, decision)
            return state

        # Check C: EXTEND
        # Candidate is extendable, and missing concepts are verified obtainable via verified association
        if best_ev.is_extension_viable:
            obtainable_fields = [
                m.requirement_field
                for m in best_ev.field_mappings
                if m.evidence_level == EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION
            ]
            ext_name = f"ZI_{best_cand.view_name.replace('I_', '')[:15]}_Ext"
            decision = Decision(
                requirement_id=req.id,
                action=DecisionAction.EXTEND,
                recommended_view=best_cand.view_name,
                confidence_score=0.90,
                fit_percentage=round((direct_count / total_concepts) * 100.0, 1),
                rationale=(
                    f"Base CDS view '{best_cand.view_name}' is extension-capable (is_extendable=True) and directly satisfies "
                    f"{direct_count}/{total_concepts} concepts. Missing concept(s) {obtainable_fields} are demonstrably obtainable "
                    f"via verified association target DDL. Recommending non-intrusive CDS View Entity Extension '{ext_name}'."
                ),
                missing_fields=obtainable_fields,
                proposed_extension_name=ext_name,
                requires_composition=False,
                complementary_views=[],
                evaluated_candidates=evaluations,
                structured_requirement=structured,
                evidence_summary=[
                    f"Base CDS '{best_cand.view_name}' verified extension-capable.",
                    f"Concept(s) {obtainable_fields} verified on association targets via SAP ADT DDL endpoint.",
                ],
                warnings=[],
                tradeoffs=[
                    "Non-intrusive extension preserves standard SAP core view entity.",
                    "Minimal clean-core footprint under customer namespace.",
                    "Customer fields isolated to extension artifact.",
                ],
                human_approval_required=True,
                is_approved=False,
            )
            state["decision"] = decision
            self._log_and_advance(state, decision)
            return state

        # Check D: Multi-CDS Composition Detection (Rule 5)
        # Check if complementary candidates cover disjoint subsets of the requested concepts
        complementary_found = False
        comp_views: List[str] = []
        if len(evaluations) > 1:
            req_set = set(canonicalize_list(all_concepts))
            best_set = set(canonicalize_list(best_ev.matched_concepts))
            missing_set = req_set - best_set

            for other_ev in evaluations[1:]:
                other_set = set(canonicalize_list(other_ev.matched_concepts))
                # If other candidate covers concepts that the best candidate is missing
                if other_set & missing_set:
                    combined_set = best_set | other_set
                    if len(combined_set) == len(req_set):
                        complementary_found = True
                        comp_views = [best_cand.view_name, other_ev.candidate.view_name]
                        break

        if complementary_found:
            proposed_name = f"ZC_{req.title.replace(' ', '')[:20]}"
            decision = Decision(
                requirement_id=req.id,
                action=DecisionAction.CREATE,
                recommended_view=None,
                confidence_score=0.85,
                fit_percentage=best_ev.coverage_percentage,
                rationale=(
                    f"No single candidate satisfies the requirement; composition across complementary views "
                    f"('{comp_views[0]}', '{comp_views[1]}') is required to fulfill all requested concepts. "
                    f"Recommending custom composite CDS View Entity '{proposed_name}'."
                ),
                missing_fields=best_ev.missing_concepts,
                proposed_new_view_name=proposed_name,
                requires_composition=True,
                complementary_views=comp_views,
                evaluated_candidates=evaluations,
                structured_requirement=structured,
                evidence_summary=[
                    f"Candidate '{comp_views[0]}' satisfies: {best_ev.matched_concepts}.",
                    f"Candidate '{comp_views[1]}' provides complementary fields covering remaining requirements.",
                ],
                warnings=["Multi-CDS composition required: join/association modeling needed between complementary views."],
                tradeoffs=[
                    "Combines multiple standard CDS views without modifying core.",
                    "Clean-core compliant composite consumption entity in customer namespace.",
                    "Requires join or association modeling between complementary views.",
                ],
                human_approval_required=True,
                is_approved=False,
            )
            state["decision"] = decision
            self._log_and_advance(state, decision)
            return state

        # Check E: CREATE (Coverage < 70%, view not extendable, or missing concepts lack verified extension points)
        proposed_name = f"ZC_{req.title.replace(' ', '')[:20]}"
        rationale_reasons = []
        if not best_cand.is_extendable:
            rationale_reasons.append(f"Top candidate '{best_cand.view_name}' does not permit extensions (is_extendable=False).")
        if missing_count > 0:
            rationale_reasons.append(
                f"Missing concept(s) {best_ev.missing_concepts} lack verified extension points on existing views."
            )
        if best_ev.coverage_percentage < 70.0:
            rationale_reasons.append(
                f"Coverage is insufficient ({best_ev.coverage_percentage}% < 70% threshold)."
            )

        decision = Decision(
            requirement_id=req.id,
            action=DecisionAction.CREATE,
            recommended_view=best_cand.view_name if best_ev.coverage_percentage > 0 else None,
            confidence_score=0.80,
            fit_percentage=best_ev.coverage_percentage,
            rationale=(
                " ".join(rationale_reasons)
                + f" Recommending custom CDS View Entity draft '{proposed_name}' in customer namespace."
            ),
            missing_fields=best_ev.missing_concepts,
            proposed_new_view_name=proposed_name,
            requires_composition=False,
            complementary_views=[],
            evaluated_candidates=evaluations,
            structured_requirement=structured,
            evidence_summary=[
                f"Evaluated {len(evaluations)} SAP candidate(s). None qualified for REUSE or EXTEND.",
                f"Top candidate '{best_cand.view_name}' achieved {best_ev.coverage_percentage}% coverage.",
            ],
            warnings=["Custom CDS view required; standard VDM reuse was not viable."],
            tradeoffs=[
                "Custom lifecycle maintenance required.",
                "Full control over associations and field projections.",
                "Clean-core compliance verified prior to deployment.",
            ],
            human_approval_required=True,
            is_approved=False,
        )
        state["decision"] = decision
        self._log_and_advance(state, decision)
        return state

    def _log_and_advance(self, state: CDSWorkflowState, decision: Decision) -> None:
        self.log_audit(
            state,
            "DECISION_FORMULATED",
            {
                "action": decision.action.value,
                "confidence_score": decision.confidence_score,
                "recommended_view": decision.recommended_view,
                "requires_composition": decision.requires_composition,
                "human_approval_required": decision.human_approval_required,
            },
        )
        state["current_step"] = "MODELING"


def canonicalize_list(items: List[str]) -> List[str]:
    """Helper to canonicalize a list of string identifiers."""
    from src.agents.normalizer import canonicalize
    return [canonicalize(x) for x in items]

