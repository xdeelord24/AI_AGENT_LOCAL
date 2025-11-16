#!/usr/bin/env python3
"""
Setup script for Offline AI Agent
"""

import os
import sys
import subprocess
import platform
import webbrowser
from pathlib import Path

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e.stderr}")
        return False

def check_python_version():
    """Check if Python version is compatible"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("❌ Python 3.8 or higher is required")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} is compatible")
    return True

def check_node_version():
    """Check if Node.js is installed"""
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"✅ Node.js {version} is installed")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ Node.js is not installed. Please install Node.js 16 or higher from https://nodejs.org")
    return False

def check_ollama():
    """Check if Ollama is installed and running"""
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Ollama is installed")
            
            # Check if Ollama is running
            try:
                import requests
                response = requests.get("http://localhost:11434/api/tags", timeout=5)
                if response.status_code == 200:
                    print("✅ Ollama is running")
                    return True
                else:
                    print("⚠️  Ollama is installed but not running")
                    return False
            except:
                print("⚠️  Ollama is installed but not running")
                return False
    except FileNotFoundError:
        print("❌ Ollama is not installed. Please install from https://ollama.ai")
        return False

def install_python_dependencies():
    """Install Python dependencies"""
    # Try the main requirements first
    if run_command("pip install -r requirements.txt", "Installing Python dependencies"):
        return True
    
    # If that fails, try the flexible requirements
    print("⚠️  Main requirements failed, trying flexible requirements...")
    return run_command("pip install -r requirements-flexible.txt", "Installing Python dependencies (flexible)")

def install_node_dependencies():
    """Install Node.js dependencies"""
    os.chdir("frontend")
    success = run_command("npm install", "Installing Node.js dependencies")
    os.chdir("..")
    return success

def download_ai_model():
    """Download a recommended AI model"""
    print("🔄 Downloading CodeLlama model (this may take a while)...")
    return run_command("ollama pull codellama", "Downloading CodeLlama model")

def create_env_file():
    """Create environment configuration file"""
    env_content = """# Offline AI Agent Configuration
API_HOST=0.0.0.0
API_PORT=8000
OLLAMA_URL=http://localhost:11434
DEFAULT_MODEL=codellama
LOG_LEVEL=info
"""
    
    with open(".env", "w") as f:
        f.write(env_content)
    print("✅ Created .env configuration file")

def main():
    """Main setup function"""
    print("🚀 Setting up Offline AI Agent...")
    print("=" * 50)
    
    # Check system requirements
    if not check_python_version():
        return False
    
    if not check_node_version():
        return False
    
    # Install dependencies
    if not install_python_dependencies():
        return False
    
    if not install_node_dependencies():
        return False
    
    # Check Ollama
    ollama_installed = check_ollama()
    if not ollama_installed:
        print("\n📋 To complete setup:")
        print("1. Install Ollama from https://ollama.ai")
        print("2. Start Ollama: ollama serve")
        print("3. Download a model: ollama pull codellama")
        print("4. Run this setup script again")
        return False
    
    # Download AI model if needed
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = response.json().get("models", [])
        if not any("codellama" in model.get("name", "") for model in models):
            if not download_ai_model():
                print("⚠️  Failed to download model. You can download it manually later.")
    except:
        print("⚠️  Could not check for models. You may need to download one manually.")
    
    # Create configuration
    create_env_file()
    
    print("\n" + "=" * 50)
    print("🎉 Setup completed successfully!")
    print("\n📋 Next steps:")
    print("1. Start the backend: python main.py")
    print("2. Start the frontend: cd frontend && npm start")
    print("3. Open http://localhost:3000 in your browser")
    print("\n💡 Tips:")
    print("- Make sure Ollama is running: ollama serve")
    print("- Download more models: ollama pull deepseek-coder")
    print("- Check the README.md for more information")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
