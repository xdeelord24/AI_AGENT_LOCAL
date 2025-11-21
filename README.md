# Offline AI Agent – Cursor-Style Local Coding Assistant

A local-first AI pair programmer built with FastAPI and React. The backend (`main.py`) runs entirely on your machine, talks to Ollama or HuggingFace models (`backend/services/ai_service.py`), and streams structured responses (plans, file operations, terminal output, etc.) directly into the IDE-style frontend (`frontend/src/components/IDELayout.js`). No network calls ever leave your box unless you explicitly opt in to HuggingFace or DuckDuckGo web search.

---

## Core Features

- **Chat-first workflow** – `/api/chat/send` orchestrates conversational prompts, auto-continues TODO plans, and records likes/dislikes to `data/feedback/feedback_log.jsonl`.
- **Full project control** – `/api/files/*` implements read/write/tree/search/move operations on any path rooted at the workspace.
- **Code intelligence** – `/api/code/*` offers analysis, refactors, completions, suggestions, and semantic search powered by the same model context used in chat.
- **Terminal streaming** – `/api/terminal/command/stream` mirrors a persistent PTY session so the assistant can run tests or CLI tools and show incremental output.
- **Session + status metadata** – chat sessions are persisted by `backend/api/chat_sessions.py`, and each response ships an `ai_plan`, `file_operations`, `agent_statuses`, and `activity_log` that the UI renders as live status cards.
- **Multiple model backends** – Ollama (default) with optional proxy (`ollama_proxy.py`), HuggingFace fallback, configurable generation parameters, and automatic connection caching.
- **MCP & web search** – Model Context Protocol tools (`backend/services/mcp_server.py`) and the enhanced DuckDuckGo cache (`backend/services/web_search_service.py`) can be toggled via environment flags.

