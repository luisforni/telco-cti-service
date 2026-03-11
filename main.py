import os
import asyncio
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Gauge, make_asgi_app

from app.api.routes import router
from app.services.agent_service import AgentService
from app.services.cti_service import CTIService
from app.services.kafka_service import KafkaService

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger(__name__)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# ------------------------------------------------------------------ #
# Prometheus metrics                                                   #
# ------------------------------------------------------------------ #

AGENTS_BY_STATE = Gauge(
    "cti_agents_by_state",
    "Number of agents per state",
    ["state"],
)
CALL_OPERATIONS = Counter(
    "cti_call_operations_total",
    "Total call control operations",
    ["operation"],
)
QUEUE_SIZE = Gauge("cti_queue_size", "Active calls in queue", ["queue_id"])


# ------------------------------------------------------------------ #
# Lifespan                                                             #
# ------------------------------------------------------------------ #


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    redis_url = _env("REDIS_URL", "redis://redis:6379/0")
    redis_client = aioredis.from_url(redis_url, decode_responses=True)

    http_client = httpx.AsyncClient()

    kafka_brokers = _env("KAFKA_BROKERS", "kafka:9092")
    kafka_service = KafkaService(brokers=kafka_brokers)
    try:
        await kafka_service.start()
    except Exception as exc:
        logger.warning("kafka.start_failed", error=str(exc))

    sip_gateway_url = _env("SIP_GATEWAY_URL", "http://sip-gateway:8002")
    agent_service = AgentService(redis_client=redis_client)
    cti_service = CTIService(
        sip_gateway_url=sip_gateway_url,
        redis_client=redis_client,
        http_client=http_client,
    )

    app.state.redis = redis_client
    app.state.agent_service = agent_service
    app.state.cti_service = cti_service
    app.state.kafka_service = kafka_service

    logger.info(
        "cti_service.started",
        redis=redis_url,
        kafka=kafka_brokers,
        sip_gateway=sip_gateway_url,
    )

    yield

    # Shutdown
    await kafka_service.stop()
    await http_client.aclose()
    await redis_client.aclose()
    logger.info("cti_service.stopped")


# ------------------------------------------------------------------ #
# Application factory                                                  #
# ------------------------------------------------------------------ #

app = FastAPI(
    title="Telco CTI Service",
    version="1.0.0",
    description="Computer Telephony Integration service for the telco platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/healthz", tags=["Health"])
async def healthz():
    return {"status": "ok", "service": "telco-cti-service"}
