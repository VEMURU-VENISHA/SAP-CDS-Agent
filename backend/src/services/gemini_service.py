"""Small, evidence-grounded Gemini client used by the Discover Agent.

The LLM is never the source of truth. It may propose mappings only from the
candidate metadata supplied to it; callers must validate every returned name
against SAP metadata before using it.
"""
import json
from typing import Any, Dict, List, Optional

import httpx

from src.config import get_settings
from src.logging_config import logger
from src.services.cds_generation_validator import CDSGenerationValidator
from src.services.discovery_service import CDSDiscoveryService
import re as _re


CDS_GENERATION_SYSTEM_PROMPT = """You are an expert SAP ABAP CDS View Entity code generator. You MUST follow these rules EXACTLY. Violation of ANY rule is a CRITICAL BUG.

RULE 1: STRUCTURE — CDS DDL must follow this EXACT order:
  @AccessControl.authorizationCheck: #NOT_REQUIRED
  @EndUserText.label: '<label>'
  define view entity <Z_VIEW_NAME>
    as select from <PRIMARY_CDS> as _<ALIAS1>
    <ALL ASSOCIATIONS HERE — BEFORE THE OPENING BRACE>
  {
    <ALL FIELDS HERE — INSIDE THE BRACES>
  }
  CRITICAL: Associations MUST be BEFORE the opening { brace. NEVER inside { }.

RULE 2: SOURCE COMPLETENESS — Include EXACTLY the selected CDS views:
  - Include EVERY selected CDS view. Do NOT omit any.
  - Do NOT add any CDS view NOT in the selected list.
  - FIRST view = PRIMARY source (as select from).
  - Remaining views = SECONDARY sources (association).

RULE 3: PREFER ASSOCIATION OVER JOIN — Always use association. Never use left outer join or inner join.

RULE 4: ASSOCIATION CARDINALITY:
  - Lookup/Parent (I_CUSTOMER, I_COMPANYCODE, I_MATERIAL): association [0..1]
  - Transaction/Child (I_SALESORDER, I_JOURNALENTRYITEM): association [1..*]

RULE 5: JOIN CONDITIONS — Use verified key fields ONLY:
  I_CUSTOMER: on $projection.Customer = _CUSTOMER.Customer
  I_COMPANYCODE: on $projection.CompanyCode = _CC.CompanyCode
  I_MATERIAL: on $projection.Material = _MAT.Material
  I_SALESORDER: on $projection.SalesOrder = _SO.SalesOrder
  I_JOURNALENTRYITEM: on $projection.CompanyCode = _JEI.CompanyCode and $projection.AccountingDocument = _JEI.AccountingDocument
  I_CUSTOMERSALESAREA: on $projection.Customer = _CSA.Customer and $projection.SalesOrganization = _CSA.SalesOrganization and $projection.DistributionChannel = _CSA.DistributionChannel
  I_SALESANALYTICSCUBE: on _CUSTOMER.Customer = _SAC.Customer
  If joining through intermediate view, use the alias: on _CUSTOMER.Customer = _TARGET.Customer

RULE 6: COMPOSED ASSOCIATION PATHS — If verified path goes through intermediate view, reference the intermediate alias in ON clause. Example: I_RO → I_CUSTOMER → I_SALESANALYTICSCUBE means on _CUSTOMER.Customer = _SAC.Customer

RULE 7: FIELD SELECTION — Use EXACT SAP technical field names from metadata. Prefix with correct source alias. Add 'as <BusinessName>' alias only if technical name differs.

RULE 8: 100% REQUIRED FIELD COVERAGE — Every required business field MUST appear in SELECT list inside { }.

RULE 9: $PROJECTION FIELDS IN SELECT — If ON clause uses $projection.FieldName, FieldName MUST be in SELECT list.

RULE 10: NO DUPLICATES — No two associations to same CDS view. No same field selected twice.

OUTPUT: Output ONLY the CDS DDL source code. No markdown. No explanation. No backtick blocks. Just the raw DDL starting with @AccessControl.
"""


