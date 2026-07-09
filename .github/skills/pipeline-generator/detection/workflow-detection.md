# Workflow Detection

Detects the orchestration platform type for workflow files (.json, .yaml, .yml).

This is the single source of truth for workflow detection logic used by both the pipeline-generator skill and the notebook-converter orchestrator.

## Supported Workflow Types

| Platform | Format | Top-Level Markers |
|----------|--------|-------------------|
| ADF / Synapse | JSON | `properties.activities`, `Microsoft.DataFactory` |
| AWS Glue Workflow | JSON | `Actions`, `Triggers`, `Name` |
| Databricks Workflow | JSON/YAML | `tasks`, `task_key`, `job_clusters` |
| AWS Step Functions | JSON | `StartAt`, `States` |
