"""Milestone 9 Unit & Integration Tests: Real SAP CDS Metadata Intelligence.

Tests authentic CDS DDL and ADT XML parsing, structured models (CDSViewMetadata,
CDSFieldMetadata, CDSAssociationMetadata, CDSAnnotationMetadata), evidence level binding,
safe error degradation, and agent integration.

STRICT SAFETY:
- All tests run offline against sanitized authentic fixtures based on I_SalesOrder.
- Zero live SAP requests.
- Zero SAP write operations.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.models.domain import (
    BusinessRequirement,
    CDSCandidate,
    CDSLayer,
    EvidenceLevel,
    MappingType,
    TargetUseCase,
)
from src.sap.models import (
    CDSAnnotationMetadata,
    CDSAssociationMetadata,
    CDSFieldMetadata,
    CDSMetadata,
    CDSViewMetadata,
)
from src.sap.parser import CDSDDLParser


# ==============================================================================
# Realistic SAP S/4HANA 2023 Fixtures (Modeled on verified I_SalesOrder)
# ==============================================================================

REAL_SALES_ORDER_DDL = """
@AbapCatalog.viewEnhancementCategory: [#PROJECTION_LIST]
@AccessControl.authorizationCheck: #CHECK
@EndUserText.label: 'Sales Order'
@Metadata.allowExtensions: true
@VDM.viewType: #BASIC
@ObjectModel.usageType:{
    serviceQuality: #A,
    sizeCategory: #L,
    dataClass: #TRANSACTIONAL
}
define view entity I_SalesOrder
  as select from vbak as Header
  association [0..*] to I_SalesOrderItem as _Item
    on $projection.SalesOrder = _Item.SalesOrder
  association [0..1] to I_Customer as _SoldToParty
    on $projection.SoldToParty = _SoldToParty.Customer
{
  @EndUserText.label: 'Sales Document'
  key Header.vbeln as SalesOrder,
      Header.erdat as CreationDate,
      Header.ernam as CreatedByUser,
      cast(Header.netwr as abap.curr(15,2)) as TotalNetAmount,
      @Semantics.currencyCode: true
      Header.waerk as TransactionCurrency,
      @EndUserText.label: 'Customer Sold-To'
      Header.kunnr as SoldToParty,

      // Associations exposed in projection
      _Item,
      _SoldToParty
}
"""

REAL_ADT_XML_ENVELOPE = """<?xml version="1.0" encoding="utf-8"?>
<ddl:ddlSource xmlns:ddl="http://www.sap.com/adt/ddl"
               xmlns:adtcore="http://www.sap.com/adt/core"
               adtcore:name="I_SALESORDER"
               adtcore:type="DDLS/DF"
               adtcore:description="Sales Order"
               adtcore:version="active"
               ddl:source_type="view_entity">
  <adtcore:packageRef adtcore:name="VDM_SD_SLS_SO"/>
  <ddl:source><![CDATA[
@AbapCatalog.viewEnhancementCategory: [#PROJECTION_LIST]
@AccessControl.authorizationCheck: #CHECK
@EndUserText.label: 'Sales Order'
@VDM.viewType: #BASIC
define view entity I_SalesOrder
  as select from vbak as Header
  association [0..*] to I_SalesOrderItem as _Item
    on $projection.SalesOrder = _Item.SalesOrder
{
  @EndUserText.label: 'Sales Document'
  key Header.vbeln as SalesOrder,
      cast(Header.netwr as abap.curr(15,2)) as TotalNetAmount,
      Header.kunnr as SoldToParty,
      _Item
}
  ]]></ddl:source>
</ddl:ddlSource>"""

MALFORMED_CORRUPTED_DDL = """
define view entity INCOMPLETE_CDS_WITHOUT_CLOSING_BRACE
  as select from dummy_tbl
{
  key dummy_tbl.col1 as Col1,
  // syntax truncated abruptly here
"""


# ==============================================================================
# 1. Full Metadata Extraction Tests
# ==============================================================================

def test_parse_cds_metadata_from_ddl():
    """Verifies complete metadata extraction from authentic CDS DDL text."""
    meta = CDSDDLParser.parse_cds_metadata(REAL_SALES_ORDER_DDL, object_name="I_SalesOrder")

    assert isinstance(meta, CDSViewMetadata)
    assert meta.view_name == "I_SalesOrder"
    assert meta.description == "Sales Order"
    assert meta.source_type == "view_entity"
    assert meta.layer == CDSLayer.BASIC
    assert "vbak" in meta.source_tables
    assert meta.evidence_level == EvidenceLevel.LEVEL_1_EXACT_FIELD
    assert meta.evidence_source == "SAP_ADT_DDL_SOURCE"


def test_parse_cds_metadata_from_adt_xml_envelope():
    """Verifies that authentic ADT XML envelope unwraps package, version, and object type."""
    meta = CDSDDLParser.parse_cds_metadata(REAL_ADT_XML_ENVELOPE)

    assert isinstance(meta, CDSViewMetadata)
    assert meta.view_name == "I_SALESORDER"
    assert meta.package == "VDM_SD_SLS_SO"
    assert meta.object_type == "DDLS/DF"
    assert meta.source_type == "view_entity"
    assert meta.version == "active"
    assert meta.description == "Sales Order"
    assert len(meta.fields) == 3
    field_names = [f.name for f in meta.fields]
    assert "SalesOrder" in field_names
    assert "TotalNetAmount" in field_names
    assert "SoldToParty" in field_names


# ==============================================================================
# 2. Field Extraction & Cast Data Type Tests
# ==============================================================================

def test_extract_fields_with_keys_and_types():
    """Verifies field extraction with key indicators, casts, aliases, and explicit ABAP types."""
    meta = CDSDDLParser.parse_cds_metadata(REAL_SALES_ORDER_DDL)

    fields_by_name = {f.name: f for f in meta.fields}

    # Key field check
    so_field = fields_by_name["SalesOrder"]
    assert so_field.is_key is True
    assert so_field.alias == "SalesOrder"
    assert so_field.source_expression == "Header.vbeln"
    assert so_field.evidence_level == EvidenceLevel.LEVEL_1_EXACT_FIELD
    assert so_field.evidence_source == "SAP_ADT_DDL_SOURCE"
    assert "Sales Document" in so_field.description

    # Cast expression check
    amount_field = fields_by_name["TotalNetAmount"]
    assert amount_field.is_key is False
    assert amount_field.abap_type == "CURR"
    assert amount_field.length == 15
    assert amount_field.decimals == 2
    assert amount_field.data_type == "abap.curr(15,2)"
    assert "cast(" in amount_field.source_expression

    # Date field heuristic check
    date_field = fields_by_name["CreationDate"]
    assert date_field.abap_type == "DATS"
    assert date_field.length == 8

    # Exposed associations must not pollute the regular fields list
    assert "_Item" not in fields_by_name
    assert "_SoldToParty" not in fields_by_name


# ==============================================================================
# 3. Association Extraction Tests
# ==============================================================================

def test_extract_associations_structured():
    """Verifies association extraction with cardinalities, ON conditions, and exposure detection."""
    meta = CDSDDLParser.parse_cds_metadata(REAL_SALES_ORDER_DDL)

    assocs_by_name = {a.name: a for a in meta.associations}
    assert "_Item" in assocs_by_name
    assert "_SoldToParty" in assocs_by_name

    item_assoc = assocs_by_name["_Item"]
    assert item_assoc.target_entity == "I_SalesOrderItem"
    assert item_assoc.cardinality == "[0..*]"
    assert "$projection.SalesOrder = _Item.SalesOrder" in item_assoc.on_condition
    assert item_assoc.is_exposed is True
    assert item_assoc.evidence_level == EvidenceLevel.LEVEL_3_VERIFIED_ASSOCIATION
    assert item_assoc.evidence_source == "SAP_ADT_DDL_SOURCE"

    party_assoc = assocs_by_name["_SoldToParty"]
    assert party_assoc.target_entity == "I_Customer"
    assert party_assoc.cardinality == "[0..1]"
    assert party_assoc.is_exposed is True


# ==============================================================================
# 4. Annotation Extraction Tests
# ==============================================================================

def test_extract_annotations_structured():
    """Verifies structured annotation extraction including simple and nested records."""
    annos = CDSDDLParser.parse_annotations_structured(REAL_SALES_ORDER_DDL)

    anno_dict = {a.name: a for a in annos}
    assert "AccessControl.authorizationCheck" in anno_dict
    assert anno_dict["AccessControl.authorizationCheck"].value == "#CHECK"
    assert anno_dict["AccessControl.authorizationCheck"].evidence_level == EvidenceLevel.LEVEL_1_EXACT_FIELD

    assert "Metadata.allowExtensions" in anno_dict
    assert anno_dict["Metadata.allowExtensions"].value is True

    assert "VDM.viewType" in anno_dict
    assert anno_dict["VDM.viewType"].value == "#BASIC"

    assert "ObjectModel.usageType" in anno_dict
    usage_type = anno_dict["ObjectModel.usageType"].value
    assert isinstance(usage_type, dict)
    assert usage_type.get("serviceQuality") == "#A"


# ==============================================================================
# 5. Safe Error Handling & Degradation Tests
# ==============================================================================

def test_malformed_ddl_safe_degradation():
    """Verifies that malformed, corrupted, or truncated DDL never crashes the server."""
    meta = CDSDDLParser.parse_cds_metadata(MALFORMED_CORRUPTED_DDL, object_name="INCOMPLETE_CDS")

    assert isinstance(meta, CDSViewMetadata)
    assert meta.view_name == "INCOMPLETE_CDS_WITHOUT_CLOSING_BRACE"
    # Should not raise exception, may extract partial fields if possible or return empty fields
    assert isinstance(meta.fields, list)


def test_empty_string_safe_handling():
    """Verifies empty or whitespace DDL string handling."""
    meta = CDSDDLParser.parse_cds_metadata("", object_name="EMPTY_OBJ")
    assert meta.view_name == "EMPTY_OBJ"
    assert len(meta.fields) == 0
    assert len(meta.associations) == 0


# ==============================================================================
# 6. Candidate Creation & Backward-Compatibility Tests
# ==============================================================================

def test_parse_candidate_enriches_structured_metadata():
    """Verifies parse_candidate populates both legacy fields and Milestone 9 structured metadata."""
    cand = CDSDDLParser.parse_candidate(REAL_SALES_ORDER_DDL, object_name="I_SalesOrder")

    assert isinstance(cand, CDSCandidate)
    assert cand.view_name == "I_SalesOrder"
    assert cand.layer == CDSLayer.BASIC
    assert cand.is_extendable is True
    assert "SalesOrder" in cand.key_fields
    assert "TotalNetAmount" in cand.available_fields

    # Milestone 9 structured extensions
    assert cand.structured_metadata is not None
    assert isinstance(cand.structured_metadata, CDSViewMetadata)
    assert len(cand.field_details) == len(cand.available_fields)
    assert len(cand.association_details) == len(cand.associations)
    assert len(cand.annotation_details) > 0

