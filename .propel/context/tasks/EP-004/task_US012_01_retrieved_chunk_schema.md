# TASK-US012-01 — Define `RetrievedChunk` Result Schema and Upgrade `AgentState.raw_context`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US012-01 |
| User Story | US-012 |
| Epic | EP-004 — Context Retrieval Engine |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the canonical `RetrievedChunk` Pydantic model that every search path (Qdrant ANN, OpenSearch BM25) produces, and upgrade `AgentState.raw_context` from `list[dict]` to `list[RetrievedChunk]`. This is the structural contract shared by the Qdrant client (TASK-US012-02), the OpenSearch client (TASK-US012-03), the RRF merger (TASK-US012-04), and all downstream nodes (governance, compression, routing).

## Implementation Details

**Technology:** Python 3.11+, `pydantic>=2.0`

**File locations:**
- `src/retrieval/schemas/retrieved_chunk.py` — `RetrievedChunk`, `ChunkMetadata` models
- `src/agents/state.py` — `AgentState.raw_context` and `ranked_context` type upgrade
- `tests/retrieval/schemas/test_retrieved_chunk.py`

**`ChunkMetadata` model:**

```python
# src/retrieval/schemas/retrieved_chunk.py
from pydantic import BaseModel, Field
from datetime import datetime

class ChunkMetadata(BaseModel):
    file_path:  str
    timestamp:  datetime
    author:     str
    url:        str | None = None        # deep-link to source document
    chunk_index: int | None = None       # position within the parent document
```

**`RetrievedChunk` model:**

```python
class RetrievedChunk(BaseModel):
    chunk_id:   str             # stable content-addressable ID: sha256(source_id + file_path + chunk_index)
    source_id:  str             # connector/store identifier, e.g. "github", "confluence"
    content:    str             # raw text of the chunk
    score:      float           # normalised relevance score, 0.0–1.0
    metadata:   ChunkMetadata
    search_mode: Literal["vector", "keyword", "rrf"] = "rrf"
                                # origin of the score: pre-merge = "vector"/"keyword"; post-merge = "rrf"

    model_config = ConfigDict(frozen=True)
```

**`AgentState` upgrade (`src/agents/state.py`):**

```python
# Replace both list[dict] annotations — do NOT redefine other fields
from src.retrieval.schemas.retrieved_chunk import RetrievedChunk

class AgentState(TypedDict, total=False):
    # ... existing fields ...
    raw_context:    Optional[list[RetrievedChunk]]   # set by retrieval_agent after hybrid search
    ranked_context: Optional[list[RetrievedChunk]]   # set by governance/compression nodes
```

**`chunk_id` derivation:**

```python
import hashlib

def make_chunk_id(source_id: str, file_path: str, chunk_index: int) -> str:
    raw = f"{source_id}:{file_path}:{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

## Acceptance Criteria

- [ ] `RetrievedChunk` instantiation succeeds with all required fields
- [ ] `score` outside `[0.0, 1.0]` raises `ValidationError`
- [ ] `ChunkMetadata` requires `file_path`, `timestamp`, and `author`
- [ ] `AgentState.raw_context` is typed as `Optional[list[RetrievedChunk]]` — `mypy --strict` confirms no `list[dict]` annotation remains
- [ ] `RetrievedChunk.model_dump()` serialises to JSON-compatible dict (all field types are primitives or ISO strings)
- [ ] `model_config = ConfigDict(frozen=True)` — mutation post-construction raises `ValidationError`

## Dependencies

- TASK-US005-01 (`AgentState` TypedDict — `raw_context: list[dict]` upgraded here)
- TASK-US007-03 (`ContextChunk` aggregator — must be updated to produce `RetrievedChunk` instances; align field names in that task)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `RetrievedChunk` is the single canonical chunk type — no raw `dict` shapes used in retrieval or downstream node code
- [ ] Unit tests cover: valid construction, score boundary validation, `model_dump()` round-trip, `make_chunk_id()` determinism
- [ ] `mypy --strict` passes on `retrieved_chunk.py` and `state.py`; no `ruff` lint errors