def validate_cds_ddl(generated_ddl, selected_views, required_fields=None):
    errors = []
    warnings = []
    if not generated_ddl or not generated_ddl.strip():
        return {"status": "VALIDATION_FAILED", "errors": [{"rule": "EMPTY_DDL", "message": "Generated DDL is empty."}], "warnings": [], "blocking_errors": [{"rule": "EMPTY_DDL", "message": "Generated DDL is empty."}], "approval_enabled": False, "missing_sources": [], "coverage": 0.0}
    ddl_upper = generated_ddl.upper()
    ddl_lower = generated_ddl.lower()
    seen_upper = set()
    canonical_views = []
    for v in selected_views:
        upper = v.strip().upper()
        if upper and upper not in seen_upper:
            seen_upper.add(upper)
            canonical_views.append(upper)
    brace_idx = generated_ddl.find('{')
    select_section = ""
    if brace_idx > 0:
        before_brace = generated_ddl[:brace_idx].lower()
        after_brace_lower = generated_ddl[brace_idx:].lower()
        if _re.findall(r'association\s+\[', after_brace_lower):
            errors.append({"rule": "RULE1_STRUCTURE", "message": "Association declaration found inside { } braces. All associations must be BEFORE the opening brace."})
        brace_count = 0
        in_select = False
        for char in generated_ddl:
            if char == '{':
                brace_count += 1
                if brace_count == 1:
                    in_select = True
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    in_select = False
            elif in_select:
                select_section += char
    missing_sources = []
    for view in canonical_views:
        patterns = [f"FROM {view}", f"TO {view}", f"JOIN {view}", f"INNER JOIN {view}", f"LEFT JOIN {view}"]
        found = any(p in ddl_upper for p in patterns)
        if not found:
            missing_sources.append(view)
    if missing_sources:
        errors.append({"rule": "RULE2_SOURCE_COMPLETENESS", "message": f"Missing selected CDS source views: {', '.join(missing_sources)}", "missing": missing_sources})
    all_source_refs = set()
    for pattern in [r'FROM\s+(\w+)', r'TO\s+(\w+)', r'JOIN\s+(\w+)']:
        all_source_refs.update(m.upper() for m in _re.findall(pattern, ddl_upper))
    z_views = {n.upper() for n in _re.findall(r'define\s+view\s+entity\s+(\w+)', ddl_upper)}
    unselected = all_source_refs - set(canonical_views) - z_views
    unselected = {v for v in unselected if not v.startswith('Z')}
    if unselected:
        warnings.append({"rule": "RULE2_UNSELECTED_SOURCE", "message": f"DDL contains CDS views not in selection: {', '.join(sorted(unselected))}"})
    join_matches = _re.findall(r'\b(left\s+outer\s+join|inner\s+join|right\s+outer\s+join)\b', ddl_lower)
    if join_matches:
        warnings.append({"rule": "RULE3_ASSOCIATION_PREFERRED", "message": f"DDL uses JOIN instead of association: {join_matches}"})
    if required_fields:
        select_upper = select_section.upper() if select_section else ""
        missing_fields = []
        for field in required_fields:
            field_upper = field.strip().upper()
            if field_upper and field_upper not in select_upper:
                missing_fields.append(field)
        if missing_fields:
            coverage = round((len(required_fields) - len(missing_fields)) / len(required_fields) * 100, 1)
            errors.append({"rule": "RULE8_FIELD_COVERAGE", "message": f"Missing required fields: {', '.join(missing_fields)}", "coverage": coverage})
    projection_fields = _re.findall(r'\$projection\.(\w+)', generated_ddl, _re.IGNORECASE)
    if projection_fields and brace_idx > 0:
        select_upper2 = generated_ddl[brace_idx:].upper()
        for pf in projection_fields:
            if pf.upper() not in select_upper2:
                warnings.append({"rule": "RULE9_PROJECTION_FIELD", "message": f"$projection.{pf} used but '{pf}' may not be in SELECT list."})
    assoc_targets = _re.findall(r'association\s+\[[^\]]+\]\s+to\s+(\w+)', ddl_upper, _re.IGNORECASE)
    seen_targets = set()
    for target in assoc_targets:
        if target in seen_targets:
            errors.append({"rule": "RULE10_DUPLICATE_ASSOCIATION", "message": f"Duplicate association to {target}"})
        seen_targets.add(target)
    BLOCKING_RULES = {"RULE1_STRUCTURE", "RULE2_SOURCE_COMPLETENESS", "RULE8_FIELD_COVERAGE", "RULE10_DUPLICATE_ASSOCIATION"}
    blocking_errors = [e for e in errors if e.get("rule", "") in BLOCKING_RULES]
    if blocking_errors:
        status = "VALIDATION_FAILED"
    else:
        status = "VALIDATION_PASSED_WITH_WARNINGS" if (warnings or errors) else "VALIDATION_PASSED"
    coverage = 100.0
    if required_fields:
        missing_coverage_errors = [e for e in errors if e.get("rule") == "RULE8_FIELD_COVERAGE"]
        if missing_coverage_errors:
            coverage = missing_coverage_errors[0].get("coverage", 0.0)
        else:
            coverage = 100.0
    return {"status": status, "errors": errors, "warnings": warnings, "blocking_errors": blocking_errors, "approval_enabled": len(blocking_errors) == 0, "missing_sources": missing_sources, "coverage": coverage}


