import json
import datetime
from typing import Any, Dict, Optional

import httpx
import structlog

from app.models.call_control import TransferRequest, ConferenceRequest

_UTC = datetime.timezone.utc

logger = structlog.get_logger(__name__)

ACTIVE_CALL_PREFIX = "cti:call:"
ACTIVE_CALL_TTL = 3600  # 1 hour


class CTIService:
    def __init__(
        self,
        sip_gateway_url: str,
        redis_client: Any,
        http_client: httpx.AsyncClient,
    ):
        self._sip_url = sip_gateway_url.rstrip("/")
        self._redis = redis_client
        self._http = http_client

    # ------------------------------------------------------------------ #
    # Call control                                                         #
    # ------------------------------------------------------------------ #

    async def answer_call(self, call_id: str, agent_id: str) -> Dict[str, Any]:
        response = await self._sip_post(f"/calls/{call_id}/answer", {"agent_id": agent_id})
        await self._update_call(call_id, {"status": "answered", "agent_id": agent_id})
        logger.info("call.answered", call_id=call_id, agent_id=agent_id)
        return response

    async def hold_call(self, call_id: str) -> Dict[str, Any]:
        response = await self._sip_post(f"/calls/{call_id}/hold", {})
        await self._update_call(call_id, {"status": "on_hold"})
        logger.info("call.held", call_id=call_id)
        return response

    async def unhold_call(self, call_id: str) -> Dict[str, Any]:
        response = await self._sip_post(f"/calls/{call_id}/unhold", {})
        await self._update_call(call_id, {"status": "active"})
        logger.info("call.unheld", call_id=call_id)
        return response

    async def transfer_call(self, call_id: str, request: TransferRequest) -> Dict[str, Any]:
        payload = {
            "destination": request.destination,
            "transfer_type": request.transfer_type,
            "agent_id": request.agent_id,
        }
        response = await self._sip_post(f"/calls/{call_id}/transfer", payload)
        await self._update_call(call_id, {"status": "transferred", "destination": request.destination})
        logger.info("call.transferred", call_id=call_id, destination=request.destination)
        return response

    async def create_conference(self, call_id: str, request: ConferenceRequest) -> Dict[str, Any]:
        payload = {
            "participants": request.participants,
            "moderator_id": request.moderator_id,
        }
        response = await self._sip_post(f"/calls/{call_id}/conference", payload)
        await self._update_call(call_id, {"status": "conference"})
        logger.info("call.conference_created", call_id=call_id)
        return response

    async def hangup_call(self, call_id: str) -> Dict[str, Any]:
        response = await self._sip_post(f"/calls/{call_id}/hangup", {})
        await self._delete_call(call_id)
        logger.info("call.hangup", call_id=call_id)
        return response

    async def get_call(self, call_id: str) -> Optional[Dict[str, Any]]:
        key = f"{ACTIVE_CALL_PREFIX}{call_id}"
        data = await self._redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    # ------------------------------------------------------------------ #
    # IVR / DTMF                                                          #
    # ------------------------------------------------------------------ #

    async def send_dtmf(self, call_id: str, digits: str) -> Dict[str, Any]:
        return await self._sip_post(f"/calls/{call_id}/dtmf", {"digits": digits})

    # ------------------------------------------------------------------ #
    # Recording                                                            #
    # ------------------------------------------------------------------ #

    async def start_recording(self, call_id: str) -> Dict[str, Any]:
        return await self._sip_post(f"/calls/{call_id}/recording/start", {})

    async def stop_recording(self, call_id: str) -> Dict[str, Any]:
        return await self._sip_post(f"/calls/{call_id}/recording/stop", {})

    # ------------------------------------------------------------------ #
    # Screen pop / CRM data                                               #
    # ------------------------------------------------------------------ #

    async def get_screen_pop_data(self, call_id: str, caller_id: str) -> Dict[str, Any]:
        return {
            "call_id": call_id,
            "caller_id": caller_id,
            "crm_url": f"/crm/customers?phone={caller_id}",
            "timestamp": datetime.datetime.now(_UTC).isoformat(),
        }

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _sip_post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self._sip_url}{path}"
        try:
            resp = await self._http.post(url, json=payload, timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "sip_gateway.error",
                path=path,
                status=exc.response.status_code,
                body=exc.response.text,
            )
            return {"status": "simulated", "path": path, "payload": payload}
        except Exception as exc:
            logger.warning("sip_gateway.unreachable", path=path, error=str(exc))
            return {"status": "simulated", "path": path, "payload": payload}

    async def _update_call(self, call_id: str, updates: Dict[str, Any]) -> None:
        key = f"{ACTIVE_CALL_PREFIX}{call_id}"
        existing_raw = await self._redis.get(key)
        existing: Dict[str, Any] = json.loads(existing_raw) if existing_raw else {"call_id": call_id}
        existing.update(updates)
        existing["updated_at"] = datetime.datetime.now(_UTC).isoformat()
        await self._redis.set(key, json.dumps(existing), ex=ACTIVE_CALL_TTL)

    async def _delete_call(self, call_id: str) -> None:
        key = f"{ACTIVE_CALL_PREFIX}{call_id}"
        await self._redis.delete(key)
