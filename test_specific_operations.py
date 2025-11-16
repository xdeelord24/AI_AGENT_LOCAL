#!/usr/bin/env python3
"""
Test specific operations that are failing
"""

import requests
import json
import os

def test_code_analysis():
    """Test code analysis endpoint"""
    try:
        # Create a test Python file
        test_file = "test_code.py"
        with open(test_file, "w") as f:
            f.write("""
def hello_world():
    print("Hello, World!")

class TestClass:
    def __init__(self):
        self.value = 42
""")
        
        response = requests.post(f"http://localhost:8000/api/code/analyze/{test_file}")
        print(f"Code Analysis: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            data = response.json()
            print(f"Language: {data.get('language')}")
            print(f"Functions: {len(data.get('functions', []))}")
            print(f"Classes: {len(data.get('classes', []))}")
        
        # Clean up
        if os.path.exists(test_file):
            os.remove(test_file)
        
        return response.status_code == 200
    except Exception as e:
        print(f"Code Analysis failed: {e}")
        return False

def test_file_write():
    """Test file write operation"""
    try:
        test_content = "print('Hello from test file!')"
        response = requests.post(
            "http://localhost:8000/api/files/write/test_write.py",
            json={"content": test_content}
        )
        print(f"File Write: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            print("File written successfully")
        
        # Clean up
        if os.path.exists("test_write.py"):
            os.remove("test_write.py")
        
        return response.status_code == 200
    except Exception as e:
        print(f"File Write failed: {e}")
        return False

def test_file_read():
    """Test file read operation"""
    try:
        # Create a test file first
        with open("test_read.txt", "w") as f:
            f.write("This is a test file for reading.")
        
        response = requests.get("http://localhost:8000/api/files/read/test_read.txt")
        print(f"File Read: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            data = response.json()
            print(f"Content length: {len(data.get('content', ''))}")
        
        # Clean up
        if os.path.exists("test_read.txt"):
            os.remove("test_read.txt")
        
        return response.status_code == 200
    except Exception as e:
        print(f"File Read failed: {e}")
        return False

def test_code_generation():
    """Test code generation"""
    try:
        payload = {
            "prompt": "Write a Python function to calculate factorial",
            "language": "python",
            "context": {},
            "max_length": 500
        }
        response = requests.post("http://localhost:8000/api/code/generate", json=payload)
        print(f"Code Generation: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            data = response.json()
            print(f"Generated code length: {len(data.get('generated_code', ''))}")
        
        return response.status_code == 200
    except Exception as e:
        print(f"Code Generation failed: {e}")
        return False

def main():
    print("Testing Specific Operations")
    print("=" * 40)
    
    tests = [
        ("Code Analysis", test_code_analysis),
        ("File Write", test_file_write),
        ("File Read", test_file_read),
        ("Code Generation", test_code_generation),
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
