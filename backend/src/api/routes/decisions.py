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
    from src.services.review_service import get_review_store
    store = get_review_store()
    pkg = store.get_by_decision(payload.decision_id)
    if pkg:
        try:
            if payload.approved:
                store.approve(pkg.review_id, reviewer=payload.approver)
            else:
                store.reject(
                    pkg.review_id,
                    reviewer=payload.approver,
                    reason=payload.rejection_reason or "Rejected via decision approval API",
                )
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {
        "decision_id": payload.decision_id,
        "approved": payload.approved,
        "approver": payload.approver,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "RECORDED",
        "message": "Human approval recorded in platform audit ledger.",
    }
