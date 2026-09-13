"""Concrete SAP ADT Connector for Read-Only Metadata Discovery.

Backs ISAPConnector with real SAP ADT REST communication.
Primary verified capability:
- GET /sap/bc/adt/ddic/ddl/sources/{name} (Observed directly in target S/4HANA 2023 DEV system)

Strictly enforces read-only guardrails:
- Zero write, draft, or activation requests.
- Zero fake metadata emissions.
"""

from typing import List, Optional
from src.config import Settings, get_settings
from src.core.exceptions import SAPConnectorError, SAPNotFoundError
from src.logging_config import logger
from src.models.domain import CDSCandidate, CDSLayer, ValidationResult
from src.sap.adt_client import SAPADTClient
from src.sap.interface import ISAPConnector
from src.sap.models import (
    ActivationResult,
    CDSMetadata,
    DependencyGraph,
    DraftResult,
    FieldDefinition,
    SAPSystemInfo,
)
from src.sap.parser import CDSDDLParser


class SAPADTConnector(ISAPConnector):
    """Read-only SAP connector backed by native SAP S/4HANA ADT REST services."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[SAPADTClient] = None,
        parser: Optional[CDSDDLParser] = None,
    ):
        self.settings = settings or get_settings()
        self.client = client or SAPADTClient(settings=self.settings)
        self.parser = parser or CDSDDLParser()
        logger.info(
            "Initialized SAPADTConnector [Target: %s, Client: %s, BaseURL: %s, Auth: %s]",
            self.settings.SAP_SYSTEM_ID,
            self.settings.SAP_CLIENT,
            self.settings.SAP_BASE_URL,
            self.settings.SAP_AUTH_TYPE,
        )

    async def get_system_info(self) -> SAPSystemInfo:
        """Retrieves system landscape and release configuration."""
        is_conn = await self.is_connected()
        return SAPSystemInfo(
            system_id=self.settings.SAP_SYSTEM_ID,
            client=self.settings.SAP_CLIENT,
            s4hana_release=self.settings.SAP_S4HANA_RELEASE,
            s4core_release=self.settings.SAP_S4CORE_RELEASE,
            basis_release=self.settings.SAP_BASIS_RELEASE,
            adt_endpoint_configured=bool(self.settings.SAP_BASE_URL),
            is_connected=is_conn,
        )

    async def is_connected(self) -> bool:
        """Checks if a verified live connection to SAP S/4HANA is established."""
        return await self.client.check_connectivity()

    async def get_cds_metadata(self, view_name: str) -> CDSMetadata:
        """Retrieves technical metadata for a CDS view entity via the verified DDL source endpoint."""
        ddl = await self.client.get_ddl_source(view_name)
        return self.parser.parse_metadata(ddl, object_name=view_name)

    async def search_cds(
        self,
        query: str,
        package: Optional[str] = None,
        layer: Optional[CDSLayer] = None,
        limit: int = 50,
    ) -> List[CDSCandidate]:
        """Discovers CDS candidates in the target SAP system.

        Strategy:
        1. Exact match lookup via verified DDL source endpoint.
        2. If query is a pattern or not an exact hit, attempts documented repository quicksearch
           (system-unverified, handled safely).
        3. Never emits mock or synthetic metadata.
        """
        candidates: List[CDSCandidate] = []
        clean_query = query.strip()

        # 1. Attempt direct exact lookup on the verified DDL source endpoint
        try:
            ddl = await self.client.get_ddl_source(clean_query)
            candidate = self.parser.parse_candidate(ddl, object_name=clean_query)
            if layer is None or candidate.layer == layer:
                candidates.append(candidate)
            return candidates
        except (SAPNotFoundError, Exception) as direct_err:
            logger.debug("Direct DDL lookup for '%s' did not resolve: %s", clean_query, direct_err)

        # 2. Attempt documented repository quicksearch (Level 3: System-unverified)
        matches = await self.client.search_repository_unverified(clean_query, limit=limit)
        for item in matches:
            obj_name = item.get("name")
            if not obj_name:
                continue
            try:
                obj_ddl = await self.client.get_ddl_source(obj_name)
                cand = self.parser.parse_candidate(obj_ddl, object_name=obj_name)
                if layer is None or cand.layer == layer:
                    candidates.append(cand)
            except Exception as e:
                logger.debug("Could not resolve DDL source for search candidate '%s': %s", obj_name, e)

        return candidates

    async def search_fields(
        self,
        field_names: List[str],
        table_hints: Optional[List[str]] = None,
    ) -> List[FieldDefinition]:
        """Searches fields across specified CDS views using verified DDL source retrieval."""
        matched_fields: List[FieldDefinition] = []
        target_views = table_hints or []

        for view in target_views:
            try:
                meta = await self.get_cds_metadata(view)
                for f in meta.fields:
                    if f.field_name.upper() in [fn.upper() for fn in field_names]:
                        matched_fields.append(f)
            except Exception as e:
                logger.debug("Field resolution in view '%s' skipped: %s", view, e)

        return matched_fields

    async def get_dependencies(
        self,
        view_name: str,
        depth: int = 2,
    ) -> DependencyGraph:
        """Extracts direct underlying tables and CDS views from the verified DDL source."""
        ddl = await self.client.get_ddl_source(view_name)
        return self.parser.parse_dependencies(ddl, object_name=view_name)

    async def create_cds_draft(
        self,
        view_name: str,
        view_definition: str,
        package: str,
        transport_request: str,
    ) -> DraftResult:
        """Intentionally deferred in Milestone 3 (Read-only discovery mode)."""
        logger.warning("Attempted write operation 'create_cds_draft' in read-only discovery mode.")
        raise SAPConnectorError(
            message="Operation 'create_cds_draft' is disabled. Milestone 3 is strictly read-only discovery.",
            code="SAP_READ_ONLY_MODE",
            status_code=403,
        )

    async def validate_cds(
        self,
        view_definition: str,
    ) -> ValidationResult:
        """Intentionally deferred in Milestone 3 (Read-only discovery mode)."""
        logger.warning("Attempted 'validate_cds' in read-only discovery mode.")
        raise SAPConnectorError(
            message="Operation 'validate_cds' is deferred to Milestone 4.",
            code="SAP_READ_ONLY_MODE",
            status_code=403,
        )

    async def activate_cds(
        self,
        view_name: str,
        transport_request: str,
    ) -> ActivationResult:
        """Intentionally deferred in Milestone 3 (Read-only discovery mode)."""
        logger.warning("Attempted write operation 'activate_cds' in read-only discovery mode.")
        raise SAPConnectorError(
            message="Operation 'activate_cds' is disabled. Milestone 3 is strictly read-only discovery.",
            code="SAP_READ_ONLY_MODE",
            status_code=403,
        )
