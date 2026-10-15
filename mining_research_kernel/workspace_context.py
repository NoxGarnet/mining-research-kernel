"""Bounded navigation from an explicit lightweight workspace INDEX.md."""
from __future__ import annotations

import re
import stat
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_INDEX_BYTES = 65536
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _reject_reparse_chain(path: Path, root: Path) -> bool:
    """Return whether a lexical path contains a link/reparse point."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE:
            return True
    return False


def _argv(project_root: Path) -> list[str]:
    cli = Path(__file__).resolve().parents[1] / "mining_kernel.py"
    return [sys.executable, "-B", "-X", "utf8", str(cli), "project-context",
            "--project-root", str(project_root)]


def _strip_fences(text: str) -> str:
    """Mask fenced Markdown examples, including an unclosed final fence."""
    lines = text.splitlines(keepends=True)
    output, marker, width = [], None, 0
    for line in lines:
        match = re.match(r"^[ \t]{0,3}(\x60{3,}|~{3,})(.*?)(?:\r?\n)?$", line)
        if marker is None:
            if match:
                fence = match.group(1)
                marker, width = fence[0], len(fence)
                output.append(re.sub(r"[^\r\n]", " ", line))
            else:
                output.append(line)
        else:
            output.append(re.sub(r"[^\r\n]", " ", line))
            closing = re.match(r"^[ \t]{0,3}(\x60{3,}|~{3,})[ \t]*(?:\r?\n)?$", line)
            if closing and closing.group(1)[0] == marker and len(closing.group(1)) >= width:
                marker = None
    return "".join(output)


def workspace_context(workspace_root: str | Path, *, max_index_bytes: int = MAX_INDEX_BYTES) -> dict:
    supplied = Path(workspace_root).expanduser().absolute()
    if max_index_bytes < 1:
        raise ValueError("max_index_bytes must be positive")
    # Inspect the caller's lexical path before resolve() can hide a symlink.
    if _reject_reparse_chain(supplied, Path(supplied.anchor)):
        return _empty(supplied, "workspace root path contains a symlink or reparse point")
    root = supplied
    try:
        root = root.resolve(strict=False)
    except OSError:
        return _empty(root, "workspace root does not exist")
    if not root.exists():
        return _empty(root, "workspace root does not exist")
    if not root.is_dir():
        return _empty(root, "workspace root is not a directory")
    index = root / "INDEX.md"
    if _reject_reparse_chain(index, root):
        return _empty(root, "INDEX.md path is a symlink or reparse point")
    try:
        with index.open("rb") as stream:
            raw = stream.read(max_index_bytes + 1)
    except FileNotFoundError:
        return _empty(root, "INDEX.md is missing")
    clipped = len(raw) > max_index_bytes
    text = raw[:max_index_bytes].decode("utf-8-sig", errors="replace")
    prose = _strip_fences(text)
    rows, seen, diagnostics = [], set(), []
    for match in re.finditer(r"(?<!!)\[[^\]\n]+\]\((<[^>\n]+>|[^\s()]+)\)", prose):
        target = match.group(1).strip("<>")
        try:
            url = urlsplit(target)
        except ValueError as exc:
            diagnostics.append(f"malformed INDEX.md link ignored: {exc}")
            continue
        if url.scheme or url.netloc or url.query or not url.path:
            continue
        relative = unquote(url.path).replace("\\", "/")
        parts = relative.split("/")
        if (len(parts) != 3 or parts[0] != "projects" or parts[1] in {"", ".", ".."}
                or ":" in parts[1] or parts[1].rstrip(" .") != parts[1]
                or any(ord(char) < 32 for char in parts[1])
                or parts[2] not in {"START.md", "README.md"}):
            continue
        rel = "/".join(parts)
        if rel in seen:
            continue
        seen.add(rel)
        candidate = root.joinpath(*parts)
        unsafe = _reject_reparse_chain(candidate, root)
        exists = False
        if not unsafe:
            try:
                exists = candidate.is_file()
            except OSError:
                pass
        project_root = root / "projects" / parts[1]
        rows.append({"project_id": parts[1], "entry": rel, "candidate": True,
                     "existence": "not_checked" if unsafe else ("exists" if exists else "missing"),
                     "entry_read": False, "entry_verified": False,
                     "status": "unsafe_path_not_followed" if unsafe else "index_candidate_only",
                     "argv": _argv(project_root) if not unsafe else None})
    if clipped:
        diagnostics.append(f"INDEX.md truncated at {max_index_bytes} bytes; only the prefix was inspected")
    if "\ufffd" in text:
        diagnostics.append("INDEX.md contains invalid UTF-8; replacement characters were used")
    if not rows:
        diagnostics.append("no project START.md or README.md links recognized under projects/")
    return {"type": "WorkspaceContextView", "workspace_root": str(root), "read_only": True,
            "index": {"path": str(index), "read": True, "bytes_read": len(raw), "truncated": clipped},
            "automatic_selection": False, "projects": rows, "diagnostics": diagnostics,
            "limitations": ["Only the bounded root INDEX.md was read; project entries and research materials were not opened.",
                            "Link recognition is lexical navigation, not project-content or tool-availability verification."]}


def _empty(root: Path, message: str) -> dict:
    return {"type": "WorkspaceContextView", "workspace_root": str(root), "read_only": True,
            "index": {"path": str(root / "INDEX.md"), "read": False, "bytes_read": 0, "truncated": False},
            "automatic_selection": False, "projects": [], "diagnostics": [message],
            "limitations": ["No project entries or research materials were opened."]}
