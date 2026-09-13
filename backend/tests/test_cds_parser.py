"""Unit tests for CDSDDLParser parsing ABAP CDS View Entities."""

import pytest
from src.models.domain import CDSLayer
from src.sap.parser import CDSDDLParser

SAMPLE_SALES_ORDER_DDL = """
@AbapCatalog.viewEnhancementCategory: [#PROJECTION_LIST]
@AccessControl.authorizationCheck: #CHECK
@EndUserText.label: 'Sales Order View Entity'
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
  key Header.vbeln as SalesOrder,
      Header.erdat as CreationDate,
      Header.ernam as CreatedByUser,
      Header.netwr as TotalNetAmount,
      @Semantics.currencyCode: true
      Header.waerk as TransactionCurrency,
      Header.kunnr as SoldToParty,

      // Associations exposed
      _Item,
      _SoldToParty
}
"""

SAMPLE_COMPOSITE_ANALYTICS_DDL = """
@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'Sales Analytics Composite'
@VDM.viewType: #COMPOSITE
define root view entity I_SalesOrderAnalytics
  with parameters
    p_display_currency : vdm_v_display_currency,
    p_exchange_rate_type : kurst
  as select from I_SalesOrder as _Order
  left outer join I_Customer as _Customer
    on _Order.SoldToParty = _Customer.Customer
{
  key _Order.SalesOrder,
      _Order.CreationDate,
      _Order.SoldToParty,
      _Customer.CustomerName,
      _Order.TotalNetAmount
}
"""


def test_parse_annotations():
    annotations = CDSDDLParser.parse_annotations(SAMPLE_SALES_ORDER_DDL)
    assert annotations["EndUserText.label"] == "Sales Order View Entity"
    assert annotations["Metadata.allowExtensions"] is True
    assert annotations["VDM.viewType"] == "#BASIC"
    assert annotations["AccessControl.authorizationCheck"] == "#CHECK"


def test_extract_view_name():
    name1 = CDSDDLParser.extract_view_name(SAMPLE_SALES_ORDER_DDL)
    assert name1 == "I_SalesOrder"

    name2 = CDSDDLParser.extract_view_name(SAMPLE_COMPOSITE_ANALYTICS_DDL)
    assert name2 == "I_SalesOrderAnalytics"


def test_extract_sources():
    sources1 = CDSDDLParser.extract_sources(SAMPLE_SALES_ORDER_DDL)
    assert "vbak" in sources1

    sources2 = CDSDDLParser.extract_sources(SAMPLE_COMPOSITE_ANALYTICS_DDL)
    assert "I_SalesOrder" in sources2
    assert "I_Customer" in sources2


def test_extract_parameters():
    params = CDSDDLParser.extract_parameters(SAMPLE_COMPOSITE_ANALYTICS_DDL)
    assert len(params) == 2
    assert params[0]["name"] == "p_display_currency"
    assert params[0]["type"] == "vdm_v_display_currency"
    assert params[1]["name"] == "p_exchange_rate_type"
    assert params[1]["type"] == "kurst"


def test_extract_associations():
    associations = CDSDDLParser.extract_associations(SAMPLE_SALES_ORDER_DDL)
    assert len(associations) == 2
    alias0, target0, card0, on0 = associations[0]
    assert alias0 == "_Item"
    assert target0 == "I_SalesOrderItem"
    assert card0 == "[0..*]"

    alias1, target1, card1, on1 = associations[1]
    assert alias1 == "_SoldToParty"
    assert target1 == "I_Customer"
    assert card1 == "[0..1]"


def test_extract_fields():
    fields = CDSDDLParser.extract_fields(SAMPLE_SALES_ORDER_DDL)
    field_names = [f.field_name for f in fields]
    assert "SalesOrder" in field_names
    assert "CreationDate" in field_names
    assert "CreatedByUser" in field_names
    assert "TotalNetAmount" in field_names
    assert "TransactionCurrency" in field_names
    assert "SoldToParty" in field_names
    # Exposed association names starting with _ should not be treated as regular data fields
    assert "_Item" not in field_names
    assert "_SoldToParty" not in field_names

    key_field = next(f for f in fields if f.field_name == "SalesOrder")
    assert key_field.is_key is True

    date_field = next(f for f in fields if f.field_name == "CreationDate")
    assert date_field.is_key is False
    assert date_field.abap_type == "DATS"


def test_parse_metadata_full():
    meta = CDSDDLParser.parse_metadata(SAMPLE_SALES_ORDER_DDL)
    assert meta.view_name == "I_SalesOrder"
    assert meta.layer == CDSLayer.BASIC
    assert meta.description == "Sales Order View Entity"
    assert "I_SalesOrderItem" in meta.associations
    assert "I_Customer" in meta.associations
    assert "vbak" in meta.source_tables


def test_parse_candidate():
    candidate = CDSDDLParser.parse_candidate(SAMPLE_SALES_ORDER_DDL)
    assert candidate.view_name == "I_SalesOrder"
    assert candidate.layer == CDSLayer.BASIC
    assert candidate.is_extendable is True
    assert "SalesOrder" in candidate.key_fields
    assert "TotalNetAmount" in candidate.available_fields


def test_parse_dependencies():
    graph = CDSDDLParser.parse_dependencies(SAMPLE_COMPOSITE_ANALYTICS_DDL)
    assert graph.root_view == "I_SalesOrderAnalytics"
    assert "I_SalesOrder" in graph.direct_dependencies
    assert "I_Customer" in graph.direct_dependencies
    node_names = [n.name for n in graph.nodes]
    assert "I_SalesOrder" in node_names
    assert "I_Customer" in node_names
