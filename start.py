#!/usr/bin/env python3
"""
Start script for Offline AI Agent
"""

import os
import sys
import subprocess
import time
import threading
import webbrowser
from pathlib import Path

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
            # Try different ways to find npm
            npm_commands = ["npm", "npm.cmd", "npm.exe"]
            npm_found = False
            
            for npm_cmd in npm_commands:
                try:
                    subprocess.run([npm_cmd, "install"], check=True, shell=True)
                    npm_found = True
                    break
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            
            if not npm_found:
                print("❌ Could not find npm. Please check your Node.js installation.")
                os.chdir("..")
                return
            
            os.chdir("..")
        
        # Ensure CRA dev server uses safe defaults even without LAN IP
        os.environ.pop("HOST", None)
        os.environ.setdefault("DANGEROUSLY_DISABLE_HOST_CHECK", "true")

        # Start the frontend server
        os.chdir("frontend")
        # Try different ways to find npm for starting
        npm_commands = ["npm", "npm.cmd", "npm.exe"]
        npm_found = False
        
        for npm_cmd in npm_commands:
            try:
                subprocess.run([npm_cmd, "start"], check=True, shell=True)
                npm_found = True
                break
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        
        if not npm_found:
            print("❌ Could not find npm to start the frontend server.")
            
    except KeyboardInterrupt:
        print("\n🛑 Frontend server stopped")
    except Exception as e:
        print(f"❌ Frontend server error: {e}")
        print("💡 Try running manually: cd frontend && npm install && npm start")

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
    """Main start function"""
    print("🤖 Starting Offline AI Agent...")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists("main.py") or not os.path.exists("frontend"):
        print("❌ Please run this script from the project root directory")
        return False
    
    # Check Ollama
    check_ollama()
    
    print("\n📋 Starting services...")
    print("Backend will run on: http://localhost:8000")
    print("Frontend will run on: http://localhost:3000")
    print("Press Ctrl+C to stop all services")
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
            webbrowser.open("http://localhost:3000")
        except:
            pass
    
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    # Start frontend (this will block)
    try:
        run_frontend()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Offline AI Agent...")
    
    return True

if __name__ == "__main__":
    main()
