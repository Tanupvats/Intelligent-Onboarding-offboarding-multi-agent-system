

from __future__ import annotations

import io
import csv
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

# Load .env BEFORE Settings is instantiated
load_dotenv()

from .config import get_settings
from .logging_config import configure_logging, get_logger, request_id_ctx
from .mcp_client import AsyncMCPToolClient
from .security import auth_required, issue_token
from .tickets import list_tickets, list_tickets_by_employee, update_ticket
from .employees import list_employees
from .graph import app as workflow_app
from .agents import draft_notification_email

configure_logging()
log = get_logger(__name__)
settings = get_settings()


# --- App --------------------------------------------------------------------
app = FastAPI(title=settings.APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach (or propagate) X-Request-ID and time every request."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        start = time.time()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "unhandled_exception",
                extra={"path": request.url.path, "method": request.method},
            )
            raise
        finally:
            dur_ms = int((time.time() - start) * 1000)
            try:
                log.info(
                    "request",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status": getattr(locals().get("response"), "status_code", 0),
                        "duration_ms": dur_ms,
                        "ua": request.headers.get("user-agent", "-")[:120],
                    },
                )
            finally:
                request_id_ctx.reset(token)

        response.headers["X-Request-ID"] = rid
        return response


app.add_middleware(RequestIDMiddleware)


@app.exception_handler(HTTPException)
async def _http_exc_handler(_: Request, exc: HTTPException):
    # Never leak server internals; always return a clean JSON body.
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": request_id_ctx.get()},
    )


mcp = AsyncMCPToolClient()


# --- Liveness / readiness --------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "env": settings.APP_ENV}


@app.get("/readyz")
async def readyz():
    """Minimal readiness check — confirms we can read the users CSV."""
    try:
        txt = await mcp.read_text(settings.USERS_CSV)
        ready = bool(txt) and not txt.startswith("ToolExecutionError")
    except Exception:
        ready = False
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"ready": ready},
    )


# --- Auth -------------------------------------------------------------------

class LoginPayload(BaseModel):
    email: str
    password: str


@app.post("/auth/login")
async def login(payload: LoginPayload):
    txt = await mcp.read_text(settings.USERS_CSV)
    if not txt or txt.startswith("ToolExecutionError"):
        log.error("users_csv_unreadable")
        raise HTTPException(status_code=503, detail="Authentication backend unavailable")

    users = list(csv.DictReader(io.StringIO(txt)))
    for u in users:
        if u.get("email", "").lower() == payload.email.lower() and u.get("password", "") == payload.password:
            profile = {
                "email": payload.email,
                "employee_id": u.get("employee_id", ""),
                "name": u.get("name", ""),
                "department": u.get("department", ""),
                "manager": u.get("manager", ""),
                "role": u.get("role", "employee"),
            }
            token = issue_token(profile)
            log.info("login_ok", extra={"employee_id": profile["employee_id"]})
            return {"token": token, "profile": profile}

    log.warning("login_failed", extra={"email": payload.email})
    raise HTTPException(status_code=401, detail="Invalid credentials")


# --- Workflow invocation helper --------------------------------------------

async def _invoke_graph(profile: dict, kind: str, step: str, payload: dict) -> dict:
    emp = {
        "id": profile["employee_id"],
        "name": profile["name"],
        "department": profile["department"],
        "manager": profile["manager"],
    }
    config = {"configurable": {"thread_id": profile["employee_id"]}}
    return await workflow_app.ainvoke(
        {"kind": kind, "step": step, "employee": emp, "payload": payload},
        config,
    )


# --- Progress ---------------------------------------------------------------

