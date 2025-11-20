"""
AI Service for Offline AI Agent
Handles communication with local Ollama models
"""

import asyncio
import aiohttp
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import os
import re
import time

try:
    from duckduckgo_search import DDGS
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
    """Service for interacting with AI models via Ollama or Hugging Face"""
    
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
        '      "content": "file content here"',
        '    }',
        '  ]',
        "}",
        "```",
        "",
    ]
    
    def __init__(self):
        # Load from environment variables or use defaults
        self.provider = (os.getenv("LLM_PROVIDER", "ollama") or "ollama").lower()
        if self.provider not in ("ollama", "huggingface"):
            self.provider = "ollama"
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:5000")  # Proxy server
        self.ollama_direct = os.getenv("OLLAMA_DIRECT_URL", "http://localhost:11434")  # Direct connection
        self.default_model = os.getenv("DEFAULT_MODEL", "codellama")
        self.current_model = self.default_model
        self.hf_api_key = os.getenv("HF_API_KEY", "")
        self.hf_model = os.getenv("HF_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
        self.hf_base_url = os.getenv("HF_BASE_URL", "").strip()
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
            self.hf_max_tokens = int(os.getenv("HF_MAX_TOKENS", "2048"))
        except ValueError:
            self.hf_max_tokens = 2048
        try:
            self.web_search_max_results = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
        except ValueError:
            self.web_search_max_results = 5

        self.hardware_threads = os.cpu_count() or 8
        self.base_generation_options = self._load_generation_options()
        self.large_model_thread_count = max(8, min(self.hardware_threads, 32))
        self._hf_client = None
        self._hf_client_cache_key: Optional[Tuple[str, str, str]] = None
        
        # MCP integration
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
    
    def set_mcp_tools(self, mcp_tools: Optional[MCPServerTools]):
        """Set MCP tools for the AI service"""
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
            if provider_value not in ("ollama", "huggingface"):
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
            "num_predict": read_int("OLLAMA_NUM_PREDICT", 4096),
            "num_ctx": read_int("OLLAMA_NUM_CTX", 4096),
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
            options["num_ctx"] = max(options.get("num_ctx", 2048), 4096)
            options["num_batch"] = max(options.get("num_batch", 256), 512)
            options["num_thread"] = max(
                options.get("num_thread", 8),
                self.large_model_thread_count,
            )
            options["num_predict"] = min(options.get("num_predict", 1024), 768)

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
        return await self.check_ollama_connection(force=force)
    
    async def get_available_models(self) -> List[str]:
        """Get list of available models"""
        if self.provider == "huggingface":
            return [self.hf_model] if self.hf_model else []
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

        active_file = self._normalize_path(context.get("active_file"))
        if active_file:
            add_status(f"grep-active:{active_file}", f"Grepping {active_file} for relevant code", 750)

        mentioned_files = context.get("mentioned_files") or []
        added_paths = set()
        if active_file:
            added_paths.add(active_file)

        for mention in mentioned_files[:4]:
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
            for op in file_operations[:6]:
                op_type = (op.get("type") or "").lower()
                path = self._normalize_path(op.get("path")) or "workspace"
                if op_type == "delete_file":
                    label = f"Preparing removal for {path}"
                elif op_type == "create_file":
                    label = f"Drafting new file {path}"
                else:
                    label = f"Updating {path}"
                add_status(f"op:{path}", label, 600)
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
        
        # In ASK mode, never extract file operations or plans
        is_ask_mode = context and self._is_ask_context(context)
        if is_ask_mode:
            return cleaned_response, metadata

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
                op_type = (obj.get("type") or "").lower()
                path = obj.get("path")
                return bool(op_type and path)

            # Canonical metadata shape
            if isinstance(data, dict):
                file_ops = data.get("file_operations")
                ai_plan = data.get("ai_plan")

                if isinstance(file_ops, list):
                    metadata["file_operations"].extend(file_ops)
                    found = True

                if isinstance(ai_plan, dict):
                    metadata["ai_plan"] = ai_plan
                    found = True

                # Convenience: single file operation object at top level
                if not found and is_file_op(data):
                    metadata["file_operations"].append(data)
                    found = True

            # Convenience: top-level list of file-operations
            if isinstance(data, list):
                ops = [op for op in data if is_file_op(op)]
                if ops:
                    metadata["file_operations"].extend(ops)
                    found = True

            return found

        # First, try to interpret the entire response as JSON.
        # This covers the common case where the model returns *only* a metadata
        # object (with ai_plan / file_operations) and no surrounding prose.
        whole = response.strip()
        if whole:
            if extract_from_json(whole):
                # The whole response was metadata; no user-visible text remains.
                return "", metadata

        # Markdown ```json blocks (be flexible about the fence language and contents)
        # We capture the smallest possible fenced block so we don't accidentally
        # consume surrounding narrative text.
        json_block_pattern = r'```(?:json|JSON)?\s*([\s\S]*?)```'
        for match in re.finditer(json_block_pattern, response, re.DOTALL):
            block = match.group(0)
            json_str = match.group(1).strip()
            if extract_from_json(json_str):
                cleaned_response = cleaned_response.replace(block, "").strip()

        # Inline fallback for responses that embed JSON without fences.
        # These patterns intentionally allow nested braces by using a
        # non-greedy "match anything" approach.
        inline_patterns = [
            # Canonical metadata object
            r'\{[\s\S]*?"file_operations"[\s\S]*?\}',
            r'\{[\s\S]*?"ai_plan"[\s\S]*?\}',
            # Convenience: any JSON object that looks like a file operation
            r'\{[\s\S]*?"type"\s*:\s*"[a-zA-Z_]+?"[\s\S]*?"path"\s*:\s*"[^\"]+"[\s\S]*?\}',
        ]
        for pattern in inline_patterns:
            for match in re.finditer(pattern, cleaned_response, re.DOTALL):
                json_candidate = match.group(0).strip()
                if extract_from_json(json_candidate):
                    cleaned_response = cleaned_response.replace(json_candidate, "").strip()

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
        json_block_pattern = r'```(?:json|text|python)?\s*\{[\s\S]*?"(?:ai_plan|file_operations)"[\s\S]*?\}[\s\S]*?```'
        response = re.sub(json_block_pattern, '', response, flags=re.IGNORECASE | re.DOTALL)
        
        # Remove standalone JSON objects with metadata
        json_metadata_pattern = r'\{[\s\S]*?"(?:ai_plan|file_operations)"[\s\S]*?\}'
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
        ]
        
        reporting_patterns = [
            r'^(summary:|summary of|in summary|to summarize)',
            r'^(report:|reporting:|final report|completion report)',
            r'^(i\'ve completed|i have completed|i completed|completed:)',
            r'^(done:|finished:|completed tasks:)',
            r'^(results:|outcomes:|conclusion:)',
            r'^(all tasks are|all steps are|everything is)',
        ]
        
        # Section headers that indicate thinking/planning/reporting
        thinking_headers = [
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
            '## plan',
            '## planning',
            '## strategy',
            '## approach',
            '## steps',
            '## tasks',
            '### plan',
            '### planning',
            '### strategy',
            '### approach',
            '### steps',
            '### tasks',
        ]
        
        reporting_headers = [
            '## report',
            '## summary',
            '## results',
            '## conclusion',
            '## completion',
            '### report',
            '### summary',
            '### results',
            '### conclusion',
            '### completion',
        ]
        
        file_operations_headers = [
            '## file operations',
            '## file operation',
            '### file operations',
            '### file operation',
            '## file operations:',
            '### file operations:',
        ]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            line_lower = line.lower().strip()
            
            # Check for duplicate section headers (remove duplicates)
            if line_lower.startswith('##') or line_lower.startswith('###'):
                section_key = line_lower[:50]  # Use first 50 chars as key
                if section_key in seen_sections:
                    # Skip duplicate section
                    i += 1
                    # Skip until next section or end
                    while i < len(lines) and not (lines[i].strip().startswith('##') or lines[i].strip().startswith('###')):
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
            if line.strip().startswith('##') or line.strip().startswith('###'):
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
                if line.strip().startswith('##') or line.strip().startswith('###'):
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
            
            # Keep the line
            filtered_lines.append(line)
            i += 1
        
        result = '\n'.join(filtered_lines).strip()
        
        # Remove unhelpful phrases that don't provide answers
        unhelpful_phrases = [
            r'please provide more (context|information|details)',
            r'i need (more|additional) (information|context|details)',
            r'to complete (this|the) task, i need',
            r'specify the next step',
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
            if line_lower in ('file operations', 'file operation', 'project overview', 'verification'):
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
            
            # Last resort: return original if filtering removed everything
            return response.strip()
        
        return result

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
        conversation_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Process a message and get AI response"""
        
        if self.provider == "ollama":
            if not await self.check_ollama_connection():
                raise Exception("Ollama is not running. Please start Ollama and install a model.")
        elif self.provider == "huggingface":
            if InferenceClient is None:
                raise Exception("huggingface-hub is not installed. Please install it to use Hugging Face models.")
            if not self.hf_api_key:
                raise Exception("Hugging Face API key (HF_API_KEY) is not configured.")
            if not self.hf_model:
                raise Exception("Hugging Face model name (HF_MODEL) is not configured.")
        else:
            raise Exception(f"Unsupported LLM provider: {self.provider}")
        
        # Create conversation ID if not provided
        conversation_id = str(uuid.uuid4())

        # Clone and enrich context
        context = dict(context or {})
        web_search_mode = (context.get("web_search_mode") or "off").lower()
        context["web_search_mode"] = web_search_mode
        
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
        needs_web_search = self._detect_web_search_needed(message, web_search_mode)
        if needs_web_search:
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
                        # Parse the formatted result back to structured data
                        # The MCP tool returns formatted text, so we store it for the prompt
                        context["web_search_results_mcp"] = result_text
                        context["web_search_mode"] = "auto"  # Mark as auto-triggered
                        if web_search_mode == "off":
                            web_search_mode = "auto"
                            context["web_search_mode"] = "auto"
                    else:
                        error_msg = tool_results[0].get("result", "Unknown error") if tool_results else "No results"
                        context["web_search_error"] = error_msg
                except Exception as error:
                    context["web_search_error"] = f"{type(error).__name__}: {error}"
            else:
                # Fallback: if MCP not available, use direct search (shouldn't happen in production)
                try:
                    search_query = self._extract_search_query(message)
                    search_results = await self.perform_web_search(search_query)
                    if search_results:
                        context["web_search_results"] = search_results
                        context["web_search_mode"] = "auto"
                        if web_search_mode == "off":
                            web_search_mode = "auto"
                            context["web_search_mode"] = "auto"
                except Exception as error:
                    context["web_search_error"] = f"{type(error).__name__}: {error}"
        elif web_search_mode in ("browser_tab", "google_chrome"):
            # Explicit web search mode - use MCP tools
            if self.is_mcp_enabled():
                try:
                    # Use MCP web_search tool
                    tool_call = {
                        "name": "web_search",
                        "arguments": {
                            "query": message,
                            "max_results": self.web_search_max_results,
                            "search_type": "text"
                        }
                    }
                    
                    tool_results = await self.mcp_client.execute_tool_calls(
                        [tool_call],
                        allow_write=True
                    )
                    
                    if tool_results and not tool_results[0].get("error", False):
                        context["web_search_results_mcp"] = tool_results[0].get("result", "")
                    else:
                        error_msg = tool_results[0].get("result", "Unknown error") if tool_results else "No results"
                        context["web_search_error"] = error_msg
                except Exception as error:
                    context["web_search_error"] = f"{type(error).__name__}: {error}"
            else:
                # Fallback to direct search
                try:
                    search_results = await self.perform_web_search(message)
                    if search_results:
                        context["web_search_results"] = search_results
                except Exception as error:
                    context["web_search_error"] = f"{type(error).__name__}: {error}"
        
        # Prepare the prompt with context
        prompt = self._build_prompt(message, context, conversation_history or [])
        
        # Get initial response from configured provider
        response = await self._call_model(prompt)
        
        # Handle MCP tool calls if enabled
        if self.is_mcp_enabled():
            tool_calls = self.mcp_client.parse_tool_calls_from_response(response)
            if tool_calls:
                # Execute tool calls
                allow_write = self._can_modify_files(context)
                tool_results = await self.mcp_client.execute_tool_calls(tool_calls, allow_write=allow_write)
                
                # If tools were executed, get a follow-up response with results
                if tool_results and not all(r.get("error", False) for r in tool_results):
                    tool_results_text = self.mcp_client.format_tool_results_for_prompt(tool_results)
                    
                    # Build follow-up prompt with tool results
                    follow_up_prompt = f"{prompt}\n\n{response}\n\n{tool_results_text}\n\nPlease use the tool execution results above to provide a complete answer."
                    
                    # Get follow-up response that incorporates tool results
                    follow_up_response = await self._call_model(follow_up_prompt)
                    response = follow_up_response  # Use the follow-up response
        
        # Parse metadata from response (pass context to block extraction in ASK mode)
        cleaned_response, metadata = self._parse_response_metadata(response, context)
        
        # Filter out thinking/planning/reporting content
        cleaned_response = self._filter_thinking_content(cleaned_response, context)
        
        # CRITICAL: Ensure ASK mode NEVER has file operations or plans, even if the AI generated them
        if self._is_ask_context(context):
            metadata["file_operations"] = []
            metadata["ai_plan"] = None
            # Also strip any file operation mentions from the response text
            cleaned_response = self._strip_file_operation_mentions(cleaned_response)
        
        # Never generate file operations in ASK mode
        if self._can_modify_files(context) and not metadata.get("file_operations") and self._should_force_file_operations(message, cleaned_response, context):
            fallback_cleaned, fallback_metadata = await self._generate_file_operations_metadata(
                message=message,
                context=context,
                history=conversation_history or [],
                assistant_response=cleaned_response
            )
            fallback_ops = fallback_metadata.get("file_operations") or []
            if fallback_ops:
                metadata["file_operations"] = fallback_ops
                if fallback_metadata.get("ai_plan") and not metadata.get("ai_plan"):
                    metadata["ai_plan"] = fallback_metadata["ai_plan"]
                cleaned_response = (
                    f"{cleaned_response}\n\n_(Generated concrete file operations automatically.)_"
                    if cleaned_response else "_(Generated concrete file operations automatically.)_"
                )
        
        # Store conversation
        self.conversation_history[conversation_id] = {
            "messages": conversation_history or [],
            "last_updated": datetime.now().isoformat()
        }
        
        result = {
            "content": cleaned_response,
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
            "context_used": context
        }
        
        # Only include file_operations and ai_plan if file modifications are allowed
        if self._can_modify_files(context):
            file_operations = metadata.get("file_operations") or []
            if file_operations:
                result["file_operations"] = file_operations

            if metadata.get("ai_plan"):
                result["ai_plan"] = metadata["ai_plan"]
        else:
            # Explicitly set to None/null in ASK mode to prevent any confusion
            result["file_operations"] = None
            result["ai_plan"] = None
        
        return result
    
    def _strip_file_operation_mentions(self, response: str) -> str:
        """Remove any mentions of file operations from responses in ASK mode"""
        if not response:
            return response
        
        # Remove common file operation phrases
        patterns_to_remove = [
            r'```json\s*\{[^}]*"file_operations"[^}]*\}[\s\S]*?```',
            r'```json\s*\{[^}]*"ai_plan"[^}]*\}[\s\S]*?```',
            r'\{[^}]*"file_operations"[^}]*\}',
            r'\{[^}]*"ai_plan"[^}]*\}',
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
        history: List[Dict[str, str]]
    ) -> str:
        """Build a comprehensive prompt with context"""
        
        mode_value = (context.get("mode") or "").lower()
        chat_mode_value = (context.get("chat_mode") or "").lower()
        is_composer = bool(context.get("composer_mode"))
        is_agent_mode = is_composer or mode_value in ("agent", "plan") or chat_mode_value in ("agent", "plan")
        is_ask_mode = (not is_agent_mode) and (mode_value == "ask" or chat_mode_value == "ask")

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
        
        # Add MCP tools description if enabled
        if self.is_mcp_enabled():
            mcp_tools_desc = self.mcp_client.get_tools_description()
            if mcp_tools_desc:
                prompt_parts.extend([
                    "",
                    "=" * 80,
                    "MCP TOOLS AVAILABLE (You have NO direct internet access - use these tools):",
                    "=" * 80,
                    "",
                    mcp_tools_desc,
                    "",
                    "CRITICAL: You do NOT have direct internet access. To search the web, you MUST use the web_search MCP tool.",
                    "",
                    "You can use these tools by including tool calls in your response.",
                    "Example tool call format:",
                    '<tool_call name="read_file" args=\'{"path": "example.py"}\' />',
                    '<tool_call name="web_search" args=\'{"query": "current bitcoin price", "max_results": 5}\' />',
                    "",
                    "When you need to perform operations like:",
                    "- Reading files: use read_file tool",
                    "- Searching code: use grep_code tool",
                    "- Searching the web: use web_search tool (REQUIRED for any internet information)",
                    "- Executing commands: use execute_command tool",
                    "",
                    "Use the appropriate MCP tools instead of just describing what should be done.",
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
                "2. NEVER include file_operations or ai_plan metadata in your response (not in JSON, not in code blocks, not anywhere).",
                "3. NEVER include JSON objects with 'file_operations' or 'ai_plan' keys.",
                "4. NEVER generate code blocks that look like file operation metadata.",
                "5. If the user asks for file modifications, explain that ASK mode is read-only and suggest switching to Agent mode.",
                "6. Provide only a direct, concise answer to the user's question.",
                "7. DO NOT include thinking, planning, or reasoning prose—just the answer.",
                "8. You may include small code snippets for illustration, but never instruct the IDE to modify files.",
                "",
                "SYSTEM ENFORCEMENT: Even if you generate file_operations, they will be automatically stripped and ignored in ASK mode.",
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

        if is_agent_mode:
            prompt_parts.extend([
                "AGENT MODE REQUIREMENTS:",
                "- Think step-by-step internally, but DO NOT include thinking/planning/reporting prose in your response text.",
                "- Put your thinking process, planning steps, and task breakdowns in the `ai_plan` metadata only.",
                "- Your response text should contain only the actual answer, code, explanations, or results—not your internal reasoning process.",
                "- Break large requests into 3–6 concrete subtasks that flow through this lifecycle: gather information ➜ plan ➜ implement ➜ verify ➜ report.",
                "- Always begin with at least one information-gathering task (inspect mentioned files, open files, file_tree_structure, or provided web_search_results when browsing is enabled) and actually perform it before you present the plan.",
                "- Maintain a TODO list (max 5 items) where every task has an id, title, and status (`pending`, `in_progress`, or `completed`). Update statuses as you make progress so the user can monitor it.",
                "- Include this plan in the `ai_plan` metadata described below even if no file changes are required.",
                "- After planning, proactively execute the tasks: gather the requested information, produce concrete file edits (via file_operations), or clearly state which files/commands you ran.",
                "- Treat agent mode as fully autonomous execution: do NOT ask the user follow-up questions unless the request is self-contradictory or unsafe. Instead, state reasonable assumptions and continue working.",
                "- When the user responds with short inputs like `1`, `2`, `option A`, or repeats one of your earlier choices, interpret that as their selection instead of asking the same question again.",
                "- When creating or editing files, emit the necessary file_operations and then immediately move on to the next task—do not stop after the first modification if other tasks remain.",
                "- Keep edits surgical: update only the portions of each file that the user asked to change and preserve the rest of the file exactly as-is.",
                "- Only mark a task as `completed` if you actually performed that step in the current response. Mark the task you are actively doing as `in_progress`; leave future work as `pending`.",
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
                "- Explain briefly why the new file is necessary before presenting the code.",
                ""
            ])

        if not is_ask_mode:
            prompt_parts.extend(self.METADATA_FORMAT_LINES)
            prompt_parts.extend([
                "Always provide practical, working code examples. Be concise but thorough.",
                "",
                "ABSOLUTE RULES:",
                "- If the user mentions files via @filename or provides a path, open those files (content is in CONTEXT) and edit them via file_operations.",
                "- Do NOT reply with generic statements like 'we need to inspect the file' or 'we need to access the file'—assume the IDE has already provided the relevant file contents in CONTEXT and operate directly on that content.",
                "- On follow-up requests like \"change it\" or \"update that code\", assume the target file is the current active_file or default_target_file from context and still produce concrete file_operations.",
                "- Do not stop after describing a plan; always include the updated file content in file_operations so the IDE can apply the change.",
                "- Keep natural-language responses short; rely on file_operations to convey the actual modifications.",
                "- When web_search_mode is not 'off', do NOT reply with generic suggestions to visit websites; instead, read the provided web_search_results and answer the user's question as concretely as possible using those results.",
                '- When web_search_mode is not "off", statements like "I cannot browse the internet" or "I cannot access external information" are FALSE. You DO have access to web_search_results; never claim that you lack browsing or external access.',
                ""
            ])
        else:
            prompt_parts.extend([
                "Always provide practical, working explanations. Be concise but thorough.",
                "",
                "ABSOLUTE RULES FOR ASK MODE:",
                "- Reference the provided context (files, history, or web results) to answer directly.",
                "- Never include ai_plan or file_operations metadata; respond with natural language only.",
                "- If fulfilling the request would require editing files, explain the limitation and recommend switching to Agent mode instead of fabricating edits.",
                ""
            ])


        web_search_mode = (context.get("web_search_mode") or "off").lower()
        if web_search_mode in ("browser_tab", "google_chrome", "auto"):
            mode_label = "auto-triggered" if web_search_mode == "auto" else web_search_mode
            prompt_parts.extend([
                f"WEB SEARCH ACCESS ENABLED (mode: {mode_label}):",
                "- Live DuckDuckGo search results are provided; use them for up-to-date facts.",
                "- Cite the source (site or URL) when referencing a result.",
                "- If more information is required, explicitly state the next search query needed.",
                "- For questions about the current or latest price/value of an asset (e.g. BTC, a stock, or a currency), extract the best available numeric price from the web_search_results and respond with that value, including the currency and a brief note that prices change quickly. Do not merely tell the user to check a website.",
                "- You MUST NOT tell the user to \"search online\" or \"check a website\" when web_search_results are present; instead, summarize those results directly in your own words.",
                "- CRITICAL: If web_search_results are provided, you MUST use them. Never say 'no web-search results were provided' if results are shown below."
            ])

            # Check for MCP web search results (preferred) or direct results
            mcp_results = context.get("web_search_results_mcp")
            direct_results = context.get("web_search_results") or []
            
            if mcp_results:
                # MCP tool returned formatted results
                prompt_parts.append("")
                prompt_parts.append("=" * 80)
                prompt_parts.append("WEB SEARCH RESULTS (from MCP tools - USE THESE IN YOUR RESPONSE):")
                prompt_parts.append("=" * 80)
                prompt_parts.append("")
                prompt_parts.append(mcp_results)
                prompt_parts.append("")
                prompt_parts.append("=" * 80)
                prompt_parts.append("")
                prompt_parts.append("IMPORTANT: You MUST use the information from these web search results in your response.")
                prompt_parts.append("Extract specific facts, numbers, prices, or data from the results above.")
                prompt_parts.append("Do NOT say that no results were provided - they are shown above.")
                prompt_parts.append("")
            elif direct_results:
                # Direct search results (fallback)
                prompt_parts.append("")
                prompt_parts.append("=" * 80)
                prompt_parts.append("WEB SEARCH RESULTS (USE THESE IN YOUR RESPONSE):")
                prompt_parts.append("=" * 80)
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
                prompt_parts.append("IMPORTANT: You MUST use the information from these web search results in your response.")
                prompt_parts.append("Extract specific facts, numbers, prices, or data from the results above.")
                prompt_parts.append("Do NOT say that no results were provided - they are shown above.")
                prompt_parts.append("")
            elif context.get("web_search_error"):
                prompt_parts.append(f"Web search error: {truncate_text(context['web_search_error'], 160)}")
                prompt_parts.append("You may need to ask the user to try again or provide more specific information.")
                if self.is_mcp_enabled():
                    prompt_parts.append("Note: If you need web search, you can use the web_search MCP tool in your response.")
            else:
                if web_search_mode == "auto":
                    prompt_parts.append("Note: Web search was attempted but no results were returned.")
                    if self.is_mcp_enabled():
                        prompt_parts.append("You can use the web_search MCP tool to perform searches if needed.")
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
        prompt_parts.append(f"USER REQUEST: {message}")
        prompt_parts.append("")
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
            "new app",
            "upgrade",
            "enhance",
            "rename",
            "delete",
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
        
        # If web search is explicitly enabled, use it
        if web_search_mode in ("browser_tab", "google_chrome"):
            return True
        
        # If explicitly disabled, don't auto-trigger
        if web_search_mode == "off":
            # But still check if it's clearly needed (user can override)
            pass
        
        normalized = message.lower()
        
        # Price/Value queries
        price_patterns = [
            r'\b(price|cost|value|worth|rate|exchange rate)\b.*\b(bitcoin|btc|ethereum|eth|crypto|stock|currency|usd|eur|gbp|jpy)\b',
            r'\b(bitcoin|btc|ethereum|eth)\b.*\b(price|cost|value|worth|rate)\b',
            r'\b(current|latest|today|now)\b.*\b(price|value|rate)\b',
            r'\bhow much.*\b(bitcoin|btc|ethereum|eth|stock|currency)\b',
            r'\bwhat.*\b(bitcoin|btc|ethereum|eth)\b.*\b(price|worth|value)\b',
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
        
        # "What is X" queries that might need current info
        what_is_patterns = [
            r'\bwhat is\b.*\b(bitcoin|btc|ethereum|eth|stock|company|ceo|president)\b',
            r'\bwho is\b.*\b(current|now|today)\b',
        ]
        
        all_patterns = price_patterns + news_patterns + realtime_patterns + what_is_patterns
        
        for pattern in all_patterns:
            if re.search(pattern, normalized, re.IGNORECASE):
                return True
        
        # Check for explicit search requests
        search_keywords = [
            "search for",
            "look up",
            "find information about",
            "what's the current",
            "what's the latest",
            "check the price",
            "get the price",
        ]
        
        if any(keyword in normalized for keyword in search_keywords):
            return True
        
        return False
    
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
        change_intent = self._has_change_intent(combined)
        analysis_only = not change_intent and self._is_analysis_request(message)
        has_code_block = "```" in (assistant_response or "")
        mentions_file_section = "file operation" in combined
        
        if has_code_block or mentions_file_section:
            return True
        
        if analysis_only:
            return False
        
        return change_intent
    
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
            "- If the request requires new functionality, include at least one `create_file` or `edit_file` entry with the complete file contents (no placeholders like TODO).",
            "- Assume reasonable defaults instead of asking the user more questions.",
            "- Only leave file_operations empty if the user explicitly said that no code changes are needed.",
            "- Keep the ai_plan consistent with the work you are now completing (mark finished steps as completed).",
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
            fallback_response = await self._call_model(fallback_prompt)
        except Exception as error:
            print(f"Failed to regenerate file operations metadata: {error}")
            return "", {"file_operations": [], "ai_plan": None}
        
        return self._parse_response_metadata(fallback_response, context)
    
    async def _call_model(self, prompt: str) -> str:
        if self.provider == "huggingface":
            return await self._call_huggingface(prompt)
        return await self._call_ollama(prompt)

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

    async def _call_ollama(self, prompt: str) -> str:
        """Make API call to Ollama"""
        generation_options, keep_alive = self._build_generation_options_for_model()
        payload = {
            "model": self.current_model,
            "prompt": prompt,
            "stream": False,
            "options": generation_options
        }
        if keep_alive:
            payload["keep_alive"] = keep_alive
        
        # Choose URL based on connection method
        url = self.ollama_url if self.use_proxy else self.ollama_direct
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("response", "No response generated")
                    else:
                        error_text = await response.text()
                        raise Exception(f"Ollama API error: {response.status} - {error_text}")
        except asyncio.TimeoutError:
            raise Exception(
                f"Request timed out after {self.request_timeout}s. "
                "The model might be too slow or overloaded. "
                "You can increase OLLAMA_REQUEST_TIMEOUT or try a smaller prompt."
            )
        except Exception as e:
            raise Exception(f"Error calling Ollama: {str(e)}")
    
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
