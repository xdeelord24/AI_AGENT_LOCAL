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
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple
from contextlib import suppress
import json
import logging

if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except AttributeError:
        pass


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


TERMINAL_COMPLETION_LIMIT = 200
COMPLETION_DELIMITERS = " \t\n\r;&|="


logger = logging.getLogger(__name__)


@dataclass
class TerminalSession:
    """In-memory representation of a terminal session."""

    session_id: str
    cwd: Path
    created_at: datetime = field(default_factory=_utc_now)
    last_active: datetime = field(default_factory=_utc_now)
    current_process: Optional[object] = field(default=None, repr=False, compare=False)
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

    async def get_session_info(self, session_id: Optional[str], base_path: Optional[str] = None) -> Dict[str, str]:
        """Return session metadata, creating the session when needed."""
        session = await self._get_or_create_session(session_id, base_path=base_path)
        return session.to_dict()

    async def run_command(
        self,
        command: str,
        *,
        session_id: Optional[str],
        timeout: int = 120,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        session = await self._get_or_create_session(session_id)
        try:
            normalized = (command or "").strip()

            if not normalized:
                return self._build_response(
                    session,
                    stdout="",
                    stderr="",
                    exit_code=None,
                    success=False,
                    timeout=timeout,
                    message="Command cannot be empty",
                    was_cd=False,
                )

            if session.is_busy():
                return self._build_response(
                    session,
                    stdout="",
                    stderr="",
                    exit_code=None,
                    success=False,
                    timeout=timeout,
                    message="Terminal session is already running a command",
                    was_cd=False,
                )

            if self._is_cd_command(normalized):
                return await self._handle_cd_command(session, normalized, timeout)

            return await self._execute_process(session, normalized, timeout, env)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Terminal command failed: %s", command)
            return self._build_response(
                session,
                stdout="",
                stderr=str(exc),
                exit_code=None,
                success=False,
                timeout=timeout,
                message=f"Terminal error: {exc}",
                was_cd=False,
            )

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

    async def complete_command(
        self,
        session_id: Optional[str],
        text: Optional[str],
        cursor_position: Optional[int] = None,
    ) -> Dict[str, object]:
        session = await self._get_or_create_session(session_id)
        buffer = text or ""
        cursor = self._normalize_cursor(buffer, cursor_position)
        token_start, token = self._extract_completion_token(buffer, cursor)
        context = self._analyze_completion_token(token)

        search_dir = self._resolve_completion_directory(session.cwd, context["lookup"])
        completions: List[Dict[str, object]] = []
        if search_dir is not None:
            completions = self._collect_completion_entries(
                search_dir,
                context["prefix"],
                context["separator"],
            )

        common_suffix = self._longest_common_prefix([entry["append"] for entry in completions])
        replacement_text = token
        applied = False

        if completions:
            if len(completions) == 1:
                suffix_to_use = completions[0]["append"]
                if not completions[0]["is_directory"]:
                    suffix_to_use = f"{suffix_to_use} "
            else:
                suffix_to_use = common_suffix or context["prefix"]

            replacement_text = context["quote"] + context["dir_context"] + suffix_to_use
            applied = replacement_text != token

        return {
            "session_id": session.session_id,
            "cwd": str(session.cwd),
            "replacement": {
                "start": token_start,
                "end": cursor,
                "text": replacement_text,
            },
            "applied": applied,
            "completions": [
                {
                    "value": entry["value"],
                    "is_directory": entry["is_directory"],
                    "path": entry["path"],
                }
                for entry in completions
            ],
            "matched_prefix": context["prefix"],
        }

    async def _get_session(self, session_id: Optional[str]) -> Optional[TerminalSession]:
        async with self._lock:
            session = self._sessions.get(session_id or "")
            if session:
                session.touch()
            return session

    def _resolve_base_directory(self, override_path: Optional[str]) -> Optional[Path]:
        if not override_path:
            return None
        candidate = Path(override_path).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        if resolved.exists() and resolved.is_dir():
            return resolved
        return None

    async def _get_or_create_session(self, session_id: Optional[str], base_path: Optional[str] = None) -> TerminalSession:
        async with self._lock:
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                resolved_override = self._resolve_base_directory(base_path)
                if resolved_override:
                    session.cwd = resolved_override
            else:
                initial_cwd = self._resolve_base_directory(base_path) or self.base_path
                session = TerminalSession(
                    session_id=self._generate_session_id(),
                    cwd=initial_cwd,
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

    async def stream_command_events(
        self,
        command: str,
        *,
        session_id: Optional[str],
        timeout: int = 120,
        env: Optional[Dict[str, str]] = None,
    ) -> AsyncIterator[bytes]:
        session = await self._get_or_create_session(session_id)
        normalized = (command or "").strip()

        if not normalized:
            raise RuntimeError("Command cannot be empty")

        if session.is_busy():
            raise RuntimeError("Terminal session is already running a command")

        if self._is_cd_command(normalized):
            response = await self._handle_cd_command(session, normalized, timeout)

            async def cd_generator() -> AsyncIterator[bytes]:
                yield self._encode_stream_event(
                    {
                        "type": "session",
                        "session_id": response["session_id"],
                        "cwd": response["cwd"],
                        "command": normalized,
                        "was_cd": True,
                    }
                )
                yield self._encode_stream_event(
                    {
                        "type": "exit",
                        "session_id": response["session_id"],
                        "cwd": response["cwd"],
                        "exit_code": response.get("exit_code"),
                        "success": response.get("success"),
                        "timed_out": response.get("timed_out", False),
                        "timeout_seconds": response.get("timeout_seconds", timeout),
                        "message": response.get("message"),
                        "was_cd": True,
                    }
                )

            return cd_generator()

        return await self._stream_process_events(session, normalized, timeout, env)

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
        try:
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
        except NotImplementedError:
            logger.warning("Async subprocess unsupported; using blocking fallback")
            return await self._execute_process_blocking(
                session,
                command,
                timeout,
                env_vars,
                creationflags,
            )

    async def _execute_process_blocking(
        self,
        session: TerminalSession,
        command: str,
        timeout: int,
        env_vars: Dict[str, str],
        creationflags: int,
    ) -> Dict[str, object]:
        def runner():
            process = subprocess.Popen(
                command,
                cwd=str(session.cwd),
                env=env_vars,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creationflags,
            )
            session.current_process = process
            session.current_command = command
            timed_out = False
            stdout = ""
            stderr = ""
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                stdout = exc.stdout or ""
                stderr = exc.stderr or ""
                process.kill()
            finally:
                session.touch()
                session.current_process = None
                session.current_command = None
            return process, stdout, stderr, timed_out

        try:
            process, stdout, stderr, timed_out = await asyncio.to_thread(runner)
        except Exception as exc:  # noqa: BLE001
            return self._build_response(
                session,
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                success=False,
                timeout=timeout,
                message=f"Terminal error: {exc}",
                was_cd=False,
            )

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

    async def _stream_process_events(
        self,
        session: TerminalSession,
        command: str,
        timeout: int,
        env: Optional[Dict[str, str]],
    ) -> AsyncIterator[bytes]:
        env_vars = os.environ.copy()
        if env:
            env_vars.update({str(key): str(value) for key, value in env.items() if value is not None})

        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(session.cwd),
                env=env_vars,
                stdout=PIPE,
                stderr=PIPE,
                start_new_session=os.name != "nt",
                creationflags=creationflags,
            )
        except NotImplementedError:
            logger.warning("Async subprocess unsupported for streaming; falling back to blocking mode")
            return await self._stream_process_events_blocking(
                session,
                command,
                timeout,
                env_vars,
                creationflags,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Unable to start process: {exc}") from exc

        return self._consume_async_stream_process(session, process, command, timeout)

    def _consume_async_stream_process(
        self,
        session: TerminalSession,
        process: Process,
        command: str,
        timeout: int,
    ) -> AsyncIterator[bytes]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        session.current_process = process
        session.current_command = command

        async def pump_stream(stream, stream_name: str) -> None:
            if stream is None:
                await queue.put({"type": "stream_closed", "stream": stream_name})
                return
            try:
                while True:
                    data = await stream.readline()
                    if not data:
                        break
                    text = self._sanitize_stream_line(self._decode_output(data))
                    await queue.put(
                        {
                            "type": "stream",
                            "stream": stream_name,
                            "text": text,
                        }
                    )
            finally:
                await queue.put({"type": "stream_closed", "stream": stream_name})

        stdout_task = asyncio.create_task(pump_stream(process.stdout, "stdout"))
        stderr_task = asyncio.create_task(pump_stream(process.stderr, "stderr"))

        timed_out = False

        async def guard() -> None:
            nonlocal timed_out
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                timed_out = True
                await self._terminate_process(process)
                await process.wait()

        guard_task = asyncio.create_task(guard())

        async def event_generator() -> AsyncIterator[bytes]:
            nonlocal timed_out
            active_streams = sum(stream is not None for stream in (process.stdout, process.stderr))
            if active_streams == 0:
                active_streams = 1
            try:
                yield self._encode_stream_event(
                    {
                        "type": "session",
                        "session_id": session.session_id,
                        "cwd": str(session.cwd),
                        "command": command,
                    }
                )
                while True:
                    if active_streams == 0 and queue.empty():
                        break
                    item = await queue.get()
                    if item["type"] == "stream_closed":
                        active_streams = max(0, active_streams - 1)
                        continue
                    if item["type"] == "stream":
                        yield self._encode_stream_event(
                            {
                                "type": item["stream"],
                                "text": item["text"],
                            }
                        )
                await guard_task
                exit_code = process.returncode if process.returncode is not None else -1
                interrupted = session.interrupted
                session.interrupted = False
                message = None
                if timed_out:
                    message = f"Command timed out after {timeout} seconds"
                elif interrupted:
                    message = "Command interrupted by user"
                success = exit_code == 0 and not timed_out and not interrupted
                yield self._encode_stream_event(
                    {
                        "type": "exit",
                        "session_id": session.session_id,
                        "cwd": str(session.cwd),
                        "exit_code": exit_code,
                        "success": success,
                        "timed_out": timed_out,
                        "timeout_seconds": timeout,
                        "message": message,
                        "was_cd": False,
                    }
                )
            except asyncio.CancelledError:
                await self._terminate_process(process)
                raise
            finally:
                stdout_task.cancel()
                stderr_task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                if not guard_task.done():
                    guard_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await guard_task
                session.current_process = None
                session.current_command = None
                session.touch()

        return event_generator()

    async def _stream_process_events_blocking(
        self,
        session: TerminalSession,
        command: str,
        timeout: int,
        env_vars: Dict[str, str],
        creationflags: int,
    ) -> AsyncIterator[bytes]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        process = subprocess.Popen(
            command,
            cwd=str(session.cwd),
            env=env_vars,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )

        session.current_process = process
        session.current_command = command

        async def pump_stream(stream, stream_name: str) -> None:
            if stream is None:
                await queue.put({"type": "stream_closed", "stream": stream_name})
                return
            try:
                while True:
                    line = await asyncio.to_thread(stream.readline)
                    if not line:
                        break
                    text = self._sanitize_stream_line(line)
                    await queue.put(
                        {
                            "type": "stream",
                            "stream": stream_name,
                            "text": text,
                        }
                    )
            finally:
                await queue.put({"type": "stream_closed", "stream": stream_name})

        stdout_task = asyncio.create_task(pump_stream(process.stdout, "stdout"))
        stderr_task = asyncio.create_task(pump_stream(process.stderr, "stderr"))

        timed_out = False

        async def guard() -> None:
            nonlocal timed_out
            try:
                await asyncio.to_thread(process.wait, timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                await self._terminate_process(process)
                await asyncio.to_thread(process.wait)

        guard_task = asyncio.create_task(guard())

        async def event_generator() -> AsyncIterator[bytes]:
            nonlocal timed_out
            active_streams = sum(stream is not None for stream in (process.stdout, process.stderr))
            if active_streams == 0:
                active_streams = 1
            try:
                yield self._encode_stream_event(
                    {
                        "type": "session",
                        "session_id": session.session_id,
                        "cwd": str(session.cwd),
                        "command": command,
                    }
                )
                while True:
                    if active_streams == 0 and queue.empty():
                        break
                    item = await queue.get()
                    if item["type"] == "stream_closed":
                        active_streams = max(0, active_streams - 1)
                        continue
                    if item["type"] == "stream":
                        yield self._encode_stream_event(
                            {
                                "type": item["stream"],
                                "text": item["text"],
                            }
                        )
                await guard_task
                exit_code = process.returncode if process.returncode is not None else -1
                interrupted = session.interrupted
                session.interrupted = False
                message = None
                if timed_out:
                    message = f"Command timed out after {timeout} seconds"
                elif interrupted:
                    message = "Command interrupted by user"
                success = exit_code == 0 and not timed_out and not interrupted
                yield self._encode_stream_event(
                    {
                        "type": "exit",
                        "session_id": session.session_id,
                        "cwd": str(session.cwd),
                        "exit_code": exit_code,
                        "success": success,
                        "timed_out": timed_out,
                        "timeout_seconds": timeout,
                        "message": message,
                        "was_cd": False,
                    }
                )
            except asyncio.CancelledError:
                await self._terminate_process(process)
                raise
            finally:
                stdout_task.cancel()
                stderr_task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                if not guard_task.done():
                    guard_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await guard_task
                session.current_process = None
                session.current_command = None
                session.touch()

        return event_generator()


    async def _interrupt_process(self, process) -> None:
        if process.returncode is not None:
            return

        if os.name == "nt":
            sent_ctrl_event = False
            # Preferred: Ctrl+C to terminate interactive commands like ping -t
            if hasattr(signal, "CTRL_C_EVENT"):
                try:
                    process.send_signal(signal.CTRL_C_EVENT)
                    sent_ctrl_event = True
                except ValueError:
                    pass
            # Fallback: Ctrl+Break to flush stats if Ctrl+C failed
            if not sent_ctrl_event and hasattr(signal, "CTRL_BREAK_EVENT"):
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    sent_ctrl_event = True
                except ValueError:
                    pass
            if not sent_ctrl_event:
                process.terminate()
        else:
            process.send_signal(signal.SIGINT)

        await asyncio.sleep(0.2)
        if process.returncode is None:
            process.terminate()
            await asyncio.sleep(0.2)
        if process.returncode is None:
            await self._force_kill_process_tree(process)

    async def _terminate_process(self, process) -> None:
        if process.returncode is not None:
            return

        process.terminate()
        await asyncio.sleep(0.2)
        if process.returncode is None:
            await self._force_kill_process_tree(process)

    async def _force_kill_process_tree(self, process) -> None:
        if process.returncode is not None:
            return

        if os.name == "nt":
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:  # noqa: BLE001
                process.kill()
        else:
            process.kill()

    def _normalize_cursor(self, text: str, cursor_position: Optional[int]) -> int:
        if cursor_position is None:
            return len(text)
        return max(0, min(cursor_position, len(text)))

    def _extract_completion_token(self, text: str, cursor: int) -> Tuple[int, str]:
        if not text:
            return 0, ""
        start = cursor
        while start > 0 and text[start - 1] not in COMPLETION_DELIMITERS:
            start -= 1
        return start, text[start:cursor]

    def _analyze_completion_token(self, token: str) -> Dict[str, object]:
        if not token:
            return {
                "quote": "",
                "core": "",
                "dir_context": "",
                "prefix": "",
                "lookup": "",
                "separator": os.sep,
                "trailing": False,
            }

        quote = token[0] if token[:1] in {"'", '"'} else ""
        core = token[1:] if quote else token
        trailing_sep = bool(core) and core[-1] in "/\\"
        stripped_core = core.rstrip("/\\") if trailing_sep else core
        separator = self._detect_separator(core)

        dir_part = ""
        prefix = stripped_core

        if trailing_sep:
            dir_part = stripped_core
            prefix = ""
        else:
            split_index = max(stripped_core.rfind("/"), stripped_core.rfind("\\"))
            if split_index == -1:
                dir_part = ""
                prefix = stripped_core
            else:
                dir_part = stripped_core[:split_index]
                prefix = stripped_core[split_index + 1 :]
                separator = stripped_core[split_index]

        if not separator:
            separator = os.sep

        dir_context = ""
        if trailing_sep and stripped_core:
            dir_context = stripped_core + separator
        elif dir_part:
            dir_context = dir_part + separator
        elif trailing_sep and not stripped_core and core:
            dir_context = core

        lookup = ""
        if trailing_sep:
            if stripped_core:
                lookup = stripped_core
            elif core:
                lookup = core
        else:
            lookup = dir_part

        return {
            "quote": quote,
            "core": core,
            "dir_context": dir_context,
            "prefix": prefix,
            "lookup": lookup,
            "separator": separator,
            "trailing": trailing_sep,
        }

    @staticmethod
    def _detect_separator(token: str) -> str:
        if "/" in token and "\\" not in token:
            return "/"
        if "\\" in token and "/" not in token:
            return "\\"
        return os.sep

    def _resolve_completion_directory(self, cwd: Path, target: Optional[str]) -> Optional[Path]:
        if not target:
            return cwd

        expanded = os.path.expanduser(target)
        candidate = Path(expanded)
        try:
            if candidate.is_absolute():
                resolved = candidate.resolve()
            else:
                resolved = (cwd / expanded).resolve()
        except (OSError, RuntimeError):
            return None

        if resolved.exists() and resolved.is_dir():
            return resolved
        return None

    def _collect_completion_entries(
        self,
        directory: Path,
        prefix: str,
        separator: str,
    ) -> List[Dict[str, object]]:
        results: List[Dict[str, object]] = []
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda entry: (not entry.is_dir(), entry.name.lower()),
            )
        except OSError:
            return results

        for entry in entries:
            name = entry.name
            if prefix and not name.startswith(prefix):
                continue

            is_directory = entry.is_dir()
            value = f"{name}{separator if is_directory else ''}"
            results.append(
                {
                    "value": value,
                    "append": value,
                    "is_directory": is_directory,
                    "path": str(entry),
                }
            )

            if len(results) >= TERMINAL_COMPLETION_LIMIT:
                break

        return results

    @staticmethod
    def _longest_common_prefix(items: Sequence[str]) -> str:
        if not items:
            return ""
        prefix = items[0]
        for value in items[1:]:
            while not value.startswith(prefix):
                prefix = prefix[:-1]
                if not prefix:
                    return ""
        return prefix

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
    def _sanitize_stream_line(text: str) -> str:
        if not text:
            return ""
        return text.rstrip("\r\n")

    @staticmethod
    def _encode_stream_event(payload: Dict[str, Any]) -> bytes:
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    @staticmethod
    def _generate_session_id() -> str:
        return secrets.token_hex(16)

