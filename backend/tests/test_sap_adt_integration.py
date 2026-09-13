"""Opt-in live integration test scaffolding for SAP S/4HANA ADT Discovery.

Disabled by default. To execute against the live SAP DEV system:
    $env:RUN_LIVE_SAP_TESTS="true"
    $env:SAP_CONNECTOR_ENABLED="true"
    $env:SAP_CONNECTOR_TYPE="adt"
    $env:SAP_BASE_URL="https://<sap-dev-host>:<port>"
    $env:SAP_CLIENT="100"
    $env:SAP_USERNAME="<your-developer-user>"
    $env:SAP_PASSWORD="<your-password>"
    pytest tests/test_sap_adt_integration.py
"""

import os
import pytest
from src.config import get_settings
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SAP_TESTS", "").lower() not in ("true", "1", "yes"),
    reason="Live SAP integration tests disabled by default. Set RUN_LIVE_SAP_TESTS=true to enable.",
)
@pytest.mark.asyncio
async def test_live_sap_connectivity_smoke():
    """Live smoke test verifying reachability of SAP DEV ADT root."""
    settings = get_settings()
    client = SAPADTClient(settings=settings)
    is_live = await client.check_connectivity()
    assert is_live is True, "Expected live SAP system to be reachable and authenticated."


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SAP_TESTS", "").lower() not in ("true", "1", "yes"),
    reason="Live SAP integration tests disabled by default. Set RUN_LIVE_SAP_TESTS=true to enable.",
)
@pytest.mark.asyncio
async def test_live_sap_get_sales_order_source():
    """Live smoke test fetching verified DDL source for I_SalesOrder."""
    settings = get_settings()
    connector = SAPADTConnector(settings=settings)
    meta = await connector.get_cds_metadata("i_salesorder")
    assert meta.view_name.lower() == "i_salesorder"
    assert len(meta.fields) > 0
