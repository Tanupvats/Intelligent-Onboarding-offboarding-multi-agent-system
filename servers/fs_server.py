

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import List

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Filesystem")


def _allowed_roots() -> List[Path]:
    raw = os.getenv("FS_ALLOWED_DIRS", "./uploads,./data")
    roots = []
    for d in raw.split(","):
        d = d.strip()
        if not d:
            continue
        try:
            roots.append(Path(d).resolve(strict=False))
        except Exception:
            continue
    return roots


def _max_bytes() -> int:
    try:
        return int(os.getenv("FS_MAX_BYTES", str(25 * 1024 * 1024)))
    except ValueError:
        return 25 * 1024 * 1024


def _validate_path(req: str, *, for_write: bool = False) -> Path:
    """
    Resolve `req` (which may be relative) and confirm it lies inside one
    of the allow-list roots. For writes, additionally reject symlink targets.
    """
    if not req or not isinstance(req, str):
        raise ValueError("Path required")

    target = Path(req).resolve(strict=False)
    roots = _allowed_roots()
    if not roots:
        raise PermissionError("No allowed dirs configured")

    inside = False
    for root in roots:
        try:
            target.relative_to(root)
            inside = True
            break
        except ValueError:
            continue
    if not inside:
        raise PermissionError(f"Path not allowed: {target}")

    if for_write and target.is_symlink():
        # Refuse to follow symlinks on writes — prevents sandbox escape
        # via a pre-planted symlink.
        raise PermissionError("Refusing to write through a symlink")

    return target


@mcp.tool()
def write_file(path: str, content: str) -> str:
    p = _validate_path(path, for_write=True)
    encoded = content.encode("utf-8")
    if len(encoded) > _max_bytes():
        raise ValueError(f"Payload exceeds FS_MAX_BYTES ({_max_bytes()})")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(encoded)
    return f"Wrote {p.name} ({len(encoded)} bytes)"


@mcp.tool()
def read_file(path: str) -> str:
    p = _validate_path(path)
    if not p.exists():
        raise FileNotFoundError(f"Not found: {p.name}")
    return p.read_text(encoding="utf-8", errors="replace")


@mcp.tool()
def write_bytes(path: str, content_b64: str) -> str:
    p = _validate_path(path, for_write=True)
    try:
        data = base64.b64decode(content_b64, validate=True)
    except Exception as e:
        raise ValueError(f"Invalid base64: {e}")
    if len(data) > _max_bytes():
        raise ValueError(f"Payload exceeds FS_MAX_BYTES ({_max_bytes()})")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return f"Wrote binary {p.name} ({len(data)} bytes)"


@mcp.tool()
def read_bytes(path: str) -> str:
    p = _validate_path(path)
    if not p.exists():
        raise FileNotFoundError(f"Not found: {p.name}")
    return base64.b64encode(p.read_bytes()).decode("ascii")


if __name__ == "__main__":
    mcp.run()
