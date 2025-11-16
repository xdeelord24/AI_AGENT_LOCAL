#!/usr/bin/env python3
"""
Manual start script - starts backend and provides instructions for frontend
"""

import subprocess
import sys
import os
import time
import threading
import webbrowser

def run_backend():
    """Run the backend server"""
    print("🚀 Starting backend server...")
    try:
        subprocess.run([sys.executable, "main.py"], check=True)
    except KeyboardInterrupt:
        print("\n🛑 Backend server stopped")
    except Exception as e:
        print(f"❌ Backend server error: {e}")

def main():
    """Main function"""
    print("🤖 Starting Offline AI Agent (Manual Mode)...")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists("main.py") or not os.path.exists("frontend"):
        print("❌ Please run this script from the project root directory")
        return False
    
    print("✅ Backend will start automatically")
    print("📋 Frontend instructions will be provided")
    print("=" * 50)
    
    # Start backend in a separate thread
    backend_thread = threading.Thread(target=run_backend, daemon=True)
    backend_thread.start()
    
    # Wait a moment for backend to start
    time.sleep(3)
    
    # Open browser after a delay
    def open_browser():
        time.sleep(5)
        try:
            webbrowser.open("http://localhost:8000/docs")
        except:
            pass
    
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    print("\n🎉 Backend is starting!")
    print("📖 API Documentation will open at: http://localhost:8000/docs")
    print("\n📋 To start the frontend manually:")
    print("1. Open a new terminal/command prompt")
    print("2. Navigate to this directory")
    print("3. Run: cd frontend")
    print("4. Run: npm install")
    print("5. Run: npm start")
    print("6. Open: http://localhost:3000")
    print("\n💡 Or use the API directly at: http://localhost:8000/docs")
    print("\nPress Ctrl+C to stop the backend server")
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    
    return True

if __name__ == "__main__":
    main()
