from fastapi import APIRouter

from app.presentation.http.routes.academy import router as academy_router
from app.presentation.http.routes.admin import router as admin_router
from app.presentation.http.routes.ai import router as ai_router
from app.presentation.http.routes.auth import router as auth_router
from app.presentation.http.routes.health import router as health_router
from app.presentation.http.routes.notifications import router as notifications_router
from app.presentation.http.routes.profile import router as profile_router
from app.presentation.http.routes.requests import router as requests_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(profile_router)
api_router.include_router(requests_router)
api_router.include_router(academy_router)
api_router.include_router(notifications_router)
api_router.include_router(ai_router)

from app.presentation.http.routes.workspace import router as workspace_router

api_router.include_router(workspace_router)
from app.presentation.http.routes.extensions import router as extensions_router

api_router.include_router(extensions_router)
from app.presentation.http.routes.hr_workflows import router as hr_workflows_router

api_router.include_router(hr_workflows_router)

from app.presentation.http.routes import local_ai

api_router.include_router(local_ai.router)
