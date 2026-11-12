from fastapi import APIRouter

from app.api.v1.endpoints import auth, catalog, health, org, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(auth.approvals_router)
api_router.include_router(users.router)
api_router.include_router(org.router)
api_router.include_router(catalog.router)
