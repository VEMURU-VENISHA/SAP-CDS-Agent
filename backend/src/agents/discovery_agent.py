"""SAP Discovery Agent: Discovers CDS views, tables, and associations via ISAPConnector."""

from typing import Optional
from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.core.exceptions import SAPNotConnectedError
from src.sap.connector import get_sap_connector
from src.sap.interface import ISAPConnector


class SAPDiscoveryAgent(BaseAgent):
    """Interrogates SAP S/4HANA CDS catalogs and the Virtual Data Model (VDM).

    Milestone 1 adheres to strict guardrails:
    - Never generates fake or synthesized SAP objects.
    - If connector is unconnected, logs status cleanly and defers live discovery.
    """

    def __init__(self, connector: Optional[ISAPConnector] = None):
        super().__init__(
            name="SAPDiscoveryAgent",
            description="Discovers candidate CDS views and underlying tables via SAP Connector.",
        )
        self.connector = connector or get_sap_connector()

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        req = state.get("requirement")
        if not req:
            state.setdefault("errors", []).append("SAPDiscoveryAgent: Missing requirement.")
            return state

        # Check connector availability
        is_conn = await self.connector.is_connected()
        if not is_conn:
            # TODO (Milestone 2): Execute live query via ADT search API once SAP connection is approved & configured.
            self.log_audit(
                state,
                "DISCOVERY_DEFERRED_UNCONNECTED",
                {
                    "message": "SAP Connector is unconnected (Milestone 1 guardrail). Zero fake metadata returned.",
                    "queried_entities": req.required_entities,
                },
            )
            state["candidates"] = []
            state["current_step"] = "MAPPING"
            return state

        try:
            candidates = []
            for entity in req.required_entities:
                found = await self.connector.search_cds(query=entity)
                candidates.extend(found)
            state["candidates"] = candidates
        except SAPNotConnectedError as e:
            self.log_audit(state, "DISCOVERY_SAP_NOT_CONNECTED", {"detail": str(e)})
            state["candidates"] = []

        state["current_step"] = "MAPPING"
        return state
