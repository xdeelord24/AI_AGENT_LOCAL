#!/usr/bin/env python3
"""
Test script to verify all connections are working
"""

import requests
import json

def test_backend():
    """Test backend connection"""
    try:
        print("🔄 Testing backend connection...")
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ Backend is running")
            print(f"   Response: {response.json()}")
            return True
        else:
            print(f"❌ Backend returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Backend connection failed: {e}")
        return False

def test_ollama():
    """Test Ollama connection"""
    try:
        print("🔄 Testing Ollama connection...")
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            print("✅ Ollama is running")
            models = response.json().get("models", [])
            print(f"   Available models: {len(models)}")
            for model in models[:3]:  # Show first 3 models
                print(f"   - {model.get('name', 'Unknown')}")
            return True
        else:
            print(f"❌ Ollama returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Ollama connection failed: {e}")
        return False

def test_api_endpoints():
    """Test API endpoints"""
    endpoints = [
        "/api/chat/status",
        "/api/chat/models",
        "/api/files/list/.",
    ]
    
    print("🔄 Testing API endpoints...")
    for endpoint in endpoints:
        try:
            response = requests.get(f"http://localhost:8000{endpoint}", timeout=5)
            if response.status_code == 200:
                print(f"✅ {endpoint} - OK")
            else:
                print(f"❌ {endpoint} - Status {response.status_code}")
        except Exception as e:
            print(f"❌ {endpoint} - Error: {e}")

def main():
    """Main test function"""
    print("Testing Offline AI Agent Connections")
    print("=" * 50)
    
    backend_ok = test_backend()
    ollama_ok = test_ollama()
    
    if backend_ok:
        test_api_endpoints()
    
    print("\n" + "=" * 50)
    if backend_ok and ollama_ok:
        print("🎉 All connections are working!")
        print("💡 If the frontend still shows disconnected, try:")
        print("   1. Refresh the browser page")
        print("   2. Check browser console for errors (F12)")
        print("   3. Try opening http://localhost:3000 in incognito mode")
    else:
        print("❌ Some connections failed. Check the errors above.")
        if not backend_ok:
            print("💡 Backend issue: Make sure 'python main.py' is running")
        if not ollama_ok:
            print("💡 Ollama issue: Make sure 'ollama serve' is running")

if __name__ == "__main__":
    main()
