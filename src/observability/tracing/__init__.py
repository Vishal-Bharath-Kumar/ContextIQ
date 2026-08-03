from opentelemetry import trace as _otel_trace
from opentelemetry.trace import Tracer


def get_tracer(name: str) -> Tracer:
    """Thin wrapper so internal modules call get_tracer(__name__) consistently."""
    return _otel_trace.get_tracer(name)
