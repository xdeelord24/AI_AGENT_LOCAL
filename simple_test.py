#!/usr/bin/env python3
"""
Simple connection test without emojis
"""

import requests
import json

def test_backend():
    """Test backend connection"""
    try:
        print("Testing backend connection...")
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("OK - Backend is running")
            print(f"Response: {response.json()}")
            return True
        else:
            print(f"ERROR - Backend returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"ERROR - Backend connection failed: {e}")
        return False

def test_ollama():
    """Test Ollama connection"""
    try:
        print("Testing Ollama connection...")
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            print("OK - Ollama is running")
            models = response.json().get("models", [])
            print(f"Available models: {len(models)}")
            for model in models[:3]:  # Show first 3 models
                print(f"  - {model.get('name', 'Unknown')}")
            return True
        else:
            print(f"ERROR - Ollama returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"ERROR - Ollama connection failed: {e}")
        return False

def test_api_endpoints():
    """Test API endpoints"""
    endpoints = [
        "/api/chat/status",
        "/api/chat/models",
    ]
    
    print("Testing API endpoints...")
    for endpoint in endpoints:
        try:
            response = requests.get(f"http://localhost:8000{endpoint}", timeout=5)
            if response.status_code == 200:
                print(f"OK - {endpoint}")
            else:
                print(f"ERROR - {endpoint} - Status {response.status_code}")
                print(f"Response: {response.text}")
        except Exception as e:
            print(f"ERROR - {endpoint} - Error: {e}")

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
        print("SUCCESS - All connections are working!")
    else:
        print("ERROR - Some connections failed. Check the errors above.")

if __name__ == "__main__":
    main()
