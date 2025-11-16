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


class AIService:
    """Service for interacting with local AI models via Ollama"""
    
    def __init__(self):
        # Load from environment variables or use defaults
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:5000")  # Proxy server
        self.ollama_direct = os.getenv("OLLAMA_DIRECT_URL", "http://localhost:11434")  # Direct connection
        self.current_model = os.getenv("DEFAULT_MODEL", "codellama")
        self.conversation_history = {}
        self.available_models = []
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
            add_status("analysis", f"Analyzing request: {message_excerpt}…", 900)
        else:
            add_status("analysis", "Analyzing request…", 900)

        active_file = self._normalize_path(context.get("active_file"))
        if active_file:
            add_status(f"active:{active_file}", f"Reading {active_file}", 800)

        mentioned_files = context.get("mentioned_files") or []
        added_paths = set()
        if active_file:
            added_paths.add(active_file)

        for mention in mentioned_files[:4]:
            path = mention.get("path") if isinstance(mention, dict) else mention
            normalized = self._normalize_path(path)
            if normalized and normalized not in added_paths:
                add_status(f"mention:{normalized}", f"Scanning {normalized}", 650)
                added_paths.add(normalized)

        add_status("context", "Reviewing project context and open files", 700)

        mode_value = (context.get("mode") or context.get("chat_mode") or "").lower()
        if mode_value in ("agent", "plan") or context.get("composer_mode"):
            add_status("planning", "Planning next implementation steps", 850)
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

        add_status("finalizing", "Reviewing updates and finalizing answer", 500)

        return statuses
    
    def _parse_response_metadata(self, response: str) -> Tuple[str, Dict[str, Any]]:
        """Extract metadata such as file operations or AI plans from the response"""
        cleaned_response = response
        metadata: Dict[str, Any] = {
            "file_operations": [],
            "ai_plan": None
        }

        import re

        def extract_from_json(json_str: str) -> bool:
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                return False

            found = False
            if isinstance(data, dict):
                file_ops = data.get("file_operations")
                ai_plan = data.get("ai_plan")

                if isinstance(file_ops, list):
                    metadata["file_operations"].extend(file_ops)
                    found = True

                if isinstance(ai_plan, dict):
                    metadata["ai_plan"] = ai_plan
                    found = True
            return found

        # Markdown ```json blocks
        json_block_pattern = r'```json\s*({[^`]+})\s*```'
        for match in re.finditer(json_block_pattern, response, re.DOTALL):
            block = match.group(0)
            json_str = match.group(1)
            if extract_from_json(json_str):
                cleaned_response = cleaned_response.replace(block, "").strip()

        # Inline fallback for older responses
        inline_patterns = [
            r'\{[^{}]*"file_operations"[^{}]*\[[^\]]+\][^{}]*\}',
            r'\{[^{}]*"ai_plan"[^{}]*\}'
        ]
        for pattern in inline_patterns:
            for match in re.finditer(pattern, cleaned_response, re.DOTALL):
                json_candidate = match.group(0)
                if extract_from_json(json_candidate):
                    cleaned_response = cleaned_response.replace(json_candidate, "").strip()

        return cleaned_response, metadata

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
        
        # Prepare the prompt with context
        prompt = self._build_prompt(message, context or {}, conversation_history or [])
        
        # Get response from Ollama
        response = await self._call_ollama(prompt)
        
        # Parse metadata from response
        cleaned_response, metadata = self._parse_response_metadata(response)
        
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
        ]

        if is_agent_mode:
            prompt_parts.extend([
                "AGENT MODE REQUIREMENTS:",
                "- Think step-by-step before responding.",
                "- Create a concise TODO list (max 5 items) describing how you will fulfill the request.",
                "- Each task must include an id, title, and status (`pending`, `in_progress`, or `completed`).",
                "- Include this plan in the `ai_plan` metadata described below even if no file changes are required.",
                ""
            ])
        else:
            prompt_parts.append("If you develop a TODO plan, include it via the `ai_plan` metadata described below.")
            prompt_parts.append("")

        prompt_parts.extend([
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
            "Always provide practical, working code examples. Be concise but thorough.",
            ""
        ])
        
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
