"""Tests for EntityExtractor — TASK-US028-02.

Covers all acceptance criteria:
  AC-2  extract() returns EntityExtractionResult with 7 valid entity types supported.
  AC-5  duration_ms > 0 in the returned result.
  AC-6  Empty entity list returned when LLM returns {"entities": []}.
        Malformed entity items are skipped; other entities still returned.
        asyncio.TimeoutError propagated on LLM timeout.
        ValueError raised on non-JSON LLM response.
  deterministic entity_id derived from type + canonical_name.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.knowledge_graph.extraction.extractor import EntityExtractor, ExtractionSettings
from src.knowledge_graph.schemas.entity import EntityType, make_entity_id
from src.knowledge_graph.schemas.events import ChunkIndexedEvent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_CHUNK_ID = UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")


def _make_event(text: str = "The Auth Service was deployed by Alice.") -> ChunkIndexedEvent:
    return ChunkIndexedEvent(
        chunk_id=_CHUNK_ID,
        source_id=_SOURCE_ID,
        tenant_id="tenant-1",
        document_id="doc-1",
        text=text,
        token_count=10,
        embedding_model="text-embedding-3-small",
        indexed_at=datetime.now(tz=UTC),
    )


def _make_litellm_response(content: str) -> MagicMock:
    """Build a minimal mock that looks like a litellm ModelResponse."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def _settings() -> ExtractionSettings:
    return ExtractionSettings(
        model_id="gpt-4o-mini",
        timeout_s=2.0,
        temperature=0.0,
        max_tokens=512,
    )


# ---------------------------------------------------------------------------
# AC-5 — duration_ms > 0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_returns_positive_duration_ms() -> None:
    payload = json.dumps({"entities": []})
    mock_response = _make_litellm_response(payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        extractor = EntityExtractor(settings=_settings())
        result = await extractor.extract(_make_event())

    assert result.duration_ms > 0


# ---------------------------------------------------------------------------
# AC-6 (empty) — empty entities list when LLM returns {"entities": []}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_empty_entities_on_empty_response() -> None:
    payload = json.dumps({"entities": []})
    mock_response = _make_litellm_response(payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        extractor = EntityExtractor(settings=_settings())
        result = await extractor.extract(_make_event())

    assert result.entities == []
    assert result.chunk_id == _CHUNK_ID
    assert result.source_id == _SOURCE_ID


# ---------------------------------------------------------------------------
# Happy path — valid single entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_single_valid_entity() -> None:
    canonical = "auth service"
    payload = json.dumps(
        {
            "entities": [
                {
                    "entity_type": "Service",
                    "name": "Auth Service",
                    "canonical_name": canonical,
                    "properties": {"team": "platform"},
                }
            ]
        }
    )
    mock_response = _make_litellm_response(payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        extractor = EntityExtractor(settings=_settings())
        result = await extractor.extract(_make_event())

    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.entity_type == EntityType.SERVICE
    assert entity.name == "Auth Service"
    assert entity.canonical_name == canonical
    assert entity.entity_id == make_entity_id(EntityType.SERVICE, canonical)
    assert entity.source_id == _SOURCE_ID
    assert entity.chunk_id == _CHUNK_ID
    assert entity.properties == {"team": "platform"}


# ---------------------------------------------------------------------------
# AC-2 — all 7 entity types round-trip through extractor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity_type_str",
    [
        "Service",
        "Repository",
        "Developer",
        "Incident",
        "Deployment",
        "AlertRule",
        "Document",
    ],
)
async def test_extract_all_entity_types(entity_type_str: str) -> None:
    canonical = f"test {entity_type_str.lower()}"
    payload = json.dumps(
        {
            "entities": [
                {
                    "entity_type": entity_type_str,
                    "name": f"Test {entity_type_str}",
                    "canonical_name": canonical,
                    "properties": {},
                }
            ]
        }
    )
    mock_response = _make_litellm_response(payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        extractor = EntityExtractor(settings=_settings())
        result = await extractor.extract(_make_event())

    assert len(result.entities) == 1
    assert result.entities[0].entity_type.value == entity_type_str


# ---------------------------------------------------------------------------
# AC-6 (malformed skip) — malformed items skipped; valid items still returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_skips_malformed_entity_keeps_valid() -> None:
    canonical = "payment service"
    payload = json.dumps(
        {
            "entities": [
                # malformed: missing "entity_type"
                {"name": "BadEntity", "canonical_name": "bad entity", "properties": {}},
                # valid
                {
                    "entity_type": "Service",
                    "name": "Payment Service",
                    "canonical_name": canonical,
                    "properties": {},
                },
                # malformed: invalid entity_type value
                {
                    "entity_type": "UnknownType",
                    "name": "Unknown",
                    "canonical_name": "unknown",
                    "properties": {},
                },
            ]
        }
    )
    mock_response = _make_litellm_response(payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        extractor = EntityExtractor(settings=_settings())
        result = await extractor.extract(_make_event())

    assert len(result.entities) == 1
    assert result.entities[0].canonical_name == canonical


# ---------------------------------------------------------------------------
# AC-6 (timeout) — asyncio.TimeoutError propagated on LLM timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_raises_timeout_error_on_llm_timeout() -> None:
    async def _slow(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(10)

    with patch("litellm.acompletion", new=AsyncMock(side_effect=asyncio.TimeoutError)):
        extractor = EntityExtractor(settings=_settings())
        with pytest.raises(asyncio.TimeoutError):
            await extractor.extract(_make_event())


# ---------------------------------------------------------------------------
# AC-6 (invalid JSON) — ValueError raised on non-JSON LLM response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_raises_value_error_on_non_json_response() -> None:
    mock_response = _make_litellm_response("This is not JSON at all!!!")

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        extractor = EntityExtractor(settings=_settings())
        with pytest.raises(ValueError, match="LLM returned non-JSON content"):
            await extractor.extract(_make_event())


# ---------------------------------------------------------------------------
# Deterministic entity_id — same inputs always produce same ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_entity_id_is_deterministic() -> None:
    canonical = "api gateway"
    payload = json.dumps(
        {
            "entities": [
                {
                    "entity_type": "Service",
                    "name": "API Gateway",
                    "canonical_name": canonical,
                    "properties": {},
                }
            ]
        }
    )

    with patch("litellm.acompletion", new=AsyncMock(return_value=_make_litellm_response(payload))):
        extractor = EntityExtractor(settings=_settings())
        result1 = await extractor.extract(_make_event())

    with patch("litellm.acompletion", new=AsyncMock(return_value=_make_litellm_response(payload))):
        extractor2 = EntityExtractor(settings=_settings())
        result2 = await extractor2.extract(_make_event())

    assert result1.entities[0].entity_id == result2.entities[0].entity_id
    assert result1.entities[0].entity_id == make_entity_id(EntityType.SERVICE, canonical)


# ---------------------------------------------------------------------------
# canonical_name fallback — canonical_name derived from name when absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_derives_canonical_name_from_name_when_missing() -> None:
    payload = json.dumps(
        {
            "entities": [
                {
                    "entity_type": "Developer",
                    "name": "  Alice Smith  ",
                    "properties": {},
                }
            ]
        }
    )
    mock_response = _make_litellm_response(payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        extractor = EntityExtractor(settings=_settings())
        result = await extractor.extract(_make_event())

    assert len(result.entities) == 1
    assert result.entities[0].canonical_name == "alice smith"
