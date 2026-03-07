
import os, io, csv, uuid, time, asyncio, shutil
from fastapi import FastAPI, UploadFile, File, Header, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from .tickets import create_ticket, update_ticket, list_tickets, list_tickets_by_employee
from .mcp_client import AsyncMCPToolClient
from .graph import app as workflow_app
from fastapi import BackgroundTasks
from .agents import hr_assistant_chat, draft_notification_email
from dotenv import load_dotenv

load_dotenv()

import json
import base64
from dataclasses import dataclass


app = FastAPI(title='Intelligent Onboarding/Offboarding MAS')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
mcp = AsyncMCPToolClient()

SESSIONS: Dict[str, Dict[str, Any]] = {}
USERS_PATH = os.path.join('data','users.csv')

async def _auth_required(authorization: Optional[str]) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    sess = SESSIONS.get(token)
    if not sess or sess.get("expires", 0) < time.time(): raise HTTPException(status_code=401, detail="Invalid/expired token")
    return sess

class LoginPayload(BaseModel): email: str; password: str

@app.post("/auth/login")
async def login(payload: LoginPayload):
    txt = await mcp.read_text(USERS_PATH)
    users = list(csv.DictReader(io.StringIO(txt))) if txt and not txt.startswith("ToolExecutionError") else []
    for u in users:
        if u.get("email", "").lower() == payload.email.lower() and u.get("password", "") == payload.password:
            token = str(uuid.uuid4())
            SESSIONS[token] = {"email": payload.email, "employee_id": u.get("employee_id", ""), "name": u.get("name", ""), "department": u.get("department", ""), "manager": u.get("manager", ""), "role": u.get("role", "employee"), "expires": time.time() + 8*3600}
            return {"token": token, "profile": SESSIONS[token]}
    raise HTTPException(status_code=401, detail="Invalid credentials")


async def invoke_graph(sess: dict, kind: str, step: str, payload: dict) -> dict:
    emp = {"id": sess["employee_id"], "name": sess["name"], "department": sess["department"], "manager": sess["manager"]}
    config = {"configurable": {"thread_id": sess["employee_id"]}}
    return await workflow_app.ainvoke({"kind": kind, "step": step, "employee": emp, "payload": payload}, config)


@app.get('/progress/{flow}')
async def get_progress(flow: str, authorization: Optional[str] = Header(None)):
    sess = await _auth_required(authorization)
    tickets = await list_tickets_by_employee(sess["employee_id"])
    flow_tickets = {t.get("step"): t for t in tickets if t.get("flow") == flow}
    
    def _evaluate_step(step_name: str, prev_step_status: str):
        if prev_step_status not in ['completed', 'none_required']: return "locked", None
        ticket = flow_tickets.get(step_name)
        if not ticket: return "unlocked", None
        t_status = ticket.get("status", "").lower()
        if t_status in ['done', 'closed', 'approved']: return "completed", ticket
        elif t_status in ['rejected', 'blocked']: return "rejected", ticket
        else: return "pending_hr", ticket

    if flow == 'onboarding':
        s1_stat, s1_t = _evaluate_step("offer", "completed")
        s2_stat, s2_t = _evaluate_step("documents", s1_stat)
        s3_stat, s3_t = _evaluate_step("assets", s2_stat)
    else:
        s1_stat, s1_t = _evaluate_step("initiation", "completed")
        s2_stat, s2_t = _evaluate_step("approval", s1_stat)
        s3_stat, s3_t = _evaluate_step("exit", s2_stat)
        
    return {"step1": s1_stat, "step2": s2_stat, "step3": s3_stat, "tickets": {"step1": s1_t, "step2": s2_t, "step3": s3_t}}


class OfferPayload(BaseModel): accepted: bool; reason: str = ''
@app.post('/onboarding/offer')
async def onboarding_offer(payload: OfferPayload, authorization: Optional[str] = Header(None)):
    await invoke_graph(await _auth_required(authorization), "onboarding", "offer", {"accepted": payload.accepted, "reason": payload.reason})
    return {"status": "success"}

