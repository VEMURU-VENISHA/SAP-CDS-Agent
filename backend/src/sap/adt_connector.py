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
from src.models.domain import CDSCandidate, CDSLayer, SAPCheckrunResult, SAPValidationStatus, ValidationResult
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
        """Discovers real CDS candidates in target SAP system using verified ADT endpoints.

        Endpoints:
        - GET /sap/bc/adt/repository/informationsystem/search (VERIFIED IN SYSTEM)
        - GET /sap/bc/adt/ddic/ddl/sources/{name} (VERIFIED IN SYSTEM)
        """
        candidates: List[CDSCandidate] = []
        clean_query = query.strip()
        seen_names = set()

        # 1. Direct exact lookup if query is a specific view entity without wildcards
        if "*" not in clean_query:
            try:
                ddl = await self.client.get_ddl_source(clean_query)
                candidate = self.parser.parse_candidate(ddl, object_name=clean_query)
                if layer is None or candidate.layer == layer:
                    candidates.append(candidate)
                    seen_names.add(candidate.view_name.upper())
            except (SAPNotFoundError, Exception) as direct_err:
                logger.debug("Direct DDL lookup for '%s' did not resolve: %s", clean_query, direct_err)

        # 2. Query verified repository information system search endpoint
        search_hits = await self.client.search_information_system(clean_query, max_results=limit)

        for hit in search_hits:
            obj_name = hit.get("name")
            if not obj_name or obj_name.upper() in seen_names:
                continue

            obj_type = (hit.get("type") or "").upper()
            uri = (hit.get("uri") or "").lower()

            # Filter for CDS Data Definitions
            if obj_type in ("DDLS/DF", "DDLS") or "ddic/ddl/sources" in uri or not obj_type:
                # Filter by package if specified
                hit_pkg = hit.get("package")
                if package and hit_pkg and hit_pkg.upper() != package.upper():
                    continue

                # Enrich with authoritative real DDL from the verified source endpoint
                try:
                    obj_ddl = await self.client.get_ddl_source(obj_name)
                    cand = self.parser.parse_candidate(obj_ddl, object_name=obj_name)
                    if layer is None or cand.layer == layer:
                        candidates.append(cand)
                        seen_names.add(obj_name.upper())
                except Exception as e:
                    logger.debug("Could not retrieve DDL source for search candidate '%s': %s", obj_name, e)

            if len(candidates) >= limit:
                break

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
        repository_uri: Optional[str] = None,
    ) -> ValidationResult:
        """Validates CDS view entity using verified SAP ADT checkrun endpoint.

        Rule:
        - For existing repository objects (e.g. /sap/bc/adt/ddic/ddl/sources/i_salesorder),
          executes real read-only checkrun: POST /sap/bc/adt/checkruns?reporters=abapCheckRun
        - For unpersisted drafts without a repository URI:
          returns UNAVAILABLE with reason 'Unpersisted Draft — SAP ADT checkrun requires a repository object URI.'
          Zero SAP write operations or draft creations are performed.
        """
        if not repository_uri or not repository_uri.strip():
            return ValidationResult(
                is_valid=True,
                syntax_errors=[],
                naming_convention_violations=[],
                clean_core_compliance_score=100.0,
                governance_warnings=[],
                details=[
                    {
                        "check": "SAP ADT Remote Checkrun",
                        "passed": False,
                        "detail": "Unpersisted Draft — SAP ADT checkrun requires a repository object URI.",
                    },
                ],
                sap_validation_status=SAPValidationStatus.UNAVAILABLE,
                sap_checkrun_reason="Unpersisted Draft — SAP ADT checkrun requires a repository object URI.",
            )

        checkrun_result = await self.client.run_checkrun(repository_uri.strip())

        syntax_errors = []
        governance_warnings = []
        details = []

        if checkrun_result.status == SAPValidationStatus.PASS:
            is_valid = True
            details.append({
                "check": "SAP ADT Remote Checkrun",
                "passed": True,
                "detail": "All SAP ABAP syntax and compiler checks passed cleanly.",
            })
        elif checkrun_result.status == SAPValidationStatus.WARNING:
            is_valid = True
            for m in checkrun_result.messages:
                loc = f"Line {m.line}" if m.line else "Header"
                governance_warnings.append(f"SAP Compiler Warning ({loc}): {m.short_text}")
            details.append({
                "check": "SAP ADT Remote Checkrun",
                "passed": True,
                "detail": f"SAP returned {len(checkrun_result.messages)} compiler warnings.",
            })
        elif checkrun_result.status == SAPValidationStatus.ERROR:
            is_valid = False
            for m in checkrun_result.messages:
                if m.severity in ("E", "A"):
                    loc = f"Line {m.line}" if m.line else "General"
                    syntax_errors.append(f"SAP Compiler Error ({loc}): {m.short_text}")
                elif m.severity == "W":
                    loc = f"Line {m.line}" if m.line else "General"
                    governance_warnings.append(f"SAP Compiler Warning ({loc}): {m.short_text}")
            details.append({
                "check": "SAP ADT Remote Checkrun",
                "passed": False,
                "detail": f"SAP returned {len(syntax_errors)} blocking syntax/compiler errors.",
            })
        else:
            # UNAVAILABLE or INSUFFICIENT_EVIDENCE
            is_valid = True
            details.append({
                "check": "SAP ADT Remote Checkrun",
                "passed": False,
                "detail": checkrun_result.reason or "SAP checkrun unavailable.",
            })

        return ValidationResult(
            is_valid=is_valid,
            syntax_errors=syntax_errors,
            naming_convention_violations=[],
            clean_core_compliance_score=100.0 if is_valid else 0.0,
            governance_warnings=governance_warnings,
            details=details,
            sap_validation_status=checkrun_result.status,
            sap_checkrun_result=checkrun_result,
            sap_checkrun_reason=checkrun_result.reason,
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

    async def aclose(self) -> None:
        """Closes the underlying ADT client session to prevent resource leaks."""
        if hasattr(self.client, "aclose"):
            await self.client.aclose()

    async def __aenter__(self) -> "SAPADTConnector":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