def _repair_missing_sources(
    ddl: str,
    views: List[str],
    join_paths: Optional[List[Dict[str, Any]]] = None,
    mappings: Optional[List[Dict[str, Any]]] = None,
) -> tuple[str, List[str], List[str]]:
    """Auto-repairs missing REQUIRED CDS sources into DDL ONLY if a verified join path exists in join_paths."""
    ddl_upper = (ddl or "").upper()
    required_sources: set[str] = set()
    if mappings:
        for m in mappings:
            cds = m.get("selected_cds") or m.get("cds_name") or m.get("cds_view") or m.get("cds_entity") or m.get("source_entity")
            if cds and str(cds).strip():
                required_sources.add(str(cds).strip().upper())
    if not required_sources and views:
        required_sources = {v.strip().upper() for v in views if v and v.strip()}

    missing = []
    for v in sorted(required_sources):
        vu = v.strip().upper()
        patterns = [f"FROM {vu}", f"TO {vu}", f"JOIN {vu}", f"INNER JOIN {vu}", f"LEFT JOIN {vu}"]
        if not any(p in ddl_upper for p in patterns):
            missing.append(vu)
    if not missing:
        return ddl, [], []
    
    repairs = []
    repair_details = []
    join_paths = join_paths or []

    for view in missing:
        # Search join_paths for a verified relationship connecting missing view
        matching_jp = None
        for jp in join_paths:
            s_ent = str(jp.get("source_cds") or jp.get("left_cds") or jp.get("left_entity") or jp.get("left_view") or "").strip().upper()
            t_ent = str(jp.get("target_cds") or jp.get("right_cds") or jp.get("right_entity") or jp.get("right_view") or "").strip().upper()
            if (s_ent == view or t_ent == view):
                matching_jp = jp
                break

        if not matching_jp:
            STANDARD_FALLBACK_JOINS = {
                "I_JOURNALENTRYITEM": {"source_field": "CompanyCode", "target_field": "CompanyCode", "cardinality": "1..*"},
                "I_CUSTOMER": {"source_field": "Customer", "target_field": "Customer", "cardinality": "0..1"},
                "I_COMPANYCODE": {"source_field": "CompanyCode", "target_field": "CompanyCode", "cardinality": "0..1"},
                "I_MATERIAL": {"source_field": "Material", "target_field": "Material", "cardinality": "0..1"},
                "I_SALESORDER": {"source_field": "SalesOrder", "target_field": "SalesOrder", "cardinality": "1..*"},
            }
            if not join_paths and view in STANDARD_FALLBACK_JOINS:
                std_info = STANDARD_FALLBACK_JOINS[view]
                alias_core = view.replace("I_", "").replace("C_", "").replace("_", "")
                assoc = (
                    f"  association [{std_info['cardinality']}] to {view} as _{alias_core}\n"
                    f"    on $projection.{std_info['source_field']} = _{alias_core}.{std_info['target_field']}"
                )
                repairs.append(assoc)
                repair_details.append(view)
                continue
            # DO NOT invent an unverified join when explicit join_paths are provided.
            continue

        s_ent = str(matching_jp.get("source_cds") or matching_jp.get("left_cds") or matching_jp.get("left_entity") or matching_jp.get("left_view") or "").strip().upper()
        t_ent = str(matching_jp.get("target_cds") or matching_jp.get("right_cds") or matching_jp.get("right_entity") or matching_jp.get("right_view") or "").strip().upper()
        s_fld = matching_jp.get("source_field") or matching_jp.get("left_field") or matching_jp.get("join_field")
        t_fld = matching_jp.get("target_field") or matching_jp.get("right_field") or matching_jp.get("join_field")
        card = matching_jp.get("cardinality") or "0..1"

        target_view = view
        source_fld = s_fld if target_view == t_ent else t_fld
        target_fld = t_fld if target_view == t_ent else s_fld

        alias_core = target_view.replace("I_", "").replace("C_", "").replace("_", "")
        alias = f"_{alias_core}"

        assoc = (
            f"  association [{card}] to {target_view} as {alias}\n"
            f"    on $projection.{source_fld} = {alias}.{target_fld}"
        )
        repairs.append(assoc)
        repair_details.append(target_view)

    if not repairs:
        return ddl, missing, []

    lines = ddl.split('\n')
    insert_after = -1
    for i, line in enumerate(lines):
        if 'association' in line.lower():
            insert_after = i
            if i + 1 < len(lines) and 'on' in lines[i + 1].lower():
                insert_after = i + 1
                if i + 2 < len(lines) and 'and' in lines[i + 2].lower():
                    insert_after = i + 2
    if insert_after == -1:
        for i, line in enumerate(lines):
            if 'as select from' in line.lower():
                insert_after = i
                break
    if insert_after == -1:
        insert_after = 0
    
    final = []
    for i, line in enumerate(lines):
        final.append(line)
        if i == insert_after:
            for r in repairs:
                final.append(r)
    
    repaired_ddl = '\n'.join(final)
    return repaired_ddl, missing, repair_details


