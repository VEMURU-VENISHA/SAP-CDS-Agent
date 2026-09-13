"""Unit Tests for Milestone 8 Security Controls & Zero-Write Policy."""

import pytest
from pydantic import SecretStr
import httpx

from src.config import Settings
from src.core.exceptions import SAPSecurityError, SAPConnectorError
from src.sap.adt_client import SAPADTClient
from src.sap.adt_connector import SAPADTConnector


def get_secure_settings(**kwargs):
    default_args = {
        "SAP_BASE_URL": "https://sap-dev.corp.internal:44300",
        "SAP_CLIENT": "100",
        "SAP_USERNAME": "DEVELOPER",
        "SAP_PASSWORD": SecretStr("SecretPass123!"),
        "SAP_AUTH_TYPE": "basic",
        "SAP_VERIFY_SSL": True,
        "SAP_LIVE_READ_ONLY": False,
        "SAP_LIVE_TEST_ENABLED": False,
        "SAP_SEND_CLIENT_PARAM": False,
    }
    default_args.update(kwargs)
    return Settings(**default_args)


# 1. Pre-socket blocker: rejecting modifying HTTP methods (PUT, DELETE, PATCH)
def test_security_guard_blocks_modifying_methods():
    settings = get_secure_settings()
    client = SAPADTClient(settings=settings)

    for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
        with pytest.raises(SAPSecurityError) as exc:
            client.assert_zero_write_policy(method, "/sap/bc/adt/ddic/ddl/sources/z_custom_view")
        assert "modifying HTTP method" in str(exc.value)
        assert method in str(exc.value)


# 2. Pre-socket blocker: rejecting unauthorized POST requests
def test_security_guard_blocks_unauthorized_posts():
    settings = get_secure_settings()
    client = SAPADTClient(settings=settings)

    # Attempt to POST to CDS creation endpoint
    with pytest.raises(SAPSecurityError) as exc1:
        client.assert_zero_write_policy("POST", "/sap/bc/adt/ddic/ddl/sources")
    assert "unauthorized POST" in str(exc1.value)

    # Attempt to POST to activation endpoint
    with pytest.raises(SAPSecurityError) as exc2:
        client.assert_zero_write_policy("POST", "/sap/bc/adt/activation")
    assert "unauthorized POST" in str(exc2.value)

    # Attempt to POST to transport creation endpoint
    with pytest.raises(SAPSecurityError) as exc3:
        client.assert_zero_write_policy("POST", "/sap/bc/adt/cts/transports")
    assert "unauthorized POST" in str(exc3.value)

    # Attempt to POST to checkruns with non-approved reporter
    with pytest.raises(SAPSecurityError) as exc4:
        client.assert_zero_write_policy("POST", "/sap/bc/adt/checkruns", params={"reporters": "arbitraryCheck"})
    assert "unauthorized POST" in str(exc4.value)


# 3. Pre-socket blocker: rejecting non-allowlisted GET endpoints
def test_security_guard_blocks_non_allowlisted_gets():
    settings = get_secure_settings()
    client = SAPADTClient(settings=settings)

    # Speculative or unverified GET paths
    with pytest.raises(SAPSecurityError) as exc1:
        client.assert_zero_write_policy("GET", "/sap/bc/adt/cts/transports")
    assert "non-allowlisted GET endpoint" in str(exc1.value)

    with pytest.raises(SAPSecurityError) as exc2:
        client.assert_zero_write_policy("GET", "/sap/bc/adt/packages/Z_PACKAGE")
    assert "non-allowlisted GET endpoint" in str(exc2.value)


