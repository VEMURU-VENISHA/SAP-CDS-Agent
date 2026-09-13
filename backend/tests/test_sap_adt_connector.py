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


@pytest.mark.asyncio
async def test_adt_connector_search_cds_unverified_quicksearch_fallback():
    """Verifies that unverified search handles failures gracefully without crashing or faking data."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        # Simulate quicksearch 404 or 500 on unverified endpoint
        return httpx.Response(404, text="Quicksearch endpoint not activated")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://s4dev.company.corp:44300") as http_client:
        adt_client = SAPADTClient(settings=create_test_settings(), client=http_client)
        connector = SAPADTConnector(settings=create_test_settings(), client=adt_client)

        candidates = await connector.search_cds("UNKNOWN_QUERY_*")
        assert candidates == []


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

    with pytest.raises(SAPConnectorError) as exc_val:
        await connector.validate_cds("code")
    assert "deferred to Milestone 4" in str(exc_val.value)

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
