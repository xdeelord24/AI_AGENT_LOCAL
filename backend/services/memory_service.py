"""
Memory Service for AI Agent
Manages user memories and chat history references

Features:
- Store explicit user memories (name, preferences, etc.)
- Reference chat history for context
- Memory persistence and retrieval
"""

import json
import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Memory Service - Manages user memories and chat history references
    
    This service enables the AI to:
    - Remember explicit user details (saved memories)
    - Reference past conversations for context
    - Provide personalized responses based on stored information
    """
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize memory service
        
        Args:
            storage_dir: Directory to store memory data (default: ~/.offline_ai_agent/memories)
        """
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            config_dir = os.getenv("AI_AGENT_CONFIG_DIR") or os.path.join(
                os.path.expanduser("~"), ".offline_ai_agent"
            )
            self.storage_dir = Path(config_dir) / "memories"
        
        # Ensure storage directory exists
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Memory files
        self.memories_file = self.storage_dir / "memories.json"
        self.settings_file = self.storage_dir / "memory_settings.json"
        
        # Default settings
        self.default_settings = {
            "reference_saved_memories": True,
            "reference_chat_history": True
        }
        
        # Load settings
        self.settings = self._load_settings()
        
        # Load memories
        self.memories: List[Dict[str, Any]] = self._load_memories()
    
    def _load_settings(self) -> Dict[str, bool]:
        """Load memory settings from disk"""
        try:
            if self.settings_file.exists():
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    # Ensure all default settings are present
                    for key, value in self.default_settings.items():
                        if key not in settings:
                            settings[key] = value
                    return settings
        except Exception as e:
            logger.error(f"Error loading memory settings: {e}")
        
        return self.default_settings.copy()
    
    def _save_settings(self) -> None:
        """Save memory settings to disk"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving memory settings: {e}")
    
    def _load_memories(self) -> List[Dict[str, Any]]:
        """Load memories from disk"""
        try:
            if self.memories_file.exists():
                with open(self.memories_file, 'r', encoding='utf-8') as f:
                    memories = json.load(f)
                    # Ensure memories is a list
                    if isinstance(memories, list):
                        return memories
                    return []
        except Exception as e:
            logger.error(f"Error loading memories: {e}")
        
        return []
    
    def _save_memories(self) -> None:
        """Save memories to disk"""
        try:
            with open(self.memories_file, 'w', encoding='utf-8') as f:
                json.dump(self.memories, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving memories: {e}")
    
    def get_settings(self) -> Dict[str, bool]:
        """Get current memory settings"""
        return self.settings.copy()
    
    def update_settings(self, reference_saved_memories: Optional[bool] = None,
                       reference_chat_history: Optional[bool] = None) -> Dict[str, bool]:
        """
        Update memory settings
        
        Args:
            reference_saved_memories: Whether to use saved memories
            reference_chat_history: Whether to reference chat history
            
        Returns:
            Updated settings dictionary
        """
        if reference_saved_memories is not None:
            self.settings["reference_saved_memories"] = reference_saved_memories
        if reference_chat_history is not None:
            self.settings["reference_chat_history"] = reference_chat_history
        
        self._save_settings()
        return self.get_settings()
    
    def get_memories(self) -> List[Dict[str, Any]]:
        """Get all saved memories"""
        return self.memories.copy()
    
    def add_memory(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Add a new memory
        
        Args:
            content: The memory content (e.g., "User's name is John")
            metadata: Optional metadata (e.g., {"category": "personal", "tags": ["name"]})
            
        Returns:
            Created memory dictionary
        """
        memory = {
            "id": f"mem_{datetime.now().timestamp()}_{len(self.memories)}",
            "content": content,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        self.memories.append(memory)
        self._save_memories()
        
        logger.info(f"Added memory: {content[:50]}...")
        return memory
    
    def update_memory(self, memory_id: str, content: Optional[str] = None,
                     metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Update an existing memory
        
        Args:
            memory_id: ID of the memory to update
            content: New content (optional)
            metadata: New metadata (optional, will merge with existing)
            
        Returns:
            Updated memory dictionary or None if not found
        """
        for memory in self.memories:
            if memory["id"] == memory_id:
                if content is not None:
                    memory["content"] = content
                if metadata is not None:
                    memory["metadata"] = {**memory.get("metadata", {}), **metadata}
                memory["updated_at"] = datetime.now().isoformat()
                self._save_memories()
                logger.info(f"Updated memory: {memory_id}")
                return memory
        
        return None
    
    def delete_memory(self, memory_id: str) -> bool:
        """
        Delete a memory
        
        Args:
            memory_id: ID of the memory to delete
            
        Returns:
            True if deleted, False if not found
        """
        initial_count = len(self.memories)
        self.memories = [m for m in self.memories if m["id"] != memory_id]
        
        if len(self.memories) < initial_count:
            self._save_memories()
            logger.info(f"Deleted memory: {memory_id}")
            return True
        
        return False
    
    def clear_all_memories(self) -> int:
        """
        Clear all memories
        
        Returns:
            Number of memories cleared
        """
        count = len(self.memories)
        self.memories = []
        self._save_memories()
        logger.info(f"Cleared {count} memories")
        return count
    
    def get_memories_for_prompt(self) -> str:
        """
        Get formatted memories for inclusion in AI prompt
        
        Returns:
            Formatted string with memories (empty if disabled)
        """
        if not self.settings.get("reference_saved_memories", True):
            return ""
        
        if not self.memories:
            return ""
        
        lines = ["=" * 80]
        lines.append("SAVED MEMORIES")
        lines.append("=" * 80)
        lines.append("")
        lines.append("The following information has been explicitly saved by the user:")
        lines.append("")
        
        for i, memory in enumerate(self.memories, 1):
            lines.append(f"{i}. {memory['content']}")
            if memory.get('metadata'):
                meta_str = ", ".join(f"{k}: {v}" for k, v in memory['metadata'].items())
                if meta_str:
                    lines.append(f"   ({meta_str})")
            lines.append("")
        
        lines.append("=" * 80)
        lines.append("")
        lines.append("IMPORTANT: Use these saved memories to personalize your responses.")
        lines.append("Always reference relevant memories when they apply to the user's question.")
        lines.append("")
        
        return "\n".join(lines)
    
    def should_reference_chat_history(self) -> bool:
        """Check if chat history should be referenced"""
        return self.settings.get("reference_chat_history", True)

