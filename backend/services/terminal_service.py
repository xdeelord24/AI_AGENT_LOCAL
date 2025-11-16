from __future__ import annotations

"""
Terminal Service
Provides a lightweight shell-like experience that persists the working
directory across commands so the in-app terminal can behave like a real one.
"""

import asyncio
import os
import time
import uuid
from typing import Dict, Optional, Any


class TerminalSession:
    """Represents a terminal session with its own working directory."""

    def __init__(self, session_id: str, cwd: str):
        self.session_id = session_id
        self.current_directory = cwd


class TerminalService:
    """Executes shell commands while preserving per-session state."""

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = os.path.abspath(base_path or os.getcwd())
        self.sessions: Dict[str, TerminalSession] = {}
        self.session_locks: Dict[str, asyncio.Lock] = {}
        self._lock = asyncio.Lock()

    async def ensure_session(self, session_id: Optional[str] = None) -> TerminalSession:
        """Return an existing session or create a new one."""
        async with self._lock:
            if session_id and session_id in self.sessions:
                return self.sessions[session_id]

            new_session_id = session_id or uuid.uuid4().hex
            session = TerminalSession(new_session_id, self.base_path)
            self.sessions[new_session_id] = session
            if new_session_id not in self.session_locks:
                self.session_locks[new_session_id] = asyncio.Lock()
            return session

    async def get_session_info(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Return a serialisable snapshot of a session."""
        session = await self.ensure_session(session_id)
        return {
            "session_id": session.session_id,
            "cwd": self._normalize_path(session.current_directory),
            "base_path": self._normalize_path(self.base_path),
        }

    async def run_command(
        self,
        command: str,
        session_id: Optional[str] = None,
        timeout: int = 120,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute a shell command and capture the output."""
        session = await self.ensure_session(session_id)
        lock = await self._get_session_lock(session.session_id)

        async with lock:
            prepared_command = (command or "").strip()
            if not prepared_command:
                return {
                    "session_id": session.session_id,
                    "stdout": "",
                    "stderr": "",
                    "stdout_lines": [],
                    "stderr_lines": [],
                    "exit_code": 0,
                    "cwd": self._normalize_path(session.current_directory),
                    "success": True,
                    "message": "No command provided",
                }

            lower_command = prepared_command.lower()
            if lower_command in {"clear", "cls"}:
                return {
                    "session_id": session.session_id,
                    "cleared": True,
                    "stdout": "",
                    "stderr": "",
                    "stdout_lines": [],
                    "stderr_lines": [],
                    "exit_code": 0,
                    "cwd": self._normalize_path(session.current_directory),
                    "success": True,
                    "message": "Terminal cleared",
                }

            if lower_command.startswith("cd"):
                return self._handle_cd(prepared_command, session)

            try:
                return await self._execute_subprocess(
                    prepared_command,
                    session,
                    timeout=timeout,
                    env=env,
                )
            except Exception as exc:  # noqa: BLE001
                return self._build_error_result(
                    session,
                    prepared_command,
                    message=str(exc),
                    timeout=timeout,
                )

    async def _execute_subprocess(
        self,
        command: str,
        session: TerminalSession,
        timeout: int = 120,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        environment = os.environ.copy()
        if env:
            environment.update(env)

        start_time = time.perf_counter()
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=session.current_directory,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Unable to execute command: {exc}") from exc

        timed_out = False
        message = ""
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()
            message = f"Command timed out after {timeout}s"

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        return {
            "session_id": session.session_id,
            "command": command,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "stdout_lines": self._split_lines(stdout_text),
            "stderr_lines": self._split_lines(stderr_text),
            "exit_code": process.returncode,
            "cwd": self._normalize_path(session.current_directory),
            "duration_ms": duration_ms,
            "success": process.returncode == 0 and not timed_out,
            "was_cd": False,
            "cleared": False,
            "timed_out": timed_out,
            "timeout_seconds": timeout,
            "message": message,
        }

    def _build_error_result(
        self,
        session: TerminalSession,
        command: str,
        message: str,
        *,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "command": command,
            "stdout": "",
            "stderr": "",
            "stdout_lines": [],
            "stderr_lines": [],
            "exit_code": 1,
            "cwd": self._normalize_path(session.current_directory),
            "duration_ms": 0,
            "success": False,
            "was_cd": False,
            "cleared": False,
            "timed_out": False,
            "timeout_seconds": timeout,
            "message": message,
        }

    def _handle_cd(self, command: str, session: TerminalSession) -> Dict[str, Any]:
        parts = command.split(maxsplit=1)
        target_argument = parts[1] if len(parts) > 1 else ""
        target_argument = target_argument.strip().strip('"').strip("'")

        if not target_argument:
            session.current_directory = self.base_path
            message = f"Current directory reset to {self._normalize_path(session.current_directory)}"
        else:
            candidate = self._resolve_path(session.current_directory, target_argument)
            if not os.path.exists(candidate) or not os.path.isdir(candidate):
                return {
                    "session_id": session.session_id,
                    "stdout": "",
                    "stderr": "",
                    "stdout_lines": [],
                    "stderr_lines": [],
                    "exit_code": 1,
                    "cwd": self._normalize_path(session.current_directory),
                    "success": False,
                    "message": f"Directory not found: {target_argument}",
                    "was_cd": True,
                }
            session.current_directory = candidate
            message = f"Directory changed to {self._normalize_path(candidate)}"

        return {
            "session_id": session.session_id,
            "stdout": "",
            "stderr": "",
            "stdout_lines": [],
            "stderr_lines": [],
            "exit_code": 0,
            "cwd": self._normalize_path(session.current_directory),
            "success": True,
            "message": message,
            "was_cd": True,
        }

    async def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        async with self._lock:
            if session_id not in self.session_locks:
                self.session_locks[session_id] = asyncio.Lock()
            return self.session_locks[session_id]

    @staticmethod
    def _split_lines(text: str) -> list[str]:
        if not text:
            return []
        return [line.rstrip("\r") for line in text.splitlines()]

    @staticmethod
    def _resolve_path(current_directory: str, target: str) -> str:
        if os.path.isabs(target):
            return os.path.abspath(target)
        return os.path.abspath(os.path.join(current_directory, target))

    @staticmethod
    def _normalize_path(path: str) -> str:
        return path.replace("\\", "/")


