"""Concept Normalizer and Natural Language Requirement Parser.

Provides deterministic semantic token normalization and business concept extraction
for the SAP CDS Intelligence platform.
"""

import re
from typing import Dict, List, Optional, Set, Tuple
from src.models.domain import StructuredRequirement


# Standard heuristic SAP DDIC technical abbreviations (cross-module SAP technical synonym vocabulary)
HEURISTIC_SAP_VOCABULARY: Dict[str, List[str]] = {
    # Sales & Distribution
    "salesorder": ["vbeln", "salesdocument", "salesorderid", "salesordernumber", "order", "salesdoc"],
    "salesorderitem": ["posnr", "item", "orderitem", "itemnumber", "linenumber", "salesdocumentitem"],
    "salesorganization": ["vkorg", "salesorg", "salesorganizationid"],
    "distributionchannel": ["vtweg", "distchannel", "channel"],
    "division": ["spart", "divisioncode"],
    "deliverystatus": ["lfstk", "overallstatus", "status", "gbstk"],
    "salesordertype": ["auart", "ordertype", "salesdocumenttype"],
    "rejectionreason": ["abgru", "rejectionreasoncode"],

    # Sourcing & Procurement / Purchasing
    "purchaseorder": ["ebeln", "purchasedocument", "purchaseorderid", "pnumber", "po"],
    "purchaseorderitem": ["ebelp", "poitem", "purchaseorderitemnumber"],
    "purchasingorganization": ["ekorg", "purchorg"],
    "purchasinggroup": ["ekgrp", "purchgroup"],
    "supplier": ["lifnr", "vendor", "supplierid", "vendorid", "suppliernumber"],

    # Billing & Invoicing
    "billingdocument": ["vbeln_vf", "billingdoc", "invoicenumber", "invoice", "billdoc"],
    "billingdocumentitem": ["posnr_vf", "billingitem", "invoiceitem"],
    "billingdate": ["fkdat", "invoicedate"],
    "billingtype": ["fpart", "invoicetype"],

    # Finance & Accounting
    "accountingdocument": ["belnr", "journalentry", "accountingdoc", "documentnumber", "docnumber"],
    "accountingdocumentitem": ["buzei", "journalentryitem", "lineitem", "itemnumber"],
    "companycode": ["bukrs", "company", "cocode", "companycodeid"],
    "fiscalyear": ["gjahr", "fiscalyr", "year"],
    "fiscalperiod": ["poper", "monat", "postingperiod", "period"],
    "glaccount": ["saknr", "racct", "glaccountnumber", "account", "generalledgeraccount"],
    "profitcenter": ["prctr", "profitcenterid"],
    "costcenter": ["kostl", "costcenterid"],
    "controllingarea": ["kokrs", "coarea"],

    # Master Data
    "customer": ["kunnr", "soldtoparty", "customerid", "customernumber", "client", "shiptoparty", "billtoparty", "payer"],
    "material": ["matnr", "product", "materialid", "productid", "itemmaterial", "materialnumber"],
    "businesspartner": ["partner", "bp", "businesspartnerid", "partnernumber"],

    # Logistics, Plant & Inventory
    "plant": ["werks", "plantid", "factory", "site"],
    "storagelocation": ["lgort", "storage_location", "storloc"],
    "deliverydocument": ["vbeln_vl", "delivery", "outbounddelivery"],

    # Measures, Quantities & Currencies
    "netamount": ["netwr", "totalnetamount", "netvalue", "amount", "netprice"],
    "grossamount": ["brtwr", "totalgrossamount", "grossvalue", "grossprice"],
    "taxamount": ["mwsbp", "taxvalue", "tax"],
    "currency": ["waerk", "transactioncurrency", "currencycode", "doccurrency", "currencykey"],
    "quantity": ["menge", "orderquantity", "salesquantity", "billedquantity", "orderqty"],
    "unitofmeasure": ["meins", "vrkme", "baseunit", "salesunit", "uom", "unit"],

    # Administrative & Dates
    "creationdate": ["erdat", "createdon", "createdat", "orderdate", "date"],
    "createdby": ["ernam", "createdbyuser", "author", "createdbyname"],
    "documentdate": ["bldat", "docdate"],
    "postingdate": ["budat", "postdate"],
}


def get_synonym_cluster(term: str) -> Set[str]:
    """Returns set of all canonicalized synonyms and technical abbreviations for a given term."""
    c_term = canonicalize(term)
    if not c_term:
        return set()

    cluster: Set[str] = {c_term}
    for std_term, synonyms in HEURISTIC_SAP_VOCABULARY.items():
        std_canon = canonicalize(std_term)
        syn_canons = {canonicalize(s) for s in synonyms}
        all_members = syn_canons | {std_canon}
        if c_term in all_members or any(c_term == m or (len(c_term) >= 5 and c_term in m) or (len(m) >= 5 and m in c_term) for m in all_members):
            cluster.update(all_members)

    return cluster


