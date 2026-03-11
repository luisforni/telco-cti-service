import json
import datetime
from typing import Optional, List, Dict, Any

import redis.asyncio as aioredis
import structlog

from app.models.agent import Agent, AgentLogin, AgentState, AgentStateChange

_UTC = datetime.timezone.utc

logger = structlog.get_logger(__name__)

AGENT_KEY_PREFIX = "cti:agent:"
AGENT_SET_KEY = "cti:agents"
SESSION_TTL = 86400  # 24 hours


class AgentService:
    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client

    async def login(self, login: AgentLogin) -> Agent:
        now = datetime.datetime.now(_UTC)
        agent = Agent(
            id=login.agent_id,
            name=login.name,
            extension=login.extension,
            state=AgentState.available,
            skills=login.skills,
            queue_ids=login.queue_ids,
            logged_in_at=now,
            last_state_change=now,
        )
        await self._save(agent)
        logger.info("agent.login", agent_id=agent.id, extension=agent.extension)
        return agent

    async def logout(self, agent_id: str) -> bool:
        key = f"{AGENT_KEY_PREFIX}{agent_id}"
        pipe = self._redis.pipeline()
        pipe.delete(key)
        pipe.srem(AGENT_SET_KEY, agent_id)
        await pipe.execute()
        logger.info("agent.logout", agent_id=agent_id)
        return True

    async def change_state(self, agent_id: str, change: AgentStateChange) -> Optional[Agent]:
        agent = await self.get(agent_id)
        if agent is None:
            return None
        agent.state = change.state
        agent.last_state_change = datetime.datetime.now(_UTC)
        await self._save(agent)
        logger.info("agent.state_changed", agent_id=agent_id, state=change.state)
        return agent

    async def get(self, agent_id: str) -> Optional[Agent]:
        key = f"{AGENT_KEY_PREFIX}{agent_id}"
        data = await self._redis.get(key)
        if data is None:
            return None
        return Agent.model_validate(json.loads(data))

    async def list_agents(self) -> List[Agent]:
        agent_ids = await self._redis.smembers(AGENT_SET_KEY)
        agents = []
        for aid in agent_ids:
            agent = await self.get(aid.decode() if isinstance(aid, bytes) else aid)
            if agent is not None:
                agents.append(agent)
        return agents

    async def is_available(self, agent_id: str) -> bool:
        agent = await self.get(agent_id)
        return agent is not None and agent.state == AgentState.available

    async def get_stats(self) -> Dict[str, Any]:
        agents = await self.list_agents()
        stats: Dict[str, int] = {s.value: 0 for s in AgentState}
        for agent in agents:
            stats[agent.state.value] = stats.get(agent.state.value, 0) + 1
        return {"total": len(agents), "by_state": stats}

    async def _save(self, agent: Agent) -> None:
        key = f"{AGENT_KEY_PREFIX}{agent.id}"
        pipe = self._redis.pipeline()
        pipe.set(key, agent.model_dump_json(), ex=SESSION_TTL)
        pipe.sadd(AGENT_SET_KEY, agent.id)
        await pipe.execute()
