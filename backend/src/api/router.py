"""API Router consolidating version 1 endpoints."""

from fastapi import APIRouter
from src.api.routes.decisions import router as decisions_router
from src.api.routes.discovery import router as discovery_router
from src.api.routes.health import router as health_router
from src.api.routes.requirements import router as requirements_router
from src.api.routes.reviews import router as reviews_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(health_router)
api_v1_router.include_router(requirements_router)
api_v1_router.include_router(discovery_router)
api_v1_router.include_router(decisions_router)
api_v1_router.include_router(reviews_router)

api_legacy_router = APIRouter(prefix="/api")
api_legacy_router.include_router(health_router)
api_legacy_router.include_router(requirements_router)
api_legacy_router.include_router(discovery_router)
api_legacy_router.include_router(decisions_router)
api_legacy_router.include_router(reviews_router)
