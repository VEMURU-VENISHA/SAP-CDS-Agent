"""Unit tests for SAPADTClient and SAPADTConnector with mocked HTTP responses."""

import logging
import pytest
import httpx
from pydantic import SecretStr
from src.config import Settings
from src.core.exceptions import (
    SAPAuthenticationError,
    SAPConfigurationError,
    SAPConnectionError,
    SAPConnectorError,
    SAPNotFoundError,
    SAPPermissionError,
)
from src.models.domain import CDSLayer
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector
from src.sap.connector import (
    UnconnectedSAPConnector,
    get_sap_connector,
    reset_sap_connector,
)
from tests.test_cds_parser import SAMPLE_SALES_ORDER_DDL


def create_test_settings(
    enabled: bool = True,
    connector_type: str = "adt",
    base_url: str = "https://s4dev.company.corp:44300",
    auth_type: str = "basic",
    username: str = "DEV_USER",
    password: str = "SuperSecret123",
) -> Settings:
    return Settings(
        SAP_CONNECTOR_ENABLED=enabled,
        SAP_CONNECTOR_TYPE=connector_type,
        SAP_BASE_URL=base_url,
        SAP_CLIENT="100",
        SAP_SYSTEM_ID="DEV",
        SAP_AUTH_TYPE=auth_type,
        SAP_USERNAME=username,
        SAP_PASSWORD=SecretStr(password),
        SAP_API_TOKEN=SecretStr(""),
        SAP_VERIFY_SSL=True,
        SAP_REQUEST_TIMEOUT_SECONDS=5,
    )


@pytest.mark.asyncio
async def test_client_config_validation():
    # Missing base URL
    settings_no_url = create_test_settings(base_url="")
    client = SAPADTClient(settings=settings_no_url)
    with pytest.raises(SAPConfigurationError) as exc_info:
        await client.get_ddl_source("i_salesorder")
    assert "SAP_BASE_URL is not configured" in str(exc_info.value)

    # Missing username
    settings_no_user = create_test_settings(username="")
    client2 = SAPADTClient(settings=settings_no_user)
    with pytest.raises(SAPConfigurationError) as exc_info:
        await client2.get_ddl_source("i_salesorder")
    assert "SAP_USERNAME and SAP_PASSWORD are required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_client_get_ddl_source_success():
    requested_urls = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        assert request.headers.get("sap-client") == "100"
        return httpx.Response(200, text=SAMPLE_SALES_ORDER_DDL)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        settings = create_test_settings()
        adt_client = SAPADTClient(settings=settings, client=http_client)
        source = await adt_client.get_ddl_source("I_SalesOrder")

    assert "define view entity I_SalesOrder" in source
    assert len(requested_urls) == 1
    # Check that it called the verified endpoint with singular ddl and lowercase name
    assert "/sap/bc/adt/ddic/ddl/sources/i_salesorder" in requested_urls[0]
    assert "sap-client=100" in requested_urls[0]


@pytest.mark.asyncio
async def test_client_handles_304():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304, text=SAMPLE_SALES_ORDER_DDL)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        source = await adt_client.get_ddl_source("i_salesorder")

    assert "define view entity I_SalesOrder" in source


@pytest.mark.asyncio
async def test_client_handles_401_unauthorized():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        with pytest.raises(SAPAuthenticationError):
            await adt_client.get_ddl_source("i_salesorder")


@pytest.mark.asyncio
async def test_client_handles_403_forbidden():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        with pytest.raises(SAPPermissionError):
            await adt_client.get_ddl_source("i_salesorder")


@pytest.mark.asyncio
async def test_client_handles_404_not_found():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Object Not Found")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        with pytest.raises(SAPNotFoundError):
            await adt_client.get_ddl_source("non_existent_view")


@pytest.mark.asyncio
async def test_client_handles_connection_timeout():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Request timed out")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        with pytest.raises(SAPConnectionError):
            await adt_client.get_ddl_source("i_salesorder")


@pytest.mark.asyncio
async def test_adt_connector_get_cds_metadata():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_SALES_ORDER_DDL)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        connector = SAPADTConnector(settings=create_test_settings(), client=adt_client)

        meta = await connector.get_cds_metadata("I_SalesOrder")
        assert meta.view_name == "I_SalesOrder"
        assert meta.layer == CDSLayer.BASIC
        assert len(meta.fields) >= 5
        assert "I_SalesOrderItem" in meta.associations


@pytest.mark.asyncio
async def test_adt_connector_search_cds_exact():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if "i_salesorder" in str(request.url).lower():
            return httpx.Response(200, text=SAMPLE_SALES_ORDER_DDL)
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        connector = SAPADTConnector(settings=create_test_settings(), client=adt_client)

        candidates = await connector.search_cds("I_SalesOrder")
        assert len(candidates) == 1
        assert candidates[0].view_name == "I_SalesOrder"
        assert candidates[0].is_extendable is True


SAMPLE_SEARCH_XML = """<?xml version="1.0" encoding="utf-8"?>
<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/ddic/ddl/sources/i_salesorder"
                           adtcore:type="DDLS/DF"
                           adtcore:name="I_SalesOrder"
                           adtcore:packageName="SD_FIO_SLS"
                           adtcore:description="Sales Order View Entity"/>
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/ddic/ddl/sources/i_salesorderitem"
                           adtcore:type="DDLS/DF"
                           adtcore:name="I_SalesOrderItem"
                           adtcore:packageName="SD_FIO_SLS"
                           adtcore:description="Sales Order Item View Entity"/>
  <adtcore:objectReference adtcore:uri="/sap/bc/adt/programs/programs/z_report"
                           adtcore:type="PROG/P"
                           adtcore:name="Z_REPORT"
                           adtcore:packageName="ZTEST"
                           adtcore:description="Ignored Non-CDS Program"/>
</adtcore:objectReferences>
"""


@pytest.mark.asyncio
async def test_client_search_information_system_success():
    observed_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        observed_requests.append(request)
        assert request.url.path == "/sap/bc/adt/repository/informationsystem/search"
        assert request.url.params.get("operation") == "quickSearch"
        assert request.url.params.get("query") == "DDLSALES*"
        assert request.url.params.get("maxResults") == "51"
        return httpx.Response(200, text=SAMPLE_SEARCH_XML)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        hits = await adt_client.search_information_system("DDLSALES", max_results=51)

    assert len(hits) == 3
    assert hits[0]["name"] == "I_SalesOrder"
    assert hits[0]["type"] == "DDLS/DF"
    assert hits[0]["package"] == "SD_FIO_SLS"
    assert hits[1]["name"] == "I_SalesOrderItem"
    assert hits[2]["name"] == "Z_REPORT"


@pytest.mark.asyncio
async def test_client_search_information_system_empty_results():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core"/>')

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        hits = await adt_client.search_information_system("NON_EXISTENT_VIEW")

    assert hits == []


@pytest.mark.asyncio
async def test_client_search_information_system_malformed_xml():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<corrupt>unclosed xml payload")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        hits = await adt_client.search_information_system("SALES")

    assert hits == []


@pytest.mark.asyncio
async def test_client_search_information_system_http_errors():
    def mock_401(req: httpx.Request): return httpx.Response(401, text="Unauthorized")
    def mock_403(req: httpx.Request): return httpx.Response(403, text="Forbidden")
    def mock_500(req: httpx.Request): return httpx.Response(500, text="Internal Server Error")

    # 401
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_401), base_url="https://s4dev.company.corp:44300") as h:
        with pytest.raises(SAPAuthenticationError):
            await SAPADTClient(settings=create_test_settings(), client=h).search_information_system("SALES")

    # 403
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_403), base_url="https://s4dev.company.corp:44300") as h:
        with pytest.raises(SAPPermissionError):
            await SAPADTClient(settings=create_test_settings(), client=h).search_information_system("SALES")

    # 500
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_500), base_url="https://s4dev.company.corp:44300") as h:
        with pytest.raises(SAPConnectorError):
            await SAPADTClient(settings=create_test_settings(), client=h).search_information_system("SALES")


