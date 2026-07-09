# Normalized Workflow Schema

Defines the platform-independent intermediate representation that ALL workflow adapters produce (source) and consume (target). This is the **universal contract** between source and target adapters.

## Purpose

```
Source Workflow (ADF, Glue, Databricks, Step Functions)
       │
       ▼ source adapter parses
┌─────────────────────────────┐
│   NORMALIZED WORKFLOW       │  ← This schema
│   (platform-independent)    │
└─────────────────────────────┘
       │
       ▼ target adapter generates
Target Workflow (Databricks, ADF, Step Functions, Fabric)
```

Every source adapter MUST produce this schema. Every target adapter MUST consume this schema. No adapter may reference another adapter's format.

## Schema Definition

```yaml
normalized_workflow:
  name: string                    # Workflow/pipeline name
  source_platform: string         # Original platform (for tracking)
  description: string             # Optional description

  tasks:                          # Ordered list of all tasks
    - task_id: string             # Unique task identifier (sanitized)
      task_type: string           # Normalized type (see Task Types below)
      original_type: string       # Source-native type name (for audit)
      config:                     # Task-specific configuration
        notebook_path: string     # For notebook tasks
        main_file: string         # For spark_job tasks
        query: string             # For sql tasks
        pipeline_ref: string      # For sub_pipeline tasks
        resource_arn: string      # For AWS tasks
        # ... extensible per task type
      parameters: object          # Flat key-value: {"param": "value"}
      timeout_seconds: integer    # Timeout in seconds (normalized)
      retries: integer            # Max retry count
      parallel: boolean           # True if part of parallel group
      layer: string               # Detected layer: bronze/silver/gold/default

  dependencies:                   # Dependency graph edges
    - source_task: string         # Upstream task_id
      target_task: string         # Downstream task_id
      condition: string           # success | failure | completed | default

  parallel_groups:                # Groups of tasks that run in parallel
    - group_id: string
      task_ids: [string]          # Tasks in this parallel group
      upstream_dependency: string # Shared upstream task_id

  triggers:                       # Schedule/event triggers
    - trigger_id: string
      type: string                # cron | event | manual
      cron_expression: string     # Normalized cron (6-field: sec min hr dom mon dow)
      timezone: string            # Timezone (default: UTC)
      event_config: object        # For event triggers (source, filter, etc.)

  compute:                        # Compute resource definitions
    - cluster_id: string          # Cluster/resource identifier
      tier: string                # small | medium | large | xlarge
      vcpu: integer               # Source vCPU count
      memory_gb: integer          # Source memory in GB
      num_workers: integer        # Worker count
      spark_version: string       # Spark version (e.g., "3.3")
      assigned_tasks: [string]    # Tasks using this cluster

  metadata:                       # Conversion tracking
    converted_at: string          # ISO timestamp
    source_adapter: string        # Adapter that produced this
    target_adapter: string        # Adapter that will consume this
    transformation: string        # Transformation strategy applied
```

## Normalized Task Types

These are the universal task types that all adapters must map to/from:

| Normalized Type | Description | Source Examples |
|----------------|-------------|----------------|
| `notebook` | Execute a notebook | ADF DatabricksNotebook, Glue Job, Databricks notebook_task |
| `spark_job` | Execute a Spark script/jar | ADF SparkJob, Glue Job (PySpark), Databricks spark_python_task |
| `sql_task` | Execute SQL query | ADF SqlServerStoredProcedure, Databricks sql_task |
| `data_copy` | Copy data between sources | ADF Copy activity |
| `sub_pipeline` | Execute child pipeline | ADF ExecutePipeline, Databricks run_job_task |
| `http_task` | HTTP/REST call | ADF WebActivity |
| `lookup` | Data lookup/query | ADF Lookup |
| `parallel_group` | Group of parallel tasks | Step Functions Parallel, ADF ForEach |
| `conditional_branch` | Conditional routing | Step Functions Choice, ADF IfCondition |
| `for_each` | Iterate over items | Step Functions Map, ADF ForEach |
| `delay` | Wait/pause | Step Functions Wait |
| `dlt_pipeline` | Delta Live Tables pipeline | Databricks pipeline_task |
| `dbt_task` | dbt execution | Databricks dbt_task |
| `crawler` | Schema discovery | Glue Crawler |
| `lambda_function` | Serverless function | Step Functions Lambda task |
| `container_task` | Container execution | Step Functions ECS task |
| `ml_task` | ML training/inference | Step Functions SageMaker task |
| `data_quality` | Data quality check | Step Functions DataBrew task |
| `task_dispatch` | Generic dispatched task | Step Functions Task (unresolved ARN) |
| `passthrough` | No-op / pass data | Step Functions Pass |
| `end_marker` | Terminal success state | Step Functions Succeed |
| `error_handler` | Terminal error state | Step Functions Fail |

## Dependency Conditions

| Normalized Condition | Description |
|---------------------|-------------|
| `success` | Run target task only if source task succeeds |
| `failure` | Run target task only if source task fails |
| `completed` | Run target task regardless of source outcome |
| `default` | Default/fallback path (for conditional branches) |
| `skipped` | Run if source task was skipped |

## Validation Rules

After a source adapter produces the normalized schema, validate:

1. **Every task has a unique `task_id`** — no duplicates
2. **Every dependency references valid task_ids** — both source_task and target_task must exist
3. **Dependency graph is acyclic** — topological sort must succeed (no cycles)
4. **At least one root task** — at least one task with no incoming dependencies
5. **All task_types are from the allowed list** — no unknown types
6. **Timeout values are positive integers** — in seconds, reasonable range (60-86400)
7. **Parallel group tasks exist** — every task_id in parallel_groups.task_ids is in tasks list

## Example: Normalized from ADF Pipeline

```yaml
normalized_workflow:
  name: "customer_etl_pipeline"
  source_platform: "adf"

  tasks:
    - task_id: "ingest_customers"
      task_type: "notebook"
      original_type: "DatabricksNotebook"
      config:
        notebook_path: "/pipelines/ingest_customers"
      parameters:
        source_path: "abfss://raw@storage.dfs.core.windows.net/customers/"
      timeout_seconds: 3600
      retries: 1
      parallel: false
      layer: "bronze"

    - task_id: "transform_customers"
      task_type: "notebook"
      original_type: "DatabricksNotebook"
      config:
        notebook_path: "/pipelines/transform_customers"
      parameters:
        quality_threshold: "0.95"
      timeout_seconds: 7200
      retries: 0
      parallel: false
      layer: "silver"

    - task_id: "aggregate_customers"
      task_type: "notebook"
      original_type: "DatabricksNotebook"
      config:
        notebook_path: "/pipelines/aggregate_customers"
      parameters: {}
      timeout_seconds: 3600
      retries: 0
      parallel: false
      layer: "gold"

  dependencies:
    - source_task: "ingest_customers"
      target_task: "transform_customers"
      condition: "success"
    - source_task: "transform_customers"
      target_task: "aggregate_customers"
      condition: "success"

  parallel_groups: []

  triggers:
    - trigger_id: "daily_schedule"
      type: "cron"
      cron_expression: "0 0 10 * * ?"
      timezone: "UTC"

  compute:
    - cluster_id: "etl_cluster"
      tier: "medium"
      vcpu: 8
      memory_gb: 32
      num_workers: 4
      spark_version: "3.3"
      assigned_tasks: ["ingest_customers", "transform_customers", "aggregate_customers"]

  metadata:
    converted_at: "2026-04-01T10:00:00Z"
    source_adapter: "adf"
    target_adapter: "databricks_workflow"
    transformation: "workflow_transform"
```
