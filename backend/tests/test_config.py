"""Tests for Application Configuration."""

from src.config import Settings, get_settings


def test_settings_defaults():
    """Verifies default settings structure and SAP system parameters."""
    settings = get_settings()
    assert settings.APP_PORT == 8000
    assert settings.SAP_SYSTEM_ID == "DEV"
    assert settings.SAP_CLIENT == "100"
    assert settings.SAP_S4HANA_RELEASE == "2023"
    assert settings.SAP_CONNECTOR_ENABLED is False
    assert isinstance(settings.CORS_ORIGINS, list)
    assert len(settings.CORS_ORIGINS) >= 1
