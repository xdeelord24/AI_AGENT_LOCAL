# Installation Guide - Offline AI Agent

This guide will help you set up the Offline AI Agent on your system.

## Prerequisites

### System Requirements
- **Operating System**: Windows 10+, macOS 10.15+, or Linux
- **RAM**: 8GB minimum, 16GB recommended
- **Storage**: 10GB free space for models
- **CPU**: Modern multi-core processor
- **GPU**: Optional but recommended for better performance

### Software Requirements
- **Python**: 3.8 or higher
- **Node.js**: 16 or higher
- **Ollama**: Latest version

## Step-by-Step Installation

### 1. Install Python

#### Windows
1. Download Python from [python.org](https://www.python.org/downloads/)
2. Run the installer and check "Add Python to PATH"
3. Verify installation: `python --version`

#### macOS
```bash
# Using Homebrew
brew install python

# Or download from python.org
```

#### Linux
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3 python3-pip

# CentOS/RHEL
sudo yum install python3 python3-pip
```

### 2. Install Node.js

#### Windows/macOS
1. Download from [nodejs.org](https://nodejs.org/)
2. Run the installer
3. Verify installation: `node --version`

#### Linux
```bash
# Using NodeSource repository
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs
```

### 3. Install Ollama

#### Windows
1. Download from [ollama.ai](https://ollama.ai/download)
2. Run the installer
3. Start Ollama: `ollama serve`

#### macOS
```bash
# Using Homebrew
brew install ollama

# Or download from ollama.ai
```

#### Linux
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

### 4. Download AI Models

After installing Ollama, download recommended models:

```bash
# Start Ollama service
ollama serve

# Download models (in separate terminal)
ollama pull codellama        # Best for code generation
ollama pull deepseek-coder   # Good for code analysis
ollama pull wizardcoder      # Balanced performance
ollama pull starcoder        # Fast completion
```

### 5. Clone and Setup the Project

```bash
# Clone the repository
git clone <repository-url>
cd offline-ai-agent

# Run the setup script
python setup.py

# Or manual setup
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

## Quick Start

### Option 1: Using the Start Script
```bash
python start.py
```

### Option 2: Manual Start
```bash
# Terminal 1: Start backend
python main.py

# Terminal 2: Start frontend
cd frontend
npm start
```

### Option 3: Development Mode
```bash
# Backend with auto-reload
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Frontend with hot-reload
cd frontend && npm start
```

## Access the Application

1. Open your browser
2. Navigate to `http://localhost:3000`
3. The backend API is available at `http://localhost:8000`

## Troubleshooting

### Common Issues

#### Ollama Connection Failed
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama if not running
ollama serve

# Check available models
ollama list
```

#### Python Dependencies Issues
```bash
# Update pip
python -m pip install --upgrade pip

# Install with specific Python version
python3 -m pip install -r requirements.txt

# Use virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

#### Node.js Dependencies Issues
```bash
# Clear npm cache
npm cache clean --force

# Delete node_modules and reinstall
rm -rf node_modules package-lock.json
npm install

# Use specific Node version
nvm use 18
npm install
```

#### Port Already in Use
```bash
# Find process using port 8000
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Kill the process or change port in main.py
```

### Performance Optimization

#### For Better AI Performance
1. **Use GPU**: Install CUDA for NVIDIA GPUs
2. **Increase RAM**: More RAM allows larger models
3. **SSD Storage**: Faster model loading
4. **Model Selection**: Choose smaller models for faster responses

#### For Better Development Experience
1. **Use VS Code**: With Python and JavaScript extensions
2. **Enable Auto-save**: In editor settings
3. **Use Git**: For version control
4. **Hot Reload**: Both backend and frontend support it

## Configuration

### Environment Variables
Copy `env.example` to `.env` and modify:

```bash
cp env.example .env
```

Key settings:
- `OLLAMA_URL`: Ollama server URL
- `DEFAULT_MODEL`: Default AI model
- `API_PORT`: Backend port
- `MAX_FILE_SIZE`: Maximum file size to process

### Model Configuration
Edit `backend/services/ai_service.py` to customize:
- Model parameters (temperature, top_p)
- Prompt templates
- Response formatting

## Advanced Setup

### Docker Setup (Optional)
```bash
# Build and run with Docker
docker-compose up --build
```

### Production Deployment
1. Set `DEBUG=false` in environment
2. Use a production WSGI server (Gunicorn)
3. Configure reverse proxy (Nginx)
4. Set up SSL certificates
5. Configure logging and monitoring

### Custom Models
1. Train your own model with Ollama
2. Modify model selection in settings
3. Update prompt templates for your model

## Support

If you encounter issues:

1. Check the [Troubleshooting](#troubleshooting) section
2. Review the logs in the terminal
3. Check Ollama status: `ollama list`
4. Verify all services are running
5. Check system requirements

## Next Steps

After successful installation:

1. **Explore Features**: Try the chat, file explorer, and code editor
2. **Configure Models**: Download additional models as needed
3. **Customize Settings**: Adjust editor and AI preferences
4. **Import Projects**: Use the file explorer to work with your code
5. **Learn Commands**: Familiarize yourself with AI prompts

Enjoy your offline AI coding assistant! 🚀
