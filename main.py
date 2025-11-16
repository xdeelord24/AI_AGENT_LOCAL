#!/usr/bin/env python3
"""
Offline AI Agent - Main Application Entry Point
A Cursor-like AI coding assistant that runs entirely offline.
"""

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