@pytest.mark.asyncio
async def test_adt_connector_search_cds_with_ddl_enrichment():
    """Verifies that search_cds queries informationsystem/search and enriches hits via get_ddl_source."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url).lower()
        if "informationsystem/search" in url_str:
            return httpx.Response(200, text=SAMPLE_SEARCH_XML)
        if request.url.path.endswith("/i_salesorderitem"):
            # Return item DDL
            item_ddl = """
            @EndUserText.label: 'Sales Order Item'
            @VDM.viewType: #BASIC
            define view entity I_SalesOrderItem
              as select from vbap as Item
            {
              key Item.vbeln as SalesOrder,
              key Item.posnr as SalesOrderItem,
                  Item.matnr as Material
            }
            """
            return httpx.Response(200, text=item_ddl)
        if request.url.path.endswith("/i_salesorder"):
            return httpx.Response(200, text=SAMPLE_SALES_ORDER_DDL)
        return httpx.Response(404, text="Not found")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        connector = SAPADTConnector(settings=create_test_settings(), client=adt_client)

        candidates = await connector.search_cds("DDLSALES*", limit=10)

    # Z_REPORT was ignored because it's not a CDS view (PROG/P)
    # I_SalesOrder and I_SalesOrderItem should both be enriched with real DDL metadata!
    assert len(candidates) == 2
    order_cand = next(c for c in candidates if c.view_name == "I_SalesOrder")
    assert order_cand.layer == CDSLayer.BASIC
    assert "SalesOrder" in order_cand.key_fields
    assert order_cand.is_extendable is True
    assert "vbak" in order_cand.source_tables

    item_cand = next(c for c in candidates if c.view_name == "I_SalesOrderItem")
    assert item_cand.layer == CDSLayer.BASIC
    assert "SalesOrderItem" in item_cand.key_fields
    assert "vbap" in item_cand.source_tables


@pytest.mark.asyncio
async def test_adt_connector_search_cds_respects_limit():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url).lower()
        if "informationsystem/search" in url_str:
            return httpx.Response(200, text=SAMPLE_SEARCH_XML)
        if "ddl/sources/i_salesorder" in url_str:
            return httpx.Response(200, text=SAMPLE_SALES_ORDER_DDL)
        return httpx.Response(404, text="Not found")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        connector = SAPADTConnector(settings=create_test_settings(), client=adt_client)

        # Request limit=1
        candidates = await connector.search_cds("DDLSALES*", limit=1)

    assert len(candidates) == 1
    assert candidates[0].view_name == "I_SalesOrder"


@pytest.mark.asyncio
async def test_adt_connector_get_dependencies():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_SALES_ORDER_DDL)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        connector = SAPADTConnector(settings=create_test_settings(), client=adt_client)

        deps = await connector.get_dependencies("I_SalesOrder")
        assert deps.root_view == "I_SalesOrder"
        assert "vbak" in deps.direct_dependencies


@pytest.mark.asyncio
async def test_adt_connector_refuses_write_operations():
    connector = SAPADTConnector(settings=create_test_settings())

    with pytest.raises(SAPConnectorError) as exc_draft:
        await connector.create_cds_draft("Z_Draft", "code", "ZPKG", "TR123")
    assert "strictly read-only" in str(exc_draft.value)

    with pytest.raises(SAPConnectorError) as exc_act:
        await connector.activate_cds("Z_Draft", "TR123")
    assert "strictly read-only" in str(exc_act.value)


@pytest.mark.asyncio
async def test_safe_logging_never_emits_credentials(caplog):
    caplog.set_level(logging.DEBUG)
    secret_pass = "UltraSecretSuperPassword999!"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_SALES_ORDER_DDL)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        settings = create_test_settings(password=secret_pass)
        adt_client = SAPADTClient(settings=settings, client=http_client)
        await adt_client.get_ddl_source("i_salesorder")

    all_logs = " ".join(record.message for record in caplog.records)
    # Check that password is never present in log records
    assert secret_pass not in all_logs
    # Check that authorization header content is never logged
    assert "Basic " not in all_logs


def test_connector_factory():
    reset_sap_connector()
    disabled_settings = create_test_settings(enabled=False)
    conn = get_sap_connector(settings=disabled_settings)
    assert isinstance(conn, UnconnectedSAPConnector)

    reset_sap_connector()
    enabled_settings = create_test_settings(enabled=True, connector_type="adt")
    conn2 = get_sap_connector(settings=enabled_settings)
    assert isinstance(conn2, SAPADTConnector)
    reset_sap_connector()
