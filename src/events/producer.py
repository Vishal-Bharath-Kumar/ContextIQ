"""
Shared Kafka producer — thin singleton wrapper around AIOKafkaProducer.

DR-005: emits StateTransitionEvents to Kafka for downstream consumers.

``aiokafka`` is imported lazily inside ``get_kafka_producer()`` so this module
can be imported in test environments where the ``aiokafka`` package is not
installed (it will be mocked before the function is called).
"""
from __future__ import annotations

import os
import ssl
from typing import Any

BOOTSTRAP_SERVERS: str = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "kafka.contextiq-data.svc.cluster.local:9092",
)

_producer: Any = None  # AIOKafkaProducer at runtime; Any to avoid import at module level


def _sasl_kwargs() -> dict[str, Any]:
    # aiokafka expects an ssl.SSLContext object (unlike kafka-python's sync
    # clients, which accept a raw ssl_cafile path).
    return {
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "SCRAM-SHA-512",
        "sasl_plain_username": os.environ.get("KAFKA_USERNAME", ""),
        "sasl_plain_password": os.environ.get("KAFKA_PASSWORD", ""),
        "ssl_context": ssl.create_default_context(cafile="/tls/ca.crt"),
    }


async def get_kafka_producer() -> Any:
    """
    Return a started singleton AIOKafkaProducer.

    Creates and starts the producer on first call; returns the cached instance
    on subsequent calls.  Thread-safety is provided by the single-threaded
    asyncio event loop.

    ``aiokafka`` is imported lazily so the module can be loaded in environments
    where the package is unavailable (e.g. tests that mock this function).
    """
    global _producer  # noqa: PLW0603
    if _producer is None:
        from aiokafka import AIOKafkaProducer  # lazy — not needed at import time

        _producer = AIOKafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            **_sasl_kwargs(),
        )
        await _producer.start()
    return _producer
