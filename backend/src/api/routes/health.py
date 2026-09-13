"""Health and System Status API Route."""

from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import text
from src.config import get_settings
from src.db.session import engine
from src.sap.connector import get_sap_connector

router = APIRouter(prefix="/health", tags=["System Health"])
settings = get_settings()


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    environment: str
    timestamp: str
    database: Dict[str, Any]
    sap_connector: Dict[str, Any]


@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Platform health check and system landscape audit",
)
async def get_health_status():
    """Checks the runtime health of the API, Database engine, and SAP Connector status."""
    # Test DB connectivity
    db_status = "unreachable"
    db_driver = settings.DATABASE_URL.split("://")[0]
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_status = "connected"
    except Exception as e:
        db_status = f"degraded ({type(e).__name__})"

    # Retrieve SAP connector status
    connector = get_sap_connector()
    sap_info = await connector.get_system_info()

    return HealthResponse(
        status="healthy",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc).isoformat(),
        database={
            "status": db_status,
            "driver": db_driver,
        },
        sap_connector={
            "status": "unconnected (guarded)",
            "system_id": sap_info.system_id,
            "client": sap_info.client,
            "s4hana_release": sap_info.s4hana_release,
            "s4core_release": sap_info.s4core_release,
            "basis_release": sap_info.basis_release,
            "is_connected": sap_info.is_connected,
        },
    )
