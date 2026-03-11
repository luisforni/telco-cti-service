# Telco CTI Service

Computer Telephony Integration (CTI) microservice for the telco platform. Provides agent state management, call control operations, queue management, and real-time telephony events.

## Features

- **Agent Management**: Login/logout, state tracking (available, busy, break, away, offline), skill-based routing support
- **Call Control**: Answer, hold, unhold, transfer, conference, and hangup operations via SIP Gateway integration
- **Queue Management**: Queue listing, queue details, and queue call tracking
- **Screen Pop**: CRM data retrieval for incoming calls
- **Real-time Events**: Kafka event publishing for UI and downstream services
- **Redis State**: Agent sessions and active call tracking persisted in Redis
- **Prometheus Metrics**: Active agents by state, call operations counter, queue statistics

## API Endpoints

### Agent Management

| Method | Path | Description |
|--------|------|-------------|
| POST | `/cti/agents/login` | Agent login |
| POST | `/cti/agents/{agent_id}/logout` | Agent logout |
| PUT | `/cti/agents/{agent_id}/state` | Change agent state |
| GET | `/cti/agents/{agent_id}` | Get agent info |
| GET | `/cti/agents/{agent_id}/status` | Get agent current status |
| GET | `/cti/agents` | List all agents |

### Call Control

| Method | Path | Description |
|--------|------|-------------|
| POST | `/cti/calls/{call_id}/answer` | Answer a call |
| POST | `/cti/calls/{call_id}/hold` | Put call on hold |
| POST | `/cti/calls/{call_id}/unhold` | Resume a held call |
| POST | `/cti/calls/{call_id}/transfer` | Transfer call |
| POST | `/cti/calls/{call_id}/conference` | Create conference call |
| POST | `/cti/calls/{call_id}/hangup` | Hang up call |
| GET | `/cti/calls/{call_id}` | Get call details |

### Queue Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/cti/queues` | List all queues |
| GET | `/cti/queues/{queue_id}` | Get queue details |
| GET | `/cti/queues/{queue_id}/calls` | Get calls in queue |

### System

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Health check |
| GET | `/metrics` | Prometheus metrics |

## Agent States

| State | Description |
|-------|-------------|
| `available` | Agent is ready to take calls |
| `busy` | Agent is on a call |
| `break` | Agent is on a break |
| `away` | Agent is away from desk |
| `offline` | Agent is logged out |

## Call Control Operations

| Operation | Description |
|-----------|-------------|
| `answer` | Answer an inbound call |
| `hold` | Place the active call on hold |
| `unhold` | Resume a held call |
| `transfer` | Transfer call to another destination (blind or attended) |
| `conference` | Bridge multiple participants into a conference |
| `hangup` | Terminate the call |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |
| `KAFKA_BROKERS` | `kafka:9092` | Kafka broker addresses |
| `SIP_GATEWAY_URL` | `http://sip-gateway:8002` | SIP Gateway base URL |
| `CALL_ORCHESTRATOR_URL` | `http://call-orchestrator:8005` | Call Orchestrator URL |
| `ROUTING_SERVICE_URL` | `http://routing-service:8007` | Routing Service URL |

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Start the service
uvicorn main:app --host 0.0.0.0 --port 8006 --reload
```

### Docker

```bash
docker build -t telco-cti-service .
docker run -p 8006:8006 \
  -e REDIS_URL=redis://redis:6379/0 \
  -e KAFKA_BROKERS=kafka:9092 \
  telco-cti-service
```

## Integration Examples

### Agent Login

```bash
curl -X POST http://localhost:8006/cti/agents/login \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent-001",
    "name": "John Doe",
    "extension": "1001",
    "skills": ["english", "sales"],
    "queue_ids": ["queue-sales", "queue-support"]
  }'
```

### Answer a Call

```bash
curl -X POST "http://localhost:8006/cti/calls/call-abc123/answer?agent_id=agent-001"
```

### Transfer a Call

```bash
curl -X POST http://localhost:8006/cti/calls/call-abc123/transfer \
  -H "Content-Type: application/json" \
  -d '{
    "destination": "1002",
    "transfer_type": "blind"
  }'
```

### Change Agent State

```bash
curl -X PUT http://localhost:8006/cti/agents/agent-001/state \
  -H "Content-Type: application/json" \
  -d '{"state": "break", "reason": "Lunch break"}'
```

## Kafka Topics

| Direction | Topic | Event Types |
|-----------|-------|-------------|
| Produce | `cti-events` | `call_answered`, `call_held`, `call_unheld`, `call_transferred`, `conference_created`, `call_hangup` |
| Produce | `agent-state-events` | `agent_login`, `agent_logout`, `state_changed` |
| Consume | `call-events` | Inbound call notifications from SIP Gateway |
| Consume | `orchestrator-events` | Routing decisions from Call Orchestrator |

## Redis Schema

| Key Pattern | Type | Description |
|-------------|------|-------------|
| `cti:agent:{agent_id}` | String (JSON) | Agent session data (TTL: 24h) |
| `cti:agents` | Set | Set of all active agent IDs |
| `cti:call:{call_id}` | String (JSON) | Active call state (TTL: 1h) |

