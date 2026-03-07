"""
tickets.py
Async data layer using asyncio.Lock() to prevent race conditions.
"""
import csv, io, datetime, os, asyncio
from typing import Dict, List, Optional
from .mcp_client import AsyncMCPToolClient

DATA_PATH = os.path.join('data', 'ticket.csv')
FIELDS = ['ticket_id', 'type', 'flow', 'step', 'employee_id', 'employee_name', 'department', 'manager', 'status', 'priority', 'created_at', 'updated_at', 'description', 'assigned_to', 'sla_due', 'comments', 'approvals', 'attachments']

mcp = AsyncMCPToolClient()
ticket_lock = asyncio.Lock()

async def _read_all() -> List[Dict]:
    text = await mcp.read_text(DATA_PATH)
    if not text or not text.strip() or text.startswith("ToolExecutionError"): return []
    return list(csv.DictReader(io.StringIO(text)))

async def _write_all(rows: List[Dict]):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS)
    writer.writeheader()
    for r in rows: writer.writerow(r)
    await mcp.write_text(DATA_PATH, buf.getvalue())

def next_ticket_id(rows: List[Dict]) -> str:
    max_id = 1000
    for r in rows:
        try: max_id = max(max_id, int(str(r.get('ticket_id', '')).replace('T', '')))
        except: continue
    return f"T{max_id + 1}"

async def create_ticket(**kwargs) -> Dict:
    async with ticket_lock:
        rows = await _read_all()
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ticket = {k: '' for k in FIELDS}
        ticket.update({k: str(v) for k, v in kwargs.items()})
        ticket['ticket_id'] = ticket.get('ticket_id') or next_ticket_id(rows)
        ticket['created_at'] = now
        ticket['updated_at'] = now
        rows.append(ticket)
        await _write_all(rows)
        return ticket

async def update_ticket(ticket_id: str, **updates) -> Dict:
    async with ticket_lock:
        rows = await _read_all()
        found = None
        for r in rows:
            if r.get('ticket_id') == ticket_id:
                r.update({k: str(v) for k, v in updates.items()})
                r['updated_at'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                found = r
                break
        if found: await _write_all(rows)
        return found or {}

async def list_tickets() -> List[Dict]:
    async with ticket_lock: return await _read_all()

async def list_tickets_by_employee(employee_id: str) -> List[Dict]:
    async with ticket_lock:
        return [r for r in await _read_all() if r.get('employee_id') == employee_id]