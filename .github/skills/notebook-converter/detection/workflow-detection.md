# Workflow File Type Detection

Detects the orchestration platform for workflow files (.json, .yaml, .yml) by inspecting structural markers.

## Supported Workflow Types

| Platform | File Format | Key Markers |
|----------|-------------|-------------|
| Azure Data Factory (ADF) | JSON | `"properties"."activities"`, `"type": "Microsoft.DataFactory/..."` |
| Azure Synapse Pipeline | JSON | Same as ADF with Synapse type prefix |
| AWS Glue Workflow | JSON | `"Actions"`, `"Triggers"`, `"Name"` (top-level) |
| Databricks Workflow | JSON/YAML | `"tasks"`, `"task_key"`, `"job_clusters"` |
| AWS Step Functions | JSON | `"StartAt"`, `"States"`, state types (Task, Choice, Map) |

## Detection Algorithm

1. Parse file as JSON or YAML
2. Check for distinctive top-level keys per platform
3. Count matches per orchestration type
4. Type with most matches = detected workflow type
5. If JSON file has no orchestration markers → skip (not a workflow file)

## ADF / Synapse Pipeline Detection

**Required markers (any 2+):**
- `"properties"` key at top level
- `"activities"` array inside properties
- `"type"` containing `"Microsoft.DataFactory"` or `"Microsoft.Synapse"`
- `"linkedServiceName"` in activities
- `"dependsOn"` in activities
- `"triggers"` key

## AWS Glue Workflow Detection

**Required markers (any 2+):**
- `"Name"` as top-level string
- `"Actions"` array with `"JobName"` entries
- `"Triggers"` array with `"Type"` field
- `"Crawlers"` array (optional)
- `"Graph"` with `"Nodes"` and `"Edges"`

## Databricks Workflow Detection

**JSON markers (any 2+):**
- `"tasks"` array with `"task_key"`
- `"job_clusters"` array
- `"schedule"` with `"quartz_cron_expression"`
- `"notebook_task"` or `"spark_python_task"` in tasks

**YAML markers (any 2+):**
- `tasks:` list with `task_key:`
- `job_clusters:` (optional)
- `schedule:` with `quartz_cron_expression:`
- `notebook_task:` or `spark_python_task:` in tasks

## AWS Step Functions Detection

**Required markers (any 2+):**
- `"StartAt"` top-level string
- `"States"` top-level object
- State definitions with `"Type"` (Task, Choice, Parallel, Map, Wait)
- `"Resource"` ARN references

## Non-Workflow JSON Filtering

Skip JSON files that are NOT workflow definitions:
- Configuration files (`config.json`, `settings.json`)
- Package files (`package.json`)
- Schema files
- Files without ANY orchestration markers from above

**Filter rule:** If zero markers match any platform → classify as non-workflow, skip.

## Output

Returns per workflow file:
- `workflow_type`: ADF | Synapse Pipeline | Glue Workflow | Databricks Workflow | Step Functions
- `file_format`: .json | .yaml | .yml
- `marker_count`: Number of platform markers matched
- `detection_confidence`: HIGH (3+) | MEDIUM (2) | LOW (1)
