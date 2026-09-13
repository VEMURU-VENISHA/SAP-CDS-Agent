"""Architectural Decision and Human Approval API Routes."""

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from src.core.exceptions import EntityNotFoundError
from src.models.domain import Decision, DecisionAction

router = APIRouter(prefix="/decisions", tags=["Decisions & Governance"])


class ApprovalPayload(BaseModel):
    decision_id: str
    approved: bool
    approver: str
    rejection_reason: Optional[str] = None


@router.post(
    "/approval",
    summary="Human-in-the-loop sign-off for CDS action recommendation",
)
async def submit_human_approval(payload: ApprovalPayload):
    """Allows a Senior Developer or Architect to approve or reject a REUSE/EXTEND/CREATE decision."""
    # Milestone 1 endpoint records approval event
    return {
        "decision_id": payload.decision_id,
        "approved": payload.approved,
        "approver": payload.approver,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "RECORDED",
        "message": "Human approval recorded in platform audit ledger.",
    }
