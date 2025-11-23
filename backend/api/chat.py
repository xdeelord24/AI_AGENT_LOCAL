from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Tuple, Literal
import asyncio
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_PLAN_AUTOCONTINUE_ROUNDS = 3
COMPLETED_TASK_STATUSES = {"completed", "complete", "done"}
FEEDBACK_LOG_PATH = Path("data/feedback/feedback_log.jsonl")


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
    message_id: str
    context_used: Optional[Dict[str, Any]] = None
    file_operations: Optional[List[Dict[str, Any]]] = None
    ai_plan: Optional[Dict[str, Any]] = None
    agent_statuses: Optional[List[Dict[str, Any]]] = None
    activity_log: Optional[List[Dict[str, Any]]] = None


class FeedbackRequest(BaseModel):
    conversation_id: str
    message_id: str
    rating: Literal["like", "dislike"]
    comment: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


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


def _summarize_request(message: str, limit: int = 120) -> str:
    if not message:
        return "Processing developer request"
    snippet = " ".join(message.strip().split())
    if len(snippet) <= limit:
        return snippet
    return snippet[: limit - 1].rstrip() + "…"


def _utc_now_iso() -> str:
    """Return current UTC timestamp with trailing Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record_activity_event(
    events: List[Dict[str, Any]],
    key: str,
    label: str,
) -> None:
    events.append({
        "key": key,
        "label": label,
        "ts": time.perf_counter(),
        "started_at": _utc_now_iso(),
    })


def _finalize_activity_log(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not events:
        return []
    finalized: List[Dict[str, Any]] = []
    for idx, event in enumerate(events):
        end_ts = events[idx + 1]["ts"] if idx + 1 < len(events) else time.perf_counter()
        duration_ms = max(1, int((end_ts - event["ts"]) * 1000))
        finalized.append({
            "key": event["key"],
            "label": event["label"],
            "started_at": event["started_at"],
            "duration_ms": duration_ms
        })
    return finalized


def _append_feedback_entry(entry: Dict[str, Any]) -> None:
    FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as feedback_file:
        feedback_file.write(json.dumps(entry) + "\n")


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

        # Detect ASK mode - never accumulate file operations or plans in ASK mode
        mode_value = (context_payload.get("mode") or "").lower()
        chat_mode_value = (context_payload.get("chat_mode") or "").lower()
        is_ask_mode = (mode_value == "ask" or chat_mode_value == "ask") and not context_payload.get("composer_mode")

        current_message = request.message
        auto_continue_rounds = 0
        activity_events: List[Dict[str, Any]] = []
        last_message_id: Optional[str] = None
        _record_activity_event(
            activity_events,
            "thinking",
            f"Thinking about: {_summarize_request(request.message or '')}"
        )
        _record_activity_event(
            activity_events,
            "context_analysis",
            "Analyzing provided context and recent history"
        )

        while True:
            _record_activity_event(
                activity_events,
                f"model_request_round_{auto_continue_rounds + 1}",
                f"Sending instructions to AI model (round {auto_continue_rounds + 1})"
            )
            response = await ai_service.process_message(
                message=current_message,
                context=context_payload,
                conversation_history=working_history
            )
            _record_activity_event(
                activity_events,
                f"model_response_round_{auto_continue_rounds + 1}",
                f"AI model responded (round {auto_continue_rounds + 1})"
            )

            if not conversation_id:
                conversation_id = response["conversation_id"]
            last_timestamp = response["timestamp"]
            last_context_used = response.get("context_used")
            if last_context_used:
                context_payload = dict(last_context_used)

            aggregated_messages.append(response.get("content", ""))
            if response.get("message_id"):
                last_message_id = response["message_id"]

            # CRITICAL: Never accumulate file operations or plans in ASK mode
            # Even if the AI service accidentally includes them, strip them here
            if is_ask_mode:
                # Explicitly strip any file operations or plans that might have been generated
                response["file_operations"] = None
                response["ai_plan"] = None
            else:
                # Only accumulate file operations and plans in non-ASK modes
                if response.get("file_operations"):
                    accumulated_file_ops.extend(response["file_operations"])

                if response.get("ai_plan"):
                    final_ai_plan = response["ai_plan"]

            working_history.append({"role": "user", "content": current_message})
            working_history.append({"role": "assistant", "content": response.get("content", "")})

            # In ASK mode, never auto-continue (no plans to execute)
            if is_ask_mode:
                break

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

        _record_activity_event(
            activity_events,
            "finalizing",
            "Finalizing TODO results and report"
        )

        agent_statuses = ai_service.generate_agent_statuses(
            message=request.message,
            context=last_context_used or request.context or {},
            file_operations=accumulated_file_ops if accumulated_file_ops else None,
            ai_plan=final_ai_plan
        )

        activity_log = _finalize_activity_log(activity_events)

        # CRITICAL: Final check - ensure ASK mode NEVER returns file operations or plans
        # This is a redundant safeguard in case anything slipped through
        if is_ask_mode:
            final_file_ops = None
            final_plan = None
        else:
            final_file_ops = accumulated_file_ops if accumulated_file_ops else None
            final_plan = final_ai_plan
        
        return ChatResponse(
            response=combined_response,
            conversation_id=conversation_id or "",
            timestamp=last_timestamp or "",
            message_id=last_message_id or str(uuid.uuid4()),
            context_used=last_context_used or context_payload,
            file_operations=final_file_ops,
            ai_plan=final_plan,
            agent_statuses=agent_statuses,
            activity_log=activity_log or None
        )

    except Exception as e:
        error_msg = str(e)
        logger.exception("Error processing message in /api/chat/send endpoint")
        # Provide more detailed error messages for common issues
        if "Ollama is not running" in error_msg or "Cannot connect" in error_msg:
            status_code = 503  # Service Unavailable
        elif "Ollama API error" in error_msg or "model" in error_msg.lower():
            status_code = 400  # Bad Request (likely model name issue)
        else:
            status_code = 500  # Internal Server Error
        raise HTTPException(status_code=status_code, detail=f"Error processing message: {error_msg}")


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


@router.post("/feedback")
async def submit_feedback(feedback: FeedbackRequest):
    """Record like/dislike feedback for assistant responses."""
    entry = {
        "conversation_id": feedback.conversation_id,
        "message_id": feedback.message_id,
        "rating": feedback.rating,
        "comment": feedback.comment or "",
        "metadata": feedback.metadata or {},
        "recorded_at": _utc_now_iso()
    }
    try:
        await asyncio.to_thread(_append_feedback_entry, entry)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to record feedback: {exc}")
    return {"message": "Feedback recorded"}


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
