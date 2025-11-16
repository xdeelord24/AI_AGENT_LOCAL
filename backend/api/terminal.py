from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from typing import Dict, Optional


router = APIRouter()


class TerminalSessionPayload(BaseModel):
    session_id: Optional[str] = None


class TerminalCommandPayload(BaseModel):
    command: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    timeout: int = Field(default=120, ge=5, le=600)
    env: Optional[Dict[str, str]] = None


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
    return await terminal_service.get_session_info(payload.session_id)


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
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terminal error: {exc}",
        ) from exc


