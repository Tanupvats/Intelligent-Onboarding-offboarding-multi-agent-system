

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Email")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool_env(name: str, default: bool = True) -> bool:
    v = os.getenv(name, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _require_config() -> None:
    missing = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD") if not _env(k)]
    if missing:
        # Raised from within the tool call so the error is delivered to the client
        raise RuntimeError(f"SMTP config incomplete. Missing: {', '.join(missing)}")


def _dedup(items: List[str]) -> List[str]:
    seen, out = set(), []
    for x in items:
        x = (x or "").strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


@mcp.tool()
def send_email(
    receiver: List[str],
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,  # reserved for future use
) -> str:
    _require_config()

    to_list = _dedup(receiver or [])
    if not to_list:
        raise ValueError("No recipients")
    if not subject or not body:
        raise ValueError("Subject and body are required")

    host = _env("SMTP_HOST", "smtp.gmail.com")
    try:
        port = int(_env("SMTP_PORT", "587"))
    except ValueError:
        raise RuntimeError("SMTP_PORT must be an integer")
    use_tls = _bool_env("SMTP_STARTTLS", True)
    try:
        timeout = int(_env("SMTP_TIMEOUT", "15"))
    except ValueError:
        timeout = 15
    sender = _env("SMTP_FROM") or _env("SMTP_USER") or "no-reply@example.com"
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            server.ehlo()
            if use_tls:
                ctx = ssl.create_default_context()
                server.starttls(context=ctx)
                server.ehlo()
            server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise RuntimeError(f"SMTP auth failed: {e.smtp_code} {e.smtp_error!r}") from e
    except smtplib.SMTPException as e:
        raise RuntimeError(f"SMTP error: {e}") from e
    except (TimeoutError, OSError) as e:
        raise RuntimeError(f"SMTP network error: {e}") from e

    return f"Sent to {', '.join(to_list)}"


if __name__ == "__main__":
    mcp.run()
