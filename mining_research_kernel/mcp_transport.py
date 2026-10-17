"""Bounded, read-only JSON-RPC stdio transport for explicitly selected MCP Hosts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from typing import Any

from mining_research_kernel.artifacts import _reject_reparse_chain

_MAX_CONFIG = 32 * 1024
_MAX_LINE = 2 * 1024 * 1024
_JSONRPC_VERSION = "2.0"
_PROTOCOL_VERSION = "2024-11-05"


class MCPHostError(RuntimeError):
    """Sanitized Host/profile/protocol failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _absolute_path(value: Any, field: str, *, directory: bool = False) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or not Path(value).is_absolute():
        raise ValueError(f"{field} must be an absolute path")
    path = Path(value)
    _reject_reparse_chain(path, field)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{field} must name an existing path") from exc
    if directory and not resolved.is_dir():
        raise ValueError(f"{field} must name an existing directory")
    if not directory and not resolved.is_file():
        raise ValueError(f"{field} must name an existing executable file")
    return str(resolved)


class MCPStdioReader:
    """Short-lived read-only MCP client; one instance is one Host launch."""

    def __init__(self, registration: dict[str, Any], read_operations: frozenset[str]):
        self.registration = dict(registration)
        self.read_operations = frozenset(read_operations)
        self.tool_call_started = False
        self.process: subprocess.Popen[bytes] | None = None
        self._lines: queue.Queue[bytes | BaseException | None] = queue.Queue(maxsize=8)
        self._stop_reader = threading.Event()
        self._stderr_thread: threading.Thread | None = None
        self._stdout_thread: threading.Thread | None = None
        self._job_handle: Any = None
        self._kernel32: Any = None
        self._next_id = 0
        self._tools: set[str] = set()

    def __enter__(self) -> "MCPStdioReader":
        profile = self.registration
        kwargs: dict[str, Any] = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                                  "stderr": subprocess.PIPE, "cwd": profile.get("cwd"),
                                  "bufsize": 0}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            self.process = subprocess.Popen([profile["command"], *profile["args"]], **kwargs)
        except OSError as exc:
            raise MCPHostError("host_unavailable") from exc
        self._attach_windows_job()
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        try:
            self._rpc("initialize", {"protocolVersion": _PROTOCOL_VERSION,
                                      "capabilities": {}, "clientInfo": {"name": "mining-research-kernel", "version": "1"}})
            self._notify("notifications/initialized")
            self._load_tools()
        except Exception:
            self.close()
            raise
        return self

    def _attach_windows_job(self) -> None:
        if os.name != "nt" or self.process is None:
            return
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimitInformation), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                     wintypes.LPVOID, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(info), ctypes.sizeof(info))
        assigned = configured and kernel32.AssignProcessToJobObject(
            handle, wintypes.HANDLE(int(self.process._handle)))
        if assigned:
            self._job_handle = handle
            self._kernel32 = kernel32
        else:
            kernel32.CloseHandle(handle)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None

        def publish(item: bytes | BaseException | None) -> bool:
            while not self._stop_reader.is_set():
                try:
                    self._lines.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        try:
            line = bytearray()
            while True:
                chunk = self.process.stdout.read(65536)
                if not chunk:
                    publish(bytes(line) if line else None)
                    return
                line.extend(chunk)
                while True:
                    boundary = line.find(b"\n")
                    if boundary < 0:
                        if len(line) > _MAX_LINE:
                            publish(MCPHostError("response_too_large"))
                            return
                        break
                    if boundary > _MAX_LINE:
                        publish(MCPHostError("response_too_large"))
                        return
                    complete = bytes(line[:boundary])
                    del line[:boundary + 1]
                    if not publish(complete):
                        return
        except BaseException as exc:
            publish(exc)

    def _drain_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        try:
            while self.process.stderr.read(4096):
                pass
        except (OSError, ValueError):
            pass

    def _write(self, message: dict[str, Any], deadline: float) -> None:
        if self.process is None or self.process.stdin is None or self.process.poll() is not None:
            raise MCPHostError("host_closed")
        try:
            encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False,
                                 allow_nan=False).encode("utf-8") + b"\n"
        except (TypeError, ValueError, UnicodeError) as exc:
            raise MCPHostError("invalid_request") from exc
        if len(encoded) > _MAX_LINE:
            raise MCPHostError("request_too_large")
        completed = threading.Event()
        failures: list[BaseException] = []

        def write_request() -> None:
            try:
                assert self.process is not None and self.process.stdin is not None
                view = memoryview(encoded)
                while view:
                    written = self.process.stdin.write(view)
                    if not written:
                        raise BrokenPipeError("short stdio write")
                    view = view[written:]
            except BaseException as exc:
                failures.append(exc)
            finally:
                completed.set()

        writer = threading.Thread(target=write_request, daemon=True)
        writer.start()
        if not completed.wait(max(0.0, deadline - time.monotonic())):
            raise MCPHostError("host_timeout")
        if failures:
            raise MCPHostError("host_closed") from failures[0]

    def _receive(self, request_id: int, deadline: float) -> dict[str, Any]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPHostError("host_timeout")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise MCPHostError("host_timeout") from exc
            if isinstance(line, BaseException):
                code = line.code if isinstance(line, MCPHostError) else "host_io_error"
                raise MCPHostError(code) from None
            if line is None:
                raise MCPHostError("host_closed")
            try:
                message = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object,
                                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))
            except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
                raise MCPHostError("malformed_response") from exc
            if not isinstance(message, dict) or message.get("jsonrpc") != _JSONRPC_VERSION:
                raise MCPHostError("malformed_response")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise MCPHostError("host_rpc_error")
            if "result" not in message or not isinstance(message["result"], dict):
                raise MCPHostError("malformed_response")
            return message["result"]

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + self.registration["timeout_seconds"]
        self._next_id += 1
        request_id = self._next_id
        try:
            self._write({"jsonrpc": _JSONRPC_VERSION, "id": request_id, "method": method, "params": params}, deadline)
            return self._receive(request_id, deadline)
        except MCPHostError:
            self.close()
            raise

    def _notify(self, method: str) -> None:
        self._write({"jsonrpc": _JSONRPC_VERSION, "method": method},
                    time.monotonic() + self.registration["timeout_seconds"])

    def _load_tools(self) -> None:
        cursor = None
        found: set[str] = set()
        cursors: set[str] = set()
        for _ in range(100):
            params = {} if cursor is None else {"cursor": cursor}
            page = self._rpc("tools/list", params)
            tools = page.get("tools")
            if not isinstance(tools, list):
                raise MCPHostError("malformed_tool_list")
            for tool in tools:
                if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                    found.add(tool["name"])
            cursor = page.get("nextCursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise MCPHostError("malformed_tool_cursor")
            cursors.add(cursor)
        else:
            raise MCPHostError("tool_list_page_limit")
        self._tools = found & self.read_operations

    def __call__(self, operation: str, params: dict[str, Any]) -> Any:
        if operation not in self.read_operations:
            raise MCPHostError("operation_not_allowed")
        if operation not in self._tools:
            raise MCPHostError("required_read_tools_missing")
        return self._rpc("tools/call", {"name": operation, "arguments": params})

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        self.process = None
        self._stop_reader.set()
        job_closed = False
        if self._job_handle is not None:
            job_closed = bool(self._kernel32.CloseHandle(self._job_handle))
            if job_closed:
                self._job_handle = None
                self._kernel32 = None
        if process.poll() is None and job_closed:
            try:
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        elif process.poll() is None:
            if os.name == "nt":
                # Target only this launched process tree, including cmd wrappers.
                try:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=2, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.terminate()
                    except OSError:
                        pass
            else:
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if self._job_handle is not None:
            self._kernel32.CloseHandle(self._job_handle)
            self._job_handle = None
            self._kernel32 = None
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        for stream in (process.stdout, process.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass


__all__ = ["MCPHostError", "MCPStdioReader", "_MAX_CONFIG", "_absolute_path", "_unique_object"]
