from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Tuple, Literal, AsyncGenerator
import asyncio
import json
import time
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_PLAN_AUTOCONTINUE_ROUNDS = 10  # Increased to handle plans with many tasks
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
    images: Optional[List[str]] = None  # List of base64-encoded images (data URLs)


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
    thinking: Optional[str] = None
    web_references: Optional[List[Dict[str, Any]]] = None


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


def _finalize_ai_plan(ai_plan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Mark all tasks in the plan as completed before finalizing."""
    if not isinstance(ai_plan, dict):
        return ai_plan
    tasks = ai_plan.get("tasks") or []
    if not isinstance(tasks, list):
        return ai_plan
    
    # Create a copy to avoid mutating the original
    finalized_plan = dict(ai_plan)
    finalized_tasks = []
    
    for task in tasks:
        if not isinstance(task, dict):
            finalized_tasks.append(task)
            continue
        
        # Mark task as completed if it's not already
        finalized_task = dict(task)
        current_status = (task.get("status") or "pending").strip().lower()
        if current_status not in COMPLETED_TASK_STATUSES:
            finalized_task["status"] = "completed"
        finalized_tasks.append(finalized_task)
    
    finalized_plan["tasks"] = finalized_tasks
    return finalized_plan


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


def _extract_web_references_from_text(result_text: str) -> List[Dict[str, Any]]:
    """Extract web references (URLs and titles) from formatted web search result text"""
    web_references = []
    if not result_text:
        return web_references
    
    try:
        import re
        # Pattern to match URLs
        url_pattern = r'https?://[^\s\)\]\>]+'
        
        # Split into lines for better parsing
        lines = result_text.split('\n')
        current_title = None
        current_index = None
        
        for line in lines:
            line = line.strip()
            if not line:
                current_title = None
                current_index = None
                continue
            
            # Look for numbered items (1. Title, 2. Title, etc.) - this matches the format from _format_result
            title_match = re.match(r'^(\d+)\.\s*(.+)$', line)
            if title_match:
                current_index = int(title_match.group(1))
                current_title = title_match.group(2).strip()
                continue
            
            # Look for "Source:" or "URL:" or "Link:" labels
            if line.lower().startswith(('source:', 'url:', 'link:')):
                url_match = re.search(url_pattern, line)
                if url_match:
                    url = url_match.group(0).rstrip('.,;')
                    if url not in [ref.get("url") for ref in web_references]:
                        web_references.append({
                            "index": current_index or len(web_references) + 1,
                            "url": url,
                            "title": current_title or url
                        })
                current_title = None
                current_index = None
                continue
            
            # Look for URLs in the line
            url_matches = re.findall(url_pattern, line)
            for url in url_matches:
                url = url.rstrip('.,;')
                if url not in [ref.get("url") for ref in web_references]:
                    # Use current_title if available, otherwise use part of the line as title
                    title = current_title
                    if not title:
                        # Try to extract title from the line (text before the URL)
                        title_part = line[:line.find(url)].strip()
                        if title_part and len(title_part) < 200:
                            title = title_part
                        else:
                            title = url
                    
                    web_references.append({
                        "index": current_index or len(web_references) + 1,
                        "url": url,
                        "title": title
                    })
            
            # Reset current_title after processing a line with URL
            if url_matches:
                current_title = None
                current_index = None
        
        # Limit to 10 references
        return web_references[:10]
    except Exception as e:
        logger.warning(f"Error extracting web_references from text: {e}")
        return []


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
        accumulated_thinking: Optional[str] = None
        final_ai_plan: Optional[Dict[str, Any]] = None
        final_web_references: Optional[List[Dict[str, Any]]] = None
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
                conversation_history=working_history,
                images=request.images if auto_continue_rounds == 0 else None
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
            
            # Accumulate thinking if present
            thinking_content = response.get("thinking")
            if thinking_content:
                if accumulated_thinking:
                    accumulated_thinking = accumulated_thinking + "\n" + thinking_content
                else:
                    accumulated_thinking = thinking_content

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
                
                # Track web references from the response
                if response.get("web_references"):
                    final_web_references = response["web_references"]

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

        # Finalize the plan before returning
        finalized_plan = _finalize_ai_plan(final_ai_plan) if final_ai_plan else None

        agent_statuses = ai_service.generate_agent_statuses(
            message=request.message,
            context=last_context_used or request.context or {},
            file_operations=accumulated_file_ops if accumulated_file_ops else None,
            ai_plan=finalized_plan
        )

        activity_log = _finalize_activity_log(activity_events)

        # CRITICAL: Final check - ensure ASK mode NEVER returns file operations or plans
        # This is a redundant safeguard in case anything slipped through
        if is_ask_mode:
            final_file_ops = None
            final_plan = None
        else:
            final_file_ops = accumulated_file_ops if accumulated_file_ops else None
            final_plan = finalized_plan
        
        return ChatResponse(
            response=combined_response,
            conversation_id=conversation_id or "",
            timestamp=last_timestamp or "",
            message_id=last_message_id or str(uuid.uuid4()),
            context_used=last_context_used or context_payload,
            file_operations=final_file_ops,
            ai_plan=final_plan,
            agent_statuses=agent_statuses,
            activity_log=activity_log or None,
            thinking=accumulated_thinking,
            web_references=final_web_references
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


@router.post("/send/stream")
async def send_message_stream(
    request: ChatRequest,
    ai_service = Depends(get_ai_service)
):
    """Stream chat messages with real-time thinking and response chunks, then process full flow for file operations"""
    async def generate_stream():
        try:
            # Build prompt
            history: List[Dict[str, Any]] = []
            if request.conversation_history:
                for msg in request.conversation_history:
                    if isinstance(msg, dict):
                        history.append(msg)
                    else:
                        history.append(msg.dict())
            
            context_payload: Dict[str, Any] = dict(request.context or {})
            
            # Update MCP server workspace root if provided in context
            workspace_path = context_payload.get("workspace_path")
            if workspace_path and ai_service.mcp_client and ai_service.mcp_client.mcp_tools:
                try:
                    ai_service.mcp_client.mcp_tools.set_workspace_root(workspace_path)
                    logger.info(f"[DEBUG] Updated MCP workspace root to: {workspace_path}")
                except Exception as e:
                    logger.warning(f"[DEBUG] Failed to update MCP workspace root: {e}")
            
            # Detect ASK mode - never auto-continue in ASK mode
            mode_value = (context_payload.get("mode") or "").lower()
            chat_mode_value = (context_payload.get("chat_mode") or "").lower()
            is_ask_mode = (mode_value == "ask" or chat_mode_value == "ask") and not context_payload.get("composer_mode")
            
            working_history = list(history)
            current_message = request.message
            images = request.images or []  # Extract images from request
            if images:
                logger.info(f"[IMAGE DEBUG] Received {len(images)} image(s) in request")
                logger.info(f"[IMAGE DEBUG] First image preview: {images[0][:100] if images[0] else 'empty'}...")
            auto_continue_rounds = 0
            accumulated_thinking = ""
            accumulated_responses = []  # Accumulate responses from all rounds
            conversation_id = None
            message_id = None
            final_ai_plan = None
            accumulated_file_ops = []
            accumulated_web_references = []  # Track web references from web_search tool results
            
            while True:
                # Build prompt for current message (include images if provided, only on first round)
                prompt = ai_service._build_prompt(
                    current_message, 
                    context_payload, 
                    working_history,
                    images=images if auto_continue_rounds == 0 else None
                )
                
                # DEBUG: Log if MCP tools are included in prompt
                has_mcp_tools_in_prompt = "MCP TOOLS AVAILABLE" in prompt or "web_search" in prompt
                
                # Get detailed MCP status
                mcp_client_available = False
                mcp_tools_in_client = False
                if ai_service.mcp_client:
                    mcp_client_available = ai_service.mcp_client.is_available()
                    mcp_tools_in_client = ai_service.mcp_client.mcp_tools is not None
                
                mcp_status = {
                    "is_enabled": ai_service.is_mcp_enabled(),
                    "has_client": ai_service.mcp_client is not None,
                    "client_is_available": mcp_client_available,
                    "has_tools_in_client": mcp_tools_in_client,
                    "has_tools_in_prompt": has_mcp_tools_in_prompt,
                    "prompt_length": len(prompt),
                    "_enable_mcp": ai_service._enable_mcp if hasattr(ai_service, '_enable_mcp') else None
                }
                logger.info(f"[DEBUG] Prompt built - length: {len(prompt)}, has_mcp_tools: {has_mcp_tools_in_prompt}, is_mcp_enabled: {ai_service.is_mcp_enabled()}")
                logger.info(f"[DEBUG] MCP details - _enable_mcp: {ai_service._enable_mcp if hasattr(ai_service, '_enable_mcp') else 'N/A'}, client_available: {mcp_client_available}, tools_in_client: {mcp_tools_in_client}")
                
                # Send MCP status to frontend for debugging
                yield f"data: {json.dumps({'type': 'debug', 'mcp_status': mcp_status})}\n\n"
                
                if has_mcp_tools_in_prompt:
                    # Log a snippet showing MCP tools section
                    mcp_section_start = prompt.find("MCP TOOLS AVAILABLE")
                    if mcp_section_start >= 0:
                        mcp_snippet = prompt[mcp_section_start:min(mcp_section_start + 500, len(prompt))]
                        logger.info(f"[DEBUG] MCP tools section in prompt (first 500 chars): {mcp_snippet[:500]}")
                
                # Stream from Ollama directly
                accumulated_thinking_round = ""
                accumulated_response_round = ""
                
                if ai_service.provider == "ollama":
                    async for chunk in ai_service._stream_ollama(prompt, images=images if auto_continue_rounds == 0 else None):
                        if chunk.get("type") == "thinking":
                            thinking_chunk = chunk.get("content", "")
                            accumulated_thinking_round += thinking_chunk
                            accumulated_thinking += thinking_chunk
                            yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_chunk, 'round': auto_continue_rounds + 1})}\n\n"
                        elif chunk.get("type") == "response":
                            response_chunk = chunk.get("content", "")
                            accumulated_response_round += response_chunk
                            # Don't stream response chunks yet if MCP is enabled - we'll check for tool calls after streaming completes
                            # and stream the follow-up response instead if tool calls are found
                            # This prevents showing the user tool call syntax
                            mcp_enabled = ai_service.is_mcp_enabled() and ai_service.mcp_client
                            if not mcp_enabled:
                                # MCP not enabled, stream normally
                                yield f"data: {json.dumps({'type': 'response', 'content': response_chunk, 'round': auto_continue_rounds + 1})}\n\n"
                            else:
                                # MCP enabled - suppress response chunks to check for tool calls first
                                logger.info(f"[DEBUG] Suppressing response chunk (MCP enabled): {len(response_chunk)} chars, total accumulated: {len(accumulated_response_round)} chars")
                        elif chunk.get("type") == "done":
                            break
                        elif chunk.get("type") == "error":
                            yield f"data: {json.dumps({'type': 'error', 'content': chunk.get('content', 'Unknown error')})}\n\n"
                            return
                    
                    # After streaming, parse metadata from the streamed response to get file operations, plans, etc.
                    # This ensures we use the actual streamed content, not a regenerated response
                    try:
                        # Generate conversation and message IDs if not set (before parsing)
                        if not conversation_id:
                            conversation_id = str(uuid.uuid4())
                        if not message_id:
                            message_id = str(uuid.uuid4())
                        
                        # Check for tool calls in the ORIGINAL response BEFORE cleaning
                        # This is critical for web_search and other MCP tools
                        tool_calls = []
                        if ai_service.is_mcp_enabled() and ai_service.mcp_client:
                            # Log full response for debugging (first 1000 chars)
                            response_preview = accumulated_response_round[:1000].replace('\n', '\\n')
                            logger.info(f"[DEBUG] Full response preview (first 1000 chars): {response_preview}")
                            
                            tool_calls = ai_service.mcp_client.parse_tool_calls_from_response(accumulated_response_round)
                            logger.info(f"[DEBUG] Parsed tool calls from response: {len(tool_calls)} found")
                            
                            # Send tool call detection status to frontend
                            tool_call_debug = {
                                "tool_calls_found": len(tool_calls),
                                "tool_call_names": [tc.get('name') for tc in tool_calls] if tool_calls else [],
                                "response_length": len(accumulated_response_round),
                                "has_tool_call_pattern": '<tool_call' in accumulated_response_round or 'tool_call' in accumulated_response_round.lower()
                            }
                            yield f"data: {json.dumps({'type': 'debug', 'tool_call_status': tool_call_debug})}\n\n"
                            
                            if tool_calls:
                                logger.info(f"[DEBUG] Tool call names: {[tc.get('name') for tc in tool_calls]}")
                                for i, tc in enumerate(tool_calls):
                                    logger.info(f"[DEBUG] Tool call {i+1}: name={tc.get('name')}, args={tc.get('arguments')}")
                            else:
                                # No tool calls found - check if response contains tool call patterns
                                has_tool_call_pattern = '<tool_call' in accumulated_response_round or 'tool_call' in accumulated_response_round.lower()
                                logger.info(f"[DEBUG] No tool calls detected. Response contains 'tool_call' pattern: {has_tool_call_pattern}")
                                if has_tool_call_pattern:
                                    # Try to find where tool calls might be
                                    import re
                                    tool_call_matches = re.findall(r'<tool_call[^>]*>', accumulated_response_round, re.IGNORECASE)
                                    logger.info(f"[DEBUG] Found potential tool_call tags: {tool_call_matches}")
                        else:
                            logger.info(f"[DEBUG] MCP not enabled or client not available - is_mcp_enabled: {ai_service.is_mcp_enabled()}, mcp_client: {ai_service.mcp_client is not None}")
                        
                        # Parse metadata from the streamed response content
                        cleaned_response, metadata = ai_service._parse_response_metadata(
                            accumulated_response_round,
                            context_payload
                        )
                        
                        # Extract file operations and plans from metadata
                        file_ops = metadata.get("file_operations", []) if not is_ask_mode else []
                        ai_plan = metadata.get("ai_plan")  # Extract plan regardless of mode
                        
                        # Debug logging for plan extraction
                        logger.info(f"[DEBUG] Plan extraction - metadata keys: {list(metadata.keys())}, has_ai_plan: {bool(ai_plan)}")
                        if ai_plan:
                            logger.info(f"[DEBUG] Plan extracted - summary: {ai_plan.get('summary', 'N/A')}, tasks: {len(ai_plan.get('tasks', []))}")
                        else:
                            logger.info(f"[DEBUG] No plan extracted from metadata. Response length: {len(accumulated_response_round)}")
                            # Log a sample of the response to see if it contains plan-like content
                            if 'plan' in accumulated_response_round.lower() or 'task' in accumulated_response_round.lower():
                                sample = accumulated_response_round[:500].replace('\n', '\\n')
                                logger.info(f"[DEBUG] Response sample (first 500 chars): {sample}")
                        
                        if not is_ask_mode:
                            if file_ops:
                                accumulated_file_ops.extend(file_ops)
                        
                        # Always update final_ai_plan if a plan is found (even in ask_mode)
                        if ai_plan:
                            final_ai_plan = ai_plan
                            logger.info(f"[DEBUG] Setting final_ai_plan from initial response")
                            # Send plan update during streaming so frontend can display it
                            yield f"data: {json.dumps({
                                'type': 'plan',
                                'ai_plan': final_ai_plan
                            })}\n\n"
                        
                        # Use the streamed response (cleaned of metadata) for consistency
                        # This ensures what was streamed matches what's in the final response
                        # If cleaned_response is empty or None, fall back to accumulated_response_round
                        final_round_response = cleaned_response if cleaned_response and cleaned_response.strip() else accumulated_response_round
                        
                        # Log for debugging
                        logger.info(f"[DEBUG] Response after metadata parsing: cleaned={len(cleaned_response) if cleaned_response else 0} chars, accumulated={len(accumulated_response_round)} chars, final={len(final_round_response)} chars, tool_calls found: {len(tool_calls) if tool_calls else 0}")
                        if tool_calls:
                            logger.info(f"[DEBUG] Tool calls detected: {[tc.get('name') for tc in tool_calls]}")
                        else:
                            logger.info(f"[DEBUG] No tool calls detected in response. Response length: {len(accumulated_response_round)} chars")
                            # Log a sample of the response to help debug why tool calls aren't detected
                            if accumulated_response_round:
                                sample = accumulated_response_round[:300].replace('\n', '\\n')
                                logger.info(f"[DEBUG] Response sample (first 300 chars): {sample}")
                        
                        # Track if we've updated accumulated_responses during tool execution
                        tool_execution_updated_responses = False
                        
                        # Execute tool calls if found
                        if tool_calls:
                            logger.info(f"Found {len(tool_calls)} tool call(s) in streamed response, executing...")
                            logger.info(f"[DEBUG] Tool calls: {[tc.get('name') for tc in tool_calls]}")
                            # Execute tool calls
                            allow_write = not is_ask_mode
                            try:
                                # Add timeout for tool execution (especially important for web_search)
                                try:
                                    tool_results = await asyncio.wait_for(
                                        ai_service.mcp_client.execute_tool_calls(tool_calls, allow_write=allow_write),
                                        timeout=60.0  # 60 second timeout for tool execution
                                    )
                                    logger.info(f"Tool execution completed: {len(tool_results) if tool_results else 0} result(s)")
                                    
                                    # Log detailed tool execution results for debugging
                                    for i, result in enumerate(tool_results or []):
                                        tool_name = result.get("tool", "unknown")
                                        has_error = result.get("error", False)
                                        error_type = result.get("error_type")
                                        result_length = len(result.get("result", ""))
                                        logger.info(f"[DEBUG] Tool result {i+1}: tool={tool_name}, error={has_error}, error_type={error_type}, result_length={result_length}")
                                        if has_error:
                                            error_msg = result.get("result", "")[:200]  # First 200 chars of error
                                            logger.error(f"[DEBUG] Tool {tool_name} error details: {error_msg}")
                                    
                                    # Send tool execution status to frontend
                                    tool_exec_status = {
                                        "tool_calls_executed": len(tool_calls),
                                        "tool_results_count": len(tool_results) if tool_results else 0,
                                        "has_errors": any(r.get("error", False) for r in (tool_results or [])),
                                        "error_details": [
                                            {
                                                "tool": r.get("tool"),
                                                "error_type": r.get("error_type"),
                                                "error_msg": r.get("result", "")[:100] if r.get("error") else None
                                            }
                                            for r in (tool_results or []) if r.get("error", False)
                                        ]
                                    }
                                    yield f"data: {json.dumps({'type': 'debug', 'tool_execution_status': tool_exec_status})}\n\n"
                                except asyncio.TimeoutError:
                                    logger.error("Tool execution timed out after 60 seconds")
                                    tool_results = [{
                                        "tool": tc.get("name", "unknown"),
                                        "arguments": tc.get("arguments", {}),
                                        "result": "Tool execution timed out after 60 seconds. Please try again.",
                                        "error": True,
                                        "error_type": "TIMEOUT"
                                    } for tc in tool_calls]
                                
                                # Check if we have any successful results
                                has_successful_results = tool_results and any(not r.get("error", False) for r in tool_results)
                                has_any_results = tool_results and len(tool_results) > 0
                                logger.info(f"Tool execution results: {len(tool_results) if tool_results else 0} total, {sum(1 for r in tool_results if not r.get('error', False)) if tool_results else 0} successful")
                                logger.info(f"[DEBUG] Tool execution - has_any_results: {has_any_results}, has_successful_results: {has_successful_results}")
                                
                                # Extract web_references from web_search tool results
                                for tool_result in (tool_results or []):
                                    if tool_result.get("tool") == "web_search" and not tool_result.get("error", False):
                                        result_text = tool_result.get("result", "")
                                        if result_text:
                                            extracted_refs = _extract_web_references_from_text(result_text)
                                            # Merge with existing, avoiding duplicates
                                            existing_urls = {ref.get("url") for ref in accumulated_web_references}
                                            for ref in extracted_refs:
                                                if ref.get("url") and ref.get("url") not in existing_urls:
                                                    accumulated_web_references.append(ref)
                                                    existing_urls.add(ref.get("url"))
                                            if extracted_refs:
                                                logger.info(f"[DEBUG] Extracted {len(extracted_refs)} web references from web_search tool result")
                                
                                # CRITICAL: Convert successful write_file tool executions to file_operations
                                # This ensures files written via MCP tools are shown for review in the frontend
                                # Note: Files are already written at this point, but we still show them for review
                                if not is_ask_mode:
                                    for tool_result in (tool_results or []):
                                        if tool_result.get("tool") == "write_file" and not tool_result.get("error", False):
                                            arguments = tool_result.get("arguments", {})
                                            path = arguments.get("path") or arguments.get("file_path")
                                            content = arguments.get("content") or arguments.get("text") or ""
                                            
                                            if path:
                                                # Normalize path - handle relative paths
                                                workspace_path = context_payload.get("workspace_path", ".")
                                                if not os.path.isabs(path):
                                                    # Path is relative, make it relative to workspace
                                                    # Keep it relative for frontend (frontend will handle normalization)
                                                    normalized_path = path
                                                else:
                                                    # Path is absolute, try to make it relative to workspace if possible
                                                    try:
                                                        workspace_abs = os.path.abspath(workspace_path)
                                                        if path.startswith(workspace_abs):
                                                            normalized_path = os.path.relpath(path, workspace_abs)
                                                        else:
                                                            normalized_path = path
                                                    except:
                                                        normalized_path = path
                                                
                                                # Determine if file was created or edited (check before write, but file is already written)
                                                # We'll use a heuristic: if content is non-empty and path doesn't exist in our list, assume create
                                                # Otherwise assume edit
                                                existing_paths = {op.get("path") for op in accumulated_file_ops}
                                                is_new_file = normalized_path not in existing_paths
                                                
                                                # Create a file_operation entry for review
                                                file_op = {
                                                    "type": "create_file" if is_new_file else "edit_file",
                                                    "path": normalized_path,
                                                    "content": content
                                                }
                                                
                                                if is_new_file:
                                                    accumulated_file_ops.append(file_op)
                                                    logger.info(f"[DEBUG] Converted write_file tool execution to file_operation: {normalized_path} ({len(content)} chars, type: create_file)")
                                                else:
                                                    # Update existing file operation with new content
                                                    for i, op in enumerate(accumulated_file_ops):
                                                        if op.get("path") == normalized_path:
                                                            accumulated_file_ops[i] = file_op
                                                            logger.info(f"[DEBUG] Updated existing file_operation from write_file tool: {normalized_path} ({len(content)} chars)")
                                                            break
                                
                                # Always generate a follow-up response if we have tool results (even if some failed)
                                # This ensures the process doesn't stop
                                if has_any_results:
                                    logger.info(f"[DEBUG] Generating follow-up response after tool execution (round {auto_continue_rounds + 1})")
                                    # Save original response before replacing (in case follow-up is empty)
                                    original_response_before_tools = final_round_response
                                    
                                    # Format tool results and get follow-up response
                                    tool_results_text = ai_service.mcp_client.format_tool_results_for_prompt(tool_results)
                                    
                                    # Build follow-up prompt with tool results
                                    if has_successful_results:
                                        follow_up_prompt = f"{prompt}\n\nInitial AI response:\n{final_round_response}\n\n{tool_results_text}\n\n🚨 CRITICAL INSTRUCTIONS 🚨\n\nThe tool execution results above contain the ACTUAL data from the tools. The tools have ALREADY been executed.\n\nYou MUST:\n1. Use the tool results to provide a direct, complete answer to the user's question\n2. Do NOT say you will search, need to search, or should search - the search is DONE\n3. Do NOT include thinking about using tools - just provide the answer using the results\n4. Extract relevant information from the tool results and present it clearly\n5. If the tool results contain the answer, use them directly\n\nDo NOT repeat phrases like:\n- 'I'll search for...'\n- 'Let me search...'\n- 'I need to search...'\n- 'I should use the web_search tool...'\n\nInstead, directly answer the question using the tool results provided above."
                                    else:
                                        # All tools failed - still generate a response explaining the error
                                        # Extract error details for better context
                                        error_summary = []
                                        for result in tool_results:
                                            if result.get("error"):
                                                tool_name = result.get("tool", "unknown")
                                                error_type = result.get("error_type", "UNKNOWN")
                                                error_msg = result.get("result", "Unknown error")
                                                error_summary.append(f"- {tool_name} ({error_type}): {error_msg[:200]}")
                                        
                                        error_details = "\n".join(error_summary) if error_summary else "Unknown error occurred"
                                        logger.warning(f"[DEBUG] All tools failed. Error details: {error_details}")
                                        
                                        follow_up_prompt = f"{prompt}\n\nInitial AI response:\n{final_round_response}\n\nTool execution encountered errors:\n{tool_results_text}\n\nError summary:\n{error_details}\n\nPlease provide a helpful response to the user. If the error suggests the tool is unavailable or there's a configuration issue, explain that clearly. If it's a temporary error, suggest the user try again."
                                    
                                    # Get follow-up response that incorporates tool results
                                    logger.info("Getting follow-up response with tool results in streaming mode...")
                                    logger.info(f"[DEBUG] Follow-up prompt length: {len(follow_up_prompt)}, tool_results_text length: {len(tool_results_text)}")
                                    try:
                                        follow_up_response, follow_up_thinking = await asyncio.wait_for(
                                            ai_service._call_model(follow_up_prompt),
                                            timeout=120.0  # 2 minute timeout for follow-up generation
                                        )
                                        logger.info(f"[DEBUG] Follow-up response generated - length: {len(follow_up_response) if follow_up_response else 0}, has_thinking: {bool(follow_up_thinking)}")
                                    except asyncio.TimeoutError:
                                        logger.error("Follow-up response generation timed out")
                                        follow_up_response = "I apologize, but I encountered a timeout while processing the tool results. Please try asking your question again."
                                        follow_up_thinking = None
                                    
                                    # Remove any tool calls from the follow-up response
                                    follow_up_response = ai_service.mcp_client.remove_tool_calls_from_text(follow_up_response)
                                    
                                    # If follow-up is empty, use the original response (cleaned of tool calls)
                                    if not follow_up_response or not follow_up_response.strip():
                                        logger.warning("Follow-up response is empty, using original response without tool calls")
                                        follow_up_response = ai_service.mcp_client.remove_tool_calls_from_text(original_response_before_tools)
                                        if not follow_up_response or not follow_up_response.strip():
                                            # Last resort: provide a generic message
                                            follow_up_response = "I attempted to search for information, but encountered an issue. Please try rephrasing your question or try again later."
                                    
                                    # Update accumulated thinking if there's new thinking
                                    if follow_up_thinking:
                                        if accumulated_thinking:
                                            accumulated_thinking = (accumulated_thinking + "\n" + follow_up_thinking).strip()
                                        else:
                                            accumulated_thinking = follow_up_thinking
                                    
                                    # Use the follow-up response instead of the original
                                    final_round_response = follow_up_response
                                    accumulated_response_round = follow_up_response
                                    logger.info(f"Follow-up response received: {len(final_round_response)} chars, replacing original response")
                                    
                                    # CRITICAL: Re-parse metadata from follow-up response to get updated ai_plan
                                    # The follow-up response may contain an updated plan after tool execution
                                    try:
                                        cleaned_follow_up, follow_up_metadata = ai_service._parse_response_metadata(
                                            follow_up_response,
                                            context_payload
                                        )
                                        # Update ai_plan if the follow-up response contains one
                                        if follow_up_metadata.get("ai_plan"):
                                            ai_plan = follow_up_metadata.get("ai_plan")
                                            final_ai_plan = ai_plan
                                            logger.info("Updated ai_plan from follow-up response after tool execution")
                                            # Send plan update during streaming so frontend can display it
                                            yield f"data: {json.dumps({
                                                'type': 'plan',
                                                'ai_plan': final_ai_plan
                                            })}\n\n"
                                        
                                        # Also update file operations if present (but only if not in ask_mode)
                                        if not is_ask_mode and follow_up_metadata.get("file_operations"):
                                            follow_up_file_ops = follow_up_metadata.get("file_operations", [])
                                            accumulated_file_ops.extend(follow_up_file_ops)
                                            logger.info(f"Updated file_operations from follow-up response: {len(follow_up_file_ops)} operations")
                                        
                                        # Extract web_references from follow-up metadata if present
                                        if follow_up_metadata.get("web_references"):
                                            follow_up_web_refs = follow_up_metadata.get("web_references", [])
                                            # Merge with existing, avoiding duplicates
                                            existing_urls = {ref.get("url") for ref in accumulated_web_references}
                                            for ref in follow_up_web_refs:
                                                if ref.get("url") and ref.get("url") not in existing_urls:
                                                    accumulated_web_references.append(ref)
                                                    existing_urls.add(ref.get("url"))
                                            logger.info(f"Updated web_references from follow-up response: {len(follow_up_web_refs)} references")
                                    except Exception as parse_error:
                                        logger.warning(f"Error parsing metadata from follow-up response: {parse_error}")
                                        # Continue with existing ai_plan if parsing fails
                                    
                                    # Update accumulated_responses to replace the last entry (which had tool calls) with the follow-up
                                    # Mark that we've updated accumulated_responses so we don't append again later
                                    tool_execution_updated_responses = True
                                    if accumulated_responses:
                                        # Replace the last response (which contained tool calls) with the follow-up
                                        accumulated_responses[-1] = follow_up_response
                                    else:
                                        # If no accumulated responses yet, add the follow-up
                                        accumulated_responses.append(follow_up_response)
                                    
                                    # Stream the follow-up response to the frontend
                                    # Since we suppressed the initial response chunks, just stream the follow-up normally
                                    logger.info(f"Streaming follow-up response: {len(follow_up_response)} chars")
                                    chunk_size = 100  # Characters per chunk
                                    for i in range(0, len(follow_up_response), chunk_size):
                                        chunk = follow_up_response[i:i + chunk_size]
                                        yield f"data: {json.dumps({'type': 'response', 'content': chunk, 'round': auto_continue_rounds + 1})}\n\n"
                                else:
                                    # No tool results at all - this shouldn't happen, but handle it gracefully
                                    logger.warning("Tool execution returned no results, cleaning and streaming original response")
                                    if ai_service.mcp_client:
                                        final_round_response = ai_service.mcp_client.remove_tool_calls_from_text(final_round_response)
                                        accumulated_response_round = final_round_response
                                        if accumulated_response_round and accumulated_response_round.strip():
                                            chunk_size = 100
                                            for i in range(0, len(accumulated_response_round), chunk_size):
                                                chunk = accumulated_response_round[i:i + chunk_size]
                                                yield f"data: {json.dumps({'type': 'response', 'content': chunk, 'round': auto_continue_rounds + 1})}\n\n"
                            except Exception as tool_error:
                                logger.error(f"Error executing tools in streaming mode: {tool_error}", exc_info=True)
                                # Continue with original response if tool execution fails
                                # But still remove tool calls from the response
                                if ai_service.mcp_client:
                                    final_round_response = ai_service.mcp_client.remove_tool_calls_from_text(final_round_response)
                                    accumulated_response_round = final_round_response
                                    
                                    # Stream the cleaned response since we suppressed it earlier
                                    if accumulated_response_round and accumulated_response_round.strip():
                                        logger.info(f"Streaming response after tool execution error: {len(accumulated_response_round)} chars")
                                        chunk_size = 100
                                        for i in range(0, len(accumulated_response_round), chunk_size):
                                            chunk = accumulated_response_round[i:i + chunk_size]
                                            yield f"data: {json.dumps({'type': 'response', 'content': chunk, 'round': auto_continue_rounds + 1})}\n\n"
                        else:
                            # No tool calls, but still remove any that might be in the response
                            if ai_service.is_mcp_enabled() and ai_service.mcp_client:
                                final_round_response = ai_service.mcp_client.remove_tool_calls_from_text(final_round_response)
                                accumulated_response_round = final_round_response
                                
                                # Since we suppressed response chunks during streaming, stream the cleaned response now
                                # Always stream if there's any content, even if it's just whitespace (frontend will handle it)
                                if accumulated_response_round:
                                    content_preview = accumulated_response_round[:200].replace('\n', '\\n')
                                    logger.info(f"Streaming suppressed response (no tool calls found): {len(accumulated_response_round)} chars, preview: {content_preview}")
                                    chunk_size = 100
                                    for i in range(0, len(accumulated_response_round), chunk_size):
                                        chunk = accumulated_response_round[i:i + chunk_size]
                                        yield f"data: {json.dumps({'type': 'response', 'content': chunk, 'round': auto_continue_rounds + 1})}\n\n"
                                else:
                                    # Response was empty after cleaning - this shouldn't happen but log it
                                    logger.warning(f"No response content to stream after cleaning. Original accumulated_response_round length: {len(accumulated_response_round) if accumulated_response_round else 0}")
                                    # Try to use the original response before cleaning as fallback
                                    if accumulated_response_round and len(accumulated_response_round.strip()) == 0:
                                        logger.warning("Response was empty or only whitespace after cleaning tool calls")
                        
                        # Ensure response is cleaned of tool calls before using it
                        if ai_service.is_mcp_enabled() and ai_service.mcp_client:
                            final_round_response = ai_service.mcp_client.remove_tool_calls_from_text(final_round_response)
                            accumulated_response_round = final_round_response
                        
                        # Update working history with the actual streamed content
                        working_history.append({"role": "user", "content": current_message})
                        working_history.append({"role": "assistant", "content": final_round_response})
                        
                        # Accumulate response from this round - use what was actually streamed (cleaned)
                        # Only append if we haven't already updated accumulated_responses during tool execution
                        round_response = final_round_response
                        if round_response and not tool_execution_updated_responses:
                            accumulated_responses.append(round_response)
                        elif tool_execution_updated_responses:
                            # Tool execution already updated accumulated_responses, just ensure round_response is set
                            round_response = final_round_response
                        
                        # Log summary of this round
                        logger.info(f"[DEBUG] Round {auto_continue_rounds + 1} summary: tool_calls={len(tool_calls) if tool_calls else 0}, has_plan={bool(ai_plan)}, has_final_plan={bool(final_ai_plan)}, response_length={len(final_round_response)}, web_refs={len(accumulated_web_references)}")
                        
                        # Check if we should continue
                        # CRITICAL: After tool execution, allow continuation even in ask_mode if there are pending tasks
                        # This ensures web_search and other tools can complete their work
                        had_tool_execution = tool_execution_updated_responses
                        logger.info(f"[DEBUG] Checking continuation - is_ask_mode: {is_ask_mode}, auto_continue_rounds: {auto_continue_rounds}, MAX_ROUNDS: {MAX_PLAN_AUTOCONTINUE_ROUNDS}, had_tool_execution: {had_tool_execution}")
                        
                        if is_ask_mode and not had_tool_execution:
                            # In ask_mode without tool execution, send final response and break
                            # Use round_response (which should be the follow-up if tool execution happened) or accumulated_responses
                            combined_response = "\n\n".join(accumulated_responses) if accumulated_responses else round_response
                            # Ensure response is cleaned of tool calls one more time before sending
                            if ai_service.is_mcp_enabled() and ai_service.mcp_client and combined_response:
                                combined_response = ai_service.mcp_client.remove_tool_calls_from_text(combined_response)
                            # Finalize and include AI plan if it exists (even in ask_mode, plans can be generated)
                            finalized_plan = _finalize_ai_plan(final_ai_plan) if final_ai_plan else None
                            logger.info(f"[DEBUG] Breaking in ask_mode (no tool execution) - response length={len(combined_response) if combined_response else 0} chars")
                            logger.info(f"[DEBUG] Plan status - final_ai_plan: {bool(final_ai_plan)}, finalized_plan: {bool(finalized_plan)}")
                            if final_ai_plan:
                                logger.info(f"[DEBUG] Final AI plan details - summary: {final_ai_plan.get('summary', 'N/A')}, tasks: {len(final_ai_plan.get('tasks', []))}")
                            logger.info(f"Sending 'done' message in ask_mode: response length={len(combined_response) if combined_response else 0} chars, plan={finalized_plan is not None}, thinking length={len(accumulated_thinking) if accumulated_thinking else 0}")
                            # Always include thinking if it exists (even if empty string, convert to None only if truly empty)
                            thinking_to_send = accumulated_thinking.strip() if accumulated_thinking and accumulated_thinking.strip() else None
                            # CRITICAL: In ask_mode, file_operations should be None, but in other modes, send accumulated_file_ops
                            final_file_ops = None if is_ask_mode else (accumulated_file_ops if accumulated_file_ops else None)
                            yield f"data: {json.dumps({
                                'type': 'done', 
                                'thinking': thinking_to_send, 
                                'response': combined_response,
                                'message_id': message_id, 
                                'conversation_id': conversation_id, 
                                'timestamp': datetime.now().isoformat(),
                                'file_operations': final_file_ops,
                                'ai_plan': finalized_plan,
                                'activity_log': None,
                                'web_references': accumulated_web_references if accumulated_web_references else None
                            })}\n\n"
                            break
                        
                        # Check if plan has pending tasks
                        # Use final_ai_plan (which may have been updated from follow-up response) or ai_plan as fallback
                        plan_to_check = final_ai_plan or ai_plan
                        has_pending = _plan_has_pending_tasks(plan_to_check)
                        logger.info(f"[DEBUG] Plan check - has_pending: {has_pending}, plan_to_check: {bool(plan_to_check)}, final_ai_plan: {bool(final_ai_plan)}, ai_plan: {bool(ai_plan)}, had_tool_execution: {had_tool_execution}")
                        
                        # In ask_mode, only break if no pending tasks AND no tool execution happened
                        # If tool execution happened, allow continuation to complete the work
                        if is_ask_mode and not has_pending and not had_tool_execution:
                            # No pending tasks and no tool execution in ask_mode - complete
                            finalized_plan = _finalize_ai_plan(final_ai_plan) if final_ai_plan else None
                            combined_response = "\n\n".join(accumulated_responses) if accumulated_responses else round_response
                            if ai_service.is_mcp_enabled() and ai_service.mcp_client and combined_response:
                                combined_response = ai_service.mcp_client.remove_tool_calls_from_text(combined_response)
                            logger.info(f"[DEBUG] Breaking in ask_mode (no pending tasks, no tool execution) - response length={len(combined_response) if combined_response else 0} chars")
                            thinking_to_send = accumulated_thinking.strip() if accumulated_thinking and accumulated_thinking.strip() else None
                            # CRITICAL: In ask_mode, file_operations should be None, but in other modes, send accumulated_file_ops
                            final_file_ops = None if is_ask_mode else (accumulated_file_ops if accumulated_file_ops else None)
                            yield f"data: {json.dumps({
                                'type': 'done', 
                                'thinking': thinking_to_send, 
                                'response': combined_response,
                                'message_id': message_id, 
                                'conversation_id': conversation_id, 
                                'timestamp': datetime.now().isoformat(),
                                'file_operations': final_file_ops,
                                'ai_plan': finalized_plan,
                                'activity_log': None,
                                'web_references': accumulated_web_references if accumulated_web_references else None
                            })}\n\n"
                            break
                        
                        if not has_pending:
                            # All tasks completed, finalize plan and send final response
                            logger.info(f"[DEBUG] No pending tasks - completing. had_tool_execution: {had_tool_execution}, is_ask_mode: {is_ask_mode}")
                            finalized_plan = _finalize_ai_plan(final_ai_plan) if final_ai_plan else None
                            combined_response = "\n\n".join(accumulated_responses) if accumulated_responses else round_response
                            logger.info(f"[DEBUG] Sending done message - response length: {len(combined_response) if combined_response else 0}, web_refs: {len(accumulated_web_references)}")
                            # CRITICAL: Always send accumulated file_operations (unless in ask_mode)
                            final_file_ops = None if is_ask_mode else (accumulated_file_ops if accumulated_file_ops else None)
                            if final_file_ops:
                                logger.info(f"[DEBUG] Sending {len(final_file_ops)} file operations in done chunk")
                            yield f"data: {json.dumps({
                                'type': 'done', 
                                'thinking': accumulated_thinking.strip() if accumulated_thinking and accumulated_thinking.strip() else None, 
                                'response': combined_response,
                                'message_id': message_id, 
                                'conversation_id': conversation_id, 
                                'timestamp': datetime.now().isoformat(),
                                'file_operations': final_file_ops,
                                'ai_plan': finalized_plan,
                                'activity_log': None,
                                'web_references': accumulated_web_references if accumulated_web_references else None
                            })}\n\n"
                            break
                        
                        if auto_continue_rounds >= MAX_PLAN_AUTOCONTINUE_ROUNDS:
                            # Max rounds reached, finalize plan and send final response with warning
                            logger.info(f"[DEBUG] Max rounds reached ({auto_continue_rounds} >= {MAX_PLAN_AUTOCONTINUE_ROUNDS}), breaking")
                            finalized_plan = _finalize_ai_plan(final_ai_plan) if final_ai_plan else None
                            combined_response = "\n\n".join(accumulated_responses) if accumulated_responses else round_response
                            yield f"data: {json.dumps({
                                'type': 'done', 
                                'thinking': accumulated_thinking.strip() if accumulated_thinking and accumulated_thinking.strip() else None, 
                                'response': combined_response + "\n\nAuto-continue stopped after maximum retries. Some tasks may still be pending.",
                                'message_id': message_id, 
                                'conversation_id': conversation_id, 
                                'timestamp': datetime.now().isoformat(),
                                'file_operations': accumulated_file_ops if accumulated_file_ops else None,
                                'ai_plan': finalized_plan,
                                'activity_log': None,
                                'web_references': accumulated_web_references if accumulated_web_references else None
                            })}\n\n"
                            break
                        
                        # Continue with next round
                        auto_continue_rounds += 1
                        # Use final_ai_plan (which may have been updated from follow-up response) or ai_plan as fallback
                        plan_for_continue = final_ai_plan or ai_plan or {}
                        logger.info(f"[DEBUG] Continuing to next round - round: {auto_continue_rounds}, has_plan: {bool(plan_for_continue)}, is_ask_mode: {is_ask_mode}")
                        current_message = _build_auto_continue_prompt(plan_for_continue)
                        # Note: context_payload is maintained from previous rounds
                        
                        # Send a continuation marker
                        continue_message = f"Continuing with remaining tasks (round {auto_continue_rounds})..."
                        logger.info(f"[DEBUG] Sending continue message: {continue_message}")
                        yield f"data: {json.dumps({'type': 'continue', 'round': auto_continue_rounds, 'message': continue_message})}\n\n"
                        
                    except Exception as process_error:
                        logger.exception("Error parsing metadata from streamed response")
                        # On error, still use the streamed content to ensure consistency
                        round_response = accumulated_response_round
                        if round_response:
                            accumulated_responses.append(round_response)
                        combined_response = "\n\n".join(accumulated_responses) if accumulated_responses else accumulated_response_round
                        yield f"data: {json.dumps({
                            'type': 'done', 
                                'thinking': accumulated_thinking.strip() if accumulated_thinking and accumulated_thinking.strip() else None,
                            'response': combined_response,
                            'message_id': message_id or str(uuid.uuid4()), 
                            'conversation_id': conversation_id or str(uuid.uuid4()), 
                            'timestamp': datetime.now().isoformat(),
                            'file_operations': accumulated_file_ops if accumulated_file_ops else None,
                            'ai_plan': _finalize_ai_plan(final_ai_plan) if final_ai_plan else None,
                            'activity_log': None,
                            'web_references': accumulated_web_references if accumulated_web_references else None
                        })}\n\n"
                        break
                else:
                    # For non-Ollama providers, fall back to regular processing with auto-continue
                    response = await ai_service.process_message(
                        current_message,
                        context_payload,
                        working_history
                    )
                    
                    if not conversation_id:
                        conversation_id = response.get("conversation_id") or str(uuid.uuid4())
                    if not message_id:
                        message_id = response.get("message_id") or str(uuid.uuid4())
                    
                    # Send AI plan FIRST (before thinking and response) for proper sequencing
                    if not is_ask_mode and response.get("ai_plan"):
                        final_ai_plan = response.get("ai_plan")
                        if response.get("file_operations"):
                            accumulated_file_ops.extend(response.get("file_operations"))
                        # Send plan immediately so frontend can display it first
                        yield f"data: {json.dumps({
                            'type': 'plan',
                            'ai_plan': final_ai_plan
                        })}\n\n"
                    elif not is_ask_mode:
                        if response.get("file_operations"):
                            accumulated_file_ops.extend(response.get("file_operations"))
                    
                    if response.get("thinking"):
                        if accumulated_thinking:
                            accumulated_thinking = accumulated_thinking + "\n" + response.get("thinking")
                        else:
                            accumulated_thinking = response.get("thinking")
                        yield f"data: {json.dumps({'type': 'thinking', 'content': response['thinking'], 'round': auto_continue_rounds + 1})}\n\n"
                    
                    yield f"data: {json.dumps({'type': 'response', 'content': response.get('content', ''), 'round': auto_continue_rounds + 1})}\n\n"
                    
                    # Accumulate response from this round
                    round_response = response.get('content', '')
                    if round_response:
                        accumulated_responses.append(round_response)
                    
                    working_history.append({"role": "user", "content": current_message})
                    working_history.append({"role": "assistant", "content": round_response})
                    
                    if is_ask_mode:
                        combined_response = "\n\n".join(accumulated_responses) if accumulated_responses else round_response
                        yield f"data: {json.dumps({
                            'type': 'done', 
                                'thinking': accumulated_thinking.strip() if accumulated_thinking and accumulated_thinking.strip() else None,
                            'response': combined_response,
                            'message_id': message_id, 
                            'conversation_id': conversation_id, 
                            'timestamp': response.get('timestamp') or datetime.now().isoformat(),
                            'file_operations': None,
                            'ai_plan': None,
                            'activity_log': response.get('activity_log')
                        })}\n\n"
                        break
                    
                    ai_plan = response.get("ai_plan")
                    if not _plan_has_pending_tasks(ai_plan):
                        # All tasks completed, finalize plan and send final response
                        finalized_plan = _finalize_ai_plan(final_ai_plan) if final_ai_plan else None
                        combined_response = "\n\n".join(accumulated_responses) if accumulated_responses else round_response
                        yield f"data: {json.dumps({
                            'type': 'done', 
                                'thinking': accumulated_thinking.strip() if accumulated_thinking and accumulated_thinking.strip() else None,
                            'response': combined_response,
                            'message_id': message_id, 
                            'conversation_id': conversation_id, 
                            'timestamp': response.get('timestamp') or datetime.now().isoformat(),
                            'file_operations': accumulated_file_ops if accumulated_file_ops else None,
                            'ai_plan': finalized_plan,
                            'activity_log': response.get('activity_log')
                        })}\n\n"
                        break
                    
                    if auto_continue_rounds >= MAX_PLAN_AUTOCONTINUE_ROUNDS:
                        # Finalize plan before sending
                        finalized_plan = _finalize_ai_plan(final_ai_plan) if final_ai_plan else None
                        combined_response = "\n\n".join(accumulated_responses) if accumulated_responses else round_response
                        yield f"data: {json.dumps({
                            'type': 'done', 
                                'thinking': accumulated_thinking.strip() if accumulated_thinking and accumulated_thinking.strip() else None,
                            'response': combined_response + "\n\nAuto-continue stopped after maximum retries. Some tasks may still be pending.",
                            'message_id': message_id, 
                            'conversation_id': conversation_id, 
                            'timestamp': response.get('timestamp') or datetime.now().isoformat(),
                            'file_operations': accumulated_file_ops if accumulated_file_ops else None,
                            'ai_plan': finalized_plan,
                            'activity_log': response.get('activity_log')
                        })}\n\n"
                        break
                    
                    auto_continue_rounds += 1
                    current_message = _build_auto_continue_prompt(ai_plan or {})
                    if response.get("context_used"):
                        context_payload = dict(response.get("context_used"))
                    
                    yield f"data: {json.dumps({'type': 'continue', 'round': auto_continue_rounds + 1, 'message': 'Continuing with remaining tasks...'})}\n\n"
                    
        except Exception as e:
            logger.exception("Error in streaming chat")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
    
    return StreamingResponse(generate_stream(), media_type="text/event-stream")


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
