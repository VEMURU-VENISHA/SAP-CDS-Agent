"""Concrete Unconnected SAP Connector implementation adhering to Milestone 1 guardrails.

This connector provides the structure and contract for future SAP connectivity,
while strictly refusing to emit fake SAP metadata or initiate unapproved network calls.
"""

from typing import List, Optional
from src.config import Settings, get_settings
from src.core.exceptions import SAPNotConnectedError
from src.logging_config import logger
from src.models.domain import CDSCandidate, CDSLayer, ValidationResult
from src.sap.interface import ISAPConnector
from src.sap.models import (
    ActivationResult,
    CDSMetadata,
    DependencyGraph,
    DraftResult,
    FieldDefinition,
    SAPSystemInfo,
)


class UnconnectedSAPConnector(ISAPConnector):
    """Stub connector implementation for Milestone 1.

    Enforces enterprise safety rules:
    - Zero live network traffic to SAP.
    - Zero fake/synthetic metadata generation.
    - Explicit `SAPNotConnectedError` raised on every SAP invocation.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        logger.info(
            "Initialized UnconnectedSAPConnector [Target SID: %s, Client: %s, Release: %s, S4CORE: %s, BASIS: %s]",
            self.settings.SAP_SYSTEM_ID,
            self.settings.SAP_CLIENT,
            self.settings.SAP_S4HANA_RELEASE,
            self.settings.SAP_S4CORE_RELEASE,
            self.settings.SAP_BASIS_RELEASE,
        )

    async def get_system_info(self) -> SAPSystemInfo:
        """Returns configured SAP target profile without initiating an active connection."""
        return SAPSystemInfo(
            system_id=self.settings.SAP_SYSTEM_ID,
            client=self.settings.SAP_CLIENT,
            s4hana_release=self.settings.SAP_S4HANA_RELEASE,
            s4core_release=self.settings.SAP_S4CORE_RELEASE,
            basis_release=self.settings.SAP_BASIS_RELEASE,
            adt_endpoint_configured=False,
            is_connected=False,
        )

    async def is_connected(self) -> bool:
        """Returns connection status (strictly False in Milestone 1)."""
        return False

    async def search_cds(
        self,
        query: str,
        package: Optional[str] = None,
        layer: Optional[CDSLayer] = None,
        limit: int = 50,
    ) -> List[CDSCandidate]:
        logger.warning(f"SAP search_cds invoked while connector is unconnected: query='{query}'")
        raise SAPNotConnectedError("search_cds")

    async def get_cds_metadata(self, view_name: str) -> CDSMetadata:
        logger.warning(f"SAP get_cds_metadata invoked while connector is unconnected: view_name='{view_name}'")
        raise SAPNotConnectedError("get_cds_metadata")

    async def search_fields(
        self,
        field_names: List[str],
        table_hints: Optional[List[str]] = None,
    ) -> List[FieldDefinition]:
        logger.warning(f"SAP search_fields invoked while connector is unconnected: field_names={field_names}")
        raise SAPNotConnectedError("search_fields")

    async def get_dependencies(
        self,
        view_name: str,
        depth: int = 2,
    ) -> DependencyGraph:
        logger.warning(f"SAP get_dependencies invoked while connector is unconnected: view_name='{view_name}'")
        raise SAPNotConnectedError("get_dependencies")

    async def create_cds_draft(
        self,
        view_name: str,
        view_definition: str,
        package: str,
        transport_request: str,
    ) -> DraftResult:
        logger.warning(f"SAP create_cds_draft invoked while connector is unconnected: view_name='{view_name}'")
        raise SAPNotConnectedError("create_cds_draft")

    async def validate_cds(
        self,
        view_definition: str,
    ) -> ValidationResult:
        logger.warning("SAP validate_cds invoked while connector is unconnected")
        raise SAPNotConnectedError("validate_cds")

    async def activate_cds(
        self,
        view_name: str,
        transport_request: str,
    ) -> ActivationResult:
        logger.warning(f"SAP activate_cds invoked while connector is unconnected: view_name='{view_name}'")
        raise SAPNotConnectedError("activate_cds")


_connector_instance: Optional[ISAPConnector] = None


def get_sap_connector() -> ISAPConnector:
    """Dependency injection provider for SAP connector."""
    global _connector_instance
    if _connector_instance is None:
        _connector_instance = UnconnectedSAPConnector()
    return _connector_instance
