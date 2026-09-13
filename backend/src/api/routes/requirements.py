"""Requirements Intake and Analysis API Routes."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from src.agents.orchestrator import CDSWorkflowOrchestrator
from src.agents.state import CDSWorkflowState
from src.models.domain import (
    BusinessRequirement,
    CandidateEvaluation,
    CDSDraft,
    Decision,
    StructuredRequirement,
    TargetUseCase,
)

router = APIRouter(prefix="/requirements", tags=["Requirements"])
orchestrator = CDSWorkflowOrchestrator()


class RequirementCreatePayload(BaseModel):
    title: str
    description: str
    business_domain: str = "Sales & Distribution"
    target_use_case: TargetUseCase = TargetUseCase.ANALYTICAL_REPORT
    required_entities: List[str] = []
    required_fields: List[str] = []
    filter_criteria: List[str] = []


class PipelineExecutionResponse(BaseModel):
    requirement: BusinessRequirement
    structured_requirement: Optional[StructuredRequirement] = None
    evaluated_candidates: List[CandidateEvaluation] = []
    decision: Decision
    cds_draft: Optional[CDSDraft] = None
    generated_code_preview: str = ""
    current_step: str
    audit_events_count: int


@router.post(
    "/analyze",
    response_model=PipelineExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Submits a requirement to the multi-agent intelligence pipeline",
)
async def analyze_requirement(payload: RequirementCreatePayload):
    """Executes the full agent evaluation lifecycle on an incoming business requirement."""
    req = BusinessRequirement(
        title=payload.title,
        description=payload.description,
        business_domain=payload.business_domain,
        target_use_case=payload.target_use_case,
        required_entities=payload.required_entities,
        required_fields=payload.required_fields,
        filter_criteria=payload.filter_criteria,
    )

    initial_state: CDSWorkflowState = {
        "requirement": req,
        "candidates": [],
        "field_mappings": [],
        "audit_logs": [],
        "errors": [],
        "current_step": "INITIATED",
        "is_human_approved": False,
    }

    final_state = await orchestrator.execute_pipeline(initial_state)

    decision = final_state.get("decision")
    if not decision:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pipeline failed to formulate a decision.",
        )

    return PipelineExecutionResponse(
        requirement=req,
        structured_requirement=final_state.get("structured_requirement"),
        evaluated_candidates=final_state.get("evaluated_candidates", []),
        decision=decision,
        cds_draft=final_state.get("cds_draft"),
        generated_code_preview=final_state.get("generated_cds_code") or "",
        current_step=final_state.get("current_step", "COMPLETED"),
        audit_events_count=len(final_state.get("audit_logs", [])),
    )
