"""
AI Service for Offline AI Agent
Handles communication with local Ollama models
"""

import asyncio
import aiohttp
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, AsyncGenerator
import os
import re
import time
import logging

logger = logging.getLogger(__name__)

FILE_OP_METADATA_PATTERN = r'(?:file[\s_-]?operations|file[\s_-]?ops)'
AI_PLAN_METADATA_PATTERN = r'(?:ai[\s_-]?plan|ai[\s_-]?todo)'

try:
    from ddgs import DDGS  # type: ignore
except ImportError:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except ImportError:
        DDGS = None

try:
    from huggingface_hub import InferenceClient
except ImportError:
    InferenceClient = None

try:
    from .mcp_client import MCPClient
    from .mcp_server import MCPServerTools
    MCP_AVAILABLE = True
except ImportError:
    MCPClient = None
    MCPServerTools = None
    MCP_AVAILABLE = False


def truncate_text(text: Optional[str], limit: int = 220) -> str:
    if not text:
        return ''
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3].rstrip() + '...'


class AIService:
    """Service for interacting with AI models via Ollama, Hugging Face, or OpenRouter"""
    
    CONFIG_DIR_ENV_VAR = "AI_AGENT_CONFIG_DIR"
    DEFAULT_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".offline_ai_agent")
    SETTINGS_FILENAME = "settings.json"
    HF_DEFAULT_API_BASE = "https://api-inference.huggingface.co"
    
    METADATA_FORMAT_LINES = [
        "Metadata format (always include this JSON block when sharing an ai_plan or file operations):",
        "```json",
        "{",
        '  "ai_plan": {',
        '    "summary": "One-sentence summary of your approach",',
        '    "tasks": [',
        '      {',
        '        "id": "task-1",',
        '        "title": "Describe the step",',
        '        "status": "pending"',
        '      }',
        '    ]',
        '  },',
        '  "file_operations": [',
        '    {',
        '      "type": "create_file" | "edit_file" | "delete_file",',
        '      "path": "file/path.ext",',
        '      "content": "file content here"  // Required for create_file and edit_file, NOT needed for delete_file',
        '    }',
        '    // Example delete_file (no content field needed):',
        '    {',
        '      "type": "delete_file",',
        '      "path": "file/to/delete.ext"',
        '    }',
        '  ]',
        "}",
        "```",
        "",
    ]
    
    def __init__(self):
        # Load from environment variables or use defaults
        self.provider = (os.getenv("LLM_PROVIDER", "ollama") or "ollama").lower()
        if self.provider not in ("ollama", "huggingface", "openrouter"):
            self.provider = "ollama"
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:5000")  # Proxy server
        self.ollama_direct = os.getenv("OLLAMA_DIRECT_URL", "http://localhost:11434")  # Direct connection
        self.default_model = os.getenv("DEFAULT_MODEL", "codellama")
        self.current_model = self.default_model
        self.hf_api_key = os.getenv("HF_API_KEY", "")
        self.hf_model = os.getenv("HF_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
        self.hf_base_url = os.getenv("HF_BASE_URL", "").strip()
        # OpenRouter (OpenAI-compatible) provider settings
        # See https://openrouter.ai/docs for details
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        # Default to OpenRouter's "auto" router if not specified
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
        self.openrouter_base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        self.conversation_history = {}
        self.available_models = []
        self._config_dir = os.getenv(self.CONFIG_DIR_ENV_VAR) or self.DEFAULT_CONFIG_DIR
        self._settings_path = os.path.join(self._config_dir, self.SETTINGS_FILENAME)
        self._last_connection_check = 0.0
        self._last_connection_status = False
        try:
            self.connection_cache_seconds = int(os.getenv("OLLAMA_CONNECTION_CACHE_SECONDS", "25"))
        except ValueError:
            self.connection_cache_seconds = 25
        # Default to using proxy if OLLAMA_URL is explicitly set, otherwise try direct first
        use_proxy_env = os.getenv("USE_PROXY", "").lower()
        if use_proxy_env in ("true", "1", "yes"):
            self.use_proxy = True
        elif use_proxy_env in ("false", "0", "no"):
            self.use_proxy = False
        else:
            # Default: try proxy first if it's not the default direct URL
            self.use_proxy = self.ollama_url != "http://localhost:11434"

        try:
            self.request_timeout = int(os.getenv("OLLAMA_REQUEST_TIMEOUT", "120"))
        except ValueError:
            self.request_timeout = 120
        try:
            self.hf_request_timeout = int(os.getenv("HF_REQUEST_TIMEOUT", "120"))
        except ValueError:
            self.hf_request_timeout = 120
        try:
            self.hf_max_tokens = int(os.getenv("HF_MAX_TOKENS", "8192"))
        except ValueError:
            self.hf_max_tokens = 8192
        try:
            self.web_search_max_results = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
        except ValueError:
            self.web_search_max_results = 5

        self.hardware_threads = os.cpu_count() or 8
        self.base_generation_options = self._load_generation_options()
        self.large_model_thread_count = max(8, min(self.hardware_threads, 32))
        self._hf_client = None
        self._hf_client_cache_key: Optional[Tuple[str, str, str]] = None
        
        # MCP (Model Context Protocol) integration
        # The MCP server acts as a bridge between AI models and external systems,
        # providing unified connectivity, real-time access, and scalable integration.
        # See mcp_server.py and mcp_client.py for implementation details.
        self.mcp_tools = None
        self.mcp_client = None
        self._enable_mcp = os.getenv("ENABLE_MCP", "true").lower() in ("true", "1", "yes")
        
        # Enhanced web search service
        try:
            from .web_search_service import WebSearchService
            self._web_search_service = WebSearchService(
                cache_size=int(os.getenv("WEB_SEARCH_CACHE_SIZE", "100")),
                cache_ttl_seconds=int(os.getenv("WEB_SEARCH_CACHE_TTL", "3600"))
            )
        except ImportError:
            self._web_search_service = None
        
        self._load_persisted_settings()

        if self.provider == "huggingface":
            self.current_model = self.hf_model
        elif self.provider == "openrouter":
            self.current_model = self.openrouter_model
    
    def set_mcp_tools(self, mcp_tools: Optional[MCPServerTools]):
        """
        Set MCP tools for the AI service
        
        This method integrates the Model Context Protocol (MCP) server with the AI service,
        enabling the AI model to access external tools and data sources through a
        standardized protocol.
        
        The MCP integration provides:
        - Unified connectivity to external systems (files, web, code analysis)
        - Real-time data access instead of static training data
        - Scalable architecture that can be extended with new tools
        - Standardized tool discovery and execution
        
        When MCP is enabled, the AI model can:
        1. Discover available tools through get_tools_description()
        2. Make tool calls in standardized format (<tool_call name="..." args="..." />)
        3. Receive real-time results from external systems
        4. Access multiple data sources through one unified interface
        
        This removes the need for custom integrations for each external service,
        making the AI assistant more useful by providing access to live, accurate information.
        """
        self.mcp_tools = mcp_tools
        if mcp_tools and MCP_AVAILABLE:
            self.mcp_client = MCPClient(mcp_tools)
        else:
            self.mcp_client = None
    
    def is_mcp_enabled(self) -> bool:
        """Check if MCP is enabled and available"""
        return self._enable_mcp and self.mcp_client is not None and self.mcp_client.is_available()
    
    def _load_persisted_settings(self) -> None:
        """Load saved connectivity settings from disk if they exist."""
        try:
            if not os.path.exists(self._settings_path):
                return
            with open(self._settings_path, "r", encoding="utf-8") as settings_file:
                data = json.load(settings_file)
            self.ollama_url = data.get("ollama_url", self.ollama_url)
            self.ollama_direct = data.get("ollama_direct_url", self.ollama_direct)
            provider_value = (data.get("provider") or self.provider or "ollama").lower()
            if provider_value not in ("ollama", "huggingface", "openrouter"):
                provider_value = "ollama"
            self.provider = provider_value
            if "use_proxy" in data:
                self.use_proxy = bool(data["use_proxy"])
            if data.get("default_model"):
                self.default_model = data["default_model"]
            if data.get("current_model"):
                self.current_model = data["current_model"]
            elif data.get("default_model"):
                self.current_model = data["default_model"]
            if data.get("hf_model"):
                self.hf_model = data["hf_model"]
            if "hf_base_url" in data:
                self.hf_base_url = (data.get("hf_base_url") or "").strip()
            if "hf_api_key" in data:
                self.hf_api_key = data.get("hf_api_key") or ""
            # OpenRouter settings (all optional)
            if data.get("openrouter_model"):
                self.openrouter_model = data["openrouter_model"]
            if "openrouter_api_key" in data:
                self.openrouter_api_key = data.get("openrouter_api_key") or ""
            if "openrouter_base_url" in data:
                base = (data.get("openrouter_base_url") or "").strip()
                if base:
                    self.openrouter_base_url = base.rstrip("/")
        except Exception as error:
            print(f"⚠️  Failed to load saved settings: {error}")
    
    def save_settings(self) -> None:
        """Persist the current connectivity settings to disk."""
        settings_payload = {
            "ollama_url": self.ollama_url,
            "ollama_direct_url": self.ollama_direct,
            "use_proxy": self.use_proxy,
            "default_model": self.default_model,
            "current_model": self.current_model,
            "provider": self.provider,
            "hf_model": self.hf_model,
            "hf_base_url": self.hf_base_url,
            "hf_api_key": self.hf_api_key or "",
            "openrouter_model": self.openrouter_model,
            "openrouter_api_key": self.openrouter_api_key or "",
            "openrouter_base_url": self.openrouter_base_url,
        }
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._settings_path, "w", encoding="utf-8") as settings_file:
                json.dump(settings_payload, settings_file, indent=2)
        except Exception as error:
            print(f"⚠️  Failed to save settings: {error}")

    def reset_hf_client(self) -> None:
        """Drop cached Hugging Face inference client so new settings take effect."""
        self._hf_client = None
        self._hf_client_cache_key = None
        
    def _load_generation_options(self) -> Dict[str, Any]:
        def read_int(env_name: str, default: int) -> int:
            value = os.getenv(env_name)
            if value is None:
                return default
            try:
                return int(value)
            except ValueError:
                return default

        def read_float(env_name: str, default: float) -> float:
            value = os.getenv(env_name)
            if value is None:
                return default
            try:
                return float(value)
            except ValueError:
                return default

        default_threads = read_int(
            "OLLAMA_NUM_THREADS",
            max(4, min(self.hardware_threads - 1, 16))
        )

        options = {
            "temperature": read_float("OLLAMA_TEMPERATURE", 0.7),
            "top_p": read_float("OLLAMA_TOP_P", 0.9),
            # Use larger defaults so long answers are less likely to be cut off.
            # These can still be customized via OLLAMA_NUM_PREDICT / OLLAMA_NUM_CTX.
            "num_predict": read_int("OLLAMA_NUM_PREDICT", 8192),
            "num_ctx": read_int("OLLAMA_NUM_CTX", 8192),
            "num_batch": read_int("OLLAMA_NUM_BATCH", 256),
            "num_thread": default_threads,
        }

        keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "10m")
        options["_keep_alive"] = keep_alive
        return options

    def _build_generation_options_for_model(self) -> Tuple[Dict[str, Any], Optional[str]]:
        options = dict(self.base_generation_options)
        keep_alive = options.pop("_keep_alive", None)

        model_name = (self.current_model or "").lower()
        is_large = any(tag in model_name for tag in ("120b", "110b", "70b", ":70", ":120"))

        if is_large:
            options["num_ctx"] = max(options.get("num_ctx", 4096), 8192)
            options["num_batch"] = max(options.get("num_batch", 256), 512)
            options["num_thread"] = max(
                options.get("num_thread", 8),
                self.large_model_thread_count,
            )
            # For large models, ensure we have enough tokens for complete responses
            # Don't reduce num_predict - large models need more tokens, not fewer
            options["num_predict"] = max(options.get("num_predict", 4096), 4096)

        return options, keep_alive

    async def check_ollama_connection(self, force: bool = False) -> bool:
        """Check if Ollama is running and accessible"""
        now = time.time()
        if not force:
            if (
                self._last_connection_status
                and (now - self._last_connection_check) < self.connection_cache_seconds
            ):
                return True
        # Try proxy first
        if self.use_proxy:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.ollama_url}/api/tags") as response:
                        if response.status == 200:
                            data = await response.json()
                            self.available_models = [model["name"] for model in data.get("models", [])]
                            print("✅ Connected to Ollama via proxy")
                            self._last_connection_status = True
                            self._last_connection_check = now
                            return True
            except Exception as e:
                print(f"❌ Proxy connection failed: {e}")
                print("🔄 Trying direct connection...")
                self.use_proxy = False
        
        # Try direct connection
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_direct}/api/tags") as response:
                    if response.status == 200:
                        data = await response.json()
                        self.available_models = [model["name"] for model in data.get("models", [])]
                        print("✅ Connected to Ollama directly")
                        self._last_connection_status = True
                        self._last_connection_check = now
                        return True
        except Exception as e:
            print(f"❌ Direct connection failed: {e}")
        
        self._last_connection_status = False
        self._last_connection_check = now
        return False

    async def check_provider_connection(self, force: bool = False) -> bool:
        """Check connectivity for the currently selected provider."""
        if self.provider == "huggingface":
            if InferenceClient is None:
                return False
            return bool(self.hf_api_key and self.hf_model)
        if self.provider == "openrouter":
            # For OpenRouter we currently just validate configuration (key + model)
            # The /test-connection endpoint will surface any runtime API errors.
            return bool(self.openrouter_api_key and self.openrouter_model)
        return await self.check_ollama_connection(force=force)
    
    async def get_available_models(self) -> List[str]:
        """Get list of available models"""
        if self.provider == "huggingface":
            return [self.hf_model] if self.hf_model else []
        if self.provider == "openrouter":
            return [self.openrouter_model] if self.openrouter_model else []
        if not self.available_models:
            await self.check_ollama_connection(force=True)
        return self.available_models
    
    async def select_model(self, model_name: str) -> bool:
        """Select a specific model"""
        if self.provider == "huggingface":
            if not model_name:
                return False
            self.hf_model = model_name
            self.current_model = model_name
            self.reset_hf_client()
            self.save_settings()
            return True
        if self.provider == "openrouter":
            if not model_name:
                return False
            self.openrouter_model = model_name
            self.current_model = model_name
            self.save_settings()
            return True

        if model_name in self.available_models:
            self.current_model = model_name
            self.default_model = model_name
            self.save_settings()
            return True
        return False
    
    async def get_status(self) -> Dict[str, Any]:
        """Get current service status"""
        if self.provider == "huggingface":
            provider_connected = await self.check_provider_connection()
            available = [self.hf_model] if self.hf_model else []
            return {
                "provider": "huggingface",
                "provider_connected": provider_connected,
                "ollama_connected": provider_connected,
                "current_model": self.hf_model or self.current_model,
                "available_models": available,
                "conversation_count": len(self.conversation_history)
            }
        if self.provider == "openrouter":
            provider_connected = await self.check_provider_connection()
            available = [self.openrouter_model] if self.openrouter_model else []
            return {
                "provider": "openrouter",
                "provider_connected": provider_connected,
                # Keep key name for frontend compatibility; here it just mirrors provider_connected
                "ollama_connected": provider_connected,
                "current_model": self.openrouter_model or self.current_model,
                "available_models": available,
                "conversation_count": len(self.conversation_history)
            }

        is_connected = await self.check_ollama_connection(force=True)
        return {
            "provider": "ollama",
            "provider_connected": is_connected,
            "ollama_connected": is_connected,
            "current_model": self.current_model,
            "available_models": self.available_models,
            "conversation_count": len(self.conversation_history)
        }
    
    def _normalize_path(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        normalized = path.replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized or None
    
    def validate_ai_plan(self, ai_plan: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """Validate an AI plan structure and return (is_valid, errors)"""
        if not ai_plan:
            return True, []  # Empty plan is valid
        
        errors = []
        
        if not isinstance(ai_plan, dict):
            return False, ["AI plan must be a dictionary"]
        
        tasks = ai_plan.get("tasks", [])
        if not isinstance(tasks, list):
            errors.append("Tasks must be a list")
        else:
            # Validate each task
            task_ids = set()
            for idx, task in enumerate(tasks):
                if not isinstance(task, dict):
                    errors.append(f"Task {idx + 1} must be a dictionary")
                    continue
                
                task_id = task.get("id")
                if not task_id:
                    errors.append(f"Task {idx + 1} missing required 'id' field")
                elif task_id in task_ids:
                    errors.append(f"Duplicate task id: {task_id}")
                else:
                    task_ids.add(task_id)
                
                if not task.get("title"):
                    errors.append(f"Task {idx + 1} ({task_id or 'no-id'}) missing 'title' field")
                
                status = (task.get("status") or "pending").lower()
                valid_statuses = {"pending", "in_progress", "completed", "complete", "done", "blocked"}
                if status not in valid_statuses:
                    errors.append(f"Task {idx + 1} ({task_id or 'no-id'}) has invalid status: {status}")
        
        # Check for circular dependencies if dependencies are specified
        if tasks:
            task_deps = {}
            for task in tasks:
                task_id = task.get("id")
                if task_id:
                    deps = task.get("depends_on", [])
                    if isinstance(deps, list):
                        task_deps[task_id] = deps
            
            # Check for circular dependencies
            def has_cycle(task_id: str, visited: set, rec_stack: set) -> bool:
                visited.add(task_id)
                rec_stack.add(task_id)
                
                for dep in task_deps.get(task_id, []):
                    if dep not in visited:
                        if has_cycle(dep, visited, rec_stack):
                            return True
                    elif dep in rec_stack:
                        return True
                
                rec_stack.remove(task_id)
                return False
            
            visited = set()
            for task_id in task_deps:
                if task_id not in visited:
                    if has_cycle(task_id, visited, set()):
                        errors.append(f"Circular dependency detected involving task: {task_id}")
                        break
        
        return len(errors) == 0, errors
    
    def generate_agent_statuses(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        file_operations: Optional[List[Dict[str, Any]]] = None,
        ai_plan: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Create contextual agent status steps for the frontend"""
        context = context or {}
        statuses: List[Dict[str, Any]] = []
        delay = 0

        # Validate plan if present
        if ai_plan:
            is_valid, validation_errors = self.validate_ai_plan(ai_plan)
            if not is_valid:
                logger.warning(f"AI plan validation failed: {validation_errors}")

        def add_status(key: str, label: str, increment: int = 800):
            nonlocal delay
            statuses.append({
                "key": key,
                "label": label,
                "delay_ms": delay
            })
            delay += max(increment, 200)

        message_excerpt = (message or "").strip().splitlines()[0][:80]
        if message_excerpt:
            add_status("thinking", f"Thinking about: {message_excerpt}…", 700)
        else:
            add_status("thinking", "Thinking about the request…", 700)

        add_status("analysis", "Analyzing context and recent history", 700)

        active_file = None
        try:
            active_file_raw = context.get("active_file")
            if active_file_raw:
                active_file = self._normalize_path(str(active_file_raw))
        except Exception as e:
            logger.warning(f"Error processing active_file in generate_agent_statuses: {e}")
        
        if active_file:
            add_status(f"grep-active:{active_file}", f"Grepping {active_file} for relevant code", 750)

        mentioned_files = []
        try:
            mentioned_files_raw = context.get("mentioned_files")
            if isinstance(mentioned_files_raw, list):
                mentioned_files = mentioned_files_raw[:4]
            elif mentioned_files_raw:
                # If it's not a list, try to convert or skip
                logger.warning(f"mentioned_files is not a list: {type(mentioned_files_raw)}")
        except Exception as e:
            logger.warning(f"Error processing mentioned_files in generate_agent_statuses: {e}")
        
        added_paths = set()
        if active_file:
            added_paths.add(active_file)

        for mention in mentioned_files:
            try:
                if isinstance(mention, dict):
                    path = mention.get("path")
                elif isinstance(mention, str):
                    path = mention
                else:
                    path = None
                
                if path:
                    normalized = self._normalize_path(str(path))
                    if normalized and normalized not in added_paths:
                        add_status(f"grep:{normalized}", f"Grepping {normalized} for matches", 600)
                        added_paths.add(normalized)
            except Exception as e:
                logger.warning(f"Error processing mention in generate_agent_statuses: {e}")
                continue

        if not mentioned_files and not active_file:
            add_status("grep_workspace", "Grepping workspace for references", 650)

        add_status("context", "Collecting workspace structure, open files, and directory info", 700)

        mode_value = (context.get("mode") or context.get("chat_mode") or "").lower()
        web_mode = (context.get("web_search_mode") or "").lower()
        agent_like = mode_value in ("agent", "plan") or context.get("composer_mode")

        if web_mode in ("browser_tab", "google_chrome"):
            add_status("web_lookup", "Reviewing latest web search findings", 650)

        if agent_like:
            add_status("subtasks", "Breaking work into actionable subtasks", 650)
            add_status("planning", "Sequencing tasks for execution", 750)
        else:
            add_status("planning", "Preparing direct response", 700)

        if file_operations:
            try:
                if not isinstance(file_operations, list):
                    logger.warning(f"file_operations is not a list: {type(file_operations)}")
                    file_operations = []
                
                for op in file_operations[:6]:
                    try:
                        if not isinstance(op, dict):
                            continue
                        op_type = (op.get("type") or "").lower()
                        path_raw = op.get("path")
                        path = self._normalize_path(str(path_raw) if path_raw else None) or "workspace"
                        if op_type == "delete_file":
                            label = f"Preparing removal for {path}"
                        elif op_type == "create_file":
                            label = f"Drafting new file {path}"
                        else:
                            label = f"Updating {path}"
                        add_status(f"op:{path}", label, 600)
                    except Exception as e:
                        logger.warning(f"Error processing file operation in generate_agent_statuses: {e}")
                        continue
            except Exception as e:
                logger.warning(f"Error processing file_operations in generate_agent_statuses: {e}")
        else:
            add_status("drafting", "Drafting potential code changes", 750)

        if agent_like:
            add_status("progress", "Monitoring TODO progress and updating task statuses", 600)

        add_status("verification", "Verifying updates and running quick checks", 600)
        add_status("reporting", "Reporting outcomes and next steps", 500)

        return statuses
    
    def _parse_response_metadata(self, response: str, context: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
        """Extract metadata such as file operations or AI plans from the response"""
        cleaned_response = response
        metadata: Dict[str, Any] = {
            "file_operations": [],
            "ai_plan": None
        }
        
        # Remove tool calls from response (they should be executed, not shown to user)
        if self.mcp_client and self.is_mcp_enabled():
            cleaned_response = self.mcp_client.remove_tool_calls_from_text(cleaned_response)
        
        # Check if in ASK mode - we'll still extract plans but not file operations
        is_ask_mode = context and self._is_ask_context(context)

        def to_snake_case(value: str) -> str:
            if not isinstance(value, str):
                return ""
            converted = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', value)
            converted = re.sub(r'[\s\-]+', '_', converted)
            return converted.strip('_').lower()

        def normalize_metadata_key(key: Any) -> str:
            if not isinstance(key, str):
                return ""
            normalized = to_snake_case(key)
            alias_map = {
                "aiplan": "ai_plan",
                "ai_todo": "ai_plan",
                "plan": "ai_plan",
                "todo_plan": "ai_plan",
                "fileoperations": "file_operations",
                "fileops": "file_operations",
                "file_ops": "file_operations",
                "fileedits": "file_operations",
                "file_edit_requests": "file_operations",
            }
            return alias_map.get(normalized, normalized)

        def is_plan_object(obj: Any) -> bool:
            if not isinstance(obj, dict):
                return False
            summary = obj.get("summary") or obj.get("description") or obj.get("thoughts")
            tasks = obj.get("tasks")
            # Accept plans with either summary OR tasks (or both)
            # This makes plan detection more lenient
            has_summary = isinstance(summary, str) and summary.strip()
            has_tasks = isinstance(tasks, list) and len(tasks) > 0
            return has_summary or has_tasks

        def strip_code_fences(text: str) -> str:
            if not isinstance(text, str):
                return text
            stripped = text.strip()
            fence_match = re.match(r'^```[a-zA-Z0-9_+-]*\n([\s\S]*?)\n```$', stripped)
            if fence_match:
                return fence_match.group(1).strip("\n")
            return stripped

        def normalize_operation_type(op_type: Optional[str]) -> Optional[str]:
            if not op_type:
                return None
            normalized = re.sub(r'[\s\-]+', '_', op_type.strip().lower())
            normalized = normalized.replace("__", "_")
            alias_map = {
                "createfile": "create_file",
                "newfile": "create_file",
                "addfile": "create_file",
                "writefile": "edit_file",
                "overwritefile": "edit_file",
                "updatefile": "edit_file",
                "modifyfile": "edit_file",
                "replacefile": "edit_file",
                "editfile": "edit_file",
                "appendfile": "edit_file",
                "deletefile": "delete_file",
                "removefile": "delete_file",
                "rmfile": "delete_file",
            }
            normalized_no_underscore = normalized.replace("_", "")
            if normalized in alias_map:
                return alias_map[normalized]
            if normalized_no_underscore in alias_map:
                return alias_map[normalized_no_underscore]
            if normalized in ("create", "create_file"):
                return "create_file"
            if normalized in ("edit", "update", "modify", "edit_file"):
                return "edit_file"
            if normalized in ("delete", "remove", "delete_file"):
                return "delete_file"
            return normalized if normalized in ("create_file", "edit_file", "delete_file") else None

        def is_document_file(path: str) -> bool:
            """Check if a file path is a binary document file that shouldn't be opened in code editor"""
            if not path:
                return False
            path_lower = str(path).lower()
            # Binary document file extensions that should not be opened in code editor
            document_extensions = {'.pptx', '.docx', '.xlsx', '.pdf', '.odt', '.ods', '.odp', '.ppt', '.doc', '.xls'}
            return any(path_lower.endswith(ext) for ext in document_extensions)
        
        def normalize_file_operation(op: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(op, dict):
                return None
            op_type = normalize_operation_type(
                op.get("type") or op.get("action") or op.get("op") or op.get("operation")
            )
            path = op.get("path") or op.get("file") or op.get("target")
            if not op_type or not path:
                return None
            path_str = str(path).strip()
            normalized_op: Dict[str, Any] = {
                "type": op_type,
                "path": path_str
            }
            
            # Mark document files to prevent opening in code editor
            if is_document_file(path_str):
                normalized_op["is_document"] = True
                normalized_op["open_in_editor"] = False  # Don't open binary files in editor
                # For document files, don't include content in file_operations
                # They are created via tools, not text editing
                if "content" in op:
                    # Remove content for document files - they're binary
                    pass
            
            if "content" in op and not normalized_op.get("is_document"):
                normalized_op["content"] = strip_code_fences(str(op["content"]))
            if "beforeContent" in op:
                normalized_op["beforeContent"] = strip_code_fences(str(op["beforeContent"]))
            if "afterContent" in op:
                normalized_op["afterContent"] = strip_code_fences(str(op["afterContent"]))
            if "before" in op:
                normalized_op["before"] = strip_code_fences(str(op["before"]))
            if "after" in op:
                normalized_op["after"] = strip_code_fences(str(op["after"]))
            for key in ("diff", "metadata", "encoding", "language", "overwrite", "is_document", "open_in_editor"):
                if key in op:
                    normalized_op[key] = op[key]
            return normalized_op

        def normalize_file_operations(obj: Any) -> List[Dict[str, Any]]:
            normalized_ops: List[Dict[str, Any]] = []
            if isinstance(obj, list):
                for item in obj:
                    normalized = normalize_file_operation(item)
                    if normalized:
                        normalized_ops.append(normalized)
            elif isinstance(obj, dict):
                normalized = normalize_file_operation(obj)
                if normalized:
                    normalized_ops.append(normalized)
            return normalized_ops

        def extract_from_json(json_str: str) -> bool:
            """
            Try to extract metadata from a JSON string.
            Supports both the canonical shape:
              {"file_operations": [...], "ai_plan": {...}}
            and convenience shapes like:
              {"type": "create_file", "path": "...", "content": "..."}
              [{"type": "...", "path": "...", "content": "..."}]
            """
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # Fallback: be more lenient and try to parse as a Python literal.
                # This allows the model to use triple-quoted strings, trailing commas, etc.
                try:
                    import ast
                    data = ast.literal_eval(json_str)
                except Exception:
                    return False

            found = False

            # Helper: detect a single file-operation dict
            def is_file_op(obj: Any) -> bool:
                if not isinstance(obj, dict):
                    return False
                op_type = (
                    obj.get("type")
                    or obj.get("action")
                    or obj.get("op")
                    or obj.get("operation")
                    or ""
                ).lower()
                path = obj.get("path")
                return bool(op_type and path)

            # Canonical metadata shape
            if isinstance(data, dict):
                file_ops_value = None
                ai_plan_value = None
                for key, value in list(data.items()):
                    normalized_key = normalize_metadata_key(key)
                    if normalized_key == "file_operations":
                        file_ops_value = value
                    elif normalized_key == "ai_plan":
                        ai_plan_value = value

                # In ASK mode, skip file operations but still extract plans
                if not is_ask_mode:
                    normalized_ops = normalize_file_operations(file_ops_value)
                    if normalized_ops:
                        metadata["file_operations"].extend(normalized_ops)
                        found = True

                # Always extract plans, even in ASK mode
                if isinstance(ai_plan_value, dict) and is_plan_object(ai_plan_value):
                    metadata["ai_plan"] = ai_plan_value
                    found = True

                # Convenience: single file operation object at top level (skip in ASK mode)
                if not is_ask_mode and not found and is_file_op(data):
                    normalized_op = normalize_file_operation(data)
                    if normalized_op:
                        metadata["file_operations"].append(normalized_op)
                        found = True

                # Convenience: plan object at top level without ai_plan key (always extract)
                if not found and is_plan_object(data):
                    metadata["ai_plan"] = data
                    found = True

            # Convenience: top-level list of file-operations (skip in ASK mode)
            if not is_ask_mode and isinstance(data, list):
                ops = [op for op in data if is_file_op(op)]
                if ops:
                    normalized_ops = normalize_file_operations(ops)
                    if normalized_ops:
                        metadata["file_operations"].extend(normalized_ops)
                    found = True

            return found

        # First, try to interpret the entire response as JSON.
        # This covers the common case where the model returns *only* a metadata
        # object (with ai_plan / file_operations) and no surrounding prose.
        whole = response.strip()
        if whole:
            if extract_from_json(whole):
                # The whole response was metadata; no user-visible text remains.
                logger.debug(f"[DEBUG] Extracted metadata from whole response - has_plan: {bool(metadata.get('ai_plan'))}, has_file_ops: {bool(metadata.get('file_operations'))}")
                return "", metadata

        # Markdown ```json blocks (be flexible about the fence language and contents)
        # We capture the smallest possible fenced block so we don't accidentally
        # consume surrounding narrative text.
        json_block_pattern = r'```(?:json|JSON)?\s*([\s\S]*?)```'
        json_blocks_found = 0
        for match in re.finditer(json_block_pattern, response, re.DOTALL):
            json_blocks_found += 1
            block = match.group(0)
            json_str = match.group(1).strip()
            if extract_from_json(json_str):
                logger.debug(f"[DEBUG] Extracted metadata from JSON block #{json_blocks_found} - has_plan: {bool(metadata.get('ai_plan'))}, has_file_ops: {bool(metadata.get('file_operations'))}")
                cleaned_response = cleaned_response.replace(block, "").strip()
        if json_blocks_found > 0:
            logger.debug(f"[DEBUG] Found {json_blocks_found} JSON code block(s) in response")

        # Inline fallback for responses that embed JSON without fences.
        # Try to find and extract JSON objects more robustly, handling nested structures.
        # We need to ensure we capture ALL file operations, even in large JSON objects.
        
        # Strategy: Find all potential JSON objects by looking for opening braces
        # and matching them with closing braces, then check if they contain our metadata keys
        def find_balanced_json_objects(text: str) -> List[Tuple[int, int, str]]:
            """Find all balanced JSON objects in text, handling nested braces."""
            results = []
            i = 0
            while i < len(text):
                # Find next opening brace
                brace_start = text.find('{', i)
                if brace_start == -1:
                    break
                
                # Find matching closing brace
                brace_count = 0
                brace_end = -1
                in_string = False
                escape_next = False
                
                for j in range(brace_start, len(text)):
                    if escape_next:
                        escape_next = False
                        continue
                    char = text[j]
                    if char == '\\':
                        escape_next = True
                        continue
                    if char == '"' and not escape_next:
                        in_string = not in_string
                    if not in_string:
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                brace_end = j + 1
                                break
                
                if brace_end > 0:
                    json_candidate = text[brace_start:brace_end]
                    # Check if this JSON contains our metadata keys
                    if (re.search(rf'"{FILE_OP_METADATA_PATTERN}"', json_candidate, re.IGNORECASE) or
                        re.search(rf'"{AI_PLAN_METADATA_PATTERN}"', json_candidate, re.IGNORECASE) or
                        re.search(r'"summary"[\s\S]*"tasks"', json_candidate, re.IGNORECASE)):
                        results.append((brace_start, brace_end, json_candidate))
                    i = brace_end
                else:
                    i = brace_start + 1
            return results
        
        # Find all JSON objects that might contain metadata
        json_objects = find_balanced_json_objects(cleaned_response)
        
        # Extract from found objects (process from end to start to preserve indices)
        json_objects.sort(key=lambda x: x[0], reverse=True)
        for start, end, json_candidate in json_objects:
            if extract_from_json(json_candidate):
                cleaned_response = cleaned_response[:start] + cleaned_response[end:]
        
        # Fallback: Try simpler patterns for single file operation objects
        # (in case they weren't caught by the balanced matching)
        inline_patterns = [
            r'\{[\s\S]*?"summary"\s*:\s*".*?"[\s\S]*?"tasks"\s*:\s*\[[\s\S]*?\]\s*\}',
            # Convenience: any JSON object that looks like a single file operation
            r'\{[\s\S]*?"type"\s*:\s*"[a-zA-Z_]+?"[\s\S]*?"path"\s*:\s*"[^\"]+"[\s\S]*?\}',
        ]
        for pattern in inline_patterns:
            for match in re.finditer(pattern, cleaned_response, re.DOTALL):
                json_candidate = match.group(0).strip()
                if extract_from_json(json_candidate):
                    cleaned_response = cleaned_response.replace(json_candidate, "", 1).strip()

        cleaned_response = re.sub(
            rf'(?mi)^\s*(?:{AI_PLAN_METADATA_PATTERN}|{FILE_OP_METADATA_PATTERN})\s*:?\s*$',
            '',
            cleaned_response
        )
        cleaned_response = re.sub(r'\n{3,}', '\n\n', cleaned_response).strip()

        # Final summary of extracted metadata
        has_plan = bool(metadata.get("ai_plan"))
        has_file_ops = bool(metadata.get("file_operations"))
        if has_plan or has_file_ops:
            logger.info(f"[DEBUG] Metadata extraction complete - has_plan: {has_plan}, has_file_ops: {has_file_ops}")
            if has_plan:
                plan = metadata.get("ai_plan")
                logger.info(f"[DEBUG] Plan details - summary: {plan.get('summary', 'N/A')[:100]}, tasks: {len(plan.get('tasks', []))}")

        return cleaned_response, metadata

    def _filter_thinking_content(self, response: str, context: Dict[str, Any]) -> str:
        """Remove thinking, planning, and reporting content from the response, keeping only the actual answer."""
        if not response or not response.strip():
            return response
        
        is_ask_mode = self._is_ask_context(context)
        is_agent_mode = self._is_agent_context(context)
        
        # Remove the "(Generated concrete file operations automatically.)" message
        response = re.sub(r'\(Generated concrete file operations automatically\.\)', '', response, flags=re.IGNORECASE)
        
        # Remove JSON code blocks that contain metadata (ai_plan, file_operations)
        json_block_pattern = rf'```(?:json|text|python)?\s*\{{[\s\S]*?"(?:{AI_PLAN_METADATA_PATTERN}|{FILE_OP_METADATA_PATTERN})"[\s\S]*?\}}[\s\S]*?```'
        response = re.sub(json_block_pattern, '', response, flags=re.IGNORECASE | re.DOTALL)
        
        # Remove standalone JSON objects with metadata
        json_metadata_pattern = rf'\{{[\s\S]*?"(?:{AI_PLAN_METADATA_PATTERN}|{FILE_OP_METADATA_PATTERN})"[\s\S]*?\}}'
        response = re.sub(json_metadata_pattern, '', response, flags=re.IGNORECASE | re.DOTALL)
        
        lines = response.split('\n')
        filtered_lines = []
        in_thinking_section = False
        in_planning_section = False
        in_reporting_section = False
        in_file_operations_section = False
        seen_sections = set()  # Track seen section headers to remove duplicates
        
        # Patterns that indicate thinking/planning/reporting content
        thinking_patterns = [
            r'^(let me|i\'ll|i will|i need to|i should|i must|i\'m going to|i am going to)',
            r'^(first|second|third|next|then|after that|finally|now|so)',
            r'^(thinking|analyzing|considering|evaluating|reviewing)',
            r'^(to understand|to analyze|to determine|to figure out|to identify)',
            r'^(let me think|let me analyze|let me check|let me review)',
            r'^(i think|i believe|i assume|i suppose|i guess)',
            r'^(based on|according to|from what i can see)',
            r'^since the search results',
        ]
        
        planning_patterns = [
            r'^(here\'s my plan|here is my plan|my plan is|the plan is)',
            r'^(i\'ll break this down|i will break this down|breaking this down)',
            r'^(step \d+|task \d+|phase \d+)',
            r'^(first step|next step|final step|last step)',
            r'^(plan:|planning:|strategy:)',
            r'^(i\'ll start by|i will start by|starting with)',
            r'^(let me create a plan|let me outline|let me structure)',
            r'^(update aiplan|update ai_plan|update ai plan)',
            r'^(gather more information|gathering information|to gather)',
            r'^(after (inspecting|determining|completing)|i will update)',
            r'^(inspect|inspecting)',
            r'^(todo list|todo:|task-1:|task-2:|task-3:)',
            r'^(we will use|we will|we\'ll)',
        ]
        
        reporting_patterns = [
            r'^(summary:|summary of|in summary|to summarize)',
            r'^(report:|reporting:|final report|completion report|task report|verification report)',
            r'^(i\'ve completed|i have completed|i completed|completed:)',
            r'^(done:|finished:|completed tasks:)',
            r'^(results:|outcomes:|conclusion:)',
            r'^(all tasks are|all steps are|everything is)',
            r'^(verification|i verified|verifying)',
            r'^(task status|remaining risks|task report)',
        ]
        
        # Section headers that indicate thinking/planning/reporting
        thinking_headers = [
            '# thinking',
            '# analysis',
            '# reasoning',
            '# understanding',
            '## thinking',
            '## analysis',
            '## reasoning',
            '## understanding',
            '### thinking',
            '### analysis',
            '### reasoning',
            '### understanding',
        ]
        
        planning_headers = [
            '# plan',
            '# planning',
            '# strategy',
            '# approach',
            '# steps',
            '# tasks',
            '# todo list',
            '# todo',
            '# ai plan',
            '## plan',
            '## planning',
            '## strategy',
            '## approach',
            '## steps',
            '## tasks',
            '## todo list',
            '## todo',
            '## ai plan',
            '### plan',
            '### planning',
            '### strategy',
            '### approach',
            '### steps',
            '### tasks',
            '### todo list',
            '### todo',
            '### ai plan',
        ]
        
        reporting_headers = [
            '# report',
            '# summary',
            '# results',
            '# conclusion',
            '# completion',
            '# verification',
            '# verification report',
            '# task report',
            '# task status',
            '# task status update',
            '# remaining risks',
            '# better answer',
            '## report',
            '## summary',
            '## results',
            '## conclusion',
            '## completion',
            '## verification',
            '## verification report',
            '## task report',
            '## task status',
            '## task status update',
            '## remaining risks',
            '### report',
            '### summary',
            '### results',
            '### conclusion',
            '### completion',
            '### verification',
            '### verification report',
            '### task report',
            '### task status',
            '### task status update',
            '### remaining risks',
        ]
        
        file_operations_headers = [
            '# file operations',
            '# file operation',
            '## file operations',
            '## file operation',
            '### file operations',
            '### file operation',
            '## file operations:',
            '### file operations:',
        ]
        
        metadata_label_names = {
            'aiplan',
            'ai plan',
            'ai plan summary',
            'web search',
            'web search results',
            'web.search',
            'web_search',
            'process steps',
            'process',
            'process status',
            'activity log',
            'agent statuses',
            'agent status',
            'better answer',
        }
        web_search_label_names = {
            'web search',
            'web search results',
            'web.search',
            'web_search',
        }
        
        i = 0
        while i < len(lines):
            line = lines[i]
            line_lower = line.lower().strip()
            normalized_label = re.sub(r'\s+', ' ', line_lower.rstrip(':').replace('_', ' ').replace('.', ' ')).strip()
            
            if normalized_label in metadata_label_names:
                if normalized_label in web_search_label_names:
                    i += 1
                    while i < len(lines):
                        next_line = lines[i].strip()
                        if not next_line:
                            i += 1
                            continue
                        if next_line.startswith('```'):
                            i += 1
                            while i < len(lines) and not lines[i].strip().startswith('```'):
                                i += 1
                            if i < len(lines):
                                i += 1
                            continue
                        if next_line.startswith('<tool_call') or next_line.startswith('</tool_call'):
                            i += 1
                            continue
                        break
                    continue
                i += 1
                continue
            
            if line_lower.startswith('<tool_call') or line_lower.startswith('</tool_call'):
                i += 1
                continue
            
            # Check for duplicate section headers (remove duplicates)
            if line_lower.startswith('#'):
                section_key = normalized_label or line_lower[:50]  # Use normalized heading
                # Also check for common repetitive headers
                if (section_key in seen_sections or 
                    (line_lower.startswith('## trending') and any('trending' in s for s in seen_sections))):
                    # Skip duplicate section
                    i += 1
                    # Skip until next section or end
                    while i < len(lines) and not lines[i].strip().startswith('#'):
                        i += 1
                    continue
                seen_sections.add(section_key)
            
            # Check for "File Operations" sections (always remove in ASK mode, remove in other modes if empty)
            if any(line_lower.startswith(header) for header in file_operations_headers):
                in_file_operations_section = True
                in_thinking_section = False
                in_planning_section = False
                in_reporting_section = False
                i += 1
                continue
            
            # Check for section headers
            if any(line_lower.startswith(header) for header in thinking_headers):
                in_thinking_section = True
                in_planning_section = False
                in_reporting_section = False
                i += 1
                continue
            
            if any(line_lower.startswith(header) for header in planning_headers):
                in_thinking_section = False
                in_planning_section = True
                in_reporting_section = False
                i += 1
                continue
            
            if any(line_lower.startswith(header) for header in reporting_headers):
                in_thinking_section = False
                in_planning_section = False
                in_reporting_section = True
                i += 1
                continue
            
            # Check if we're exiting a section (new heading or empty line followed by content)
            if line.strip().startswith('#'):
                in_thinking_section = False
                in_planning_section = False
                in_reporting_section = False
                in_file_operations_section = False
            
            # Skip file operations sections (always in ASK mode, or if empty in other modes)
            if in_file_operations_section:
                if is_ask_mode:
                    i += 1
                    continue
                # In other modes, check if this line is part of file operations content
                if line_lower and ('file' in line_lower and 'operation' in line_lower):
                    i += 1
                    continue
                # Exit file operations section if we hit a new section or meaningful content
                if line.strip().startswith('#'):
                    in_file_operations_section = False
                elif line.strip() and not line_lower.startswith(('```', '- ', '* ', '1. ', '2. ')):
                    # If we hit non-file-ops content, exit the section
                    in_file_operations_section = False
            
            # Skip thinking sections entirely
            if in_thinking_section:
                i += 1
                continue
            
            # Skip planning sections in ASK mode, but keep them in AGENT mode if they're brief
            if in_planning_section:
                if is_ask_mode:
                    i += 1
                    continue
                # In agent mode, only skip if it's clearly just planning prose
                if any(re.match(pattern, line_lower) for pattern in planning_patterns):
                    i += 1
                    continue
            
            # Skip reporting sections that are just summaries (unless it's the only content)
            if in_reporting_section:
                if any(re.match(pattern, line_lower) for pattern in reporting_patterns):
                    # Check if there's substantial content before this
                    if len(filtered_lines) > 5:
                        i += 1
                        continue
            
            # Check for thinking patterns in regular lines (only at start of line)
            # Be more conservative - only skip if it's clearly thinking prose
            if line_lower and not line_lower.startswith(('```', '##', '###', '- ', '* ', '1. ', '2. ')):
                if any(re.match(pattern, line_lower) for pattern in thinking_patterns):
                    # Skip this line and potentially following lines if they continue the thought
                    i += 1
                    # Skip continuation lines (indented or starting with "  ")
                    while i < len(lines) and (lines[i].startswith('  ') or lines[i].strip() == ''):
                        i += 1
                    continue
            
            # Check for planning patterns (skip in ASK mode)
            if is_ask_mode and any(re.match(pattern, line_lower) for pattern in planning_patterns):
                i += 1
                continue
            
            # Check for "Continuing the TODO Plan" or similar continuation statements
            if re.search(r'continuing.*todo.*plan', line_lower) or re.search(r'continuing.*plan', line_lower):
                i += 1
                # Skip until we find actual content
                while i < len(lines):
                    next_line = lines[i].strip()
                    if next_line and not (next_line.lower().startswith(('task', 'step', 'completed', 'remaining', 'file'))):
                        break
                    i += 1
                continue
            
            # Check for TODO LIST or AI PLAN sections (remove them)
            # This catches various formats: "TODO LIST", "AI PLAN", "AI PLAN:", etc.
            if (line_lower.startswith('todo list') or 
                line_lower.startswith('ai plan') or 
                'ai plan' in line_lower or
                line_lower.startswith('fileoperations') or
                line_lower.startswith('file operations') or
                ('ai plan' in line_lower and line_lower.startswith('#'))):
                # Skip this line and all content until next section or end
                i += 1
                while i < len(lines):
                    next_line = lines[i].strip()
                    next_line_lower = next_line.lower()
                    # Stop at next section header
                    if next_line.startswith('#'):
                        break
                    # Stop at empty line followed by non-indented content that's not part of the plan
                    if (next_line == '' and i + 1 < len(lines)):
                        following_line = lines[i + 1].strip()
                        following_lower = following_line.lower()
                        # If next line doesn't look like plan content, stop
                        if not (following_line.startswith(('-', '*', '1.', '2.', '3.', '4.', '5.', 'task-', 'step', 'completed', 'use web', 'search', 'verify', 'answered')) or
                                'completed' in following_lower or 'provide' in following_lower or 'plan' in following_lower or
                                'answered' in following_lower or 'search for' in following_lower):
                            break
                    i += 1
                continue
            
            # Check for "Remaining Tasks:" or similar headers
            if re.match(r'^(remaining tasks|remaining task|task status|tasks:).*', line_lower):
                i += 1
                # Skip the task list that follows
                while i < len(lines):
                    next_line = lines[i].strip()
                    if not next_line or next_line.startswith(('-', '*', '1.', '2.', '3.', '4.', '5.', 'task', 'step')):
                        i += 1
                    else:
                        break
                continue
            
            # Check for task-1, task-2, etc. patterns (remove TODO list items)
            if re.match(r'^[-*]?\s*(task[- ]?\d+|step[- ]?\d+|task \d+).*', line_lower):
                # Check if it's a completed task or just a task description
                if 'completed' in line_lower or re.search(r'\(completed\)|\[completed\]', line_lower):
                    i += 1
                    continue
                # Also remove task descriptions that are just status updates
                if re.search(r'^(task|step).*:(search|verify|provide|get|obtain|check)', line_lower):
                    i += 1
                    # Skip the description that follows
                    while i < len(lines) and (lines[i].strip() == '' or lines[i].startswith('  ') or 
                                               re.match(r'^(after|to|using|we will)', lines[i].lower().strip())):
                        i += 1
                    continue
            
            # Check for "COMPLETED" status indicators (remove lines with completed actions)
            # But be more selective - don't remove lines that mention completion as part of the answer
            if re.match(r'^(completed|complete|done|finished).*$', line_lower) and len(line_lower) < 50:
                # Short status lines like "completed" or "completed: task name"
                i += 1
                continue
            if 'completed' in line_lower and re.search(r'\[completed\]|\(completed\)|status.*completed', line_lower):
                # Lines with explicit completed status markers
                i += 1
                continue
            
            # Check for "Answered the question" or similar plan completion statements
            if re.match(r'^(answered|completed|finished|done).*(question|task|request)', line_lower):
                i += 1
                continue
            
            # Check for lines that are just status descriptions
            if re.match(r'^(search|verify|provide|get|obtain).*(for|the|current|price)', line_lower) and len(line_lower) < 50:
                # Short status lines like "Search for the current Bitcoin price"
                i += 1
                continue
            
            # Check for "Task X: Description" patterns (remove task execution descriptions)
            if re.match(r'^task \d+:\s*(search|verify|provide|get|obtain|check|find|run)', line_lower):
                # Skip task descriptions like "Task 1: Search for..."
                i += 1
                # Skip the following description lines
                while i < len(lines):
                    next_line = lines[i].strip()
                    next_lower = next_line.lower()
                    # Stop at next task or section
                    if re.match(r'^(task \d+|step \d+|##|###)', next_lower):
                        break
                    # Stop if we hit actual content (not a continuation of task description)
                    if next_line and not (next_line.startswith(('after', 'to ', 'we ', 'using', '  ')) or 
                                         re.match(r'^(after|to verify|we found|result:)', next_lower)):
                        break
                    i += 1
                continue
            
            # Check for "After searching..." or "After re-verifying..." patterns (redundant task execution descriptions)
            if re.match(r'^(after (searching|re-verifying|verifying|checking|inspecting)|to verify|to re-verify)', line_lower):
                # Skip these redundant execution descriptions
                i += 1
                # Skip the following line if it's just continuation
                if i < len(lines) and (lines[i].strip() == '' or lines[i].startswith('  ') or 
                                       re.match(r'^(we found|we are|result:|the result)', lines[i].lower().strip())):
                    i += 1
                continue
            
            # Check for verification statements
            if re.match(r'^(i verified|i have verified|verifying|verification|no additional verification)', line_lower):
                i += 1
                continue
            
            # Check for task status update sections
            if 'task status update' in line_lower or 'remaining risks' in line_lower:
                i += 1
                continue
            
            # Check for lines that are task items (like "Verify the price information", "Get the latest price")
            if re.match(r'^(verify|get|check|obtain|retrieve|find).*(the|price|information|currency|data|result)', line_lower) and len(line_lower) < 60:
                # These are task descriptions, not answers
                i += 1
                continue
            
            # Check for lines that describe what was done (plan execution descriptions)
            if re.match(r'^(use|using|provide|providing|get|getting|obtain|obtaining).*(web|search|tool|price)', line_lower):
                # Skip if it's clearly a plan description, not the actual answer
                if 'to' in line_lower or 'in order to' in line_lower:
                    i += 1
                    continue
            
            # Check for repetitive "Web Search Results:" headers and redundant result formatting
            if re.match(r'^(web search results|query:|result:).*', line_lower):
                # Skip redundant search result headers
                i += 1
                # Skip the JSON code block or result that follows if it's just formatting
                if i < len(lines):
                    next_line = lines[i].strip()
                    if next_line.startswith('```') or next_line.startswith('{') or next_line.startswith('['):
                        # Skip until end of code block or JSON
                        in_code_block = next_line.startswith('```')
                        brace_count = 0
                        bracket_count = 0
                        if next_line.startswith('{'):
                            brace_count = next_line.count('{') - next_line.count('}')
                        if next_line.startswith('['):
                            bracket_count = next_line.count('[') - next_line.count(']')
                        
                        while i < len(lines):
                            current_line = lines[i].strip()
                            if in_code_block:
                                if current_line.endswith('```'):
                                    i += 1
                                    break
                            else:
                                brace_count += current_line.count('{') - current_line.count('}')
                                bracket_count += current_line.count('[') - current_line.count(']')
                                if brace_count <= 0 and bracket_count <= 0 and (current_line.endswith('}') or current_line.endswith(']')):
                                    i += 1
                                    break
                            i += 1
                            if i >= len(lines):
                                break
                continue
            
            # Check for redundant "The task of..." completion statements
            if re.match(r'^(the task of|the task is|task.*is now complete)', line_lower):
                i += 1
                continue
            
            # Keep the line
            filtered_lines.append(line)
            i += 1
        
        result = '\n'.join(filtered_lines).strip()
        
        # Remove unhelpful phrases that don't provide answers
        unhelpful_phrases = [
            r'please provide more (context|information|details)',
            r'i need (more|additional) (information|context|details)',
            r'^we will use.*to (obtain|get|fetch|retrieve)',
            r'^we will (obtain|get|fetch|retrieve)',
            r'^we\'ll use.*to (obtain|get|fetch|retrieve)',
            r'^we\'ll (obtain|get|fetch|retrieve)',
            r'to complete (this|the) task, i need',
            r'specify the next step',
            r'please let me know if you\'d like (additional|more|any) information',
            r'please let me know if you need (additional|more|any) information',
            r'if you\'d like to see (the|additional)',
            r'i can (display|show|provide) (the|additional)',
            r'alternatively, if you\'d like',
            r'note: prices may fluctuate',
            r'source: \[.*\]\(.*\)',
            r'\(as of the last search result provided\)',
            r'\(as of the latest search result\)',
            r'i verified.*by searching',
            r'the price.*has (changed|been updated)',
            r'none\s*$',  # Remove standalone "None" lines (like "Remaining Risks: None")
            r'^please note that.*change quickly',  # Remove disclaimers about data changing
            r'^the information provided is based on.*at the time of writing',
            r'^after searching for.*using the (websearch|web search) tool',
            r'^after re-verifying.*we are confident',
            r'^to verify.*we will check',
            r'^the task of.*is now complete',
            r'^no additional verification is required',
            r'^remaining tasks:\s*$',  # Remove empty "Remaining Tasks:" lines
        ]
        for phrase in unhelpful_phrases:
            result = re.sub(phrase, '', result, flags=re.IGNORECASE)
        
        # Clean up multiple consecutive empty lines
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        # Remove lines that are just "File Operations" or similar
        result_lines = result.split('\n')
        cleaned_result_lines = []
        for line in result_lines:
            line_lower = line.lower().strip()
            if line_lower in ('file operations', 'file operation', 'project overview', 'verification', 'ai plan', 'todo list', 
                            'task status update', 'remaining risks', 'task report', 'verification report', 'fileoperations',
                            'current file operations', 'remaining tasks'):
                continue
            # Remove lines that are just "Web Search Results:" headers (redundant)
            if line_lower == 'web search results:' or line_lower.startswith('web search results') or line_lower == 'query:':
                continue
            # Remove standalone "Verification" headers
            if line_lower == 'verification' and (not cleaned_result_lines or cleaned_result_lines[-1].strip() == ''):
                continue
            # Remove lines that are just task numbers like "Task 1:", "Task 2:" without meaningful content
            if re.match(r'^task \d+:\s*$', line_lower) or re.match(r'^step \d+:\s*$', line_lower):
                continue
            # Remove lines that are just "Result:" or "Query:" headers
            if line_lower in ('result:', 'query:', 'results:'):
                continue
            # Remove repetitive "Trending Word" headers if they appear multiple times
            if line_lower.startswith('trending word') and any('trending' in prev.lower() for prev in cleaned_result_lines[-3:] if prev.strip()):
                continue
            cleaned_result_lines.append(line)
        result = '\n'.join(cleaned_result_lines).strip()
        
        # If we filtered everything, return a minimal response
        if not result or len(result) < 10:
            # Try to extract just code blocks or the last meaningful paragraph
            code_blocks = re.findall(r'```[\s\S]*?```', response, re.DOTALL)
            if code_blocks:
                return '\n\n'.join(code_blocks)
            
            # Return the last paragraph that's not thinking/planning
            paragraphs = response.split('\n\n')
            for para in reversed(paragraphs):
                para_lower = para.lower().strip()
                if not any(re.match(pattern, para_lower) for pattern in thinking_patterns + planning_patterns):
                    if len(para.strip()) > 20:
                        return para.strip()
            
            # If still empty, try to extract meaningful content but avoid pure thinking
            # This prevents showing nothing when the model only generated thinking-like content
            if response.strip():
                # Remove only the most obvious thinking prefixes but keep the content
                cleaned = response.strip()
                # Remove common thinking prefixes but keep the rest
                for pattern in [r'^(let me|i\'ll|i will)\s+', r'^(thinking|analyzing):\s*']:
                    cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
                
                # Check if what remains is still mostly thinking (starts with thinking patterns)
                cleaned_lower = cleaned.lower().strip()
                is_still_thinking = any(
                    cleaned_lower.startswith(prefix) 
                    for prefix in ['i need to', 'i should', 'i must', 'to understand', 'to analyze', 
                                 'the user is asking', 'this is a question', 'i need to search']
                )
                
                # Only return if it's not pure thinking and has meaningful length
                if cleaned.strip() and len(cleaned.strip()) > 10 and not is_still_thinking:
                    return cleaned.strip()
            
            # Last resort: return original if filtering removed everything
            # But check if original is not just thinking
            if response.strip():
                response_lower = response.lower().strip()
                is_thinking_only = any(
                    response_lower.startswith(prefix) or response_lower.startswith('the user')
                    for prefix in ['i need to', 'i should', 'i must', 'to understand', 'to analyze',
                                 'thinking:', 'analyzing:', 'the user is asking', 'this is a question']
                )
                # If it's not just thinking, return it; otherwise return a generic message
                if not is_thinking_only:
                    return response.strip()
            
            # Final fallback: generic message (NEVER return thinking content as response)
            return "I've processed your request. Please let me know if you need more information."
        
        # Remove duplicate price statements (AI sometimes mentions price twice - old then new)
        # Keep only the last (most recent) price mention
        price_pattern = r'the current price.*?\$[\d,]+\.?\d*'
        price_matches = list(re.finditer(price_pattern, result, re.IGNORECASE | re.DOTALL))
        if len(price_matches) > 1:
            # Find all price mentions and keep only the last one
            lines = result.split('\n')
            filtered_lines = []
            last_price_idx = -1
            for i, line in enumerate(lines):
                if re.search(price_pattern, line, re.IGNORECASE):
                    last_price_idx = i
            # Rebuild, removing earlier price mentions
            if last_price_idx >= 0:
                for i, line in enumerate(lines):
                    is_price_line = bool(re.search(price_pattern, line, re.IGNORECASE))
                    if not is_price_line or i == last_price_idx:
                        filtered_lines.append(line)
                result = '\n'.join(filtered_lines)
        
        # Remove duplicate "Verification" sections - keep only first
        if result.lower().count('verification') > 1:
            lines = result.split('\n')
            filtered_lines = []
            verification_count = 0
            skip_verification = False
            for line in lines:
                line_lower = line.lower().strip()
                if 'verification' in line_lower and (line_lower.startswith('#') or line_lower == 'verification'):
                    verification_count += 1
                    if verification_count > 1:
                        skip_verification = True
                        continue
                    skip_verification = False
                elif skip_verification and line_lower.startswith('#'):
                    skip_verification = False
                if not skip_verification:
                    filtered_lines.append(line)
            result = '\n'.join(filtered_lines)
        
        # Remove duplicate content blocks (same substantial text appearing multiple times)
        # This catches cases where the AI repeats the same information verbatim
        lines = result.split('\n')
        seen_signatures = set()
        deduplicated_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            line_stripped = line.strip()
            
            # Check if this looks like a repeated section header
            if line_stripped and line_stripped.startswith('#'):
                # Create a signature from the next few lines to detect duplicates
                signature_lines = [line_stripped.lower()]
                j = i + 1
                # Collect next 3-5 lines for signature
                while j < len(lines) and j < i + 6:
                    next_line = lines[j].strip()
                    if next_line:
                        signature_lines.append(next_line.lower()[:50])  # First 50 chars
                    j += 1
                
                signature = '|'.join(signature_lines)
                
                # If we've seen this exact pattern before, skip it
                if signature in seen_signatures and len(signature) > 30:
                    # Skip this section
                    i += 1
                    while i < len(lines):
                        if lines[i].strip().startswith(('##', '###')):
                            break
                        i += 1
                    continue
                
                seen_signatures.add(signature)
            
            deduplicated_lines.append(line)
            i += 1
        
        result = '\n'.join(deduplicated_lines).strip()
        
        # Final cleanup: remove excessive empty lines
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        return result
    
    def _correct_price_from_search_results(self, response: str, context: Dict[str, Any]) -> str:
        """Extract correct information from search results if AI used outdated data"""
        import re
        
        # Get search results
        search_results_text = context.get("web_search_results_mcp", "")
        if not search_results_text:
            direct_results = context.get("web_search_results", [])
            if direct_results:
                # Format direct results into text
                search_results_text = "\n".join([
                    f"{r.get('title', '')} {r.get('snippet', '')} {r.get('body', '')} {r.get('description', '')}"
                    for r in direct_results
                ])
        
        if not search_results_text:
            return response  # No search results available
        
        # Detect what type of price query this is (crypto, forex, stock)
        response_lower = response.lower()
        search_lower = search_results_text.lower()
        
        # Check for crypto queries
        crypto_keywords = ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'cryptocurrency']
        is_crypto = any(keyword in response_lower for keyword in crypto_keywords)
        
        # Check for forex queries
        forex_keywords = ['forex', 'fx', 'exchange rate', 'eur/usd', 'usd/eur', 'gbp/usd', 'usd/jpy', 'currency pair']
        forex_currencies = ['usd', 'eur', 'gbp', 'jpy', 'aud', 'cad', 'chf', 'cny', 'nzd', 'sek', 'nok', 'mxn', 'zar', 'inr', 'krw', 'sgd', 'hkd']
        is_forex = any(keyword in response_lower for keyword in forex_keywords) or \
                   (any(curr in response_lower for curr in forex_currencies) and ('rate' in response_lower or 'exchange' in response_lower))
        
        # Check for outdated BTC/crypto prices ($23,000-$24,000 range - common outdated training data)
        outdated_crypto_pattern = r'\$23[,.]?\d{3}[,.]?\d*'
        if is_crypto and re.search(outdated_crypto_pattern, response):
            # Extract all prices from search results
            # Look for USD prices: $XX,XXX.XX or $XX,XXX
            price_pattern = r'\$[\d,]+\.?\d*'
            prices_found = re.findall(price_pattern, search_results_text)
            
            if prices_found:
                # Convert to numbers and find the highest (most likely current price)
                def parse_price(price_str):
                    try:
                        return float(price_str.replace('$', '').replace(',', ''))
                    except:
                        return 0
                
                prices = [parse_price(p) for p in prices_found]
                # Reasonable crypto price ranges (BTC can be $20k-$150k+, ETH $1k-$10k+, etc.)
                valid_prices = [p for p in prices if 100 < p < 200000]
                if valid_prices:
                    # Use the highest price found (most likely current)
                    correct_price = max(valid_prices)
                    correct_price_str = f"${correct_price:,.2f}" if correct_price % 1 else f"${int(correct_price):,}"
                    
                    # Replace outdated price with correct price
                    response = re.sub(
                        outdated_crypto_pattern,
                        correct_price_str,
                        response,
                        count=1  # Replace only first occurrence
                    )
        
        # Handle forex exchange rates
        if is_forex:
            # Look for exchange rate patterns: 1.05, 1.1234, 0.85, etc. (typical forex rates)
            # Also look for formats like "EUR/USD 1.05" or "1.05 EUR/USD"
            forex_rate_patterns = [
                r'\b(\d+\.\d{2,5})\b.*\b(usd|eur|gbp|jpy|aud|cad|chf|cny|nzd|sek|nok|mxn|zar|inr|krw|sgd|hkd)\b',
                r'\b(usd|eur|gbp|jpy|aud|cad|chf|cny|nzd|sek|nok|mxn|zar|inr|krw|sgd|hkd)\b.*\b(\d+\.\d{2,5})\b',
                r'\b(\d+\.\d{2,5})\s*[/-]\s*(usd|eur|gbp|jpy|aud|cad|chf|cny|nzd|sek|nok|mxn|zar|inr|krw|sgd|hkd)\b',
            ]
            
            # Extract rates from search results
            rates_found = []
            for pattern in forex_rate_patterns:
                matches = re.finditer(pattern, search_results_text, re.IGNORECASE)
                for match in matches:
                    rate_str = match.group(1) if match.group(1) and '.' in match.group(1) else match.group(2)
                    try:
                        rate = float(rate_str)
                        # Forex rates are typically between 0.5 and 2.0 for major pairs, but can be wider
                        # For JPY pairs, rates can be 100+ (e.g., USD/JPY ~150)
                        if 0.1 < rate < 1000:  # Reasonable forex rate range
                            rates_found.append(rate)
                    except:
                        continue
            
            # If we found rates and response doesn't have a clear rate, try to extract and add it
            if rates_found and not re.search(r'\b\d+\.\d{2,5}\b', response):
                # Use the most common rate (or median if multiple)
                if len(rates_found) > 1:
                    rates_found.sort()
                    correct_rate = rates_found[len(rates_found) // 2]  # Median
                else:
                    correct_rate = rates_found[0]
                
                # Find currency pair mentioned in response
                currency_pair_match = re.search(r'\b([A-Z]{3})\s*[/-]\s*([A-Z]{3})\b', response, re.IGNORECASE)
                if currency_pair_match:
                    pair = f"{currency_pair_match.group(1).upper()}/{currency_pair_match.group(2).upper()}"
                    # Add rate if not already present
                    if f"{pair} {correct_rate:.4f}" not in response and f"{correct_rate:.4f} {pair}" not in response:
                        # Try to insert rate near currency pair mention
                        response = re.sub(
                            rf'\b({currency_pair_match.group(1)}[/-]{currency_pair_match.group(2)})\b',
                            f"{pair} {correct_rate:.4f}",
                            response,
                            count=1,
                            flags=re.IGNORECASE
                        )
        
        # Check for other common outdated patterns when web search results are available
        # If the response mentions "I don't have access" or "I cannot" but we have search results, 
        # that's a sign the AI ignored the search results
        if re.search(r"(?:i (?:don'?t|do not) have|i cannot|cannot access|no access to|unable to access).*(?:internet|web|current|latest|real.?time)", response, re.IGNORECASE):
            # The AI claimed it doesn't have access, but we provided search results
            # Try to extract key information from search results and prepend it
            if len(search_results_text) > 100:
                # Extract first meaningful sentence from search results
                sentences = re.split(r'[.!?]+', search_results_text[:500])
                if sentences:
                    first_info = sentences[0].strip()
                    if len(first_info) > 20:
                        # Prepend a note that we're using search results
                        response = f"Based on current web search results: {first_info}\n\n{response}"
        
        # Check if response contains phrases indicating the AI didn't use search results
        # when search results are clearly available
        ignore_patterns = [
            r"based on my (?:knowledge|training|data)",
            r"as of my (?:last|most recent) (?:update|knowledge)",
            r"my training (?:data|knowledge)",
            r"i (?:was|am) (?:trained|trained on)",
        ]
        
        has_ignore_phrase = any(re.search(pattern, response, re.IGNORECASE) for pattern in ignore_patterns)
        if has_ignore_phrase and search_results_text:
            # The AI is referencing its training data instead of search results
            # Add a warning at the beginning
            response = f"⚠️ NOTE: Current information from web search is available above. " + response
        
        return response
    
    async def _extract_price_data_for_chart(self, message: str, response: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract price data and fetch real-time data from API for chart display"""
        import re
        import aiohttp
        
        message_lower = message.lower()
        response_lower = response.lower()
        
        # Check if this is a price query
        price_keywords = ['price', 'rate', 'exchange rate', 'forex', 'crypto', 'bitcoin', 'btc', 'ethereum', 'eth']
        is_price_query = any(keyword in message_lower for keyword in price_keywords)
        
        if not is_price_query:
            return None
        
        # Determine asset type and identifier
        asset_type = 'crypto'
        asset_identifier = None
        
        # Check for crypto
        crypto_patterns = {
            'bitcoin': ['bitcoin', 'btc'],
            'ethereum': ['ethereum', 'eth'],
            'cardano': ['cardano', 'ada'],
            'solana': ['solana', 'sol'],
            'polkadot': ['polkadot', 'dot'],
            'chainlink': ['chainlink', 'link'],
            'avalanche': ['avalanche', 'avax'],
            'polygon': ['polygon', 'matic'],
            'dogecoin': ['dogecoin', 'doge'],
            'litecoin': ['litecoin', 'ltc'],
            'ripple': ['ripple', 'xrp'],
        }
        
        for name, patterns in crypto_patterns.items():
            if any(pattern in message_lower or pattern in response_lower for pattern in patterns):
                asset_identifier = name  # Use lowercase for API
                break
        
        # Check for forex
        forex_patterns = {
            'eur/usd': ['eur/usd', 'eur usd', 'euro'],
            'gbp/usd': ['gbp/usd', 'gbp usd', 'pound'],
            'usd/jpy': ['usd/jpy', 'usd jpy', 'yen'],
            'usd/chf': ['usd/chf', 'usd chf', 'swiss franc'],
            'aud/usd': ['aud/usd', 'aud usd', 'australian dollar'],
            'usd/cad': ['usd/cad', 'usd cad', 'canadian dollar'],
        }
        
        for pair, patterns in forex_patterns.items():
            if any(pattern in message_lower or pattern in response_lower for pattern in patterns):
                asset_identifier = pair
                asset_type = 'forex'
                break
        
        # If we found an asset, fetch real-time data from API
        if asset_identifier:
            try:
                # Import the market data functions directly instead of making HTTP calls
                # This avoids circular dependencies and is more efficient
                from backend.api.market_data import fetch_crypto_price, fetch_forex_rate
                
                if asset_type == 'crypto':
                    # Map asset identifier to coin ID
                    crypto_id_map = {
                        'bitcoin': 'bitcoin',
                        'btc': 'bitcoin',
                        'ethereum': 'ethereum',
                        'eth': 'ethereum',
                        'cardano': 'cardano',
                        'ada': 'cardano',
                        'solana': 'solana',
                        'sol': 'solana',
                        'polkadot': 'polkadot',
                        'dot': 'polkadot',
                        'chainlink': 'chainlink',
                        'link': 'chainlink',
                        'avalanche': 'avalanche',
                        'avax': 'avalanche',
                        'polygon': 'polygon',
                        'matic': 'polygon',
                        'dogecoin': 'dogecoin',
                        'doge': 'dogecoin',
                        'litecoin': 'litecoin',
                        'ltc': 'litecoin',
                        'ripple': 'ripple',
                        'xrp': 'ripple',
                    }
                    coin_id = crypto_id_map.get(asset_identifier, asset_identifier)
                    price_data = await fetch_crypto_price(coin_id, days=30)
                elif asset_type == 'forex':
                    # Parse forex pair
                    forex_map = {
                        'eur/usd': {'base': 'EUR', 'target': 'USD'},
                        'gbp/usd': {'base': 'GBP', 'target': 'USD'},
                        'usd/jpy': {'base': 'USD', 'target': 'JPY'},
                        'usd/chf': {'base': 'USD', 'target': 'CHF'},
                        'aud/usd': {'base': 'AUD', 'target': 'USD'},
                        'usd/cad': {'base': 'USD', 'target': 'CAD'},
                    }
                    pair_info = forex_map.get(asset_identifier)
                    if pair_info:
                        price_data = await fetch_forex_rate(pair_info['base'], pair_info['target'], days=30)
                    else:
                        raise ValueError(f"Unsupported forex pair: {asset_identifier}")
                
                if price_data:
                    # Format historical data for chart component
                    historical_data = price_data.get('historicalData', [])
                    if historical_data:
                        # Ensure data is in the format expected by PriceChart
                        formatted_data = []
                        for item in historical_data:
                            formatted_data.append({
                                'date': item.get('date', ''),
                                'price': item.get('price', 0),
                                'timestamp': item.get('timestamp', 0)
                            })
                        price_data['historicalData'] = formatted_data
                    
                    return price_data
            except ImportError:
                logger.warning("Market data API not available, falling back to text extraction")
            except Exception as e:
                logger.error(f"Error fetching real-time price data: {e}", exc_info=True)
                # Fallback to extracting from response text
                pass
        
        # Fallback: Extract current price from response if API fails
        current_price = None
        asset_name = None
        
        # Try to extract price from response
        # For crypto: $XX,XXX.XX format - look for the largest/most recent price
        crypto_price_matches = re.findall(r'\$[\d,]+\.?\d*', response)
        if crypto_price_matches:
            prices = []
            for match in crypto_price_matches:
                try:
                    price_str = match.replace('$', '').replace(',', '')
                    price_val = float(price_str)
                    if 100 < price_val < 200000:
                        prices.append(price_val)
                except:
                    pass
            if prices:
                current_price = max(prices)
                if asset_identifier:
                    asset_name = asset_identifier.capitalize()
        
        # For forex: X.XXXX format
        if not current_price and asset_type == 'forex' and asset_identifier:
            forex_rate_patterns = [
                r'\b(\d+\.\d{2,5})\b',
            ]
            for pattern in forex_rate_patterns:
                forex_rate_matches = re.findall(pattern, response, re.IGNORECASE)
                if forex_rate_matches:
                    rates = []
                    for match in forex_rate_matches:
                        rate_str = match if isinstance(match, str) else (match[0] if isinstance(match, tuple) else str(match))
                        try:
                            rate_val = float(rate_str)
                            if 0.1 < rate_val < 1000:
                                rates.append(rate_val)
                        except:
                            pass
                    if rates:
                        rates.sort()
                        current_price = rates[len(rates) // 2] if len(rates) > 1 else rates[0]
                        asset_name = asset_identifier.upper()
                        break
        
        # Return fallback data if we found a price
        if current_price and asset_name:
            return {
                'currentPrice': current_price,
                'assetName': asset_name,
                'assetType': asset_type,
                'timestamp': datetime.now().isoformat()
            }
        
        return None

    async def perform_web_search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch search results from DuckDuckGo when browsing is enabled."""
        # Use enhanced web search service if available
        if hasattr(self, '_web_search_service'):
            results, metadata = await self._web_search_service.search(
                query=query,
                max_results=max_results or self.web_search_max_results,
                search_type="text",
                use_cache=True,
                optimize_query=True
            )
            # Convert to expected format
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "title": result.get("title") or "",
                    "url": result.get("href") or result.get("url") or "",
                    "snippet": result.get("body") or result.get("description") or "",
                    "source": result.get("source") or result.get("hostname") or ""
                })
            return formatted_results
        
        # Fallback to original implementation
        if not query or DDGS is None:
            return []

        loop = asyncio.get_event_loop()
        target_results = max_results or self.web_search_max_results

        def run_search():
            collected: List[Dict[str, Any]] = []
            with DDGS() as ddgs:
                for result in ddgs.text(query, max_results=target_results):
                    collected.append({
                        "title": result.get("title") or "",
                        "url": result.get("href") or result.get("url") or "",
                        "snippet": result.get("body") or result.get("description") or "",
                        "source": result.get("source") or result.get("hostname") or ""
                    })
            return collected

        return await loop.run_in_executor(None, run_search)

    async def process_message(
        self, 
        message: str, 
        context: Dict[str, Any] = None,
        conversation_history: List[Dict[str, str]] = None,
        images: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Process a message and get AI response"""
        
        # Initialize accumulated thinking at the start - must be initialized before any use
        # Use explicit None assignment to ensure it's always defined
        accumulated_thinking: Optional[str] = None
        
        if self.provider == "ollama":
            if not await self.check_ollama_connection():
                raise Exception("Ollama is not running. Please start Ollama and install a model.")
            # Validate that the selected model exists
            available_models = await self.get_available_models()
            if available_models and self.current_model not in available_models:
                logger.warning(f"Model '{self.current_model}' not found in available models. Available: {available_models}. Trying anyway...")
                # Note: We'll try anyway as Ollama might return a better error message
        elif self.provider == "huggingface":
            if InferenceClient is None:
                raise Exception("huggingface-hub is not installed. Please install it to use Hugging Face models.")
            if not self.hf_api_key:
                raise Exception("Hugging Face API key (HF_API_KEY) is not configured.")
            if not self.hf_model:
                raise Exception("Hugging Face model name (HF_MODEL) is not configured.")
        elif self.provider == "openrouter":
            if not self.openrouter_api_key:
                raise Exception("OpenRouter API key (OPENROUTER_API_KEY) is not configured.")
            if not self.openrouter_model:
                raise Exception("OpenRouter model name (OPENROUTER_MODEL) is not configured.")
        else:
            raise Exception(f"Unsupported LLM provider: {self.provider}")
        
        # Create conversation ID if not provided
        conversation_id = str(uuid.uuid4())
        response_message_id = str(uuid.uuid4())

        # Clone and enrich context
        context = dict(context or {})
        web_search_mode = (context.get("web_search_mode") or "off").lower()
        context["web_search_mode"] = web_search_mode
        web_search_enabled = web_search_mode in ("browser_tab", "google_chrome", "auto")
        context["_web_search_attempted"] = False
        
        new_script_requested = bool(context.get("requested_new_script"))
        if not new_script_requested and self._detect_new_script_request(message):
            new_script_requested = True
            context["requested_new_script"] = True
            context.setdefault("intent", "new_script")
        
        if new_script_requested:
            for key in ("active_file", "active_file_content", "default_target_file"):
                context.pop(key, None)
            if context.get("open_files"):
                context["open_files_snapshot"] = context["open_files"]
                context["open_files"] = []
            context.setdefault("new_script_prompt", message)
            context["disable_active_file_context"] = True

        # Detect if query needs web search and use MCP tools to perform it
        # Only allow web search if it's not explicitly disabled
        if web_search_mode == "off":
            needs_web_search = False
        else:
            force_web_search = (
                web_search_mode in ("browser_tab", "google_chrome")
                and not context.get("disable_forced_web_search")
            )
            needs_web_search = force_web_search or self._detect_web_search_needed(message, web_search_mode)
        
        if needs_web_search:
            normalized_query = (message or "").strip().lower()
            requires_browser = any(term in normalized_query for term in [
                "open ",
                "visit ",
                "navigate to ",
                "browser tab",
                "google chrome",
                "use the browser",
                "show me the website",
                "display the page",
                "on the website",
                "in the browser",
            ])
            if requires_browser and not web_search_enabled:
                context["web_search_error"] = (
                    "Browser mode is disabled. Enable the browser tab to allow live web lookups."
                )
            else:
                # Use MCP tools to perform web search instead of direct internet access
                if self.is_mcp_enabled():
                    try:
                        # Extract search query from message
                        search_query = self._extract_search_query(message)
                        
                        # Use MCP web_search tool to perform the search
                        tool_call = {
                            "name": "web_search",
                            "arguments": {
                                "query": search_query,
                                "max_results": self.web_search_max_results,
                                "search_type": "text"
                            }
                        }
                        
                        # Execute web search via MCP
                        tool_results = await self.mcp_client.execute_tool_calls(
                            [tool_call],
                            allow_write=True  # Web search doesn't modify files
                        )
                        
                        # Extract results from MCP tool execution
                        if tool_results and not tool_results[0].get("error", False):
                            result_text = tool_results[0].get("result", "")
                            context["web_search_results_mcp"] = result_text
                            structured_results = self._parse_web_search_results_text(result_text)
                            if structured_results:
                                context["web_search_results"] = structured_results
                            # Only mark as auto if web search mode wasn't explicitly off
                            if web_search_mode != "off":
                                context["web_search_mode"] = "auto"  # Mark as auto-triggered
                            web_search_enabled = True
                            context["_web_search_attempted"] = True
                        else:
                            error_msg = tool_results[0].get("result", "Unknown error") if tool_results else "No results"
                            context["web_search_error"] = error_msg
                            context["_web_search_attempted"] = True
                    except Exception as error:
                        context["web_search_error"] = f"{type(error).__name__}: {error}"
                        context["_web_search_attempted"] = True
                else:
                    # Fallback: if MCP not available, use direct search (shouldn't happen in production)
                    # Only if web search is not explicitly disabled
                    if web_search_mode != "off":
                        try:
                            search_query = self._extract_search_query(message)
                            search_results = await self.perform_web_search(search_query)
                            if search_results:
                                context["web_search_results"] = search_results
                                context["web_search_mode"] = "auto"
                                web_search_enabled = True
                                context["_web_search_attempted"] = True
                        except Exception as error:
                            context["web_search_error"] = f"{type(error).__name__}: {error}"
                            context["_web_search_attempted"] = True
        if needs_web_search and not web_search_enabled and not context.get("web_search_error"):
            context["web_search_error"] = (
                "Browser mode is off, so live web searches are unavailable for this request."
            )
        elif web_search_mode in ("browser_tab", "google_chrome"):
            # Explicit web search mode - perform search if query clearly needs current information
            # Check if the message needs web search (prices, current events, etc.)
            if self._detect_web_search_needed(message, web_search_mode):
                # Perform web search automatically when clearly needed
                if self.is_mcp_enabled():
                    try:
                        search_query = self._extract_search_query(message)
                        tool_call = {
                            "name": "web_search",
                            "arguments": {
                                "query": search_query,
                                "max_results": self.web_search_max_results,
                                "search_type": "text"
                            }
                        }
                        # Use longer timeout to allow MCP processes to complete (30 seconds)
                        try:
                            tool_results = await asyncio.wait_for(
                                self.mcp_client.execute_tool_calls(
                                    [tool_call],
                                    allow_write=True
                                ),
                                timeout=30.0
                            )
                            if tool_results and not tool_results[0].get("error", False):
                                context["web_search_results_mcp"] = tool_results[0].get("result", "")
                                structured_results = self._parse_web_search_results_text(tool_results[0].get("result", ""))
                                if structured_results:
                                    context["web_search_results"] = structured_results
                                context["_web_search_attempted"] = True
                        except asyncio.TimeoutError:
                            print(f"Web search timed out in {web_search_mode} mode - continuing without results")
                        except Exception as search_error:
                            print(f"Web search exception in {web_search_mode} mode: {search_error}")
                    except Exception as error:
                        print(f"Web search error in {web_search_mode} mode: {error}")
                else:
                    # Fallback to direct search with longer timeout (30 seconds)
                    try:
                        search_query = self._extract_search_query(message)
                        try:
                            search_results = await asyncio.wait_for(
                                self.perform_web_search(search_query),
                                timeout=30.0
                            )
                            if search_results:
                                context["web_search_results"] = search_results
                                context["_web_search_attempted"] = True
                        except asyncio.TimeoutError:
                            print(f"Web search timed out in {web_search_mode} mode - continuing without results")
                        except Exception as search_error:
                            print(f"Web search exception in {web_search_mode} mode: {search_error}")
                    except Exception as error:
                        print(f"Web search error in {web_search_mode} mode: {error}")
            
            # Legacy code path (disabled) - kept for reference
            if False:  # Disable automatic searches in browser_tab/google_chrome mode
                # Use MCP tools to perform web search with timeout
                if self.is_mcp_enabled():
                    try:
                        # Extract search query from message
                        search_query = self._extract_search_query(message)
                        
                        # Use MCP web_search tool with timeout to prevent hanging
                        tool_call = {
                            "name": "web_search",
                            "arguments": {
                                "query": search_query,
                                "max_results": self.web_search_max_results,
                                "search_type": "text"
                            }
                        }
                        
                        # Use longer timeout to allow MCP processes to complete (30 seconds)
                        try:
                            tool_results = await asyncio.wait_for(
                                self.mcp_client.execute_tool_calls(
                                    [tool_call],
                                    allow_write=True
                                ),
                                timeout=30.0
                            )
                            
                            if tool_results and not tool_results[0].get("error", False):
                                context["web_search_results_mcp"] = tool_results[0].get("result", "")
                            # Don't set error if search fails - just continue without results
                        except asyncio.TimeoutError:
                            print(f"Web search timed out in {web_search_mode} mode - continuing without results")
                            # Don't set error - just continue without search results
                        except Exception as search_error:
                            print(f"Web search exception in {web_search_mode} mode: {search_error}")
                            # Don't set error - just continue without search results
                    except Exception as error:
                        # Log error but don't block response
                        print(f"Web search error in {web_search_mode} mode: {error}")
                        context["web_search_error"] = f"{type(error).__name__}: {error}"
                else:
                    # Fallback to direct search with timeout
                    try:
                        search_query = self._extract_search_query(message)
                        # Use longer timeout to allow search to complete (30 seconds)
                        try:
                            search_results = await asyncio.wait_for(
                                self.perform_web_search(search_query),
                                timeout=30.0
                            )
                            if search_results:
                                context["web_search_results"] = search_results
                            # Don't set error if search fails - just continue without results
                        except asyncio.TimeoutError:
                            print(f"Web search timed out in {web_search_mode} mode - continuing without results")
                            # Don't set error - just continue without search results
                        except Exception as search_error:
                            print(f"Web search exception in {web_search_mode} mode: {search_error}")
                            # Don't set error - just continue without search results
                    except Exception as error:
                        # Log error but don't block response
                        print(f"Web search error in {web_search_mode} mode: {error}")
                        context["web_search_error"] = f"{type(error).__name__}: {error}"
            # If web search mode is enabled but the message doesn't need a search,
            # just mark that web search is available for the AI to use if needed
            # The AI can still use the web_search tool in its response if it needs to
            # The response will continue normally regardless of search status
        
        # Prepare the prompt with context
        prompt = self._build_prompt(message, context, conversation_history or [], images=images)
        
        # Get initial response from configured provider
        # accumulated_thinking is already initialized to None at function start
        response, thinking = await self._call_model(prompt, images=images)
        # Always assign to ensure variable is set (even if thinking is None)
        accumulated_thinking = thinking if thinking else None
        
        # Extract ai_plan from initial response BEFORE tool execution
        # This ensures the plan is preserved even if the follow-up response doesn't include it
        initial_metadata = self._parse_response_metadata(response, context)[1]
        initial_ai_plan = initial_metadata.get("ai_plan")
        if initial_ai_plan:
            logger.info(f"Extracted initial ai_plan with {len(initial_ai_plan.get('tasks', []))} tasks")
        
        # Initialize tool_calls - will be populated from MCP or auto-trigger logic
        tool_calls = []
        
        # Handle MCP tool calls if enabled
        if self.is_mcp_enabled():
            tool_calls = self.mcp_client.parse_tool_calls_from_response(response)
            # Remove tool calls from response text if any were found
            if tool_calls:
                response = self.mcp_client.remove_tool_calls_from_text(response)
            
            # Check if user asked about directories but AI didn't use tools (just described what it would do)
            message_lower = (message or "").lower()
            response_lower = (response or "").lower()
            directory_keywords = ["scan", "directory", "list files", "examine", "project structure", "show directory", "what files", "directory contents", "understand the project"]
            directory_intent = any(keyword in message_lower for keyword in directory_keywords)
            just_describing = any(phrase in response_lower for phrase in [
                "i'll scan", "i will scan", "let me scan", "i'll examine", "i will examine", 
                "let me examine", "i'll check", "i will check", "let me check", "i'll look",
                "i will look", "let me look", "i'll list", "i will list"
            ])
            
            # If user wants directory info but AI just described action without tool call, auto-trigger tool
            if directory_intent and just_describing and not tool_calls:
                logger.info("Detected directory scan request but AI only described action - auto-triggering list_directory tool")
                # Determine path from message or use current directory
                path = "."
                if "path" in message_lower or "/" in message or "\\" in message:
                    # Try to extract path from message (simple extraction)
                    import re
                    path_match = re.search(r'["\']([^"\']+[/\\][^"\']+)["\']', message)
                    if path_match:
                        path = path_match.group(1)
                    else:
                        # Look for path-like strings
                        words = message.split()
                        for word in words:
                            if "/" in word or "\\" in word:
                                path = word.strip('"\'')
                                break
                
                # Auto-trigger list_directory tool
                auto_tool_call = {
                    "name": "list_directory",
                    "arguments": {"path": path}
                }
                tool_calls = [auto_tool_call]
                logger.info(f"Auto-triggered list_directory tool with path: {path}")
        
        # Check if user asked about web search topics but AI didn't use tools
        # This works with or without MCP (has fallback)
        message_lower = (message or "").lower()
        response_lower = (response or "").lower()
        
        # Get web_search_mode from context to check if web search is enabled
        web_search_mode = (context.get("web_search_mode") or "off").lower()
        web_search_enabled = web_search_mode in ("browser_tab", "google_chrome", "auto")
        
        # Check if we already have search results (don't trigger again)
        has_search_results = bool(context.get("web_search_results_mcp") or context.get("web_search_results"))
        web_search_attempted = context.get("_web_search_attempted", False)
        
        # Auto-trigger web search for clear queries (only if web_search_mode is not "off")
        # Check if we already have a web_search tool call
        has_web_search_call = any(tc.get("name") == "web_search" for tc in tool_calls) if tool_calls else False
        
        # Auto-trigger if:
        # 1. Web search mode is not explicitly disabled
        # 2. We don't already have a web_search tool call
        # 3. We don't already have search results
        # 4. The query clearly needs web search
        if web_search_mode != "off" and not has_web_search_call and not has_search_results:
            # Keywords that clearly indicate web search is needed
            web_search_keywords = ["who is", "what is", "current price", "latest news", "recent", "today", "now", "current", "find information", "search for", "look up", "tell me about", "information about"]
            web_search_intent = any(keyword in message_lower for keyword in web_search_keywords)
            
            # Also check for questions about people, places, companies, etc. (common web search queries)
            # Questions typically start with who, what, when, where, why, how
            is_question = message.strip().endswith("?") or any(message_lower.strip().startswith(q + " ") for q in ["who", "what", "when", "where", "why", "how"])
            # Check if it's asking about a person (name pattern) or entity - matches "John Doe" or "Jundee Mark G. Molina"
            has_name_pattern = bool(re.search(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', message)) if message else False
            
            # If it's a question or has a name pattern, likely needs web search
            if (is_question or has_name_pattern) and not web_search_intent:
                web_search_intent = True
                logger.info(f"Detected web search intent from question/name pattern: is_question={is_question}, has_name_pattern={has_name_pattern}, message='{message[:50]}'")
            
            # Check if AI said it will search (but didn't include tool call)
            # Check both response and thinking content
            thinking_lower = (accumulated_thinking or "").lower()
            combined_text = (response_lower + " " + thinking_lower).lower()
            
            web_search_describing = any(phrase in combined_text for phrase in [
                "i'll search", "i will search", "let me search", "i'll look up", "i will look up",
                "let me look up", "i'll find", "i will find", "let me find", "i'll get information",
                "i will get information", "let me get information", "using the web_search", "use the web_search",
                "should search", "need to search", "will search", "search for information", "search the web",
                "web_search tool", "search tool", "internet access", "search for information about",
                "i need to search", "i should search", "need to use", "should use the web_search",
                "will use the web_search", "going to search", "i'm going to search", "i need to get",
                "current information", "up-to-date", "real-time", "latest information", "current data"
            ])
            
            logger.info(f"[DEBUG] Web search detection: intent={web_search_intent}, describing={web_search_describing}, has_results={has_search_results}, attempted={web_search_attempted}")
            
            # Auto-trigger web search if user clearly needs it OR AI said it will search
            # Only trigger if web_search_mode is not explicitly disabled
            should_auto_trigger = False
            reason = ""
            
            if web_search_intent:
                should_auto_trigger = True
                reason = "user query requires web search"
            elif web_search_describing:
                should_auto_trigger = True
                reason = "AI described search action without tool call"
            
            # Trigger for questions about people, places, or current information
            # But only if web search mode is not explicitly disabled
            if not should_auto_trigger and (is_question or has_name_pattern):
                # Double-check: if it's a question or has a name, it likely needs web search
                should_auto_trigger = True
                reason = "question or name pattern detected - likely needs web search"
            
            if should_auto_trigger:
                logger.info(f"Auto-triggering web_search tool - reason: {reason}, query: {message[:100]}")
                # Extract search query from message
                search_query = self._extract_search_query(message)
                if not search_query or len(search_query.strip()) < 3:
                    # Fallback: use the message itself as query
                    search_query = message.strip()
                
                # Auto-trigger web_search tool
                auto_tool_call = {
                    "name": "web_search",
                    "arguments": {
                        "query": search_query,
                        "max_results": self.web_search_max_results,
                        "search_type": "text"
                    }
                }
                # Add web_search to existing tool_calls if any, otherwise create new list
                if tool_calls:
                    tool_calls.append(auto_tool_call)
                    logger.info(f"Added web_search tool call to existing {len(tool_calls)-1} tool call(s)")
                else:
                    tool_calls = [auto_tool_call]
                logger.info(f"Auto-triggered web_search tool with query: {search_query}")
                print(f"[DEBUG] Auto-triggered web_search: query='{search_query}', tool_calls={tool_calls}")
                print(f"[DEBUG] Total tool calls after auto-trigger: {len(tool_calls)}")
        
        # Execute tool calls (works with or without MCP - has fallback for web_search)
        if tool_calls:
                logger.info(f"Executing {len(tool_calls)} tool call(s): {[tc.get('name') for tc in tool_calls]}")
                print(f"[DEBUG] About to execute tool calls: {tool_calls}")
                print(f"[DEBUG] MCP enabled: {self.is_mcp_enabled()}, MCP client: {self.mcp_client is not None}")
                
                # Execute tool calls
                allow_write = self._can_modify_files(context)
                try:
                    if not self.is_mcp_enabled():
                        logger.warning("MCP is not enabled or client is not available - attempting fallback for web_search")
                        print(f"[DEBUG] MCP not enabled - attempting fallback for web_search")
                        
                        # Fallback: Handle web_search directly when MCP is not available
                        tool_results = []
                        for tool_call in tool_calls:
                            tool_name = tool_call.get("name")
                            if tool_name == "web_search":
                                # Use direct web search fallback
                                try:
                                    args = tool_call.get("arguments", {})
                                    query = args.get("query", "")
                                    max_results = args.get("max_results", self.web_search_max_results)
                                    search_type = args.get("search_type", "text")  # Get search_type from arguments
                                    
                                    if query:
                                        logger.info(f"Fallback: Performing web search for '{query}' (type: {search_type})")
                                        search_results = await self.perform_web_search(query, max_results=max_results)
                                        
                                        if search_results:
                                            # Format results similar to MCP tool output
                                            from backend.services.web_search_service import WebSearchService
                                            web_service = WebSearchService()
                                            # Convert search_results format to web_search_service format
                                            formatted_search_results = []
                                            for r in search_results:
                                                formatted_search_results.append({
                                                    "title": r.get("title", ""),
                                                    "href": r.get("url", ""),
                                                    "url": r.get("url", ""),
                                                    "body": r.get("snippet", ""),
                                                    "description": r.get("snippet", ""),
                                                    # Include image fields for image search results
                                                    "image": r.get("image"),
                                                    "thumbnail": r.get("thumbnail")
                                                })
                                            formatted_results = web_service.format_results(
                                                formatted_search_results,
                                                query,
                                                include_metadata=True,
                                                search_type=search_type  # Use search_type from tool call
                                            )
                                            tool_results.append({
                                                "tool": "web_search",
                                                "arguments": tool_call.get("arguments", {}),
                                                "result": formatted_results,
                                                "error": False
                                            })
                                            logger.info(f"Fallback web search successful: {len(search_results)} results")
                                        else:
                                            tool_results.append({
                                                "tool": "web_search",
                                                "arguments": tool_call.get("arguments", {}),
                                                "result": "No search results found.",
                                                "error": False
                                            })
                                    else:
                                        tool_results.append({
                                            "tool": "web_search",
                                            "arguments": tool_call.get("arguments", {}),
                                            "result": "Error: No search query provided",
                                            "error": True
                                        })
                                except Exception as search_error:
                                    logger.error(f"Fallback web search failed: {search_error}", exc_info=True)
                                    tool_results.append({
                                        "tool": "web_search",
                                        "arguments": tool_call.get("arguments", {}),
                                        "result": f"Error performing web search: {str(search_error)}",
                                        "error": True
                                    })
                            else:
                                # For non-web_search tools, return error when MCP is not available
                                tool_results.append({
                                    "tool": tool_name,
                                    "arguments": tool_call.get("arguments", {}),
                                    "result": f"Tool '{tool_name}' requires MCP which is not available",
                                    "error": True
                                })
                    else:
                        tool_results = await self.mcp_client.execute_tool_calls(tool_calls, allow_write=allow_write)
                        logger.info(f"Tool execution completed: {len(tool_results) if tool_results else 0} result(s)")
                        print(f"[DEBUG] Tool execution results: {len(tool_results) if tool_results else 0} result(s)")
                        if tool_results:
                            for idx, result in enumerate(tool_results):
                                print(f"[DEBUG] Result {idx}: tool={result.get('tool')}, error={result.get('error')}, result_length={len(result.get('result', ''))}")
                except Exception as tool_error:
                    logger.error(f"Tool execution failed: {tool_error}", exc_info=True)
                    print(f"[DEBUG] Tool execution error: {tool_error}")
                    import traceback
                    print(f"[DEBUG] Traceback: {traceback.format_exc()}")
                    tool_results = None
                
                # If tools were executed, get a follow-up response with results
                if tool_results and not all(r.get("error", False) for r in tool_results):
                    # Check if any tool call was web_search and store results in context
                    for idx, tool_call in enumerate(tool_calls):
                        tool_name = tool_call.get("name")
                        if tool_name == "web_search" and idx < len(tool_results):
                            result = tool_results[idx]
                            is_error = result.get("error", False)
                            result_text = result.get("result", "")
                            
                            logger.info(f"Processing web_search result: error={is_error}, result_length={len(result_text) if result_text else 0}")
                            print(f"[DEBUG] web_search result: error={is_error}, result_length={len(result_text) if result_text else 0}")
                            
                            if not is_error and result_text:
                                context["web_search_results_mcp"] = result_text
                                structured_results = self._parse_web_search_results_text(result_text)
                                if structured_results:
                                    context["web_search_results"] = structured_results
                                context["_web_search_attempted"] = True  # Mark as attempted to prevent duplicates
                                logger.info(f"Stored web_search results in context ({len(result_text)} chars)")
                                print(f"[DEBUG] Stored web_search results: {len(result_text)} chars")
                            elif is_error:
                                error_msg = result_text or result.get("error", "Unknown error")
                                logger.error(f"web_search tool returned error: {error_msg}")
                                print(f"[DEBUG] web_search error: {error_msg}")
                                context["web_search_error"] = error_msg
                            else:
                                logger.warning("web_search returned empty result")
                                print(f"[DEBUG] web_search returned empty result")
                    
                    # Format tool results for prompt
                    if self.mcp_client:
                        tool_results_text = self.mcp_client.format_tool_results_for_prompt(tool_results)
                    else:
                        # Fallback formatting when MCP client is not available
                        formatted = ["=" * 80]
                        formatted.append("TOOL EXECUTION RESULTS")
                        formatted.append("=" * 80)
                        formatted.append("")
                        for result in tool_results:
                            tool_name = result.get("tool", "unknown")
                            is_error = result.get("error", False)
                            result_text = result.get("result", "")
                            status = "ERROR" if is_error else "SUCCESS"
                            formatted.append(f"[{status}] {tool_name}:")
                            if is_error:
                                formatted.append(f"Error: {result_text}")
                            else:
                                formatted.append(result_text)
                            formatted.append("")
                        formatted.append("=" * 80)
                        formatted.append("")
                        formatted.append("IMPORTANT: The tool execution results above contain the actual data from the tools.")
                        formatted.append("You MUST use this information in your response. Do not say you will perform the action - it has already been done.")
                        formatted.append("For web_search results, extract the relevant information and provide a direct answer to the user's question.")
                        formatted.append("")
                        tool_results_text = "\n".join(formatted)
                    logger.info(f"Formatted tool results: {len(tool_results_text)} chars")
                    
                    # Build follow-up prompt with tool results
                    # Include explicit instructions to use the search results
                    follow_up_prompt = f"{prompt}\n\nInitial AI response:\n{response}\n\n{tool_results_text}\n\n🚨 CRITICAL INSTRUCTIONS 🚨\n\nThe tool execution results above contain the ACTUAL web search results. The search has ALREADY been performed.\n\nYou MUST:\n1. Use the search results to provide a direct, complete answer to the user's question\n2. Do NOT say you will search, need to search, or should search - the search is DONE\n3. Do NOT include thinking about searching - just provide the answer using the results\n4. Extract relevant information from the search results and present it clearly\n5. If the search results contain the answer, use them directly\n\nDo NOT repeat phrases like:\n- 'I'll search for...'\n- 'Let me search...'\n- 'I need to search...'\n- 'I should use the web_search tool...'\n\nInstead, directly answer the question using the search results provided above."
                    
                    # Get follow-up response that incorporates tool results
                    logger.info("Getting follow-up response with tool results...")
                    follow_up_response, follow_up_thinking = await self._call_model(follow_up_prompt)
                    response = follow_up_response  # Use the follow-up response
                    logger.info(f"Follow-up response received: {len(response)} chars")
                    print(f"[DEBUG] Follow-up response preview: {response[:200]}...")
                    
                    # Remove any tool calls from the follow-up response (shouldn't be any, but just in case)
                    if self.mcp_client:
                        response = self.mcp_client.remove_tool_calls_from_text(response)
                    if follow_up_thinking:
                        if accumulated_thinking:
                            accumulated_thinking = (accumulated_thinking + "\n" + follow_up_thinking).strip()
                        else:
                            accumulated_thinking = follow_up_thinking
                elif tool_results:
                    errors = [r.get("error", "Unknown") for r in tool_results if r.get("error")]
                    logger.warning(f"Tool execution had errors: {errors}")
        
        # Check if AI response indicates uncertainty or lack of knowledge
        # If so, try web search as fallback (only if web search mode is not off and no search was done yet)
        # When web search mode is "off", rely only on model knowledge
        # Skip if we already have search results or already attempted search
        has_search_results = bool(context.get("web_search_results_mcp") or context.get("web_search_results"))
        web_search_attempted = context.get("_web_search_attempted", False)
        
        if (web_search_enabled and 
            not has_search_results and 
            not web_search_attempted and
            self._detect_ai_uncertainty(response, message)):
            logger.info("AI response indicates uncertainty - attempting fallback web search")
            try:
                # Extract search query from original message
                search_query = self._extract_search_query(message)
                
                # Try to perform web search using MCP tools first
                if self.is_mcp_enabled():
                    tool_call = {
                        "name": "web_search",
                        "arguments": {
                            "query": search_query,
                            "max_results": self.web_search_max_results,
                            "search_type": "text"
                        }
                    }
                    
                    tool_results = await self.mcp_client.execute_tool_calls(
                        [tool_call],
                        allow_write=True
                    )
                    
                    if tool_results and not tool_results[0].get("error", False):
                        result_text = tool_results[0].get("result", "")
                        context["web_search_results_mcp"] = result_text
                        structured_results = self._parse_web_search_results_text(result_text)
                        if structured_results:
                            context["web_search_results"] = structured_results
                        context["web_search_fallback"] = True  # Mark as fallback search
                        context["_web_search_attempted"] = True
                        logger.info(f"Fallback web search successful: {len(result_text)} chars")
                        
                        # Build follow-up prompt with web search results
                        search_context = f"\n\nWeb search results for your query:\n{result_text}\n\n"
                        follow_up_prompt = f"{prompt}\n\nInitial response:\n{response}\n\n{search_context}Please use the web search results above to provide a better answer. If the search results contain relevant information, use it to answer the question. If not, explain what you found."
                        
                        # Get follow-up response that incorporates web search results
                        follow_up_response, follow_up_thinking = await self._call_model(follow_up_prompt)
                        response = follow_up_response
                        if follow_up_thinking:
                            if accumulated_thinking:
                                accumulated_thinking = (accumulated_thinking + "\n" + follow_up_thinking).strip()
                            else:
                                accumulated_thinking = follow_up_thinking
                    else:
                        # Fallback: use direct web search
                        search_results = await self.perform_web_search(search_query)
                        if search_results:
                            # Format search results for prompt
                            formatted_results = []
                            for idx, result in enumerate(search_results[:self.web_search_max_results], 1):
                                formatted_results.append(
                                    f"{idx}. {result.get('title', 'No title')}\n"
                                    f"   URL: {result.get('url', 'N/A')}\n"
                                    f"   {result.get('snippet', 'No description')}"
                                )
                            
                            results_text = "\n\n".join(formatted_results)
                            context["web_search_results"] = search_results
                            context["web_search_fallback"] = True  # Mark as fallback search
                            context["_web_search_attempted"] = True
                            
                            # Build follow-up prompt with web search results
                            search_context = f"\n\nWeb search results for your query:\n{results_text}\n\n"
                            follow_up_prompt = f"{prompt}\n\nInitial response:\n{response}\n\n{search_context}Please use the web search results above to provide a better answer. If the search results contain relevant information, use it to answer the question. If not, explain what you found."
                            
                            # Get follow-up response that incorporates web search results
                            follow_up_response, follow_up_thinking = await self._call_model(follow_up_prompt)
                            response = follow_up_response
                            if follow_up_thinking:
                                if accumulated_thinking:
                                    accumulated_thinking = (accumulated_thinking + "\n" + follow_up_thinking).strip()
                                else:
                                    accumulated_thinking = follow_up_thinking
                else:
                    # Fallback: use direct web search if MCP not available
                    search_results = await self.perform_web_search(search_query)
                    if search_results:
                        context["web_search_results"] = search_results
                        context["web_search_fallback"] = True
                        context["_web_search_attempted"] = True
            except Exception as error:
                # If web search fails, continue with original response
                logger.warning(f"Web search fallback failed: {error}")
                # Don't raise - just use the original response
        
        # Parse metadata from response (pass context to block extraction in ASK mode)
        cleaned_response, metadata = self._parse_response_metadata(response, context)
        
        # Preserve initial ai_plan if follow-up response doesn't have one
        # This ensures the AI plan is shown first in the frontend even after tool execution
        if initial_ai_plan and not metadata.get("ai_plan"):
            metadata["ai_plan"] = initial_ai_plan
            logger.info("Preserved initial ai_plan in follow-up response")
        
        # Store original response length to detect if filtering was too aggressive
        original_length = len(cleaned_response.strip())
        
        # Filter out thinking/planning/reporting content
        cleaned_response = self._filter_thinking_content(cleaned_response, context)
        
        # If filtering removed too much (more than 90% of content), be less aggressive
        filtered_length = len(cleaned_response.strip())
        if original_length > 50 and filtered_length < (original_length * 0.1):
            # Filtering was too aggressive - use original response with minimal filtering
            logger.warning(f"Response filtering removed {original_length - filtered_length} chars, using lighter filter")
            # Only remove obvious thinking headers, keep the content
            import re
            lightly_filtered = re.sub(r'^#+\s*(thinking|analysis|reasoning):?\s*$', '', cleaned_response if cleaned_response else response, flags=re.IGNORECASE | re.MULTILINE)
            lightly_filtered = re.sub(r'^##\s*thinking\s*$', '', lightly_filtered, flags=re.IGNORECASE | re.MULTILINE)
            if lightly_filtered.strip() and len(lightly_filtered.strip()) > 10:
                cleaned_response = lightly_filtered.strip()
            elif response.strip():
                # Last resort: use original response
                cleaned_response = response.strip()
        
        structured_results = self._get_structured_web_results(context)
        # Post-process: If AI used outdated price ($23,433 range), extract correct price from search results
        if context.get("web_search_results_mcp") or structured_results:
            cleaned_response = self._correct_price_from_search_results(cleaned_response, context)
        
        # Extract web search references for frontend linking
        web_references = []
        if structured_results:
            for idx, result in enumerate(structured_results[:10], start=1):  # Limit to 10 references
                url = result.get("url", "").strip()
                title = result.get("title", "").strip()
                if url:
                    web_references.append({
                        "index": idx,
                        "url": url,
                        "title": title or url
                    })
        
        # Add web references to metadata
        if web_references:
            metadata["web_references"] = web_references
        
        # If response is empty or too short, try fallbacks
        if not cleaned_response.strip() or len(cleaned_response.strip()) < 10:
            # First try web search results
            if structured_results:
                fallback_from_results = self._build_answer_from_web_results(message, structured_results)
                if fallback_from_results:
                    cleaned_response = fallback_from_results
            
            # If still empty and we have the original response, use it with minimal processing
            if (not cleaned_response.strip() or len(cleaned_response.strip()) < 10) and response.strip():
                # The filtering was too aggressive - use original response but clean it minimally
                cleaned_response = response.strip()
                # Only remove obvious metadata blocks, keep everything else
                cleaned_response = re.sub(r'```json\s*\{[^}]*"(?:ai_plan|file_operations)"[^}]*\}\s*```', '', cleaned_response, flags=re.IGNORECASE | re.DOTALL)
                cleaned_response = cleaned_response.strip()
                
                # If still empty after minimal cleaning, ensure we have something
                if not cleaned_response.strip():
                    cleaned_response = "I'm processing your request. Please wait for the response."
        
        final_uncertain = self._detect_ai_uncertainty(cleaned_response, message)
        if final_uncertain and structured_results:
            direct_answer = self._build_answer_from_web_results(message, structured_results)
            if direct_answer:
                cleaned_response = direct_answer
                final_uncertain = False
                metadata["ai_plan"] = None
                metadata["file_operations"] = []
        search_attempted = bool(context.get("_web_search_attempted"))
        search_results_present = bool(context.get("web_search_results_mcp") or context.get("web_search_results"))
        needs_fallback = final_uncertain and len(cleaned_response.strip()) < 400
        if needs_fallback:
            fallback_query = self._extract_search_query(message or "")
            cleaned_response = self._build_no_answer_response(
                fallback_query,
                web_search_enabled,
                search_attempted,
                search_results_present
            )
            metadata["ai_plan"] = None
            metadata["file_operations"] = []
        
        # CRITICAL: Ensure we always have a response, even if minimal
        # NEVER use thinking content as the main response - it should be separate
        if not cleaned_response.strip() or len(cleaned_response.strip()) < 5:
            # If filtering removed everything, use the original response with minimal cleaning
            if response.strip() and len(response.strip()) > 10:
                logger.warning("Filtering removed all content, using original response with minimal cleaning")
                # Only remove obvious metadata blocks, keep everything else including thinking-like content
                import re
                minimal_cleaned = re.sub(r'```json\s*\{[^}]*"(?:ai_plan|file_operations)"[^}]*\}\s*```', '', response, flags=re.IGNORECASE | re.DOTALL)
                minimal_cleaned = re.sub(r'\n{3,}', '\n\n', minimal_cleaned).strip()
                if minimal_cleaned and len(minimal_cleaned) > 10:
                    cleaned_response = minimal_cleaned
                else:
                    cleaned_response = response.strip()
            
            # Final fallback: ensure we always return something meaningful
            if not cleaned_response.strip() or len(cleaned_response.strip()) < 5:
                # Try to build answer from web search results if available
                if structured_results:
                    fallback_answer = self._build_answer_from_web_results(message, structured_results)
                    if fallback_answer and len(fallback_answer.strip()) > 10:
                        cleaned_response = fallback_answer
                
                # Last resort: generic message (NEVER use thinking content as response)
                if not cleaned_response.strip() or len(cleaned_response.strip()) < 5:
                    cleaned_response = "I've processed your request. Please let me know if you need more information."
        
        # CRITICAL: Ensure ASK mode NEVER has file operations or plans, even if the AI generated them
        if self._is_ask_context(context):
            metadata["file_operations"] = []
            metadata["ai_plan"] = None
            # Also strip any file operation mentions from the response text
            cleaned_response = self._strip_file_operation_mentions(cleaned_response)
        
        # Never generate file operations in ASK mode
        # In agent mode, if no file operations were generated but the user asked for changes, force regeneration
        existing_ops = metadata.get("file_operations") or []
        has_file_ops = existing_ops and len(existing_ops) > 0
        
        if self._can_modify_files(context) and not has_file_ops:
            should_force = self._should_force_file_operations(message, cleaned_response, context)
            
            # Additional check: in agent mode, if user message has change intent, be more aggressive
            if not should_force and self._is_agent_context(context):
                user_has_change_intent = self._has_change_intent(message)
                # If user explicitly asked for changes but no file operations were generated, force it
                if user_has_change_intent:
                    should_force = True
            
            if should_force:
                print(f"[Agent Mode] Forcing file operations generation for message: {message[:100]}...")
                fallback_cleaned, fallback_metadata = await self._generate_file_operations_metadata(
                    message=message,
                    context=context,
                    history=conversation_history or [],
                    assistant_response=cleaned_response
                )
                fallback_ops = fallback_metadata.get("file_operations") or []
                if fallback_ops and len(fallback_ops) > 0:
                    print(f"[Agent Mode] Generated {len(fallback_ops)} file operation(s) via fallback")
                    metadata["file_operations"] = fallback_ops
                    if fallback_metadata.get("ai_plan") and not metadata.get("ai_plan"):
                        metadata["ai_plan"] = fallback_metadata["ai_plan"]
                    # Don't add the "Generated concrete file operations" message - it's not needed
                    # cleaned_response is already set above
                else:
                    print(f"[Agent Mode] Warning: Fallback file operations generation returned no operations")
                    # If fallback failed but we're in agent mode with change intent, try one more time with a simpler prompt
                    if self._is_agent_context(context) and self._has_change_intent(message):
                        print(f"[Agent Mode] Retrying with simplified prompt...")
                        simplified_prompt = (
                            f"The user requested: {message[:200]}\n\n"
                            f"Generate file_operations JSON. If they asked to create a file, include a create_file operation. "
                            f"If they asked to modify code, include edit_file operations.\n\n"
                            f"Format: {{\"file_operations\": [{{\"type\": \"create_file\", \"path\": \"filename.ext\", \"content\": \"...\"}}]}}\n\n"
                            f"Return ONLY valid JSON, no other text."
                        )
                        try:
                            retry_response, _ = await self._call_model(simplified_prompt)
                            retry_cleaned, retry_metadata = self._parse_response_metadata(retry_response, context)
                            retry_ops = retry_metadata.get("file_operations") or []
                            if retry_ops and len(retry_ops) > 0:
                                print(f"[Agent Mode] Retry successful: Generated {len(retry_ops)} file operation(s)")
                                metadata["file_operations"] = retry_ops
                        except Exception as retry_error:
                            print(f"[Agent Mode] Retry failed: {retry_error}")
        
        # Store conversation
        self.conversation_history[conversation_id] = {
            "messages": conversation_history or [],
            "last_updated": datetime.now().isoformat()
        }
        context.pop("_web_search_attempted", None)
        
        # Ensure accumulated_thinking is always defined before use
        # The variable is initialized at the start of the function, so it's always available
        thinking_value = accumulated_thinking
        
        result = {
            "content": cleaned_response,
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
            "context_used": context,
            "message_id": response_message_id,
            "thinking": thinking_value
        }
        
        # Only include file_operations and ai_plan if file modifications are allowed
        if self._can_modify_files(context):
            file_operations = metadata.get("file_operations") or []
            # Only include if we have actual operations (not empty list)
            if file_operations and len(file_operations) > 0:
                result["file_operations"] = file_operations
                print(f"[Agent Mode] Returning {len(file_operations)} file operation(s) in response")
            else:
                # In agent mode, if user asked for changes but no file ops, log it
                if self._is_agent_context(context) and self._has_change_intent(message):
                    print(f"[Agent Mode] WARNING: User asked for changes but no file operations generated!")
                result["file_operations"] = None

            if metadata.get("ai_plan"):
                result["ai_plan"] = metadata["ai_plan"]
        else:
            # Explicitly set to None/null in ASK mode to prevent any confusion
            result["file_operations"] = None
            result["ai_plan"] = None
        
        # Add web references if available (for clickable citations)
        if metadata.get("web_references"):
            result["web_references"] = metadata["web_references"]
        
        # Extract price data for charts if this is a price query
        price_data = await self._extract_price_data_for_chart(message, cleaned_response, context)
        if price_data:
            result["price_data"] = price_data
        
        return result
    
    def _strip_file_operation_mentions(self, response: str) -> str:
        """Remove any mentions of file operations from responses in ASK mode"""
        if not response:
            return response
        
        # Remove common file operation phrases
        patterns_to_remove = [
            rf'```json\s*\{{[^}}]*"(?:{FILE_OP_METADATA_PATTERN})"[^}}]*\}}[\s\S]*?```',
            rf'```json\s*\{{[^}}]*"(?:{AI_PLAN_METADATA_PATTERN})"[^}}]*\}}[\s\S]*?```',
            rf'\{{[^}}]*"(?:{FILE_OP_METADATA_PATTERN})"[^}}]*\}}',
            rf'\{{[^}}]*"(?:{AI_PLAN_METADATA_PATTERN})"[^}}]*\}}',
            r'##?\s*file\s+operations?\s*##?',
            r'##?\s*file\s+operation\s*##?',
        ]
        
        cleaned = response
        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE | re.DOTALL)
        
        # Clean up multiple consecutive empty lines
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        
        return cleaned.strip()
    
    def _build_prompt(
        self, 
        message: str, 
        context: Dict[str, Any], 
        history: List[Dict[str, str]],
        images: Optional[List[str]] = None
    ) -> str:
        """Build a comprehensive prompt with context
        
        Args:
            message: The user's message
            context: Context dictionary with mode, workspace info, etc.
            history: Conversation history
            images: Optional list of base64-encoded image data URLs
        """
        
        mode_value = (context.get("mode") or "").lower()
        chat_mode_value = (context.get("chat_mode") or "").lower()
        is_composer = bool(context.get("composer_mode"))
        is_agent_mode = is_composer or mode_value in ("agent", "plan") or chat_mode_value in ("agent", "plan")
        is_ask_mode = (not is_agent_mode) and (mode_value == "ask" or chat_mode_value == "ask")

        # Get current date and time for accurate date information
        now = datetime.now()
        current_date_str = now.strftime("%A, %B %d, %Y")
        # Try to get timezone name, fallback to UTC offset if not available
        try:
            tz_name = time.tzname[0] if time.tzname else ""
            tz_offset = now.strftime("%z")
            if tz_offset:
                tz_offset_formatted = f"{tz_offset[:3]}:{tz_offset[3:]}"
            else:
                tz_offset_formatted = ""
            current_time_str = now.strftime("%I:%M %p")
            if tz_name:
                current_time_str += f" {tz_name}"
            elif tz_offset_formatted:
                current_time_str += f" UTC{tz_offset_formatted}"
        except Exception:
            current_time_str = now.strftime("%I:%M %p")
        current_datetime_iso = now.isoformat()
        
        prompt_parts = [
            "You are an expert AI coding assistant similar to Cursor. You help developers with:",
            "- Code generation and completion",
            "- Code analysis and debugging",
            "- Refactoring and optimization",
            "- Explaining complex code",
            "- Creating and editing files",
            "- Best practices and patterns",
            "",
        ]
        
        # Add image information FIRST if provided (before other context)
        # Note: For full vision model support, images are passed to Ollama's /api/chat endpoint
        # The images are also available for use with the identify_image MCP tool
        
        # DEBUG: Log image status in prompt building
        logger.info(f"[IMAGE DEBUG] _build_prompt called - images param: type={type(images)}, length={len(images) if images else 0}")
        if images:
            logger.info(f"[IMAGE DEBUG] ✅ _build_prompt: Images present - {len(images)} image(s)")
            for idx, img in enumerate(images):
                logger.info(f"[IMAGE DEBUG]   Image {idx+1}: type={type(img)}, length={len(img) if img else 0}, starts_with_data={img.startswith('data:image') if img and isinstance(img, str) else False}")
        else:
            logger.warning(f"[IMAGE DEBUG] ⚠️ _build_prompt: NO IMAGES provided!")
        
        if images and len(images) > 0:
            prompt_parts.extend([
                "=" * 80,
                "🚨🚨🚨 CRITICAL: IMAGES ATTACHED TO THIS MESSAGE 🚨🚨🚨",
                "=" * 80,
                "",
                f"⚠️ ATTENTION: The user has attached {len(images)} image(s) to their message.",
                "",
                "MANDATORY ACTION REQUIRED:",
                "If the user's message mentions images, asks 'what is in this image', 'what's this', 'identify this',",
                "or ANY question about the image content, you MUST IMMEDIATELY call the identify_image tool.",
                "",
                "DO NOT:",
                "- Ask the user to provide image data",
                "- Say 'no image was provided'",
                "- Request the user to upload the image",
                "- Ask for base64 data",
                "",
                "DO THIS INSTEAD:",
                "- Call identify_image tool immediately: <tool_call name=\"identify_image\" args='{\"query\": \"what is in this image?\"}' />",
                "- The images are ALREADY available - you don't need image_data parameter",
                "- Use the tool FIRST, then respond based on the results",
                "",
                "=" * 80,
                "",
            ])
        
        prompt_parts.extend([
            "=" * 80,
            "CURRENT DATE AND TIME INFORMATION:",
            "=" * 80,
            f"Current date: {current_date_str}",
            f"Current time: {current_time_str}",
            f"ISO format: {current_datetime_iso}",
            "",
            "IMPORTANT: Always use the current date and time provided above when answering questions about dates, times, or temporal information.",
            "Do NOT use dates from your training data - use the current date/time information provided above.",
            "",
            "=" * 80,
            "",
        ])
        
        # Add detailed image instructions after date/time section
        if images and len(images) > 0:
            prompt_parts.extend([
                "",
                "=" * 80,
                f"DETAILED IMAGE INFORMATION: {len(images)} image(s) attached",
                "=" * 80,
                "",
                "The images from this message are automatically stored and available to the identify_image tool.",
                "You can call identify_image WITHOUT providing image_data - the images are already loaded.",
                "",
                "Tool call format (images are automatically available):",
                '<tool_call name="identify_image" args=\'{"query": "what is in this image?"}\' />',
                "",
                "The identify_image tool analyzes images to detect:",
                "- Objects, people, scenes, and visual content",
                "- Text content (OCR)",
                "- UI elements, buttons, icons, interface components",
                "- Code screenshots and programming content",
                "- Diagrams, charts, and visualizations",
                "",
                "REMEMBER: If the user asks about the image, call identify_image immediately.",
                "Do NOT ask for image data - it's already available!",
                "",
                "=" * 80,
                "",
            ])
        
        # Add memory information if available
        try:
            from .memory_service import MemoryService
            memory_service = MemoryService()
            if memory_service.should_reference_chat_history() or memory_service.settings.get("reference_saved_memories", True):
                memories_text = memory_service.get_memories_for_prompt()
                if memories_text:
                    prompt_parts.extend([
                        "",
                        memories_text,
                    ])
        except Exception as e:
            # Memory service not available or error - continue without it
            logger.debug(f"Memory service not available: {e}")
        
        # Add MCP tools description if enabled
        if self.is_mcp_enabled():
            mcp_tools_desc = self.mcp_client.get_tools_description()
            if mcp_tools_desc:
                prompt_parts.extend([
                    "",
                    "=" * 80,
                    "MCP TOOLS AVAILABLE (You CAN access the internet through these tools):",
                    "=" * 80,
                    "",
                    mcp_tools_desc,
                    "",
                    "IMPORTANT: You HAVE internet access through the web_search MCP tool. Use it to search the web for current information, prices, news, and any online content.",
                    "",
                    "CRITICAL RULE: NEVER write code to scrape websites, access URLs, or make HTTP requests to get internet information.",
                    "When you need internet information (prices, news, current data, etc.), you MUST use the web_search tool, NOT write Python code with requests/urllib/etc.",
                    "",
                    "You can use these tools by including tool calls in your response.",
                    "",
                    "🚨 CRITICAL: Tool call format MUST be exactly:",
                    '<tool_call name="tool_name" args=\'{"param": "value"}\' />',
                    "",
                    "CORRECT Examples:",
                    '- <tool_call name="read_file" args=\'{"path": "example.py"}\' />',
                    '- <tool_call name="write_file" args=\'{"path": "file.txt", "content": "text"}\' />',
                    '- <tool_call name="web_search" args=\'{"query": "current bitcoin price", "max_results": 5}\' />',
                    '- <tool_call name="list_directory" args=\'{"path": "."}\' />',
                    "",
                    "❌ WRONG Formats (DO NOT USE):",
                    '- <toolcall name="writefile" ...> (missing underscore, wrong tag name)',
                    '- [TOOLCALL "tool": "getfiletree"] (completely wrong format)',
                    '- writefile("path", "content") (function call format not supported)',
                    "",
                    "⚠️ IMPORTANT:",
                    "- Tool names use underscores: write_file, read_file, list_directory, get_file_tree, grep_code, execute_command, web_search",
                    "- Always close with /> (self-closing tag)",
                    "- Use single quotes for args attribute, double quotes inside JSON",
                    "",
                    "When you need to perform operations like:",
                    "- Reading files: use read_file tool",
                    "- Searching code: use grep_code tool",
                    "- Searching the web: use web_search tool (THIS GIVES YOU INTERNET ACCESS - DO NOT WRITE CODE TO SCRAPE)",
                    "- Executing commands: use execute_command tool",
                    "- Listing directory contents: use list_directory tool",
                    "- Getting directory tree structure: use get_file_tree tool",
                    "",
                    "🚨🚨🚨 CRITICAL DIRECTORY SCANNING RULE 🚨🚨🚨",
                    "",
                    "When the user asks to 'scan the directory', 'list files', 'show directory structure', 'examine the project', 'understand the project', or ANY similar request:",
                    "",
                    "❌ FORBIDDEN RESPONSES (DO NOT DO THIS):",
                    "- 'I'll scan the directory...'",
                    "- 'Let me examine the files...'",
                    "- 'I'll check the project structure...'",
                    "- 'I'll look at the directory...'",
                    "- ANY response that describes what you WILL do instead of actually doing it",
                    "",
                    "✅ REQUIRED ACTION (YOU MUST DO THIS):",
                    "- IMMEDIATELY use a tool call to get the actual directory data",
                    "- Example: <tool_call name=\"list_directory\" args='{\"path\": \".\"}' />",
                    "- Or: <tool_call name=\"get_file_tree\" args='{\"path\": \".\", \"max_depth\": 6}' />",
                    "- Then provide the ACTUAL directory listing or structure from the tool results",
                    "",
                    "The tool call MUST appear in your FIRST response. Do not describe - ACTUALLY DO IT.",
                    "",
                    "Use the appropriate MCP tools instead of just describing what should be done.",
                    "",
                    "🚨🚨🚨 CRITICAL WEB SEARCH RULE 🚨🚨🚨",
                    "",
                    "⚠️ MANDATORY: When the user asks about current information, real-time data, people, events, prices, news, historical figures, or ANY internet content:",
                    "",
                    "❌ ABSOLUTELY FORBIDDEN (DO NOT DO THIS - YOU WILL BE AUTO-CORRECTED):",
                    "- 'I'll search for information...'",
                    "- 'Let me search the web...'",
                    "- 'I'll look that up...'",
                    "- 'I'll find information about...'",
                    "- 'I need to search...'",
                    "- 'I should use the web_search tool...'",
                    "- ANY response that describes what you WILL do instead of actually doing it",
                    "- ANY thinking about searching without actually including the tool call",
                    "",
                    "✅ REQUIRED ACTION (YOU MUST DO THIS IMMEDIATELY):",
                    "- IMMEDIATELY include the web_search tool call in your response - DO NOT just describe it",
                    "- Example: <tool_call name=\"web_search\" args='{\"query\": \"Jundee Mark G. Molina\", \"max_results\": 5}' />",
                    "- The tool call MUST appear in your FIRST response. Do not describe - ACTUALLY DO IT.",
                    "- If you think about searching, you MUST include the actual tool call, not just describe it",
                    "- After including the tool call, the system will execute it and provide results",
                    "",
                    "🔴 CRITICAL: Questions starting with 'who', 'what', 'when', 'where', 'why', 'how' about people, places, events, or current data REQUIRE web_search.",
                    "🔴 CRITICAL: Questions about prices, news, current events, or real-time information REQUIRE web_search.",
                    "🔴 CRITICAL: Questions with names of people, places, or entities REQUIRE web_search.",
                    "",
                    "For ANY question requiring current information, real-time data, or internet content, you MUST use the web_search tool.",
                    "DO NOT write code with requests.get(), urllib, or any HTTP libraries to fetch internet data - use web_search tool instead.",
                    "",
                    "If you are unsure whether a query needs web search, ERR ON THE SIDE OF USING web_search.",
                    "",
                    "⚠️ WHEN NOT TO USE WEB SEARCH ⚠️",
                    "",
                    "DO NOT use web_search for queries about:",
                    "- UI elements, icons, buttons, tooltips, or interface features",
                    "- Questions about how the interface works (e.g., 'show more info', 'what does this icon do')",
                    "- Questions about the application itself or its features",
                    "- Questions that can be answered from the codebase or context",
                    "- Questions about UI/UX features, tooltips, hover effects, or interface elements",
                    "",
                    "Examples of queries that should NOT trigger web search:",
                    "- 'show more info' (about UI elements - this refers to tooltips/hover info)",
                    "- 'what does this icon do' (about interface elements)",
                    "- 'how does this feature work' (referring to the app interface)",
                    "- 'explain this button' (about UI elements)",
                    "- 'more information' (when referring to UI tooltips or help text)",
                    "",
                    "When users ask 'show more info' or 'more information' about UI elements:",
                    "- They are asking about tooltips, hover information, or help text in the interface",
                    "- They are NOT asking you to search the web for external information",
                    "- Answer by explaining what the UI element does or how to use it",
                    "- Do NOT perform a web search",
                    "",
                    "These are questions about the application interface, not external information that needs web search.",
                    "",
                    "=" * 80,
                    "",
                ])

        if is_ask_mode:
            prompt_parts.extend([
                "⚠️ ASK MODE (READ-ONLY) - CRITICAL RESTRICTIONS ⚠️",
                "",
                "ASK mode is STRICTLY read-only. You MUST follow these rules:",
                "",
                "1. NEVER create, edit, delete, or modify ANY files in ASK mode.",
                "2. NEVER include file_operations metadata in your response (not in JSON, not in code blocks, not anywhere).",
                "3. NEVER include JSON objects with 'file_operations' keys.",
                "4. NEVER generate code blocks that look like file operation metadata.",
                "5. If the user asks for file modifications, explain that ASK mode is read-only and suggest switching to Agent mode.",
                "6. You MAY include ai_plan metadata to show your thinking process and task breakdown (this is allowed and will be displayed).",
                "7. Provide a direct, concise answer to the user's question.",
                "8. You may include small code snippets for illustration, but never instruct the IDE to modify files.",
                "",
                "SYSTEM ENFORCEMENT: Even if you generate file_operations, they will be automatically stripped and ignored in ASK mode.",
                "However, ai_plan metadata will be extracted and displayed to help users understand your approach.",
                "",
            ])
        else:
            prompt_parts.extend([
                "IMPORTANT: When the user asks you to create, edit, or modify files, you MUST include",
                "file operations in a special JSON format at the end of your response.",
                "",
            ])

        prompt_parts.extend([
            "RESPONSE CONTENT RULES:",
            "- DO NOT include thinking, planning, reasoning, or reporting prose in your response text.",
            "- Your response should contain only the actual answer, code, explanations, or results.",
            "- Avoid phrases like 'Let me think...', 'I'll analyze...', 'Here's my plan...', 'In summary...', etc.",
            "- If you need to show your thinking process, put it in the `ai_plan` metadata (for agent/plan modes only).",
            "",
            "🚨 CRITICAL: NEVER say 'I'll scan...', 'I'll examine...', 'I'll check...' - ACTUALLY DO IT by using tools immediately.",
            "If the user asks about directories, files, or project structure, use list_directory or get_file_tree tool RIGHT AWAY.",
            "",
            "⚠️ IMPORTANT: `file_operations` is NOT a tool - it is metadata format for your response JSON.",
            "- Use MCP tools (write_file, read_file, list_directory, etc.) for actual file operations.",
            "- Include `file_operations` array in your JSON metadata response to tell the IDE what files to create/edit/delete.",
            "- NEVER call `file_operations` as a tool - it does not exist as a tool.",
            "",
            "MARKDOWN FORMATTING RULES:",
            "- Always answer using GitHub-flavored Markdown.",
            "- Use '##' and '###' headings (never top-level '#' headings).",
            "- Use bullet lists starting with '- ' and keep them concise.",
            "- Use bold (for example **text**) to highlight key points or pseudo-headings in lists.",
            "- Use backticks for file names, directories, functions, classes, and inline code (for example `app/main.py`).",
            "- When you include code, use fenced code blocks with a language tag, for example:",
            "```python",
            "def hello():",
            '    print("hi")',
            "```",
            "- Do not include artificial line numbers inside code blocks.",
            "- When mentioning URLs, either wrap them in backticks or use standard Markdown links like [docs](https://example.com).",
            "",
        ])

        is_plan_mode = self._is_plan_context(context) and not is_ask_mode
        
        if is_plan_mode:
            prompt_parts.extend([
                "📋 PLAN MODE REQUIREMENTS:",
                "",
                "PLAN MODE: Show the plan FIRST, then execute it step-by-step.",
                "",
                "- Your FIRST response MUST include a clear `ai_plan` with a summary and task breakdown.",
                "- Show the plan prominently before starting execution.",
                "- Break large requests into 3–6 concrete subtasks with clear titles.",
                "- Each task must have: id (unique string), title (descriptive), and status (`pending`, `in_progress`, or `completed`).",
                "- OPTIONAL: Tasks can include `depends_on` array listing task IDs that must complete first (for dependency tracking).",
                "- After showing the plan, begin executing tasks one by one.",
                "- Update task statuses in real-time as you work: `pending` → `in_progress` → `completed`.",
                "- The plan acts as a progress tracker—users can see what's done and what's remaining.",
                "- Always begin with information-gathering tasks (inspect files, read code, understand structure).",
                "- 🚨 CRITICAL: When gathering information, YOU MUST USE the list_directory or get_file_tree MCP tools.",
                "- 🚨 FORBIDDEN: Never respond with 'I'll scan...' or 'Let me examine...' - include the tool call in your response.",
                "- 🚨 CRITICAL: When a task requires web search, you MUST include the actual <tool_call name=\"web_search\" ... /> in your response.",
                "- 🚨 FORBIDDEN: Never mark a web search task as `completed` unless you have actually included the web_search tool call and received results.",
                "- 🚨 FORBIDDEN: Never say 'I'll search...' or 'Let me search...' - include the actual tool call: <tool_call name=\"web_search\" args='{\"query\": \"...\", \"max_results\": 5}' />",
                "- After planning, execute tasks proactively: gather information, produce file edits (via file_operations), or run commands.",
                "- When creating or editing files, emit file_operations and continue to the next task.",
                "- CRITICAL: If the user asks to create/modify files, you MUST include file_operations. Never just describe—actually do it.",
                "- Keep edits surgical: update only what's needed, preserve the rest.",
                "- Mark tasks as `completed` only when actually done AND the tool call has been executed. Mark active work as `in_progress`.",
                "- If a task fails or encounters an error, mark it as `blocked` and add a `error` field with details.",
                "- When a task is blocked, try to work around it or mark dependent tasks appropriately.",
                "- Continue working until all tasks are `completed` (unless blocked).",
                "- End with a verification task and reporting task that summarizes outcomes.",
                "",
                "PLAN VALIDATION:",
                "- Ensure all task IDs are unique and non-empty.",
                "- Ensure all tasks have valid statuses.",
                "- Avoid circular dependencies in `depends_on` arrays.",
                "- Keep task titles concise but descriptive (under 100 characters).",
                "",
                "PLAN MODE is more structured than Agent mode—always show the plan first, then execute.",
                "",
            ])
        elif is_agent_mode and not is_plan_mode:
            prompt_parts.extend([
                "🤖 AGENT MODE REQUIREMENTS:",
                "",
                "AGENT MODE: Fully autonomous execution—act like a coding copilot.",
                "",
                "- Think step-by-step internally, but DO NOT include thinking/planning/reporting prose in your response text.",
                "- Put your thinking process, planning steps, and task breakdowns in the `ai_plan` metadata only.",
                "- Your response text should contain only the actual answer, code, explanations, or results—not your internal reasoning process.",
                "- You may skip showing the plan and proceed directly to execution if appropriate.",
                "- Break large requests into 3–6 concrete subtasks that flow through: gather information ➜ plan ➜ implement ➜ verify ➜ report.",
                "- Always begin with at least one information-gathering task and actually perform it before presenting the plan.",
                "- 🚨 CRITICAL: When gathering information about directories or project structure, YOU MUST USE the list_directory or get_file_tree MCP tools.",
                "- 🚨 FORBIDDEN: Never respond with 'I'll scan the directory...' or 'Let me examine...' - you MUST include the tool call in your response.",
                "- If the user asks to scan, list, or examine a directory, your FIRST response MUST include: <tool_call name=\"list_directory\" args='{\"path\": \".\"}' /> or <tool_call name=\"get_file_tree\" args='{\"path\": \".\", \"max_depth\": 6}' />",
                "- Do not describe what you will do - the tool call must be in your response so the system can execute it.",
                "- Maintain a TODO list (max 5 items) where every task has an id, title, and status (`pending`, `in_progress`, or `completed`). Update statuses as you make progress so the user can monitor it.",
                "- Include this plan in the `ai_plan` metadata described below even if no file changes are required.",
                "- After planning, proactively execute the tasks: gather the requested information, produce concrete file edits (via file_operations), or clearly state which files/commands you ran.",
                "- 🚨 CRITICAL: When a task requires web search, you MUST include the actual <tool_call name=\"web_search\" ... /> in your response.",
                "- 🚨 FORBIDDEN: Never mark a web search task as `completed` unless you have actually included the web_search tool call in your response.",
                "- 🚨 FORBIDDEN: Never say 'I'll search...' or 'Let me search...' - include the actual tool call: <tool_call name=\"web_search\" args='{\"query\": \"...\", \"max_results\": 5}' />",
                "- Treat agent mode as fully autonomous execution: do NOT ask the user follow-up questions unless the request is self-contradictory or unsafe. Instead, state reasonable assumptions and continue working.",
                "- When the user responds with short inputs like `1`, `2`, `option A`, or repeats one of your earlier choices, interpret that as their selection instead of asking the same question again.",
                "- When creating or editing files, emit the necessary file_operations and then immediately move on to the next task—do not stop after the first modification if other tasks remain.",
                "- CRITICAL: If the user asks to create, make, write, or generate a file, you MUST include a create_file operation in file_operations. Never just describe the file—actually create it via file_operations.",
                "- CRITICAL: If the user asks to save, store, or save information/data/notes/content, you MUST create a file with that information using a create_file operation. Choose an appropriate filename based on the content (e.g., notes.txt, information.md, summary.txt).",
                "- CRITICAL: If the user asks to modify, update, change, or fix code, you MUST include edit_file operations in file_operations. Never just show code blocks—include the actual file_operations.",
                "- Keep edits surgical: update only the portions of each file that the user asked to change and preserve the rest of the file exactly as-is.",
                "- Only mark a task as `completed` if you actually performed that step in the current response AND included the necessary tool calls. Mark the task you are actively doing as `in_progress`; leave future work as `pending`.",
                "- Do not leave tasks pending unless you hit a hard blocker; otherwise continue working until every task is marked `completed` within this response.",
                "- Add a verification task (linting, reasoning, or test strategy) before reporting back, and end with a reporting task that summarizes outcomes and remaining risks.",
                "- When the user references a specific file or when composer_mode is true, you MUST produce concrete file edits, not just a plan.",
                "- Plans are only helpful if they are followed by actual file_operations that apply the requested changes.",
                "- When web_search_mode is not 'off', treat the supplied web_search_results as part of your information-gathering step—never claim you lack browsing ability.",
                ""
            ])
        elif not is_ask_mode:
            prompt_parts.append("If you develop a TODO plan, include it via the `ai_plan` metadata described below.")
            prompt_parts.append("")
        
        if context.get("requested_new_script"):
            prompt_parts.extend([
                "USER INTENT: The developer explicitly requested a brand-new script.",
                "- Do NOT continue editing previously opened files or tabs unless the user references them explicitly.",
                "- Propose a sensible new filename (include directories if helpful) and include a `create_file` operation with the full script.",
                "- CRITICAL: You MUST include the create_file operation in file_operations - do not just describe the file.",
                "- Explain briefly why the new file is necessary before presenting the code.",
                ""
            ])

        # Always show metadata format instructions, but emphasize different rules for ASK mode
        if is_ask_mode:
            # In ASK mode, show metadata format but emphasize that only ai_plan is allowed
            prompt_parts.extend([
                "Metadata format (you MAY include ai_plan to show your thinking, but NEVER include file_operations):",
                "```json",
                "{",
                '  "ai_plan": {',
                '    "summary": "One-sentence summary of your approach",',
                '    "tasks": [',
                '      {',
                '        "id": "task-1",',
                '        "title": "Describe the step",',
                '        "status": "pending"',
                '      }',
                '    ]',
                '  }',
                '  // NOTE: file_operations are FORBIDDEN in ASK mode',
                "}",
                "```",
                "",
            ])
        else:
            prompt_parts.extend(self.METADATA_FORMAT_LINES)
            prompt_parts.extend([
                "Always provide practical, working code examples. Be concise but thorough.",
                "",
                "ABSOLUTE RULES:",
                "- 🚨 CRITICAL: If the user asks to create, make, write, or generate ANY file, you MUST include a create_file operation in file_operations. Never just show code in a code block—actually create the file via file_operations.",
                "",
                "💾 MEMORY MANAGEMENT - SAVING USER INFORMATION:",
                "",
                "🚨 CRITICAL DISTINCTION:",
                "- If user asks to REMEMBER, SAVE, or KEEP IN MIND something about THEMSELVES or their PREFERENCES → Use save_memory tool",
                "- If user asks to SAVE information/data/notes/content TO A FILE → Use create_file operation in file_operations",
                "",
                "When the user asks you to REMEMBER, SAVE, or KEEP IN MIND something about them or their preferences:",
                "- IMMEDIATELY use the save_memory tool to store this information permanently",
                "- Examples of when to use save_memory (PERSONAL INFORMATION):",
                "  * 'Remember that my name is John' → <tool_call name=\"save_memory\" args='{\"content\": \"User's name is John\"}' />",
                "  * 'Save that I prefer dark mode' → <tool_call name=\"save_memory\" args='{\"content\": \"User prefers dark mode\"}' />",
                "  * 'Keep in mind I'm a Python developer' → <tool_call name=\"save_memory\" args='{\"content\": \"User is a Python developer\"}' />",
                "  * 'Remember I like Thai food' → <tool_call name=\"save_memory\" args='{\"content\": \"User likes Thai food\"}' />",
                "  * 'Save this: I work at Google' → <tool_call name=\"save_memory\" args='{\"content\": \"User works at Google\"}' />",
                "  * 'Remember my favorite color is blue' → <tool_call name=\"save_memory\" args='{\"content\": \"User's favorite color is blue\"}' />",
                "- The memory content should be clear, concise, and in third person (e.g., 'User's name is John' not 'My name is John')",
                "- After saving, confirm to the user that you've saved it",
                "- DO NOT use save_memory for code, files, or technical documentation - use file operations for those",
                "- DO use save_memory for personal preferences, facts about the user, or information they explicitly want you to remember",
                "- If the user says 'remember this' or 'save this' without context, ask what they want you to remember",
                "",
                "- 🚨 CRITICAL: If the user asks to save, store, or save information/data/notes/content TO A FILE, you MUST create a file with that information using a create_file operation in file_operations.",
                "- 🚨 CRITICAL: When saving information TO A FILE, choose an appropriate filename (e.g., notes.txt, information.md, data.json, summary.txt) based on the content type and user's request.",
                "- 🚨 CRITICAL: If the user asks to modify, update, change, or fix ANY code, you MUST include edit_file operations in file_operations. Never just show code—include the actual file_operations.",
                "- 🚨 CRITICAL: If the user asks to delete, remove, or delete ANY file(s), you MUST include delete_file operations in file_operations. NEVER use edit_file with empty content to delete files—ALWAYS use delete_file type. The delete_file operation only requires the 'path' field, not 'content'.",
                "- Example: If user says 'delete test.py', use: {\"type\": \"delete_file\", \"path\": \"test.py\"} - NOT edit_file with empty content.",
                "- Example: If user says 'save this information' or 'save these notes', create a file like: {\"type\": \"create_file\", \"path\": \"notes.txt\", \"content\": \"[the information to save]\"}",
                "- If the user mentions files via @filename or provides a path, open those files (content is in CONTEXT) and edit them via file_operations.",
                "- Do NOT reply with generic statements like 'we need to inspect the file' or 'we need to access the file'—assume the IDE has already provided the relevant file contents in CONTEXT and operate directly on that content.",
                "- On follow-up requests like \"change it\" or \"update that code\", assume the target file is the current active_file or default_target_file from context and still produce concrete file_operations.",
                "- Do not stop after describing a plan; always include the updated file content in file_operations so the IDE can apply the change.",
                "- Keep natural-language responses short; rely on file_operations to convey the actual modifications.",
                "- NEVER respond with just code blocks when the user asks to create or modify files—ALWAYS include file_operations.",
                "- When web_search_mode is not 'off', do NOT reply with generic suggestions to visit websites; instead, read the provided web_search_results and answer the user's question as concretely as possible using those results.",
                '- When web_search_mode is not "off", you HAVE internet access through the web_search tool. Statements like "I cannot browse the internet" or "I cannot access external information" are FALSE. You DO have access to web_search_results and can use the web_search tool anytime; never claim that you lack browsing or external access.',
                "- 🚫 NEVER write code to access the internet (requests.get(), urllib, httpx, etc.). If internet information is needed, use the web_search MCP tool instead.",
                "- When asked for current prices, news, or any internet data, use <tool_call name=\"web_search\" ... /> - do NOT generate scraping code.",
                ""
            ])


        web_search_mode = (context.get("web_search_mode") or "off").lower()
        if web_search_mode in ("browser_tab", "google_chrome", "auto"):
            mode_label = "auto-triggered" if web_search_mode == "auto" else web_search_mode
            prompt_parts.extend([
                f"WEB SEARCH ACCESS ENABLED (mode: {mode_label}):",
                "",
                "🚨 CRITICAL RULES - READ CAREFULLY:",
                "",
                "1. YOU HAVE INTERNET ACCESS:",
                "   - You HAVE internet access through the web_search MCP tool. Use it whenever you need current information.",
                "   - Live DuckDuckGo search results are provided; use them for up-to-date facts.",
                "   - NEVER say 'I cannot access the internet' or 'I don't have internet access' - this is FALSE.",
                "",
                "2. WHEN WEB SEARCH RESULTS ARE PROVIDED BELOW:",
                "   - ⚠️ ABSOLUTE REQUIREMENT: You MUST use ONLY the information from web_search_results shown below.",
                "   - ⚠️ FORBIDDEN: DO NOT use ANY prices, numbers, facts, or data from your training data - it is OUTDATED.",
                "   - ⚠️ FORBIDDEN: DO NOT say 'based on my knowledge' or 'as of my training' - use the search results instead.",
                "   - ⚠️ FORBIDDEN: DO NOT say 'I don't have access to current information' - the search results ARE current information.",
                "   - ⚠️ FORBIDDEN: DO NOT ignore the search results and use your training data instead.",
                "   - ✅ REQUIRED: Extract facts, prices, numbers DIRECTLY from the search results below.",
                "   - ✅ REQUIRED: Cite the source (site or URL) when referencing a result.",
                "",
                "3. WHEN WEB SEARCH RESULTS ARE NOT PROVIDED BUT MODE IS ENABLED:",
                "   - Use the web_search tool to get current information: <tool_call name=\"web_search\" args='{\"query\": \"your search query\"}' />",
                "   - Do not ask the user to search - you can do it yourself.",
                "   - For questions about current prices, news, or real-time data, automatically use web_search.",
                "",
                "4. ABSOLUTE PROHIBITIONS:",
                "   - 🚫 NEVER write Python code with requests, urllib, httpx, or any HTTP library to fetch internet data.",
                "   - 🚫 NEVER write code like: requests.get(url), urllib.request.urlopen(), or any web scraping code.",
                "   - 🚫 NEVER tell the user to \"search online\" or \"check a website\" - use the web_search tool yourself.",
                "   - 🚫 NEVER say 'no web-search results were provided' if results are shown below.",
                "",
                "5. FOR PRICE/ASSET QUERIES:",
                "   - Use web_search to get the latest price and respond with that value.",
                "   - For CRYPTO: Include the currency symbol and USD (e.g., 'Bitcoin (BTC) is $92,641 USD').",
                "   - For FOREX: Always include both currencies in the pair (e.g., 'EUR/USD 1.05').",
                "   - For STOCKS: Include the ticker symbol and price (e.g., 'AAPL is $150.25').",
                "   - Include a brief note that prices change quickly.",
                "   - If search results show a price/rate, use THAT price/rate, not your training data.",
                ""
            ])

            # Check for MCP web search results (preferred) or direct results
            mcp_results = context.get("web_search_results_mcp")
            direct_results = context.get("web_search_results") or []
            
            if mcp_results:
                # MCP tool returned formatted results
                prompt_parts.append("")
                prompt_parts.append("=" * 80)
                prompt_parts.append("🚨 WEB SEARCH RESULTS - USE ONLY THESE, IGNORE YOUR TRAINING DATA 🚨")
                prompt_parts.append("=" * 80)
                prompt_parts.append("")
                prompt_parts.append("⚠️ IMPORTANT: The information below is from a LIVE web search. Use ONLY this data.")
                prompt_parts.append("⚠️ DO NOT use prices or data from your training knowledge - it is outdated.")
                prompt_parts.append("⚠️ Extract prices and facts DIRECTLY from the results below.")
                prompt_parts.append("")
                prompt_parts.append(mcp_results)
                prompt_parts.append("")
                prompt_parts.append("=" * 80)
                prompt_parts.append("")
                prompt_parts.append("🚨 CRITICAL INSTRUCTIONS FOR WEB SEARCH RESULTS 🚨:")
                prompt_parts.append("")
                prompt_parts.append("⚠️ ABSOLUTE REQUIREMENT: You MUST use ONLY the information from the web search results shown above.")
                prompt_parts.append("⚠️ DO NOT use any prices, numbers, or data from your training data - it is OUTDATED.")
                prompt_parts.append("⚠️ IGNORE any knowledge you have about current prices - ONLY use the prices shown in the search results above.")
                prompt_parts.append("")
                prompt_parts.append("🚫 FORBIDDEN PRICES: The prices $23,433, $23,400, $23,000, or any price around $23,000 are WRONG and OUTDATED.")
                prompt_parts.append("🚫 DO NOT use $23,433, $23,400, $23,000, or similar prices - these are from your training data and are INCORRECT.")
                prompt_parts.append("🚫 If you are about to write $23,433 or similar, STOP - that is wrong. Look at the search results above instead.")
                prompt_parts.append("")
                prompt_parts.append("- Extract specific facts, numbers, prices, or data DIRECTLY from the search results above.")
                prompt_parts.append("")
                prompt_parts.append("FOR CRYPTO PRICE QUERIES:")
                prompt_parts.append("- SCAN the search results above line by line and find the price value mentioned there.")
                prompt_parts.append("- Look for dollar amounts like $92,641, $90,000+, $95,000, $80,000+, etc. in the search results.")
                prompt_parts.append("- Use the HIGHEST/MOST RECENT price value you find in the search results.")
                prompt_parts.append("- Copy the price EXACTLY as shown in the search results (e.g., if results show '$92,641.37', use that EXACT value).")
                prompt_parts.append("- Always specify the currency (e.g., 'Bitcoin (BTC) is $92,641 USD').")
                prompt_parts.append("")
                prompt_parts.append("FOR FOREX PRICE QUERIES:")
                prompt_parts.append("- Look for exchange rates like 1.05, 1.1234, 0.85, 150.25, etc. in the search results.")
                prompt_parts.append("- Exchange rates are typically shown as 'EUR/USD 1.05' or '1.05 EUR/USD' format.")
                prompt_parts.append("- Extract the rate value (number with 2-5 decimal places) and the currency pair.")
                prompt_parts.append("- Use the MOST RECENT rate value you find in the search results.")
                prompt_parts.append("- CRITICAL: Always include BOTH currencies in the pair (e.g., 'EUR/USD 1.05' not just '1.05').")
                prompt_parts.append("")
                prompt_parts.append("FOR STOCK PRICE QUERIES:")
                prompt_parts.append("- Look for dollar amounts like $150.25, $1,234.56, etc. in the search results.")
                prompt_parts.append("- Extract the price EXACTLY as shown (including decimals).")
                prompt_parts.append("")
                prompt_parts.append("GENERAL:")
                prompt_parts.append("- If you cannot find a price/rate in the search results, say 'Price/Rate information not found in search results' - DO NOT make up a price.")
                prompt_parts.append("- If you see prices like $92,641, $90,000+, or similar HIGH values in the search results, use THOSE, NOT $23,433.")
                prompt_parts.append("")
                # Only restrict plans in ASK mode - allow plans in agent/plan modes
                is_ask_mode_for_web = (not is_agent_mode) and is_ask_mode
                if is_ask_mode_for_web:
                    prompt_parts.append("🚫 DO NOT GENERATE ANY OF THE FOLLOWING (ASK MODE - READ ONLY):")
                    prompt_parts.append("- Do NOT generate TODO lists, AI plans, step-by-step breakdowns, or status messages - just provide the answer.")
                    prompt_parts.append("- Do NOT include 'Verification', 'Verification Report', 'Task Report', 'Task Status Update', or 'Remaining Risks' sections.")
                    prompt_parts.append("- Do NOT say 'I verified' or 'I have verified' - just provide the answer directly.")
                    prompt_parts.append("- Do NOT list tasks like 'Verify the price information' or 'Get the latest price' - these are not answers.")
                    prompt_parts.append("- Do NOT say 'we will use', 'we will obtain', 'I can display', or 'I can show' - you already have the results, so provide the answer NOW.")
                    prompt_parts.append("- Do NOT include 'AI PLAN' sections, 'COMPLETED' status indicators, or any planning metadata in your response.")
                    prompt_parts.append("- Do NOT say 'please let me know if you'd like additional information' - just provide the complete answer.")
                    prompt_parts.append("- Do NOT say that no results were provided - they are shown above.")
                    prompt_parts.append("")
                    prompt_parts.append("✅ YOUR RESPONSE SHOULD BE:")
                    prompt_parts.append("- A direct answer to the user's question using the search results.")
                    prompt_parts.append("- For price queries: 'The current price of [asset] is $[EXACT_PRICE_FROM_RESULTS] USD'")
                    prompt_parts.append("- Brief and to the point - no verification steps, no task lists, no reports.")
                    prompt_parts.append("")
                else:
                    # In agent/plan modes, web search results should be used as part of the planning process
                    prompt_parts.append("✅ WHEN USING WEB SEARCH RESULTS IN AGENT/PLAN MODE:")
                    prompt_parts.append("- Use the web search results as part of your information-gathering phase.")
                    prompt_parts.append("- Include web search findings in your ai_plan tasks when relevant.")
                    prompt_parts.append("- You can still generate ai_plan metadata to structure your work, even when using web search results.")
                    prompt_parts.append("- Break down complex tasks that involve web research into clear steps in your plan.")
                    prompt_parts.append("- Extract facts, prices, and data from the search results and incorporate them into your plan execution.")
                    prompt_parts.append("")
            elif direct_results:
                # Direct search results (fallback)
                prompt_parts.append("")
                prompt_parts.append("=" * 80)
                prompt_parts.append("🚨 WEB SEARCH RESULTS - USE ONLY THESE, IGNORE YOUR TRAINING DATA 🚨")
                prompt_parts.append("=" * 80)
                prompt_parts.append("")
                prompt_parts.append("⚠️ IMPORTANT: The information below is from a LIVE web search. Use ONLY this data.")
                prompt_parts.append("⚠️ DO NOT use prices or data from your training knowledge - it is outdated.")
                prompt_parts.append("⚠️ Extract prices and facts DIRECTLY from the results below.")
                prompt_parts.append("")
                for idx, result in enumerate(direct_results[:10], start=1):
                    title = truncate_text(result.get("title") or "Untitled result", 140)
                    snippet = truncate_text(result.get("snippet") or result.get("body") or result.get("description") or "", 300)
                    url = truncate_text(result.get("url") or result.get("href") or result.get("source") or "", 180)
                    prompt_parts.append(f"Result {idx}:")
                    prompt_parts.append(f"  Title: {title}")
                    prompt_parts.append(f"  URL: {url}")
                    prompt_parts.append(f"  Content: {snippet}")
                    prompt_parts.append("")
                prompt_parts.append("=" * 80)
                prompt_parts.append("")
                prompt_parts.append("🚨 CRITICAL INSTRUCTIONS FOR WEB SEARCH RESULTS 🚨:")
                prompt_parts.append("")
                prompt_parts.append("⚠️ ABSOLUTE REQUIREMENT: You MUST use ONLY the information from the web search results shown above.")
                prompt_parts.append("⚠️ DO NOT use any prices, numbers, or data from your training data - it is OUTDATED.")
                prompt_parts.append("⚠️ IGNORE any knowledge you have about current prices - ONLY use the prices shown in the search results above.")
                prompt_parts.append("")
                prompt_parts.append("🚫 FORBIDDEN PRICES: The prices $23,433, $23,400, $23,000, or any price around $23,000 are WRONG and OUTDATED.")
                prompt_parts.append("🚫 DO NOT use $23,433, $23,400, $23,000, or similar prices - these are from your training data and are INCORRECT.")
                prompt_parts.append("🚫 If you are about to write $23,433 or similar, STOP - that is wrong. Look at the search results above instead.")
                prompt_parts.append("")
                prompt_parts.append("- Extract specific facts, numbers, prices, or data DIRECTLY from the search results above.")
                prompt_parts.append("")
                prompt_parts.append("FOR CRYPTO PRICE QUERIES:")
                prompt_parts.append("- SCAN the search results above line by line and find the price value mentioned there.")
                prompt_parts.append("- Look for dollar amounts like $92,641, $90,000+, $95,000, $80,000+, etc. in the search results.")
                prompt_parts.append("- Use the HIGHEST/MOST RECENT price value you find in the search results.")
                prompt_parts.append("- Copy the price EXACTLY as shown in the search results (e.g., if results show '$92,641.37', use that EXACT value).")
                prompt_parts.append("- Always specify the currency (e.g., 'Bitcoin (BTC) is $92,641 USD').")
                prompt_parts.append("")
                prompt_parts.append("FOR FOREX PRICE QUERIES:")
                prompt_parts.append("- Look for exchange rates like 1.05, 1.1234, 0.85, 150.25, etc. in the search results.")
                prompt_parts.append("- Exchange rates are typically shown as 'EUR/USD 1.05' or '1.05 EUR/USD' format.")
                prompt_parts.append("- Extract the rate value (number with 2-5 decimal places) and the currency pair.")
                prompt_parts.append("- Use the MOST RECENT rate value you find in the search results.")
                prompt_parts.append("- CRITICAL: Always include BOTH currencies in the pair (e.g., 'EUR/USD 1.05' not just '1.05').")
                prompt_parts.append("")
                prompt_parts.append("FOR STOCK PRICE QUERIES:")
                prompt_parts.append("- Look for dollar amounts like $150.25, $1,234.56, etc. in the search results.")
                prompt_parts.append("- Extract the price EXACTLY as shown (including decimals).")
                prompt_parts.append("")
                prompt_parts.append("GENERAL:")
                prompt_parts.append("- If you cannot find a price/rate in the search results, say 'Price/Rate information not found in search results' - DO NOT make up a price.")
                prompt_parts.append("- If you see prices like $92,641, $90,000+, or similar HIGH values in the search results, use THOSE, NOT $23,433.")
                prompt_parts.append("")
                # Only restrict plans in ASK mode - allow plans in agent/plan modes
                is_ask_mode_for_web = (not is_agent_mode) and is_ask_mode
                if is_ask_mode_for_web:
                    prompt_parts.append("🚫 DO NOT GENERATE ANY OF THE FOLLOWING (ASK MODE - READ ONLY):")
                    prompt_parts.append("- Do NOT generate TODO lists, AI plans, step-by-step breakdowns, or status messages - just provide the answer.")
                    prompt_parts.append("- Do NOT include 'Verification', 'Verification Report', 'Task Report', 'Task Status Update', or 'Remaining Risks' sections.")
                    prompt_parts.append("- Do NOT say 'I verified' or 'I have verified' - just provide the answer directly.")
                    prompt_parts.append("- Do NOT list tasks like 'Verify the price information' or 'Get the latest price' - these are not answers.")
                    prompt_parts.append("- Do NOT say 'we will use', 'we will obtain', 'I can display', or 'I can show' - you already have the results, so provide the answer NOW.")
                    prompt_parts.append("- Do NOT include 'AI PLAN' sections, 'COMPLETED' status indicators, or any planning metadata in your response.")
                    prompt_parts.append("- Do NOT say 'please let me know if you'd like additional information' - just provide the complete answer.")
                    prompt_parts.append("- Do NOT say that no results were provided - they are shown above.")
                    prompt_parts.append("")
                    prompt_parts.append("✅ YOUR RESPONSE SHOULD BE:")
                    prompt_parts.append("- A direct answer to the user's question using the search results.")
                    prompt_parts.append("- For price queries: 'The current price of [asset] is $[EXACT_PRICE_FROM_RESULTS] USD'")
                    prompt_parts.append("- Brief and to the point - no verification steps, no task lists, no reports.")
                    prompt_parts.append("")
                else:
                    # In agent/plan modes, web search results should be used as part of the planning process
                    prompt_parts.append("✅ WHEN USING WEB SEARCH RESULTS IN AGENT/PLAN MODE:")
                    prompt_parts.append("- Use the web search results as part of your information-gathering phase.")
                    prompt_parts.append("- Include web search findings in your ai_plan tasks when relevant.")
                    prompt_parts.append("- You can still generate ai_plan metadata to structure your work, even when using web search results.")
                    prompt_parts.append("- Break down complex tasks that involve web research into clear steps in your plan.")
                    prompt_parts.append("- Extract facts, prices, and data from the search results and incorporate them into your plan execution.")
                    prompt_parts.append("")
            elif context.get("web_search_error"):
                error_msg = truncate_text(context['web_search_error'], 160)
                prompt_parts.append(f"Note: A web search was attempted but encountered an error: {error_msg}")
                prompt_parts.append("You should still respond to the user's question. If you need current information, you can try using the web_search MCP tool in your response.")
                if self.is_mcp_enabled():
                    prompt_parts.append("You can use the web_search MCP tool by including a tool call in your response if you need to search the web.")
                prompt_parts.append("Do not let the search error prevent you from providing a helpful response.")
            else:
                if web_search_mode == "auto":
                    prompt_parts.append("Note: Web search was attempted but no results were returned.")
                    if self.is_mcp_enabled():
                        prompt_parts.append("You can use the web_search MCP tool to perform searches if needed.")
                else:
                    # When browser_tab or google_chrome mode is enabled but no search was performed,
                    # inform the AI that web search is available for use
                    if web_search_mode in ("browser_tab", "google_chrome"):
                        prompt_parts.append("Web search mode is enabled. You can use the web_search MCP tool if you need current information, real-time data, or any internet content.")
                        if self.is_mcp_enabled():
                            prompt_parts.append("Use the web_search tool by including a tool call in your response when you need to search the web.")
                    else:
                        prompt_parts.append("No web search was performed for this prompt.")
                        if self.is_mcp_enabled() and self._detect_web_search_needed(message, web_search_mode):
                            prompt_parts.append("Note: This query might benefit from web search. You can use the web_search MCP tool.")

            prompt_parts.append("")
        
        # Add context if available
        if context:
            prompt_parts.append("CONTEXT:")
            if context.get("active_file"):
                prompt_parts.append(f"Active file: {context['active_file']}")
                active_content = context.get("active_file_content") or ""
                if active_content:
                    # Show up to 5000 characters so the model can actually edit the file,
                    # and only add an ellipsis if we truly truncated the content.
                    max_active_preview = 5000
                    preview = active_content[:max_active_preview]
                    suffix = "..." if len(active_content) > max_active_preview else ""
                    prompt_parts.append(f"Active file content:\n{preview}{suffix}")
            
            if context.get("open_files"):
                prompt_parts.append(f"\nOpen files ({len(context['open_files'])}):")
                for file in context["open_files"]:
                    status = "ACTIVE" if file.get("is_active") else "open"
                    prompt_parts.append(f"  [{status}] {file['path']} ({file.get('language', 'unknown')})")
                    file_content = file.get("content") or ""
                    if file_content and len(file_content) < 2000:
                        max_open_preview = 800
                        preview = file_content[:max_open_preview]
                        suffix = "..." if len(file_content) > max_open_preview else ""
                        prompt_parts.append(f"    Content: {preview}{suffix}")
            
            if context.get("mentioned_files"):
                prompt_parts.append(f"\nMentioned files (@mentions):")
                for file in context["mentioned_files"]:
                    prompt_parts.append(f"  - {file.get('path', file)}")
                    file_content = (file.get("content") if isinstance(file, dict) else None) or ""
                    if file_content:
                        max_mention_preview = 2000
                        preview = file_content[:max_mention_preview]
                        suffix = "..." if len(file_content) > max_mention_preview else ""
                        prompt_parts.append(f"    Content: {preview}{suffix}")
            
            if context.get("file_tree_structure"):
                prompt_parts.append(f"\nProject structure available (use @filename to reference files)")
                # Show top-level structure
                top_level = [item["name"] for item in context["file_tree_structure"][:10]]
                if top_level:
                    prompt_parts.append(f"  Top files/dirs: {', '.join(top_level)}")
            
            if context.get("composer_mode"):
                prompt_parts.append(f"\nMode: AGENT MODE - You can create, edit, and delete files.")
            
            prompt_parts.append("")
        
        # Add conversation history
        if history:
            prompt_parts.append("CONVERSATION HISTORY:")
            for msg in history[-5:]:  # Last 5 messages
                role = "User" if msg["role"] == "user" else "Assistant"
                prompt_parts.append(f"{role}: {msg['content']}")
            prompt_parts.append("")
        
        # Add current message
        # Add explicit image detection instruction if images are present
        if images and len(images) > 0:
            message_lower = (message or "").lower().strip()
            image_keywords = ['image', 'picture', 'photo', 'screenshot', 'what is', "what's", 'identify', 'what does', 'describe', 'show', 'see', 'what', 'this']
            asks_about_image = any(keyword in message_lower for keyword in image_keywords) if message_lower else False
            
            # If message is empty or very short, assume user wants image identified
            # Also trigger if message contains image-related keywords
            if not message_lower or len(message_lower) < 10 or asks_about_image:
                query = message.strip() if message.strip() else "what is in this image?"
                prompt_parts.extend([
                    "",
                    "🚨🚨🚨 AUTOMATIC IMAGE DETECTION TRIGGERED 🚨🚨🚨",
                    "",
                    f"Images are attached ({len(images)} image(s)).",
                    "The user's message is empty or asks about the image.",
                    "YOU MUST call identify_image tool IMMEDIATELY before responding.",
                    "",
                    "REQUIRED ACTION: Include this tool call in your response:",
                    f'<tool_call name="identify_image" args=\'{{"query": "{query}"}}\' />',
                    "",
                    "DO NOT ask for image data - it's already available!",
                    "DO NOT say 'no image was provided' - images ARE attached!",
                    "DO NOT say 'please upload the image' - images ARE already uploaded!",
                    "",
                    "=" * 80,
                    "",
                ])
        
        prompt_parts.append(f"USER REQUEST: {message}")
        prompt_parts.append("")
        
        # Add final reminder about directory scanning if the message seems to request it
        message_lower = (message or "").lower()
        directory_scan_keywords = ["scan", "directory", "list files", "examine", "project structure", "show directory", "what files", "directory contents"]
        if any(keyword in message_lower for keyword in directory_scan_keywords):
            prompt_parts.extend([
                "",
                "=" * 80,
                "🚨 FINAL REMINDER: The user is asking about directories/files.",
                "🚨 YOU MUST use list_directory or get_file_tree tool - DO NOT just say 'I'll scan...'",
                "🚨 Include the tool call in your response NOW: <tool_call name=\"list_directory\" args='{\"path\": \".\"}' />",
                "=" * 80,
                "",
            ])
        
        prompt_parts.append("ASSISTANT RESPONSE:")
        
        return "\n".join(prompt_parts)
    
    def _detect_new_script_request(self, text: Optional[str]) -> bool:
        if not text:
            return False
        normalized = text.lower()
        keywords = [
            "new script",
            "brand new script",
            "new file",
            "create a new script",
            "write a new script",
            "fresh script",
            "from scratch",
            "start a new",
            "start over",
            "spin up a new",
            "new module",
            "new component",
            "new service",
        ]
        if any(keyword in normalized for keyword in keywords):
            return True
        pattern = re.compile(
            r"(create|build|write|generate)\s+(?:a\s+)?(?:brand\s+new\s+|new\s+)?"
            r"(?:python|js|javascript|typescript|bash|shell|powershell|go|rust|c#|c\+\+|node|react|vue|script)?\s*script"
        )
        return bool(pattern.search(normalized))
    
    def _has_change_intent(self, text: Optional[str]) -> bool:
        """Heuristic to determine if the user is asking for code changes."""
        if not text:
            return False
        normalized = text.lower()
        change_keywords = [
            "fix",
            "update",
            "change",
            "modify",
            "refactor",
            "implement",
            "add ",
            "add\n",
            "add\t",
            "remove",
            "rewrite",
            "improve",
            "adjust",
            "patch",
            "create",
            "build",
            "generate",
            "design",
            "scaffold",
            "bootstrap",
            "prototype",
            "develop",
            "new file",
            "new files",
            "new app",
            "new script",
            "new code",
            "make a",
            "make an",
            "write a",
            "write an",
            "set up",
            "setup",
            "upgrade",
            "enhance",
            "rename",
            "delete",
            "make",
            "write",
            "put",
            "save",
        ]
        return any(keyword in normalized for keyword in change_keywords)
    
    def _is_analysis_request(self, text: Optional[str]) -> bool:
        """Detect requests that are explicitly analysis/explanation focused."""
        if not text:
            return False
        normalized = text.lower()
        analysis_keywords = [
            "explain",
            "describe",
            "walk me through",
            "what does",
            "how does",
            "summarize",
            "document",
            "comment on",
            "review this",
            "analyze",
            "understand",
        ]
        return any(keyword in normalized for keyword in analysis_keywords)
    
    def _detect_web_search_needed(self, message: str, web_search_mode: str) -> bool:
        """Detect if a query needs web search based on content"""
        if not message:
            return False
        
        # If web search is explicitly enabled (browser_tab/google_chrome), 
        # still check if the message actually needs a search
        # Don't force search for every message - let the AI decide when to use it
        # The web search capability will still be available via MCP tools
        
        # If explicitly disabled, don't auto-trigger
        if web_search_mode == "off":
            # When web search is off, never auto-trigger searches
            return False
        
        normalized = message.lower().strip()
        
        # EXCLUSION PATTERNS: UI/Interface-related queries that should NOT trigger web search
        ui_exclusion_patterns = [
            r'\bshow more info\b',
            r'\bmore info\b.*\b(icon|button|tooltip|hover|click|ui|interface|feature)\b',
            r'\b(info|information)\b.*\b(icon|button|tooltip|hover|click|ui|interface|feature|element)\b',
            r'\bhow.*\b(icon|button|tooltip|hover|click|ui|interface|feature|element)\b.*\b(work|works|function|functions)\b',
            r'\bwhat.*\b(icon|button|tooltip|hover|click|ui|interface|feature|element)\b.*\b(do|does|mean|means)\b',
            r'\b(icon|button|tooltip|hover|click|ui|interface|feature|element)\b.*\b(info|information|help|explain)\b',
            r'\bshow.*\b(tooltip|hover|info|information)\b',
            r'\b(help|explain|tell me about)\b.*\b(icon|button|tooltip|hover|ui|interface|feature|element)\b',
            r'\b(ui|interface|ui element|ui feature|user interface)\b',
            r'\b(how to use|how do i use|how does this work)\b.*\b(here|this|interface|ui|feature)\b',
        ]
        
        # Check exclusions first - if it matches UI patterns, don't trigger web search
        for pattern in ui_exclusion_patterns:
            if re.search(pattern, normalized, re.IGNORECASE):
                return False
        
        # Price/Value queries - Enhanced for forex, crypto, and stocks
        price_patterns = [
            # Crypto patterns
            r'\b(price|cost|value|worth|rate)\b.*\b(bitcoin|btc|ethereum|eth|cardano|ada|solana|sol|polkadot|dot|chainlink|link|avalanche|avax|polygon|matic|dogecoin|doge|shiba|shib|litecoin|ltc|ripple|xrp|binance|bnb|tether|usdt|usdc|stablecoin|crypto|cryptocurrency)\b',
            r'\b(bitcoin|btc|ethereum|eth|cardano|ada|solana|sol|polkadot|dot|chainlink|link|avalanche|avax|polygon|matic|dogecoin|doge|shiba|shib|litecoin|ltc|ripple|xrp|binance|bnb|tether|usdt|usdc)\b.*\b(price|cost|value|worth|rate)\b',
            # Forex patterns
            r'\b(price|rate|exchange rate|exchange|forex|fx)\b.*\b(usd|eur|gbp|jpy|aud|cad|chf|cny|nzd|sek|nok|mxn|zar|inr|krw|sgd|hkd|usd/eur|eur/usd|gbp/usd|usd/jpy|eur/gbp|aud/usd|usd/cad|forex pair)\b',
            r'\b(usd|eur|gbp|jpy|aud|cad|chf|cny|nzd|sek|nok|mxn|zar|inr|krw|sgd|hkd|usd/eur|eur/usd|gbp/usd|usd/jpy|eur/gbp|aud/usd|usd/cad)\b.*\b(price|rate|exchange rate|exchange|forex|fx)\b',
            r'\b(forex|fx|currency pair|exchange rate)\b.*\b(price|rate|value|worth)\b',
            # Stock patterns
            r'\b(price|cost|value|worth|rate|stock price|share price)\b.*\b(stock|share|equity|ticker|nasdaq|nyse|sp500|s&p)\b',
            r'\b(stock|share|equity|ticker)\b.*\b(price|cost|value|worth|rate)\b',
            # General price queries
            r'\b(current|latest|today|now|live|real-time|real time)\b.*\b(price|value|rate|exchange rate)\b',
            r'\bhow much.*\b(bitcoin|btc|ethereum|eth|stock|currency|crypto|cryptocurrency|forex|forex pair)\b',
            r'\bwhat.*\b(bitcoin|btc|ethereum|eth|forex|currency pair)\b.*\b(price|worth|value|rate)\b',
            r'\b(current|latest|live)\b.*\b(bitcoin|btc|ethereum|eth|crypto|forex|currency)\b.*\b(price|rate)\b',
        ]
        
        # Current events/news queries
        news_patterns = [
            r'\b(latest|recent|current|today|now|breaking)\b.*\b(news|update|event|happening|trend)\b',
            r'\bwhat.*\b(happening|going on|new|latest)\b',
            r'\b(when|where|who)\b.*\b(happened|occurred|announced)\b',
        ]
        
        # Real-time data queries
        realtime_patterns = [
            r'\b(weather|temperature|forecast)\b',
            r'\b(current|live|real-time|real time)\b.*\b(data|information|status)\b',
        ]
        
        # "What is X" queries that might need current info (but not UI-related)
        what_is_patterns = [
            r'\bwhat is\b.*\b(bitcoin|btc|ethereum|eth|stock|company|ceo|president)\b',
            r'\bwho is\b.*\b(current|now|today)\b',
            # Removed overly broad pattern: r'\bwho is\b.+',
            # Only match "who is" with specific entities that need current info
            r'\bwho is\b.*\b(current|now|today|president|ceo|leader|minister)\b',
        ]
        
        # General information queries that likely need internet (but not UI-related)
        general_info_patterns = [
            r'\bwhat is\b.*\b(api|service|tool|library|framework|package)\b',
            r'\bhow to\b.*\b(install|use|configure|setup|set up)\b.*\b(package|library|framework|tool|software)\b',
            r'\b(latest|new|recent|current)\b.*\b(version|release|update)\b.*\b(of|for)\b',
            r'\b(documentation|docs|tutorial|guide|example)\b.*\b(for|about|on)\b',
        ]
        
        all_patterns = price_patterns + news_patterns + realtime_patterns + what_is_patterns + general_info_patterns
        
        for pattern in all_patterns:
            if re.search(pattern, normalized, re.IGNORECASE):
                return True
        
        # Check for explicit search requests (but exclude UI-related ones)
        search_keywords = [
            "search for",
            "look up",
            "find information about",
            "what's the current",
            "what's the latest",
            "check the price",
            "get the price",
            "search online",
            "look online",
            "find online",
        ]
        
        # Only trigger if it's an explicit search AND not about UI
        if any(keyword in normalized for keyword in search_keywords):
            # Double-check it's not UI-related
            if not any(re.search(pattern, normalized, re.IGNORECASE) for pattern in ui_exclusion_patterns):
                return True
        
        return False
    
    def _detect_ai_uncertainty(self, response: str, original_message: str) -> bool:
        """Detect if AI response indicates uncertainty or lack of knowledge"""
        if not response:
            return True
        
        response_lower = response.lower()
        message_lower = original_message.lower() if original_message else ""
        
        # Patterns that indicate uncertainty
        uncertainty_patterns = [
            r'\bi don\'?t know\b',
            r'\bi\'?m not sure\b',
            r'\bi don\'?t have.*information\b',
            r'\bi cannot.*(answer|find|provide|tell)\b',
            r'\bunable to.*(answer|find|provide|tell)\b',
            r'\bcannot.*(answer|find|provide|tell)\b',
            r'\bno information available\b',
            r'\bdon\'?t have access to\b',
            r'\bmy knowledge.*doesn\'?t include\b',
            r'\bmy knowledge.*cut off\b',
            r'\bmy training data.*(doesn\'?t|does not)\b',
            r'\bi\'?m unable to\b',
            r'\boutside.*knowledge\b',
            r'\boutside.*training\b',
            r'\bneed.*search\b',
            r'\bsearch.*internet\b',
            r'\bsearch.*web\b',
            r'\bcheck.*online\b',
            r'\blook.*up.*online\b',
            r'\bfind.*online\b',
            r'\bverify.*online\b',
            r'\bi\'?m not.*able\b',
            r'\blimited.*information\b',
            r'\bdon\'?t have.*access\b',
            r'\bdoesn\'?t.*have.*information\b',
            r'\bsorry.*don\'?t know\b',
            r'\bsorry.*cannot\b',
            r'\bunfortunately.*don\'?t\b',
            r'\bunfortunately.*cannot\b',
            r'\bi don\'?t.*have.*current\b',
            r'\bi don\'?t.*have.*latest\b',
            r'\bmy.*knowledge.*up.*to\b',
            r'\btraining.*data.*up.*to\b',
            r'\bsearch results.*did not provide\b',
            r'\bsearch results.*no relevant\b',
            r'\bcouldn\'?t find.*search results\b',
            r'\bno relevant information.*search results\b',
        ]
        
        # Check for uncertainty indicators
        for pattern in uncertainty_patterns:
            if re.search(pattern, response_lower, re.IGNORECASE):
                return True
        
        # Check if response is very short and doesn't answer the question
        # This is a heuristic: if the response is very short and the question seems substantive
        if len(response.strip()) < 100 and len(message_lower) > 20:
            # Check if response contains question-like phrases (often indicates uncertainty)
            question_indicators = [
                'maybe', 'perhaps', 'might', 'could', 'possibly',
                'not certain', 'uncertain', 'unclear'
            ]
            if any(indicator in response_lower for indicator in question_indicators):
                return True
        
        # Check if response is mostly apologies or disclaimers
        apology_phrases = [
            'sorry', 'apologize', 'regret', 'unfortunately'
        ]
        if any(phrase in response_lower for phrase in apology_phrases):
            # If response starts with apology and is short, likely uncertain
            first_sentence = response.split('.')[0].lower() if '.' in response else response.lower()
            if any(phrase in first_sentence for phrase in apology_phrases) and len(response.strip()) < 200:
                return True
        
        return False
    
    def _parse_web_search_results_text(self, raw_text: str) -> List[Dict[str, str]]:
        """Best-effort conversion of MCP web_search text output into structured results."""
        if not raw_text:
            return []
        structured: List[Dict[str, str]] = []
        text = raw_text.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
                items = data["results"]
            elif isinstance(data, list):
                items = data
            else:
                items = []
            for item in items:
                if isinstance(item, dict):
                    structured.append({
                        "title": str(item.get("title") or "").strip(),
                        "url": str(item.get("url") or item.get("link") or item.get("href") or "").strip(),
                        "snippet": str(item.get("snippet") or item.get("description") or item.get("body") or "").strip(),
                        "source": str(item.get("source") or item.get("host") or item.get("hostname") or "").strip(),
                    })
        except Exception:
            pass
        if structured:
            return structured
        
        # Fallback: parse simple bullet/numbered lines.
        current: Dict[str, str] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower().startswith(("title:", "result ", "- ")):
                if current:
                    structured.append(current)
                    current = {}
                stripped = stripped.lstrip("- ").strip()
                if stripped.lower().startswith("title:"):
                    current["title"] = stripped.split(":", 1)[1].strip()
                else:
                    current["title"] = stripped
                continue
            if stripped.lower().startswith("url:"):
                current["url"] = stripped.split(":", 1)[1].strip()
                continue
            if stripped.lower().startswith("source:"):
                current["source"] = stripped.split(":", 1)[1].strip()
                continue
            snippet = current.get("snippet", "")
            current["snippet"] = (snippet + " " + stripped).strip()
        if current:
            structured.append(current)
        
        # Ensure at least minimal info
        cleaned = []
        for item in structured:
            if any(item.get(k) for k in ("title", "snippet", "url")):
                cleaned.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                    "source": item.get("source", ""),
                })
        return cleaned

    def _get_structured_web_results(self, context: Dict[str, Any]) -> List[Dict[str, str]]:
        """Ensure we always work with a list of structured web search results."""
        results = context.get("web_search_results")
        if isinstance(results, dict):
            results = [results]
        if not isinstance(results, list):
            return []
        structured: List[Dict[str, str]] = []
        for item in results:
            if isinstance(item, dict):
                structured.append({
                    "title": str(item.get("title") or "").strip(),
                    "url": str(item.get("url") or "").strip(),
                    "snippet": str(item.get("snippet") or "").strip(),
                    "source": str(item.get("source") or "").strip(),
                })
        return structured

    def _build_answer_from_web_results(
        self,
        message: str,
        structured_results: List[Dict[str, str]]
    ) -> Optional[str]:
        """Generate a direct answer from structured search results."""
        if not structured_results:
            return None
        query = (message or "").strip()
        best = None
        for result in structured_results:
            snippet = (result.get("snippet") or "").strip()
            if snippet:
                best = result
                break
            if not best and (result.get("title") or result.get("url")):
                best = result
        if not best:
            return None

        snippet = (best.get("snippet") or "").strip()
        if not snippet:
            snippet = (best.get("title") or "").strip()
        if not snippet:
            return None
        snippet = snippet.replace('\n', ' ').strip()
        if len(snippet.split('. ')) > 1:
            snippet = snippet.split('. ')[0].strip()

        source = (best.get("source") or "").strip()
        url = (best.get("url") or "").strip()
        if url and not source:
            parsed = re.sub(r'^https?://(www\.)?', '', url).split('/')[0]
            source = parsed

        answer_parts = [snippet]
        if source:
            if url:
                answer_parts.append(f"Source: {source} ({url})")
            else:
                answer_parts.append(f"Source: {source}")
        elif url:
            answer_parts.append(f"Source: {url}")

        if query and query.lower() not in snippet.lower():
            answer_parts.insert(0, f"Query: {query}")

        return "\n\n".join(part for part in answer_parts if part)
    
    def _build_no_answer_response(
        self,
        query: str,
        web_search_available: bool,
        search_attempted: bool,
        search_results_present: bool
    ) -> str:
        """Create a safe fallback response when no reliable information is available."""
        normalized_query = (query or "").strip('" ') or "this request"
        normalized_query = normalized_query.replace('\n', ' ')[:160]
        quoted_query = f"“{normalized_query}”"
        
        if web_search_available:
            if search_attempted:
                if search_results_present:
                    return (
                        f"I searched the web for {quoted_query}, but the available sources didn't provide a reliable answer. "
                        "Please share more context or specify another query so I can keep looking."
                    )
                return (
                    f"I attempted to search the web for {quoted_query}, but couldn't retrieve any trustworthy results. "
                    "Try rephrasing the request or provide more details so I can search again."
                )
            return (
                f"I don't have enough information about {quoted_query} yet. "
                "Please allow me to run a web search (browser tab must stay enabled) or provide more context."
            )
        
        return (
            f"I don't have reliable information about {quoted_query}. "
            "Enable the browser tab or provide additional details if you'd like me to search the internet."
        )
    
    def _extract_search_query(self, message: str) -> str:
        """Extract or optimize search query from user message"""
        # Remove common prefixes that don't help search
        normalized = message.strip()
        
        # Remove question words at start
        question_prefixes = [
            "what is the",
            "what's the",
            "what is",
            "what's",
            "tell me the",
            "show me the",
            "get me the",
            "find the",
            "search for",
            "look up",
        ]
        
        for prefix in question_prefixes:
            if normalized.lower().startswith(prefix):
                normalized = normalized[len(prefix):].strip()
                break
        
        # Remove trailing question marks and common phrases
        normalized = normalized.rstrip("?")
        normalized = re.sub(r'\b(please|can you|could you|would you)\b', '', normalized, flags=re.IGNORECASE)
        
        # Optimize for price queries - add "current price" or "live price" if it's a price query
        normalized_lower = normalized.lower()
        price_keywords = ['price', 'rate', 'exchange rate', 'forex', 'crypto', 'bitcoin', 'btc', 'ethereum', 'eth', 
                         'usd', 'eur', 'gbp', 'jpy', 'currency', 'stock', 'forex pair']
        is_price_query = any(keyword in normalized_lower for keyword in price_keywords)
        
        if is_price_query:
            # Add "current price" or "live price" to improve search results
            if 'current' not in normalized_lower and 'live' not in normalized_lower and 'latest' not in normalized_lower:
                # Check if it's forex (currency pair)
                forex_pattern = r'\b(usd|eur|gbp|jpy|aud|cad|chf|cny|nzd|sek|nok|mxn|zar|inr|krw|sgd|hkd)\s*[/-]\s*(usd|eur|gbp|jpy|aud|cad|chf|cny|nzd|sek|nok|mxn|zar|inr|krw|sgd|hkd)\b'
                if re.search(forex_pattern, normalized_lower):
                    normalized = f"{normalized} current exchange rate"
                # Check if it's crypto
                elif any(crypto in normalized_lower for crypto in ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'cryptocurrency']):
                    normalized = f"{normalized} current price"
                # General price query
                else:
                    normalized = f"{normalized} current price"
        
        return normalized.strip() or message.strip()
    
    def _is_agent_context(self, context: Dict[str, Any]) -> bool:
        if not context:
            return False
        mode_value = (context.get("mode") or "").lower()
        chat_mode_value = (context.get("chat_mode") or "").lower()
        if context.get("composer_mode"):
            return True
        return mode_value in ("agent", "plan") or chat_mode_value in ("agent", "plan")
    
    def _is_ask_context(self, context: Dict[str, Any]) -> bool:
        """Check if the current context is in ASK (read-only) mode"""
        if not context:
            return False
        if context.get("composer_mode"):
            return False
        mode_value = (context.get("mode") or "").lower()
        chat_mode_value = (context.get("chat_mode") or "").lower()
        return mode_value == "ask" or chat_mode_value == "ask"
    
    def _is_plan_context(self, context: Dict[str, Any]) -> bool:
        """Check if the current context is in PLAN mode"""
        if not context:
            return False
        if context.get("composer_mode"):
            return True  # Composer mode acts like agent/plan mode
        mode_value = (context.get("mode") or "").lower()
        chat_mode_value = (context.get("chat_mode") or "").lower()
        return mode_value == "plan" or chat_mode_value == "plan"
    
    @staticmethod
    def _is_browser_search_enabled(web_search_mode: str) -> bool:
        """Browser tab search is only available when explicitly enabled."""
        normalized = (web_search_mode or "").lower()
        return normalized in ("browser_tab", "google_chrome")
    
    @staticmethod
    def _browser_disabled_response() -> str:
        """Message shown when search is required but browser tab is off."""
        return (
            "I don't have enough local information to answer that confidently. "
            "Please turn on Browser Tab web search and ask again so I can look it up online."
        )
    
    def _can_modify_files(self, context: Dict[str, Any]) -> bool:
        """Centralized check: returns True only if file modifications are allowed"""
        # ASK mode is always read-only
        if self._is_ask_context(context):
            return False
        # AGENT and PLAN modes can modify files
        return self._is_agent_context(context) or self._is_plan_context(context)
    
    def _should_force_file_operations(
        self,
        message: str,
        assistant_response: str,
        context: Dict[str, Any]
    ) -> bool:
        if not self._is_agent_context(context):
            return False
        
        combined = f"{message or ''}\n{assistant_response or ''}".lower()
        message_lower = (message or "").lower()
        response_lower = (assistant_response or "").lower()
        
        # Check if user message has change intent
        user_change_intent = self._has_change_intent(message)
        combined_change_intent = self._has_change_intent(combined)
        
        # Check for explicit file-related patterns in user message
        file_creation_patterns = [
            "create a file",
            "create file",
            "create files",
            "new file",
            "new files",
            "make a file",
            "make files",
            "write a file",
            "write files",
            "add a file",
            "add files",
            "generate a file",
            "generate files",
            "create the",
            "make the",
            "write the",
            "create",
            "make",
            "write",
            "add",
        ]
        has_file_creation_request = any(pattern in message_lower for pattern in file_creation_patterns)
        
        analysis_only = not combined_change_intent and self._is_analysis_request(message)
        has_code_block = "```" in response_lower
        mentions_file_section = "file operation" in combined or "file_operations" in combined
        
        # In agent mode, be VERY aggressive about forcing file operations
        # If user explicitly asks for file creation/modification, ALWAYS force
        if has_file_creation_request:
            print(f"[Agent Mode] Detected file creation request, forcing file operations")
            return True
        
        # If user has change intent and response has code blocks, likely needs file operations
        if user_change_intent and has_code_block:
            print(f"[Agent Mode] User has change intent + code blocks, forcing file operations")
            return True
        
        # If response mentions file operations but none were extracted, force regeneration
        if mentions_file_section:
            print(f"[Agent Mode] Response mentions file operations, forcing regeneration")
            return True
        
        # If analysis only, don't force
        if analysis_only:
            return False
        
        # In agent mode, if user has change intent, ALWAYS force (be very aggressive)
        if user_change_intent:
            print(f"[Agent Mode] User has change intent in agent mode, forcing file operations")
            return True
        
        return False
    
    async def _generate_file_operations_metadata(
        self,
        message: str,
        context: Dict[str, Any],
        history: List[Dict[str, str]],
        assistant_response: str
    ) -> Tuple[str, Dict[str, Any]]:
        history_lines = []
        for item in history[-4:]:
            role = item.get("role", "assistant").title()
            snippet = truncate_text(item.get("content", ""), 400)
            history_lines.append(f"{role}: {snippet}")
        history_text = "\n".join(history_lines) if history_lines else "None"
        
        context_snapshot = ""
        if context:
            try:
                context_snapshot = truncate_text(json.dumps(context, indent=2), 2000)
            except Exception:
                context_snapshot = truncate_text(str(context), 2000)
        
        prompt_lines = [
            "You previously responded to the developer but failed to include the required file_operations metadata.",
            "Your last assistant response (for reference):",
            truncate_text(assistant_response or "", 2000),
            "",
            "The developer's original request:",
            truncate_text(message or "", 1000),
            "",
        ]
        
        if context_snapshot:
            prompt_lines.extend([
                "Workspace context snapshot:",
                context_snapshot,
                "",
            ])
        
        prompt_lines.append("Recent conversation history:")
        prompt_lines.append(history_text)
        prompt_lines.append("")
        prompt_lines.extend([
            "You must now produce concrete file_operations that actually fulfill the developer's request.",
            "- CRITICAL: If the user asked to create, make, write, or generate a file, you MUST include a `create_file` operation with the complete file contents.",
            "- CRITICAL: If the user asked to modify, update, change, or fix code, you MUST include `edit_file` operations with the complete updated file contents.",
            "- Include at least one `create_file` or `edit_file` entry with the complete file contents (no placeholders like TODO, no comments saying 'add code here').",
            "- The file_operations array must contain actual operations—do not return an empty array unless the user explicitly said no code changes are needed.",
            "- Assume reasonable defaults instead of asking the user more questions.",
            "- Only leave file_operations empty if the user explicitly said that no code changes are needed.",
            "- Keep the ai_plan consistent with the work you are now completing (mark finished steps as completed).",
            "- Do not just describe what should be done—actually create the file_operations that do it.",
            ""
        ])
        prompt_lines.append(
            "Provide ONLY the JSON metadata block that includes ai_plan and file_operations as previously specified."
        )
        prompt_lines.extend(self.METADATA_FORMAT_LINES)
        prompt_lines.append("Respond with JSON only. Do not include prose, explanations, or markdown headings.")
        prompt_lines.append("If no file changes are actually required, return an empty file_operations array.")
        
        fallback_prompt = "\n".join(prompt_lines)
        
        try:
            fallback_response, _ = await self._call_model(fallback_prompt)
        except Exception as error:
            print(f"Failed to regenerate file operations metadata: {error}")
            return "", {"file_operations": [], "ai_plan": None}
        
        return self._parse_response_metadata(fallback_response, context)
    
    async def _call_model(self, prompt: str, images: Optional[List[str]] = None) -> Tuple[str, Optional[str]]:
        """Call the AI model, returns (response, thinking) tuple"""
        if self.provider == "huggingface":
            response = await self._call_huggingface(prompt)
            return response, None  # Hugging Face doesn't support thinking yet
        if self.provider == "openrouter":
            response = await self._call_openrouter(prompt, images=images)
            return response, None  # OpenRouter doesn't support separate thinking channel yet
        return await self._call_ollama(prompt, images=images)

    async def _call_huggingface(self, prompt: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._huggingface_completion, prompt)

    def _huggingface_completion(self, prompt: str) -> str:
        if InferenceClient is None:
            raise Exception("huggingface-hub is not installed. Please install it to use Hugging Face models.")
        client_kwargs = {
            "timeout": self.hf_request_timeout,
        }

        if self.hf_api_key:
            client_kwargs["token"] = self.hf_api_key
        base_url = (self.hf_base_url or "").strip()
        if base_url and base_url.lower() == self.HF_DEFAULT_API_BASE.lower():
            base_url = ""

        if base_url:
            client_kwargs["base_url"] = base_url
        elif self.hf_model:
            client_kwargs["model"] = self.hf_model

        cache_key = (self.hf_model or "", base_url or "", self.hf_api_key or "")
        try:
            if not self._hf_client or self._hf_client_cache_key != cache_key:
                self._hf_client = InferenceClient(**client_kwargs)
                self._hf_client_cache_key = cache_key
            client = self._hf_client
        except Exception as error:
            raise Exception(f"Failed to initialize Hugging Face client: {error}") from error

        try:
            completion = client.chat.completions.create(
                model=self.hf_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.hf_max_tokens,
                stream=True,
            )
            parts: List[str] = []
            for chunk in completion:
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None) if delta else None
                if content:
                    parts.append(content)
            response_text = "".join(parts).strip()
            return response_text or "No response generated"
        except Exception as error:
            raise Exception(f"Hugging Face API error: {error}") from error

    async def _call_openrouter(self, prompt: str, images: Optional[List[str]] = None) -> str:
        """
        Call OpenRouter's OpenAI-compatible chat completions API.

        This uses a simple non-streaming request to keep implementation small and robust.
        Supports images via OpenAI-compatible format (base64 data URLs in content array).
        """
        if not self.openrouter_api_key:
            raise Exception("OpenRouter API key is not configured.")
        if not self.openrouter_model:
            raise Exception("OpenRouter model is not configured.")

        url = f"{self.openrouter_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            # Optional but recommended headers for OpenRouter analytics
            "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "") or "http://localhost",
            "X-Title": os.getenv("OPENROUTER_APP_NAME", "") or "Offline AI Agent",
        }
        
        # Build message content - OpenAI format supports images in content array
        if images and len(images) > 0:
            logger.info(f"[IMAGE DEBUG] OpenRouter: Processing {len(images)} image(s)")
            # OpenAI format: content is an array of text and image_url objects
            # Add text first if prompt exists
            message_content = []
            if prompt:
                message_content.append({"type": "text", "text": prompt})
            # Add images
            for idx, img_data_url in enumerate(images):
                logger.info(f"[IMAGE DEBUG] OpenRouter: Processing image {idx+1}, data_url_length={len(img_data_url) if img_data_url else 0}")
                # OpenAI accepts data URLs directly in image_url format
                if img_data_url and isinstance(img_data_url, str):
                    message_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": img_data_url  # OpenAI/OpenRouter accepts data URLs directly
                        }
                    })
                    logger.info(f"[IMAGE DEBUG] OpenRouter: Added image {idx+1} to content array")
                else:
                    logger.warning(f"[IMAGE DEBUG] OpenRouter: Skipping invalid image {idx+1}, type={type(img_data_url)}")
            
            if not message_content:
                # Fallback: if no valid content, use prompt as text
                message_content = prompt
        else:
            # No images, just text (can be string or array with single text item)
            message_content = prompt
            logger.info(f"[IMAGE DEBUG] OpenRouter: No images, using text-only content")
        
        payload = {
            "model": self.openrouter_model,
            "messages": [
                {
                    "role": "user",
                    "content": message_content,
                }
            ],
        }

        # Use a longer timeout for OpenRouter (can be slow for complex requests)
        openrouter_timeout = max(self.request_timeout, 300)  # At least 5 minutes
        timeout = aiohttp.ClientTimeout(
            total=openrouter_timeout,
            connect=30,  # 30 seconds to establish connection
            sock_read=openrouter_timeout  # Timeout for reading response
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        try:
                            text = await asyncio.wait_for(resp.text(), timeout=10)
                            # Try to parse JSON error response
                            error_message = text
                            try:
                                error_json = json.loads(text)
                                # Extract meaningful error message from JSON response
                                if isinstance(error_json, dict):
                                    # Common OpenRouter error fields
                                    error_msg = (
                                        error_json.get("error", {}).get("message") if isinstance(error_json.get("error"), dict)
                                        else error_json.get("message")
                                        or error_json.get("error")
                                        or str(error_json)
                                    )
                                    if error_msg and len(error_msg) < 500:  # Use JSON error if reasonable length
                                        error_message = error_msg
                                    else:
                                        # If error message is too long, truncate it
                                        error_message = f"OpenRouter API error: {str(error_msg)[:200]}..." if error_msg else text[:500]
                            except (json.JSONDecodeError, AttributeError):
                                # Not JSON, use text as-is but limit length
                                error_message = text[:500] if len(text) > 500 else text
                            
                            # Log full error for debugging
                            logger.error(f"OpenRouter API error (status {resp.status}): Full response: {text[:1000]}")
                            
                            # Raise with concise error message
                            raise Exception(f"OpenRouter API error (status {resp.status}): {error_message}")
                        except asyncio.TimeoutError:
                            text = f"Failed to read error response (timeout)"
                            raise Exception(f"OpenRouter API error (status {resp.status}): {text}")
                    
                    # Read JSON with timeout protection
                    try:
                        data = await asyncio.wait_for(resp.json(), timeout=openrouter_timeout - 30)
                    except asyncio.TimeoutError:
                        raise Exception(
                            f"OpenRouter API response timeout after {openrouter_timeout}s. "
                            f"The model may be processing a complex request. Try again or use a simpler prompt."
                        )
            except asyncio.TimeoutError as timeout_error:
                raise Exception(
                    f"OpenRouter API request timed out after {openrouter_timeout}s. "
                    f"This can happen with complex requests or slow model responses. "
                    f"Try again or use a simpler prompt."
                ) from timeout_error
            except aiohttp.ClientError as client_error:
                error_msg = str(client_error)
                # Limit error message length
                if len(error_msg) > 500:
                    error_msg = error_msg[:500] + "..."
                raise Exception(f"OpenRouter API connection error: {error_msg}") from client_error
            except Exception as error:
                # Check if it's a timeout-related error
                error_str = str(error).lower()
                if 'timeout' in error_str or isinstance(error, (asyncio.TimeoutError, aiohttp.ServerTimeoutError)):
                    raise Exception(
                        f"OpenRouter API request timed out. "
                        f"The model may be processing a complex request. Try again or use a simpler prompt."
                    ) from error
                # Limit error message length to prevent truncation
                error_msg = str(error)
                if len(error_msg) > 500:
                    error_msg = error_msg[:500] + "..."
                    logger.error(f"OpenRouter API full error (truncated): {str(error)}")
                raise Exception(f"OpenRouter API request failed: {error_msg}") from error

        try:
            choices = data.get("choices") or []
            if not choices:
                return "No response generated"
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            content_str = content.strip()
            return content_str or "No response generated"
        except Exception as error:
            raise Exception(f"Invalid response from OpenRouter: {error}") from error

    def _extract_base64_from_data_url(self, data_url: str) -> Tuple[str, str]:
        """Extract base64 data and media type from data URL"""
        if not data_url or not data_url.startswith("data:"):
            return data_url, "image/png"
        
        # Parse data:image/png;base64,<data>
        header, data = data_url.split(",", 1)
        media_type = "image/png"  # default
        if "image/" in header:
            # Extract the image type (png, jpeg, gif, etc.)
            img_type = header.split("image/")[1].split(";")[0]
            media_type = f"image/{img_type}"
        
        return data, media_type
    
    async def _call_ollama(self, prompt: str, images: Optional[List[str]] = None) -> Tuple[str, Optional[str]]:
        """Make API call to Ollama, returns (response, thinking) tuple"""
        generation_options, keep_alive = self._build_generation_options_for_model()
        
        # Choose URL based on connection method
        url = self.ollama_url if self.use_proxy else self.ollama_direct
        
        # Use /api/chat endpoint if images are provided (for vision support)
        if images and len(images) > 0:
            logger.info(f"[IMAGE DEBUG] ========== _call_ollama: Processing images ==========")
            logger.info(f"[IMAGE DEBUG] Received {len(images)} image(s) for Ollama chat API")
            # Build messages format for chat API with images
            # Ollama expects images as base64 strings in an images array
            images_base64 = []
            for idx, img_data_url in enumerate(images):
                logger.info(f"[IMAGE DEBUG] Processing image {idx+1}: type={type(img_data_url)}, length={len(img_data_url) if img_data_url else 0}")
                logger.info(f"[IMAGE DEBUG] Image {idx+1} preview: {img_data_url[:200] if img_data_url else 'None'}...")
                base64_data, media_type = self._extract_base64_from_data_url(img_data_url)
                logger.info(f"[IMAGE DEBUG] Image {idx+1}: extracted base64 length={len(base64_data)}, media_type={media_type}")
                images_base64.append(base64_data)
                logger.info(f"[IMAGE DEBUG] Image {idx+1}: ✅ Added to images_base64 array")
            logger.info(f"[IMAGE DEBUG] Total images_base64: {len(images_base64)}")
            logger.info(f"[IMAGE DEBUG] =====================================================")
            
            messages = [{
                "role": "user",
                "content": prompt,
                "images": images_base64
            }]
            
            # Verify images are in the message
            logger.info(f"[IMAGE DEBUG] Message structure - role: {messages[0]['role']}, content length: {len(messages[0]['content'])}, images count: {len(messages[0]['images'])}")
            if len(messages[0]['images']) == 0:
                logger.error(f"[IMAGE DEBUG] ⚠️⚠️⚠️ ERROR: No images in message! images_base64 length was {len(images_base64)}")
            
            payload = {
                "model": self.current_model,
                "messages": messages,
                "stream": True,
                "options": generation_options
            }
            if keep_alive:
                payload["keep_alive"] = keep_alive
            
            # Final verification before sending
            logger.info(f"[IMAGE DEBUG] Final payload check - model: {payload['model']}, messages[0]['images'] count: {len(payload['messages'][0].get('images', []))}")
            logger.info(f"[IMAGE DEBUG] Using /api/chat endpoint with {len(images_base64)} image(s)")
            logger.info(f"[IMAGE DEBUG] Payload preview - model: {self.current_model}, messages count: {len(messages)}")
            logger.info(f"[IMAGE DEBUG] First message images count: {len(messages[0].get('images', [])) if messages else 0}")
            endpoint = "/api/chat"
        else:
            # Use /api/generate endpoint for text-only requests
            payload = {
                "model": self.current_model,
                "prompt": prompt,
                "stream": True,  # Enable streaming to capture thinking
                "options": generation_options
            }
            if keep_alive:
                payload["keep_alive"] = keep_alive
            
            endpoint = "/api/generate"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{url}{endpoint}",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout)
                ) as response:
                    if response.status == 200:
                        # Stream the response to capture thinking and response separately
                        response_parts = []
                        thinking_parts = []
                        buffer = ""
                        done = False
                        
                        async for chunk in response.content.iter_chunked(8192):
                            if not chunk or done:
                                break
                            buffer += chunk.decode('utf-8', errors='ignore')
                            
                            # Process complete lines (Ollama sends newline-delimited JSON)
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line = line.strip()
                                if not line:
                                    continue
                                
                                try:
                                    # Parse each JSON line from the stream
                                    data = json.loads(line)
                                    
                                    # Handle chat API format (message.content) vs generate API format (response)
                                    if endpoint == "/api/chat":
                                        # Chat API uses message.content
                                        if "message" in data and "content" in data["message"]:
                                            response_parts.append(data["message"]["content"])
                                        # Chat API may also have thinking
                                        if "thinking" in data and data["thinking"]:
                                            thinking_parts.append(data["thinking"])
                                    else:
                                        # Generate API uses response
                                        if "thinking" in data and data["thinking"]:
                                            thinking_parts.append(data["thinking"])
                                        if "response" in data and data["response"]:
                                            response_parts.append(data["response"])
                                    
                                    # Check if done
                                    if data.get("done", False):
                                        done = True
                                        break
                                except json.JSONDecodeError:
                                    # Skip invalid JSON lines
                                    continue
                                except Exception as e:
                                    logger.debug(f"Error parsing stream line: {e}")
                                    continue
                        
                        # Combine all parts
                        full_response = "".join(response_parts)
                        full_thinking = "".join(thinking_parts) if thinking_parts else None
                        
                        # Fallback: if streaming didn't work, try non-streaming
                        if not full_response:
                            # Retry with non-streaming
                            payload["stream"] = False
                            async with session.post(
                                f"{url}{endpoint}",
                                json=payload,
                                timeout=aiohttp.ClientTimeout(total=self.request_timeout)
                            ) as fallback_response:
                                if fallback_response.status == 200:
                                    response_text = await fallback_response.text()
                                    try:
                                        data = json.loads(response_text)
                                        if isinstance(data, dict):
                                            full_response = data.get("response", response_text)
                                            full_thinking = data.get("thinking")
                                        else:
                                            full_response = str(data)
                                    except (json.JSONDecodeError, ValueError):
                                        full_response = response_text
                        
                        return full_response or "", full_thinking
                    else:
                        error_text = await response.text()
                        logger.error(f"Ollama API error: {response.status} - Model: {self.current_model}, URL: {url}, Error: {error_text}")
                        raise Exception(f"Ollama API error: {response.status} - {error_text}")
        except asyncio.TimeoutError:
            logger.error(f"Ollama request timed out after {self.request_timeout}s. Model: {self.current_model}, URL: {url}")
            raise Exception(
                f"Request timed out after {self.request_timeout}s. "
                "The model might be too slow or overloaded. "
                "You can increase OLLAMA_REQUEST_TIMEOUT or try a smaller prompt."
            )
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Cannot connect to Ollama at {url}. Model: {self.current_model}, Error: {str(e)}")
            raise Exception(f"Cannot connect to Ollama at {url}. Please ensure Ollama is running (try 'ollama serve'). Error: {str(e)}")
        except Exception as e:
            logger.exception(f"Error calling Ollama. Model: {self.current_model}, URL: {url}")
            raise Exception(f"Error calling Ollama: {str(e)}")
    
    async def _stream_ollama(self, prompt: str, images: Optional[List[str]] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream Ollama response, yielding chunks as they arrive"""
        generation_options, keep_alive = self._build_generation_options_for_model()
        
        url = self.ollama_url if self.use_proxy else self.ollama_direct
        
        # Use /api/chat endpoint if images are provided (for vision support)
        if images and len(images) > 0:
            logger.info(f"[IMAGE DEBUG] ========== _stream_ollama: Processing images ==========")
            logger.info(f"[IMAGE DEBUG] Streaming: Received {len(images)} image(s) for Ollama chat API")
            # Build messages format for chat API with images
            # Ollama expects images as base64 strings in an images array
            images_base64 = []
            for idx, img_data_url in enumerate(images):
                logger.info(f"[IMAGE DEBUG] Streaming: Processing image {idx+1}: type={type(img_data_url)}, length={len(img_data_url) if img_data_url else 0}")
                logger.info(f"[IMAGE DEBUG] Streaming: Image {idx+1} preview: {img_data_url[:200] if img_data_url else 'None'}...")
                base64_data, media_type = self._extract_base64_from_data_url(img_data_url)
                logger.info(f"[IMAGE DEBUG] Streaming: Image {idx+1}: extracted base64 length={len(base64_data)}, media_type={media_type}")
                images_base64.append(base64_data)
                logger.info(f"[IMAGE DEBUG] Streaming: Image {idx+1}: ✅ Added to images_base64 array")
            logger.info(f"[IMAGE DEBUG] Streaming: Total images_base64: {len(images_base64)}")
            logger.info(f"[IMAGE DEBUG] ========================================================")
            
            messages = [{
                "role": "user",
                "content": prompt,
                "images": images_base64
            }]
            
            payload = {
                "model": self.current_model,
                "messages": messages,
                "stream": True,
                "options": generation_options
            }
            if keep_alive:
                payload["keep_alive"] = keep_alive
            
            logger.info(f"[IMAGE DEBUG] Streaming: Using /api/chat endpoint with {len(images_base64)} image(s)")
            logger.info(f"[IMAGE DEBUG] Streaming: Payload preview - model: {self.current_model}, messages count: {len(messages)}")
            logger.info(f"[IMAGE DEBUG] Streaming: First message images count: {len(messages[0].get('images', [])) if messages else 0}")
            endpoint = "/api/chat"
        else:
            # Use /api/generate endpoint for text-only requests
            payload = {
                "model": self.current_model,
                "prompt": prompt,
                "stream": True,
                "options": generation_options
            }
            if keep_alive:
                payload["keep_alive"] = keep_alive
            
            endpoint = "/api/generate"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{url}{endpoint}",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout)
                ) as response:
                    if response.status == 200:
                        buffer = ""
                        async for chunk in response.content.iter_chunked(8192):
                            if not chunk:
                                break
                            buffer += chunk.decode('utf-8', errors='ignore')
                            
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line = line.strip()
                                if not line:
                                    continue
                                
                                try:
                                    data = json.loads(line)
                                    
                                    # Handle chat API format (message.content) vs generate API format (response)
                                    if endpoint == "/api/chat":
                                        # Chat API uses message.content
                                        if "message" in data and "content" in data["message"]:
                                            yield {"type": "response", "content": data["message"]["content"]}
                                        # Chat API may also have thinking
                                        if "thinking" in data and data["thinking"]:
                                            yield {"type": "thinking", "content": data["thinking"]}
                                    else:
                                        # Generate API uses response
                                        if "thinking" in data and data["thinking"]:
                                            yield {"type": "thinking", "content": data["thinking"]}
                                        if "response" in data and data["response"]:
                                            yield {"type": "response", "content": data["response"]}
                                    
                                    # Yield done signal
                                    if data.get("done", False):
                                        yield {"type": "done"}
                                        return
                                except json.JSONDecodeError:
                                    continue
                                except Exception as e:
                                    logger.debug(f"Error parsing stream line: {e}")
                                    continue
                    else:
                        error_text = await response.text()
                        raise Exception(f"Ollama API error: {response.status} - {error_text}")
        except Exception as e:
            logger.exception(f"Error streaming from Ollama: {e}")
            yield {"type": "error", "content": str(e)}
    
    async def generate_code(
        self, 
        prompt: str, 
        language: str = "python",
        context: Dict[str, Any] = None
    ) -> str:
        """Generate code based on a prompt"""
        code_prompt = f"Generate {language} code for: {prompt}"
        if context:
            code_prompt += f"\n\nContext: {json.dumps(context, indent=2)}"
        
        response = await self._call_model(code_prompt)
        return response
    
    async def explain_code(self, code: str, language: str = "python") -> str:
        """Explain what a piece of code does"""
        explain_prompt = f"Explain this {language} code:\n\n```{language}\n{code}\n```"
        response = await self._call_model(explain_prompt)
        return response
    
    async def debug_code(self, code: str, error_message: str, language: str = "python") -> str:
        """Help debug code with an error message"""
        debug_prompt = f"Debug this {language} code. Error: {error_message}\n\n```{language}\n{code}\n```"
        response = await self._call_model(debug_prompt)
        return response
    
    def _validate_suggestion_syntax(
        self,
        suggestion: str,
        line_prefix: str,
        line_suffix: str,
        cursor_context: Dict[str, Any],
        current_line: str,
        cursor_column: int
    ) -> bool:
        """Validate that the suggestion won't create syntax errors"""
        if not suggestion or not suggestion.strip():
            return False
        
        # Check for balanced brackets, parentheses, and braces
        # Count opening and closing brackets in the suggestion
        open_parens = suggestion.count('(') - suggestion.count(')')
        open_brackets = suggestion.count('[') - suggestion.count(']')
        open_braces = suggestion.count('{') - suggestion.count('}')
        
        # Count quotes (simple check - not perfect but helps)
        single_quotes = suggestion.count("'") - suggestion.count("\\'")
        double_quotes = suggestion.count('"') - suggestion.count('\\"')
        
        # If we're in a string context, the suggestion should not add unbalanced quotes
        if cursor_context.get('in_string'):
            quote_char = '"' if cursor_context.get('string_type') in ['double', 'triple'] else "'"
            # If we're in a string and there's a closing quote after cursor, 
            # suggestion shouldn't add extra quotes
            if line_suffix and quote_char in line_suffix:
                # Check if suggestion has unmatched quotes of the same type
                if quote_char == '"' and double_quotes % 2 != 0:
                    # Unmatched double quotes - could break syntax
                    return False
                elif quote_char == "'" and single_quotes % 2 != 0:
                    # Unmatched single quotes - could break syntax
                    return False
        
        # Check if suggestion would create unbalanced brackets when combined with prefix
        # Count brackets in prefix
        prefix_open_parens = line_prefix.count('(') - line_prefix.count(')')
        prefix_open_brackets = line_prefix.count('[') - line_prefix.count(']')
        prefix_open_braces = line_prefix.count('{') - line_prefix.count('}')
        
        # Count brackets in suffix (what comes after cursor)
        suffix_close_parens = line_suffix.count(')') - line_suffix.count('(')
        suffix_close_brackets = line_suffix.count(']') - line_suffix.count('[')
        suffix_close_braces = line_suffix.count('}') - line_suffix.count('{')
        
        # Check if suggestion would balance properly
        total_parens = prefix_open_parens + open_parens - suffix_close_parens
        total_brackets = prefix_open_brackets + open_brackets - suffix_close_brackets
        total_braces = prefix_open_braces + open_braces - suffix_close_braces
        
        # If we're inside parentheses/brackets/braces, we should be closing them, not opening more
        if cursor_context.get('in_parens') and open_parens > 0:
            # Opening more parens when already inside - might be okay, but be cautious
            # Only allow if we're not already very unbalanced
            if prefix_open_parens > 3:
                return False
        
        if cursor_context.get('in_brackets') and open_brackets > 0:
            if prefix_open_brackets > 3:
                return False
        
        if cursor_context.get('in_braces') and open_braces > 0:
            if prefix_open_braces > 3:
                return False
        
        # Check for common syntax errors
        # Don't allow suggestions that start with operators (unless in specific contexts)
        suggestion_stripped = suggestion.strip()
        if suggestion_stripped and suggestion_stripped[0] in [',', ';', ':', '}', ']', ')']:
            # Starting with closing bracket/operator - likely syntax error
            return False
        
        # Check if suggestion contains incomplete statements that would break syntax
        # For example, "def " without a name, "if " without condition, etc.
        incomplete_patterns = [
            r'\bdef\s+$',  # "def " at end
            r'\bif\s+$',   # "if " at end
            r'\bfor\s+$',  # "for " at end
            r'\bwhile\s+$', # "while " at end
            r'\bclass\s+$', # "class " at end
        ]
        for pattern in incomplete_patterns:
            if re.search(pattern, suggestion_stripped, re.IGNORECASE):
                return False
        
        # If suggestion is just whitespace or very short and doesn't make sense
        if len(suggestion_stripped) < 2 and suggestion_stripped not in ['', ' ', '\n', '\t']:
            # Very short suggestion - might be incomplete
            pass  # Allow short suggestions, they might be valid
        
        return True
    
    async def generate_code_completion(
        self,
        file_path: str,
        content: str,
        cursor_line: int,
        cursor_column: int,
        language: str = "python"
    ) -> Dict[str, Any]:
        """Generate code completion suggestion based on current context"""
        # Extract context around cursor (last 50 lines before cursor)
        lines = content.split('\n')
        context_start = max(0, cursor_line - 50)
        context_lines = lines[context_start:cursor_line]
        context_before = '\n'.join(context_lines)
        
        # Get the current line up to cursor and after cursor
        current_line = lines[cursor_line] if cursor_line < len(lines) else ""
        line_prefix = current_line[:cursor_column]
        line_suffix = current_line[cursor_column:] if cursor_column < len(current_line) else ""
        
        # Analyze context around cursor for better suggestions
        # Check if cursor is inside quotes, parentheses, brackets, etc.
        cursor_context = {
            'in_string': False,
            'string_type': None,  # 'single', 'double', 'triple'
            'in_parens': False,
            'in_brackets': False,
            'in_braces': False,
            'after_colon': False,
            'after_function': False,
        }
        
        # Analyze line_prefix to understand context
        prefix_stripped = line_prefix.strip()
        if prefix_stripped:
            # Check for string context
            single_quotes = line_prefix.count("'") - line_prefix.count("\\'")
            double_quotes = line_prefix.count('"') - line_prefix.count('\\"')
            triple_single = line_prefix.count("'''")
            triple_double = line_prefix.count('"""')
            
            if triple_single % 2 == 1 or (single_quotes % 2 == 1 and not triple_single):
                cursor_context['in_string'] = True
                cursor_context['string_type'] = 'triple' if triple_single else 'single'
            elif triple_double % 2 == 1 or (double_quotes % 2 == 1 and not triple_double):
                cursor_context['in_string'] = True
                cursor_context['string_type'] = 'triple' if triple_double else 'double'
            
            # Check if after colon (function definition, if statement, etc.)
            if prefix_stripped.endswith(':'):
                cursor_context['after_colon'] = True
                # Check if it's a function definition
                if re.search(r'\b(def|function|class|if|elif|else|for|while|with|try|except|finally)\s+\w+\s*:\s*$', line_prefix, re.IGNORECASE):
                    cursor_context['after_function'] = True
            
            # Check for parentheses, brackets, braces
            open_parens = line_prefix.count('(') - line_prefix.count(')')
            open_brackets = line_prefix.count('[') - line_prefix.count(']')
            open_braces = line_prefix.count('{') - line_prefix.count('}')
            cursor_context['in_parens'] = open_parens > 0
            cursor_context['in_brackets'] = open_brackets > 0
            cursor_context['in_braces'] = open_braces > 0
        
        # Calculate indentation of current line
        current_indent = len(current_line) - len(current_line.lstrip())
        # If cursor is after some text, use that line's indentation
        # Otherwise, check previous non-empty line for indentation context
        if cursor_column > 0 and current_line[:cursor_column].strip():
            # Cursor is in the middle of a line, use current line's indent
            base_indent = current_indent
        else:
            # Cursor is at start or after whitespace, check previous lines
            base_indent = current_indent
            # Look for the last non-empty line to determine indentation context
            for i in range(cursor_line - 1, max(0, cursor_line - 10), -1):
                if i < len(lines) and lines[i].strip():
                    prev_indent = len(lines[i]) - len(lines[i].lstrip())
                    # If previous line ends with colon or opening brace, increase indent
                    prev_line = lines[i].rstrip()
                    if prev_line.endswith(':') or prev_line.endswith('{') or prev_line.endswith('('):
                        base_indent = prev_indent + 4  # Standard 4-space indent
                    else:
                        base_indent = prev_indent
                    break
        
        # Get more context for better suggestions (last 100 lines, or entire file if small)
        full_context = content
        if len(lines) > 100:
            context_start_full = max(0, cursor_line - 100)
            context_end = min(len(lines), cursor_line + 5)  # Include a few lines after cursor
            context_lines_full = lines[context_start_full:context_end]
            full_context = '\n'.join(context_lines_full)
        
        # Build context-aware prompt
        context_hints = []
        if cursor_context['in_string']:
            if cursor_context['string_type'] == 'triple':
                context_hints.append("CURSOR IS INSIDE A TRIPLE-QUOTED STRING - suggest only the string content continuation")
            else:
                context_hints.append("CURSOR IS INSIDE A STRING - suggest only the string content (e.g., 'Hello World' if cursor is at print('|'))")
        elif cursor_context['after_function']:
            context_hints.append("CURSOR IS AFTER A FUNCTION DEFINITION - suggest only the function body (e.g., 'pass' or actual body), NOT the function signature again")
        elif cursor_context['after_colon']:
            context_hints.append("CURSOR IS AFTER A COLON - suggest only the block content, NOT the line with the colon")
        elif cursor_context['in_parens']:
            context_hints.append("CURSOR IS INSIDE PARENTHESES - suggest only the argument/parameter content")
        elif cursor_context['in_brackets']:
            context_hints.append("CURSOR IS INSIDE BRACKETS - suggest only the list/array element")
        elif cursor_context['in_braces']:
            context_hints.append("CURSOR IS INSIDE BRACES - suggest only the dictionary/object content")
        
        context_note = "\n".join(context_hints) if context_hints else "Analyze the cursor position carefully."
        
        # Build prompt for code completion with better context
        completion_prompt = f"""You are a code completion assistant. Analyze the following {language} code and suggest ONLY the continuation that should come after the cursor position.

FULL CODE CONTEXT (for understanding the file structure, patterns, and style):
{full_context}

CURSOR POSITION (the code ends here, suggest what comes next):
{context_before}{line_prefix}|{line_suffix}

NOTE: The | marks the cursor position. Code before | already exists. Code after | (if any) also exists and your suggestion should work with it, not break it.

{context_note}

CRITICAL INSTRUCTIONS:
1. Analyze the FULL CODE CONTEXT to understand the codebase structure, patterns, naming conventions, and coding style
2. The suggestion MUST be contextually relevant to the existing code patterns and style
3. Provide ONLY the continuation code that should come AFTER the cursor position (marked with |)
4. Do NOT repeat any code that already exists before the cursor
5. Do NOT include code fences (```) or markdown formatting - return ONLY raw code
6. Do NOT include backticks (`) anywhere in your response
7. Do NOT include explanations, comments about the code, or meta-commentary
8. The suggestion should match the coding style, patterns, and conventions used in the file
9. Maintain proper indentation - the first line should continue from the cursor position
10. Keep it concise (typically 1-10 lines)
11. Return ONLY the raw code continuation, nothing else - no markdown, no code blocks, no explanations
12. **CRITICAL: The suggestion MUST be syntactically correct and MUST NOT break existing code**
13. **CRITICAL: Account for what comes after the cursor (if shown) - ensure your suggestion works with it**
14. **CRITICAL: Do NOT create unbalanced brackets, parentheses, or quotes**
15. **CRITICAL: If cursor is inside quotes/parens/brackets, ensure your suggestion properly closes them or continues correctly**

EXAMPLES:
- If cursor is at "def calculator:" → suggest "pass" or function body, NOT "def calculator: pass"
- If cursor is at "print('|')" with suffix "')" → suggest "Hello World" (just the string content, closing quote already exists)
- If cursor is at "function samplecode" → suggest "(){{\n\n}}" (just the signature continuation)
- If cursor is at "if x > 5:" → suggest the if block content, NOT "if x > 5: ..."
- If cursor is at "print(|)" with suffix ")" → suggest the argument, NOT "print(...)" which would duplicate the function call

Provide the code completion (raw code only, no markdown, syntactically correct):"""

        try:
            response = await self._call_model(completion_prompt)
            
            # Clean up the response - remove code fences, markdown, backticks, and explanations
            suggestion = response.strip()
            
            # Remove ALL backticks first (they should never appear in code suggestions)
            suggestion = suggestion.replace('`', '')
            
            # Remove code fences (handle various formats: ```, ```python, ```js, etc.)
            # Remove opening code fence (at start or after whitespace)
            suggestion = re.sub(r'^```[a-zA-Z0-9]*\s*\n?', '', suggestion, flags=re.MULTILINE)
            suggestion = re.sub(r'\n\s*```[a-zA-Z0-9]*\s*\n?', '\n', suggestion, flags=re.MULTILINE)
            # Remove closing code fence (at end or before newline)
            suggestion = re.sub(r'\n?\s*```\s*$', '', suggestion, flags=re.MULTILINE)
            suggestion = re.sub(r'\n?\s*```\s*\n', '\n', suggestion, flags=re.MULTILINE)
            # Remove any remaining standalone ``` lines
            suggestion = re.sub(r'^\s*```\s*$', '', suggestion, flags=re.MULTILINE)
            
            # Remove any remaining backticks that might have been in code fences
            suggestion = suggestion.replace('`', '')
            suggestion = suggestion.strip()
            
            # Remove common markdown patterns and explanations
            # Remove lines that look like explanations (starting with #, //, or containing "Here is", "The code", etc.)
            suggestion_lines = suggestion.split('\n')
            cleaned_lines = []
            skip_explanation = True
            for line in suggestion_lines:
                line_stripped = line.strip()
                # Skip explanation lines at the start
                if skip_explanation:
                    # Check for comment markers
                    if (line_stripped.startswith('#') or 
                        line_stripped.startswith('//') or 
                        line_stripped.startswith('/*') or
                        line_stripped.startswith('*') or
                        # Check for common explanation phrases
                        any(phrase in line_stripped.lower() for phrase in [
                            'here is', 'the code', 'completion:', 'suggestion:', 'example:',
                            'note:', 'notes:', 'note that', 'notes that',
                            'important:', 'warning:', 'tip:', 'hint:',
                            'remember:', 'keep in mind', 'please note'
                        ]) or
                        # Check if line is just "Notes" or "Note"
                        line_stripped.lower() in ['notes', 'note', 'note:', 'notes:']):
                        continue
                    if line_stripped:  # First non-explanation line
                        skip_explanation = False
                
                # Also filter out explanation lines in the middle (but be less aggressive)
                if not skip_explanation:
                    # Skip lines that are clearly explanations even in the middle
                    if (line_stripped.lower() in ['notes', 'note', 'note:', 'notes:'] or
                        (line_stripped.lower().startswith('note:') and len(line_stripped) < 50) or
                        (line_stripped.lower().startswith('notes:') and len(line_stripped) < 50)):
                        continue
                
                # Keep the line
                if not skip_explanation or line_stripped:
                    cleaned_lines.append(line)
            
            suggestion = '\n'.join(cleaned_lines).strip()
            
            # Final check: if suggestion starts with "Notes" or "Note", remove it
            suggestion_stripped = suggestion.strip()
            if suggestion_stripped.lower().startswith('notes') or suggestion_stripped.lower().startswith('note:'):
                # Find the first line break or remove the first line
                lines = suggestion.split('\n')
                if len(lines) > 1:
                    # Remove first line if it's just "Notes" or "Note:"
                    if lines[0].strip().lower() in ['notes', 'note', 'note:', 'notes:']:
                        suggestion = '\n'.join(lines[1:]).strip()
                    elif lines[0].strip().lower().startswith('note'):
                        # Check if it's a short note line
                        if len(lines[0].strip()) < 50:
                            suggestion = '\n'.join(lines[1:]).strip()
                else:
                    # Single line that's just "Notes" - return empty
                    if suggestion_stripped.lower() in ['notes', 'note', 'note:', 'notes:']:
                        suggestion = ""
            
            # Remove duplicate/redundant code - be aggressive about detecting what user already typed
            if suggestion and line_prefix.strip():
                line_prefix_stripped = line_prefix.strip()
                suggestion_stripped = suggestion.strip()
                suggestion_lines_list = suggestion.split('\n')
                
                # Check if suggestion starts with the same prefix (case-insensitive)
                prefix_lower = line_prefix_stripped.lower()
                suggestion_lower = suggestion_stripped.lower()
                
                # More aggressive matching: check if any significant part of prefix appears in suggestion
                # Split prefix into meaningful tokens (words, operators, etc.)
                prefix_tokens = re.findall(r'\w+|[^\w\s]', line_prefix_stripped)
                
                if prefix_tokens and len(prefix_tokens) > 0:
                    # Check if suggestion starts with the same tokens
                    suggestion_tokens = re.findall(r'\w+|[^\w\s]', suggestion_stripped)
                    
                    # Find matching token count
                    match_count = 0
                    for i in range(min(len(prefix_tokens), len(suggestion_tokens))):
                        if prefix_tokens[i].lower() == suggestion_tokens[i].lower():
                            match_count += 1
                        else:
                            break
                    
                    # If significant portion matches, remove it
                    if match_count >= 2 or (match_count >= 1 and len(prefix_tokens) <= 3):
                        # Reconstruct matched prefix from suggestion tokens
                        matched_tokens = suggestion_tokens[:match_count]
                        matched_text = ''.join(matched_tokens)
                        
                        # Find where this text appears in suggestion
                        if suggestion_stripped.lower().startswith(matched_text.lower()):
                            # Find exact position (preserving case)
                            remaining = suggestion_stripped
                            for i in range(len(suggestion_stripped)):
                                if suggestion_stripped[i:].lower().startswith(matched_text.lower()):
                                    remaining = suggestion_stripped[i + len(matched_text):]
                                    break
                            
                            # Remove leading whitespace and common separators
                            remaining = remaining.lstrip()
                            # Remove colon, semicolon, equals, or other separators that might be duplicated
                            while remaining and remaining[0] in [':', ';', '=', '(', '[', '{', ' ']:
                                remaining = remaining[1:].lstrip()
                            
                            # Only use remaining if it's meaningful
                            if remaining and len(remaining) > 0:
                                suggestion = remaining
                            elif len(suggestion_lines_list) > 1:
                                # Remove first line and use rest
                                suggestion = '\n'.join(suggestion_lines_list[1:]).strip()
                            else:
                                suggestion = ""
                
                # Also check if first line of suggestion exactly matches or contains current_line
                if suggestion_lines_list and current_line.strip():
                    suggestion_first_line = suggestion_lines_list[0].strip()
                    current_line_stripped = current_line.strip()
                    
                    # If first line matches current line exactly, remove it
                    if suggestion_first_line == current_line_stripped:
                        if len(suggestion_lines_list) > 1:
                            suggestion = '\n'.join(suggestion_lines_list[1:]).strip()
                        else:
                            suggestion = ""
                    # Check if first line starts with current_line (partial match)
                    elif suggestion_first_line.lower().startswith(current_line_stripped.lower()):
                        # Remove the matching prefix from first line
                        remaining_first = suggestion_first_line[len(current_line_stripped):].lstrip()
                        # Remove separators
                        while remaining_first and remaining_first[0] in [':', ';', '=', '(', '[', '{', ' ']:
                            remaining_first = remaining_first[1:].lstrip()
                        
                        if remaining_first:
                            suggestion_lines_list[0] = remaining_first
                            suggestion = '\n'.join(suggestion_lines_list).strip()
                        elif len(suggestion_lines_list) > 1:
                            suggestion = '\n'.join(suggestion_lines_list[1:]).strip()
                        else:
                            suggestion = ""
                
                # Special handling for function definitions: if user typed "function name" or "def name"
                # and suggestion starts with same, extract only the signature continuation
                func_pattern = r'^(def|function|class)\s+(\w+)'
                prefix_match = re.search(func_pattern, line_prefix_stripped, re.IGNORECASE)
                if prefix_match and suggestion:
                    func_keyword = prefix_match.group(1)
                    func_name = prefix_match.group(2)
                    # Check if suggestion repeats the function definition
                    suggestion_func_match = re.search(func_pattern, suggestion_stripped, re.IGNORECASE)
                    if suggestion_func_match and suggestion_func_match.group(2).lower() == func_name.lower():
                        # Extract everything after the function signature
                        # Find where function body starts (after colon or opening brace)
                        body_start = re.search(r'[:\{]\s*', suggestion_stripped)
                        if body_start:
                            suggestion = suggestion_stripped[body_start.end():].strip()
                        else:
                            # Try to find the actual continuation
                            lines = suggestion.split('\n')
                            if len(lines) > 1:
                                suggestion = '\n'.join(lines[1:]).strip()
                            else:
                                suggestion = ""
            
            # Context-aware suggestion adjustment
            if suggestion and cursor_context['in_string']:
                # If cursor is inside a string, the suggestion should be string content only
                # Remove any quotes that might be in the suggestion (we're already inside quotes)
                suggestion = suggestion.strip()
                
                # Remove leading/trailing quotes if present (we're already inside quotes)
                quote_char = '"' if cursor_context['string_type'] in ['double', 'triple'] else "'"
                triple_quote = '"""' if cursor_context['string_type'] == 'triple' and quote_char == '"' else "'''"
                
                # Remove triple quotes if present
                if cursor_context['string_type'] == 'triple':
                    if suggestion.startswith(triple_quote):
                        suggestion = suggestion[len(triple_quote):]
                    if suggestion.endswith(triple_quote):
                        suggestion = suggestion[:-len(triple_quote)]
                
                # Remove single/double quotes
                if suggestion.startswith('"') and suggestion.endswith('"'):
                    suggestion = suggestion[1:-1]
                elif suggestion.startswith("'") and suggestion.endswith("'"):
                    suggestion = suggestion[1:-1]
                
                # Remove standalone quotes
                if len(suggestion) == 1 and suggestion in ['"', "'"]:
                    suggestion = ""
                
                # If suggestion ends with just a quote (likely the closing quote we already have)
                # Remove it since the closing quote is already in the code
                if suggestion.endswith(quote_char) and len(suggestion) > 1:
                    # Check if it's just ending with quote (not escaped)
                    if suggestion[-1] == quote_char and (len(suggestion) < 2 or suggestion[-2] != '\\'):
                        suggestion = suggestion[:-1]
                
                suggestion = suggestion.strip()
            
            # Remove closing brackets/quotes from suggestion if they already exist after cursor
            if suggestion and line_suffix:
                suffix_stripped = line_suffix.strip()
                suggestion_stripped = suggestion.strip()
                
                # If suffix starts with closing bracket and suggestion ends with same, remove from suggestion
                if suffix_stripped.startswith(')') and suggestion_stripped.endswith(')'):
                    # Check if it's a standalone closing paren (not part of something else)
                    if len(suggestion_stripped) > 1 and suggestion_stripped[-2] not in ['(', '[', '{']:
                        suggestion = suggestion_stripped[:-1].strip()
                elif suffix_stripped.startswith(']') and suggestion_stripped.endswith(']'):
                    if len(suggestion_stripped) > 1 and suggestion_stripped[-2] not in ['(', '[', '{']:
                        suggestion = suggestion_stripped[:-1].strip()
                elif suffix_stripped.startswith('}') and suggestion_stripped.endswith('}'):
                    if len(suggestion_stripped) > 1 and suggestion_stripped[-2] not in ['(', '[', '{']:
                        suggestion = suggestion_stripped[:-1].strip()
                elif suffix_stripped.startswith('"') and suggestion_stripped.endswith('"'):
                    # Only if we're not in a string context (handled above)
                    if not cursor_context.get('in_string'):
                        if len(suggestion_stripped) > 1:
                            suggestion = suggestion_stripped[:-1].strip()
                elif suffix_stripped.startswith("'") and suggestion_stripped.endswith("'"):
                    if not cursor_context.get('in_string'):
                        if len(suggestion_stripped) > 1:
                            suggestion = suggestion_stripped[:-1].strip()
            
            # Fix indentation to match current context
            if suggestion:
                suggestion_lines = suggestion.split('\n')
                if suggestion_lines:
                    # For inline completion, first line continues from cursor (no extra indent)
                    # Subsequent lines should maintain proper relative indentation
                    
                    # Check if cursor is in middle of line or at start
                    cursor_in_middle = cursor_column > 0 and current_line[:cursor_column].rstrip()
                    
                    if len(suggestion_lines) == 1:
                        # Single line - just strip leading whitespace (continues from cursor)
                        suggestion = suggestion.strip()
                    else:
                        # Multi-line suggestion
                        # First line: no indent (continues from cursor position)
                        adjusted_lines = []
                        if suggestion_lines[0].strip():
                            adjusted_lines.append(suggestion_lines[0].lstrip())
                        else:
                            adjusted_lines.append('')
                        
                        # For subsequent lines, calculate proper indentation
                        # Find minimum indent in subsequent lines
                        min_indent = float('inf')
                        for line in suggestion_lines[1:]:
                            if line.strip():
                                line_indent = len(line) - len(line.lstrip())
                                min_indent = min(min_indent, line_indent)
                        
                        if min_indent == float('inf'):
                            min_indent = 0
                        
                        # Determine base indent for subsequent lines
                        if cursor_in_middle:
                            # Cursor in middle of line - check if line ends with colon/brace
                            line_before_cursor = current_line[:cursor_column].rstrip()
                            if line_before_cursor.endswith(':') or line_before_cursor.endswith('{') or line_before_cursor.endswith('('):
                                subsequent_base_indent = base_indent + 4
                            else:
                                subsequent_base_indent = base_indent
                        else:
                            # Cursor at start or after whitespace
                            # Check previous line for context
                            if cursor_line > 0:
                                prev_line = lines[cursor_line - 1].rstrip() if cursor_line - 1 < len(lines) else ""
                                if prev_line.endswith(':') or prev_line.endswith('{') or prev_line.endswith('('):
                                    subsequent_base_indent = base_indent + 4
                                else:
                                    subsequent_base_indent = base_indent
                            else:
                                subsequent_base_indent = base_indent
                        
                        # Adjust indentation for subsequent lines
                        indent_diff = subsequent_base_indent - min_indent
                        for line in suggestion_lines[1:]:
                            if line.strip():
                                current_indent = len(line) - len(line.lstrip())
                                new_indent = max(0, current_indent + indent_diff)
                                adjusted_lines.append(' ' * new_indent + line.lstrip())
                            else:
                                adjusted_lines.append('')
                        
                        suggestion = '\n'.join(adjusted_lines)
            
            # If suggestion is empty after cleaning, return empty
            if not suggestion or not suggestion.strip():
                return {
                    "suggestion": "",
                    "insert_text": "",
                    "range_start_line": cursor_line,
                    "range_start_column": cursor_column,
                    "range_end_line": cursor_line,
                    "range_end_column": cursor_column
                }
            
            # Calculate the range for the suggestion
            range_start_line = cursor_line
            range_start_column = cursor_column
            
            # Determine what text to insert
            insert_text = suggestion
            
            # For string completions, we might need to handle closing quotes
            if cursor_context['in_string'] and line_suffix:
                # Check if there's a closing quote after cursor
                quote_char = '"' if cursor_context['string_type'] in ['double', 'triple'] else "'"
                # Find the closing quote position
                closing_quote_pos = line_suffix.find(quote_char)
                if closing_quote_pos >= 0:
                    # If suggestion doesn't end with quote, we might need to add it
                    # But actually, let's let the AI handle this - if it suggests the content,
                    # we'll replace up to the closing quote
                    # For now, just replace the content between cursor and closing quote
                    pass
            
            # Calculate end position based on suggestion
            suggestion_lines = suggestion.split('\n')
            if len(suggestion_lines) > 1:
                # Multi-line suggestion
                range_end_line = cursor_line + len(suggestion_lines) - 1
                range_end_column = len(suggestion_lines[-1])
            else:
                # Single line suggestion - end is at cursor + length of suggestion
                range_end_line = cursor_line
                # If cursor is in middle of line, replace text after cursor
                # For string context, be smarter about what to replace
                if cursor_context['in_string'] and line_suffix:
                    # If we're in a string and there's text after, check if we should replace it
                    # For example, if cursor is at print("|"), line_suffix is '")'
                    # We want to replace just the content, keeping the closing quote
                    quote_char = '"' if cursor_context['string_type'] in ['double', 'triple'] else "'"
                    closing_quote_pos = line_suffix.find(quote_char)
                    if closing_quote_pos >= 0:
                        # Replace content up to (but not including) the closing quote
                        range_end_column = cursor_column + closing_quote_pos
                    else:
                        # No closing quote found, replace rest of line
                        range_end_column = len(current_line)
                elif cursor_column < len(current_line):
                    # There's text after cursor - be careful about what we replace
                    # Don't replace if it would break syntax
                    # Check if suffix contains important syntax (closing brackets, etc.)
                    suffix_stripped = line_suffix.strip()
                    
                    # If suffix starts with closing brackets/quotes that match open ones in prefix,
                    # we might want to preserve them
                    if suffix_stripped:
                        # Check if we're in a context where suffix should be preserved
                        # For example, if prefix has "print(" and suffix has ")", we should replace
                        # content between them, not the closing paren
                        if (cursor_context.get('in_parens') and 
                            suffix_stripped.startswith(')') and 
                            not suggestion.endswith(')')):
                            # We're in parens and suffix has closing paren - replace up to it
                            closing_paren_pos = line_suffix.find(')')
                            if closing_paren_pos >= 0:
                                range_end_column = cursor_column + closing_paren_pos
                            else:
                                range_end_column = len(current_line)
                        elif (cursor_context.get('in_brackets') and 
                              suffix_stripped.startswith(']') and 
                              not suggestion.endswith(']')):
                            closing_bracket_pos = line_suffix.find(']')
                            if closing_bracket_pos >= 0:
                                range_end_column = cursor_column + closing_bracket_pos
                            else:
                                range_end_column = len(current_line)
                        elif (cursor_context.get('in_braces') and 
                              suffix_stripped.startswith('}') and 
                              not suggestion.endswith('}')):
                            closing_brace_pos = line_suffix.find('}')
                            if closing_brace_pos >= 0:
                                range_end_column = cursor_column + closing_brace_pos
                            else:
                                range_end_column = len(current_line)
                        else:
                            # Replace rest of line
                            range_end_column = len(current_line)
                    else:
                        # Empty suffix, just append
                        range_end_column = cursor_column + len(suggestion)
                else:
                    # No text after cursor, just append
                    range_end_column = cursor_column + len(suggestion)
            
            # Ensure valid range (end >= start)
            if range_end_line < range_start_line:
                range_end_line = range_start_line
            if range_end_line == range_start_line and range_end_column < range_start_column:
                range_end_column = range_start_column
            
            # Validate suggestion syntax - check if it would create syntax errors
            if suggestion and not self._validate_suggestion_syntax(
                suggestion, line_prefix, line_suffix, cursor_context, current_line, cursor_column
            ):
                # Suggestion would create syntax error, return empty
                return {
                    "suggestion": "",
                    "insert_text": "",
                    "range_start_line": cursor_line,
                    "range_start_column": cursor_column,
                    "range_end_line": cursor_line,
                    "range_end_column": cursor_column
                }
            
            return {
                "suggestion": suggestion,
                "insert_text": insert_text,
                "range_start_line": range_start_line,
                "range_start_column": range_start_column,
                "range_end_line": range_end_line,
                "range_end_column": range_end_column
            }
        except Exception as e:
            raise Exception(f"Failed to generate code completion: {str(e)}")