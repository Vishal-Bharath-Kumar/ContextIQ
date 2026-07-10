# TASK-US038-04 — Connector `fetch()` Span Instrumentation and Kubernetes Jaeger Manifests

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US038-04 |
| User Story | US-038 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend / Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `@connector_span` decorator that wraps every connector `fetch()` call in a child OTel span (AC-3) with `connector_id` and `source_id` attributes (AC-4), and provision the Kubernetes resources required to receive and store OTLP spans in Jaeger: a `jaeger-all-in-one` `Deployment`, a `Service` for the OTLP gRPC receiver (port 4317), and a `Service` for the Jaeger query UI (port 16686). The `BatchSpanProcessor` flush delay from TASK-US038-01 (1 s) combined with Jaeger's ingestion latency satisfies the 5 s retrievability SLA (AC-6).

## Implementation Details

**Technology (backend):** Python 3.11+, `opentelemetry-sdk>=1.25`

**Technology (infra):** Kubernetes YAML, Jaeger `all-in-one` image `jaegertracing/all-in-one:1.57`

**File locations:**
- `src/observability/tracing/connector_span.py` — `connector_span` decorator
- `src/connectors/base.py` — apply decorator to `BaseFetcher.fetch()` (extend only)
- `k8s/monitoring/jaeger/jaeger-deployment.yaml` — `Deployment` + `Services`
- `k8s/monitoring/jaeger/jaeger-collector-service.yaml` — OTLP gRPC + HTTP receiver ports

---

### `connector_span` decorator

```python
# src/observability/tracing/connector_span.py
from __future__ import annotations
import functools
import logging
from typing import Callable, Awaitable, Any

from opentelemetry import trace, context as otel_context

from src.observability.tracing.root_span import RootSpanContext

logger  = logging.getLogger(__name__)
_TRACER = trace.get_tracer(__name__)


def connector_span(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """
    Decorator for connector `fetch()` and `sync()` methods (AC-3).

    Expects `self` to have:
    - `self.connector_id: str`  — unique connector identifier
    - `self.source_id: str`     — knowledge source UUID

    The span context is retrieved from the last positional argument (AgentState)
    OR from `self._otel_ctx` if the connector stores it during request setup.
    """
    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs) -> Any:
        rsc: RootSpanContext | None = (
            getattr(self, "_otel_ctx", None)
            or _extract_ctx_from_args(args, kwargs)
        )

        connector_id = getattr(self, "connector_id", "unknown")
        source_id    = getattr(self, "source_id",    "unknown")
        span_name    = f"connector.{connector_id}.fetch"

        if rsc is None:
            return await fn(self, *args, **kwargs)

        token = otel_context.attach(
            trace.set_span_in_context(rsc.span)
        )
        try:
            with _TRACER.start_as_current_span(
                span_name,
                kind = trace.SpanKind.CLIENT,
            ) as span:
                # AC-3, AC-4: required connector span attributes
                span.set_attribute("connector_id",   connector_id)
                span.set_attribute("source_id",      source_id)
                span.set_attribute("connector.type", getattr(self, "connector_type", "unknown"))
                span.set_attribute("request_id",     str(getattr(self, "_request_id", "")))
                try:
                    result = await fn(self, *args, **kwargs)
                    span.set_attribute("connector.fetch_ok", True)
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR, description=str(exc))
                    raise
        finally:
            otel_context.detach(token)

    return wrapper


def _extract_ctx_from_args(args, kwargs) -> RootSpanContext | None:
    """Scan positional/keyword args for a dict containing _otel_ctx."""
    for arg in args:
        if isinstance(arg, dict) and "_otel_ctx" in arg:
            return arg["_otel_ctx"]
    for val in kwargs.values():
        if isinstance(val, dict) and "_otel_ctx" in val:
            return val["_otel_ctx"]
    return None
```

---

### Apply to `BaseFetcher`

```python
# src/connectors/base.py  (extend only — do NOT rewrite)
from src.observability.tracing.connector_span import connector_span

class BaseFetcher:
    connector_id:   str
    source_id:      str
    connector_type: str
    _otel_ctx:      object | None = None   # injected by retrieval_node

    @connector_span                         # AC-3
    async def fetch(self, query: str, **kwargs) -> list[dict]:
        raise NotImplementedError
```

---

### Inject `_otel_ctx` from `retrieval_node`

