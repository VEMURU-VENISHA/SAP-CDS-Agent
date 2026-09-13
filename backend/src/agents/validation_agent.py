"""Validation Agent: Performs static local validation of synthesized CDS drafts."""

import re
from typing import Any, Dict, List, Optional
from src.agents.base import BaseAgent
from src.agents.state import CDSWorkflowState
from src.models.domain import CDSDraft, DecisionAction, SAPValidationStatus, ValidationResult
from src.sap.connector import get_sap_connector
from src.sap.interface import ISAPConnector


class ValidationAgent(BaseAgent):
    """Validates CDS draft artifacts against SAP clean-core standards, syntax rules, and naming conventions.

    Performs Dual-Gate Validation:
    1. Gate 1: Local static clean-core analysis (identifier length, namespace Z/Y, unique aliases, auth checks, braces, semicolon).
    2. Gate 2: Real read-only SAP ADT checkrun:
       - For existing repository objects (e.g. REUSE recommendation), executes POST /sap/bc/adt/checkruns?reporters=abapCheckRun.
       - For unpersisted drafts (CREATE/EXTEND), SAP status remains UNAVAILABLE:
         'Unpersisted Draft — SAP ADT checkrun requires a repository object URI.'
       - A failed SAP checkrun (ERROR) marks draft REJECTED and halts progression.
       - Absolutely zero SAP write operations are performed.
    """

    def __init__(self, connector: Optional[ISAPConnector] = None):
        super().__init__(
            name="ValidationAgent",
            description="Performs dual-gate (local static + remote SAP ADT checkrun) validation of CDS drafts.",
        )
        self.connector = connector or get_sap_connector()

    async def run(self, state: CDSWorkflowState) -> CDSWorkflowState:
        code = state.get("generated_cds_code")
        decision = state.get("decision")
        draft: Optional[CDSDraft] = state.get("cds_draft")
        candidates = state.get("candidates", [])
        req = state.get("requirement")

        if not code and not draft:
            state.setdefault("errors", []).append("ValidationAgent: No code or draft available to validate.")
            return state

        # Case 1: REUSE recommendation
        if decision and decision.action == DecisionAction.REUSE:
            rec_view = decision.recommended_view or (draft.source_views[0] if draft and draft.source_views else None)
            repo_uri = f"/sap/bc/adt/ddic/ddl/sources/{rec_view.lower()}" if rec_view else None

            sap_status = SAPValidationStatus.UNAVAILABLE
            sap_reason = "SAP connector unconnected or unconfigured."
            sap_checkrun_res = None
            syntax_errors: List[str] = []
            governance_warnings: List[str] = []
            details: List[Dict[str, Any]] = [
                {"check": "Standard VDM View Reuse", "passed": True, "detail": f"Reusing standard SAP released view '{rec_view}' as-is."},
                {"check": "Clean Core Footprint", "passed": True, "detail": "Zero custom ABAP/CDS code deployed."},
            ]
            is_valid = True

            if repo_uri and self.connector:
                try:
                    is_conn = await self.connector.is_connected()
                    if is_conn:
                        sap_res = await self.connector.validate_cds(view_definition=code or "", repository_uri=repo_uri)
                        sap_status = sap_res.sap_validation_status
                        sap_checkrun_res = sap_res.sap_checkrun_result
                        sap_reason = sap_res.sap_checkrun_reason

                        if sap_status == SAPValidationStatus.ERROR:
                            is_valid = False
                            syntax_errors.extend(sap_res.syntax_errors)
                            details.append({"check": "SAP ADT Remote Checkrun", "passed": False, "detail": "SAP compiler errors detected."})
                        elif sap_status == SAPValidationStatus.WARNING:
                            governance_warnings.extend(sap_res.governance_warnings)
                            details.append({"check": "SAP ADT Remote Checkrun", "passed": True, "detail": f"SAP checkrun passed with {len(sap_res.governance_warnings)} warning(s)."})
                        elif sap_status == SAPValidationStatus.PASS:
                            details.append({"check": "SAP ADT Remote Checkrun", "passed": True, "detail": "All SAP syntax/compiler checks passed cleanly."})
                        else:
                            details.append({"check": "SAP ADT Remote Checkrun", "passed": False, "detail": sap_reason or "SAP checkrun unavailable."})
                    else:
                        sap_status = SAPValidationStatus.UNAVAILABLE
                        sap_reason = "SAP DEV system is offline or unconnected."
                        details.append({"check": "SAP ADT Remote Checkrun", "passed": False, "detail": sap_reason})
                except Exception as e:
                    sap_status = SAPValidationStatus.UNAVAILABLE
                    sap_reason = f"SAP checkrun call failed: {e}"
                    details.append({"check": "SAP ADT Remote Checkrun", "passed": False, "detail": sap_reason})

            validation = ValidationResult(
                is_valid=is_valid,
                syntax_errors=syntax_errors,
                naming_convention_violations=[],
                clean_core_compliance_score=100.0 if is_valid else 0.0,
                governance_warnings=governance_warnings,
                details=details,
                sap_validation_status=sap_status,
                sap_checkrun_result=sap_checkrun_res,
                sap_checkrun_reason=sap_reason,
            )
            if draft:
                draft.generation_status = "VALIDATED" if is_valid else "REJECTED"
                draft.sap_validation_status = sap_status
            state["validation_result"] = validation
            self.log_audit(state, "VALIDATION_COMPLETED", {"is_valid": is_valid, "action": "REUSE", "sap_status": sap_status.value})
            state["current_step"] = "GOVERNANCE"
            return state

        # Case 2: INSUFFICIENT_EVIDENCE
        if decision and decision.action == DecisionAction.INSUFFICIENT_EVIDENCE:
            validation = ValidationResult(
                is_valid=False,
                syntax_errors=[],
                naming_convention_violations=[],
                clean_core_compliance_score=0.0,
                governance_warnings=["Generation halted: insufficient verified evidence to validate CDS artifact."],
                details=[
                    {"check": "Sufficient Evidence Check", "passed": False, "detail": "Unresolved association targets or ambiguous metadata."},
                ],
                sap_validation_status=SAPValidationStatus.INSUFFICIENT_EVIDENCE,
                sap_checkrun_reason="Halting validation: Insufficient verified SAP evidence in requirement mapping.",
            )
            if draft:
                draft.generation_status = "INSUFFICIENT_EVIDENCE"
                draft.sap_validation_status = SAPValidationStatus.INSUFFICIENT_EVIDENCE
            state["validation_result"] = validation
            self.log_audit(state, "VALIDATION_HALTED", {"reason": "INSUFFICIENT_EVIDENCE"})
            state["current_step"] = "GOVERNANCE"
            return state

        # Case 3: EXTEND, CREATE, and SKELETON drafts
        syntax_errors: List[str] = []
        naming_violations: List[str] = []
        governance_warnings: List[str] = []
        details: List[Dict[str, Any]] = []

        target_code = draft.ddl_source if draft else (code or "")
        obj_name = draft.object_name if draft else (decision.proposed_new_view_name or "ZC_CustomCDSView" if decision else "ZC_CustomCDSView")
        obj_type = draft.object_type if draft else "VIEW_ENTITY"

        # Check A: Identifier validation for Object Name
        if len(obj_name) > 30:
            naming_violations.append(
                f"Object name '{obj_name}' exceeds SAP ABAP limit of 30 characters ({len(obj_name)} chars)."
            )
        if not re.match(r"^[A-Za-z][A-Za-z0-9_\/]{0,29}$", obj_name):
            naming_violations.append(
                f"Object name '{obj_name}' contains invalid characters for an ABAP CDS identifier."
            )

        # Customer namespace check for custom objects / extensions
        if obj_type in ("CUSTOM_VIEW_ENTITY", "VIEW_ENTITY_EXTENSION"):
            if not (obj_name.startswith("Z") or obj_name.startswith("Y")):
                naming_violations.append(
                    f"Custom object name '{obj_name}' must start with customer namespace prefix 'Z' or 'Y'."
                )
        details.append({"check": "Object Identifier Rules", "passed": len(naming_violations) == 0})

        # Check B: Unique field aliases and field identifier validity
        if draft and draft.fields:
            seen_aliases = set()
            for f in draft.fields:
                f_alias = f.alias or f.field_name
                # Length check
                if len(f_alias) > 30:
                    naming_violations.append(
                        f"Field alias '{f_alias}' exceeds SAP 30-character limit ({len(f_alias)} chars)."
                    )
                # Alphanumeric / underscore check
                if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,29}$", f_alias):
                    naming_violations.append(
                        f"Field alias '{f_alias}' contains invalid characters. Must be alphanumeric and start with a letter."
                    )
                # Duplicate check
                f_key = f_alias.lower()
                if f_key in seen_aliases:
                    syntax_errors.append(
                        f"Duplicate field alias '{f_alias}' detected in SELECT projection list."
                    )
                seen_aliases.add(f_key)

            details.append({"check": "Unique Field Aliases", "passed": len(syntax_errors) == 0})

        # Check C: Mandatory Access Control annotation (for custom view entities)
        if obj_type in ("CUSTOM_VIEW_ENTITY", "COMPOSITION_PROPOSAL"):
            has_auth = "@AccessControl.authorizationCheck" in target_code
            if not has_auth:
                syntax_errors.append("Missing mandatory @AccessControl.authorizationCheck annotation.")
            details.append({"check": "Authorization Check Annotation", "passed": has_auth})

            has_label = "@EndUserText.label" in target_code
            if not has_label:
                governance_warnings.append("Missing recommended @EndUserText.label annotation.")
            details.append({"check": "EndUserText Label Annotation", "passed": has_label})

        # Check D: Source views presence in discovered candidates
        if draft and draft.source_views:
            cand_names = [c.view_name for c in candidates]
            for src in draft.source_views:
                if cand_names and src not in cand_names and not src.startswith("I_BusinessEntity"):
                    governance_warnings.append(
                        f"Source entity '{src}' was not found among discovered SAP candidate views."
                    )
            details.append({"check": "Source Views Verified", "passed": True})

        # Check E: Missing required concepts detection
        if req and req.required_fields and draft:
            projected_names = {f.field_name.lower() for f in draft.fields}
            unresolved_set = {u.lower() for u in draft.unresolved_items}
            for rf in req.required_fields:
                rf_lower = rf.lower()
                if rf_lower not in projected_names and rf_lower not in unresolved_set:
                    governance_warnings.append(
                        f"Requested field '{rf}' is not projected in the generated CDS draft."
                    )

        # Check F: DDL structural integrity (matching braces and semicolon)
        open_braces = target_code.count("{")
        close_braces = target_code.count("}")
        if open_braces != close_braces:
            syntax_errors.append(
                f"Mismatched curly braces in CDS DDL definition ({open_braces} open vs {close_braces} close)."
            )

        clean_code = re.sub(r"/\*[\s\S]*?\*/", "", target_code).strip()
        if not clean_code.endswith(";"):
            # If DDL contains a view/extend entity definition, it must end with ';'
            if "define view" in clean_code.lower() or "extend view" in clean_code.lower():
                syntax_errors.append("CDS DDL definition must terminate with a semicolon ';'.")

        details.append({
            "check": "DDL Syntax Structure",
            "passed": open_braces == close_braces and clean_code.endswith(";"),
        })

        # Score computation
        is_valid = len(syntax_errors) == 0 and len(naming_violations) == 0
        score = 100.0
        score -= len(syntax_errors) * 25.0
        score -= len(naming_violations) * 15.0
        score -= len(governance_warnings) * 5.0
        score = max(0.0, min(100.0, score))

        # Gate 2: Remote SAP ADT Checkrun evaluation
        if not is_valid:
            sap_status = SAPValidationStatus.UNAVAILABLE
            sap_reason = "Local static validation failed; remote SAP checkrun bypassed."
            details.append({"check": "SAP ADT Remote Checkrun", "passed": False, "detail": sap_reason})
        else:
            # In-memory unpersisted draft (CREATE or EXTEND)
            sap_status = SAPValidationStatus.UNAVAILABLE
            sap_reason = "Unpersisted Draft — SAP ADT checkrun requires a repository object URI."
            details.append({"check": "SAP ADT Remote Checkrun", "passed": False, "detail": sap_reason})

        if draft:
            draft.validation_errors = syntax_errors + naming_violations
            draft.generation_status = "VALIDATED" if is_valid else "REJECTED"
            draft.sap_validation_status = sap_status

        validation = ValidationResult(
            is_valid=is_valid,
            syntax_errors=syntax_errors,
            naming_convention_violations=naming_violations,
            clean_core_compliance_score=score,
            governance_warnings=governance_warnings,
            details=details,
            sap_validation_status=sap_status,
            sap_checkrun_reason=sap_reason,
        )

        state["validation_result"] = validation
        self.log_audit(
            state,
            "VALIDATION_COMPLETED",
            {
                "is_valid": validation.is_valid,
                "score": validation.clean_core_compliance_score,
                "syntax_errors_count": len(syntax_errors),
                "naming_violations_count": len(naming_violations),
            },
        )
        state["current_step"] = "GOVERNANCE"
        return state