@app.get("/progress/{flow}")
async def get_progress(flow: str, profile: Dict[str, Any] = Depends(auth_required)):
    tickets = await list_tickets_by_employee(profile["employee_id"])
    flow_tickets = {t.get("step"): t for t in tickets if t.get("flow") == flow}

    def _evaluate(step_name: str, prev_status: str):
        if prev_status not in ("completed", "none_required"):
            return "locked", None
        ticket = flow_tickets.get(step_name)
        if not ticket:
            return "unlocked", None
        t_status = (ticket.get("status") or "").lower()
        if t_status in ("done", "closed", "approved"):
            return "completed", ticket
        if t_status in ("rejected", "blocked"):
            return "rejected", ticket
        return "pending_hr", ticket

    if flow == "onboarding":
        s1, s1t = _evaluate("offer", "completed")
        s2, s2t = _evaluate("documents", s1)
        s3, s3t = _evaluate("assets", s2)
    else:
        s1, s1t = _evaluate("initiation", "completed")
        s2, s2t = _evaluate("approval", s1)
        s3, s3t = _evaluate("exit", s2)

    return {
        "step1": s1, "step2": s2, "step3": s3,
        "tickets": {"step1": s1t, "step2": s2t, "step3": s3t},
    }


# --- Onboarding endpoints ---------------------------------------------------

class OfferPayload(BaseModel):
    accepted: bool
    reason: str = ""


@app.post("/onboarding/offer")
async def onboarding_offer(payload: OfferPayload, profile: Dict[str, Any] = Depends(auth_required)):
    await _invoke_graph(profile, "onboarding", "offer",
                        {"accepted": payload.accepted, "reason": payload.reason})
    return {"status": "success"}


@app.post("/onboarding/documents")
async def onboarding_documents(
    profile: Dict[str, Any] = Depends(auth_required),
    files: List[UploadFile] = File([]),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    allowed_exts = settings.allowed_upload_exts_set
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024

    uploads_dir = Path(settings.UPLOADS_DIR).resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)

    saved: List[str] = []
    for f in files:
        # Extension allow-list
        ext = (Path(f.filename).suffix or "").lstrip(".").lower()
        if ext not in allowed_exts:
            raise HTTPException(status_code=400, detail=f"Extension not allowed: .{ext}")

        # Build a safe target filename (strip directory parts, keep simple chars)
        safe_name = "".join(c for c in Path(f.filename).name if c.isalnum() or c in "._-")
        if not safe_name:
            raise HTTPException(status_code=400, detail="Invalid filename")

        target = (uploads_dir / f"{profile['employee_id']}_{safe_name}").resolve()
        # Defense in depth: make sure target is inside uploads_dir
        if uploads_dir not in target.parents and target != uploads_dir:
            raise HTTPException(status_code=400, detail="Invalid upload path")

        # Stream with size cap
        written = 0
        with target.open("wb") as out:
            while True:
                chunk = await f.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {settings.MAX_UPLOAD_MB} MB: {safe_name}",
                    )
                out.write(chunk)

        saved.append(str(target))

    await _invoke_graph(profile, "onboarding", "documents", {"attachments": saved})
    return {"status": "success", "saved": len(saved)}


class AssetPayload(BaseModel):
    laptop_type: str
    accessories: List[str] = []


@app.post("/onboarding/assets")
async def onboarding_assets(payload: AssetPayload, profile: Dict[str, Any] = Depends(auth_required)):
    await _invoke_graph(profile, "onboarding", "assets",
                        {"selection": {"laptop_type": payload.laptop_type, "accessories": payload.accessories}})
    return {"status": "success"}


# --- Offboarding endpoints --------------------------------------------------

class SeparationPayload(BaseModel):
    reason: str
    early_release: bool = False


@app.post("/offboarding/initiate")
async def offboarding_initiate(payload: SeparationPayload, profile: Dict[str, Any] = Depends(auth_required)):
    await _invoke_graph(profile, "offboarding", "separation",
                        {"reason": payload.reason, "early_release": payload.early_release})
    return {"status": "success"}


@app.post("/offboarding/approval")
async def offboarding_approval(profile: Dict[str, Any] = Depends(auth_required)):
    await _invoke_graph(profile, "offboarding", "approval", {})
    return {"status": "success"}


class ExitPayload(BaseModel):
    last_day: str


