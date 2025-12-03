#!/usr/bin/env python3
"""
Offline AI Agent - Main Application Entry Point
A Cursor-like AI coding assistant that runs entirely offline.
"""

import asyncio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import sys

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.api import router as api_router
from backend.services.ai_service import AIService
from backend.services.file_service import FileService
from backend.services.code_analyzer import CodeAnalyzer
from backend.services.terminal_service import TerminalService

try:
    from backend.services.mcp_server import MCPServerTools
    MCP_AVAILABLE = True
except ImportError:
    MCPServerTools = None
    MCP_AVAILABLE = False


# Ensure Windows event loop supports subprocess operations (required for terminal)
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    print("🚀 Starting Offline AI Agent...")
    
    # Initialize services
    app.state.ai_service = AIService()
    app.state.file_service = FileService()
    app.state.code_analyzer = CodeAnalyzer()
    app.state.terminal_service = TerminalService(base_path=os.getcwd())
    
    # Initialize enhanced web search service
    try:
        from backend.services.web_search_service import WebSearchService
        web_search_service = WebSearchService(
            cache_size=int(os.getenv("WEB_SEARCH_CACHE_SIZE", "100")),
            cache_ttl_seconds=int(os.getenv("WEB_SEARCH_CACHE_TTL", "3600"))
        )
        # Share web search service with AI service
        if hasattr(app.state.ai_service, '_web_search_service'):
            app.state.ai_service._web_search_service = web_search_service
        print("✅ Enhanced web search service initialized")
    except Exception as e:
        print(f"⚠️  Warning: Enhanced web search not available: {e}")
        web_search_service = None
    
    # Initialize location service for weather and news
    try:
        from backend.services.location_service import LocationService
        location_service = LocationService()
        print("✅ Location service initialized (weather & news available)")
    except Exception as e:
        print(f"⚠️  Warning: Location service not available: {e}")
        location_service = None
    
    # Initialize memory service
    try:
        from backend.services.memory_service import MemoryService
        memory_service = MemoryService()
        app.state.memory_service = memory_service  # Store in app.state for API access
        print("✅ Memory service initialized")
    except Exception as e:
        print(f"⚠️  Warning: Memory service not available: {e}")
        memory_service = None
        app.state.memory_service = None
    
    # Initialize MCP tools if available
    if MCP_AVAILABLE and MCPServerTools:
        try:
            web_search_enabled = os.getenv("ENABLE_WEB_SEARCH", "true").lower() in ("true", "1", "yes")
            mcp_tools = MCPServerTools(
                file_service=app.state.file_service,
                code_analyzer=app.state.code_analyzer,
                web_search_enabled=web_search_enabled,
                web_search_service=web_search_service,  # Share web search service instance
                location_service=location_service,  # Share location service instance
                memory_service=memory_service  # Share memory service instance
            )
            app.state.ai_service.set_mcp_tools(mcp_tools)
            print("✅ MCP tools enabled and available")
        except Exception as e:
            print(f"⚠️  Warning: Failed to initialize MCP tools: {e}")
            print("   Continuing without MCP tools...")
    else:
        print("ℹ️  MCP tools not available (install with: pip install mcp)")
    
    # Check if Ollama is running
    if not await app.state.ai_service.check_ollama_connection():
        print("⚠️  Warning: Ollama is not running. Please start Ollama and install a model.")
        print("   Run: ollama serve")
        print("   Then: ollama pull codellama")
    
    print("✅ Offline AI Agent is ready!")
    yield
    
    # Shutdown
    print("🛑 Shutting down Offline AI Agent...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        title="Offline AI Agent",
        description="A Cursor-like AI coding assistant that runs entirely offline",
        version="1.0.0",
        lifespan=lifespan
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000", 
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001"
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    
    # Include API routes
    app.include_router(api_router, prefix="/api")
    
    @app.get("/")
    async def root():
        return {
            "message": "Offline AI Agent is running!",
            "status": "online",
            "version": "1.0.0"
        }
    
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "offline-ai-agent"}
    
    return app


if __name__ == "__main__":
    uvicorn.run(
        "main:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
