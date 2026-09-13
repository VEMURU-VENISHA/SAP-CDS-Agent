from typing import Dict, List, Optional, Tuple
from src.agents.base import BaseAgent
from src.agents.normalizer import (
    HEURISTIC_SAP_VOCABULARY,
    canonicalize,
    match_concept_against_field,
)
from src.agents.state import CDSWorkflowState
from src.logging_config import logger
from src.models.domain import (
    CandidateEvaluation,
    CDSCandidate,
    CDSLayer,
    EvidenceLevel,
    FieldMapping,
    MappingType,
    StructuredRequirement,
    TargetUseCase,
)
from src.sap.connector import get_sap_connector
from src.sap.interface import ISAPConnector


class SemanticMappingAgent(BaseAgent):
    """Maps requested business concepts to SAP CDS view candidates using a strict 6-level evidence hierarchy.

    Verifies association targets dynamically using the verified SAP ADT source endpoint.
    Computes transparent candidate evaluations with configurable heuristic ranking and hard requirement overrides.
    """

    def __init__(self, connector: Optional[ISAPConnector] = None):
        super().__init__(
            name="SemanticMappingAgent",
            description="Performs multi-candidate semantic mapping and association verification against SAP CDS metadata.",
        )
        self.connector = connector or get_sap_connector()

    async def _verify_association_field(
        self,
        target_view: str,
        concept: str,
    ) -> Tuple[str, Optional[str], str]:
        """Fetches target CDS DDL via verified source endpoint and checks if concept exists on target.

        Returns:
            (status, matched_field, detail)
            where status is "FOUND", "NOT_ON_TARGET", or "UNRESOLVED_TARGET".
        """
        try:
            target_meta = await self.connector.get_cds_metadata(target_view)
            c_canon = canonicalize(concept)
            for f in target_meta.fields:
                if canonicalize(f.field_name) == c_canon:
                    return (
                        "FOUND",
                        f.field_name,
                        f"Verified association to '{target_view}' exposing field '{f.field_name}'",
                    )
                # Check description/label if available
                if f.description and c_canon in canonicalize(f.description):
                    return (
                        "FOUND",
                        f.field_name,
                        f"Verified association to '{target_view}' exposing field '{f.field_name}' (label: {f.description})",
                    )
            return (
                "NOT_ON_TARGET",
                None,
                f"Association target '{target_view}' retrieved via ADT, but field '{concept}' was not found on target",
            )
        except Exception as e:
            logger.debug("Association target DDL verification for '%s' failed: %s", target_view, e)
            return (
                "UNRESOLVED_TARGET",
                None,
                f"Target DDL for association '{target_view}' could not be retrieved from SAP ADT: {e}",
            )

    async def evaluate_candidate(
        self,
        candidate: CDSCandidate,
        requested_concepts: List[str],
        mandatory_dimensions: List[str],
        target_use_case: TargetUseCase,
    ) -> CandidateEvaluation:
        """Evaluates a single CDS candidate across all requested concepts."""
        field_mappings: List[FieldMapping] = []
        direct_matched_concepts: List[str] = []
        extension_obtainable_concepts: List[str] = []
        unresolved_concepts: List[str] = []
        missing_concepts: List[str] = []
        matched_concepts: List[str] = []
        exact_match_count = 0
        association_extension_count = 0

        for concept in requested_concepts:
            c_canon = canonicalize(concept)
            mapping: Optional[FieldMapping] = None

            # LEVEL 1: Exact technical field name or alias match
            for f_name in candidate.available_fields:
                if canonicalize(f_name) == c_canon:
                    mapping = FieldMapping(
                        requirement_field=concept,
                        matched_field=f_name,
                        source_entity=candidate.view_name,
                        mapping_type=MappingType.DIRECT_MATCH,
                        evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                        evidence_detail=f"Exact technical field match: CDS field '{f_name}' on '{candidate.view_name}'",
                        confidence=1.0,
                    )
                    exact_match_count += 1
                    break

            # LEVEL 2: Description or label match
            if not mapping and candidate.description and c_canon in canonicalize(candidate.description):
                # If the view itself represents the entity (e.g. concept is 'SalesOrder' and view is 'I_SalesOrder')
                # and candidate has key fields:
                for k in candidate.key_fields:
                    if canonicalize(k) == c_canon or c_canon in canonicalize(k):
                        mapping = FieldMapping(
                            requirement_field=concept,
                            matched_field=k,
                            source_entity=candidate.view_name,
                            mapping_type=MappingType.DIRECT_MATCH,
                            evidence_level=EvidenceLevel.LEVEL_2_LABEL_MATCH,
                            evidence_detail=f"Label/Key match: Primary key '{k}' matches requested '{concept}'",
                            confidence=0.95,
                        )
                        exact_match_count += 1
                        break

            # LEVEL 3: Verified Association Target + Verified Field
            if not mapping and candidate.associations:
                candidate_unresolved_mapping: Optional[FieldMapping] = None
                candidate_not_on_target_mapping: Optional[FieldMapping] = None

                for target_view in candidate.associations:
                    status, matched_target_f, detail = await self._verify_association_field(target_view, concept)
                    if status == "FOUND":
                        mapping = FieldMapping(
                            requirement_field=concept,
                            matched_field=matched_target_f,
                            source_entity=candidate.view_name,
                            mapping_type=MappingType.ASSOCIATION_HOP,
                            evidence_level=EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION,
                            evidence_detail=detail,
                            association_target_view=target_view,
                            association_target_field=matched_target_f,
                            confidence=0.85,
                        )
                        association_extension_count += 1
                        break
                    elif status == "UNRESOLVED_TARGET":
                        if not candidate_unresolved_mapping:
                            candidate_unresolved_mapping = FieldMapping(
                                requirement_field=concept,
                                matched_field=None,
                                source_entity=candidate.view_name,
                                mapping_type=MappingType.UNRESOLVED,
                                evidence_level=EvidenceLevel.LEVEL_6_MISSING,
                                evidence_detail=detail,
                                association_target_view=target_view,
                                confidence=0.0,
                            )
                    elif status == "NOT_ON_TARGET":
                        if not candidate_not_on_target_mapping:
                            candidate_not_on_target_mapping = FieldMapping(
                                requirement_field=concept,
                                matched_field=None,
                                source_entity=candidate.view_name,
                                mapping_type=MappingType.MISSING,
                                evidence_level=EvidenceLevel.LEVEL_6_MISSING,
                                evidence_detail=detail,
                                association_target_view=target_view,
                                confidence=0.0,
                            )

                if not mapping:
                    if candidate_unresolved_mapping:
                        mapping = candidate_unresolved_mapping
                    elif candidate_not_on_target_mapping:
                        mapping = candidate_not_on_target_mapping

            # LEVEL 4: Metadata-Supported Heuristic Synonym
            if not mapping:
                for std_concept, syn_list in HEURISTIC_SAP_VOCABULARY.items():
                    all_syns = [canonicalize(s) for s in syn_list] + [std_concept]
                    if c_canon in all_syns:
                        # Find if candidate has any of these technical fields
                        for f_name in candidate.available_fields:
                            if canonicalize(f_name) in all_syns:
                                mapping = FieldMapping(
                                    requirement_field=concept,
                                    matched_field=f_name,
                                    source_entity=candidate.view_name,
                                    mapping_type=MappingType.DIRECT_MATCH,
                                    evidence_level=EvidenceLevel.LEVEL_4_HEURISTIC_SYNONYM,
                                    evidence_detail=f"Metadata-supported synonym: CDS field '{f_name}' maps to standard concept '{std_concept}'",
                                    confidence=0.80,
                                )
                                break
                    if mapping:
                        break

            # LEVEL 6: No Evidence -> MISSING
            if not mapping:
                mapping = FieldMapping(
                    requirement_field=concept,
                    matched_field=None,
                    source_entity=candidate.view_name,
                    mapping_type=MappingType.MISSING,
                    evidence_level=EvidenceLevel.LEVEL_6_MISSING,
                    evidence_detail=f"Concept '{concept}' not found in candidate DDL fields, labels, or verified associations",
                    confidence=0.0,
                )
                missing_concepts.append(concept)
            else:
                if mapping.evidence_level == EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION:
                    extension_obtainable_concepts.append(concept)
                    matched_concepts.append(concept)
                elif mapping.mapping_type != MappingType.MISSING and mapping.evidence_level != EvidenceLevel.LEVEL_6_MISSING:
                    direct_matched_concepts.append(concept)
                    matched_concepts.append(concept)
                elif mapping.mapping_type == MappingType.UNRESOLVED:
                    unresolved_concepts.append(concept)
                    missing_concepts.append(concept)
                else:
                    missing_concepts.append(concept)

            field_mappings.append(mapping)

        total_req = max(1, len(requested_concepts))
        coverage_pct = round((len(matched_concepts) / total_req) * 100.0, 1)

        # Configurable Heuristic Ranking (Explicitly non-authoritative)
        coverage_score = coverage_pct
        exact_ratio_score = round((exact_match_count / total_req) * 100.0, 1)
        layer_score = 100.0 if (
            (target_use_case == TargetUseCase.ANALYTICAL_REPORT and candidate.layer in (CDSLayer.COMPOSITE, CDSLayer.CONSUMPTION))
            or (target_use_case != TargetUseCase.ANALYTICAL_REPORT and candidate.layer == CDSLayer.BASIC)
        ) else 70.0
        extend_score = 100.0 if candidate.is_extendable else 0.0
        assoc_score = min(100.0, len(candidate.associations) * 25.0)

        composite_rank_score = (
            (0.50 * coverage_score)
            + (0.20 * exact_ratio_score)
            + (0.15 * layer_score)
            + (0.10 * extend_score)
            + (0.05 * assoc_score)
        )

        # Hard Requirement Override: Disqualify candidate if mandatory dimensions are completely missing
        for mandatory_dim in mandatory_dimensions:
            m_canon = canonicalize(mandatory_dim)
            if not any(canonicalize(m) == m_canon for m in matched_concepts):
                composite_rank_score = max(0.0, composite_rank_score - 35.0)

        scoring_breakdown = {
            "coverage_score": coverage_score,
            "exact_match_ratio_score": exact_ratio_score,
            "layer_suitability_score": layer_score,
            "extendability_score": extend_score,
            "association_richness_score": assoc_score,
            "direct_matches_count": len(direct_matched_concepts),
            "extension_matches_count": len(extension_obtainable_concepts),
            "missing_count": len(missing_concepts),
            "unresolved_count": len(unresolved_concepts),
            "final_heuristic_rank_score": round(composite_rank_score, 1),
        }

        # Extension viability check: candidate is extendable, at least one concept requires extension
        # through verified association, and zero concepts are missing or unresolved
        is_extension_viable = bool(
            candidate.is_extendable
            and len(extension_obtainable_concepts) > 0
            and len(missing_concepts) == 0
            and len(unresolved_concepts) == 0
        )

        suitability_reason = (
            f"Candidate '{candidate.view_name}' satisfies {len(matched_concepts)}/{total_req} concepts ({coverage_pct}%). "
            f"Layer: {candidate.layer.value}, Extendable: {candidate.is_extendable}."
        )

        return CandidateEvaluation(
            candidate=candidate,
            rank=1,
            rank_score=round(composite_rank_score, 1),
            coverage_percentage=coverage_score,
            matched_concepts=matched_concepts,
            missing_concepts=missing_concepts,
            field_mappings=field_mappings,
            scoring_breakdown=scoring_breakdown,
            is_extension_viable=is_extension_viable,
            suitability_reason=suitability_reason,
        )

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        req = state.get("requirement")
        structured = state.get("structured_requirement")
        candidates = state.get("candidates", [])

        if not req:
            state.setdefault("errors", []).append("SemanticMappingAgent: Missing requirement.")
            return state

        # Determine requested concepts
        if structured and structured.all_requested_concepts:
            requested_concepts = structured.all_requested_concepts
            mandatory_dims = structured.dimensions
        elif req.required_fields:
            requested_concepts = req.required_fields
            mandatory_dims = req.required_entities
        else:
            requested_concepts = [req.title]
            mandatory_dims = []

        # If zero candidates (e.g. unconnected mode or 0 hits returned by SAP)
        if not candidates:
            empty_mappings = [
                FieldMapping(
                    requirement_field=c,
                    matched_field=None,
                    mapping_type=MappingType.MISSING,
                    evidence_level=EvidenceLevel.LEVEL_6_MISSING,
                    evidence_detail="No SAP candidate views available to evaluate",
                    confidence=0.0,
                )
                for c in requested_concepts
            ]
            state["field_mappings"] = empty_mappings
            state["evaluated_candidates"] = []
            self.log_audit(
                state,
                "SEMANTIC_MAPPING_ZERO_CANDIDATES",
                {"total_concepts": len(requested_concepts)},
            )
            state["current_step"] = "DECISION"
            return state

        # Evaluate each candidate independently
        evaluations: List[CandidateEvaluation] = []
        for cand in candidates:
            evaluation = await self.evaluate_candidate(
                candidate=cand,
                requested_concepts=requested_concepts,
                mandatory_dimensions=mandatory_dims,
                target_use_case=req.target_use_case,
            )
            evaluations.append(evaluation)

        # Multi-Candidate Ranking: sort by rank_score descending
        evaluations.sort(key=lambda e: e.rank_score, reverse=True)
        for idx, ev in enumerate(evaluations, start=1):
            ev.rank = idx

        state["evaluated_candidates"] = evaluations
        # Best candidate mappings become the primary field_mappings
        state["field_mappings"] = evaluations[0].field_mappings

        self.log_audit(
            state,
            "SEMANTIC_MAPPING_EVALUATED",
            {
                "total_concepts": len(requested_concepts),
                "candidates_evaluated": len(evaluations),
                "top_candidate": evaluations[0].candidate.view_name,
                "top_coverage": evaluations[0].coverage_percentage,
                "top_rank_score": evaluations[0].rank_score,
            },
        )
        state["current_step"] = "DECISION"
        return state

