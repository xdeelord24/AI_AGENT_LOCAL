"""
Memory API endpoints
Handles memory management and settings
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, List, Any

router = APIRouter()


class MemoryCreate(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None


class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class MemorySettingsUpdate(BaseModel):
    reference_saved_memories: Optional[bool] = None
    reference_chat_history: Optional[bool] = None


async def get_memory_service(request: Request):
    """Dependency to get memory service instance"""
    if not hasattr(request.app.state, 'memory_service'):
        from backend.services.memory_service import MemoryService
        request.app.state.memory_service = MemoryService()
    return request.app.state.memory_service


@router.get("/settings")
async def get_memory_settings(memory_service = Depends(get_memory_service)):
    """Get memory settings"""
    try:
        return memory_service.get_settings()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting memory settings: {str(e)}")


@router.put("/settings")
async def update_memory_settings(
    settings: MemorySettingsUpdate,
    memory_service = Depends(get_memory_service)
):
    """Update memory settings"""
    try:
        updated = memory_service.update_settings(
            reference_saved_memories=settings.reference_saved_memories,
            reference_chat_history=settings.reference_chat_history
        )
        return updated
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating memory settings: {str(e)}")


@router.get("")
async def get_memories(memory_service = Depends(get_memory_service)):
    """Get all saved memories"""
    try:
        memories = memory_service.get_memories()
        return {"memories": memories, "count": len(memories)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting memories: {str(e)}")


@router.post("")
async def create_memory(
    memory: MemoryCreate,
    memory_service = Depends(get_memory_service)
):
    """Create a new memory"""
    try:
        created = memory_service.add_memory(
            content=memory.content,
            metadata=memory.metadata
        )
        return created
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating memory: {str(e)}")


@router.put("/{memory_id}")
async def update_memory(
    memory_id: str,
    memory: MemoryUpdate,
    memory_service = Depends(get_memory_service)
):
    """Update an existing memory"""
    try:
        updated = memory_service.update_memory(
            memory_id=memory_id,
            content=memory.content,
            metadata=memory.metadata
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return updated
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating memory: {str(e)}")


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    memory_service = Depends(get_memory_service)
):
    """Delete a memory"""
    try:
        deleted = memory_service.delete_memory(memory_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"success": True, "message": "Memory deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting memory: {str(e)}")


@router.delete("")
async def clear_all_memories(memory_service = Depends(get_memory_service)):
    """Clear all memories"""
    try:
        count = memory_service.clear_all_memories()
        return {"success": True, "count": count, "message": f"Cleared {count} memories"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing memories: {str(e)}")

