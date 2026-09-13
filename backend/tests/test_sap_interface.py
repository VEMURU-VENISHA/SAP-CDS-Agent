"""Tests for SAP Connector Interface and Unconnected Safety Guardrails."""

import pytest
from src.core.exceptions import SAPNotConnectedError
from src.sap.connector import UnconnectedSAPConnector


@pytest.mark.asyncio
async def test_sap_connector_is_not_connected():
    """Verifies that connector strictly reports unconnected status in Milestone 1."""
    connector = UnconnectedSAPConnector()
    assert await connector.is_connected() is False


@pytest.mark.asyncio
async def test_sap_connector_system_info():
    """Verifies baseline target SAP profile retrieval without live connection."""
    connector = UnconnectedSAPConnector()
    info = await connector.get_system_info()
    assert info.system_id == "DEV"
    assert info.client == "100"
    assert info.s4hana_release == "2023"
    assert info.is_connected is False


@pytest.mark.asyncio
async def test_sap_connector_refuses_operations_without_connection():
    """Verifies that all SAP operations raise typed SAPNotConnectedError instead of faking data."""
    connector = UnconnectedSAPConnector()

    with pytest.raises(SAPNotConnectedError) as exc_info:
        await connector.search_cds("I_SalesOrder")
    assert "search_cds" in exc_info.value.message

    with pytest.raises(SAPNotConnectedError) as exc_info:
        await connector.get_cds_metadata("I_SalesOrder")
    assert "get_cds_metadata" in exc_info.value.message

    with pytest.raises(SAPNotConnectedError) as exc_info:
        await connector.search_fields(["NETWR"])
    assert "search_fields" in exc_info.value.message

    with pytest.raises(SAPNotConnectedError) as exc_info:
        await connector.get_dependencies("I_SalesOrder")
    assert "get_dependencies" in exc_info.value.message

    with pytest.raises(SAPNotConnectedError) as exc_info:
        await connector.create_cds_draft("Z_Draft", "code", "ZPKG", "TR123")
    assert "create_cds_draft" in exc_info.value.message

    with pytest.raises(SAPNotConnectedError) as exc_info:
        await connector.validate_cds("code")
    assert "validate_cds" in exc_info.value.message

    with pytest.raises(SAPNotConnectedError) as exc_info:
        await connector.activate_cds("Z_Draft", "TR123")
    assert "activate_cds" in exc_info.value.message
