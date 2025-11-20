from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import os
from pathlib import Path

router = APIRouter()

# Simple file-based storage for chat sessions
CHAT_SESSIONS_DIR = Path.home() / ".ai_agent_local" / "chat_sessions"
CHAT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


class ChatSessionMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: str
    rawContent: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    activityLog: Optional[List[Dict[str, Any]]] = None


class ChatSession(BaseModel):
    id: str
    title: str
    messages: List[ChatSessionMessage]
    created_at: str
    updated_at: str
    conversation_id: Optional[str] = None


class ChatSessionCreate(BaseModel):
    title: Optional[str] = None
    messages: List[Dict[str, Any]]
    conversation_id: Optional[str] = None


class ChatSessionUpdate(BaseModel):
    title: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None


def _get_session_file_path(session_id: str) -> Path:
    """Get the file path for a chat session"""
    return CHAT_SESSIONS_DIR / f"{session_id}.json"


def _generate_session_id() -> str:
    """Generate a unique session ID"""
    return f"chat_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{os.urandom(4).hex()}"


def _generate_title_from_messages(messages: List[Dict[str, Any]]) -> str:
    """Generate a title from the first user message"""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "").strip()
            if content:
                # Take first 60 characters
                title = content[:60].strip()
                if len(content) > 60:
                    title += "…"
                return title or "Untitled Chat"
    return "Untitled Chat"


def _format_time_ago(timestamp_str: str) -> str:
    """Format timestamp as relative time (e.g., '5m', '2h', '3d')"""
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        if dt.tzinfo:
            now = datetime.now(dt.tzinfo)
        else:
            now = datetime.utcnow()
        delta = now - dt
        
        if delta.total_seconds() < 60:
            return "Now"
        elif delta.total_seconds() < 3600:
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes}m"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"{hours}h"
        else:
            days = int(delta.total_seconds() / 86400)
            return f"{days}d"
    except Exception:
        return "Unknown"


@router.post("/sessions", response_model=ChatSession)
async def create_chat_session(session: ChatSessionCreate):
    """Create a new chat session"""
    try:
        session_id = _generate_session_id()
        title = session.title or _generate_title_from_messages(session.messages)
        now = datetime.utcnow().isoformat() + "Z"
        
        # Convert messages to ChatSessionMessage format
        messages = []
        for msg in session.messages:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("timestamp", now),
                "rawContent": msg.get("rawContent"),
                "plan": msg.get("plan"),
                "activityLog": msg.get("activityLog")
            })
        
        chat_session = {
            "id": session_id,
            "title": title,
            "messages": messages,
            "created_at": now,
            "updated_at": now,
            "conversation_id": session.conversation_id
        }
        
        # Save to file
        session_file = _get_session_file_path(session_id)
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(chat_session, f, indent=2)
        
        return ChatSession(**chat_session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating chat session: {str(e)}")


@router.get("/sessions", response_model=List[Dict[str, Any]])
async def list_chat_sessions():
    """List all chat sessions"""
    try:
        sessions = []
        for session_file in CHAT_SESSIONS_DIR.glob("*.json"):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    session_data = json.load(f)
                    # Return summary with formatted time
                    sessions.append({
                        "id": session_data.get("id"),
                        "title": session_data.get("title", "Untitled Chat"),
                        "created_at": session_data.get("created_at"),
                        "updated_at": session_data.get("updated_at"),
                        "time": _format_time_ago(session_data.get("updated_at", session_data.get("created_at", ""))),
                        "message_count": len(session_data.get("messages", []))
                    })
            except Exception as e:
                print(f"Error reading session file {session_file}: {e}")
                continue
        
        # Sort by updated_at descending (most recent first)
        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return sessions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing chat sessions: {str(e)}")


@router.get("/sessions/by-conversation/{conversation_id}", response_model=ChatSession)
async def get_chat_session_by_conversation_id(conversation_id: str):
    """Get a chat session by conversation_id"""
    try:
        # Search through all session files to find one with matching conversation_id
        for session_file in CHAT_SESSIONS_DIR.glob("*.json"):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    session_data = json.load(f)
                    if session_data.get("conversation_id") == conversation_id:
                        return ChatSession(**session_data)
            except Exception as e:
                print(f"Error reading session file {session_file}: {e}")
                continue
        
        raise HTTPException(status_code=404, detail="Chat session not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting chat session: {str(e)}")


@router.get("/sessions/{session_id}", response_model=ChatSession)
async def get_chat_session(session_id: str):
    """Get a specific chat session"""
    try:
        session_file = _get_session_file_path(session_id)
        if not session_file.exists():
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        with open(session_file, "r", encoding="utf-8") as f:
            session_data = json.load(f)
        
        return ChatSession(**session_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting chat session: {str(e)}")


@router.put("/sessions/{session_id}", response_model=ChatSession)
async def update_chat_session(session_id: str, update: ChatSessionUpdate):
    """Update a chat session"""
    try:
        session_file = _get_session_file_path(session_id)
        if not session_file.exists():
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        with open(session_file, "r", encoding="utf-8") as f:
            session_data = json.load(f)
        
        # Update fields
        if update.title is not None:
            session_data["title"] = update.title
        
        if update.messages is not None:
            session_data["messages"] = update.messages
        
        session_data["updated_at"] = datetime.utcnow().isoformat() + "Z"
        
        # Save back to file
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2)
        
        return ChatSession(**session_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating chat session: {str(e)}")


@router.delete("/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    """Delete a chat session"""
    try:
        session_file = _get_session_file_path(session_id)
        if not session_file.exists():
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        session_file.unlink()
        return {"message": "Chat session deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting chat session: {str(e)}")

