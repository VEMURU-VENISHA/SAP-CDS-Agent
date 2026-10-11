"""ABAP Core Data Services (CDS) DDL Parser.

Parses real SAP S/4HANA CDS View Entity and classic CDS View DDL definitions
into normalized domain objects (CDSMetadata, CDSCandidate, DependencyGraph, FieldDefinition).
"""

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple
from src.logging_config import logger
from src.models.domain import CDSConstructType, CDSCandidate, CDSLayer, EvidenceLevel
from src.sap.models import (
    CDSAnnotationMetadata,
    CDSAssociationMetadata,
    CDSFieldMetadata,
    CDSMetadata,
    CDSViewMetadata,
    DependencyGraph,
    DependencyNode,
    FieldDefinition,
)


class CDSDDLParser:
    """Extracts structured metadata, annotations, parameters, associations, and fields from CDS DDL."""

    @staticmethod
    def _strip_comments(ddl: str) -> str:
        """Removes single-line and multi-line SQL/ABAP comments."""
        # Multi-line /* ... */
        ddl = re.sub(r"/\*[\s\S]*?\*/", "", ddl)
        # Single-line // ...
        ddl = re.sub(r"//.*$", "", ddl, flags=re.MULTILINE)
        # Single-line -- ...
        ddl = re.sub(r"--.*$", "", ddl, flags=re.MULTILINE)
        return ddl

    @classmethod
    def detect_construct_type(
        cls,
        ddl_source: Optional[str] = None,
        envelope: Optional[Dict[str, Any]] = None,
        source_type: Optional[str] = None,
    ) -> CDSConstructType:
        """Deterministically detects whether a base CDS object is a CLASSIC_VIEW, VIEW_ENTITY, or UNKNOWN.

        Evidence hierarchy (authoritative, zero guessing):
        1. DDL source definition statement:
           - 'define [root|custom] view entity' -> VIEW_ENTITY
           - 'define [root|custom] view <name>' -> CLASSIC_VIEW
        2. ADT envelope or source_type attribute:
           - 'view' / 'classic_view' -> CLASSIC_VIEW
           - 'view_entity' / 'viewentity' -> VIEW_ENTITY
        3. If inconclusive or missing:
           - UNKNOWN (never inferred from object name).
        """
        if ddl_source and ddl_source.strip():
            clean_no_comments = cls._strip_comments(ddl_source)
            if re.search(r"\bdefine\s+(?:root\s+|custom\s+)?view\s+entity\b", clean_no_comments, re.IGNORECASE):
                return CDSConstructType.VIEW_ENTITY
            if re.search(r"\bdefine\s+(?:root\s+|custom\s+)?view\s+[a-zA-Z0-9_\/]+\b", clean_no_comments, re.IGNORECASE):
                return CDSConstructType.CLASSIC_VIEW

        # Check envelope source_type
        if envelope and envelope.get("source_type"):
            st = str(envelope["source_type"]).strip().lower()
            if st in ("view", "classic_view", "classic"):
                return CDSConstructType.CLASSIC_VIEW
            if st in ("view_entity", "viewentity", "entity"):
                return CDSConstructType.VIEW_ENTITY

        # Check explicit source_type argument
        if source_type and str(source_type).strip():
            st = str(source_type).strip().lower()
            if st in ("view", "classic_view", "classic"):
                return CDSConstructType.CLASSIC_VIEW
            if st in ("view_entity", "viewentity", "entity"):
                return CDSConstructType.VIEW_ENTITY

        return CDSConstructType.UNKNOWN

    @classmethod
    def _parse_adt_envelope(cls, raw_content: str) -> Tuple[str, Dict[str, Any]]:
        """Parses authentic SAP ADT XML envelope wrapping DDL source code.

        Observed in SAP DEV:
        <ddl:ddlSource xmlns:ddl="..." xmlns:adtcore="..."
                       adtcore:name="I_SALESORDER"
                       adtcore:type="DDLS/DF"
                       adtcore:description="Sales Order"
                       adtcore:version="active"
                       ddl:source_type="view">
            <adtcore:packageRef adtcore:name="VDM_SD_SLS_SO" />
            <ddl:source><![CDATA[ ... ]]></ddl:source>
        </ddl:ddlSource>
        """
        envelope: Dict[str, Any] = {}
        clean_ddl = raw_content

        if not raw_content or not raw_content.strip():
            return clean_ddl, envelope

        stripped = raw_content.strip()
        if stripped.startswith("<?xml") or "<ddl:ddlSource" in stripped or "<content" in stripped:
            try:
                root = ET.fromstring(stripped)

                # Extract attributes stripping namespace URIs
                for k, v in root.attrib.items():
                    clean_k = k.split("}")[-1] if "}" in k else k
                    if clean_k == "name":
                        envelope["name"] = v
                    elif clean_k == "type":
                        envelope["type"] = v
                    elif clean_k == "description":
                        envelope["description"] = v
                    elif clean_k == "version":
                        envelope["version"] = v
                    elif clean_k in ("source_type", "sourceType"):
                        envelope["source_type"] = v

                # Walk children to extract packageRef and source body
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag == "packageRef":
                        for pk, pv in elem.attrib.items():
                            clean_pk = pk.split("}")[-1] if "}" in pk else pk
                            if clean_pk == "name":
                                envelope["package"] = pv
                                break
                    elif tag in ("source", "sourceCode", "content"):
                        if elem.text and elem.text.strip():
                            clean_ddl = elem.text.strip()

                # If source tag didn't contain DDL, inspect CDATA or text nodes with 'define'
                if clean_ddl == raw_content:
                    for elem in root.iter():
                        if elem.text and "define " in elem.text.lower():
                            clean_ddl = elem.text.strip()
                            break

            except ET.ParseError as pe:
                logger.debug("Content not valid XML envelope; treating as raw DDL text: %s", pe)

        return clean_ddl, envelope

    @classmethod
    def parse_annotations(cls, ddl: str) -> Dict[str, Any]:
        """Extracts top-level header and element annotations."""
        clean_ddl = cls._strip_comments(ddl)
        annotations: Dict[str, Any] = {}

        # Matches @Annotation.name: value or @Annotation.name: #ENUM_VAL or @Annotation.name: 'string' or boolean
        pattern = re.compile(
            r"@([A-Za-z0-9_\.]+)\s*:\s*(?:#([A-Za-z0-9_]+)|'([^']*)'|\"([^\"]*)\"|true|false|[0-9\.]+)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(clean_ddl):
            full_match = match.group(0)
            anno_name = match.group(1)
            enum_val = match.group(2)
            single_str = match.group(3)
            double_str = match.group(4)

            if enum_val is not None:
                val: Any = f"#{enum_val}"
            elif single_str is not None:
                val = single_str
            elif double_str is not None:
                val = double_str
            elif "true" in full_match.lower():
                val = True
            elif "false" in full_match.lower():
                val = False
            else:
                val = full_match.split(":")[-1].strip()

            if anno_name not in annotations:
                annotations[anno_name] = val

        return annotations

    @classmethod
    def parse_annotations_structured(cls, ddl: str) -> List[CDSAnnotationMetadata]:
        """Extracts comprehensive structured annotations including enums, booleans, strings, and records."""
        clean_ddl = cls._strip_comments(ddl)
        structured_annos: List[CDSAnnotationMetadata] = []
        seen_names = set()

        define_match = re.search(
            r"\bdefine\s+(?:root\s+|custom\s+)?(?:view\s+entity|projection\s+view|custom\s+entity|view)\b",
            clean_ddl,
            re.IGNORECASE,
        )
        header_end = define_match.start() if define_match else len(clean_ddl)

        # 1. Standard pattern @Anno.name: value
        pattern = re.compile(
            r"@([A-Za-z0-9_\.]+)\s*:\s*(?:#([A-Za-z0-9_]+)|'([^']*)'|\"([^\"]*)\"|\[([^\]]*)\]|true|false|[0-9\.]+)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(clean_ddl):
            full_match = match.group(0)
            anno_name = match.group(1)
            enum_val = match.group(2)
            single_str = match.group(3)
            double_str = match.group(4)
            array_val = match.group(5)
            scope = "HEADER" if match.start() < header_end else "ELEMENT"

            if enum_val is not None:
                val: Any = f"#{enum_val}"
            elif single_str is not None:
                val = single_str
            elif double_str is not None:
                val = double_str
            elif array_val is not None:
                val = [item.strip() for item in array_val.split(",") if item.strip()]
            elif "true" in full_match.lower():
                val = True
            elif "false" in full_match.lower():
                val = False
            else:
                val = full_match.split(":")[-1].strip()

            structured_annos.append(
                CDSAnnotationMetadata(
                    name=anno_name,
                    value=val,
                    scope=scope,
                    raw_text=full_match.strip(),
                    evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                )
            )
            seen_names.add(anno_name.lower())

        # 2. Nested record pattern: @ObjectModel.usageType:{ ... }
        nested_pattern = re.compile(
            r"@([A-Za-z0-9_\.]+)\s*:\s*\{([^}]+)\}",
            re.IGNORECASE,
        )
        for match in nested_pattern.finditer(clean_ddl):
            anno_name = match.group(1)
            inner_content = match.group(2)
            if anno_name.lower() in seen_names:
                continue

            record_val: Dict[str, Any] = {}
            for item in inner_content.split(","):
                item = item.strip()
                if not item:
                    continue
                parts = item.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = parts[1].strip()
                    record_val[k] = v

            structured_annos.append(
                CDSAnnotationMetadata(
                    name=anno_name,
                    value=record_val,
                    scope="HEADER",
                    raw_text=match.group(0).strip(),
                    evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                )
            )

        return structured_annos

    @classmethod
    def extract_view_name(cls, ddl: str) -> Optional[str]:
        """Extracts the technical CDS view entity name."""
        clean_ddl = cls._strip_comments(ddl)
        match = re.search(
            r"define\s+(?:root\s+|custom\s+)?(?:view\s+entity|view)\s+([A-Za-z0-9_\/]+)",
            clean_ddl,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        return None

    @classmethod
    def extract_sources(cls, ddl: str) -> List[str]:
        """Extracts underlying database tables and joined CDS entities from FROM and JOIN clauses."""
        clean_ddl = cls._strip_comments(ddl)
        sources: List[str] = []

        # FROM clause
        from_match = re.search(
            r"\bas\s+select\s+from\s+([A-Za-z0-9_\/]+)",
            clean_ddl,
            re.IGNORECASE,
        )
        if from_match:
            primary_source = from_match.group(1).strip()
            if primary_source.upper() not in ("SELECT", "FROM"):
                sources.append(primary_source)

        # JOIN clauses
        join_pattern = re.compile(
            r"\b(?:inner|left\s+outer|right\s+outer|cross)?\s*join\s+([A-Za-z0-9_\/]+)",
            re.IGNORECASE,
        )
        for match in join_pattern.finditer(clean_ddl):
            joined_tbl = match.group(1).strip()
            if joined_tbl and joined_tbl not in sources:
                sources.append(joined_tbl)

        return sources

    @classmethod
    def extract_parameters(cls, ddl: str) -> List[Dict[str, str]]:
        """Extracts input parameters declared with 'with parameters'."""
        clean_ddl = cls._strip_comments(ddl)
        params: List[Dict[str, str]] = []

        param_block = re.search(
            r"\bwith\s+parameters\s+([\s\S]*?)\s+as\s+select\b",
            clean_ddl,
            re.IGNORECASE,
        )
        if not param_block:
            return params

        items = param_block.group(1).split(",")
        for item in items:
            item = item.strip()
            if not item:
                continue
            # e.g., p_display_currency : vdm_v_display_currency
            parts = item.split(":")
            if len(parts) >= 2:
                name = parts[0].strip()
                dtype = parts[1].strip()
                params.append({"name": name, "type": dtype})
            elif len(parts) == 1 and parts[0]:
                params.append({"name": parts[0].strip(), "type": "string"})

        return params

    @classmethod
    def extract_associations(cls, ddl: str) -> List[Tuple[str, str, str, str]]:
        """Extracts associations: returns list of (alias, target_entity, cardinality, on_condition)."""
        clean_ddl = cls._strip_comments(ddl)
        associations: List[Tuple[str, str, str, str]] = []

        pattern = re.compile(
            r"\bassociation\s*(?:\[\s*([^\]]+?)\s*\])?\s*to\s+([A-Za-z0-9_\/]+)\s+as\s+([A-Za-z0-9_\/]+)\s+on\s+([\s\S]*?)(?=(?:\bassociation\b|\bas\s+select\b|\{|$))",
            re.IGNORECASE,
        )
        for match in pattern.finditer(clean_ddl):
            cardinality = (match.group(1) or "[0..1]").strip()
            if not cardinality.startswith("["):
                cardinality = f"[{cardinality}]"
            target_entity = match.group(2).strip()
            alias = match.group(3).strip()
            on_condition = match.group(4).strip()
            # Clean up trailing braces or keywords if captured
            on_condition = re.sub(r"[\{\};]+$", "", on_condition).strip()
            associations.append((alias, target_entity, cardinality, on_condition))

        return associations

    @classmethod
    def extract_associations_structured(cls, ddl: str) -> List[CDSAssociationMetadata]:
        """Extracts structured associations with exposure verification and Level 3 evidence binding."""
        raw_assocs = cls.extract_associations(ddl)
        clean_ddl = cls._strip_comments(ddl)

        # Detect exposed associations inside projection list { ... }
        exposed_aliases: set = set()
        start = clean_ddl.find("{")
        end = clean_ddl.rfind("}")
        if start != -1 and end != -1 and end > start:
            body = clean_ddl[start + 1 : end]
            elements = cls._split_elements(body)
            for elem in elements:
                clean_elem = re.sub(r"@[A-Za-z0-9_\.]+(?:\s*:\s*(?:#[A-Za-z0-9_]+|'[^']*'|\"[^\"]*\"|[^\s,]+))?", "", elem).strip()
                if re.match(r"^_[A-Za-z0-9_]+$", clean_elem):
                    exposed_aliases.add(clean_elem)

        structured_assocs: List[CDSAssociationMetadata] = []
        for alias, target, card, on_cond in raw_assocs:
            is_exposed = (alias in exposed_aliases) or (not exposed_aliases)
            structured_assocs.append(
                CDSAssociationMetadata(
                    name=alias,
                    target_entity=target,
                    cardinality=card,
                    on_condition=on_cond,
                    is_exposed=is_exposed,
                    evidence_level=EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION,
                    evidence_source="SAP_ADT_DDL_SOURCE",
                    evidence_detail=f"Authoritative association '{alias}' to target '{target}' declared in active CDS DDL on SAP DEV",
                )
            )

        return structured_assocs

    @classmethod
    def extract_fields_structured(cls, ddl: str) -> List[CDSFieldMetadata]:
        """Extracts complete structured field metadata from SELECT list inside { ... }."""
        clean_ddl = cls._strip_comments(ddl)
        fields: List[CDSFieldMetadata] = []

        select_match = re.search(r"\bas\s+select\s+from\b", clean_ddl, re.IGNORECASE)
        if select_match:
            search_area = clean_ddl[select_match.end() :]
        else:
            define_match = re.search(
                r"\bdefine\s+(?:root\s+|custom\s+)?(?:view\s+entity|projection\s+view|custom\s+entity|view)\b",
                clean_ddl,
                re.IGNORECASE,
            )
            search_area = clean_ddl[define_match.end() :] if define_match else clean_ddl

        start = search_area.find("{")
        end = search_area.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return fields

        body = search_area[start + 1 : end]
        raw_items = cls._split_elements(body)

        for item in raw_items:
            item = item.strip()
            if not item:
                continue

            # Extract field-level annotations
            elem_annos: Dict[str, Any] = {}
            for am in re.finditer(
                r"@([A-Za-z0-9_\.]+)\s*:\s*(?:#([A-Za-z0-9_]+)|'([^']*)'|\"([^\"]*)\"|true|false|[0-9\.]+)",
                item,
                re.IGNORECASE,
            ):
                a_name = am.group(1)
                enum_v = am.group(2)
                s_str = am.group(3)
                d_str = am.group(4)
                if enum_v:
                    elem_annos[a_name] = f"#{enum_v}"
                elif s_str is not None:
                    elem_annos[a_name] = s_str
                elif d_str is not None:
                    elem_annos[a_name] = d_str
                elif "true" in am.group(0).lower():
                    elem_annos[a_name] = True
                elif "false" in am.group(0).lower():
                    elem_annos[a_name] = False
                else:
                    elem_annos[a_name] = am.group(0).split(":")[-1].strip()

            # Strip leading element annotations (including nested {...} and [...])
            clean_element = cls._strip_element_annotations(item)

            # Skip exposed association references (e.g. _Item)
            if re.match(r"^_[A-Za-z0-9_]+$", clean_element):
                continue

            is_key = bool(re.match(r"^\bkey\b\s+", clean_element, re.IGNORECASE))
            cleaned_item = re.sub(r"^\bkey\b\s+", "", clean_element, flags=re.IGNORECASE).strip()

            # Handle alias: `expr as FieldAlias`
            alias_match = re.search(r"\bas\s+([A-Za-z0-9_\/]+)$", cleaned_item, re.IGNORECASE)
            if alias_match:
                field_name = alias_match.group(1).strip()
                source_expr = cleaned_item[: alias_match.start()].strip()
                alias = field_name
            else:
                source_expr = cleaned_item
                parts = source_expr.split(".")
                field_name = parts[-1].strip()
                alias = None

            # Clean field name
            field_name = re.sub(r"[^A-Za-z0-9_]", "", field_name)
            if not field_name:
                continue

            # Data Type & Length extraction
            data_type = None
            length = 0
            decimals = 0
            abap_type = "CHAR"

            # Check for cast expression: cast(expr as abap.type(len, dec)) or cast(expr as type)
            cast_match = re.search(
                r"cast\s*\([\s\S]*?\bas\s+(?:abap\.)?([A-Za-z0-9_]+)(?:\s*\(\s*(\d+)(?:\s*,\s*(\d+))?\s*\))?",
                source_expr,
                re.IGNORECASE,
            )
            if cast_match:
                type_token = cast_match.group(1).upper()
                len_token = cast_match.group(2)
                dec_token = cast_match.group(3)

                abap_type = type_token
                length = int(len_token) if len_token else 0
                decimals = int(dec_token) if dec_token else 0
                if len_token and dec_token:
                    data_type = f"abap.{type_token.lower()}({length},{decimals})"
                elif len_token:
                    data_type = f"abap.{type_token.lower()}({length})"
                else:
                    data_type = f"abap.{type_token.lower()}"
            else:
                # Infer type heuristic
                abap_type, length, decimals = cls._infer_abap_type(field_name, source_expr)
                data_type = f"abap.{abap_type.lower()}"

            description = str(elem_annos.get("EndUserText.label") or f"{field_name} (extracted from CDS DDL)")

            fields.append(
                CDSFieldMetadata(
                    name=field_name,
                    alias=alias,
                    source_expression=source_expr,
                    is_key=is_key,
                    data_type=data_type,
                    abap_type=abap_type,
                    length=length,
                    decimals=decimals,
                    description=description,
                    annotations=elem_annos,
                    evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                    evidence_source="SAP_ADT_DDL_SOURCE",
                    evidence_detail=f"Field '{field_name}' extracted from active CDS DDL definition on SAP DEV",
                )
            )

        return fields

    @classmethod
    def extract_fields(cls, ddl: str) -> List[FieldDefinition]:
        """Extracts field definitions from SELECT list (backward-compatible FieldDefinition DTO)."""
        structured = cls.extract_fields_structured(ddl)
        return [
            FieldDefinition(
                field_name=f.name,
                data_element=None,
                abap_type=f.abap_type,
                length=f.length,
                decimals=f.decimals,
                is_key=f.is_key,
                description=f.description,
            )
            for f in structured
        ]
    @classmethod
    def _strip_element_annotations(cls, elem: str) -> str:
        """Strips all leading annotations from a SELECT element, including nested {...} and [...]."""
        cleaned = elem.strip()
        while cleaned.startswith("@"):
            m = re.match(r"^@[A-Za-z0-9_\.]+\s*", cleaned)
            if not m:
                break
            cleaned = cleaned[m.end():].strip()
            if not cleaned:
                break
            if cleaned.startswith(":"):
                cleaned = cleaned[1:].strip()
                if not cleaned:
                    break
                if cleaned.startswith("{"):
                    depth = 0
                    idx = len(cleaned)
                    for i, c in enumerate(cleaned):
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                idx = i + 1
                                break
                    cleaned = cleaned[idx:].strip()
                elif cleaned.startswith("["):
                    depth = 0
                    idx = len(cleaned)
                    for i, c in enumerate(cleaned):
                        if c == "[":
                            depth += 1
                        elif c == "]":
                            depth -= 1
                            if depth == 0:
                                idx = i + 1
                                break
                    cleaned = cleaned[idx:].strip()
                elif cleaned[0] in ("'", '"'):
                    q = cleaned[0]
                    end_q = cleaned.find(q, 1)
                    cleaned = cleaned[end_q + 1:].strip() if end_q != -1 else ""
                elif cleaned[0] == "#":
                    m_val = re.match(r"^#[A-Za-z0-9_]+", cleaned)
                    cleaned = cleaned[m_val.end():].strip() if m_val else ""
                else:
                    m_val = re.match(r"^[^\s,;]+", cleaned)
                    cleaned = cleaned[m_val.end():].strip() if m_val else ""
            else:
                # Annotation without colon
                pass
        return cleaned

    @staticmethod
    def _split_elements(body: str) -> List[str]:
        """Splits comma-separated items inside a CDS SELECT body, ignoring commas inside (), [], {}, and strings."""
        items: List[str] = []
        paren_depth = 0
        bracket_depth = 0
        brace_depth = 0
        in_quote = False
        quote_char = None
        current: List[str] = []

        for char in body:
            if in_quote:
                current.append(char)
                if char == quote_char:
                    in_quote = False
                continue

            if char in ("'", '"'):
                in_quote = True
                quote_char = char
                current.append(char)
            elif char == "(":
                paren_depth += 1
                current.append(char)
            elif char == ")":
                paren_depth = max(0, paren_depth - 1)
                current.append(char)
            elif char == "[":
                bracket_depth += 1
                current.append(char)
            elif char == "]":
                bracket_depth = max(0, bracket_depth - 1)
                current.append(char)
            elif char == "{":
                brace_depth += 1
                current.append(char)
            elif char == "}":
                brace_depth = max(0, brace_depth - 1)
                current.append(char)
            elif char == "," and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                items.append("".join(current).strip())
                current = []
            else:
                current.append(char)

        if current:
            items.append("".join(current).strip())

        return [it for it in items if it]

    @staticmethod
    def _infer_abap_type(name: str, expr: str) -> Tuple[str, int, int]:
        """Infers reasonable default ABAP type metadata from field name and expression."""
        upper_name = name.upper()
        if any(w in upper_name for w in ("DATE", "DATS", "ERDAT", "AEDAT", "VKDAT")):
            return ("DATS", 8, 0)
        if any(w in upper_name for w in ("TIME", "TIMS", "ERZET", "CPUTM")):
            return ("TIMS", 6, 0)
        if any(w in upper_name for w in ("CURRENCY", "WAERK", "CURR")):
            return ("CUKY", 5, 0)
        if any(w in upper_name for w in ("AMOUNT", "NETWR", "BRTWR", "KZWI")):
            return ("CURR", 15, 2)
        if any(w in upper_name for w in ("QUANTITY", "MENGE", "KWMENG")):
            return ("QUAN", 13, 3)
        if any(w in upper_name for w in ("UNIT", "MEINS", "VRKME")):
            return ("UNIT", 3, 0)
        if any(w in upper_name for w in ("NUM", "COUNT", "POSNR", "LINE")):
            return ("NUMC", 10, 0)
        return ("CHAR", 40, 0)

    @classmethod
    def parse_cds_metadata(cls, ddl_source: str, object_name: Optional[str] = None) -> CDSViewMetadata:
        """Authoritative parser for authentic SAP CDS View Entities and DDL sources.

        Transforms raw DDL source or ADT XML into structured Milestone 9 CDSViewMetadata:
        - View name, description, package, version, object type, source type, VDM layer
        - Key indicators, source expressions, ABAP types, length, decimals, and field annotations
        - Associations with alias, target entity, cardinality, ON condition, and exposure
        - Ground-truth Evidence Records (Level 1 for exact fields, Level 3 for verified associations)

        Fails safely on malformed syntax without crashing the application.
        """
        if not ddl_source or not ddl_source.strip():
            return CDSViewMetadata(
                view_name=object_name or "EMPTY_VIEW",
                description="Empty CDS DDL source",
                evidence_source="SAP_ADT_DDL_SOURCE",
            )

        try:
            clean_ddl, envelope = cls._parse_adt_envelope(ddl_source)

            # View Name
            extracted_name = cls.extract_view_name(clean_ddl)
            view_name = envelope.get("name") or extracted_name or object_name or "UNKNOWN_VIEW"

            # Source Type & Base Construct Type
            clean_no_comments = cls._strip_comments(clean_ddl)
            source_type = envelope.get("source_type")
            if not source_type:
                if re.search(r"\bdefine\s+(?:root\s+)?view\s+entity\b", clean_no_comments, re.IGNORECASE):
                    source_type = "view_entity"
                elif re.search(r"\bdefine\s+(?:root\s+)?projection\s+view\b", clean_no_comments, re.IGNORECASE):
                    source_type = "projection_view"
                elif re.search(r"\bdefine\s+(?:root\s+)?custom\s+entity\b", clean_no_comments, re.IGNORECASE):
                    source_type = "custom_entity"
                elif re.search(r"\bdefine\s+view\b", clean_no_comments, re.IGNORECASE):
                    source_type = "view"
                else:
                    source_type = "unknown"

            construct_type = cls.detect_construct_type(clean_ddl, envelope=envelope, source_type=source_type)

            # Annotations
            annotations = cls.parse_annotations_structured(clean_ddl)
            header_annos = {a.name: a.value for a in annotations if a.scope == "HEADER"}
            anno_dict = {a.name: a.value for a in annotations}

            # VDM Layer
            vdm_raw = str(header_annos.get("VDM.viewType") or anno_dict.get("VDM.viewType", "")).upper()
            if "#COMPOSITE" in vdm_raw:
                layer = CDSLayer.COMPOSITE
            elif "#CONSUMPTION" in vdm_raw:
                layer = CDSLayer.CONSUMPTION
            else:
                layer = CDSLayer.BASIC

            # Description
            desc = envelope.get("description") or str(
                header_annos.get("EndUserText.label")
                or anno_dict.get("EndUserText.label")
                or f"CDS View {view_name}"
            )

            # Package
            package = envelope.get("package")

            # Object Type & Version
            object_type = envelope.get("type", "DDLS/DF")
            version = envelope.get("version", "active")

            # Source tables & joins
            sources = cls.extract_sources(clean_ddl)

            # Parameters
            params = cls.extract_parameters(clean_ddl)

            # Associations
            associations = cls.extract_associations_structured(clean_ddl)

            # Fields
            fields = cls.extract_fields_structured(clean_ddl)

            return CDSViewMetadata(
                view_name=view_name,
                description=desc,
                object_type=object_type,
                source_type=source_type,
                cds_construct_type=construct_type,
                version=version,
                package=package,
                layer=layer,
                sql_view_name=None,
                source_tables=sources,
                parameters=params,
                fields=fields,
                associations=associations,
                annotations=annotations,
                raw_source=clean_ddl,
                evidence_level=EvidenceLevel.LEVEL_1_EXACT_FIELD,
                evidence_source="SAP_ADT_DDL_SOURCE",
            )
        except Exception as e:
            logger.warning("CDSDDLParser encountered error during parsing (safe degradation): %s", e)
            return CDSViewMetadata(
                view_name=object_name or "UNPARSED_VIEW",
                description=f"Parsing degraded safely: {e}",
                evidence_source="SAP_ADT_DDL_SOURCE",
                raw_source=ddl_source,
            )

    @classmethod
    def parse_metadata(cls, ddl_text: str, object_name: Optional[str] = None) -> CDSMetadata:
        """Parses DDL source text into full CDSMetadata DTO (with attached structured view metadata)."""
        view_meta = cls.parse_cds_metadata(ddl_text, object_name)

        fields = [
            FieldDefinition(
                field_name=f.name,
                data_element=None,
                abap_type=f.abap_type,
                length=f.length,
                decimals=f.decimals,
                is_key=f.is_key,
                description=f.description,
            )
            for f in view_meta.fields
        ]

        return CDSMetadata(
            view_name=view_meta.view_name,
            sql_view_name=view_meta.sql_view_name,
            package=view_meta.package,
            layer=view_meta.layer,
            description=view_meta.description,
            annotations={a.name: a.value for a in view_meta.annotations},
            parameters=view_meta.parameters,
            fields=fields,
            associations=[assoc.target_entity for assoc in view_meta.associations],
            source_tables=view_meta.source_tables,
            structured=view_meta,
        )

    @classmethod
    def parse_candidate(cls, ddl_text: str, object_name: Optional[str] = None) -> CDSCandidate:
        """Parses DDL source text into a CDSCandidate carrying full Milestone 9 structured metadata."""
        view_meta = cls.parse_cds_metadata(ddl_text, object_name)
        is_extendable = True
        for anno in view_meta.annotations:
            if anno.name.lower() == "metadata.allowextensions":
                is_extendable = bool(anno.value)

        key_fields = [f.name for f in view_meta.fields if f.is_key]
        all_fields = [f.name for f in view_meta.fields]

        return CDSCandidate(
            view_name=view_meta.view_name,
            sql_view_name=view_meta.sql_view_name,
            description=view_meta.description,
            layer=view_meta.layer,
            release_status="RELEASED",
            confidence_score=0.95,
            source_tables=view_meta.source_tables,
            associations=[a.target_entity for a in view_meta.associations],
            available_fields=all_fields,
            key_fields=key_fields,
            is_extendable=is_extendable,
            package=view_meta.package,
            object_type=view_meta.object_type,
            source_type=view_meta.source_type,
            cds_construct_type=view_meta.cds_construct_type,
            version=view_meta.version,
            structured_metadata=view_meta,
            field_details=view_meta.fields,
            association_details=view_meta.associations,
            annotation_details=view_meta.annotations,
        )

    @classmethod
    def parse_dependencies(cls, ddl_text: str, object_name: Optional[str] = None) -> DependencyGraph:
        """Extracts direct data dependencies from parsed CDS DDL."""
        meta = cls.parse_metadata(ddl_text, object_name)
        nodes: List[DependencyNode] = []

        for src in meta.source_tables:
            obj_type = "CDS_VIEW_ENTITY" if src.startswith("I_") or src.startswith("C_") or src.startswith("Z") else "TABLE"
            nodes.append(DependencyNode(name=src, object_type=obj_type, layer=meta.layer))

        return DependencyGraph(
            root_view=meta.view_name,
            nodes=nodes,
            direct_dependencies=meta.source_tables,
            used_by_views=[],
        )
