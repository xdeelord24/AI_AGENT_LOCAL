from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio

router = APIRouter()

MAX_PLAN_AUTOCONTINUE_ROUNDS = 3
COMPLETED_TASK_STATUSES = {"completed", "complete", "done"}


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


def _plan_has_pending_tasks(ai_plan: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(ai_plan, dict):
        return False
    tasks = ai_plan.get("tasks") or []
    if not isinstance(tasks, list):
        return False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = (task.get("status") or "pending").strip().lower()
        if status not in COMPLETED_TASK_STATUSES:
            return True
    return False


def _format_pending_tasks(ai_plan: Optional[Dict[str, Any]]) -> str:
    if not isinstance(ai_plan, dict):
        return "No pending tasks were provided."
    tasks = ai_plan.get("tasks") or []
    lines = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        title = task.get("title") or task.get("id") or "Untitled task"
        status = (task.get("status") or "pending").strip().lower()
        if status not in COMPLETED_TASK_STATUSES:
            lines.append(f"- [{status}] {title}")
    if not lines:
        return "All tasks appear to be completed."
    return "\n".join(lines)


def _build_auto_continue_prompt(ai_plan: Dict[str, Any]) -> str:
    summary = ai_plan.get("summary") or "Continue executing the current plan."
    pending_text = _format_pending_tasks(ai_plan)
    return (
        "Continue executing your existing TODO plan until every task is completed. "
        "Do not stop early—finish the remaining tasks, run verification, update task "
        "statuses to completed, and provide a short report of the results.\n\n"
        f"Plan summary: {summary}\n"
        f"Remaining tasks:\n{pending_text}"
    )


async def get_ai_service(request: Request):
    """Dependency to get AI service instance"""
    return request.app.state.ai_service


@router.post("/send", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    ai_service = Depends(get_ai_service)
):
    """Send a message to the AI agent and ensure TODO plans are completed when possible."""
    try:
        history: List[Dict[str, Any]] = []
        if request.conversation_history:
            for msg in request.conversation_history:
                if isinstance(msg, dict):
                    history.append(msg)
                else:
                    history.append(msg.dict())

        working_history = list(history)
        context_payload: Dict[str, Any] = dict(request.context or {})
        aggregated_messages: List[str] = []
        accumulated_file_ops: List[Dict[str, Any]] = []
        final_ai_plan: Optional[Dict[str, Any]] = None
        conversation_id: Optional[str] = None
        last_timestamp: Optional[str] = None
        last_context_used: Optional[Dict[str, Any]] = None

        current_message = request.message
        auto_continue_rounds = 0

        while True:
            response = await ai_service.process_message(
                message=current_message,
                context=context_payload,
                conversation_history=working_history
            )

            if not conversation_id:
                conversation_id = response["conversation_id"]
            last_timestamp = response["timestamp"]
            last_context_used = response.get("context_used")
            if last_context_used:
                context_payload = dict(last_context_used)

            aggregated_messages.append(response.get("content", ""))

            if response.get("file_operations"):
                accumulated_file_ops.extend(response["file_operations"])

            if response.get("ai_plan"):
                final_ai_plan = response["ai_plan"]

            working_history.append({"role": "user", "content": current_message})
            working_history.append({"role": "assistant", "content": response.get("content", "")})

            ai_plan = response.get("ai_plan")
            if not _plan_has_pending_tasks(ai_plan):
                break

            if auto_continue_rounds >= MAX_PLAN_AUTOCONTINUE_ROUNDS:
                aggregated_messages.append(
                    "Auto-continue stopped after maximum retries. "
                    "Some tasks may still be pending."
                )
                break

            auto_continue_rounds += 1
            current_message = _build_auto_continue_prompt(ai_plan or {})

        combined_response = "\n\n".join(
            part.strip() for part in aggregated_messages if part and part.strip()
        ) or ""

        agent_statuses = ai_service.generate_agent_statuses(
            message=request.message,
            context=last_context_used or request.context or {},
            file_operations=accumulated_file_ops if accumulated_file_ops else None
        )

        return ChatResponse(
            response=combined_response,
            conversation_id=conversation_id or "",
            timestamp=last_timestamp or "",
            context_used=last_context_used or context_payload,
            file_operations=accumulated_file_ops or None,
            ai_plan=final_ai_plan,
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
