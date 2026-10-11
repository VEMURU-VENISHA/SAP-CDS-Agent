"""Tests for Health Endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(async_client: AsyncClient):
    """Verifies that the /api/v1/health endpoint responds with 200 and expected schema."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert "SAP CDS Intelligence" in data["app_name"]
    assert "database" in data
    assert "sap_connector" in data
    assert isinstance(data["sap_connector"]["is_connected"], bool)
    assert data["sap_connector"]["system_id"] == "DEV"
    assert data["sap_connector"]["client"] == "100"
    assert data["sap_connector"]["s4hana_release"] == "2023"


@pytest.mark.asyncio
async def test_correlation_id_header(async_client: AsyncClient):
    """Verifies that the correlation ID middleware sets X-Correlation-ID in response headers."""
    response = await async_client.get("/api/v1/health")
    assert "X-Correlation-ID" in response.headers
    assert len(response.headers["X-Correlation-ID"]) > 0