```text
┌───────────────────────┐    ┌────────────────────────┐    ┌─────────────────────┐
│ React Frontend        │    │ FastAPI Backend        │    │ Local Models        │
│ • Chat / Editor / FS  │←──→│ • Chat, Files, Code    │←──→│ • Ollama (proxy)    │
│ • Terminal streaming  │    │ • Terminal, Sessions   │    │ • HuggingFace (opt) │
└───────────────────────┘    │ • MCP + Web Search     │    └─────────────────────┘
                             └────────────────────────┘
```
<img width="1837" height="1029" alt="image" src="https://github.com/user-attachments/assets/b71a66a3-35a4-4478-9d04-cb16c1d5ecdb" />
![IDE layout preview](https://github.com/user-attachments/assets/b71a66a3-35a4-4478-9d04-cb16c1d5ecdb)
See `INSTALL.md`, `MCP_INTEGRATION.md`, and `WEB_SEARCH_IMPROVEMENTS.md` for deeper dives.

---

## Requirements

- Python 3.8+ (the backend uses FastAPI, uvicorn, aiohttp, duckduckgo_search, etc.).
- Node.js 16+ (React app built with `react-scripts` 5.0.1, Tailwind, Monaco).
- Ollama running locally (`ollama serve`) with at least one code-capable model (`codellama`, `deepseek-coder`, etc.).
- 8 GB RAM minimum (16 GB+ recommended for larger models). GPU acceleration is optional but helpful.

Optional:

- `duckduckgo_search` for richer web search answers.
- `mcp` extras for Model Context Protocol support (see `MCP_INTEGRATION.md`).
- HuggingFace account/key if you want to set `LLM_PROVIDER=huggingface`.

---

## Quick Start

```bash
# 1. Configure environment
cp env.example .env         # edit if needed

# 2. Install backend deps (pip fallback uses requirements-flexible.txt)
python -m pip install -r requirements.txt

# 3. Install frontend deps
cd frontend && npm install && cd ..

# 4. Launch everything
python start.py             # starts backend + frontend, installs node deps if missing
```

Once both servers are up, open `http://localhost:3000`. The CRA dev server proxies API calls to `http://localhost:8000` (configurable via `frontend/package.json` or `REACT_APP_API_URL`).

Automated setup helpers:

```bash
python setup.py             # full install + model sanity checks
python install_deps.py      # Python requirements only
python install_frontend.py  # npm install frontend
```

---

## Running Services

- `python main.py` – runs the FastAPI app with uvicorn (reload enabled by default).
- `cd frontend && npm start` – launches the React dev server with Tailwind + Monaco editor.
- `python start.py` – convenience launcher (checks Ollama, spawns backend thread, runs npm start, opens browser).
- `python start_with_proxy.py` – same as above but also runs `ollama_proxy.py` (Flask proxy on `http://localhost:5000`) so browsers blocked by CORS can still reach Ollama.
- `python start_manual.py` – starts backend only and prints the commands for manually starting the frontend.
- `python start_backend.py` – backend only (handy for API tests or pairing with another UI).
- Windows users can run `fix_ollama_cors.bat` to set `OLLAMA_ORIGINS=*` before `ollama serve`, eliminating proxy requirements.

Use `simple_test.py`, `test_connections.py`, or `test_api_direct.py` if you need quick sanity checks against the backend endpoints.

---

## Environment & Configuration

All runtime settings are pulled from `.env` (see `env.example`) and standard environment variables:

- **API**: `API_HOST`, `API_PORT`, `LOG_LEVEL`, `DEBUG`, `RELOAD`.
- **Model routing** (`backend/services/ai_service.py`):
  - `LLM_PROVIDER` – `ollama` (default) or `huggingface`.
  - `OLLAMA_URL` – proxy endpoint (default `http://localhost:5000`); `OLLAMA_DIRECT_URL` – direct endpoint (`http://localhost:11434`).
  - `USE_PROXY`, `OLLAMA_REQUEST_TIMEOUT`, `OLLAMA_NUM_*`, `OLLAMA_KEEP_ALIVE`.
  - `DEFAULT_MODEL`, `HF_MODEL`, `HF_API_KEY`, `HF_BASE_URL`.
- **Generation controls**: `MAX_TOKENS`, `TEMPERATURE`, `TOP_P`, `OLLAMA_NUM_PREDICT`, etc.
- **File limits**: `MAX_FILE_SIZE`, `SUPPORTED_EXTENSIONS`.
- **Web search**: `ENABLE_WEB_SEARCH`, `WEB_SEARCH_CACHE_SIZE`, `WEB_SEARCH_CACHE_TTL`, `WEB_SEARCH_MAX_RESULTS`.
- **MCP**: `ENABLE_MCP`, `MCP_CACHE_TTL_SECONDS`, `AI_AGENT_CONFIG_DIR`.

The frontend can point to a remote backend by setting `REACT_APP_API_URL` before `npm start`.

---

## Backend API Surface

The FastAPI router (`backend/api/router.py`) mounts multiple sub-routers. The most commonly used endpoints are:

- `POST /api/chat/send` – main conversation endpoint. Handles plan auto-continue, metadata extraction, and ASK mode safeguards.
- `GET /api/chat/models`, `POST /api/chat/models/{name}/select`, `GET /api/chat/status` – manage model availability and runtime health.
- `GET/POST/PUT/DELETE /api/chat/sessions*` – persist chat transcripts, implemented in `backend/api/chat_sessions.py`.
- `GET /api/files/list|read|tree|info`, `POST /api/files/write|create-directory|copy|move`, `DELETE /api/files/delete` – workspace file manager, powered by `backend/services/file_service.py`.
- `POST /api/code/analyze|generate|search|refactor|completion`, `GET /api/code/languages|suggestions` – code operations orchestrated by `backend/services/code_analyzer.py`.
- `POST /api/terminal/session|command|command/stream|interrupt|complete` – PTY-backed shell commands via `backend/services/terminal_service.py`.
- `GET/PUT /api/settings`, `POST /api/settings/test-connection` – persist connection settings to `~/.offline_ai_agent/settings.json`.

All responses share a consistent metadata contract so the React client (`frontend/src/services/api.js`) can render plans, file diffs, statuses, and streamed terminal chunks in realtime.

---

## Frontend Notes

- Built with React 18 + React Router + Tailwind (`frontend/src/components/IDELayout.js` is the primary layout).
- Monaco editor (`@monaco-editor/react`) drives the multi-pane IDE experience with file tree, tabs, chat, and terminal.
- Markdown rendering uses `marked` with custom formatters (`frontend/src/utils/messageFormatter.js`) to support copy buttons, inline formatting, and sanitized metadata blocks.
- API requests share a single helper (`frontend/src/services/api.js`) that normalizes paths, handles streaming, and exposes high-level functions for every backend route.

Development commands:

```bash
cd frontend
npm start     # dev server @ http://localhost:3000 with proxy to :8000
npm run build # production bundle under frontend/build
npm test      # CRA test runner
```

---

## Troubleshooting

- **Ollama not detected** – run `ollama serve` manually, verify with `curl http://localhost:11434/api/tags`, or use `python test_connections.py`.
- **Browser blocked by CORS** – either run `python start_with_proxy.py` (uses Flask proxy on port 5000) or execute `fix_ollama_cors.bat` on Windows to set `OLLAMA_ORIGINS=*`.
- **npm missing** – `start.py` and `setup.py` try `npm`, `npm.cmd`, and `npm.exe`. Install Node 16+ from `https://nodejs.org` if detection fails.
- **Model not downloaded** – `setup.py` checks `ollama list` and can automatically `ollama pull codellama`. Otherwise run the `ollama pull` commands listed in `INSTALL.md`.
- **HuggingFace provider** – set `LLM_PROVIDER=huggingface`, fill `HF_API_KEY` and `HF_MODEL`, and optionally `HF_BASE_URL` for an OpenAI-compatible proxy.
- **MCP / web search** – enable by installing the optional dependencies referenced in `MCP_INTEGRATION.md` and `WEB_SEARCH_IMPROVEMENTS.md`.

---

## AI Response Format Reference

The assistant always emits GitHub-flavored Markdown plus optional embedded JSON metadata. The backend enforces this by injecting formatter instructions (`AIService.METADATA_FORMAT_LINES`) and scrubbing responses in ASK mode. Frontend rendering expectations:

- Headings limited to `##` / `###`.
- Bulleted lists for tasks or steps (use `-` followed by a space).
- Inline code for identifiers and paths.
- Fenced code blocks with language tags (copy button enabled in the UI).
- Optional metadata:
  - `ai_plan` – summary + tasks; used for progress pills and auto-continue prompts.
  - `file_operations` – edit/create/delete descriptors for the file patch previewer.
  - `agent_statuses` and `activity_log` – timeline cards showing what the agent is doing.

Example payload (trimmed for brevity):

```json
{
  "ai_plan": {
    "summary": "Add health check and describe tests",
    "tasks": [
      {"id": "1", "title": "Update backend routes", "status": "completed"},
      {"id": "2", "title": "Document new endpoint", "status": "pending"}
    ]
  },
  "file_operations": [
    {"type": "edit_file", "path": "backend/api/chat.py", "content": "..."}
  ]
}
```

---

## License

Released under the MIT License – see `LICENSE` or reuse/modify as needed.
