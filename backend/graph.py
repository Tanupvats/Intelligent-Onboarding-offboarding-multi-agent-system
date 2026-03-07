
import operator
from typing import TypedDict, Literal, Dict, Any, Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver


from .agents import (
    offer_resolution_agent, document_verification_agent, asset_and_id_agent,
    separation_initiation_agent, approval_agent, exit_formalities_agent
)


class FlowState(TypedDict):
    kind: Literal['onboarding', 'offboarding']
    step: str
    employee: Dict[str, Any]
    payload: Dict[str, Any]
    
    
    agent_logs: Annotated[list[str], operator.add]
    
    
    offer_status: str
    doc_status: str
    asset_status: str
    sep_status: str
    approval_status: str
    exit_status: str
    
    result: Dict[str, Any]


async def offer_node(state: FlowState) -> FlowState:
    res = await offer_resolution_agent({'employee': state['employee'], **state.get('payload', {})})
    return {
        'result': res, 
        'step': 'offer_evaluated',
        'offer_status': res.get('offer_status', 'pending'),
        'agent_logs': [f"Offer Node: {res.get('log', '')}"]
    }

async def documents_node(state: FlowState) -> FlowState:
    res = await document_verification_agent({'employee': state['employee'], **state.get('payload', {})})
    return {
        'result': res, 
        'step': 'documents_evaluated',
        'doc_status': res.get('doc_status', 'pending'),
        'agent_logs': [f"Doc Node: {res.get('log', '')}"]
    }

async def assets_node(state: FlowState) -> FlowState:
    res = await asset_and_id_agent({'employee': state['employee'], **state.get('payload', {})})
    return {
        'result': res, 
        'step': 'assets_evaluated',
        'asset_status': res.get('asset_status', 'pending'),
        'agent_logs': [f"Asset Node: {res.get('log', '')}"]
    }


async def separation_node(state: FlowState) -> FlowState:
    res = await separation_initiation_agent({'employee': state['employee'], **state.get('payload', {})})
    return {
        'result': res, 
        'step': 'separation_evaluated',
        'sep_status': res.get('sep_status', 'pending'),
        'agent_logs': [f"Sep Node: {res.get('log', '')}"]
    }

async def approval_node(state: FlowState) -> FlowState:
    res = await approval_agent({'employee': state['employee'], **state.get('payload', {})})
    return {
        'result': res, 
        'step': 'approval_evaluated',
        'approval_status': res.get('approval_status', 'pending'),
        'agent_logs': [f"Approval Node: {res.get('log', '')}"]
    }

async def exit_node(state: FlowState) -> FlowState:
    res = await exit_formalities_agent({'employee': state['employee'], **state.get('payload', {})})
    return {
        'result': res, 
        'step': 'completed',
        'exit_status': res.get('exit_status', 'completed'),
        'agent_logs': [f"Exit Node: {res.get('log', '')}"]
    }


def initial_router(state: FlowState) -> str:
    """Directs traffic at the start of the graph based on the workflow kind and step requested by FastAPI."""
    if state['kind'] == 'onboarding':
        if state.get('step') == 'documents':
            return 'documents'
        if state.get('step') == 'assets':
            return 'assets'
        return 'offer'
    else:
        if state.get('step') == 'approval':
            return 'approval'
        if state.get('step') == 'exit':
            return 'exit'
        return 'separation'


workflow = StateGraph(FlowState)


workflow.add_node('offer', offer_node)
workflow.add_node('documents', documents_node)
workflow.add_node('assets', assets_node)
workflow.add_node('separation', separation_node)
workflow.add_node('approval', approval_node)
workflow.add_node('exit', exit_node)


workflow.add_conditional_edges(START, initial_router)


workflow.add_edge('offer', END)
workflow.add_edge('documents', END)
workflow.add_edge('assets', END)

workflow.add_edge('separation', END)
workflow.add_edge('approval', END)
workflow.add_edge('exit', END)


memory = MemorySaver()
app = workflow.compile(checkpointer=memory)