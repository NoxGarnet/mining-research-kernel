"""Small helpers for caller-authorized, durable artifact output."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

if os.name == "nt":
    import ctypes
    import msvcrt
else:
    ctypes = None
    msvcrt = None

REPARSE_POINT = 0x0400


def _absolute_without_follow(path: str | Path) -> Path:
    """Make a path absolute without resolving links in its final components."""
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    if os.name == "nt":
        try:
            return bool(getattr(path.lstat(), "st_file_attributes", 0) & REPARSE_POINT)
        except FileNotFoundError:
            return False
    return False


def _reject_reparse_chain(path: Path, label: str) -> None:
    current = _absolute_without_follow(path)
    while True:
        if os.path.lexists(current) and _is_reparse_point(current):
            raise ValueError(f"{label} cannot pass through a symlink or junction: {path}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _descriptor_path(descriptor: int) -> Path | None:
    if os.name == "nt":
        handle = msvcrt.get_osfhandle(descriptor)
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetFinalPathNameByHandleW(
            ctypes.c_void_p(handle), buffer, len(buffer), 0
        )
        if not length or length >= len(buffer):
            raise OSError("could not resolve the temporary output handle")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value)
    proc_link = Path(f"/proc/self/fd/{descriptor}")
    if proc_link.is_symlink():
        return Path(os.readlink(proc_link))
    return None


def _assert_descriptor_under(descriptor: int, root: Path) -> None:
    actual = _descriptor_path(descriptor)
    if actual is None:
        return
    try:
        actual.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("temporary output escaped the authorized directory") from exc


def ensure_output_directory(output: str | Path) -> Path:
    """Prepare an explicitly supplied output directory.

    The caller-selected directory is the authorization boundary. Existing
    links in the directory path are rejected, while an external ordinary
    directory remains valid.
    """
    raw = _absolute_without_follow(output)
    _reject_reparse_chain(raw, "output directory")
    if os.path.lexists(raw) and not raw.is_dir():
        raise ValueError(f"output directory is not a directory: {output}")
    raw.mkdir(parents=True, exist_ok=True)
    _reject_reparse_chain(raw, "output directory")
    return raw.resolve()


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8",
                      newline: str = "\n") -> Path:
    """Atomically replace one caller-authorized output file."""
    requested_target = _absolute_without_follow(path)
    parent = ensure_output_directory(requested_target.parent)
    target = parent / requested_target.name
    if os.path.lexists(target) and _is_reparse_point(target):
        raise ValueError(f"output file cannot be a symlink or junction: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(parent)
    )
    try:
        _assert_descriptor_under(descriptor, parent)
        _reject_reparse_chain(parent, "output directory")
        with os.fdopen(descriptor, "w", encoding=encoding, newline=newline) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        _reject_reparse_chain(parent, "output directory")
        if os.path.lexists(target) and _is_reparse_point(target):
            raise ValueError(f"output file cannot be a symlink or junction: {path}")
        os.replace(temporary_name, target)
        if os.name != "nt":
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return target


def atomic_write_json(path: str | Path, value: Any) -> Path:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return atomic_write_text(path, text)
