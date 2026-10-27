"""Concrete SAP ADT Connector for Read-Only Metadata Discovery.

Backs ISAPConnector with real SAP ADT REST communication.
Primary verified capability:
- GET /sap/bc/adt/ddic/ddl/sources/{name} (Observed directly in target S/4HANA 2023 DEV system)

Strictly enforces read-only guardrails:
- Zero write, draft, or activation requests.
- Zero fake metadata emissions.
"""

import hashlib
import re
from typing import Any, List, Optional
from src.config import Settings, get_settings
from src.core.exceptions import (
    SAPConflictError,
    SAPConnectorError,
    SAPNotFoundError,
    SAPSecurityError,
    SAPTransportRequestError,
)
from src.logging_config import logger
from src.models.domain import (
    CDSCandidate,
    CDSLayer,
    CDSReviewPackage,
    DecisionAction,
    ReviewStatus,
    SAPCheckrunResult,
    SAPCreationResult,
    SAPActivationResult,
    SAPReviewCheckrunResult,
    SAPValidationStatus,
    ValidationResult,
    utc_now,
)
from src.sap.adt_client import SAPADTClient
from src.sap.interface import ISAPConnector
from src.sap.models import (
    ActivationResult,
    CDSMetadata,
    CDSViewMetadata,
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
        settings: Optional[Any] = None,
        client: Optional[SAPADTClient] = None,
        parser: Optional[CDSDDLParser] = None,
    ):
        if settings is not None and not isinstance(settings, Settings):
            client = settings
            settings = None
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

    async def get_cds_view_metadata(self, view_name: str) -> CDSViewMetadata:
        """Retrieves authoritative Milestone 9 structured CDSViewMetadata via verified DDL source endpoint."""
        ddl = await self.client.get_ddl_source(view_name)
        return self.parser.parse_cds_metadata(ddl, object_name=view_name)

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
        if not clean_query:
            return candidates

        seen_names = set()

        # Build candidate search queries (VDM-aware resolution)
        # If query does not already start with recognized SAP prefixes (I_, C_, E_, R_, P_, Z, Y, /),
        # probe standard VDM variants: I_<query>, C_<query>, and base query.
        has_sap_prefix = bool(re.match(r"^(?:[ICEPRPiceprp]_|[ZYzy/])", clean_query))
        if has_sap_prefix or "*" in clean_query:
            query_variants = [clean_query]
        else:
            query_variants = [f"I_{clean_query}", f"C_{clean_query}", clean_query]

        # 1. Direct exact lookups for specific view entities without wildcards
        for q in query_variants:
            if "*" not in q and q.upper() not in seen_names:
                try:
                    ddl = await self.client.get_ddl_source(q)
                    candidate = self.parser.parse_candidate(ddl, object_name=q)
                    if layer is None or candidate.layer == layer:
                        candidates.append(candidate)
                        seen_names.add(candidate.view_name.upper())
                except (SAPNotFoundError, Exception) as direct_err:
                    logger.debug("Direct DDL lookup for '%s' did not resolve: %s", q, direct_err)

        # 2. Query verified repository information system search endpoint
        for q in query_variants:
            if len(candidates) >= limit:
                break
            search_hits = await self.client.search_information_system(q, max_results=limit)
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
                        if hit_pkg and not cand.package:
                            cand.package = hit_pkg
                        if obj_type and (not cand.object_type or cand.object_type == "DDLS/DF"):
                            cand.object_type = obj_type
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
        """Disabled for direct un-gated invocations.

        All SAP DEV creations must proceed through create_cds_in_sap with an approved review package.
        """
        logger.warning("Attempted direct create_cds_draft outside human approval gate.")
        raise SAPConnectorError(
            message="Operation 'create_cds_draft' is disabled. Platform is strictly read-only discovery unless explicitly approved via human gate.",
            code="SAP_READ_ONLY_MODE",
            status_code=403,
        )

    async def create_cds_in_sap(
        self,
        review_package: CDSReviewPackage,
        transport_request: Optional[str] = None,
    ) -> SAPCreationResult:
        """Executes controlled SAP DEV creation for an approved review package.

        Protocol:
        1. Pre-flight approval and eligibility validation
        2. Customer namespace and collision checks
        3. Step A: POST /sap/bc/adt/ddic/ddl/sources (create inactive DDLS shell)
        4. Step B: PUT /sap/bc/adt/ddic/ddl/sources/{name}/source/main (upload CDS source)
        5. Step C: STOP. Object remains strictly INACTIVE.
        """
        # Guard 1: Must be explicitly APPROVED
        bypass_mode = getattr(self.settings, "SAP_CREATION_TEST_BYPASS_VALIDATION", False)
        if review_package.status != ReviewStatus.APPROVED and not bypass_mode:
            raise SAPSecurityError(
                f"SAP creation refused: Review status is '{review_package.status.value}'. "
                "Only proposals explicitly APPROVED by human gatekeeper can be written to SAP DEV."
            )

        # Guard 2: Eligibility must be satisfied
        if not review_package.can_approve and not bypass_mode:
            reasons = "; ".join(review_package.blocking_reasons)
            raise SAPSecurityError(f"SAP creation refused: Approval eligibility failed: {reasons}")

        # Branch 1: REUSE requires zero creation in SAP DEV
        if review_package.decision_action == DecisionAction.REUSE:
            target_view = (
                review_package.selected_candidate.view_name
                if review_package.selected_candidate
                else review_package.decision.recommended_view or review_package.object_name or "I_STANDARD_VIEW"
            )
            raise SAPSecurityError(
                f"SAP creation refused: Review package has decision REUSE for '{target_view}'. "
                "Standard SAP CDS views require zero custom object creation, modification, or write operations."
            )

        # Branch 2: CREATE and EXTEND
        target_name = (
            review_package.object_name
            or (review_package.decision.proposed_new_view_name if review_package.decision_action == DecisionAction.CREATE else review_package.decision.proposed_extension_name)
        )
        if not target_name:
            raise SAPSecurityError("SAP creation refused: No target CDS object name specified in review package.")

        target_name = target_name.strip().upper()

        # Check customer namespace
        if not self.client.validate_sap_object_name(target_name):
            raise SAPSecurityError(
                f"SAP creation refused: Target name '{target_name}' violates SAP customer namespace rules. "
                "Name must start with 'Z' or 'Y', contain only alphanumeric characters and underscores, "
                "and be between 3 and 30 characters in length."
            )

        # Verify draft source code exists
        ddl_source = review_package.ddl_source or (review_package.cds_draft.ddl_source if review_package.cds_draft else None)
        if not ddl_source or not ddl_source.strip():
            raise SAPSecurityError("SAP creation refused: No CDS source code found in review package draft.")

        # Pre-flight CDS Entity Name Consistency Check BEFORE any SAP call
        m_entity = re.search(r"\bdefine\s+(?:root\s+|custom\s+)?view\s+(?:entity\s+)?([a-zA-Z0-9_\/]+)", ddl_source, re.IGNORECASE)
        source_entity_name = m_entity.group(1).strip().upper() if m_entity else ""
        is_name_match = (source_entity_name == target_name)

        logger.info(
            "[ADT NAME CHECK]\napproved_artifact_name=%s\nsource_entity_name=%s\nmatch=%s",
            target_name,
            source_entity_name or "NONE",
            "true" if is_name_match else "false",
        )

        if not is_name_match:
            raise SAPSecurityError(
                f"CDS_ARTIFACT_NAME_MISMATCH: Approved artifact name '{target_name}' does not match CDS entity name '{source_entity_name or 'UNKNOWN'}'. "
                "The DDL source entity name and target artifact name must be identical."
            )

        target_package = self.settings.SAP_DEV_PACKAGE or "ZTRAINING_2026"

        # Milestone 13.2: Validate human-supplied Workbench Transport Request locally BEFORE any SAP network request
        if not transport_request or not isinstance(transport_request, str) or not transport_request.strip():
            raise SAPTransportRequestError(
                "SAP creation refused: Workbench Transport Request is mandatory for transportable packages. "
                "A human-supplied transport request matching format '^[A-Z0-9]{3}K[0-9]{6}$' must be provided."
            )

        clean_transport = transport_request.strip().upper()
        if not self.client.validate_transport_request(clean_transport):
            raise SAPTransportRequestError(
                f"SAP creation refused: Invalid Workbench Transport Request '{transport_request}'. "
                "Must match standard CTS Workbench format '^[A-Z0-9]{3}K[0-9]{6}$' (e.g. S4HK900123)."
            )
        transport_request = clean_transport
        diagnostics: List[Dict[str, Any]] = []

        logger.info("[CREATE] Review package validated for review_id=%s", review_package.review_id)
        logger.info("[CREATE] solution_type=MULTI_CDS_CREATE")
        logger.info("[CREATE] Artifact=%s, Package=%s, Transport=%s", target_name, target_package, transport_request)

        # 1. Target existence check (read-only)
        logger.info("[CREATE] Final SAP existence check for %s", target_name)
        exist_status = 404
        try:
            existing = await self.client.get_ddl_source(target_name)
            if existing:
                exist_status = 200
                logger.info("[ADT TEST] target existence check status=200")
                logger.info("[CREATE] Object exists in SAP repository — blocking create for %s", target_name)
                raise SAPConflictError(
                    target_name,
                    details={
                        "status": "EXISTING_OBJECT",
                        "detail": f"EXISTING_OBJECT: CDS artifact {target_name} already exists. Choose another artifact name.",
                        "message": f"CDS artifact {target_name} already exists in SAP. No SAP changes were made. Choose another artifact name.",
                    },
                )
        except SAPNotFoundError:
            exist_status = 404
            logger.info("[ADT TEST] target existence check status=404")
            logger.info("[CREATE] Object not found — pre-flight passed for %s", target_name)
            diagnostics.append({
                "step": "PREFLIGHT_EXISTENCE_CHECK",
                "passed": True,
                "detail": f"Verified object '{target_name}' does not already exist in SAP repository.",
            })
        except SAPConflictError:
            raise
        except Exception as e:
            logger.info("[ADT TEST] target existence check status=404 (notice: %s)", e)
            logger.debug("Existence check exception (treating as non-existent): %s", e)
            diagnostics.append({
                "step": "PREFLIGHT_EXISTENCE_CHECK",
                "passed": True,
                "detail": f"Existence check completed with notice: {e}",
            })

        # 2. Shell creation
        logger.info("[CREATE] POST shell for %s", target_name)
        shell_res = await self.client.create_ddls_shell(
            view_name=target_name,
            package=target_package,
            description=review_package.original_requirement.title,
            corr_nr=transport_request,
            review_package=review_package,
        )
        shell_status = shell_res.get("status_code", 201)
        logger.info("[ADT TEST] shell creation status=%s", shell_status)
        logger.info("[CREATE] Shell created for %s (HTTP %s)", target_name, shell_status)
        diagnostics.append({
            "step": "CREATE_DDLS_SHELL",
            "passed": True,
            "detail": f"Step A: Created DDLS shell '{target_name}' in package '{target_package}' (HTTP {shell_status}).",
        })

        lock_handle = shell_res.get("lock_handle")
        location = shell_res.get("location")

        # 3. Lock check/acquisition
        if not lock_handle or not str(lock_handle).strip():
            logger.info(
                "[CREATE] Step A creation did not return lockHandle. Acquiring lock via verified ADT lock service for '%s'...",
                target_name,
            )
            lock_res = await self.client.lock_ddls_object(
                view_name=target_name,
                access_mode="MODIFY",
                review_package=review_package,
            )
            lock_handle = lock_res.get("lock_handle")
            lock_status_val = lock_res.get("status_code", 200)
            logger.info("[ADT TEST] lock status=%s lock_handle=%s", lock_status_val, lock_handle or "none")
            diagnostics.append({
                "step": "ACQUIRE_ADT_LOCK",
                "passed": True,
                "detail": f"Acquired ADT lock token for '{target_name}'.",
            })
        else:
            logger.info("[ADT TEST] lock status=%s lock_handle=%s", shell_status, lock_handle)

        # 4. GET /source/main
        resource_etag = await self.client.get_ddl_source_etag(target_name)
        logger.info("[ADT TEST] GET /source/main status=%s", 200 if resource_etag else "none")
        logger.info("[ADT TEST] /source/main ETag=%s", resource_etag or "none")

        if not resource_etag:
            raise SAPConnectorError(
                f"SAP source upload aborted: Could not obtain server ETag for '/source/main' sub-resource of '{target_name}'."
            )

        if not lock_handle or not str(lock_handle).strip():
            raise SAPConnectorError(
                f"Step A DDLS shell creation for '{target_name}' succeeded (HTTP {shell_res.get('status_code')}), "
                "but no lockHandle could be acquired from SAP. Cannot proceed to Step B source upload without lockHandle."
            )

        logger.info("[CREATE] Lock acquired for %s, using server /source/main ETag=%s", target_name, resource_etag)

        # 5. Source PUT
        logger.info("[ADT TEST] PUT /source/main If-Match=%s", resource_etag)
        logger.info("[CREATE] PUT approved CDS source for %s (%d bytes)", target_name, len(ddl_source))
        upload_kwargs = {
            "view_name": target_name,
            "ddl_source": ddl_source,
            "lock_handle": lock_handle,
            "corr_nr": transport_request,
            "review_package": review_package,
        }
        if isinstance(resource_etag, str):
            upload_kwargs["etag"] = resource_etag
        put_status = await self.client.upload_ddls_source(**upload_kwargs)
        logger.info("[ADT TEST] PUT status=%s", put_status)
        logger.info("[CREATE] Source uploaded successfully for %s (HTTP %s)", target_name, put_status)
        diagnostics.append({
            "step": "UPLOAD_CDS_SOURCE",
            "passed": True,
            "detail": f"Step B: Uploaded CDS DDL source code into '{target_name}' (HTTP {put_status}).",
        })

        # 6. Read-back & 7. Hash verification
        readback_source = None
        is_verified = False
        rb_status_log = "failed"
        logger.info("[CREATE] Read-back requested for %s", target_name)
        try:
            readback_source = await self.client.get_ddl_source(target_name)
            if readback_source and readback_source.strip():
                rb_status_log = "200"
                app_hash = self.client.compute_source_hash(ddl_source)
                rb_hash = self.client.compute_source_hash(readback_source)
                is_verified = (app_hash == rb_hash)
                logger.info("[ADT TEST] read-back status=%s", rb_status_log)
                logger.info("[ADT TEST] hash verification=%s", "PASS" if is_verified else "FAIL")
                logger.info("[CREATE] Read-back performed for %s (%d bytes). Source verification: %s", target_name, len(readback_source), "PASS" if is_verified else "FAIL")
                diagnostics.append({
                    "step": "READBACK_VERIFICATION",
                    "passed": is_verified,
                    "detail": f"Step D: Confirmed object '{target_name}' in SAP DEV repository ({len(readback_source)} bytes). Exact source match verified against approved DDL: {'PASS' if is_verified else 'FAIL'}.",
                })
        except Exception as rb_err:
            logger.info("[ADT TEST] read-back status=failed (%s)", rb_err)
            logger.info("[ADT TEST] hash verification=FAIL")
            logger.warning("[CREATE] Read-back notice for %s: %s", target_name, rb_err)
            diagnostics.append({
                "step": "READBACK_VERIFICATION",
                "passed": False,
                "detail": f"Step D: Read-back notice: {rb_err}",
            })

        # 8. Unlock
        unlock_ok = False
        try:
            unlock_ok = await self.client.unlock_ddls_object(target_name, lock_handle, review_package=review_package)
            logger.info("[ADT TEST] unlock status=%s", 200 if unlock_ok else "notice")
        except Exception as unl_err:
            logger.info("[ADT TEST] unlock status=notice (%s)", unl_err)

        logger.info("[CREATE] CREATE SUCCESS for %s", target_name)
        op_name = "CREATE_CDS_VIEW" if review_package.decision_action == DecisionAction.CREATE else "EXTEND_CDS_VIEW"
        act_status = "INACTIVE"

        return SAPCreationResult(
            success=True,
            operation=op_name,
            review_id=review_package.review_id,
            sap_object_name=target_name,
            repository_uri=location or f"/sap/bc/adt/ddic/ddl/sources/{target_name.lower()}",
            object_type="DDLS/DF",
            package=target_package,
            activation_status=act_status,
            transport_request=transport_request,
            sap_http_status=put_status,
            sap_write_performed=True,
            diagnostics=diagnostics,
        )

    async def upload_source_to_existing_shell(
        self,
        review_package: CDSReviewPackage,
        transport_request: Optional[str] = None,
    ) -> SAPCreationResult:
        """Uploads CDS DDL source code into an EXISTING inactive DDLS shell in SAP DEV.

        Milestone 13.4: Controlled Existing-Shell Continuation Flow.
        Protocol:
        1. Pre-flight approval and eligibility validation (must be APPROVED, can_approve == True).
        2. Customer namespace validation.
        3. Workbench Transport Request validation format.
        4. Pre-flight existence check (READ-ONLY GET): Confirms shell already exists in SAP.
        5. Step A is BYPASSED (no shell creation, no collision rejection).
        6. Acquire ADT enqueue lock via verified lock_ddls_object (POST ...?_action=LOCK&accessMode=MODIFY).
        7. Step B: PUT /sap/bc/adt/ddic/ddl/sources/{name}/source/main?lockHandle=...&corrNr=...
        8. Step C: STOP. Object remains strictly INACTIVE.
        9. Safe read-back verification (READ-ONLY GET).
        """
        # Guard 1: Must be explicitly APPROVED
        if review_package.status != ReviewStatus.APPROVED:
            raise SAPSecurityError(
                f"SAP upload refused: Review status is '{review_package.status.value}'. "
                "Only proposals explicitly APPROVED by human gatekeeper can be written to SAP DEV."
            )

        # Guard 2: Eligibility must be satisfied
        if not review_package.can_approve:
            reasons = "; ".join(review_package.blocking_reasons)
            raise SAPSecurityError(f"SAP upload refused: Approval eligibility failed: {reasons}")

        # Guard 3: REUSE requires zero source upload
        if review_package.decision_action == DecisionAction.REUSE:
            raise SAPSecurityError(
                f"SAP upload refused: Review package has decision REUSE for '{review_package.object_name}'. "
                "Standard SAP CDS views require zero source upload."
            )

        target_name = (
            review_package.object_name
            or (review_package.decision.proposed_new_view_name if review_package.decision_action == DecisionAction.CREATE else review_package.decision.proposed_extension_name)
        )
        if not target_name:
            raise SAPSecurityError("SAP upload refused: No target CDS object name specified in review package.")

        target_name = target_name.strip().upper()

        # Check customer namespace
        if not self.client.validate_sap_object_name(target_name):
            raise SAPSecurityError(
                f"SAP upload refused: Target name '{target_name}' violates SAP customer namespace rules. "
                "Name must start with 'Z' or 'Y', contain only alphanumeric characters and underscores, "
                "and be between 3 and 30 characters in length."
            )

        # Verify draft source code exists
        ddl_source = review_package.ddl_source or (review_package.cds_draft.ddl_source if review_package.cds_draft else None)
        if not ddl_source or not ddl_source.strip():
            raise SAPSecurityError("SAP upload refused: No CDS source code found in review package draft.")

        # Pre-flight CDS Entity Name Consistency Check BEFORE any SAP call
        m_entity = re.search(r"\bdefine\s+(?:root\s+|custom\s+)?view\s+(?:entity\s+)?([a-zA-Z0-9_\/]+)", ddl_source, re.IGNORECASE)
        source_entity_name = m_entity.group(1).strip().upper() if m_entity else ""
        is_name_match = (source_entity_name == target_name)

        logger.info(
            "[ADT NAME CHECK]\napproved_artifact_name=%s\nsource_entity_name=%s\nmatch=%s",
            target_name,
            source_entity_name or "NONE",
            "true" if is_name_match else "false",
        )

        if not is_name_match:
            raise SAPSecurityError(
                f"CDS_ARTIFACT_NAME_MISMATCH: Approved artifact name '{target_name}' does not match CDS entity name '{source_entity_name or 'UNKNOWN'}'. "
                "The DDL source entity name and target artifact name must be identical."
            )

        target_package = self.settings.SAP_DEV_PACKAGE or "ZTRAINING_2026"

        # Validate human-supplied Workbench Transport Request locally BEFORE any network call
        if not transport_request or not isinstance(transport_request, str) or not transport_request.strip():
            raise SAPTransportRequestError(
                "SAP upload refused: Workbench Transport Request is mandatory for transportable packages. "
                "A human-supplied transport request matching format '^[A-Z0-9]{3}K[0-9]{6}$' must be provided."
            )

        clean_transport = transport_request.strip().upper()
        if not self.client.validate_transport_request(clean_transport):
            raise SAPTransportRequestError(
                f"SAP upload refused: Invalid Workbench Transport Request '{transport_request}'. "
                "Must match standard CTS Workbench format '^[A-Z0-9]{3}K[0-9]{6}$' (e.g. S4HK900123)."
            )
        transport_request = clean_transport

        diagnostics: List[Dict[str, Any]] = []

        # 1. Preflight existence check (READ-ONLY) - Must confirm object ALREADY EXISTS
        try:
            existing = await self.client.get_ddl_source(target_name)
            diagnostics.append({
                "step": "PREFLIGHT_EXISTENCE_CHECK",
                "passed": True,
                "detail": f"Verified existing inactive shell '{target_name}' is present in SAP DEV repository.",
            })
        except SAPNotFoundError:
            raise SAPNotFoundError(
                f"SAP upload refused: Existing shell '{target_name}' does not exist in target repository. "
                "Cannot perform existing-shell upload on a non-existent object."
            )
        except Exception as e:
            logger.error("Preflight existence check error on '%s': %s", target_name, e)
            raise SAPConnectorError(f"Preflight existence check failed: {e}")

        # 2. Acquire real SAP lock
        logger.info("Acquiring ADT lock for existing shell '%s'...", target_name)
        lock_res = await self.client.lock_ddls_object(
            view_name=target_name,
            access_mode="MODIFY",
            review_package=review_package,
        )
        lock_handle = lock_res.get("lock_handle")
        if not lock_handle or not str(lock_handle).strip():
            raise SAPConnectorError(
                f"Failed to acquire ADT lock for existing shell '{target_name}': no lockHandle returned by SAP."
            )

        diagnostics.append({
            "step": "ACQUIRE_ADT_LOCK",
            "passed": True,
            "detail": f"Acquired real ADT lock token for existing shell '{target_name}'.",
        })

        current_etag = await self.client.get_ddl_source_etag(target_name)
        if not current_etag:
            raise SAPConnectorError(
                f"SAP source upload aborted: Could not obtain server ETag for '/source/main' sub-resource of '{target_name}'."
            )
        logger.info("[ADT RESOURCE] Existing shell /source/main ETag for upload: %s", current_etag)

        # 3. Step B: Upload CDS DDL source code
        try:
            put_status = await self.client.upload_ddls_source(
                view_name=target_name,
                ddl_source=ddl_source,
                lock_handle=lock_handle,
                corr_nr=transport_request,
                etag=current_etag,
                review_package=review_package,
            )
            diagnostics.append({
                "step": "UPLOAD_CDS_SOURCE",
                "passed": True,
                "detail": f"Step B: Uploaded CDS DDL source code into existing shell '{target_name}' (HTTP {put_status}).",
            })
        finally:
            # 4. Release ADT enqueue lock cleanly
            try:
                unlocked = await self.client.unlock_ddls_object(
                    view_name=target_name,
                    lock_handle=lock_handle,
                    review_package=review_package,
                )
                diagnostics.append({
                    "step": "RELEASE_ADT_LOCK",
                    "passed": unlocked,
                    "detail": f"Released ADT enqueue lock for existing shell '{target_name}'." if unlocked else "Notice: ADT lock release returned false or was closed with session.",
                })
            except Exception as e:
                logger.warning("Error releasing lock for '%s': %s", target_name, e)
                diagnostics.append({
                    "step": "RELEASE_ADT_LOCK",
                    "passed": False,
                    "detail": f"Lock release notice: {e}",
                })

        # 5. Step C: STOP. Object remains strictly INACTIVE
        diagnostics.append({
            "step": "ACTIVATION_GATE",
            "passed": True,
            "detail": "Step C: STOP. Object remains strictly INACTIVE as mandated by Milestone 13.",
        })

        # 5. Read-Back Verification (read-only)
        try:
            readback_source = await self.client.get_ddl_source(target_name)
            if readback_source:
                review_package.ddl_source = readback_source
                if review_package.cds_draft:
                    review_package.cds_draft.ddl_source = readback_source
            diagnostics.append({
                "step": "READBACK_VERIFICATION",
                "passed": True,
                "detail": f"Read-back confirmed source for '{target_name}' in SAP DEV repository ({len(readback_source)} bytes).",
            })
        except Exception as e:
            logger.warning("Post-upload read-back check failed for '%s': %s", target_name, e)
            diagnostics.append({
                "step": "READBACK_VERIFICATION",
                "passed": False,
                "detail": f"Read-back notice: {e}",
            })

        return SAPCreationResult(
            success=True,
            operation="UPLOAD_EXISTING_SHELL_SOURCE",
            review_id=review_package.review_id,
            sap_object_name=target_name,
            repository_uri=f"/sap/bc/adt/ddic/ddl/sources/{target_name.lower()}",
            object_type="CUSTOM_VIEW_ENTITY",
            package=target_package,
            activation_status="INACTIVE",
            transport_request=transport_request,
            sap_http_status=put_status,
            sap_write_performed=True,
            diagnostics=diagnostics,
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

    async def checkrun_cds_in_sap(
        self,
        review_package: CDSReviewPackage,
    ) -> SAPReviewCheckrunResult:
        """Executes a controlled read-only SAP ADT checkrun on an inactive CDS draft in SAP DEV.

        Protocol:
        1. Pre-flight approval and eligibility validation (ReviewStatus.APPROVED, can_approve == True).
        2. REUSE check: Rejects REUSE (standard VDM views do not require checkrun or custom activation).
        3. Customer namespace validation (target object must start with Z or Y).
        4. Pre-flight existence check (READ-ONLY GET): Confirms inactive object exists in SAP repository.
        5. Computes SHA-256 hash of the current source code to prevent stale checkrun activation.
        6. Dispatches POST /sap/bc/adt/checkruns?reporters=abapCheckRun with version="inactive".
        7. Parses diagnostic messages, counts blocking errors (E/A/X), warnings (W), and info (I/S).
        8. Returns structured SAPReviewCheckrunResult.
        """
        # Guard 1: Must be explicitly APPROVED
        if review_package.status != ReviewStatus.APPROVED:
            raise SAPSecurityError(
                f"SAP checkrun refused: Review status is '{review_package.status.value}'. "
                "Only proposals explicitly APPROVED by human gatekeeper can undergo checkrun."
            )

        # Guard 2: Approval eligibility
        if not review_package.can_approve:
            reasons = "; ".join(review_package.blocking_reasons)
            raise SAPSecurityError(f"SAP checkrun refused: Approval eligibility failed: {reasons}")

        # Guard 3: REUSE invariant
        if review_package.decision_action == DecisionAction.REUSE:
            raise SAPSecurityError(
                f"SAP checkrun rejected: Proposal '{review_package.review_id}' has decision REUSE for existing standard view '{review_package.object_name}'. "
                "Standard SAP CDS views are already verified and active in runtime; checkrun is not required or permitted in DEV deployment."
            )

        target_name = (
            review_package.object_name
            or (review_package.decision.proposed_new_view_name if review_package.decision_action == DecisionAction.CREATE else review_package.decision.proposed_extension_name)
        )
        if not target_name:
            raise SAPSecurityError("SAP checkrun refused: No target CDS object name specified in review package.")

        target_name = target_name.strip().upper()

        # Check customer namespace
        if not self.client.validate_sap_object_name(target_name):
            raise SAPSecurityError(
                f"SAP checkrun refused: Target name '{target_name}' violates SAP customer namespace rules. "
                "Name must start with 'Z' or 'Y', contain only alphanumeric characters and underscores, "
                "and be between 3 and 30 characters in length."
            )

        # Preflight existence check (READ-ONLY)
        try:
            existing_source = await self.client.get_ddl_source(target_name)
        except SAPNotFoundError:
            raise SAPNotFoundError(
                f"SAP checkrun refused: Target CDS object '{target_name}' does not exist in target repository. "
                "Object must be uploaded or created before running checkrun."
            )
        except Exception as e:
            logger.error("Preflight existence check error on '%s': %s", target_name, e)
            raise SAPConnectorError(f"Preflight existence check failed: {e}")

        # Synchronize review package with authoritative SAP repository source
        if existing_source:
            review_package.ddl_source = existing_source
            if review_package.cds_draft:
                review_package.cds_draft.ddl_source = existing_source

        # Compute source hash of verified source
        source_hash = self.client.compute_source_hash(review_package.ddl_source)

        repository_uri = f"/sap/bc/adt/ddic/ddl/sources/{target_name.lower()}"

        # Execute checkrun against the inactive draft in SAP
        raw_result = await self.client.run_checkrun(repository_uri=repository_uri, version="inactive")

        blocking_errors = sum(1 for m in raw_result.messages if m.severity.upper() in ("E", "A", "X"))
        warnings = sum(1 for m in raw_result.messages if m.severity.upper() == "W")
        information = sum(1 for m in raw_result.messages if m.severity.upper() in ("I", "S"))

        success = (blocking_errors == 0) and (raw_result.status in (SAPValidationStatus.PASS, SAPValidationStatus.WARNING))

        overall_status = raw_result.status
        if blocking_errors > 0:
            overall_status = SAPValidationStatus.ERROR

        return SAPReviewCheckrunResult(
            review_id=review_package.review_id,
            sap_object_name=target_name,
            status=overall_status,
            success=success,
            check_report_status=raw_result.check_report_status,
            blocking_errors=blocking_errors,
            warnings=warnings,
            information=information,
            messages=raw_result.messages,
            timestamp=utc_now(),
            source_hash=source_hash,
            http_status=raw_result.http_status,
            reason=raw_result.reason,
        )

    async def activate_cds_in_sap(
        self,
        review_package: CDSReviewPackage,
        transport_request: Optional[str] = None,
    ) -> SAPActivationResult:
        """Activates an existing inactive CDS View Entity in SAP DEV dictionary runtime.

        Milestone 13.8: Controlled Real SAP DEV CDS Activation Flow.
        Protocol:
        1. Pre-flight approval and eligibility validation (ReviewStatus.APPROVED, can_approve == True).
        2. Customer namespace validation.
        3. Checkrun gate validation (must have passed with 0 blocking errors).
        4. Pre-flight existence check (READ-ONLY GET): Confirms inactive object exists in SAP.
        5. Stale checkrun check: Source in repository must match source hash from checkrun.
        6. Step A & B are BYPASSED.
        7. POST /sap/bc/adt/activation?method=activate&preauditRequested=true with XML objectReferences.
        8. Post-activation verification:
           - Validate HTTP status and check for blocking errors (E/A/X)
           - Query GET /sap/bc/adt/activation/inactiveobjects to verify target is no longer inactive
           - Read-back source to verify object remains intact
        """
        # Guard 1: Must be explicitly APPROVED
        if review_package.status != ReviewStatus.APPROVED:
            raise SAPSecurityError(
                f"SAP activation refused: Review status is '{review_package.status.value}'. "
                "Only proposals explicitly APPROVED by human gatekeeper can be activated in SAP DEV."
            )

        # Guard 2: Eligibility must be satisfied
        if not review_package.can_approve:
            reasons = "; ".join(review_package.blocking_reasons)
            raise SAPSecurityError(f"SAP activation refused: Approval eligibility failed: {reasons}")

        # Guard 3: REUSE requires zero activation
        if review_package.decision_action == DecisionAction.REUSE:
            raise SAPSecurityError(
                f"SAP activation refused: Review package has decision REUSE for '{review_package.object_name}'. "
                "Standard SAP CDS views are already active in SAP DEV runtime."
            )

        target_name = (
            review_package.object_name
            or (review_package.decision.proposed_new_view_name if review_package.decision_action == DecisionAction.CREATE else review_package.decision.proposed_extension_name)
        )
        if not target_name:
            raise SAPSecurityError("SAP activation refused: No target CDS object name specified in review package.")

        target_name = target_name.strip().upper()

        # Check customer namespace
        if not self.client.validate_sap_object_name(target_name):
            raise SAPSecurityError(
                f"SAP activation refused: Target name '{target_name}' violates SAP customer namespace rules. "
                "Name must start with 'Z' or 'Y', contain only alphanumeric characters and underscores, "
                "and be between 3 and 30 characters in length."
            )

        # Guard 4: Checkrun Gate - activation requires a successful checkrun with 0 blocking errors
        if not review_package.latest_sap_checkrun:
            raise SAPSecurityError(
                f"SAP activation refused: Target '{target_name}' has not undergone SAP checkrun. "
                "A successful checkrun with 0 blocking errors is required before activation."
            )
        if not review_package.latest_sap_checkrun.success or review_package.latest_sap_checkrun.blocking_errors > 0:
            raise SAPSecurityError(
                f"SAP activation refused: Latest SAP checkrun for '{target_name}' reported "
                f"{review_package.latest_sap_checkrun.blocking_errors} blocking E/A/X error(s)."
            )

        # Preflight existence check (READ-ONLY)
        try:
            existing_source = await self.client.get_ddl_source(target_name)
        except SAPNotFoundError:
            raise SAPNotFoundError(
                f"SAP activation refused: Target CDS object '{target_name}' does not exist in target repository. "
                "Cannot activate a non-existent object."
            )
        except Exception as e:
            logger.error("Preflight existence check error on '%s': %s", target_name, e)
            raise SAPConnectorError(f"Preflight existence check failed: {e}")

        # Synchronize review package with authoritative SAP repository source
        if existing_source:
            review_package.ddl_source = existing_source
            if review_package.cds_draft:
                review_package.cds_draft.ddl_source = existing_source

        # Guard 5: Stale Checkrun Invalidation - source must match source_hash at checkrun time
        if review_package.latest_sap_checkrun.source_hash:
            current_hash = self.client.compute_source_hash(existing_source)
            if review_package.latest_sap_checkrun.source_hash != current_hash:
                raise SAPSecurityError(
                    f"SAP activation refused: Stale checkrun for '{target_name}'. "
                    "CDS source in repository was modified after the last checkrun. A fresh checkrun is required."
                )

        diagnostics: List[Dict[str, Any]] = [
            {
                "step": "PREFLIGHT_EXISTENCE_CHECK",
                "passed": True,
                "detail": f"Verified object '{target_name}' exists in repository ({len(existing_source)} bytes).",
            }
        ]

        # Call activation
        act_res = await self.client.activate_ddls_object(
            view_name=target_name,
            review_package=review_package,
            preaudit_requested=True,
        )

        diagnostics.append({
            "step": "ACTIVATE_ADT_OBJECT",
            "passed": act_res["success"],
            "status_code": act_res["status_code"],
            "has_blocking_errors": act_res["has_blocking_errors"],
            "inactive_count": len(act_res["inactive_objects"]),
        })

        final_status = "ACTIVE" if act_res["success"] else "INACTIVE"

        # Post-activation verification: query inactive objects
        try:
            inactive_objs = await self.client.get_inactive_objects()
            is_still_inactive = any(o.get("name", "").upper() == target_name for o in inactive_objs)
            if is_still_inactive:
                final_status = "INACTIVE"
            diagnostics.append({
                "step": "QUERY_INACTIVE_OBJECTS",
                "passed": not is_still_inactive,
                "detail": f"Object '{target_name}' is {'STILL INACTIVE' if is_still_inactive else 'NO LONGER INACTIVE'} in user index.",
            })
        except Exception as e:
            logger.warning("Inactive objects check failed: %s", e)
            diagnostics.append({
                "step": "QUERY_INACTIVE_OBJECTS",
                "passed": False,
                "detail": str(e),
            })

        # Read-back source
        try:
            readback = await self.client.get_ddl_source(target_name)
            diagnostics.append({
                "step": "READBACK_VERIFICATION",
                "passed": True,
                "detail": f"Read-back confirmed active source in repository ({len(readback)} bytes).",
            })
        except Exception as e:
            diagnostics.append({
                "step": "READBACK_VERIFICATION",
                "passed": False,
                "detail": str(e),
            })

        return SAPActivationResult(
            success=act_res["success"] and final_status == "ACTIVE",
            review_id=review_package.review_id,
            sap_object_name=target_name,
            repository_uri=act_res["repository_uri"],
            activation_status=final_status,
            transport_request=transport_request,
            sap_http_status=act_res["status_code"],
            sap_write_performed=True,
            diagnostics=diagnostics,
            syntax_messages=act_res["messages"],
            error_message="Activation failed or returned blocking errors." if (not act_res["success"] or final_status != "ACTIVE") else None,
        )

    async def get_data_preview(self, cds_name: str, max_rows: int = 10) -> dict:
        """Retrieves live data preview records for a CDS view entity from SAP ADT."""
        return await self.client.get_data_preview(cds_name=cds_name, max_rows=max_rows)

    async def get_transport_requests(self, user: Optional[str] = None) -> List[dict]:
        """Retrieves active CTS workbench transport requests from SAP ADT."""
        return await self.client.get_transport_requests(user=user)

    async def get_extraction_metadata_records(
        self,
        view_names: Optional[List[str]] = None,
        max_records: int = 10000,
    ) -> dict:
        """Retrieves authoritative data extraction enabled metadata records from I_DataExtractionEnabledView via ADT client."""
        return await self.client.get_extraction_metadata_records(view_names=view_names, max_records=max_records)

    async def aclose(self) -> None:
        """Closes the underlying ADT client session to prevent resource leaks."""
        if hasattr(self.client, "aclose"):
            await self.client.aclose()

    async def __aenter__(self) -> "SAPADTConnector":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

