# TASK-US005-04 — Publish Immutable State Transition Events to Kafka

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US005-04 |
| User Story | US-005 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Event-Driven |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Publish a Kafka event to `contextiq.state.events` on every `AgentState` status transition (`pending → running`, `running → complete`, `running → failed`). Events are immutable, keyed by `request_id`, and consumed by the Replay Service (EP-011) to build the execution audit trace.

## Implementation Details

**Technology:** Python 3.11+, `aiokafka`, `pydantic`, Kafka topic `contextiq.state.events`

**File locations:**
- `src/agents/events/state_event_publisher.py` — `StateEventPublisher` class
- `src/agents/events/state_event_schema.py` — `StateTransitionEvent` Pydantic model
- `src/agents/graph.py` — publisher injected into node wrapper (extends TASK-US005-01)
- `tests/agents/test_state_event_publisher.py`

**`StateTransitionEvent` schema:**
```python
class StateTransitionEvent(BaseModel):
    event_id:     str   # UUID v4 — unique per event
    request_id:   str   # thread_id / LangGraph checkpoint key
    user_id:      str
    from_status:  str   # previous ExecutionStatus value
    to_status:    str   # new ExecutionStatus value
    node_name:    str   # LangGraph node that triggered the transition
    timestamp:    str   # ISO-8601 UTC
    duration_ms:  int   # time spent in the completed node
    error:        str | None = None
```

**`StateEventPublisher`:**
```python
class StateEventPublisher:
    TOPIC = "contextiq.state.events"

    async def publish(self, event: StateTransitionEvent) -> None:
        await self.producer.send_and_wait(
            self.TOPIC,
            key=event.request_id.encode(),   # Kafka partition key → all events for a request go to same partition
            value=event.model_dump_json().encode(),
            headers=[("event_type", b"state.transition")],
        )
```

**Hooking events into the graph — LangGraph node wrapper:**
```python
def with_state_events(node_fn: Callable, node_name: str, publisher: StateEventPublisher):
    async def wrapper(state: AgentState) -> AgentState:
        t_start = time.monotonic()
        await publisher.publish(StateTransitionEvent(
            event_id=str(uuid4()),
            request_id=state["request_id"],
            user_id=state["user_id"],
            from_status=state["status"],
            to_status=ExecutionStatus.RUNNING,
            node_name=node_name,
            timestamp=utcnow_iso(),
            duration_ms=0,
        ))
        try:
            result = await node_fn(state)
            await publisher.publish(StateTransitionEvent(
                ..., to_status=ExecutionStatus.RUNNING, duration_ms=elapsed_ms(t_start)
            ))
            return result
        except Exception as e:
            await publisher.publish(StateTransitionEvent(
                ..., to_status=ExecutionStatus.FAILED, error=str(e), duration_ms=elapsed_ms(t_start)
            ))
            raise
    return wrapper
```

**Terminal events:** After `routing_agent` completes, publish a final `complete` event with `to_status=complete` and total `duration_ms` from `initial_state.timestamp`.

**Event ordering guarantee:** Kafka partition key = `request_id` ensures all events for a single request land on the same partition → consumer (Replay Service) sees them in order.

**Publish failure resilience:** Kafka publish failures are logged at `ERROR` level but do **not** fail the graph execution — event publishing is fire-and-forget (the pipeline result must not be blocked by observability).

## Acceptance Criteria

- [ ] A `pending → running` event is published when the first node begins executing
- [ ] A `running → complete` event is published when `routing_agent` finishes successfully
- [ ] A `running → failed` event is published when any node raises an unhandled exception, including the failing node name in `node_name`
- [ ] All events for the same `request_id` share the same Kafka partition (verified by inspecting partition assignment)
- [ ] Kafka publish failure does not raise an exception in the graph — graph execution continues normally
- [ ] Unit tests assert event fields using a mock `AIOKafkaProducer`; cover: success path, node failure, publish failure

## Dependencies

- TASK-US005-01 (graph nodes to wrap with event publisher)
- TASK-US005-02 (`request_id` available in `AgentState`)
- EP-DATA-002 Kafka topic `contextiq.state.events` with 12 partitions (US-052)

## Definition of Done

- [ ] `aiokafka` added to `pyproject.toml`
- [ ] `AIOKafkaProducer` initialized in FastAPI lifespan with graceful `stop()` on shutdown
- [ ] Unit coverage ≥ 90% for `events/state_event_publisher.py`
- [ ] Integration test: graph invocation → `contextiq.state.events` topic contains `pending→running` and `running→complete` events with correct `request_id`
- [ ] `KAFKA_BOOTSTRAP_SERVERS` documented in `.env.example`