def canonicalize(text: str) -> str:
    """Canonicalizes a concept name by lowercasing and stripping all punctuation/whitespace.

    Example: 'Sales Order ID' -> 'salesorderid', 'net_amount' -> 'netamount'.
    """
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]", "", text.strip().lower())


def extract_structured_requirement(
    text: str,
    title: str = "",
    explicit_entities: List[str] = None,
    explicit_fields: List[str] = None,
    explicit_filters: List[str] = None,
) -> StructuredRequirement:
    """Extracts dimensions, measures, attributes, and filters from natural language requirement statements.

    Works dynamically on arbitrary text without hardcoding specific scenarios.
    """
    explicit_entities = explicit_entities or []
    explicit_fields = explicit_fields or []
    explicit_filters = explicit_filters or []

    dimensions: Set[str] = set()
    measures: Set[str] = set()
    attributes: Set[str] = set()
    filters: Set[str] = set(explicit_filters)

    # Measure-indicating keywords
    measure_indicators = {"amount", "value", "price", "quantity", "net", "gross", "cost", "revenue", "rate", "count", "margin"}
    # Attribute-indicating keywords
    attribute_indicators = {"date", "status", "type", "category", "time", "user", "name", "description", "code", "group"}

    # 1. Incorporate explicit fields first (highest priority)
    for f in explicit_fields:
        f_clean = f.strip()
        if not f_clean:
            continue
        canon = canonicalize(f_clean)
        if any(m in canon for m in measure_indicators):
            measures.add(f_clean)
        elif any(a in canon for a in attribute_indicators) and not any(m in canon for m in measure_indicators):
            attributes.add(f_clean)
        else:
            dimensions.add(f_clean)

    # 2. Incorporate explicit entities (highest priority)
    for e in explicit_entities:
        e_clean = e.strip()
        if e_clean:
            dimensions.add(e_clean)

    # 3. If explicit fields and entities were both provided, skip synthesizing conversational phrases
    if not (explicit_fields and explicit_entities):
        # Conversational noise patterns to eliminate prose run-ons
        noise_patterns = [
            r"\bi\s+need\b",
            r"\bwe\s+need\b",
            r"\bwant\s+to\s+see\b",
            r"\bshow\s+me\b",
            r"\bshowing\b",
            r"\bdisplaying\b",
            r"\blisting\b",
            r"\bcombining\b",
            r"\bjoined\s+with\b",
            r"\bplease\b",
            r"\bcreate\s+a\s+(?:new\s+)?view\s+for\b",
            r"\banalytical\s+view\s+combining\b",
            r"\ban?\s+(?:analytical|transactional|basic|composite|consumption)?\s*(?:cds)?\s*views?\s+(?:for|of|showing|containing)?\b",
            r"\bviews?\s+(?:for|of|containing)?\b",
            r"\bselect\b",
            r"\banalytics\b",
            r"\breport\s+for\b",
            r"\breporting\b",
        ]
        full_text = f"{title}. {text}".strip()
        cleaned = full_text
        for p in noise_patterns:
            cleaned = re.sub(p, " ", cleaned, flags=re.IGNORECASE)

        # Split on separators and transition keywords (showing, displaying, for, with)
        split_pattern = r"[,;]|\band\b|\bwith\b|\bincluding\b|\bshowing\b|\bdisplaying\b|\blisting\b|\bfor\b|\n"
        chunks = re.split(split_pattern, text, flags=re.IGNORECASE)

        conversational_words = {"need", "want", "see", "report", "view", "please", "analytical", "transactional", "cds", "create", "select"}

        for chunk in chunks:
            phrase = chunk.strip()
            if not phrase or len(phrase) < 2:
                continue
            phrase = re.sub(r"[\.:!?]+$", "", phrase).strip()

            # Check filter expressions
            if re.search(r"\bwhere\b|\bis\b|[=<>]", phrase, flags=re.IGNORECASE):
                parts = re.split(r"\bwhere\b", phrase, flags=re.IGNORECASE)
                phrase = parts[0].strip()
                if len(parts) > 1 and parts[1].strip():
                    filters.add(parts[1].strip())

            canon = canonicalize(phrase)
            if not canon or canon in ("the", "a", "an", "all", "each", "of", "in", "to", "showing", "view", "report"):
                continue

            words = [w.capitalize() for w in re.split(r"[\s_-]+", phrase) if w]
            # Discard conversational run-on clauses (more than 4 words)
            if len(words) > 4:
                continue
            # Discard pure conversational filler phrases
            if any(w.lower() in conversational_words for w in words) and not any(m in canon for m in measure_indicators) and not any(a in canon for a in attribute_indicators):
                if any(w.lower() in ("need", "want", "report", "view") for w in words):
                    continue

            concept_name = "".join(words)
            if not concept_name or len(concept_name) > 35:
                continue

            if any(m in canon for m in measure_indicators):
                measures.add(concept_name)
            elif any(a in canon for a in attribute_indicators):
                attributes.add(concept_name)
            else:
                dimensions.add(concept_name)

        # If dimensions are still empty, detect standard business entities from heuristic vocabulary
        if not dimensions:
            full_canon = canonicalize(f"{title} {text}")
            for std_entity in ("salesorder", "customer", "material", "companycode"):
                if std_entity in full_canon:
                    # Map to standard PascalCase
                    entity_map = {
                        "salesorder": "SalesOrder",
                        "customer": "Customer",
                        "material": "Material",
                        "companycode": "CompanyCode",
                    }
                    dimensions.add(entity_map[std_entity])
                    break

    # Consolidate unique list of all requested concepts
    all_concepts: List[str] = []
    seen = set()
    for item in list(dimensions) + list(measures) + list(attributes):
        c = canonicalize(item)
        if c and c not in seen:
            seen.add(c)
            all_concepts.append(item)

    return StructuredRequirement(
        dimensions=sorted(list(dimensions)),
        measures=sorted(list(measures)),
        attributes=sorted(list(attributes)),
        parameters=[],
        filters=sorted(list(filters)),
        all_requested_concepts=all_concepts,
    )


