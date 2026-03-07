
import os
from typing import Dict, Any
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from .tickets import create_ticket, update_ticket, list_tickets_by_employee
from .mcp_client import AsyncMCPToolClient
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

LLM_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2')

llm = ChatOllama(model=LLM_MODEL, temperature=0.1, format="json")
mcp = AsyncMCPToolClient()

class AgentDecision(BaseModel):
    status: str = Field(description="Must be exactly 'approved' or 'rejected'")
    reason: str = Field(description="A concise explanation of the decision.")

class EmailDraft(BaseModel):
    subject: str = Field(description="A professional and concise subject line for the email.")
    body: str = Field(description="The full, formal email body addressed to the employee.")

parser = JsonOutputParser(pydantic_object=AgentDecision)

async def _upsert_ticket(employee_id: str, flow: str, step: str, ticket_data: dict) -> dict:
    """Idempotency Check: Prevents duplicate tickets for the same step."""
    existing_tickets = await list_tickets_by_employee(employee_id)
    step_ticket = next((t for t in existing_tickets if t.get('flow') == flow and t.get('step') == step), None)
    
    if step_ticket:
        return await update_ticket(step_ticket['ticket_id'], **ticket_data)
    else:
        return await create_ticket(employee_id=employee_id, flow=flow, step=step, **ticket_data)

async def _summarize_issue(prompt: str) -> str:
    text_llm = ChatOllama(model=LLM_MODEL, temperature=0.1)
    resp = await text_llm.ainvoke([("system", "Summarize the employee's concern in one sentence."), ("human", prompt)])
    return resp.content


async def offer_resolution_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    accepted, reason, employee = payload.get('accepted'), payload.get('reason', ''), payload.get('employee', {})
    
    if accepted:
        desc = f"Offer accepted by {employee.get('name')}. Proceeding to documents."
        ticket = await _upsert_ticket(
            employee.get('id',''), 'onboarding', 'offer',
            {'type': 'onboarding', 'employee_name': employee.get('name',''), 'status': 'Done', 'priority': 'P3', 'description': desc, 'assigned_to': 'HR-Operations'}
        )
        return {'offer_status': 'accepted', 'ticket': ticket, 'log': 'Candidate accepted offer.'}
    else:
        summary = await _summarize_issue(reason or 'Candidate has concerns.')
        desc = f"Offer not accepted. Concern: {summary}"
        ticket = await _upsert_ticket(
            employee.get('id',''), 'onboarding', 'offer',
            {'type': 'onboarding', 'employee_name': employee.get('name',''), 'status': 'Open', 'priority': 'P1', 'description': desc, 'assigned_to': 'HR-Partner', 'comments': reason}
        )
        await mcp.create_ticket(ticket)
        return {'offer_status': 'negotiation', 'ticket': ticket, 'log': summary}

