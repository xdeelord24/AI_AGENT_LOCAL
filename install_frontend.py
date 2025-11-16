#!/usr/bin/env python3
"""
Install frontend dependencies
"""

import subprocess
import sys
import os

def main():
    """Install frontend dependencies"""
    print("🔄 Installing frontend dependencies...")
    
    # Check if frontend directory exists
    if not os.path.exists("frontend"):
        print("❌ Frontend directory not found")
        return False
    
    # Check if package.json exists
    if not os.path.exists("frontend/package.json"):
        print("❌ package.json not found in frontend directory")
        return False
    
    try:
        # Change to frontend directory
        os.chdir("frontend")
        
        # Install dependencies
        print("📦 Running npm install...")
        result = subprocess.run(["npm", "install"], check=True, capture_output=True, text=True)
        print("✅ Frontend dependencies installed successfully")
        
        # Go back to parent directory
        os.chdir("..")
        return True
        
    except FileNotFoundError:
        print("❌ npm not found. Please install Node.js from https://nodejs.org")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ npm install failed: {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n🎉 Frontend setup completed!")
        print("You can now run: python start.py")
    else:
        print("\n❌ Frontend setup failed")
        sys.exit(1)
