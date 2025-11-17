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

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None


def truncate_text(text: Optional[str], limit: int = 220) -> str:
    if not text:
        return ''
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3].rstrip() + '...'


class AIService:
    """Service for interacting with local AI models via Ollama"""
    
    CONFIG_DIR_ENV_VAR = "AI_AGENT_CONFIG_DIR"
    DEFAULT_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".offline_ai_agent")
    SETTINGS_FILENAME = "settings.json"
    
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
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:5000")  # Proxy server
        self.ollama_direct = os.getenv("OLLAMA_DIRECT_URL", "http://localhost:11434")  # Direct connection
        self.default_model = os.getenv("DEFAULT_MODEL", "codellama")
        self.current_model = self.default_model
        self.conversation_history = {}
        self.available_models = []
        self._config_dir = os.getenv(self.CONFIG_DIR_ENV_VAR) or self.DEFAULT_CONFIG_DIR
        self._settings_path = os.path.join(self._config_dir, self.SETTINGS_FILENAME)
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
            self.web_search_max_results = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
        except ValueError:
            self.web_search_max_results = 5
        
        self._load_persisted_settings()
    
    def _load_persisted_settings(self) -> None:
        """Load saved connectivity settings from disk if they exist."""
        try:
            if not os.path.exists(self._settings_path):
                return
            with open(self._settings_path, "r", encoding="utf-8") as settings_file:
                data = json.load(settings_file)
            self.ollama_url = data.get("ollama_url", self.ollama_url)
            self.ollama_direct = data.get("ollama_direct_url", self.ollama_direct)
            if "use_proxy" in data:
                self.use_proxy = bool(data["use_proxy"])
            if data.get("default_model"):
                self.default_model = data["default_model"]
            if data.get("current_model"):
                self.current_model = data["current_model"]
            elif data.get("default_model"):
                self.current_model = data["default_model"]
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
        }
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            with open(self._settings_path, "w", encoding="utf-8") as settings_file:
                json.dump(settings_payload, settings_file, indent=2)
        except Exception as error:
            print(f"⚠️  Failed to save settings: {error}")
        
    async def check_ollama_connection(self) -> bool:
        """Check if Ollama is running and accessible"""
        # Try proxy first
        if self.use_proxy:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.ollama_url}/api/tags") as response:
                        if response.status == 200:
                            data = await response.json()
                            self.available_models = [model["name"] for model in data.get("models", [])]
                            print("✅ Connected to Ollama via proxy")
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
                        return True
        except Exception as e:
            print(f"❌ Direct connection failed: {e}")
        
        return False
    
    async def get_available_models(self) -> List[str]:
        """Get list of available models"""
        if not self.available_models:
            await self.check_ollama_connection()
        return self.available_models
    
    async def select_model(self, model_name: str) -> bool:
        """Select a specific model"""
        if model_name in self.available_models:
            self.current_model = model_name
            self.default_model = model_name
            self.save_settings()
            return True
        return False
    
    async def get_status(self) -> Dict[str, Any]:
        """Get current service status"""
        is_connected = await self.check_ollama_connection()
        return {
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
        file_operations: Optional[List[Dict[str, Any]]] = None
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
            path = mention.get("path") if isinstance(mention, dict) else mention
            normalized = self._normalize_path(path)
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
    
    def _parse_response_metadata(self, response: str) -> Tuple[str, Dict[str, Any]]:
        """Extract metadata such as file operations or AI plans from the response"""
        cleaned_response = response
        metadata: Dict[str, Any] = {
            "file_operations": [],
            "ai_plan": None
        }

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

    async def perform_web_search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch search results from DuckDuckGo when browsing is enabled."""
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
        
        if not await self.check_ollama_connection():
            raise Exception("Ollama is not running. Please start Ollama and install a model.")
        
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

        if web_search_mode in ("browser_tab", "google_chrome"):
            try:
                search_results = await self.perform_web_search(message)
                if search_results:
                    context["web_search_results"] = search_results
            except Exception as error:
                context["web_search_error"] = f"{type(error).__name__}: {error}"
        
        # Prepare the prompt with context
        prompt = self._build_prompt(message, context, conversation_history or [])
        
        # Get response from Ollama
        response = await self._call_ollama(prompt)
        
        # Parse metadata from response
        cleaned_response, metadata = self._parse_response_metadata(response)
        
        if not metadata.get("file_operations") and self._should_force_file_operations(message, cleaned_response, context):
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
        
        file_operations = metadata.get("file_operations") or []
        if file_operations:
            result["file_operations"] = file_operations

        if metadata.get("ai_plan"):
            result["ai_plan"] = metadata["ai_plan"]
        
        return result
    
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

        prompt_parts = [
            "You are an expert AI coding assistant similar to Cursor. You help developers with:",
            "- Code generation and completion",
            "- Code analysis and debugging",
            "- Refactoring and optimization",
            "- Explaining complex code",
            "- Creating and editing files",
            "- Best practices and patterns",
            "",
            "IMPORTANT: When the user asks you to create, edit, or modify files, you MUST include",
            "file operations in a special JSON format at the end of your response.",
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
        ]

        if is_agent_mode:
            prompt_parts.extend([
                "AGENT MODE REQUIREMENTS:",
                "- Think step-by-step before responding and explicitly narrate your reasoning.",
                "- Break large requests into 3–6 concrete subtasks that flow through this lifecycle: gather information ➜ plan ➜ implement ➜ verify ➜ report.",
                "- Always begin with at least one information-gathering task (inspect mentioned files, open files, file_tree_structure, or provided web_search_results when browsing is enabled) and actually perform it before you present the plan.",
                "- Maintain a TODO list (max 5 items) where every task has an id, title, and status (`pending`, `in_progress`, or `completed`). Update statuses as you make progress so the user can monitor it.",
                "- Include this plan in the `ai_plan` metadata described below even if no file changes are required.",
                "- After planning, proactively execute the tasks: gather the requested information, produce concrete file edits (via file_operations), or clearly state which files/commands you ran.",
                "- When creating or editing files, emit the necessary file_operations and then immediately move on to the next task—do not stop after the first modification if other tasks remain.",
                "- Only mark a task as `completed` if you actually performed that step in the current response. Mark the task you are actively doing as `in_progress`; leave future work as `pending`.",
                "- Do not leave tasks pending unless you hit a hard blocker; otherwise continue working until every task is marked `completed` within this response.",
                "- Add a verification task (linting, reasoning, or test strategy) before reporting back, and end with a reporting task that summarizes outcomes and remaining risks.",
                "- When the user references a specific file or when composer_mode is true, you MUST produce concrete file edits, not just a plan.",
                "- Plans are only helpful if they are followed by actual file_operations that apply the requested changes.",
                "- When web_search_mode is not 'off', treat the supplied web_search_results as part of your information-gathering step—never claim you lack browsing ability.",
                ""
            ])
        else:
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

        prompt_parts.extend(self.METADATA_FORMAT_LINES)
        prompt_parts.extend([
            "Always provide practical, working code examples. Be concise but thorough.",
            "",
            "ABSOLUTE RULES:",
            "- If the user mentions files via @filename or provides a path, open those files (content is in context) and edit them via file_operations.",
            "- On follow-up requests like \"change it\" or \"update that code\", assume the target file is the current active_file or default_target_file from context and still produce concrete file_operations.",
            "- Do not stop after describing a plan; always include the updated file content in file_operations so the IDE can apply the change.",
            "- Keep natural-language responses short; rely on file_operations to convey the actual modifications.",
            "- When web_search_mode is not 'off', do NOT reply with generic suggestions to visit websites; instead, read the provided web_search_results and answer the user's question as concretely as possible using those results.",
            '- When web_search_mode is not \"off\", statements like \"I cannot browse the internet\" or \"I cannot access external information\" are FALSE. You DO have access to web_search_results; never claim that you lack browsing or external access.',
            ""
        ])

        web_search_mode = (context.get("web_search_mode") or "off").lower()
        if web_search_mode in ("browser_tab", "google_chrome"):
            prompt_parts.extend([
                f"WEB SEARCH ACCESS ENABLED (mode: {web_search_mode}):",
                "- Live DuckDuckGo search results are provided; use them for up-to-date facts.",
                "- Cite the source (site or URL) when referencing a result.",
                "- If more information is required, explicitly state the next search query needed.",
                "- For questions about the current or latest price/value of an asset (e.g. BTC, a stock, or a currency), extract the best available numeric price from the web_search_results and respond with that value, including the currency and a brief note that prices change quickly. Do not merely tell the user to check a website.",
                "- You MUST NOT tell the user to \"search online\" or \"check a website\" when web_search_results are present; instead, summarize those results directly in your own words."
            ])

            results = context.get("web_search_results") or []
            if results:
                prompt_parts.append("Newest web results:")
                for idx, result in enumerate(results[:5], start=1):
                    title = truncate_text(result.get("title") or "Untitled result", 140)
                    snippet = truncate_text(result.get("snippet") or "", 220)
                    url = truncate_text(result.get("url") or result.get("source") or "", 180)
                    prompt_parts.append(f"{idx}. {title} — {snippet} (source: {url})")
            elif context.get("web_search_error"):
                prompt_parts.append(f"Web search error: {truncate_text(context['web_search_error'], 160)}")
            else:
                prompt_parts.append("No web search results were available for this prompt.")

            prompt_parts.append("")
        
        # Add context if available
        if context:
            prompt_parts.append("CONTEXT:")
            if context.get("active_file"):
                prompt_parts.append(f"Active file: {context['active_file']}")
                if context.get("active_file_content"):
                    prompt_parts.append(f"Active file content:\n{context['active_file_content'][:1000]}...")
            
            if context.get("open_files"):
                prompt_parts.append(f"\nOpen files ({len(context['open_files'])}):")
                for file in context["open_files"]:
                    status = "ACTIVE" if file.get("is_active") else "open"
                    prompt_parts.append(f"  [{status}] {file['path']} ({file.get('language', 'unknown')})")
                    if file.get("content") and len(file["content"]) < 500:
                        prompt_parts.append(f"    Content: {file['content'][:200]}...")
            
            if context.get("mentioned_files"):
                prompt_parts.append(f"\nMentioned files (@mentions):")
                for file in context["mentioned_files"]:
                    prompt_parts.append(f"  - {file.get('path', file)}")
                    if file.get("content"):
                        prompt_parts.append(f"    Content: {file['content'][:200]}...")
            
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
    
    def _is_agent_context(self, context: Dict[str, Any]) -> bool:
        if not context:
            return False
        mode_value = (context.get("mode") or "").lower()
        chat_mode_value = (context.get("chat_mode") or "").lower()
        if context.get("composer_mode"):
            return True
        return mode_value in ("agent", "plan") or chat_mode_value in ("agent", "plan")
    
    def _should_force_file_operations(
        self,
        message: str,
        assistant_response: str,
        context: Dict[str, Any]
    ) -> bool:
        if not self._is_agent_context(context):
            return False
        
        combined = f"{message or ''}\n{assistant_response or ''}".lower()
        keywords = [
            "fix", "update", "change", "modify", "refactor",
            "implement", "add ", "remove", "rewrite", "improve",
            "adjust", "patch", "bug", "issue", "error"
        ]
        contains_keyword = any(keyword in combined for keyword in keywords)
        has_code_block = "```" in (assistant_response or "")
        mentions_file_section = "file operation" in combined
        has_context_files = bool(context.get("active_file") or context.get("mentioned_files"))
        
        return contains_keyword or has_code_block or mentions_file_section or has_context_files
    
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
        prompt_lines.append(
            "Provide ONLY the JSON metadata block that includes ai_plan and file_operations as previously specified."
        )
        prompt_lines.extend(self.METADATA_FORMAT_LINES)
        prompt_lines.append("Respond with JSON only. Do not include prose, explanations, or markdown headings.")
        prompt_lines.append("If no file changes are actually required, return an empty file_operations array.")
        
        fallback_prompt = "\n".join(prompt_lines)
        
        try:
            fallback_response = await self._call_ollama(fallback_prompt)
        except Exception as error:
            print(f"Failed to regenerate file operations metadata: {error}")
            return "", {"file_operations": [], "ai_plan": None}
        
        return self._parse_response_metadata(fallback_response)
    
    async def _call_ollama(self, prompt: str) -> str:
        """Make API call to Ollama"""
        payload = {
            "model": self.current_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "max_tokens": 2000
            }
        }
        
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
        
        response = await self._call_ollama(code_prompt)
        return response
    
    async def explain_code(self, code: str, language: str = "python") -> str:
        """Explain what a piece of code does"""
        explain_prompt = f"Explain this {language} code:\n\n```{language}\n{code}\n```"
        response = await self._call_ollama(explain_prompt)
        return response
    
    async def debug_code(self, code: str, error_message: str, language: str = "python") -> str:
        """Help debug code with an error message"""
        debug_prompt = f"Debug this {language} code. Error: {error_message}\n\n```{language}\n{code}\n```"
        response = await self._call_ollama(debug_prompt)
        return response
