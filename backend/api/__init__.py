from fastapi import APIRouter
from .chat import router as chat_router
from .chat_sessions import router as chat_sessions_router
from .files import router as files_router
from .code import router as code_router
from .settings import router as settings_router
from .terminal import router as terminal_router
from .web_search import router as web_search_router
from .extensions import router as extensions_router
from .memory import router as memory_router
from .market_data import router as market_data_router

router = APIRouter()

# Include all sub-routers
router.include_router(chat_router, prefix="/chat", tags=["chat"])
router.include_router(chat_sessions_router, prefix="/chat", tags=["chat"])
router.include_router(files_router, prefix="/files", tags=["files"])
router.include_router(code_router, prefix="/code", tags=["code"])
router.include_router(settings_router, prefix="/settings", tags=["settings"])
router.include_router(terminal_router, prefix="/terminal", tags=["terminal"])
router.include_router(web_search_router, prefix="/web-search", tags=["web-search"])
router.include_router(extensions_router, prefix="/extensions", tags=["extensions"])
router.include_router(memory_router, prefix="/memory", tags=["memory"])
router.include_router(market_data_router)  # Already has /api/market-data prefix