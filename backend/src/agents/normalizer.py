"""Concept Normalizer and Natural Language Requirement Parser.

Provides deterministic semantic token normalization and business concept extraction
for the SAP CDS Intelligence platform.
"""

import re
from typing import Dict, List, Set, Tuple
from src.models.domain import StructuredRequirement


# Standard heuristic SAP DDIC technical abbreviations (clearly labeled as heuristic test vocabulary)
HEURISTIC_SAP_VOCABULARY: Dict[str, List[str]] = {
    "salesorder": ["vbeln", "salesdocument", "salesorderid", "salesordernumber", "order"],
    "customer": ["kunnr", "soldtoparty", "customerid", "customernumber", "client"],
    "material": ["matnr", "product", "materialid", "productid", "itemmaterial"],
    "companycode": ["bukrs", "company", "cocode"],
    "netamount": ["netwr", "totalnetamount", "netvalue", "amount"],
    "grossamount": ["brtwr", "totalgrossamount", "grossvalue"],
    "currency": ["waerk", "transactioncurrency", "currencycode", "doccurrency"],
    "creationdate": ["erdat", "createdon", "createdat", "orderdate", "date"],
    "createdby": ["ernam", "createdbyuser", "author"],
    "salesorderitem": ["posnr", "item", "orderitem", "itemnumber", "linenumber"],
    "salesorganization": ["vkorg", "salesorg"],
    "distributionchannel": ["vtweg", "distchannel"],
    "division": ["spart"],
    "plant": ["werks"],
    "storagelocation": ["lgort"],
    "deliverystatus": ["lfstk", "overallstatus", "status"],
}


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

    # Combined text for scanning
    full_text = f"{title} {text}".strip()

    # Pre-clean sentence noise
    noise_patterns = [
        r"\bi\s+need\b",
        r"\bwe\s+need\b",
        r"\bwant\s+to\s+see\b",
        r"\bshow\s+me\b",
        r"\bcombining\b",
        r"\bjoined\s+with\b",
        r"\bplease\b",
        r"\bcreate\s+a\s+view\s+for\b",
        r"\banalytical\s+view\s+combining\b",
        r"\bview\s+containing\b",
        r"\bselect\b",
    ]
    cleaned = full_text
    for p in noise_patterns:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)

    # Measure-indicating keywords
    measure_indicators = {"amount", "value", "price", "quantity", "net", "gross", "cost", "revenue", "rate", "count", "margin"}
    # Attribute-indicating keywords
    attribute_indicators = {"date", "status", "type", "category", "time", "user", "name", "description", "code", "group"}

    # Incorporate explicit fields first
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

    # Incorporate explicit entities
    for e in explicit_entities:
        e_clean = e.strip()
        if e_clean:
            dimensions.add(e_clean)

    # Dynamic extraction of phrases from text (separated by commas, 'and', or newlines)
    chunks = re.split(r"[,;]|\band\b|\bwith\b|\bincluding\b|\n", cleaned, flags=re.IGNORECASE)
    for chunk in chunks:
        phrase = chunk.strip()
        if not phrase or len(phrase) < 2:
            continue
        # Strip trailing punctuation
        phrase = re.sub(r"[\.:!?]+$", "", phrase).strip()
        canon = canonicalize(phrase)
        if not canon or canon in ("the", "a", "an", "all", "each"):
            continue

        # Check filter expressions (e.g. status = 'X', where status is Completed, year > 2022)
        if re.search(r"\bwhere\b|\bis\b|[=<>]", phrase, flags=re.IGNORECASE):
            clean_filter = re.sub(r"^\s*where\s+", "", phrase, flags=re.IGNORECASE).strip()
            filters.add(clean_filter)
            continue

        # Convert phrase to PascalCase concept name
        words = [w.capitalize() for w in re.split(r"[\s_-]+", phrase) if w]
        concept_name = "".join(words)
        if not concept_name:
            continue

        if any(m in canon for m in measure_indicators):
            measures.add(concept_name)
        elif any(a in canon for a in attribute_indicators):
            attributes.add(concept_name)
        else:
            dimensions.add(concept_name)

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
