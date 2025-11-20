from fastapi import APIRouter
from .chat import router as chat_router
from .chat_sessions import router as chat_sessions_router
from .files import router as files_router
from .code import router as code_router
from .settings import router as settings_router
from .terminal import router as terminal_router

router = APIRouter()

# Include all sub-routers
router.include_router(chat_router, prefix="/chat", tags=["chat"])
router.include_router(chat_sessions_router, prefix="/chat", tags=["chat"])
router.include_router(files_router, prefix="/files", tags=["files"])
router.include_router(code_router, prefix="/code", tags=["code"])
router.include_router(settings_router, prefix="/settings", tags=["settings"])
router.include_router(terminal_router, prefix="/terminal", tags=["terminal"])