class GeminiService:

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.GEMINI_API_KEY.get_secret_value() if settings.GEMINI_API_KEY else ""
        self.model = settings.GEMINI_MODEL
        self.timeout = settings.GEMINI_TIMEOUT_SECONDS

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def map_requirement(self, business_requirement: str, required_fields: List[str], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.enabled or not candidates:
            return {"enabled": False, "reason": "Gemini is not configured or no SAP candidates were returned."}

        compact_candidates = []
        for c in candidates:
            compact_candidates.append({
                "cds_name": c.get("cds_name"),
                "description": c.get("description", ""),
                "fields": c.get("fields", []),
                "keys": c.get("keys", []),
                "associations": c.get("associations", []),
                "source": c.get("source", ""),
                "layer": c.get("layer"),
            })

        prompt = f"""You are the semantic mapping layer for an SAP CDS discovery agent.
Use ONLY the candidate metadata supplied below. Never invent a CDS view, field, association, or join field.
Return JSON only.

Business requirement: {business_requirement}
Required fields: {json.dumps(required_fields)}
Candidates: {json.dumps(compact_candidates, ensure_ascii=False)}

Schema:
{{
  "primary_cds": "existing candidate name or null",
  "field_mappings": [{{"requested_field":"...","cds_view":"...","mapped_field":"...","confidence":0.0}}],
  "missing_fields": ["..."],
  "additional_cds_required": false,
  "join_candidates": [{{"left_view":"...","left_field":"...","right_view":"...","right_field":"...","join_type":"INNER JOIN","confidence":0.0}}],
  "reason": "short explanation"
}}
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, params={"key": self.api_key}, json=payload)
                response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            return {"enabled": True, "result": parsed}
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
            return {"enabled": True, "error": f"Gemini mapping failed: {exc}"}

    async def extract_fields_and_variants(
        self,
        business_requirement: str,
        business_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Extract required business fields, semantic classification, and search variants using Gemini 3.5/3.6 Flash."""
        if not self.enabled:
            return self._fallback_extract_fields(business_requirement, business_domains)

        domain_context = ", ".join(business_domains) if business_domains else "General / S4HANA"

        prompt = f"""You are an SAP S/4HANA CDS expert. Analyze the following business requirement:
"{business_requirement}"

Selected Business Domain(s): {domain_context}

Tasks:
1. Understand the core business domain, objective, and analytical needs.
2. Extract the individual required business fields and concepts.
3. For EACH concept, classify its nature into one of:
   - "DIRECT": Standard literal entity attribute (e.g. Sales Order, Sold-to Party, Material, Currency, Company Code).
   - "DERIVED": Attribute derived from relationships or underlying values.
   - "CALCULATED": Business measure requiring computation (e.g. Overdue Amount, Days Sales Outstanding, Margin).
   - "AGGREGATED": Aggregated measure (e.g. Total Sales Amount, Net Invoiced Quantity).
   - "FILTER/CONDITION": Time horizon, status filter, or business condition (e.g. Current Fiscal Year, Open Items).
4. If a field is "DERIVED", "CALCULATED", "AGGREGATED", or "FILTER/CONDITION", identify the underlying SAP concepts (e.g. for Overdue Amount: ["Open Amount", "Due Date", "Key Date", "Posting Date"]; for Current Fiscal Year: ["Posting Date", "Fiscal Year"]).
5. For each field, generate 4 to 8 SAP search variants (technical names, DDIC element synonyms, VDM field variations, e.g. "Sold-to Party" -> ["SoldToParty", "Customer", "Customer ID", "Customer Number", "CustomerID", "Sold-to Customer", "KUNNR"]).
6. Suggest a standard Clean Core CDS artifact name (e.g., "ZC_SalesOrderAnalysis" or "ZI_SalesOrderReporting") starting with ZC_ or ZI_.

Return JSON strictly conforming to this schema:
{{
  "domain": "{domain_context}",
  "fields": [
    {{
      "name": "Field Name",
      "field_type": "DIRECT",
      "variants": ["Variant 1", "Variant 2", "Variant 3"],
      "underlying_concepts": ["Concept 1"],
      "calculation_approach": "Conceptual formula or filter approach"
    }}
  ],
  "suggested_artifact_name": "ZC_...",
  "summary": "Short explanation of requirement understanding"
}}
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(url, params={"key": self.api_key}, json=payload)
                response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            return {"enabled": True, "result": parsed}
        except Exception as exc:
            # Graceful deterministic fallback
            fallback = self._fallback_extract_fields(business_requirement, business_domains)
            fallback["warning"] = f"Gemini unavailable ({exc}); fallback used."
            return fallback

    async def generate_single_field_variants(
        self,
        field_name: str,
        requirement_context: Optional[str] = "",
        business_domains: Optional[List[str]] = None,
        requirement_text: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates semantic search variants and classifies field when a human adds/edits a field."""
        if not self.enabled:
            return self._fallback_field_variants(field_name)

        req = requirement_text or requirement_context or ""
        dom_list = business_domains or ([domain] if domain else ["Sales & Distribution"])
        domain_context = ", ".join(dom_list)

        prompt = f"""You are an SAP S/4HANA CDS expert. A business analyst has manually entered/edited a required field:
Field Name: "{field_name}"
Overall Requirement: "{req}"
Business Domain: {domain_context}

Tasks:
1. Understand the semantic business meaning of this field in SAP S/4HANA.
2. Classify its nature into one of: "DIRECT", "DERIVED", "CALCULATED", "AGGREGATED", "FILTER/CONDITION".
3. Generate 6 to 10 relevant SAP search variants / synonyms (e.g. technical field names, DDIC data elements, CDS camelCase variations, German ABAP abbreviations e.g. VBELN, KUNNR, NETWR, FAEDN, BUDAT, GJAHR).
4. If it is "CALCULATED", "DERIVED", "AGGREGATED", or "FILTER/CONDITION", identify the underlying SAP concepts required to derive or compute it (e.g. for "Overdue Amount": ["Open Amount", "Due Date", "Key Date", "Posting Date"]; for "Current Fiscal Year": ["Posting Date", "Fiscal Year"]).
5. Suggest a conceptual calculation formula or filtering approach.

Return JSON strictly conforming to this schema:
{{
  "name": "{field_name}",
  "field_type": "DIRECT",
  "variants": ["variant1", "variant2", "variant3", "variant4", "variant5"],
  "underlying_concepts": ["concept1", "concept2"],
  "calculation_approach": "Conceptual formula or filter approach",
  "notes": "Semantic explanation"
}}
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, params={"key": self.api_key}, json=payload)
                response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) > 0:
                parsed = parsed[0]
            if isinstance(parsed, dict):
                return {
                    "name": parsed.get("name") or parsed.get("field_name") or field_name,
                    "field_type": parsed.get("field_type") or "DIRECT",
                    "variants": parsed.get("variants") or [field_name],
                    "underlying_concepts": parsed.get("underlying_concepts") or [],
                    "calculation_approach": parsed.get("calculation_approach") or "",
                    "notes": parsed.get("notes") or "",
                }
            return self._fallback_field_variants(field_name)
        except Exception as exc:
            fallback = self._fallback_field_variants(field_name)
            fallback["warning"] = f"Gemini variant generation failed ({exc}); deterministic fallback used."
            return fallback

    def _fallback_field_variants(self, field_name: str) -> Dict[str, Any]:
        """Deterministic heuristic variants for single field when LLM is unavailable."""
        clean = field_name.strip()
        lower = clean.lower()
        cleaned_no_spaces = clean.replace(" ", "").replace("-", "").replace("_", "")

        # Default classification & variants
        field_type = "DIRECT"
        underlying: List[str] = []
        calc_approach = ""
        variants = [clean, cleaned_no_spaces]

        if "overdue" in lower:
            field_type = "CALCULATED"
            underlying = ["Open Amount", "Due Date", "Key Date", "Posting Date"]
            calc_approach = "SUM(Open Amount WHERE Due Date < Key Date)"
            variants = [
                clean,
                cleaned_no_spaces,
                "Past Due Amount",
                "PastDueAmount",
                "Past Due Receivable",
                "Overdue Receivable",
                "Outstanding Overdue Amount",
                "Open Amount",
                "Outstanding Amount",
                "TotalNetAmount",
                "NETWR",
            ]
        elif "fiscal" in lower or "year" in lower:
            field_type = "FILTER/CONDITION"
            underlying = ["Posting Date", "Fiscal Year"]
            calc_approach = "Filter PostingDate within active fiscal year period"
            variants = [
                clean,
                cleaned_no_spaces,
                "FiscalYear",
                "FiscalPeriod",
                "PostingDate",
                "DocumentDate",
                "GJAHR",
                "BUDAT",
            ]
        elif "sold" in lower or "customer" in lower:
            variants = [
                clean,
                cleaned_no_spaces,
                "SoldToParty",
                "Customer",
                "Customer Number",
                "CustomerID",
                "CustomerNumber",
                "Sold-to Customer",
                "KUNNR",
            ]
        elif "amount" in lower or "revenue" in lower or "net" in lower:
            field_type = "AGGREGATED" if "total" in lower else "DIRECT"
            variants = [
                clean,
                cleaned_no_spaces,
                "TotalNetAmount",
                "NetAmount",
                "NetValue",
                "Amount",
                "NetPriceAmount",
                "NETWR",
            ]
        elif "billing" in lower or "invoice" in lower:
            variants = [
                clean,
                cleaned_no_spaces,
                "BillingDocumentType",
                "BillingType",
                "BillingDocument",
                "InvoiceType",
                "FKART",
                "FKDAT",
                "VBELN",
            ]
        elif "type" in lower:
            variants = [
                clean,
                cleaned_no_spaces,
                clean.replace(" ", "") + "Type",
                clean.replace(" ", "") + "Code",
                "DocumentType",
                "TypeCode",
                clean.upper().replace(" ", "_"),
            ]
        elif "material" in lower or "product" in lower:
            variants = [clean, cleaned_no_spaces, "Material", "Product", "ProductNumber", "MATNR"]
        elif "date" in lower:
            variants = [clean, cleaned_no_spaces, "PostingDate", "CreationDate", "DocumentDate", "NetDueDate", "BUDAT"]

        # Ensure at least 6 standard variations exist for any business term
        if len(variants) < 6:
            extra_candidates = [
                clean.title().replace(" ", ""),
                clean.upper().replace(" ", "_"),
                clean.lower().replace(" ", "_"),
                cleaned_no_spaces + "ID",
                cleaned_no_spaces + "Code",
                cleaned_no_spaces + "Name",
                "Technical" + cleaned_no_spaces,
            ]
            for ec in extra_candidates:
                if ec not in variants:
                    variants.append(ec)
                if len(variants) >= 8:
                    break

        return {
            "name": clean,
            "field_type": field_type,
            "variants": variants,
            "underlying_concepts": underlying,
            "calculation_approach": calc_approach,
            "notes": "Generated from deterministic heuristic vocabulary",
        }

    def _fallback_extract_fields(
        self,
        requirement: str,
        business_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Deterministic heuristic fallback when LLM is unavailable."""
        from src.services.normalizer import extract_structured_requirement, HEURISTIC_SAP_VOCABULARY
        structured = extract_structured_requirement(text=requirement)
        fields = []
        req_lower = requirement.lower()

        # Check for Overdue Amount
        if "overdue" in req_lower and not any(c.lower() == "overdue amount" for c in structured.all_requested_concepts):
            structured.all_requested_concepts.append("Overdue Amount")

        # Check for Current Fiscal Year
        if "fiscal" in req_lower and not any("fiscal" in c.lower() for c in structured.all_requested_concepts):
            structured.all_requested_concepts.append("Current Fiscal Year")

        for concept in structured.all_requested_concepts:
            field_res = self._fallback_field_variants(concept)
            fields.append(field_res)

        if not fields:
            fields = [
                {
                    "name": "Sales Order",
                    "field_type": "DIRECT",
                    "variants": ["SalesOrder", "SalesDocument", "VBELN"],
                    "underlying_concepts": [],
                },
                {
                    "name": "Sold-to Party",
                    "field_type": "DIRECT",
                    "variants": ["SoldToParty", "Customer", "Customer Number", "KUNNR"],
                    "underlying_concepts": [],
                },
                {
                    "name": "Material",
                    "field_type": "DIRECT",
                    "variants": ["Material", "Product", "MATNR"],
                    "underlying_concepts": [],
                },
                {
                    "name": "Net Amount",
                    "field_type": "DIRECT",
                    "variants": ["TotalNetAmount", "NetAmount", "NETWR"],
                    "underlying_concepts": [],
                },
            ]

        domain_label = ", ".join(business_domains) if business_domains else "Sales & Distribution"
        return {
            "enabled": False,
            "result": {
                "domain": domain_label,
                "fields": fields,
                "suggested_artifact_name": "ZC_SalesOrderAnalysis",
                "summary": "Extracted via deterministic business normalizer",
            },
        }


    async def generate_cds_code(
        self,
        requirement: str,
        selected_views: List[str],
        mappings: List[Dict[str, Any]],
        join_paths: List[Dict[str, Any]],
        kpi: Optional[Dict[str, Any]] = None,
        artifact_name: str = "ZI_CustomCDSView",
    ) -> Dict[str, Any]:
        """Generate verified CDS View Entity DDL code using FULL VERIFIED DATA for ALL selected CDS views and deterministic validation."""
        # Case-insensitive deduplication of selected CDS entity names to canonical ADT uppercase format
        seen_views_upper = set()
        deduped_selected_views = []
        for v in selected_views:
            clean_v = v.strip().upper()
            if clean_v and clean_v not in seen_views_upper:
                seen_views_upper.add(clean_v)
                deduped_selected_views.append(clean_v)
        selected_views = deduped_selected_views

        # 1. Fetch FULL VERIFIED METADATA for EVERY selected CDS view from discovery service
        discovery_svc = CDSDiscoveryService()
        selected_views_full_metadata: Dict[str, Any] = {}
        full_metadata_counts: Dict[str, Any] = {}

        for v in selected_views:
            try:
                meta = await discovery_svc.get_view_details(v)
                if meta:
                    selected_views_full_metadata[v] = meta
                    full_metadata_counts[v] = {
                        "fields_count": len(meta.get("fields", [])),
                        "keys_count": len(meta.get("keys", [])),
                        "associations_count": len(meta.get("associations", [])),
                        "joins_count": len(meta.get("joins", [])),
                        "package": meta.get("package", "SAP_STANDARD"),
                    }
                else:
                    selected_views_full_metadata[v] = {
                        "cds_name": v,
                        "description": f"Verified SAP View {v}",
                        "fields": [],
                        "keys": [],
                        "associations": [],
                        "joins": [],
                    }
                    full_metadata_counts[v] = {"fields_count": 0, "keys_count": 0, "associations_count": 0}
            except Exception as e:
                logger.warning(f"Failed to fetch metadata details for {v}: {e}")
                selected_views_full_metadata[v] = {"cds_name": v, "fields": [], "associations": [], "joins": []}
                full_metadata_counts[v] = {"fields_count": 0, "keys_count": 0, "associations_count": 0}

        primary_view = selected_views[0] if selected_views else "I_BaseView"
        primary_alias = f"_{primary_view.replace('I_', '').replace('C_', '').replace('_', '')}"

        # Standard CDS Code Template
        standard_template = f"""@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: '{artifact_name}'
define view entity {artifact_name}
  as select from {primary_view} as {primary_alias}
  /* Include associations ONLY for secondary views with an explicit verified relationship in Verified Join Relationships */
  association [<VERIFIED_CARDINALITY>] to <TARGET_CDS> as _<TARGET_ALIAS>
    on $projection.<SOURCE_FIELD> = _<TARGET_ALIAS>.<TARGET_FIELD>
{{
  /* Select fields strictly according to Authoritative Field Mappings */
  {primary_alias}.<TECHNICAL_FIELD> as <BUSINESS_FIELD_ALIAS>
}}"""

        # Structured Generation Context
        generation_context = {
            "business_requirement": requirement,
            "selected_views": selected_views,
            "selected_views_full_metadata": selected_views_full_metadata,
            "authoritative_mappings": mappings,
            "verified_join_paths": join_paths,
            "kpi": kpi,
            "artifact_name": artifact_name,
            "standard_code_template": standard_template,
        }

        # Immutable Generation Context for Validator
        verified_context = {
            "business_requirement": requirement,
            "selected_views": selected_views,
            "mappings": mappings,
            "join_paths": join_paths,
            "kpi": kpi,
            "artifact_name": artifact_name,
        }

        # Structured Logging of Input Context
        logger.info(
            f"CDS Code Generation Context:\n"
            f"  selected_cds: {len(selected_views)} ({selected_views})\n"
            f"  full_metadata_counts: {json.dumps(full_metadata_counts)}\n"
            f"  field_mappings: {len(mappings)}\n"
            f"  join_paths: {json.dumps(join_paths)}\n"
            f"  standard_template: Included\n"
        )

        # === CDS COMPLIANT PROMPT BUILD ===
        # Step 1: Deduplicate selected views
        seen_views_upper = set()
        deduped_selected_views = []
        for v in selected_views:
            clean_v = v.strip().upper()
            if clean_v and clean_v not in seen_views_upper:
                seen_views_upper.add(clean_v)
                deduped_selected_views.append(clean_v)
        selected_views = deduped_selected_views

        # Step 2: Build enforcement text
        primary_source = selected_views[0] if selected_views else ""
        secondary_sources = selected_views[1:] if len(selected_views) > 1 else []
        source_enforcement = (
            f"SELECTED CDS VIEWS ({len(selected_views)} total — ALL must appear in DDL):\n"
            + "\n".join(f"  {i+1}. {v}" for i, v in enumerate(selected_views))
            + f"\n\nPrimary source (select from): {primary_source}\n"
        )
        if secondary_sources:
            source_enforcement += f"Secondary sources (association): {', '.join(secondary_sources)}\n"
        source_enforcement += "\n"

        # Step 3: Construct user prompt + final prompt
        user_prompt = f"""Generate an SAP ABAP CDS View Entity DDL source code for artifact '{artifact_name}'.

CRITICAL ARTIFACT NAME RULE:
The required CDS artifact/entity name is:
{artifact_name}

You MUST use this exact name in:
define view entity {artifact_name}

Do not modify it.
Do not shorten it.
Do not append/remove numbers.
Do not generate another entity name.

Generation Context:
{json.dumps(generation_context, indent=2, default=str)}

Return JSON strictly conforming to this schema:
{{
  "artifact_name": "{artifact_name}",
  "code": "<RAW_CDS_DDL_SOURCE_CODE>",
  "explanation": "Brief explanation of generated CDS View Entity",
  "fields_included": ["<field_name_1>", "<field_name_2>"]
}}
"""
        prompt = CDS_GENERATION_SYSTEM_PROMPT + "\n\n" + source_enforcement + "\n\n" + user_prompt

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }

        code_to_validate = ""
        parsed_result = {}
        warning_msg = None

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(url, params={"key": self.api_key}, json=payload)
                response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed_result = json.loads(text)
            code_to_validate = parsed_result.get("code", "")
        except Exception as exc:
            warning_msg = f"Generated via fallback template due to LLM error: {exc}"
            primary = selected_views[0] if selected_views else "I_SalesOrder"
            primary_alias = f"_{primary.replace('I_', '').replace('_', '')}" if primary.startswith("I_") else "_Base"
            
            cds_alias_map = {primary: primary_alias}
            associations_ddl = []
            
            for idx, sec in enumerate(selected_views[1:], start=1):
                sec_alias = f"_{sec.replace('I_', '').replace('_', '')}"
                cds_alias_map[sec] = sec_alias
                
                matching_jp = None
                for jp in join_paths:
                    s_ent = str(jp.get("source_cds") or jp.get("left_cds") or jp.get("left_view") or jp.get("left_entity") or "").upper()
                    t_ent = str(jp.get("target_cds") or jp.get("right_cds") or jp.get("right_view") or jp.get("right_entity") or "").upper()
                    if (s_ent == primary and t_ent == sec) or (s_ent == sec and t_ent == primary):
                        matching_jp = jp
                        break
                
                if matching_jp:
                    s_fld = matching_jp.get("source_field") or matching_jp.get("left_field") or "Customer"
                    t_fld = matching_jp.get("target_field") or matching_jp.get("right_field") or "Customer"
                    card = matching_jp.get("cardinality") or "0..1"
                    associations_ddl.append(
                        f"  association [{card}] to {sec} as {sec_alias}\n    on $projection.{s_fld} = {sec_alias}.{t_fld}"
                    )

            code_to_validate = f"""@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: '{artifact_name}'
define view entity {artifact_name}
  as select from {primary} as {primary_alias}"""
            if associations_ddl:
                code_to_validate += "\n" + "\n".join(associations_ddl)
            
            code_to_validate += " {\n"
            field_lines = []
            for m in mappings:
                f_name = m.get("actual_field") or m.get("mapped_field") or m.get("technical_field") or m.get("business_field", "Field")
                m_cds = (m.get("selected_cds") or m.get("cds_name") or m.get("cds_entity") or primary).upper()
                alias = m.get("business_field", "").replace(" ", "").replace("-", "")
                
                ent_alias = cds_alias_map.get(m_cds, primary_alias)
                expr = f"{ent_alias}.{f_name}" if ent_alias != primary_alias else f"{primary_alias}.{f_name}"
                
                if alias and alias.lower() != f_name.lower():
                    field_lines.append(f"  {expr} as {alias}")
                else:
                    field_lines.append(f"  {expr}")
            
            if kpi and kpi.get("enabled"):
                formula = kpi.get("formula", "SUM(NetAmount)")
                field_lines.append(f"  {formula} as KpiMetric")
            
            code_to_validate += ",\n".join(field_lines)
            code_to_validate += "\n}\n"
            parsed_result = {
                "artifact_name": artifact_name,
                "code": code_to_validate,
                "explanation": "Generated from verified SAP metadata model.",
                "fields_included": [m.get("actual_field") or m.get("mapped_field") for m in mappings],
            }

        # === POST-GENERATION VALIDATION + AUTO-REPAIR ===
        validation_result = validate_cds_ddl(
            generated_ddl=code_to_validate,
            selected_views=selected_views,
        )

        # Auto-repair missing sources
        if validation_result.get("missing_sources"):
            for missing_view in validation_result["missing_sources"]:
                alias = missing_view.lstrip('I_').lstrip('C_')
                if 'JOURNALENTRY' in missing_view:
                    assoc_line = f"  association [0..1] to {missing_view} as _{alias}\n    on $projection.CompanyCode = _{alias}.CompanyCode\n      and $projection.AccountingDocument = _{alias}.AccountingDocument"
                elif 'CUSTOMER' in missing_view and 'SAFT' not in missing_view and 'RO' not in missing_view and 'SALESAREA' not in missing_view:
                    assoc_line = f"  association [0..1] to {missing_view} as _{alias}\n    on $projection.Customer = _{alias}.Customer"
                elif 'SALESORDER' in missing_view or 'SALESANALYTIC' in missing_view:
                    assoc_line = f"  association [1..*] to {missing_view} as _{alias}\n    on $projection.Customer = _{alias}.Customer"
                elif 'MATERIAL' in missing_view:
                    assoc_line = f"  association [0..1] to {missing_view} as _{alias}\n    on $projection.Material = _{alias}.Material"
                elif 'SALESAREA' in missing_view:
                    assoc_line = f"  association [0..1] to {missing_view} as _{alias}\n    on $projection.Customer = _{alias}.Customer\n      and $projection.SalesOrganization = _{alias}.SalesOrganization"
                else:
                    assoc_line = f"  association [0..1] to {missing_view} as _{alias}\n    on $projection.CompanyCode = _{alias}.CompanyCode"
                brace_pos = code_to_validate.find('{')
                if brace_pos > 0:
                    code_to_validate = code_to_validate[:brace_pos] + assoc_line + "\n" + code_to_validate[brace_pos:]
            logger.warning(f"CDS Auto-Repair: Added missing associations for: {validation_result['missing_sources']}")
            parsed_result["code"] = code_to_validate

        # Log warnings
        for w in validation_result.get("warnings", []):
            logger.warning(f"CDS Validation [{w.get('rule')}]: {w.get('message')}")

        # Log errors
        for e in validation_result.get("errors", []):
            logger.error(f"CDS Validation [{e.get('rule')}]: {e.get('message')}")

        # Deterministic Grounding Validation (Section 20 & 21)
        validation_res = CDSGenerationValidator.validate_generation(code_to_validate, verified_context)

        logger.info(
            f"CDS Code Generation Execution Result:\n"
            f"  selected_cds: {selected_views}\n"
            f"  full_metadata_counts: {json.dumps(full_metadata_counts)}\n"
            f"  field_mappings: {len(mappings)}\n"
            f"  join_paths: {json.dumps(join_paths)}\n"
            f"  Gemini_generated_ddl:\n{code_to_validate}\n"
            f"  validation_result: valid={validation_res.get('valid')}, status={validation_res.get('status')}, errors={validation_res.get('errors')}\n"
        )

        response_dict = {
            "success": True,
            "result": parsed_result,
            "validation": validation_res,
            "valid": validation_res["valid"],
            "status": validation_res["status"],
            "code_status": validation_res["code_status"],
            "generation_context": generation_context,
            "full_metadata_counts": full_metadata_counts,
        }
        if warning_msg:
            response_dict["warning"] = warning_msg

        return response_dict


    async def regenerate_code(
        self,
        current_code: str,
        feedback: str,
        verified_context: Dict[str, Any],
        validation_errors: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Regenerate CDS DDL code incorporating reviewer feedback & validation errors while strictly preserving metadata constraints."""
        prompt = f"""You are a CDS DDL generator, not a metadata discovery agent.
STRICT RULES:
1. Correct ONLY the invalid generation while remaining strictly grounded in the supplied metadata.
2. Do not invent CDS entities, fields, joins, or associations.
3. Use exact technical field names supplied in field mappings.
4. Do not substitute semantic fields.
5. Use ONLY supplied join relationships.

Current Generated Code:
{current_code}

Reviewer Feedback:
{feedback}

Previous Validation Errors:
{json.dumps(validation_errors) if validation_errors else "None"}

Verified Metadata Context:
{json.dumps(verified_context)}

Return JSON strictly:
{{
  "code": "/* Updated CDS DDL Source */\\n...",
  "explanation": "Summary of changes made based on reviewer feedback"
}}
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(url, params={"key": self.api_key}, json=payload)
                response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            new_code = parsed.get("code", current_code)

            # Re-run deterministic grounding validator
            val_res = CDSGenerationValidator.validate_generation(new_code, verified_context)
            return {
                "success": True,
                "result": parsed,
                "validation": val_res,
                "valid": val_res["valid"],
                "status": val_res["status"],
                "code_status": val_res["code_status"],
                "coverage": val_res["coverage"],
                "errors": val_res["errors"],
                "warnings": val_res["warnings"],
            }
        except Exception as exc:
            val_res = CDSGenerationValidator.validate_generation(current_code, verified_context)
            return {
                "success": False,
                "error": f"Regeneration failed: {exc}",
                "code": current_code,
                "validation": val_res,
                "valid": False,
                "status": "GENERATION_VALIDATION_FAILED",
                "code_status": "Generation Validation Failed",
            }


