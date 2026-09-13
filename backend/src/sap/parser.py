"""ABAP Core Data Services (CDS) DDL Parser.

Parses real SAP S/4HANA CDS View Entity and classic CDS View DDL definitions
into normalized domain objects (CDSMetadata, CDSCandidate, DependencyGraph, FieldDefinition).
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from src.logging_config import logger
from src.models.domain import CDSCandidate, CDSLayer
from src.sap.models import CDSMetadata, DependencyGraph, DependencyNode, FieldDefinition


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

            annotations[anno_name] = val

        return annotations

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
    def extract_fields(cls, ddl: str) -> List[FieldDefinition]:
        """Extracts field definitions from the SELECT list inside { ... }."""
        clean_ddl = cls._strip_comments(ddl)
        fields: List[FieldDefinition] = []

        # Find the main SELECT list block after 'as select from' or 'define view'
        select_match = re.search(r"\bas\s+select\s+from\b", clean_ddl, re.IGNORECASE)
        if select_match:
            search_area = clean_ddl[select_match.end() :]
        else:
            define_match = re.search(r"\bdefine\s+(?:root\s+|custom\s+)?(?:view\s+entity|view)\b", clean_ddl, re.IGNORECASE)
            search_area = clean_ddl[define_match.end() :] if define_match else clean_ddl

        start = search_area.find("{")
        end = search_area.rfind("}")
        if start != -1 and end != -1 and end > start:
            body = search_area[start + 1 : end]
        else:
            return fields

        # Split elements by comma, respecting parentheses
        raw_items = cls._split_elements(body)

        for item in raw_items:
            item = item.strip()
            if not item:
                continue

            # Strip leading element annotations (e.g. @Semantics.currencyCode: true or @EndUserText.label: '...')
            clean_element = re.sub(r"@[A-Za-z0-9_\.]+(?:\s*:\s*(?:#[A-Za-z0-9_]+|'[^']*'|\"[^\"]*\"|[^\s,]+))?", "", item).strip()

            # Check if this item is just an exposed association (e.g. `_Item` or `_Item,`)
            if re.match(r"^_[A-Za-z0-9_]+$", clean_element):
                continue

            is_key = bool(re.match(r"^\bkey\b\s+", clean_element, re.IGNORECASE))
            cleaned_item = re.sub(r"^\bkey\b\s+", "", clean_element, flags=re.IGNORECASE).strip()

            # Handle alias: `table.column as FieldAlias` or `column as FieldAlias`
            alias_match = re.search(r"\bas\s+([A-Za-z0-9_\/]+)$", cleaned_item, re.IGNORECASE)
            if alias_match:
                field_name = alias_match.group(1).strip()
                source_expr = cleaned_item[: alias_match.start()].strip()
            else:
                # Direct field without alias e.g. `table.column` or `column`
                source_expr = cleaned_item
                parts = source_expr.split(".")
                field_name = parts[-1].strip()

            # Clean field name of special characters
            field_name = re.sub(r"[^A-Za-z0-9_]", "", field_name)
            if not field_name:
                continue

            # Infer basic ABAP type heuristic
            abap_type, length, decimals = cls._infer_abap_type(field_name, source_expr)

            fields.append(
                FieldDefinition(
                    field_name=field_name,
                    data_element=None,
                    abap_type=abap_type,
                    length=length,
                    decimals=decimals,
                    is_key=is_key,
                    description=f"{field_name} (extracted from CDS DDL)",
                )
            )

        return fields

    @staticmethod
    def _split_elements(body: str) -> List[str]:
        """Splits comma-separated items inside a CDS SELECT body, ignoring commas inside parentheses."""
        items: List[str] = []
        depth = 0
        current: List[str] = []

        for char in body:
            if char == "(":
                depth += 1
                current.append(char)
            elif char == ")":
                depth = max(0, depth - 1)
                current.append(char)
            elif char == "," and depth == 0:
                items.append("".join(current).strip())
                current = []
            else:
                current.append(char)

        if current:
            items.append("".join(current).strip())

        return items

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
    def parse_metadata(cls, ddl_text: str, object_name: Optional[str] = None) -> CDSMetadata:
        """Parses DDL source text into full CDSMetadata DTO."""
        view_name = cls.extract_view_name(ddl_text) or object_name or "UNKNOWN_VIEW"
        annotations = cls.parse_annotations(ddl_text)
        sources = cls.extract_sources(ddl_text)
        params = cls.extract_parameters(ddl_text)
        associations = cls.extract_associations(ddl_text)
        fields = cls.extract_fields(ddl_text)

        # Determine VDM Layer
        vdm_raw = str(annotations.get("VDM.viewType", "")).upper()
        if "#COMPOSITE" in vdm_raw:
            layer = CDSLayer.COMPOSITE
        elif "#CONSUMPTION" in vdm_raw:
            layer = CDSLayer.CONSUMPTION
        else:
            layer = CDSLayer.BASIC

        description = str(annotations.get("EndUserText.label", f"CDS View {view_name}"))

        return CDSMetadata(
            view_name=view_name,
            sql_view_name=None,  # S/4HANA 2023 CDS View Entities do not produce classic SQL views
            package=None,
            layer=layer,
            description=description,
            annotations=annotations,
            parameters=params,
            fields=fields,
            associations=[assoc[1] for assoc in associations],
            source_tables=sources,
        )

    @classmethod
    def parse_candidate(cls, ddl_text: str, object_name: Optional[str] = None) -> CDSCandidate:
        """Parses DDL source text into a CDSCandidate for evaluation."""
        meta = cls.parse_metadata(ddl_text, object_name)
        is_extendable = bool(meta.annotations.get("Metadata.allowExtensions", True))
        key_fields = [f.field_name for f in meta.fields if f.is_key]
        all_fields = [f.field_name for f in meta.fields]

        return CDSCandidate(
            view_name=meta.view_name,
            sql_view_name=None,
            description=meta.description,
            layer=meta.layer,
            release_status="RELEASED",
            confidence_score=0.95,
            source_tables=meta.source_tables,
            associations=meta.associations,
            available_fields=all_fields,
            key_fields=key_fields,
            is_extendable=is_extendable,
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