async def document_verification_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Intelligent agent that evaluates uploaded documents. 
    """
    employee, attachments = payload.get('employee', {}), payload.get('attachments', [])
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an HR Compliance Officer. If the candidate uploaded >= 1 file, approve them. Otherwise, reject them. \n{format_instructions}"),
        ("human", "Candidate {name} uploaded {count} files.")
    ])
    
    try:
        decision_data = await (prompt | llm | parser).ainvoke({
            "name": employee.get("name"), 
            "count": len(attachments), 
            "format_instructions": parser.get_format_instructions()
        })
        status_val = decision_data.get("status", "rejected").lower()
        reason_val = decision_data.get("reason", "Missing data.")
    except Exception as e:
        status_val, reason_val = "rejected", f"AI Parsing Error: {str(e)}"

  
    if status_val == 'approved':
        
        t_status = 'Pending' 
        desc = f"Documents uploaded for {employee.get('name')}. AI preliminary check passed. Waiting for final Human HR approval."
    else:
        
        t_status = 'Rejected' 
        desc = f"Verification failed. Reason: {reason_val}"
    
    ticket = await _upsert_ticket(
        employee.get('id',''), 'onboarding', 'documents',
        {
            'type': 'onboarding', 
            'employee_name': employee.get('name',''), 
            'status': t_status, 
            'description': desc, 
            'attachments': ';'.join(attachments)
        }
    )
    
    
    await mcp.create_ticket(ticket)
    
    return {'doc_status': status_val, 'ticket': ticket, 'log': reason_val}

async def asset_and_id_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    employee, selection = payload.get('employee', {}), payload.get('selection', {})
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an IT Provisioning Agent. Evaluate if the hardware matches the department. engineering employee can have higherend \n{format_instructions}"),
        ("human", "Employee {name} in {department} requested: Laptop: {laptop}, Accessories: {accessories}")
    ])
    try:
        decision_data = await (prompt | llm | parser).ainvoke({"name": employee.get("name"), "department": employee.get("department", "General"), "laptop": selection.get("laptop_type"), "accessories": ", ".join(selection.get("accessories", [])), "format_instructions": parser.get_format_instructions()})
        status_val, reason_val = decision_data.get("status", "rejected").lower(), decision_data.get("reason", "Missing data.")
    except Exception as e:
        status_val, reason_val = "rejected", f"AI Parsing Error: {str(e)}"
    
    t_status, desc = ('Open', f"Asset evaluation: {reason_val}") if status_val == 'approved' else ('Blocked', f"Request Blocked: {reason_val}")
    ticket = await _upsert_ticket(
        employee.get('id',''), 'onboarding', 'assets',
        {'type': 'onboarding', 'employee_name': employee.get('name',''), 'status': t_status, 'priority': 'P2', 'description': desc, 'assigned_to': 'IT-Assets'}
    )
    await mcp.create_ticket(ticket)
    return {'asset_status': status_val, 'ticket': ticket, 'log': reason_val}


async def separation_initiation_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    employee, reason, early = payload.get('employee', {}), payload.get('reason', ''), payload.get('early_release', False)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an HR Risk Assessor. If reason implies toxicity/legal risk, mark 'rejected' (needs urgent HR review). If standard resignation, mark 'approved'. \n{format_instructions}"),
        ("human", "Reason: '{reason}'. Early release: {early}")
    ])
    try:
        decision_data = await (prompt | llm | parser).ainvoke({"reason": reason, "early": str(early), "format_instructions": parser.get_format_instructions()})
        status_val, reason_val = decision_data.get("status", "rejected").lower(), decision_data.get("reason", "Missing data.")
    except Exception as e:
        status_val, reason_val = "rejected", f"Error: {str(e)}"

    ticket = await _upsert_ticket(
        employee.get('id',''), 'offboarding', 'initiation',
        {'type': 'offboarding', 'employee_name': employee.get('name',''), 'status': 'Open', 'priority': 'P1' if status_val == 'rejected' else 'P2', 'description': f"AI Risk Assessment: {reason_val}", 'assigned_to': 'HR-Partner', 'approvals': 'Manager,HR'}
    )
    await mcp.create_ticket(ticket)
    return {'sep_status': 'pending', 'ticket': ticket, 'log': reason_val}

async def approval_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    employee = payload.get('employee', {})
    ticket = await _upsert_ticket(
        employee.get('id',''), 'offboarding', 'approval',
        {'type': 'offboarding', 'employee_name': employee.get('name',''), 'status': 'Pending', 'priority': 'P2', 'description': "Manager/HR approval required.", 'assigned_to': 'Manager/HR', 'approvals': 'Manager:Pending;HR:Pending'}
    )
    await mcp.create_ticket(ticket)
    return {'approval_status': 'pending', 'ticket': ticket, 'log': 'Waiting for Human HR.'}

async def exit_formalities_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    employee, last_day = payload.get('employee', {}), payload.get('last_day', 'TBD')
    ticket = await _upsert_ticket(
        employee.get('id',''), 'offboarding', 'exit',
        {'type': 'offboarding', 'employee_name': employee.get('name',''), 'status': 'Open', 'priority': 'P2', 'description': f"Exit formalities by {last_day}.", 'assigned_to': 'IT/Finance', 'sla_due': last_day}
    )
    await mcp.create_ticket(ticket)
    return {'exit_status': 'completed', 'ticket': ticket, 'log': 'Exit initiated.'}



async def hr_assistant_chat(payload: Dict[str, Any]) -> str:
    """
    A contextual, conversational agent that helps candidates navigate their current UI step.
    Does not use JSON formatting; outputs natural language.
    """
    employee = payload.get('employee', {})
    flow = payload.get('flow', 'general')
    step = payload.get('current_step', 'unknown')
    message = payload.get('message', '')
    history = payload.get('history', [])
    
    
    chat_llm = ChatOllama(model=LLM_MODEL, temperature=0.3)
    
    
    sys_prompt = (
        f"You are a warm, professional HR Support Assistant for the {employee.get('department', 'company')} department. "
        f"You are chatting with {employee.get('name')}. "
        f"They are currently in the '{flow}' process, specifically looking at the '{step}' step. "
        "Your goal is to answer their questions, clarify the process, and guide them on what to do next. "
        "Keep your answers concise, empathetic, and under 3 paragraphs. Do not invent company policies."
    )
    
    messages = [SystemMessage(content=sys_prompt)]
    
    
    for msg in history:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg.get("content")))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg.get("content")))
            
    
    messages.append(HumanMessage(content=message))
    
    
    try:
        resp = await chat_llm.ainvoke(messages)
        return resp.content
    except Exception as e:
        return f"I apologize, my systems are currently experiencing a slight delay. Error: {str(e)}"
    


async def draft_notification_email(ticket: Dict[str, Any]) -> Dict[str, str]:
    """Uses the LLM to dynamically generate a contextual HR email."""
    
    
    email_llm = ChatOllama(model=os.getenv('OLLAMA_MODEL', 'llama3.2'), temperature=0.2)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert HR Communications Agent. Draft a polite, professional, and formal notification email to an employee regarding an update to their HR ticket. 
        
        RULES:
        1. If the status is 'Approved' or 'Done', be welcoming and positive.
        2. If the status is 'Rejected' or 'Blocked', be empathetic but clear about what they need to fix based on the HR comments.
        3. Use the provided ticket details. Do NOT invent policies or links.
        4. Sign off as 'Human Resources Operations'."""),
        ("human", "Ticket Details:\nEmployee Name: {employee_name}\nProcess: {flow}\nStep: {step}\nNew Status: {status}\nHR Comments: {comments}")
    ])
    
    structured_llm = email_llm.with_structured_output(EmailDraft)
    
    try:
        
        result = await (prompt | structured_llm).ainvoke({
            "employee_name": ticket.get('employee_name', 'Employee'),
            "flow": ticket.get('flow', 'HR process'),
            "step": ticket.get('step', 'Step'),
            "status": ticket.get('status', 'Updated'),
            "comments": ticket.get('comments', 'None provided.')
        })
        return {"subject": result.subject, "body": result.body}
        
    except Exception as e:
        
        return {
            "subject": f"HR Update: Next Steps for your {ticket.get('flow', 'HR').capitalize()} Process",
            "body": f"Dear {ticket.get('employee_name', 'Employee')},\n\nYour ticket status is now: {ticket.get('status', 'Updated')}.\nHR Comments: {ticket.get('comments', 'None')}\n\nBest,\nHuman Resources Operations"
        }
