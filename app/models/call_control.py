from enum import Enum
from typing import Optional, List
from pydantic import BaseModel


class CallAction(str, Enum):
    answer = "answer"
    hold = "hold"
    unhold = "unhold"
    transfer = "transfer"
    conference = "conference"
    hangup = "hangup"


class CallControl(BaseModel):
    call_id: str
    action: CallAction
    agent_id: Optional[str] = None
    destination: Optional[str] = None


class TransferRequest(BaseModel):
    destination: str
    transfer_type: str = "blind"
    agent_id: Optional[str] = None


class ConferenceRequest(BaseModel):
    participants: List[str]
    moderator_id: Optional[str] = None
