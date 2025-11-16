#!/usr/bin/env python3
"""
Start script with Ollama proxy for better CORS handling
"""

import subprocess
import sys
import os
import time
import threading
import signal

def run_proxy():
    """Run the Ollama proxy server"""
    print("🚀 Starting Ollama proxy server...")
    try:
        subprocess.run([sys.executable, "ollama_proxy.py"], check=True)
    except KeyboardInterrupt:
        print("\n🛑 Proxy server stopped")
    except Exception as e:
        print(f"❌ Proxy server error: {e}")

def run_backend():
    """Run the backend server"""
    print("🚀 Starting backend server...")
    try:
        subprocess.run([sys.executable, "main.py"], check=True)
    except KeyboardInterrupt:
        print("\n🛑 Backend server stopped")
    except Exception as e:
        print(f"❌ Backend server error: {e}")

def run_frontend():
    """Run the frontend development server"""
    print("🚀 Starting frontend server...")
    try:
        # Check if frontend directory exists
        if not os.path.exists("frontend"):
            print("❌ Frontend directory not found")
            return
        
        # Check if node_modules exists
        if not os.path.exists("frontend/node_modules"):
            print("⚠️  Frontend dependencies not installed. Installing...")
            os.chdir("frontend")
            subprocess.run(["npm", "install"], check=True, shell=True)
            os.chdir("..")
        
        # Start the frontend server
        os.chdir("frontend")
        subprocess.run(["npm", "start"], check=True, shell=True)
    except KeyboardInterrupt:
        print("\n🛑 Frontend server stopped")
    except Exception as e:
        print(f"❌ Frontend server error: {e}")

def check_ollama():
    """Check if Ollama is running"""
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            print("✅ Ollama is running")
            return True
    except:
        pass
    
    print("⚠️  Ollama is not running. Please start it with: ollama serve")
    return False

def main():
    """Main function"""
    print("🤖 Starting Offline AI Agent with Proxy...")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists("main.py") or not os.path.exists("frontend"):
        print("❌ Please run this script from the project root directory")
        return False
    
    # Check Ollama
    check_ollama()
    
    print("\n📋 Starting services...")
    print("Proxy will run on: http://localhost:5000")
    print("Backend will run on: http://localhost:8000")
    print("Frontend will run on: http://localhost:3000")
    print("Browser will open automatically when frontend is ready")
    print("Press Ctrl+C to stop all services")
    print("=" * 50)
    
    # Start proxy in a separate thread
    proxy_thread = threading.Thread(target=run_proxy, daemon=True)
    proxy_thread.start()
    
    # Wait a moment for proxy to start
    time.sleep(2)
    
    # Start backend in a separate thread
    backend_thread = threading.Thread(target=run_backend, daemon=True)
    backend_thread.start()
    
    # Wait a moment for backend to start
    time.sleep(3)
    
    # Note: Browser will be opened automatically by React's npm start command
    
    # Start frontend (this will block)
    try:
        run_frontend()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Offline AI Agent...")
    
    return True

if __name__ == "__main__":
    main()
