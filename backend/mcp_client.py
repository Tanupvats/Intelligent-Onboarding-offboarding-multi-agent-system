

from __future__ import annotations

import base64
import json
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import get_settings


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: List[str]
    env: Optional[Dict[str, str]] = None


def default_servers() -> Dict[str, MCPServerConfig]:
    s = get_settings()
    base_env = os.environ.copy()

    email_env = {
        **base_env,
        "SMTP_HOST": s.SMTP_HOST,
        "SMTP_PORT": str(s.SMTP_PORT),
        "SMTP_USER": s.SMTP_USER,
        "SMTP_PASSWORD": s.SMTP_PASSWORD,
        "SMTP_STARTTLS": "true" if s.SMTP_STARTTLS else "false",
        "SMTP_FROM": s.smtp_from_effective,
        "SMTP_TIMEOUT": str(s.SMTP_TIMEOUT),
    }
    fs_env = {
        **base_env,
        "FS_ALLOWED_DIRS": s.FS_ALLOWED_DIRS,
        "FS_MAX_BYTES": str(s.FS_MAX_BYTES),
    }

    return {
        "filesystem": MCPServerConfig(
            name="filesystem",
            command=s.MCP_FS_COMMAND,
            args=s.MCP_FS_ARGS.split(),
            env=fs_env,
        ),
        "email": MCPServerConfig(
            name="email",
            command=s.MCP_EMAIL_COMMAND,
            args=s.MCP_EMAIL_ARGS.split(),
            env=email_env,
        ),
    }


class _MCPConnection:
    def __init__(self, cfg: MCPServerConfig):
        self.cfg = cfg
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None

    async def __aenter__(self) -> ClientSession:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        params = StdioServerParameters(command=self.cfg.command, args=self.cfg.args, env=self.cfg.env)
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if self._stack:
            await self._stack.__aexit__(exc_type, exc, tb)
        self._stack, self._session = None, None


class AsyncMCPToolClient:
    def __init__(self, servers: Optional[Dict[str, MCPServerConfig]] = None):
        self.servers = servers or default_servers()

    async def _call(self, server: str, tool: str, args: Dict[str, Any]) -> Any:
        try:
            async with _MCPConnection(self.servers[server]) as session:
                return await session.call_tool(tool, args)
        except Exception as e:
            return f"ToolExecutionError: Failed to execute {tool}. Details: {str(e)}"

    async def write_text(self, path: str, text: str) -> str:
        res = await self._call("filesystem", "write_file", {"path": path, "content": text})
        return (
            res
            if isinstance(res, str) and res.startswith("ToolExecutionError")
            else f"Successfully wrote to {path}"
        )

    async def read_text(self, path: str) -> str:
        res = await self._call("filesystem", "read_file", {"path": path})
        if isinstance(res, str) and res.startswith("ToolExecutionError"):
            return res
        try:
            if hasattr(res, "content") and res.content:
                data = getattr(res.content[0], "text", None) or getattr(res.content[0], "data", None)
                if isinstance(data, (bytes, bytearray)):
                    return data.decode("utf-8", errors="ignore")
                return str(data)
            return "Error: File was empty."
        except Exception as e:
            return f"Error parsing file: {str(e)}"

    async def create_ticket(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = get_settings().MCP_TICKET_MIRROR
        prior = await self.read_text(path)
        if prior.startswith("ToolExecutionError"):
            prior = ""
        new_text = (prior + "\n" if prior and prior.strip() else "") + json.dumps(payload, ensure_ascii=False)
        await self.write_text(path, new_text)
        return {"ok": True, "mirror_path": path, "result": payload}

    async def send_email(
        self, to: str, subject: str, body: str, attachments: Optional[List[str]] = None
    ) -> str:
        args: Dict[str, Any] = {"receiver": [to], "subject": subject, "body": body}
        if attachments:
            args["attachments"] = attachments

        res = await self._call("email", "send_email", args)
        if isinstance(res, str) and res.startswith("ToolExecutionError"):
            return res
        if hasattr(res, "isError") and res.isError:
            error_text = getattr(res.content[0], "text", str(res)) if res.content else str(res)
            return f"ToolExecutionError from Email Server: {error_text}"
        return f"Successfully sent to {to}"

    async def write_bytes(self, path: str, data: bytes) -> str:
        b64 = base64.b64encode(data).decode("utf-8")
        res = await self._call("filesystem", "write_bytes", {"path": path, "content_b64": b64})
        return (
            res
            if isinstance(res, str) and res.startswith("ToolExecutionError")
            else f"Saved binary to {path}"
        )

    async def read_bytes(self, path: str) -> Union[bytes, str]:
        res = await self._call("filesystem", "read_bytes", {"path": path})
        if isinstance(res, str) and res.startswith("ToolExecutionError"):
            return res
        if hasattr(res, "content") and res.content:
            text_b64 = getattr(res.content[0], "text", None) or getattr(res.content[0], "data", None) or ""
            return base64.b64decode(text_b64.encode("utf-8"))
        return b""
