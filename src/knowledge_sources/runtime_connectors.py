"""Runtime connector overrides sourced from active knowledge_sources rows.

Bridges the current architecture gap between:

- type-based startup connector discovery in ``src.connector_sdk.registry``
- source-scoped connector configuration stored in ``knowledge_sources``

This allows the runtime registry entry for a connector type such as ``github``
to be replaced with a connector configured from active knowledge-source rows
for that type.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.agents.retrieval.connector_loader import CONNECTOR_CLASS_MAP
from src.connector_sdk.base import BaseConnector
from src.connector_sdk.registry import ConnectorRegistry
from src.knowledge_sources.repositories.knowledge_source_repository import (
    KnowledgeSourceRepository,
)

logger = logging.getLogger(__name__)

_SCOPE_CONFIG_FIELD: dict[str, str] = {
    "github": "repos",
    "jira": "projects",
    "confluence": "spaces",
    "grafana": "dashboard_uids",
}


async def apply_runtime_connector_overrides(
    registry: ConnectorRegistry,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Replace generic registry entries with scoped active knowledge sources.

    Active knowledge-source rows are grouped by connector type. When multiple
    active rows share the same credentials path, their scopes are aggregated
    into a single runtime connector so retrieval can search across all of them.
    Rows with a different credentials path are skipped because the current
    runtime registry can only host one credential set per connector type.
    """
    async with session_factory() as session:
        records = await KnowledgeSourceRepository(session).list_all()

    active_by_type: dict[str, list[object]] = {}
    for record in records:
        if not record.is_active:
            continue
        connector_type = str(record.connector_type)
        active_by_type.setdefault(connector_type, []).append(record)

    if not active_by_type:
        return

    for connector_type, records_for_type in active_by_type.items():
        mapping = CONNECTOR_CLASS_MAP.get(connector_type)
        if mapping is None:
            continue

        connector_cls, config_cls = mapping
        scope_field = _SCOPE_CONFIG_FIELD.get(connector_type)
        primary_record = records_for_type[0]
        primary_vault_path = primary_record.credentials_vault_path
        matching_records = [
            record
            for record in records_for_type
            if record.credentials_vault_path == primary_vault_path
        ]
        skipped_records = [
            record
            for record in records_for_type
            if record.credentials_vault_path != primary_vault_path
        ]

        config_kwargs: dict[str, object] = {
            "vault_path": primary_vault_path,
        }
        if scope_field:
            scopes: list[str] = []
            for record in matching_records:
                if record.scope not in scopes:
                    scopes.append(record.scope)
            config_kwargs[scope_field] = scopes

        if skipped_records:
            logger.warning(
                "runtime_connector_override_skipped_mismatched_credentials",
                extra={
                    "connector_type": connector_type,
                    "primary_vault_path": primary_vault_path,
                    "skipped_scopes": [record.scope for record in skipped_records],
                },
            )

        try:
            connector: BaseConnector = connector_cls(config=config_cls(**config_kwargs))
            await connector.authenticate()
            registry.register(connector_type, connector, enabled=True)
            logger.info(
                "runtime_connector_override_applied",
                extra={
                    "connector_type": connector_type,
                    "scopes": [record.scope for record in matching_records],
                    "vault_path": primary_vault_path,
                },
            )
        except Exception:
            logger.warning(
                "runtime_connector_override_failed",
                extra={
                    "connector_type": connector_type,
                    "scopes": [record.scope for record in matching_records],
                },
                exc_info=True,
            )