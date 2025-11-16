#!/usr/bin/env python3
"""
Simple dependency installer that handles version conflicts
"""

import subprocess
import sys
import os

def install_package(package):
    """Install a single package with error handling"""
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", package], check=True)
        print(f"✅ Installed {package}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install {package}: {e}")
        return False

def main():
    """Install dependencies with fallback options"""
    print("🔄 Installing Python dependencies...")
    
    # Core dependencies that should work on most systems
    core_packages = [
        "fastapi>=0.100.0",
        "uvicorn>=0.20.0", 
        "pydantic>=2.0.0",
        "requests>=2.25.0",
        "python-multipart>=0.0.5",
        "aiofiles>=23.0.0",
        "watchdog>=3.0.0",
        "python-dotenv>=1.0.0"
    ]
    
    # Tree-sitter packages with fallbacks
    tree_sitter_packages = [
        "tree-sitter>=0.20.0",
        "tree-sitter-python>=0.20.0",
        "tree-sitter-javascript>=0.20.0", 
        "tree-sitter-typescript>=0.20.0",
        "tree-sitter-json>=0.20.0"
    ]
    
    # Install core packages
    print("\n📦 Installing core packages...")
    for package in core_packages:
        install_package(package)
    
    # Install tree-sitter packages with fallbacks
    print("\n🌳 Installing tree-sitter packages...")
    for package in tree_sitter_packages:
        if not install_package(package):
            # Try without version constraint
            package_name = package.split(">=")[0]
            print(f"⚠️  Trying {package_name} without version constraint...")
            install_package(package_name)
    
    # Try tree-sitter-yaml separately as it might have different requirements
    print("\n📄 Installing tree-sitter-yaml...")
    yaml_packages = ["tree-sitter-yaml>=0.0.1", "tree-sitter-yaml"]
    for package in yaml_packages:
        if install_package(package):
            break
    
    print("\n✅ Dependency installation completed!")
    print("\n📋 Next steps:")
    print("1. Make sure Ollama is installed and running")
    print("2. Download a model: ollama pull codellama")
    print("3. Start the application: python main.py")

if __name__ == "__main__":
    main()
