

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

from .config import get_settings
from .mcp_client import AsyncMCPToolClient

_mcp = AsyncMCPToolClient()


# Fields we redact / never expose via the API even if they show up in the CSV.
_REDACT_FIELDS = {"password", "salary", "ssn", "bank_account"}


async def list_employees() -> List[Dict[str, Any]]:
    path = get_settings().EMPLOYEES_CSV
    text = await _mcp.read_text(path)
    if not text or not text.strip() or text.startswith("ToolExecutionError"):
        return []
    rows = list(csv.DictReader(io.StringIO(text)))
    for r in rows:
        for k in list(r.keys()):
            if k.lower() in _REDACT_FIELDS:
                r.pop(k, None)
    return rows
