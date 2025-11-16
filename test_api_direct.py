#!/usr/bin/env python3
"""
Direct API testing to identify issues
"""

import requests
import json

def test_health():
    """Test health endpoint"""
    try:
        response = requests.get("http://localhost:8000/health")
        print(f"Health: {response.status_code} - {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Health failed: {e}")
        return False

def test_chat_status():
    """Test chat status endpoint"""
    try:
        response = requests.get("http://localhost:8000/api/chat/status")
        print(f"Chat Status: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            print(f"Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Chat Status failed: {e}")
        return False

def test_chat_models():
    """Test chat models endpoint"""
    try:
        response = requests.get("http://localhost:8000/api/chat/models")
        print(f"Chat Models: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            print(f"Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Chat Models failed: {e}")
        return False

def test_file_list():
    """Test file list endpoint"""
    try:
        response = requests.get("http://localhost:8000/api/files/list/.")
        print(f"File List: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            data = response.json()
            print(f"Files found: {data.get('total_files', 0)}")
        return response.status_code == 200
    except Exception as e:
        print(f"File List failed: {e}")
        return False

def test_send_message():
    """Test sending a message"""
    try:
        payload = {
            "message": "Hello, can you help me write a simple Python function?",
            "context": {},
            "conversation_history": []
        }
        response = requests.post("http://localhost:8000/api/chat/send", json=payload)
        print(f"Send Message: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            data = response.json()
            print(f"Response length: {len(data.get('response', ''))}")
        return response.status_code == 200
    except Exception as e:
        print(f"Send Message failed: {e}")
        return False

def main():
    print("Testing API Endpoints Directly")
    print("=" * 40)
    
    tests = [
        ("Health Check", test_health),
        ("Chat Status", test_chat_status),
        ("Chat Models", test_chat_models),
        ("File List", test_file_list),
        ("Send Message", test_send_message),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n{name}:")
        result = test_func()
        results.append((name, result))
    
    print("\n" + "=" * 40)
    print("Results:")
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{name}: {status}")

if __name__ == "__main__":
    main()
