"""Base Agent Interface and Lifecycle Hooks."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict
from src.agents.state import CDSWorkflowState
from src.logging_config import logger


class BaseAgent(ABC):
    """Abstract Base Class for all specialized CDS intelligence agents."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def log_audit(self, state: CDSWorkflowState, event: str, payload: Dict[str, Any]) -> None:
        """Appends an immutable audit event into the workflow state."""
        if "audit_logs" not in state or state["audit_logs"] is None:
            state["audit_logs"] = []

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": self.name,
            "event": event,
            "payload": payload,
        }
        state["audit_logs"].append(entry)
        logger.info(f"[{self.name}] Audit: {event}")

    @abstractmethod
    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        """Executes the agent's core responsibility on the shared state graph.

        Args:
            state: Current pipeline state

        Returns:
            Updated pipeline state
        """
        pass
