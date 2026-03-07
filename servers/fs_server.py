import os, base64
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Filesystem")
def _validate_path(req: str) -> Path:
    rp = Path(req).resolve()
    for d in [Path(d.strip()).resolve() for d in os.getenv("FS_ALLOWED_DIRS", "./uploads,./data").split(",") if d.strip()]:
        try:
            if rp.is_relative_to(d): return rp
        except:
            if str(rp).startswith(str(d)): return rp
    raise PermissionError("Path out of bounds.")

@mcp.tool()
def write_file(path: str, content: str) -> str:
    p = _validate_path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8")
    return f"Wrote to {p.name}"

@mcp.tool()
def read_file(path: str) -> str: return _validate_path(path).read_text(encoding="utf-8")

@mcp.tool()
def write_bytes(path: str, content_b64: str) -> str:
    p = _validate_path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(base64.b64decode(content_b64))
    return f"Wrote binary {p.name}"

@mcp.tool()
def read_bytes(path: str) -> str: return base64.b64encode(_validate_path(path).read_bytes()).decode('utf-8')

if __name__ == "__main__": mcp.run()