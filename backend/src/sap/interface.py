"""Abstract Interface for SAP S/4HANA Connector.

Defines the contract for interacting with SAP S/4HANA systems.
Future implementations will back this interface with real SAP ADT REST,
PyRFC, or OData communication channels.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from src.models.domain import (
    CDSCandidate,
    CDSLayer,
    CDSReviewPackage,
    SAPReviewCheckrunResult,
    ValidationResult,
)
from src.sap.models import (
    ActivationResult,
    CDSMetadata,
    DependencyGraph,
    DraftResult,
    FieldDefinition,
    SAPSystemInfo,
)


class ISAPConnector(ABC):
    """Clean abstraction contract for all SAP S/4HANA integration operations."""

    @abstractmethod
    async def get_system_info(self) -> SAPSystemInfo:
        """Retrieves system landscape and release configuration."""
        pass

    @abstractmethod
    async def is_connected(self) -> bool:
        """Checks if a verified live connection to SAP S/4HANA is currently established."""
        pass

    @abstractmethod
    async def search_cds(
        self,
        query: str,
        package: Optional[str] = None,
        layer: Optional[CDSLayer] = None,
        limit: int = 50,
    ) -> List[CDSCandidate]:
        """Searches CDS view entities matching criteria in the target SAP system.

        Args:
            query: Search string for view name or description
            package: Optional ABAP package filter
            layer: Optional VDM layer filter (BASIC, COMPOSITE, CONSUMPTION)
            limit: Max results to return
        """
        pass

    @abstractmethod
    async def get_cds_metadata(self, view_name: str) -> CDSMetadata:
        """Retrieves full technical metadata for a specified CDS view entity.

        Args:
            view_name: Technical name of the CDS view entity (e.g., I_SalesOrder)
        """
        pass

    @abstractmethod
    async def search_fields(
        self,
        field_names: List[str],
        table_hints: Optional[List[str]] = None,
    ) -> List[FieldDefinition]:
        """Searches fields across SAP data dictionary tables and CDS views.

        Args:
            field_names: Field names or business terms to locate
            table_hints: Optional list of relevant core tables (e.g. VBAK, EKKO)
        """
        pass

    @abstractmethod
    async def get_dependencies(
        self,
        view_name: str,
        depth: int = 2,
    ) -> DependencyGraph:
        """Traces underlying tables, associations, and parent consumption views.

        Args:
            view_name: Technical view name to inspect
            depth: Traversal depth for dependency exploration
        """
        pass

    @abstractmethod
    async def create_cds_draft(
        self,
        view_name: str,
        view_definition: str,
        package: str,
        transport_request: str,
    ) -> DraftResult:
        """Creates an inactive CDS DDL draft object in SAP DEV via ADT APIs.

        Requires explicit human approval.

        Args:
            view_name: CDS view entity name
            view_definition: ABAP CDS DDL source code
            package: Target ABAP package
            transport_request: Workbench Transport Request ID
        """
        pass

    @abstractmethod
    async def validate_cds(
        self,
        view_definition: str,
        repository_uri: Optional[str] = None,
    ) -> ValidationResult:
        """Invokes remote SAP ABAP syntax check and CDS validator via ADT checkruns.

        Args:
            view_definition: ABAP CDS DDL source code
            repository_uri: Optional ADT repository URI (e.g. /sap/bc/adt/ddic/ddl/sources/i_salesorder)
        """
        pass

    @abstractmethod
    async def activate_cds(
        self,
        view_name: str,
        transport_request: str,
    ) -> ActivationResult:
        """Activates a CDS view entity in SAP DEV dictionary runtime.

        Requires explicit human approval.

        Args:
            view_name: CDS view entity name
            transport_request: Workbench Transport Request ID
        """
        pass

    @abstractmethod
    async def checkrun_cds_in_sap(
        self,
        review_package: CDSReviewPackage,
    ) -> SAPReviewCheckrunResult:
        """Executes a controlled read-only SAP ADT checkrun on an inactive CDS draft in SAP DEV.

        Args:
            review_package: Approved review package with target CDS object name and metadata.
        """
        pass

    async def get_data_preview(self, cds_name: str, max_rows: int = 10) -> dict:
        """Retrieves live data preview records for a CDS view from SAP S/4HANA."""
        return {"cds_name": cds_name, "total_rows": 0, "columns": [], "rows": []}

    async def get_transport_requests(self, user: Optional[str] = None) -> List[dict]:
        """Retrieves active CTS workbench transport requests from SAP S/4HANA."""
        return []