@app.post('/onboarding/documents')
async def onboarding_documents(authorization: Optional[str] = Header(None), files: List[UploadFile] = File([])):
    sess = await _auth_required(authorization)
    saved = []
    
    
    os.makedirs('uploads', exist_ok=True) 
    
    for f in files:
        
        safe_name = "".join(c for c in f.filename if c.isalnum() or c in "._-")
        path = f"uploads/{sess['employee_id']}_{safe_name}"
        
        
        with open(path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)
            
        saved.append(path)
        
    await invoke_graph(sess, "onboarding", "documents", {"attachments": saved})
    return {"status": "success"}

class AssetPayload(BaseModel): laptop_type: str; accessories: List[str] = []
@app.post('/onboarding/assets')
async def onboarding_assets(payload: AssetPayload, authorization: Optional[str] = Header(None)):
    await invoke_graph(await _auth_required(authorization), "onboarding", "assets", {"selection": {"laptop_type": payload.laptop_type, "accessories": payload.accessories}})
    return {"status": "success"}


class SeparationPayload(BaseModel): reason: str; early_release: bool = False
@app.post('/offboarding/initiate')
async def offboarding_initiate(payload: SeparationPayload, authorization: Optional[str] = Header(None)):
    await invoke_graph(await _auth_required(authorization), "offboarding", "separation", {"reason": payload.reason, "early_release": payload.early_release})
    return {"status": "success"}

@app.post('/offboarding/approval')
async def offboarding_approval(authorization: Optional[str] = Header(None)):
    await invoke_graph(await _auth_required(authorization), "offboarding", "approval", {})
    return {"status": "success"}

class ExitPayload(BaseModel): last_day: str
@app.post('/offboarding/exit')
async def offboarding_exit(payload: ExitPayload, authorization: Optional[str] = Header(None)):
    await invoke_graph(await _auth_required(authorization), "offboarding", "exit", {"last_day": payload.last_day})
    return {"status": "success"}


@app.get('/tickets')
async def get_tickets(authorization: Optional[str] = Header(None)):
    sess = await _auth_required(authorization)
    if sess.get("role") not in ("hr", "admin"): raise HTTPException(status_code=403, detail="HR only")
    return {'tickets': await list_tickets()}

class TicketUpdate(BaseModel): ticket_id: str; status: str; assigned_to: str = ''; comments: str = ''; email: str = ''
@app.post('/tickets/update')
async def post_ticket_update(payload: TicketUpdate, background_tasks: BackgroundTasks, authorization: Optional[str] = Header(None)):
    sess = await _auth_required(authorization)
    if sess.get("role") not in ("hr", "admin"): 
        raise HTTPException(status_code=403, detail="HR only")
        
    t = await update_ticket(payload.ticket_id, status=payload.status, assigned_to=payload.assigned_to, comments=payload.comments)
    
    if t:
        email = payload.email or (t.get('employee_name', 'employee').replace(" ", ".") + "@example.com")
        
        
        async def send_notification():
            print(f"--> Asking AI Agent to draft email for: {email}")
            
            
            draft = await draft_notification_email(t)
            
            print(f"--> Attempting to send formal email via MCP to: {email}")
            
            
            result = await mcp.send_email(
                to=email, 
                subject=draft['subject'], 
                body=draft['body']
            )
            print(f"--> MCP Email Result: {result}")
            
        
        background_tasks.add_task(send_notification)
        
    return {'ticket': t}


from .agents import hr_assistant_chat


class ChatMessage(BaseModel):
    role: str
    content: str

class ChatPayload(BaseModel):
    message: str
    flow: str
    current_step: str
    history: List[ChatMessage] = []

@app.post('/chat')
async def chat_endpoint(payload: ChatPayload, authorization: Optional[str] = Header(None)):
    """Context-aware conversational endpoint."""
    sess = await _auth_required(authorization)
    
    emp_context = {
        "id": sess["employee_id"],        
        "name": sess["name"], 
        "department": sess["department"], 
        "role": sess["role"]
    }
    
    
    history_dicts = [{"role": msg.role, "content": msg.content} for msg in payload.history]
    
    reply = await hr_assistant_chat({
        "employee": emp_context,
        "flow": payload.flow,
        "current_step": payload.current_step,
        "message": payload.message,
        "history": history_dicts
    })
    
    return {"reply": reply}


@app.get("/files/get")
async def get_file(path: str, authorization: Optional[str] = Header(None)):
    await _auth_required(authorization)
    
    
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"File not found on server: {path}")
        
    return FileResponse(path, filename=os.path.basename(path))