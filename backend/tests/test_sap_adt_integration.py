"""Milestone 8: Opt-In Live Integration Test Suite for SAP S/4HANA ADT Discovery.

Strictly disabled by default. To execute against the live SAP DEV system:
    $env:RUN_LIVE_SAP_TESTS="true"
    $env:SAP_LIVE_READ_ONLY="true"
    $env:SAP_CONNECTOR_ENABLED="true"
    $env:SAP_CONNECTOR_TYPE="adt"
    $env:SAP_BASE_URL="https://<sap-dev-host>:<port>"
    $env:SAP_CLIENT="100"
    $env:SAP_USERNAME="<your-developer-user>"
    $env:SAP_PASSWORD="<your-password>"
    pytest tests/test_sap_adt_integration.py -v
"""

import os
import pytest
from src.config import get_settings
from src.core.exceptions import SAPConnectorError, SAPSecurityError
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector


def is_live_sap_enabled() -> bool:
    live_flag = os.getenv("RUN_LIVE_SAP_TESTS", "").lower() in ("true", "1", "yes")
    read_only_flag = os.getenv("SAP_LIVE_READ_ONLY", "").lower() in ("true", "1", "yes")
    return live_flag and read_only_flag


LIVE_SKIP_REASON = (
    "Live SAP integration tests disabled by default. "
    "To execute, set RUN_LIVE_SAP_TESTS=true and SAP_LIVE_READ_ONLY=true in environment."
)


# Phase 0: Offline Preflight & Safety Configuration
@pytest.mark.skipif(not is_live_sap_enabled(), reason=LIVE_SKIP_REASON)
def test_phase_0_offline_preflight_and_safety():
    """Phase 0: Verifies that live safety kill switch and settings are properly configured."""
    settings = get_settings()
    assert settings.SAP_LIVE_READ_ONLY is True, "SAP_LIVE_READ_ONLY must be explicitly enabled."
    assert settings.SAP_BASE_URL.startswith("https://"), "SAP_BASE_URL must use HTTPS."
    assert settings.SAP_CLIENT == "100"
    assert settings.SAP_VERIFY_SSL is True, "SAP_VERIFY_SSL must remain True by default."

    # Test pre-socket write blocker raises offline
    client = SAPADTClient(settings=settings)
    with pytest.raises(SAPSecurityError):
        client.assert_zero_write_policy("POST", "/sap/bc/adt/ddic/ddl/sources")


# Phase 1: Real SAP ADT Read-Only Smoke Test
@pytest.mark.skipif(not is_live_sap_enabled(), reason=LIVE_SKIP_REASON)
@pytest.mark.asyncio
async def test_phase_1_real_adt_read_only_smoke():
    """Phase 1: Proves authenticated read-only ADT interaction with SAP DEV."""
    settings = get_settings()
    client = SAPADTClient(settings=settings)
    is_live = await client.check_connectivity()
    assert is_live is True, "Expected authenticated ADT smoke test to return True."


# Phase 2: Real CDS Search
@pytest.mark.skipif(not is_live_sap_enabled(), reason=LIVE_SKIP_REASON)
@pytest.mark.asyncio
async def test_phase_2_real_cds_search():
    """Phase 2: Issues verified quickSearch query against SAP information system."""
    settings = get_settings()
    client = SAPADTClient(settings=settings)
    results = await client.search_information_system("DDLSALES*", max_results=10)
    assert isinstance(results, list)
    assert len(results) > 0, "Expected at least one search result matching DDLSALES*."
    assert any("I_SalesOrder" in r.get("name", "") for r in results)


# Phase 3: Real DDL Source Retrieval
@pytest.mark.skipif(not is_live_sap_enabled(), reason=LIVE_SKIP_REASON)
@pytest.mark.asyncio
async def test_phase_3_real_ddl_source_retrieval():
    """Phase 3: Fetches verified CDS DDL source for standard view I_SalesOrder."""
    settings = get_settings()
    connector = SAPADTConnector(settings=settings)
    meta = await connector.get_cds_metadata("i_salesorder")
    assert meta.view_name.lower() == "i_salesorder"
    assert len(meta.fields) > 0
    assert any(f.field_name.upper() == "SALESORDER" for f in meta.fields)


# Phase 4: Real Read-Only ADT Checkrun on Existing Repository Object
@pytest.mark.skipif(not is_live_sap_enabled(), reason=LIVE_SKIP_REASON)
@pytest.mark.asyncio
async def test_phase_4_real_read_only_adt_checkrun():
    """Phase 4: Executes real read-only checkrun on active repository object /sap/bc/adt/ddic/ddl/sources/i_salesorder."""
    settings = get_settings()
    client = SAPADTClient(settings=settings)
    checkrun_res = await client.run_checkrun("/sap/bc/adt/ddic/ddl/sources/i_salesorder")
    assert checkrun_res.reporter == "abapCheckRun"
    assert checkrun_res.http_status in (200, 201)
    # Valid real compiler result (PASS, WARNING, or ERROR if system has local syntax notes)
    assert checkrun_res.status.value in ("PASS", "WARNING", "ERROR")


# Write Refusal Test on Live Connector
@pytest.mark.skipif(not is_live_sap_enabled(), reason=LIVE_SKIP_REASON)
@pytest.mark.asyncio
async def test_live_connector_refuses_all_writes():
    """Confirms live connector rejects creation and activation operations locally."""
    settings = get_settings()
    connector = SAPADTConnector(settings=settings)

    with pytest.raises(SAPConnectorError):
        await connector.create_cds_draft("Z_LiveTest", "code", "ZPKG", "TR123")

    with pytest.raises(SAPConnectorError):
        await connector.activate_cds("Z_LiveTest", "TR123")
