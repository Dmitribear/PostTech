from fastapi import APIRouter

from app.api.routes.academy import router as academy_router
from app.api.routes.ai import router as ai_router
from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.profile import router as profile_router
from app.api.routes.requests import router as requests_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(profile_router)
api_router.include_router(requests_router)
api_router.include_router(academy_router)
api_router.include_router(notifications_router)
api_router.include_router(ai_router)

from app.api.routes.workspace import router as workspace_router
api_router.include_router(workspace_router)
from app.api.routes.extensions import router as extensions_router
api_router.include_router(extensions_router)
from app.api.routes.hr_workflows import router as hr_workflows_router
api_router.include_router(hr_workflows_router)
