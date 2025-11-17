## Offline AI Agent – Cursor-Style Local Coding Assistant

A fully offline AI coding assistant that provides intelligent code completion, analysis, and generation capabilities without requiring internet connectivity. It is designed to feel similar to Cursor, but runs entirely on your machine using local models via Ollama.

### Features

- **Local AI Models**: Runs entirely offline using Ollama.
- **Code Analysis**: Understands and analyzes your codebase.
- **Code Generation**: Generates code based on natural language prompts.
- **Semantic Search**: Uses project structure and context for smarter answers.
- **File Operations**: Read, write, and manage files via structured metadata.
- **Agent Mode & Planning**: Produces short TODO-style plans for complex tasks.
- **Context Awareness**: Maintains context across conversations and open files.
- **Privacy First**: All data stays on your local machine.

### Architecture

```text
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   Backend       │    │   Ollama        │
│   (React)       │◄──►│   (FastAPI)     │◄──►│   (Local LLM)   │
│                 │    │                 │    │                 │
│ - Chat UI       │    │ - API Endpoints │    │ - Code Models   │
│ - File Explorer │    │ - File Manager  │    │ - Context Mgmt  │
│ - Code Editor   │    │ - AI Integration│    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Example UI


<img width="1837" height="1029" alt="image" src="https://github.com/user-attachments/assets/b71a66a3-35a4-4478-9d04-cb16c1d5ecdb" />



## Quick Start

### Automated Setup

```bash
python setup.py

# If setup.py fails, install Python deps and frontend deps separately
python install_deps.py
python install_frontend.py

# Start the full application (backend + frontend)
python start.py

# Or start backend only (for testing)
python start_backend.py
```

### Manual Setup

1. **Install Ollama**

   ```bash
   # Download from https://ollama.ai
   # Start Ollama service
   ollama serve

   # Install a code-capable model
   ollama pull codellama
   ollama pull deepseek-coder
   ```

2. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   cd frontend && npm install
   ```

3. **Start the Application**

   ```bash
   # Start backend
   python main.py

   # Start frontend (in another terminal)
   cd frontend && npm start
   ```

4. **Access the Interface**

   Open `http://localhost:3000` in your browser.

### Configuration

- **Copy the example environment file**:

  ```bash
  cp env.example .env
  ```

- **Key settings** (see `INSTALL.md` for more):
  - `API_HOST` / `API_PORT`: where the FastAPI backend listens (defaults to `0.0.0.0:8000`).
  - `OLLAMA_URL`: Ollama server URL (for example `http://localhost:11434`).
  - `DEFAULT_MODEL`: default AI model name (for example `codellama`).
  - `MAX_FILE_SIZE`: maximum file size the agent will read/edit.
  - `LOG_LEVEL`, `DEBUG`, `RELOAD`, and basic model settings like `MAX_TOKENS`, `TEMPERATURE`, `TOP_P`.

### Start Scripts Overview

- **`start.py`**: Convenience script that:
  - Checks you are in the project root.
  - Verifies Ollama is reachable.
  - Starts the FastAPI backend (`main.py`) and React frontend (`frontend` via `npm start`), installing `node_modules` if needed.
  - Opens `http://localhost:3000` in your browser.
- **`start_with_proxy.py`**: Same as `start.py` but also:
  - Launches the Flask-based Ollama CORS proxy (`ollama_proxy.py`) on `http://localhost:5000`.
  - Is useful if your browser cannot connect directly to Ollama due to CORS/network limitations.
- **`start_manual.py`**: Starts only the backend and prints step-by-step instructions for running the frontend manually.
- **`start_backend.py`**: Minimal helper to run the backend only (handy for API testing or when integrating with another UI).

### Handling Ollama CORS

- **Option 1 – Use the proxy**:
  - Run: `python start_with_proxy.py` to start the proxy, backend, and frontend together.
  - The backend will talk to Ollama through the proxy (`ollama_proxy.py`) to avoid browser CORS issues.
