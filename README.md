# Offline AI Agent - Cursor Alternative

A fully offline AI coding assistant that provides intelligent code completion, analysis, and generation capabilities without requiring internet connectivity.

## Features

- 🤖 **Local AI Models**: Runs entirely offline using Ollama
- 💻 **Code Analysis**: Understands and analyzes your codebase
- ✨ **Code Generation**: Generates code based on natural language prompts
- 🔍 **Intelligent Search**: Semantic code search and navigation
- 📁 **File Operations**: Read, write, and manage files
- 🎯 **Context Awareness**: Maintains context across conversations
- 🔒 **Privacy First**: All data stays on your local machine

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   Backend       │    │   Ollama        │
│   (React)       │◄──►│   (FastAPI)     │◄──►│   (Local LLM)   │
│                 │    │                 │    │                 │
│ - Chat Interface│    │ - API Endpoints │    │ - Code Models   │
│ - File Explorer │    │ - File Manager  │    │ - Context Mgmt  │
│ - Code Editor   │    │ - AI Integration│    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Quick Start

### Automated Setup
```bash
# Option 1: Full setup script
python setup.py

# Option 2: If setup.py fails, try manual dependency installation
python install_deps.py

# Option 3: Install frontend dependencies separately
python install_frontend.py

# Start the application
python start.py

# Option 4: Start backend only (for testing)
python start_backend.py
```

### Manual Setup
1. **Install Ollama**:
   ```bash
   # Download from https://ollama.ai
   # Start Ollama service
   ollama serve
   
   # Install a code-capable model
   ollama pull codellama
   ollama pull deepseek-coder
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   cd frontend && npm install
   ```

3. **Start the Application**:
   ```bash
   # Start backend
   python main.py
   
   # Start frontend (in another terminal)
   cd frontend && npm start
   ```

4. **Access the Interface**:
   Open http://localhost:3000 in your browser

### Detailed Installation
See [INSTALL.md](INSTALL.md) for comprehensive installation instructions.

## Supported Models

- **CodeLlama**: Excellent for code generation and completion
- **DeepSeek-Coder**: Strong code understanding and analysis
- **WizardCoder**: Good balance of performance and speed
- **StarCoder**: Fast code completion

## Requirements

- Python 3.8+
- Node.js 16+
- 8GB+ RAM (for local models)
- Ollama installed and running

## License

MIT License - Feel free to use and modify as needed.
