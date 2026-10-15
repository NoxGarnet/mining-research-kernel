"""Create the minimal, file-native mining research workspace starter."""
from __future__ import annotations

import re
import stat
from pathlib import Path


_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates" / "starter"


def _reject_reparse_chain(path: Path) -> None:
    """Reject symlinks and Windows junctions, including existing parents."""
    absolute = Path(path).expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE:
            raise ValueError(f"refusing a symlink or reparse-point path: {current}")


def _markdown_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("question must be a non-empty string")
    if "\x00" in text:
        raise ValueError("question cannot contain NUL")
    # Blockquote each line and escape Markdown syntax so user content stays data.
    escaped = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        line = re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", line)
        escaped.append("> " + line)
    return "\n".join(escaped)


def init_workspace(target: str | Path, project_id: str, question: str) -> Path:
    """Initialize a new or empty root with exactly three Markdown files."""
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise ValueError("project_id must match ^[a-z][a-z0-9_-]{1,63}$")
    question_md = _markdown_text(question)
    root = Path(target).expanduser()
    _reject_reparse_chain(root)
    root = root.absolute()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("refusing to initialize a non-empty directory")
    project = root / "projects" / project_id
    _reject_reparse_chain(project)
    if project.exists():
        raise ValueError(f"project already exists: {project_id}")

    values = {
        "AGENTS.md": (_TEMPLATE_ROOT / "AGENTS.md").read_text(encoding="utf-8"),
        "INDEX.md": (_TEMPLATE_ROOT / "INDEX.md").read_text(encoding="utf-8").replace("{{PROJECT_ID}}", project_id),
        f"projects/{project_id}/START.md": (_TEMPLATE_ROOT / "START.md").read_text(encoding="utf-8").replace("{{PROJECT_ID}}", project_id).replace("{{QUESTION}}", question_md),
    }
    root.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True)
    created: list[Path] = []
    try:
        for relative, content in values.items():
            path = root / relative
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
            created.append(path)
    except Exception:
        # Remove only files created by this invocation; preserve any collision.
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return root