```python
# src/agents/nodes/retrieval_node.py  (extend only — add before connector calls)
for connector in connectors:
    connector._otel_ctx      = state.get("_otel_ctx")
    connector._request_id    = state.get("request_id")
```

---

### Kubernetes Jaeger all-in-one deployment

```yaml
# k8s/monitoring/jaeger/jaeger-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger
  namespace: monitoring
  labels:
    app: jaeger
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jaeger
  template:
    metadata:
      labels:
        app: jaeger
      annotations:
        # Tell Prometheus NOT to scrape this pod (Jaeger metrics go to Jaeger itself)
        prometheus.io/scrape: "false"
    spec:
      containers:
        - name: jaeger
          # AC-5, AC-6: all-in-one includes collector + query + agent in one pod
          image: jaegertracing/all-in-one:1.57
          env:
            - name: COLLECTOR_OTLP_ENABLED
              value: "true"
            # In-memory storage sufficient for Phase 1; replace with ES for production
            - name: SPAN_STORAGE_TYPE
              value: memory
            - name: MEMORY_MAX_TRACES
              value: "50000"
          ports:
            - name: otlp-grpc
              containerPort: 4317    # OTLP gRPC receiver (AC-5)
            - name: otlp-http
              containerPort: 4318    # OTLP HTTP receiver (optional fallback)
            - name: query-http
              containerPort: 16686   # Jaeger UI + API (AC-6: trace retrieval)
            - name: collector-grpc
              containerPort: 14250
          resources:
            requests:
              cpu:    200m
              memory: 512Mi
            limits:
              cpu:    "1"
              memory: 2Gi
          readinessProbe:
            httpGet:
              path: "/"
              port: 16686
            initialDelaySeconds: 5
            periodSeconds: 10
---
# k8s/monitoring/jaeger/jaeger-collector-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: jaeger-collector
  namespace: monitoring
  labels:
    app: jaeger
spec:
  selector:
    app: jaeger
  ports:
    # AC-5: OTLPSpanExporter in TASK-US038-01 targets this service on port 4317
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
      protocol: TCP
    - name: otlp-http
      port: 4318
      targetPort: 4318
      protocol: TCP
    - name: collector-grpc
      port: 14250
      targetPort: 14250
      protocol: TCP
---
# Jaeger query/UI service — accessible within the cluster and via port-forward
apiVersion: v1
kind: Service
metadata:
  name: jaeger-query
  namespace: monitoring
  labels:
    app: jaeger
spec:
  selector:
    app: jaeger
  ports:
    # AC-6: query by request_id (= trace_id) at http://jaeger-query:16686
    - name: query-http
      port: 16686
      targetPort: 16686
      protocol: TCP
  type: ClusterIP   # expose via Ingress or kubectl port-forward for external access
```

---

### OTLP endpoint environment variable for all services

Each ContextIQ service `Deployment` must set:

```yaml
# k8s/services/contextiq-api-deployment.yaml  (extend only — add to env block)
env:
  - name: OTEL_SERVICE_NAME
    value: contextiq-api
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://jaeger-collector.monitoring.svc.cluster.local:4317
  - name: OTEL_ENABLED
    value: "true"
```

## Acceptance Criteria

- [ ] `@connector_span` creates a child span named `connector.{connector_id}.fetch` (AC-3)
- [ ] Child span has `connector_id` and `source_id` attributes (AC-4)
- [ ] `connector.fetch_ok = True` is set on success; exception is recorded on failure (AC-3)
- [ ] `kubectl apply -f k8s/monitoring/jaeger/` creates the `Deployment` and both `Services` (AC-5)
- [ ] Jaeger pod is `Ready` within 30 s; `GET http://jaeger-query:16686/api/traces/{trace_id}` returns the trace within 5 s of span completion (AC-6)
- [ ] `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger-collector.monitoring.svc.cluster.local:4317` resolves to the `jaeger-collector` Service on port 4317

## Dependencies

- TASK-US038-01 (`OTLPSpanExporter` target is `jaeger-collector:4317`)
- TASK-US038-02 (`RootSpanContext` — used to parent connector spans)
- Connector base class (`src/connectors/base.py` — `BaseFetcher.fetch()`)

## Definition of Done

- [ ] YAML lints with `kubectl apply --dry-run=client`
- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors on Python files
