"""Regression tests for VDM prefix resolution, concept normalizer, generator messaging, and I_SalesOrder reuse."""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock
from src.services.normalizer import extract_structured_requirement
from src.config import Settings
from src.models.domain import (
    BusinessRequirement,
    CDSCandidate,
    CDSDraft,
    CDSLayer,
    Decision,
    DecisionAction,
    TargetUseCase,
)
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector
from src.sap.parser import CDSDDLParser


def test_normalizer_prevents_malformed_concept_for_sales_order_analytics():
    """Verifies that extract_structured_requirement prioritizes explicit inputs and suppresses run-ons."""
    title = "Sales Order Analytics"
    text = "I need an analytical CDS view for Sales Orders showing Sales Order, Sales Order Type, and Creation Date."
    explicit_entities = ["SalesOrder"]
    explicit_fields = ["SalesOrder", "SalesOrderType", "CreationDate"]

    sreq = extract_structured_requirement(
        text=text,
        title=title,
        explicit_entities=explicit_entities,
        explicit_fields=explicit_fields,
    )

    assert sreq.dimensions == ["SalesOrder"]
    assert "SalesOrderType" in sreq.attributes
    assert "CreationDate" in sreq.attributes
    assert len(sreq.all_requested_concepts) == 3

    # Assert giant malformed concept is strictly absent
    for concept in sreq.all_requested_concepts:
        assert "AnalyticsAnAnalytical" not in concept
        assert len(concept) < 30


def test_normalizer_handles_natural_language_without_explicit_inputs():
    """Verifies that pure natural language produces clean tokens rather than run-on sentences."""
    title = "Sales Order Analytics"
    text = "I need an analytical CDS view for Sales Orders showing Sales Order, Sales Order Type, and Creation Date."

    sreq = extract_structured_requirement(text=text, title=title)

    assert "SalesOrder" in sreq.dimensions or any("SalesOrder" in d for d in sreq.dimensions)
    assert any("Date" in a or "Creation" in a for a in sreq.attributes)
    assert any("Type" in a for a in sreq.attributes)

    for concept in sreq.all_requested_concepts:
        assert len(concept.split()) <= 1
        assert "AnalyticsAnAnalytical" not in concept


@pytest.mark.asyncio
async def test_search_cds_vdm_prefix_resolution():
    """Verifies that search_cds resolves VDM prefixes (I_, C_) when given a bare entity name."""
    settings = Settings(
        SAP_CONNECTOR_ENABLED=True,
        SAP_CONNECTOR_TYPE="adt",
        SAP_BASE_URL="https://s4dev.company.corp:44300",
        SAP_LIVE_READ_ONLY=True,
    )
    mock_client = MagicMock(spec=SAPADTClient)
    mock_client.settings = settings

    async def mock_get_ddl(name: str):
        if name.upper() == "I_SALESORDER":
            return "define view entity I_SalesOrder as select from vbak { key vbeln as SalesOrder };"
        raise Exception("Not found")

    mock_client.get_ddl_source = AsyncMock(side_effect=mock_get_ddl)
    mock_client.search_information_system = AsyncMock(return_value=[])

    connector = SAPADTConnector(settings=settings, client=mock_client)
    candidates = await connector.search_cds("SalesOrder")

    assert len(candidates) >= 1
    assert candidates[0].view_name.upper() == "I_SALESORDER"


@pytest.mark.asyncio
async def test_get_ddl_source_fetches_source_main_when_descriptor_returned():
    """Verifies that SAPADTClient fetches /source/main if the base endpoint returns XML descriptor."""
    requested_paths = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        requested_paths.append(url_path)
        if url_path.endswith("/source/main"):
            return httpx.Response(200, text="define view entity I_SalesOrder as select from vbak { key vbeln as SalesOrder };")
        descriptor_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<ddl:ddlSource xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources" xmlns:atom="http://www.w3.org/2005/Atom">'
            '  <atom:link href="source/main" rel="http://www.sap.com/adt/relations/source" type="text/html"/>'
            '</ddl:ddlSource>'
        )
        return httpx.Response(200, text=descriptor_xml)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        settings = Settings(
            SAP_CONNECTOR_ENABLED=True,
            SAP_CONNECTOR_TYPE="adt",
            SAP_BASE_URL="https://s4dev.company.corp:44300",
            SAP_LIVE_READ_ONLY=True,
        )
        client = SAPADTClient(settings=settings, client=http_client)
        source = await client.get_ddl_source("i_salesorder")

    assert "define view entity I_SalesOrder" in source
    assert any("/source/main" in p for p in requested_paths)


def test_resolve_domain_from_sap_metadata():
    """Verifies that business domain is derived strictly from SAP metadata hierarchy:
    1. Application Component Hierarchy (TADIR / DF14L)
    2. ABAP Package (DEVCLASS / packageRef)
    Never from view names or DDL text.
    """
    from src.services.normalizer import resolve_domain_from_sap_metadata

    # 1. Application Component Priority
    assert resolve_domain_from_sap_metadata(package="ANY_PKG", application_component="SD-SLS-SO") == "Sales & Distribution"
    assert resolve_domain_from_sap_metadata(package="ANY_PKG", application_component="SD-BIL") == "Billing & Invoicing"
    assert resolve_domain_from_sap_metadata(package="ANY_PKG", application_component="MM-PUR") == "Sourcing & Procurement"
    assert resolve_domain_from_sap_metadata(package="ANY_PKG", application_component="FI-GL-GL-ACE") == "Finance (FI/CO)"
    assert resolve_domain_from_sap_metadata(package="ANY_PKG", application_component="FIN-FSCM-CLM-BAM") == "Finance (FI/CO)"
    assert resolve_domain_from_sap_metadata(package="ANY_PKG", application_component="LO-MD-MM") == "Master Data"
    assert resolve_domain_from_sap_metadata(package="ANY_PKG", application_component="LE-JIT-S2C") == "Logistics & Delivery"
    assert resolve_domain_from_sap_metadata(package="ANY_PKG", application_component="PP-MRP") == "Manufacturing & Production"

    # 2. ABAP Package (when Application Component is empty or unknown)
    assert resolve_domain_from_sap_metadata(package="VDM_SD_SLS_SO", application_component="") == "Sales & Distribution"
    assert resolve_domain_from_sap_metadata(package="VDM_MM_PUR", application_component="") == "Sourcing & Procurement"
    assert resolve_domain_from_sap_metadata(package="ACE_S4", application_component="") == "Finance (FI/CO)"
    assert resolve_domain_from_sap_metadata(package="FI_GL", application_component="") == "Finance (FI/CO)"
    assert resolve_domain_from_sap_metadata(package="VDM_MD_COMMON", application_component="") == "Master Data"
    assert resolve_domain_from_sap_metadata(package="VDM_SD_BIL_GF", application_component="") == "Billing & Invoicing"
    assert resolve_domain_from_sap_metadata(package="NJIT_MODEL", application_component="") == "Logistics & Delivery"
    assert resolve_domain_from_sap_metadata(package="ZTRAINING_PKG", application_component="") == "Custom Development"

    # 3. Fallback when metadata is generic or unknown
    assert resolve_domain_from_sap_metadata(package="SAP_STANDARD", application_component="") == "Cross-Application / Core"
    assert resolve_domain_from_sap_metadata(package="", application_component="") == "Cross-Application / Core"
    assert resolve_domain_from_sap_metadata(package=None, application_component=None) == "Cross-Application / Core"


