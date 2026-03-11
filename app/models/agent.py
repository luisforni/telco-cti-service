from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
import datetime


class AgentState(str, Enum):
    available = "available"
    busy = "busy"
    break_ = "break"
    away = "away"
    offline = "offline"


class Agent(BaseModel):
    id: str
    name: str
    extension: str
    state: AgentState = AgentState.offline
    skills: List[str] = Field(default_factory=list)
    queue_ids: List[str] = Field(default_factory=list)
    logged_in_at: Optional[datetime.datetime] = None
    last_state_change: Optional[datetime.datetime] = None


class AgentLogin(BaseModel):
    agent_id: str
    name: str
    extension: str
    skills: List[str] = Field(default_factory=list)
    queue_ids: List[str] = Field(default_factory=list)


class AgentStateChange(BaseModel):
    state: AgentState
    reason: Optional[str] = None
