from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio

router = APIRouter()


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None
    conversation_history: Optional[List[ChatMessage]] = None


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    timestamp: str
    context_used: Optional[Dict[str, Any]] = None
    file_operations: Optional[List[Dict[str, Any]]] = None
    ai_plan: Optional[Dict[str, Any]] = None
    agent_statuses: Optional[List[Dict[str, Any]]] = None


class StatusPreviewRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None


async def get_ai_service(request: Request):
    """Dependency to get AI service instance"""
    return request.app.state.ai_service


@router.post("/send", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    ai_service = Depends(get_ai_service)
):
    """Send a message to the AI agent and get a response"""
    try:
        history = []
        if request.conversation_history:
            for msg in request.conversation_history:
                if isinstance(msg, dict):
                    history.append(msg)
                else:
                    history.append(msg.dict())

        # Process the message with context
        response = await ai_service.process_message(
            message=request.message,
            context=request.context or {},
            conversation_history=history
        )
        agent_statuses = ai_service.generate_agent_statuses(
            message=request.message,
            context=request.context or {},
            file_operations=response.get("file_operations")
        )
        
        return ChatResponse(
            response=response["content"],
            conversation_id=response["conversation_id"],
            timestamp=response["timestamp"],
            context_used=response.get("context_used"),
            file_operations=response.get("file_operations"),
            ai_plan=response.get("ai_plan"),
            agent_statuses=agent_statuses
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")


@router.get("/models")
async def get_available_models(ai_service = Depends(get_ai_service)):
    """Get list of available AI models"""
    try:
        models = await ai_service.get_available_models()
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting models: {str(e)}")


@router.post("/models/{model_name}/select")
async def select_model(
    model_name: str,
    ai_service = Depends(get_ai_service)
):
    """Select a specific AI model"""
    try:
        success = await ai_service.select_model(model_name)
        if success:
            return {"message": f"Model {model_name} selected successfully"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to select model {model_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error selecting model: {str(e)}")


@router.get("/status")
async def get_chat_status(ai_service = Depends(get_ai_service)):
    """Get the current status of the chat service"""
    try:
        status = await ai_service.get_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting status: {str(e)}")


@router.post("/status-preview")
async def get_status_preview(
    request: StatusPreviewRequest,
    ai_service = Depends(get_ai_service)
):
    """Generate contextual agent status steps for the UI"""
    try:
        statuses = ai_service.generate_agent_statuses(
            message=request.message,
            context=request.context or {}
        )
        return {"agent_statuses": statuses}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating status preview: {str(e)}")
