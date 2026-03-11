import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError

logger = structlog.get_logger(__name__)

PRODUCE_TOPICS = ["cti-events", "agent-state-events"]
CONSUME_TOPICS = ["call-events", "orchestrator-events"]


class KafkaService:
    def __init__(self, brokers: str):
        self._brokers = brokers
        self._producer: Optional[AIOKafkaProducer] = None
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._consumer_task: Optional[asyncio.Task] = None
        self._handlers: Dict[str, List[Callable]] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        await self._start_producer()
        await self._start_consumer()
        logger.info("kafka.started", brokers=self._brokers)

    async def stop(self) -> None:
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

        if self._consumer:
            await self._consumer.stop()

        if self._producer:
            await self._producer.stop()

        logger.info("kafka.stopped")

    # ------------------------------------------------------------------ #
    # Producer                                                             #
    # ------------------------------------------------------------------ #

    async def publish(self, topic: str, event_type: str, payload: Dict[str, Any]) -> None:
        if self._producer is None:
            logger.warning("kafka.producer_not_ready", topic=topic)
            return
        message = {"type": event_type, "payload": payload}
        try:
            await self._producer.send_and_wait(
                topic,
                value=json.dumps(message).encode(),
                key=event_type.encode(),
            )
            logger.debug("kafka.published", topic=topic, event_type=event_type)
        except Exception as exc:
            logger.error("kafka.publish_error", topic=topic, event_type=event_type, error=str(exc))

    async def publish_cti_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        await self.publish("cti-events", event_type, payload)

    async def publish_agent_state_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        await self.publish("agent-state-events", event_type, payload)

    # ------------------------------------------------------------------ #
    # Consumer                                                             #
    # ------------------------------------------------------------------ #

    def register_handler(self, event_type: str, handler: Callable) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def _consume_loop(self) -> None:
        if self._consumer is None:
            return
        async for msg in self._consumer:
            try:
                event = json.loads(msg.value)
                event_type = event.get("type", "unknown")
                handlers = self._handlers.get(event_type, [])
                for handler in handlers:
                    try:
                        await handler(event.get("payload", {}))
                    except Exception as exc:
                        logger.error(
                            "kafka.handler_error",
                            event_type=event_type,
                            error=str(exc),
                        )
            except Exception as exc:
                logger.error("kafka.consume_error", error=str(exc))

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _start_producer(self) -> None:
        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._brokers,
                value_serializer=None,
                compression_type="gzip",
                enable_idempotence=True,
            )
            await self._producer.start()
        except KafkaConnectionError as exc:
            logger.warning("kafka.producer_connect_failed", error=str(exc))
            self._producer = None

    async def _start_consumer(self) -> None:
        try:
            self._consumer = AIOKafkaConsumer(
                *CONSUME_TOPICS,
                bootstrap_servers=self._brokers,
                group_id="cti-service",
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda v: v,
            )
            await self._consumer.start()
            self._consumer_task = asyncio.create_task(self._consume_loop())
        except KafkaConnectionError as exc:
            logger.warning("kafka.consumer_connect_failed", error=str(exc))
            self._consumer = None
