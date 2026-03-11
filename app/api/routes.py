from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Optional

import structlog

from app.models.agent import Agent, AgentLogin, AgentState, AgentStateChange
from app.models.call_control import TransferRequest, ConferenceRequest

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/cti", tags=["CTI"])


def _agent_svc(request: Request):
    return request.app.state.agent_service


def _cti_svc(request: Request):
    return request.app.state.cti_service


def _kafka_svc(request: Request):
    return request.app.state.kafka_service


# ------------------------------------------------------------------ #
# Agent Management                                                     #
# ------------------------------------------------------------------ #


@router.post("/agents/login", response_model=Agent, status_code=201)
async def agent_login(body: AgentLogin, agent_svc=Depends(_agent_svc), kafka_svc=Depends(_kafka_svc)):
    agent = await agent_svc.login(body)
    await kafka_svc.publish_agent_state_event(
        "agent_login",
        {"agent_id": agent.id, "extension": agent.extension, "state": agent.state},
    )
    return agent


@router.post("/agents/{agent_id}/logout", status_code=200)
async def agent_logout(agent_id: str, agent_svc=Depends(_agent_svc), kafka_svc=Depends(_kafka_svc)):
    await agent_svc.logout(agent_id)
    await kafka_svc.publish_agent_state_event("agent_logout", {"agent_id": agent_id})
    return {"status": "logged_out", "agent_id": agent_id}


@router.put("/agents/{agent_id}/state", response_model=Agent)
async def change_agent_state(
    agent_id: str,
    body: AgentStateChange,
    agent_svc=Depends(_agent_svc),
    kafka_svc=Depends(_kafka_svc),
):
    agent = await agent_svc.change_state(agent_id, body)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    await kafka_svc.publish_agent_state_event(
        "state_changed",
        {"agent_id": agent_id, "state": agent.state, "reason": body.reason},
    )
    return agent


@router.get("/agents/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str, agent_svc=Depends(_agent_svc)):
    agent = await agent_svc.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent


@router.get("/agents/{agent_id}/status")
async def get_agent_status(agent_id: str, agent_svc=Depends(_agent_svc)):
    agent = await agent_svc.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return {
        "agent_id": agent_id,
        "state": agent.state,
        "available": agent.state == AgentState.available,
        "last_state_change": agent.last_state_change,
    }


@router.get("/agents", response_model=List[Agent])
async def list_agents(agent_svc=Depends(_agent_svc)):
    return await agent_svc.list_agents()


# ------------------------------------------------------------------ #
# Call Control                                                         #
# ------------------------------------------------------------------ #


@router.post("/calls/{call_id}/answer")
async def answer_call(
    call_id: str,
    agent_id: Optional[str] = None,
    cti_svc=Depends(_cti_svc),
    kafka_svc=Depends(_kafka_svc),
):
    result = await cti_svc.answer_call(call_id, agent_id or "unknown")
    await kafka_svc.publish_cti_event(
        "call_answered", {"call_id": call_id, "agent_id": agent_id}
    )
    return result


@router.post("/calls/{call_id}/hold")
async def hold_call(call_id: str, cti_svc=Depends(_cti_svc), kafka_svc=Depends(_kafka_svc)):
    result = await cti_svc.hold_call(call_id)
    await kafka_svc.publish_cti_event("call_held", {"call_id": call_id})
    return result


@router.post("/calls/{call_id}/unhold")
async def unhold_call(call_id: str, cti_svc=Depends(_cti_svc), kafka_svc=Depends(_kafka_svc)):
    result = await cti_svc.unhold_call(call_id)
    await kafka_svc.publish_cti_event("call_unheld", {"call_id": call_id})
    return result


@router.post("/calls/{call_id}/transfer")
async def transfer_call(
    call_id: str,
    body: TransferRequest,
    cti_svc=Depends(_cti_svc),
    kafka_svc=Depends(_kafka_svc),
):
    result = await cti_svc.transfer_call(call_id, body)
    await kafka_svc.publish_cti_event(
        "call_transferred",
        {"call_id": call_id, "destination": body.destination, "type": body.transfer_type},
    )
    return result


@router.post("/calls/{call_id}/conference")
async def create_conference(
    call_id: str,
    body: ConferenceRequest,
    cti_svc=Depends(_cti_svc),
    kafka_svc=Depends(_kafka_svc),
):
    result = await cti_svc.create_conference(call_id, body)
    await kafka_svc.publish_cti_event(
        "conference_created",
        {"call_id": call_id, "participants": body.participants},
    )
    return result


@router.post("/calls/{call_id}/hangup")
async def hangup_call(call_id: str, cti_svc=Depends(_cti_svc), kafka_svc=Depends(_kafka_svc)):
    result = await cti_svc.hangup_call(call_id)
    await kafka_svc.publish_cti_event("call_hangup", {"call_id": call_id})
    return result


@router.get("/calls/{call_id}")
async def get_call(call_id: str, cti_svc=Depends(_cti_svc)):
    call = await cti_svc.get_call(call_id)
    if call is None:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    return call


# ------------------------------------------------------------------ #
# Queue Management                                                     #
# ------------------------------------------------------------------ #


@router.get("/queues")
async def list_queues(agent_svc=Depends(_agent_svc)):
    agents = await agent_svc.list_agents()
    queue_ids: set = set()
    for agent in agents:
        queue_ids.update(agent.queue_ids)
    return [{"queue_id": qid} for qid in sorted(queue_ids)]


@router.get("/queues/{queue_id}")
async def get_queue(queue_id: str, agent_svc=Depends(_agent_svc)):
    agents = await agent_svc.list_agents()
    queue_agents = [a for a in agents if queue_id in a.queue_ids]
    return {
        "queue_id": queue_id,
        "total_agents": len(queue_agents),
        "available_agents": sum(1 for a in queue_agents if a.state == AgentState.available),
        "busy_agents": sum(1 for a in queue_agents if a.state == AgentState.busy),
    }


@router.get("/queues/{queue_id}/calls")
async def get_queue_calls(queue_id: str):
    return {"queue_id": queue_id, "calls": []}
