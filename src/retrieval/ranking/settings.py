"""Admin-configurable weight overrides for the Context Retrieval Engine (TASK-US014-05).

Loaded once at module import via a module-level singleton in governance_node.py.

Environment variable format::

    RANKING_WEIGHTS_<INTENT_TYPE_UPPER>=<v_weight>,<k_weight>,<r_weight>

Examples::

    RANKING_WEIGHTS_INCIDENT=0.2,0.6,0.2
    RANKING_WEIGHTS_CODE_GEN=0.7,0.1,0.2
    RANKING_RELEVANCE_THRESHOLD=0.6

When a per-intent env var is absent, the canonical AIR-011 defaults from
``INTENT_WEIGHT_TABLE`` are used instead.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.agents.schemas.intent import IntentType
from src.retrieval.ranking.weights import DEFAULT_WEIGHTS, INTENT_WEIGHT_TABLE, RankingWeights


class RankingSettings(BaseSettings):
    """Per-intent weight overrides loaded from environment at startup.

    All weight fields map to ``RANKING_WEIGHTS_<FIELD_UPPER>`` environment variables
    (e.g. ``RANKING_WEIGHTS_INCIDENT``).  Absent fields fall back to the
    ``INTENT_WEIGHT_TABLE`` canonical defaults.
    """

    relevance_threshold: float = 0.5
    recency_half_life_days: float = 30.0

    # Per-intent overrides (optional — fallback to INTENT_WEIGHT_TABLE)
    weights_debugging: str | None = None
    weights_code_gen: str | None = None
    weights_architecture: str | None = None
    weights_docs: str | None = None
    weights_incident: str | None = None
    weights_metrics: str | None = None
    weights_code_review: str | None = None
    weights_general: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="RANKING_",
        env_file=".env",
        extra="ignore",
    )

    def get_weights(self, intent_type: IntentType) -> RankingWeights:
        """Return ``RankingWeights`` for *intent_type*, applying env overrides first.

        Lookup order:
          1. ``RANKING_WEIGHTS_<INTENT_TYPE_UPPER>`` env var (parsed from CSV).
          2. ``INTENT_WEIGHT_TABLE`` canonical defaults (AIR-011).
          3. ``DEFAULT_WEIGHTS`` (0.6 / 0.2 / 0.2) as final fallback.

        Args:
            intent_type: The classified intent for the current pipeline execution.

        Returns:
            Immutable ``RankingWeights`` instance for the given intent.
        """
        key = intent_type.replace("-", "_")
        env_val: str | None = getattr(self, f"weights_{key}", None)
        if env_val:
            v, k, r = (float(x) for x in env_val.split(","))
            return RankingWeights(vector_weight=v, keyword_weight=k, recency_weight=r)
        return INTENT_WEIGHT_TABLE.get(intent_type, DEFAULT_WEIGHTS)
