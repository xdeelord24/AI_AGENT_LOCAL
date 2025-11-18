from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, Optional
import logging


router = APIRouter()
logger = logging.getLogger(__name__)


def build_error_response(session_info: Dict[str, str], timeout: int, message: str):
    return {
        "session_id": session_info.get("session_id"),
        "cwd": session_info.get("cwd", "."),
        "stdout": "",
        "stdout_lines": [],
        "stderr": "",
        "stderr_lines": [],
        "exit_code": None,
        "success": False,
        "timed_out": False,
        "timeout_seconds": timeout,
        "message": message,
        "was_cd": False,
    }


class TerminalSessionPayload(BaseModel):
    session_id: Optional[str] = None
    base_path: Optional[str] = Field(default=None, description="Initial working directory for the terminal session")


class TerminalCommandPayload(BaseModel):
    command: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    timeout: int = Field(default=120, ge=5, le=600)
    env: Optional[Dict[str, str]] = None


class TerminalCompletionPayload(BaseModel):
    command: str = ""
    session_id: Optional[str] = None
    cursor_position: Optional[int] = Field(default=None, ge=0)


async def get_terminal_service(request: Request):
    service = getattr(request.app.state, "terminal_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Terminal service is not configured")
    return service


@router.post("/session")
async def create_or_get_session(
    payload: TerminalSessionPayload,
    terminal_service=Depends(get_terminal_service),
):
    """
    Create a new terminal session or fetch the existing one if a session_id
    is provided.
    """
    return await terminal_service.get_session_info(payload.session_id, base_path=payload.base_path)


@router.get("/session/{session_id}")
async def get_session(
    session_id: str,
    terminal_service=Depends(get_terminal_service),
):
    """Fetch details for a specific session id."""
    return await terminal_service.get_session_info(session_id)


@router.post("/command")
async def run_terminal_command(
    payload: TerminalCommandPayload,
    terminal_service=Depends(get_terminal_service),
):
    """Execute a terminal command within the specified session."""
    try:
        return await terminal_service.run_command(
            payload.command,
            session_id=payload.session_id,
            timeout=payload.timeout,
            env=payload.env,
        )
    except TimeoutError as exc:
        logger.warning("Terminal command timed out: %s", payload.command)
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        logger.warning("Terminal runtime error: %s", exc)
        session_info = await terminal_service.get_session_info(payload.session_id)
        return build_error_response(
            session_info,
            payload.timeout,
            str(exc) or "Terminal runtime error",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Terminal command crashed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terminal error: {exc}",
        ) from exc


@router.post("/command/stream")
async def stream_terminal_command(
    payload: TerminalCommandPayload,
    terminal_service=Depends(get_terminal_service),
):
    """Execute a terminal command and stream output incrementally."""
    try:
        event_stream = await terminal_service.stream_command_events(
            payload.command,
            session_id=payload.session_id,
            timeout=payload.timeout,
            env=payload.env,
        )
        return StreamingResponse(event_stream, media_type="application/x-ndjson")
    except NotImplementedError as exc:
        logger.warning("Terminal streaming unsupported: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc) or "Terminal streaming is not supported on this platform",
        ) from exc
    except RuntimeError as exc:
        logger.warning("Terminal streaming error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc) or "Terminal streaming error",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Terminal streaming crashed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terminal stream error: {exc}",
        ) from exc


@router.post("/complete")
async def complete_terminal_input(
    payload: TerminalCompletionPayload,
    terminal_service=Depends(get_terminal_service),
):
    """Return completion suggestions for the current command buffer."""
    try:
        return await terminal_service.complete_command(
            payload.session_id,
            payload.command,
            payload.cursor_position,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terminal completion error: {exc}",
        ) from exc


@router.post("/interrupt")
async def interrupt_terminal(
    payload: TerminalSessionPayload,
    terminal_service=Depends(get_terminal_service),
):
    """Send an interrupt signal to the running command within a session."""
    try:
        return await terminal_service.cancel_command(payload.session_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terminal interrupt error: {exc}",
        ) from exc


