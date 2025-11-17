from __future__ import annotations

import asyncio
import os
import secrets
import shlex
import signal
import subprocess
from asyncio.subprocess import PIPE, Process
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


@dataclass
class TerminalSession:
    """In-memory representation of a terminal session."""

    session_id: str
    cwd: Path
    created_at: datetime = field(default_factory=_utc_now)
    last_active: datetime = field(default_factory=_utc_now)
    current_process: Optional[Process] = field(default=None, repr=False, compare=False)
    current_command: Optional[str] = None
    interrupted: bool = False

    def touch(self) -> None:
        self.last_active = _utc_now()

    def to_dict(self) -> Dict[str, str]:
        return {
            "session_id": self.session_id,
            "cwd": str(self.cwd),
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
        }

    def is_busy(self) -> bool:
        return self.current_process is not None and self.current_process.returncode is None


class TerminalService:
    """Manage lightweight terminal sessions backed by the host OS shell."""

    def __init__(self, base_path: Optional[str] = None):
        resolved_base = Path(base_path or os.getcwd()).expanduser()
        self.base_path = resolved_base.resolve()
        if not self.base_path.exists():
            self.base_path.mkdir(parents=True, exist_ok=True)

        self._sessions: Dict[str, TerminalSession] = {}
        self._lock = asyncio.Lock()

    async def get_session_info(self, session_id: Optional[str]) -> Dict[str, str]:
        """Return session metadata, creating the session when needed."""
        session = await self._get_or_create_session(session_id)
        return session.to_dict()

    async def run_command(
        self,
        command: str,
        *,
        session_id: Optional[str],
        timeout: int = 120,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        if not command or not command.strip():
            raise RuntimeError("Command cannot be empty")

        session = await self._get_or_create_session(session_id)
        if session.is_busy():
            raise RuntimeError("Terminal session is already running a command")

        normalized = command.strip()

        if self._is_cd_command(normalized):
            return await self._handle_cd_command(session, normalized, timeout)

        return await self._execute_process(session, normalized, timeout, env)

    async def cancel_command(self, session_id: Optional[str]) -> Dict[str, object]:
        session = await self._get_session(session_id)
        if session is None:
            raise RuntimeError("Session not found")

        if not session.is_busy():
            return self._build_response(
                session,
                stdout="",
                stderr="",
                exit_code=None,
                success=True,
                timeout=0,
                message="No running command to interrupt",
                was_cd=False,
            )

        session.interrupted = True
        process = session.current_process
        await self._interrupt_process(process)

        return self._build_response(
            session,
            stdout="",
            stderr="",
            exit_code=None,
            success=True,
            timeout=0,
            message="Interrupt signal sent",
            was_cd=False,
        )

    async def _get_session(self, session_id: Optional[str]) -> Optional[TerminalSession]:
        async with self._lock:
            session = self._sessions.get(session_id or "")
            if session:
                session.touch()
            return session

    async def _get_or_create_session(self, session_id: Optional[str]) -> TerminalSession:
        async with self._lock:
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
            else:
                session = TerminalSession(
                    session_id=self._generate_session_id(),
                    cwd=self.base_path,
                )
                self._sessions[session.session_id] = session
            session.touch()
            return session

    async def _handle_cd_command(
        self,
        session: TerminalSession,
        command: str,
        timeout: int,
    ) -> Dict[str, object]:
        tokens = self._split_command(command)
        # Support `cd`, `cd path`, `cd /d path` (Windows)
        target: Optional[str] = None
        if len(tokens) == 1:
            message = str(session.cwd)
            success = True
        else:
            index = 1
            if len(tokens) >= 3 and tokens[1].lower() == "/d":
                index = 2
            if index >= len(tokens):
                message = "No directory provided"
                success = False
            else:
                target = tokens[index]
                new_path = self._resolve_path(session.cwd, target)
                if not new_path.exists():
                    message = f"Directory not found: {target}"
                    success = False
                elif not new_path.is_dir():
                    message = f"Not a directory: {target}"
                    success = False
                else:
                    session.cwd = new_path
                    session.touch()
                    message = f"Changed directory to {session.cwd}"
                    success = True

        exit_code = 0 if success else 1
        return self._build_response(
            session,
            stdout="",
            stderr="",
            exit_code=exit_code,
            success=success,
            timeout=timeout,
            message=message,
            was_cd=True,
        )

    async def _execute_process(
        self,
        session: TerminalSession,
        command: str,
        timeout: int,
        env: Optional[Dict[str, str]],
    ) -> Dict[str, object]:
        env_vars = os.environ.copy()
        if env:
            env_vars.update({str(key): str(value) for key, value in env.items() if value is not None})

        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(session.cwd),
            env=env_vars,
            stdout=PIPE,
            stderr=PIPE,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
        session.current_process = process
        session.current_command = command

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await self._terminate_process(process)
            stdout_bytes, stderr_bytes = await process.communicate()
        finally:
            session.touch()
            session.current_process = None
            session.current_command = None

        stdout = self._decode_output(stdout_bytes)
        stderr = self._decode_output(stderr_bytes)
        exit_code = process.returncode if process.returncode is not None else -1

        interrupted = session.interrupted
        session.interrupted = False

        message = None
        if timed_out:
            message = f"Command timed out after {timeout} seconds"
        elif interrupted:
            message = "Command interrupted by user"

        success = exit_code == 0 and not timed_out and not interrupted

        return self._build_response(
            session,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            success=success,
            timeout=timeout,
            message=message,
            was_cd=False,
            timed_out=timed_out,
        )

    async def _interrupt_process(self, process: Process) -> None:
        if process.returncode is not None:
            return

        if os.name == "nt":
            # Attempt Ctrl+Break first (requires CREATE_NEW_PROCESS_GROUP)
            if hasattr(signal, "CTRL_BREAK_EVENT"):
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                except ValueError:
                    process.terminate()
            else:
                process.terminate()
        else:
            process.send_signal(signal.SIGINT)

        await asyncio.sleep(0.2)
        if process.returncode is None:
            process.terminate()
            await asyncio.sleep(0.2)
        if process.returncode is None:
            process.kill()

    async def _terminate_process(self, process: Process) -> None:
        if process.returncode is not None:
            return

        process.terminate()
        await asyncio.sleep(0.2)
        if process.returncode is None:
            process.kill()

    def _split_command(self, command: str) -> Sequence[str]:
        posix = os.name != "nt"
        try:
            return shlex.split(command, posix=posix)
        except ValueError:
            return command.split()

    @staticmethod
    def _is_cd_command(command: str) -> bool:
        stripped = command.strip().lower()
        return stripped == "cd" or stripped.startswith("cd ")

    @staticmethod
    def _resolve_path(current: Path, target: str) -> Path:
        expanded = os.path.expanduser(target)
        if os.path.isabs(expanded):
            return Path(expanded).resolve()
        return (current / expanded).resolve()

    @staticmethod
    def _split_lines(value: Optional[str]) -> Sequence[str]:
        if not value:
            return []
        normalized = value.replace("\r\n", "\n")
        lines = normalized.split("\n")
        if lines and lines[-1] == "":
            return lines[:-1]
        return lines

    @staticmethod
    def _decode_output(data: Optional[bytes]) -> str:
        if data is None:
            return ""
        try:
            return data.decode()
        except Exception:  # noqa: BLE001
            return data.decode(errors="replace")

    def _build_response(
        self,
        session: TerminalSession,
        *,
        stdout: str,
        stderr: str,
        exit_code: Optional[int],
        success: bool,
        timeout: int,
        message: Optional[str],
        was_cd: bool,
        timed_out: bool = False,
    ) -> Dict[str, object]:
        return {
            "session_id": session.session_id,
            "cwd": str(session.cwd),
            "stdout": stdout or "",
            "stdout_lines": list(self._split_lines(stdout)),
            "stderr": stderr or "",
            "stderr_lines": list(self._split_lines(stderr)),
            "exit_code": exit_code,
            "success": success,
            "timed_out": timed_out,
            "timeout_seconds": timeout,
            "message": message,
            "was_cd": was_cd,
        }

    @staticmethod
    def _generate_session_id() -> str:
        return secrets.token_hex(16)