@app.post("/offboarding/exit")
async def offboarding_exit(payload: ExitPayload, profile: Dict[str, Any] = Depends(auth_required)):
    await _invoke_graph(profile, "offboarding", "exit", {"last_day": payload.last_day})
    return {"status": "success"}


# --- HR endpoints -----------------------------------------------------------

def _require_hr(profile: Dict[str, Any]) -> None:
    if (profile.get("role") or "").lower() not in ("hr", "admin"):
        raise HTTPException(status_code=403, detail="HR/admin only")


@app.get("/tickets")
async def get_tickets(profile: Dict[str, Any] = Depends(auth_required)):
    _require_hr(profile)
    return {"tickets": await list_tickets()}


@app.get("/employees")
async def get_employees(profile: Dict[str, Any] = Depends(auth_required)):
    _require_hr(profile)
    return {"employees": await list_employees()}


class TicketUpdate(BaseModel):
    ticket_id: str
    status: str
    assigned_to: str = ""
    comments: str = ""
    email: str = ""


@app.post("/tickets/update")
async def post_ticket_update(
    payload: TicketUpdate,
    background_tasks: BackgroundTasks,
    profile: Dict[str, Any] = Depends(auth_required),
):
    _require_hr(profile)
    t = await update_ticket(
        payload.ticket_id,
        status=payload.status,
        assigned_to=payload.assigned_to,
        comments=payload.comments,
    )
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if payload.email:
        # Preserve current rid for the background task
        rid = request_id_ctx.get()

        async def send_notification():
            request_id_ctx.set(rid)
            try:
                log.info("email_draft_start", extra={"ticket_id": t.get("ticket_id"), "to": payload.email})
                draft = await draft_notification_email(t)
                result = await mcp.send_email(to=payload.email, subject=draft["subject"], body=draft["body"])
                if isinstance(result, str) and result.startswith("ToolExecutionError"):
                    log.error("email_send_failed", extra={"error": result})
                else:
                    log.info("email_sent", extra={"result": str(result)[:200]})
            except Exception:
                log.exception("email_task_exception")

        background_tasks.add_task(send_notification)

    return {"ticket": t}


# --- Chat -------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatPayload(BaseModel):
    message: str
    flow: str
    current_step: str
    history: List[ChatMessage] = []


@app.post("/chat")
async def chat_endpoint(payload: ChatPayload, profile: Dict[str, Any] = Depends(auth_required)):
    from .agents import hr_assistant_chat  # local import to keep cold-start light
    emp_context = {
        "id": profile["employee_id"],
        "name": profile["name"],
        "department": profile["department"],
        "role": profile["role"],
    }
    history_dicts = [{"role": m.role, "content": m.content} for m in payload.history]
    reply = await hr_assistant_chat({
        "employee": emp_context,
        "flow": payload.flow,
        "current_step": payload.current_step,
        "message": payload.message,
        "history": history_dicts,
    })
    return {"reply": reply}


# --- Secure file download ---------------------------------------------------

@app.get("/files/get")
async def get_file(path: str, profile: Dict[str, Any] = Depends(auth_required)):
    """
    Serve a file that was previously saved by an upload, only if the
    resolved path lives under one of the configured allowed dirs.
    """
    target = Path(path).resolve()

    allowed_roots = [Path(d.strip()).resolve() for d in settings.FS_ALLOWED_DIRS.split(",") if d.strip()]
    if not any(target == root or root in target.parents for root in allowed_roots):
        log.warning("file_get_out_of_bounds", extra={"path": path})
        raise HTTPException(status_code=403, detail="Path not allowed")

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    return FileResponse(str(target), filename=target.name)


# --- Startup banner ---------------------------------------------------------

@app.on_event("startup")
async def _startup_banner():
    log.info(
        "startup",
        extra={
            "env": settings.APP_ENV,
            "cors_origins": settings.cors_origins_list,
            "log_json": settings.LOG_JSON,
            "jwt_hours": settings.JWT_EXPIRES_HOURS,
        },
    )
