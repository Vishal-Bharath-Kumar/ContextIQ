# Import all models so that:
#   1. Alembic autogenerate can detect all tables via Base.metadata
#   2. SQLAlchemy relationship back-refs are resolved at mapper configuration time
from src.data.models.base import Base
from src.data.models.connector_config import ConnectorConfig, ConnectorType
from src.data.models.knowledge_source import KnowledgeSource
from src.data.models.knowledge_chunk import KnowledgeChunk
from src.data.models.model_registry import ModelRegistry, ModelStatus
from src.data.models.policy import Policy, PolicyType
from src.data.models.audit_log import AuditLog
from src.data.models.execution_trace_index import ExecutionTraceIndex
from src.data.models.sync_job import SyncJob, SyncStatus

__all__ = [
    "Base",
    "ConnectorConfig", "ConnectorType",
    "KnowledgeSource",
    "KnowledgeChunk",
    "ModelRegistry", "ModelStatus",
    "Policy", "PolicyType",
    "AuditLog",
    "ExecutionTraceIndex",
    "SyncJob", "SyncStatus",
]
