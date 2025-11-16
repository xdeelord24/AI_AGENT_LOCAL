#!/usr/bin/env python3
"""
Start only the backend server for testing
"""

import sys
import os

def main():
    """Start the backend server only"""
    print("🚀 Starting Offline AI Agent Backend...")
    print("Backend will run on: http://localhost:8000")
    print("API docs will be available at: http://localhost:8000/docs")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    
    try:
        # Import and run the main application
        from main import create_app
        import uvicorn
        
        app = create_app()
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8000,
            reload=False,  # Disable reload for simpler startup
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n🛑 Backend server stopped")
    except Exception as e:
        print(f"❌ Backend server error: {e}")
        print("\n💡 Troubleshooting:")
        print("1. Make sure all dependencies are installed: pip install -r requirements.txt")
        print("2. Check if Ollama is running: ollama serve")
        print("3. Try running: python install_deps.py")

if __name__ == "__main__":
    main()