- **Option 2 – Enable CORS directly in Ollama (Windows)**:
  - Run `fix_ollama_cors.bat`, which sets `OLLAMA_ORIGINS=*` and starts `ollama serve` so the frontend can call Ollama directly.

### Detailed Installation

See `INSTALL.md` for comprehensive installation instructions, including platform-specific steps, troubleshooting, and advanced deployment.

## AI Response Format & Markdown Styling

The backend AI service instructs the model to always answer using GitHub-flavored Markdown so the React frontend can render rich, readable output.

- **Headings**: Uses `##` and `###` headings (top-level `#` headings are avoided to keep the UI lighter).
- **Lists**: Uses bullet lists starting with `- ` for steps, notes, and explanations.
- **Emphasis**: Uses `**bold**` to highlight key points and pseudo-headings in lists, and `*italic*` sparingly.
- **Inline code**: Wraps file names, directories, functions, and identifiers in backticks (for example `backend/api/chat.py`).
- **Links**: Uses markdown links like `[Ollama](https://ollama.ai)` or wraps bare URLs in backticks.
- **Code blocks**: Uses fenced code blocks with language tags, for example:

```python
def example():
    print("Hello from the offline AI agent")
```

On the frontend, `frontend/src/utils/messageFormatter.js` uses `marked` plus custom renderers to:

- Render code blocks with a copy-to-clipboard button.
- Enhance lists, links, tables, and images.
- Handle inline markdown and math-like formatting via `formatInlineMarkdown`.

## File Operations & AI Plan Metadata

When the AI wants to change files, it returns a JSON metadata block that the backend parses and exposes to the UI. This metadata is embedded in the markdown response and then stripped from the user-visible text.

- **AI Plan (`ai_plan`)** – a short TODO-style plan for complex tasks:

```json
{
  "ai_plan": {
    "summary": "Short summary of your approach",
    "tasks": [
      {
        "id": "task-1",
        "title": "Describe the step",
        "status": "pending"
      }
    ]
  }
}
```

- **File Operations (`file_operations`)** – concrete file edits the agent wants to apply:

```json
{
  "file_operations": [
    {
      "type": "create_file",
      "path": "backend/services/new_service.py",
      "content": "# New service implementation ..."
    },
    {
      "type": "edit_file",
      "path": "frontend/src/App.js",
      "content": "/* full updated file content here */"
    }
  ]
}
```

The backend is lenient and also accepts:

- A single file operation object at the top level.
- A top-level list of file operations.
- JSON embedded in fenced ` ```json ` blocks or inline within the markdown.

## Agent Status & Context

The AI service (`backend/services/ai_service.py`) exposes rich status and context information:

- **Agent statuses**: `generate_agent_statuses` returns a list of step descriptions (for example “Thinking about…”, “Grepping workspace…”, “Drafting potential code changes…”), which the frontend can render as a live status timeline.
- **Context-aware prompts**: The AI prompt includes `active_file`, `open_files`, `mentioned_files`, and a file tree when available so responses are grounded in the current project.
- **Web search (optional)**: If `duckduckgo_search` is installed and `web_search_mode` is enabled in the context, the service augments responses with recent DuckDuckGo search results.

The main chat API is implemented in `backend/api/chat.py` and exposes endpoints for sending messages, listing models, selecting a model, and checking service status.

## Supported Models

- **CodeLlama**: Excellent for code generation and completion.
- **DeepSeek-Coder**: Strong code understanding and analysis.
- **WizardCoder**: Good balance of performance and speed.
- **StarCoder**: Fast code completion.

Any model available in Ollama that supports the `generate` API can be used. The default model is controlled by `DEFAULT_MODEL` and can be changed at runtime with the `/api/chat/models/{model_name}/select` endpoint.

## Requirements

- Python 3.8+
- Node.js 16+
- 8GB+ RAM (for local models)
- Ollama installed and running

Optionally, install `duckduckgo_search` to enable web search augmentation.

## License

MIT License – feel free to use and modify as needed.