# 4. Pre-socket allowlist: permitting verified read-only operations
def test_security_guard_permits_verified_operations():
    # When SAP_LIVE_READ_ONLY is True or using custom mock client, verified operations pass without error
    settings = get_secure_settings(SAP_LIVE_READ_ONLY=True)
    client = SAPADTClient(settings=settings)

    # 1. Search endpoint
    client.assert_zero_write_policy("GET", "/sap/bc/adt/repository/informationsystem/search")

    # 2. DDL source retrieval endpoint
    client.assert_zero_write_policy("GET", "/sap/bc/adt/ddic/ddl/sources/i_salesorder")
    client.assert_zero_write_policy("GET", "/sap/bc/adt/ddic/ddl/sources/c_salesorderitemdex")

    # 3. Checkrun endpoint with verified reporter
    client.assert_zero_write_policy("POST", "/sap/bc/adt/checkruns", params={"reporters": "abapCheckRun"})


# 5. Mandatory live read-only kill switch: refuses socket opening if SAP_LIVE_READ_ONLY is False
@pytest.mark.asyncio
async def test_live_read_only_kill_switch_blocks_network_dispatch():
    # Real live client (no mock client passed) with SAP_LIVE_READ_ONLY=False
    settings = get_secure_settings(SAP_LIVE_READ_ONLY=False)
    client = SAPADTClient(settings=settings)

    # get_ddl_source must be rejected before any network socket is opened
    with pytest.raises(SAPSecurityError) as exc_ddl:
        await client.get_ddl_source("i_salesorder")
    assert "SAP_LIVE_READ_ONLY is not enabled" in str(exc_ddl.value)

    # search_information_system must be rejected before socket opening
    with pytest.raises(SAPSecurityError) as exc_search:
        await client.search_information_system("DDLSALES*")
    assert "SAP_LIVE_READ_ONLY is not enabled" in str(exc_search.value)

    # check_connectivity smoke test returns False safely
    is_live = await client.check_connectivity()
    assert is_live is False

    # run_checkrun returns UNAVAILABLE
    res = await client.run_checkrun("/sap/bc/adt/ddic/ddl/sources/i_salesorder")
    assert res.status.value == "UNAVAILABLE"
    assert "Security guard blocked execution" in (res.reason or "")


# 6. HTTP client configuration: follow_redirects=False enforced
@pytest.mark.asyncio
async def test_follow_redirects_disabled_on_client():
    settings = get_secure_settings()
    client = SAPADTClient(settings=settings)
    http_client = await client._get_client()
    try:
        assert http_client.follow_redirects is False
    finally:
        await http_client.aclose()


# 7. TLS verification: secure default is True
def test_tls_verification_defaults_to_true():
    # Isolate from local developer .env file to verify application's built-in defaults
    settings = Settings(_env_file=None)
    assert settings.SAP_VERIFY_SSL is True
    assert settings.SAP_LIVE_READ_ONLY is False
    assert settings.SAP_LIVE_TEST_ENABLED is False


# 8. Client routing parameter is conditional, not hard-coded
def test_client_routing_param_conditional():
    # By default, SAP_SEND_CLIENT_PARAM is False
    settings_no_client = get_secure_settings(SAP_SEND_CLIENT_PARAM=False, SAP_CLIENT="100")
    client_no_param = SAPADTClient(settings=settings_no_client)
    headers = client_no_param._get_auth_headers()
    assert "sap-client" not in headers

    # When enabled, sap-client is included
    settings_with_client = get_secure_settings(SAP_SEND_CLIENT_PARAM=True, SAP_CLIENT="100")
    client_with_param = SAPADTClient(settings=settings_with_client)
    headers_with = client_with_param._get_auth_headers()
    assert headers_with.get("sap-client") == "100"


# 9. Connector zero write and stub fallback
@pytest.mark.asyncio
async def test_connector_zero_write_and_stub_fallback():
    settings = get_secure_settings(SAP_CONNECTOR_TYPE="stub")
    connector = SAPADTConnector(settings=settings)

    # Write operations raise locally
    with pytest.raises(SAPConnectorError) as exc_draft:
        await connector.create_cds_draft("Z_Draft", "code", "ZPKG", "TR123")
    assert "strictly read-only" in str(exc_draft.value)

    with pytest.raises(SAPConnectorError) as exc_act:
        await connector.activate_cds("Z_Draft", "TR123")
    assert "strictly read-only" in str(exc_act.value)
