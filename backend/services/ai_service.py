"""
AI Service for Offline AI Agent
Handles communication with local Ollama models
"""

import asyncio
import aiohttp
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
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
        
        # Store conversation
        self.conversation_history[conversation_id] = {
            "messages": conversation_history or [],
            "last_updated": datetime.now().isoformat()
        }
        
        return {
            "content": response,
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
            "context_used": context
        }
    
    def _build_prompt(
        self, 
        message: str, 
        context: Dict[str, Any], 
        history: List[Dict[str, str]]
    ) -> str:
        """Build a comprehensive prompt with context"""
        
        prompt_parts = [
            "You are an expert AI coding assistant similar to Cursor. You help developers with:",
            "- Code generation and completion",
            "- Code analysis and debugging", 
            "- Refactoring and optimization",
            "- Explaining complex code",
            "- Best practices and patterns",
            "",
            "Always provide practical, working code examples. Be concise but thorough.",
            ""
        ]
        
        # Add context if available
        if context:
            prompt_parts.append("CONTEXT:")
            if "current_file" in context:
                prompt_parts.append(f"Current file: {context['current_file']}")
            if "project_type" in context:
                prompt_parts.append(f"Project type: {context['project_type']}")
            if "selected_code" in context:
                prompt_parts.append(f"Selected code:\n{context['selected_code']}")
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
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("response", "No response generated")
                    else:
                        error_text = await response.text()
                        raise Exception(f"Ollama API error: {response.status} - {error_text}")
        except asyncio.TimeoutError:
            raise Exception("Request timed out. The model might be too slow or overloaded.")
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