def match_concept_against_field(
    concept: str,
    field_name: str,
    field_description: str = "",
) -> Tuple[bool, float, str]:
    """Matches a business concept against a technical field name and label.

    Returns (is_match, confidence, justification).
    """
    c_canon = canonicalize(concept)
    f_canon = canonicalize(field_name)
    d_canon = canonicalize(field_description)

    # Level 1: Exact technical field name match
    if c_canon == f_canon:
        return True, 1.0, f"Exact technical field match: '{field_name}' matches requested '{concept}'"

    # Level 2: Exact/strong match in label or description
    if d_canon and (c_canon == d_canon or c_canon in d_canon):
        return True, 0.95, f"Description match: Field '{field_name}' has label '{field_description}' matching '{concept}'"

    # Level 4: Heuristic SAP technical synonym supported by vocabulary
    for std_term, synonyms in HEURISTIC_SAP_VOCABULARY.items():
        syn_canons = [canonicalize(s) for s in synonyms] + [std_term]
        if c_canon in syn_canons and f_canon in syn_canons:
            return True, 0.80, f"Metadata-supported synonym: '{field_name}' corresponds to standard concept '{std_term}'"

    return False, 0.0, "No match"


def resolve_domain_from_sap_metadata(
    package: Optional[str] = None,
    application_component: Optional[str] = None,
) -> str:
    """Derives the business domain strictly from SAP Repository Metadata:
    1. Application Component Hierarchy (TADIR / DF14L)
    2. ABAP Package (DEVCLASS / packageRef)

    Never derives domain from view name guessing or DDL source code.
    """
    pkg_u = (package or "").strip().upper()
    comp_u = (application_component or "").strip().upper()

    # Step 1: Application Component Hierarchy (DF14L / TADIR)
    if comp_u:
        # Billing & Invoicing (check before general SD)
        if comp_u.startswith("SD-BIL") or comp_u.startswith("FI-CA-BI") or comp_u.startswith("IS-U-BI"):
            return "Billing & Invoicing"
        # Sales & Distribution
        if comp_u.startswith("SD") or comp_u.startswith("CRM-BTX-SVO") or comp_u.startswith("LE-SHP-DL"):
            return "Sales & Distribution"
        # Sourcing & Procurement / Materials Management
        if comp_u.startswith("MM") or comp_u.startswith("SRM") or comp_u.startswith("PUR"):
            return "Sourcing & Procurement"
        # Finance & Controlling
        if (
            comp_u.startswith("FI")
            or comp_u.startswith("CO")
            or comp_u.startswith("AC")
            or comp_u.startswith("FIN")
            or comp_u.startswith("TR")
            or comp_u.startswith("FS-GL")
        ):
            return "Finance (FI/CO)"
        # Master Data
        if (
            comp_u.startswith("LO-MD")
            or comp_u.startswith("CA-MD")
            or comp_u.startswith("AP-MD")
            or comp_u.startswith("FS-BP")
            or comp_u.startswith("CA-BK")
            or comp_u.startswith("CA-MDG")
            or comp_u.startswith("MDG")
        ):
            return "Master Data"
        # Basis & Technology
        if comp_u.startswith("BC"):
            return "Basis & Technology"
        # Logistics & Delivery
        if (
            comp_u.startswith("LE")
            or comp_u.startswith("TM")
            or comp_u.startswith("EWM")
            or comp_u.startswith("WM")
            or comp_u.startswith("SCM")
            or comp_u.startswith("CA-ATP")
            or (comp_u.startswith("LO") and not comp_u.startswith("LO-MD"))
        ):
            return "Logistics & Delivery"
        # Manufacturing & Production
        if (
            comp_u.startswith("PP")
            or comp_u.startswith("MPE")
            or comp_u.startswith("PLM")
        ):
            return "Manufacturing & Production"
        # Quality Management
        if comp_u.startswith("QM"):
            return "Quality Management"
        # Plant Maintenance & Asset Management
        if comp_u.startswith("PM"):
            return "Plant Maintenance & Asset Management"
        # Project System & Portfolio
        if comp_u.startswith("PS") or comp_u.startswith("CA-CPD"):
            return "Project System & Portfolio"
        # Human Resources
        if (
            comp_u.startswith("PA")
            or comp_u.startswith("PT")
            or comp_u.startswith("PY")
            or comp_u.startswith("HCM")
            or comp_u.startswith("HR")
        ):
            return "Human Resources"

    # Step 2: ABAP Package (DEVCLASS / packageRef)
    if pkg_u and pkg_u not in ("SAP_STANDARD", "UNKNOWN", "$TMP"):
        # Billing & Invoicing (specific SD sub-packages)
        if any(pkg_u.startswith(p) for p in ("VDM_SD_BIL", "BIL_", "INVOICE_")) or "_BIL_" in pkg_u:
            return "Billing & Invoicing"
        # Sales & Distribution
        if any(pkg_u.startswith(p) for p in ("VDM_SD", "SD_", "S4H_SD", "ODATA_SD", "SALES_")) or "_SD_" in pkg_u:
            return "Sales & Distribution"
        # Sourcing & Procurement
        if (
            any(pkg_u.startswith(p) for p in ("VDM_MM", "MM_", "PUR_", "ODATA_MM", "S4H_MM", "SRM_"))
            or "_MM_" in pkg_u
            or "_PUR_" in pkg_u
        ):
            return "Sourcing & Procurement"
        # Finance & Controlling
        if (
            pkg_u == "ACE_S4"
            or any(pkg_u.startswith(p) for p in ("FINS_", "FI_", "CO_", "FIN_", "ACDOC_", "ID-FI", "TR_", "FS_", "GL_", "FCLM_", "FKK"))
            or "_FI_" in pkg_u
            or "_CO_" in pkg_u
            or "_FICO" in pkg_u
        ):
            return "Finance (FI/CO)"
        # Master Data
        if (
            any(pkg_u.startswith(p) for p in ("VDM_MD", "MD_", "BUPA_", "BP_", "MDC_", "CMD_", "PRODUCT_ALLOCATION", "S_ADDRESS"))
            or "_MD_" in pkg_u
            or "_BP_" in pkg_u
        ):
            return "Master Data"
        # Logistics & Delivery
        if (
            any(pkg_u.startswith(p) for p in ("VDM_LE", "VDM_TM", "LE_", "TM_", "SHP_", "WM_", "EWM_", "SCM_", "NJIT_", "ARUN_", "ATP_", "AATP_"))
            or "_LE_" in pkg_u
            or "_TM_" in pkg_u
        ):
            return "Logistics & Delivery"
        # Manufacturing & Production
        if (
            any(pkg_u.startswith(p) for p in ("VDM_PP", "PP_", "MPE_"))
            or "_PP_" in pkg_u
        ):
            return "Manufacturing & Production"
        # Quality Management
        if any(pkg_u.startswith(p) for p in ("VDM_QM", "QM_")):
            return "Quality Management"
        # Plant Maintenance & Asset Management
        if any(pkg_u.startswith(p) for p in ("PM_", "IWO", "EAM_")):
            return "Plant Maintenance & Asset Management"
        # Project System & Portfolio
        if any(pkg_u.startswith(p) for p in ("PS_", "CPD_", "VDM_CPM")):
            return "Project System & Portfolio"
        # Basis & Technology
        if any(pkg_u.startswith(p) for p in ("BC_", "SADT_", "SADL_")):
            return "Basis & Technology"
        # Human Resources
        if any(pkg_u.startswith(p) for p in ("VDM_SHCM", "PA_", "PT_", "PY_", "HCM_", "HR_")):
            return "Human Resources"
        # Customer namespace
        if pkg_u.startswith("Z") or pkg_u.startswith("Y"):
            return "Custom Development"

    return "Cross-Application / Core"

