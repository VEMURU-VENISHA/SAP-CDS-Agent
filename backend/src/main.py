"""Main Application Entrypoint for SAP CDS Intelligence & Automation Platform."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from src.api.middleware.error_handler import register_exception_handlers
from src.api.middleware.request_id import CorrelationIdMiddleware
from src.api.router import api_v1_router
from src.config import get_settings
from src.db.session import init_db
from src.logging_config import logger, setup_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context managing startup and shutdown."""
    setup_logging(settings.LOG_LEVEL)
    logger.info("=================================================================")
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT} | Debug: {settings.DEBUG}")
    logger.info(f"Target SAP: SID={settings.SAP_SYSTEM_ID}, Client={settings.SAP_CLIENT}, Release={settings.SAP_S4HANA_RELEASE}")
    logger.info("SAP Guardrail: UNCONNECTED MODE strictly enforced.")
    logger.info("=================================================================")

    # Initialize database
    await init_db()

    yield

    logger.info("Shutting down SAP CDS Intelligence Platform...")


def create_application() -> FastAPI:
    """Factory function creating and configuring the FastAPI instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "AI-powered enterprise platform that discovers SAP CDS views, tables, and associations "
            "in SAP S/4HANA, and recommends REUSE -> EXTEND -> CREATE."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. Register Correlation ID middleware
    app.add_middleware(CorrelationIdMiddleware)

    # 2. Register CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Register global exception handlers
    register_exception_handlers(app)

    # 4. Include API v1 Router
    app.include_router(api_v1_router)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/docs")

    return app


app = create_application()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )
