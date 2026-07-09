---
name: pipeline-generator
description: Generates target platform workflow/orchestration definitions from converted notebooks. Supports Databricks Asset Bundles (DAB), ADF/Synapse Pipeline JSON, and AWS Glue Workflow JSON. Uses existing workflow conversion logic.
---

# Pipeline Orchestration Converter

Converts pipeline orchestration files (JSON/YAML) between cloud platforms: ADF, Synapse Pipeline, Glue Workflow, Databricks Workflow, Step Functions.

## Purpose

When converting data pipeline code between platforms, orchestration definitions also need conversion. This skill handles the translation of workflow/pipeline definitions, activity mappings, triggers, and dependencies.

## Supported Workflow Types

### Input Detection

**All workflow detection logic is defined in the detection module:**

**File:** `detection/workflow-detection.md`

Detects orchestration platform type for workflow files (`.json`, `.yaml`, `.yml`, `.py`) by inspecting structural markers:
- Azure Data Factory / Synapse Pipeline (JSON)
- Azure Synapse Analytics Pipeline (JSON)
- Microsoft Fabric Pipeline (JSON)
- AWS Glue Workflow (JSON)
- AWS EMR / Step Functions (JSON)
- Databricks Workflow (JSON/YAML)
- GCP Dataproc / Cloud Composer DAG (Python/YAML)

Returns: `workflow_type`, `file_format`, `marker_count`, `detection_confidence`

**Usage:** Load `detection/workflow-detection.md` and apply its detection algorithm. Do not duplicate detection logic in this file.

## Conversion Logic

### Policy Defaults

Governance constraints applied during conversion. These are the only "defaults" in the system — everything else comes from source input.

| Policy Key | Value | Description |
|-----------|-------|-------------|
| `policy.workspace_notebook_root` | `/Workspace/Pipelines` | Target notebook path prefix (supports `/Repos/` or bundle paths) |
| `policy.notebook_suffix` | `_databricks` | Suffix appended to converted notebook names |
| `policy.layer_timeout.bronze` | `28800` | Max timeout (seconds) for bronze/ingestion tasks |
| `policy.layer_timeout.silver` | `28800` | Max timeout (seconds) for silver/transform tasks |
| `policy.layer_timeout.gold` | `14400` | Max timeout (seconds) for gold/serving tasks |
| `policy.layer_timeout.default` | `28800` | Fallback timeout when layer is undetectable |
| `policy.compute_match_threshold` | `0.8` | Minimum target/source compute ratio for PASS |
| `policy.default_max_retries` | `0` | Default retry count when source has none |
| `policy.default_max_concurrent_runs` | `1` | Default concurrency when source has none |

### ADF/Synapse/Fabric → AWS Glue Workflow

**Structure mapping:**
```
ADF/Synapse/Fabric Pipeline → Glue Workflow
├── activities[] → Actions[]
│   ├── DatabricksNotebook/SynapseNotebook/TridentNotebook → Glue Job reference
│   ├── SparkJob → Glue Job reference
│   ├── Copy → Glue Job reference
│   └── dependsOn → CONDITIONAL triggers
├── triggers[] → Triggers[]
└── parameters → Job Arguments (--param format)
```

**Activity conversion:**
- Extract activity names and types
- Map each activity to Glue Job reference
- Preserve dependency order
- Convert parameters to `--key value` format

**Output format:**
```json
{
  "Name": "workflow_name",
  "Actions": [
    {
      "JobName": "glue_job_name",
      "Arguments": {
        "--param1": "value1"
      }
    }
  ],
  "Triggers": [
    {
      "Name": "scheduled_trigger",
      "Type": "SCHEDULED",
      "Schedule": "cron(0 10 * * ? *)"
    }
  ]
}
```

### AWS Glue Workflow → ADF/Synapse Pipeline

**Structure mapping:**
```
Glue Workflow → ADF Pipeline
├── Actions[] → activities[]
│   ├── JobName → DatabricksNotebook or SparkJob activity
│   └── Arguments → parameters
├── Triggers[] → triggers[]
└── Name → pipeline name
```

**Activity conversion:**
- Create SparkJob or DatabricksNotebook activity per Glue Job
- Map Arguments to activity parameters
- Infer dependencies from trigger conditions or ordering

**Output format:**
```json
{
  "name": "pipeline_name",
  "properties": {
    "activities": [
      {
        "name": "activity_name",
        "type": "DatabricksNotebook",
        "typeProperties": {
          "notebookPath": "/path/to/notebook",
          "baseParameters": {
            "param1": "value1"
          }
        },
        "dependsOn": []
      }
    ],
    "parameters": {},
    "triggers": []
  }
}
```

### ADF/Synapse → Databricks Workflow (DAB)

**Structure mapping:**
```
ADF Pipeline → Databricks Asset Bundle
├── pipeline name → resources.jobs.<key>.name
├── activities[] → tasks[]
│   ├── activity name → task_key
│   ├── DatabricksNotebook → notebook_task
│   ├── SparkJob → spark_python_task or spark_jar_task
│   └── dependsOn → depends_on[]
├── triggers[] → schedule
└── parameters → job parameters
```

**Output format (DAB-compliant):**

All values are extracted from the source workflow input — nothing is hardcoded.

```yaml
resources:
  jobs:
    ${source.pipeline_name | sanitize_key}:                   # from: ADF pipeline name
      name: ${source.pipeline_name}                            # from: ADF pipeline name
      email_notifications:
        on_failure: []
      max_concurrent_runs: 1
      tasks:
        - task_key: ${source.activities[0].name | sanitize_key} # from: ADF activity name
          notebook_task:
            notebook_path: ${policy.workspace_notebook_root}/${source.activities[0].name}
            base_parameters:                                    # from: ADF activity typeProperties.baseParameters
              ${source.activities[0].params.key}: ${source.activities[0].params.value}
          job_cluster_key: job_cluster_${derived.cluster_tier}  # tier derived from source compute
          timeout_seconds: ${derived.timeout_seconds}           # from: source timeout → converted → policy validated
          max_retries: ${source.activities[0].retry_count | default: 0}
          depends_on: []                                        # from: ADF activity dependsOn

        - task_key: ${source.activities[1].name | sanitize_key}
          notebook_task:
            notebook_path: ${policy.workspace_notebook_root}/${source.activities[1].name}
          depends_on:
            - task_key: ${source.activities[0].name | sanitize_key}  # from: ADF dependsOn[].activity
          job_cluster_key: job_cluster_${derived.cluster_tier}
          timeout_seconds: ${derived.timeout_seconds}
          max_retries: ${source.activities[1].retry_count | default: 0}
      job_clusters:
        - job_cluster_key: job_cluster_${derived.cluster_tier}
          new_cluster:
            spark_version: ${derived.spark_runtime}             # mapped from source engine version
            node_type_id: ${derived.node_type_id}              # mapped from source compute specs
            num_workers: ${derived.num_workers}                 # from: source worker/node count
      schedule:                                                 # from: ADF trigger recurrence
        quartz_cron_expression: ${derived.cron_expression}     # converted from ADF schedule format
        timezone_id: ${source.trigger.timezone | default: "UTC"}
```

**Placeholder resolution:**
- `${source.*}` — Read directly from the input workflow JSON/YAML
- `${derived.*}` — Computed by the converter (compute mapping, timeout policy, format conversion)
- `${lookup.*}` — Resolved from static mapping tables (worker specs, node types, runtime versions)
- `${policy.*}` — Governance constraints and deployment config (timeout caps, notebook root path)
- `| sanitize_key` — Lowercase, replace spaces/special chars with underscores
- `| default: value` — Fallback if source field is absent

### AWS Glue Workflow → Databricks Workflow (DAB)

**Structure mapping:**
```
Glue Workflow → Databricks Asset Bundle
├── Workflow.Name → resources.jobs.<key>.name
├── JOB nodes → tasks[]
│   ├── JobName → task_key + notebook_task
│   ├── Job Arguments → base_parameters
│   └── Trigger CONDITIONAL → depends_on[]
├── Trigger SCHEDULED → schedule (quartz_cron)
├── WorkerType + NumberOfWorkers → job_clusters[].new_cluster (compute validated)
└── Timeout (minutes) → timeout_seconds (× 60, then policy validated)
```

**Output format (DAB-compliant):**

All values are extracted from the source Glue workflow JSON — nothing is hardcoded.

```yaml
resources:
  jobs:
    ${source.Workflow.Name | sanitize_key}:                           # from: Glue Workflow.Name
      name: ${source.Workflow.Name}                                    # from: Glue Workflow.Name
      email_notifications:
        on_failure: []
      max_concurrent_runs: 1
      tasks:
        # Repeat for each JOB node in source.Graph.Nodes where Type == "JOB"
        - task_key: ${source.job_node.Name | sanitize_key}             # from: Glue JOB node Name
          notebook_task:
            notebook_path: ${policy.workspace_notebook_root}/${source.job_node.Name}_databricks
            base_parameters:                                            # from: Glue job Arguments
              ${source.job_node.Arguments.key}: ${source.job_node.Arguments.value}
          job_cluster_key: job_cluster_${derived.cluster_tier}          # tier from source WorkerType
          timeout_seconds: ${derived.policy_validated_timeout}          # source Timeout × 60 → policy cap
          max_retries: ${source.job_node.MaxRetries | default: 0}      # from: Glue job MaxRetries
          depends_on: ${derived.depends_on_from_triggers}               # from: CONDITIONAL trigger predicates
      job_clusters:
        - job_cluster_key: job_cluster_${derived.cluster_tier}
          new_cluster:
            spark_version: ${derived.spark_runtime}                     # mapped from: GlueVersion
            node_type_id: ${derived.node_type_id}                      # mapped from: WorkerType via compute table
            num_workers: ${source.job_node.NumberOfWorkers}             # from: Glue NumberOfWorkers
```

**Source field extraction (Glue Workflow JSON):**
- `Workflow.Name` → job name
- `Graph.Nodes[Type=JOB].Name` → task keys
- `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].WorkerType` → compute mapping input
- `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].NumberOfWorkers` → num_workers
- `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].Timeout` → timeout in minutes
- `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].GlueVersion` → spark runtime mapping
- `Graph.Nodes[Type=TRIGGER].TriggerDetails.Trigger.Predicate.Conditions` → depends_on (trigger source)
- `Graph.Edges` → depends_on (edge source) + dependency graph validation

**Dependency resolution:** `derived.depends_on = union(edges_predecessors, trigger_condition_predecessors)` — both sources are merged and deduplicated.

### Databricks Workflow → ADF/Synapse Pipeline

**Structure mapping:**
```
Databricks Workflow → ADF Pipeline
├── tasks[] → activities[]
│   ├── task_key → activity name
│   ├── notebook_task → DatabricksNotebook activity
│   ├── spark_python_task → SparkJob activity
│   └── depends_on[] → dependsOn[]
├── schedule → triggers[]
└── parameters → pipeline parameters
```

### Databricks Workflow (DAB) → AWS Glue Workflow

**Structure mapping:**
```
Databricks Asset Bundle → Glue Workflow
├── resources.jobs.<key>.tasks[] → Actions[]
│   ├── notebook_task → Glue Job (PySpark)
│   ├── spark_python_task → Glue Job
│   └── depends_on[] → CONDITIONAL triggers
├── job_clusters[].new_cluster → WorkerType + NumberOfWorkers
└── schedule → Triggers[] (SCHEDULED type)
```

### Any Source → Azure Synapse Pipeline

**Structure mapping:**
```
Source Workflow → Synapse Pipeline
├── tasks[] → activities[]
│   ├── notebook → SynapseNotebook activity
│   ├── spark_job → SparkJob activity
│   ├── data_copy → Copy activity
│   └── depends_on → dependsOn[]
├── schedule → ScheduleTrigger
└── parameters → pipeline parameters (typed)
```

### Any Source → AWS EMR (Step Functions)

**Structure mapping:**
```
Source Workflow → EMR Step Functions State Machine
├── tasks[] → States{}
│   ├── notebook/spark_job → Task state (emr-serverless:startJobRun)
│   ├── sql_task → Task state (athena:startQueryExecution)
│   └── depends_on → Next pointer chain
├── schedule → EventBridge rule (companion JSON)
└── parameters → EntryPointArguments list
```

### Any Source → GCP BigQuery / Cloud Composer

**Structure mapping:**
```
Source Workflow → Airflow DAG (Python)
├── tasks[] → Airflow Operator instances
│   ├── notebook/spark_job → DataprocSubmitJobOperator
│   ├── sql_task → BigQueryInsertJobOperator
│   └── depends_on → set_upstream() / >> operators
├── schedule → schedule_interval in DAG()
└── parameters → op_kwargs / EntryPointArguments
```

## Activity Type Mapping

### ADF Activity → AWS Mapping Table
| ADF Type | AWS Type | Conversion Notes |
|----------|----------|------------------|
| Copy | Glue Job (ETL) | Full ETL, map source/sink to catalog |
| DatabricksNotebook | Glue Job (PySpark) | Convert notebook content |
| SparkJob | Glue Job | Direct mapping |
| ExecutePipeline | Step Function Call | Nested workflow |
| WebActivity | Lambda invocation | API calls |
| ForEach | Step Function Map | Parallel iteration |
| IfCondition | Step Function Choice | Conditional logic |
| Lookup | Glue Job with output | Data-driven |
| Wait | Step Function Wait | Delay |

### AWS → ADF Activity Mapping Table
| AWS Type | ADF Type | Conversion Notes |
|----------|----------|------------------|
| Glue Job (PySpark) | DatabricksNotebook | Convert script to notebook |
| Glue Job (Scala) | SparkJob | JAR reference |
| Glue Crawler | Copy + Schema Detection | Metadata sync |
| Step Function Task | ExecutePipeline | Nested pipeline |
| Lambda Function | WebActivity | HTTP/API call |
| Step Function Map | ForEach | Iteration |
| Step Function Choice | IfCondition | Branching |
| Step Function Wait | Wait | Delay |

### Databricks Task → ADF/AWS Mapping
| Databricks Type | ADF Type | AWS Type |
|----------------|----------|----------|
| notebook_task | DatabricksNotebook | Glue Job (PySpark) |
| spark_python_task | SparkJob | Glue Job |
| spark_jar_task | SparkJob | Glue Job |
| run_job_task | ExecutePipeline | Step Function Call |
| sql_task | Script Activity | Glue Job (SQL) |
| for_each_task | ForEach | Step Function Map |

## Conversion Rules

### 1. Preserve Execution Order
- Extract dependency graph from source
- Maintain topological order in target
- Use `dependsOn`, `depends_on`, or sequential ordering

### 2. Parameter Mapping
**ADF parameters:**
```json
"parameters": {
  "param1": { "type": "String", "defaultValue": "value" }
}
```

**Glue arguments:**
```json
"Arguments": {
  "--param1": "value"
}
```

**Databricks parameters:**
```yaml
base_parameters:
  param1: value
```

### 3. Trigger/Schedule Conversion
**ADF trigger:**
```json
"triggers": [{
  "type": "ScheduleTrigger",
  "recurrence": {
    "frequency": "Day",
    "interval": 1,
    "schedule": { "hours": [10], "minutes": [0] }
  }
}]
```

**Glue trigger:**
```json
"Triggers": [{
  "Type": "SCHEDULED",
  "Schedule": "cron(0 10 * * ? *)"
}]
```

**Databricks schedule:**
```yaml
schedule:
  quartz_cron_expression: "0 0 10 * * ?"
  timezone_id: "UTC"
```

### 4. Linked Services / Connections
**ADF Linked Service:**
```json
"linkedServiceName": {
  "referenceName": "AzureDataLakeStore",
  "type": "LinkedServiceReference"
}
```

**Glue Connection:**
```json
"Connections": {
  "Connections": ["connection_name"]
}
```

**Conversion:** Extract storage/database configs, map to target platform credentials

### 5. Dataset References
**ADF Dataset:**
```json
"inputs": [
  {
    "referenceName": "SourceDataset",
    "type": "DatasetReference"
  }
]
```

**Mapping:** Convert to target-platform storage paths or catalog references in the job code

## Workflow Format Selection

Based on target engine, select appropriate output format:

| Target Engine | Default Format | Why |
|--------------|---------------|-----|
| Databricks | YAML | Jobs API native format |
| Synapse | JSON | ARM template format |
| ADF | JSON | Pipeline definition format |
| Glue | JSON | Workflow API format |
| EMR | JSON | Step Functions format |
| Fabric | JSON | Pipeline definition (ADF-like) |

## Conversion Architecture

The converter executes as a **staged pipeline**. Each stage produces an output consumed by the next. Generation and validation are strictly separated.

```
Stage 1: Workflow Detection
    Input:  Raw file (JSON/YAML)
    Output: source_platform, workflow_type
    Logic:  Match platform markers from Input Detection tables

Stage 2: Source Model Extraction
    Input:  Raw file + source_platform
    Output: source_model {
              workflow_name, jobs[], triggers[], edges[],
              per-job: { name, arguments, worker_type, worker_count,
                         timeout, timeout_unit, glue_version, max_retries }
            }
    Logic:  Extract fields per Input-to-Output Field Mapping tables

Stage 3: Derived Value Computation
    Input:  source_model + lookup tables + policy defaults
    Output: derived_model {
              per-task: { task_key, cluster_tier, spark_runtime, node_type_id,
                          timeout_seconds, policy_validated_timeout, layer,
                          depends_on },
              cluster: { node_type_id, num_workers, total_cpu, total_memory },
              job_level_timeout
            }
    Logic:  Apply Derived Field Definitions (see below)

Stage 4: Intermediate Workflow Model
    Input:  source_model + derived_model + policy defaults
    Output: target_model (platform-agnostic structured object)
    Logic:  Merge source + derived into unified task/cluster/schedule model

Stage 5: Validation Pipeline
    Input:  target_model + source_model
    Output: validation_report { checks[], overall_status }
    Logic:  Execute all Validation Checks (see Workflow Validation Step)
    Gate:   ERROR → halt; WARNING → log and continue

Stage 6: Target Workflow Generation
    Input:  target_model (validated)
    Output: databricks_job.yml (DAB-compliant YAML)
    Logic:  Serialize target_model into DAB structure

Stage 7: Reporting
    Input:  source_model + derived_model + validation_report
    Output: compute_validation_report.md, conversion_validation_report.md
    Logic:  Populate report templates with resolved values
```

## Derived Field Definitions

The converter computes the following derived values. Each definition specifies inputs, logic, and output.

### derived.cluster_tier
```
Input:   source.WorkerType
Logic:   IF WorkerType in [Standard, G.1X] → "small"
         IF WorkerType == "G.2X"           → "medium"
         IF WorkerType == "G.4X"           → "large"
         IF WorkerType == "G.8X"           → "xlarge"
         IF WorkerType == "Z.2X"           → "medium"
         ELSE                              → "medium" (default)
Output:  String used in job_cluster_key: "job_cluster_{tier}"
```

### derived.spark_runtime
```
Input:   source.GlueVersion (Glue) OR source.engine_version (ADF)
Lookup:  Glue Version → Spark Runtime Mapping table
Output:  Databricks runtime string (e.g., "14.3.x-scala2.12")
```

### derived.node_type_id
```
Input:   source.WorkerType + target_cloud
Lookup:  Glue Worker → Databricks Node Type Recommendations table
Output:  Databricks node type string (e.g., "Standard_DS4_v2")
```

### derived.timeout_seconds
```
Input:   source.Timeout + source.timeout_unit
Logic:   IF source_platform == "AWS Glue":  timeout_seconds = source.Timeout * 60
         IF source_platform == "ADF":       timeout_seconds = parse_to_seconds(source.Timeout)
         IF source_platform == "Databricks": timeout_seconds = source.Timeout
Output:  Integer (seconds)
```

### derived.layer
```
Input:   source.job_name
Logic:   IF regex_match(job_name, policy.layer_regex.bronze) → "bronze"
         IF regex_match(job_name, policy.layer_regex.silver) → "silver"
         IF regex_match(job_name, policy.layer_regex.gold)   → "gold"
         ELSE                                                → "default"
Output:  String ("bronze" | "silver" | "gold" | "default")
```

### derived.policy_validated_timeout
```
Input:   derived.timeout_seconds + derived.layer + policy.layer_timeout
Logic:   max_allowed = policy.layer_timeout[derived.layer]
         result = min(derived.timeout_seconds, max_allowed)
         IF result < derived.timeout_seconds:
             log_warning("Timeout adjusted: {derived.timeout_seconds}s → {result}s. Reason: {derived.layer} pipeline timeout policy")
Output:  Integer (seconds)
```

### derived.job_level_timeout
```
Input:   all derived.policy_validated_timeout values across tasks
Logic:   max(all task policy_validated_timeouts)
Output:  Integer (seconds)
```

### derived.depends_on
```
Input:   source.Graph.Edges + source.Graph.Nodes[Type=TRIGGER].Predicate.Conditions
Logic:   edge_deps = resolve_predecessor_job_names_from_edges(source.Graph.Edges, source.Graph.Nodes)
         trigger_deps = extract_job_names_from_conditional_trigger_predicates(source.Graph.Nodes)
         result = union(edge_deps, trigger_deps)
         deduplicate(result)
Output:  Array of { task_key: "predecessor_name" }
```

### derived.total_source_cpu / derived.total_source_memory
```
Input:   source.NumberOfWorkers + lookup.worker_vcpu + lookup.worker_memory
Logic:   total_cpu = source.NumberOfWorkers * lookup.worker_vcpu
         total_memory = source.NumberOfWorkers * lookup.worker_memory
Output:  Integers
```

### derived.total_target_cpu / derived.total_target_memory
```
Input:   source.NumberOfWorkers + lookup.node_vcpu + lookup.node_memory
Logic:   total_cpu = source.NumberOfWorkers * lookup.node_vcpu
         total_memory = source.NumberOfWorkers * lookup.node_memory
Output:  Integers
```

### derived.compute_validation_status
```
Input:   derived.total_source_cpu, derived.total_target_cpu,
         derived.total_source_memory, derived.total_target_memory,
         policy.compute_match_threshold
Logic:   IF target_cpu >= source_cpu AND target_memory >= source_memory → PASS
         IF target_cpu >= (source_cpu * threshold) AND target_memory >= (source_memory * threshold) → WARNING
         ELSE → FAIL
Output:  String ("PASS" | "WARNING" | "FAIL")
```

## Usage in Conversion Flow

1. **Detect workflow type:** Parse JSON/YAML, identify platform markers
2. **Extract structure:** Activities, tasks, dependencies, triggers, parameters
3. **Extract compute specs:** Worker type, worker count, allocated capacity
4. **Map activities:** Use activity mapping tables
5. **Convert parameters:** Transform parameter format
6. **Convert schedule:** Map trigger/schedule to target format
7. **Map compute:** Convert source workers to target node types, validate equivalence
8. **Normalize timeouts:** Convert timeout units, apply layer-specific caps
9. **Generate DAB output:** Wrap in `resources.jobs` structure with `job_clusters`
10. **Validate:** Run full validation pipeline (bundle structure, compute, timeout, dependencies)
11. **Generate reports:** Emit compute_validation_report.md and conversion_validation_report.md

## Example: ADF → Databricks YAML

**Input (ADF):**
```json
{
  "name": "ETL_Pipeline",
  "properties": {
    "activities": [
      {
        "name": "Extract",
        "type": "DatabricksNotebook",
        "typeProperties": {
          "notebookPath": "/bronze/extract"
        }
      },
      {
        "name": "Transform",
        "type": "DatabricksNotebook",
        "typeProperties": {
          "notebookPath": "/silver/transform"
        },
        "dependsOn": [
          { "activity": "Extract", "dependencyConditions": ["Succeeded"] }
        ]
      }
    ]
  }
}
```

**Output (Databricks Asset Bundle YAML):**

Every value below is derived from the input above — not hardcoded.

```yaml
resources:
  jobs:
    etl_pipeline:                                       # from: input.name → sanitized to lowercase
      name: ETL_Pipeline                                 # from: input.name
      email_notifications:
        on_failure: []
      max_concurrent_runs: 1
      tasks:
        - task_key: extract                              # from: input.activities[0].name → lowercase
          notebook_task:
            notebook_path: ${policy.workspace_notebook_root}/extract  # from: input.activities[0].typeProperties.notebookPath
          job_cluster_key: job_cluster_${derived.cluster_tier}   # derived from source compute
          timeout_seconds: ${derived.policy_validated_timeout}   # from: source timeout → policy validated
          max_retries: 0                                  # from: source retry config (default 0)

        - task_key: transform                             # from: input.activities[1].name → lowercase
          notebook_task:
            notebook_path: ${policy.workspace_notebook_root}/transform # from: input.activities[1].typeProperties.notebookPath
          depends_on:
            - task_key: extract                           # from: input.activities[1].dependsOn[0].activity
          job_cluster_key: job_cluster_${derived.cluster_tier}
          timeout_seconds: ${derived.policy_validated_timeout}
          max_retries: 0
      job_clusters:
        - job_cluster_key: job_cluster_${derived.tier}
          new_cluster:
            spark_version: ${derived.spark_runtime}       # mapped from source engine version
            node_type_id: ${derived.node_type_id}        # mapped from source compute specs
            num_workers: ${derived.num_workers}           # from source or default minimum
```

## Databricks Asset Bundle (DAB) Output Structure

When the target is Databricks, the generated YAML **MUST** conform to the Databricks Asset Bundle (DAB) format. The job definition must be nested under `resources.jobs` with exactly one entry.

### Required Structure

All values must be derived from the source workflow input. No hardcoded defaults for task keys, timeouts, compute, or parameters.

```yaml
resources:
  jobs:
    ${source.workflow_name | sanitize_key}:
      name: ${source.workflow_name}
      email_notifications:
        on_failure: []
      timeout_seconds: ${derived.job_level_timeout}                # max of all task timeouts
      max_concurrent_runs: 1
      tasks:
        - task_key: ${source.job_name | sanitize_key}              # from source job/activity name
          notebook_task:
            notebook_path: ${policy.workspace_notebook_root}/${source.job_name}
            base_parameters:                                        # from source job arguments/params
              ${source.param_key}: ${source.param_value}
          timeout_seconds: ${derived.policy_validated_timeout}      # source timeout → converted → capped
          max_retries: ${source.max_retries | default: 0}
          depends_on: ${derived.dependency_list}                    # from source triggers/dependsOn
      job_clusters:
        - job_cluster_key: job_cluster_${derived.cluster_tier}     # tier derived from source worker type
          new_cluster:
            spark_version: ${derived.spark_runtime}                 # mapped from source engine version
            node_type_id: ${derived.node_type_id}                  # mapped from source worker type via compute table
            num_workers: ${source.number_of_workers}                # from source worker count
      tags:
        environment: production
        source_platform: ${source.platform}                         # detected source platform
        converted: "true"
```

### Structure Rules

1. **Exactly one entry** under `resources.jobs` — the job name key
2. Each task references either `job_cluster_key` (preferred) or `existing_cluster_id`
3. `job_clusters` array defines ephemeral clusters with compute config derived from source
4. Top-level `timeout_seconds` sets job-level timeout; per-task `timeout_seconds` sets task-level timeout
5. `format: MULTI_TASK` is implicit in DAB and must NOT be included
6. **No hardcoded values** — every field value must be traceable to a source input field or a derived computation
7. **Task type exclusivity** — each task must define exactly one of: `notebook_task`, `spark_python_task`, `spark_jar_task`, `sql_task`, `run_job_task`. Multiple task types in the same task definition are invalid.
8. **Cluster reference integrity** — every `job_cluster_key` referenced by a task must exist in the `job_clusters[]` array

### Input-to-Output Field Mapping

All output values must resolve from the source input. The converter must not inject hardcoded task keys, timeouts, worker counts, node types, or Spark versions.

**Glue Workflow → DAB field mapping:**

| DAB Output Field | Source Field (Glue JSON Path) | Derivation |
|-----------------|-------------------------------|-----------|
| `resources.jobs.<key>` | `Workflow.Name` | Sanitize to lowercase, replace spaces with `_` |
| `name` | `Workflow.Name` | Direct |
| `tasks[].task_key` | `Graph.Nodes[Type=JOB].Name` | Sanitize to lowercase |
| `tasks[].notebook_task.notebook_path` | `Graph.Nodes[Type=JOB].Name` | Prefix with `/Workspace/Pipelines/`, suffix `_databricks` |
| `tasks[].base_parameters` | `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].Arguments` | Strip `--` prefix from keys |
| `tasks[].timeout_seconds` | `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].Timeout` | Multiply by 60, then apply layer timeout cap |
| `tasks[].max_retries` | `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].MaxRetries` | Direct (default: 0) |
| `tasks[].depends_on` | `Graph.Nodes[Type=TRIGGER].TriggerDetails.Trigger.Predicate.Conditions` AND `Graph.Edges` | Union of edge-resolved predecessors + CONDITIONAL trigger job names, deduplicated |
| `job_clusters[].node_type_id` | `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].WorkerType` | Map via Glue Worker → Databricks Node Type table |
| `job_clusters[].num_workers` | `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].NumberOfWorkers` | Direct |
| `job_clusters[].spark_version` | `Graph.Nodes[Type=JOB].JobDetails.JobRuns[0].GlueVersion` | Map via Glue Version → Spark Runtime table |

**ADF/Synapse → DAB field mapping:**

| DAB Output Field | Source Field (ADF JSON Path) | Derivation |
|-----------------|------------------------------|-----------|
| `resources.jobs.<key>` | `name` | Sanitize to lowercase |
| `name` | `name` | Direct |
| `tasks[].task_key` | `properties.activities[].name` | Sanitize to lowercase |
| `tasks[].notebook_task.notebook_path` | `properties.activities[].typeProperties.notebookPath` | Prefix with `/Workspace/Pipelines/` if not absolute |
| `tasks[].base_parameters` | `properties.activities[].typeProperties.baseParameters` | Direct key-value mapping |
| `tasks[].depends_on` | `properties.activities[].dependsOn[].activity` | Extract activity names |
| `schedule` | `properties.triggers[]` | Convert ADF recurrence to quartz cron |

### Glue Version → Spark Runtime Mapping

| Glue Version | Spark Version | Databricks Runtime |
|-------------|---------------|-------------------|
| 2.0 | Spark 2.4 | 7.3.x-scala2.12 |
| 3.0 | Spark 3.1 | 10.4.x-scala2.12 |
| 4.0 | Spark 3.3 | 13.3.x-scala2.12 |
| 5.0 | Spark 3.5 | 14.3.x-scala2.12 |

### Flat-to-DAB Migration

If the converter previously generated flat format:
```yaml
# INCORRECT (flat format)
name: job_name
tasks:
  - task_key: ...
```

It must be wrapped into DAB:
```yaml
# CORRECT (DAB format)
resources:
  jobs:
    job_name:
      name: job_name
      tasks:
        - task_key: ...
      job_clusters:
        - ...
```

## Compute Conversion Validation (AWS Glue → Databricks)

When converting from AWS Glue, the framework must validate that the target Databricks cluster provides equivalent or greater compute capacity.

### Glue Worker Specifications

| Worker Type | Memory | vCPU | Disk |
|------------|--------|------|------|
| Standard | 16 GB | 4 vCPU | 50 GB |
| G.1X | 16 GB | 4 vCPU | 64 GB |
| G.2X | 32 GB | 8 vCPU | 128 GB |
| G.4X | 64 GB | 16 vCPU | 256 GB |
| G.8X | 128 GB | 32 vCPU | 512 GB |
| Z.2X | 64 GB | 8 vCPU | 128 GB |

### Databricks Node Type Recommendations

| Glue Worker Type | Databricks Node Type (Azure) | Databricks Node Type (AWS) |
|-----------------|------------------------------|----------------------------|
| Standard / G.1X | Standard_DS3_v2 (14 GB, 4 vCPU) | m5.xlarge (16 GB, 4 vCPU) |
| G.2X | Standard_DS4_v2 (28 GB, 8 vCPU) | m5.2xlarge (32 GB, 8 vCPU) |
| G.4X | Standard_DS5_v2 (56 GB, 16 vCPU) | m5.4xlarge (64 GB, 16 vCPU) |
| G.8X | Standard_E32s_v3 (256 GB, 32 vCPU) | r5.8xlarge (256 GB, 32 vCPU) |

### Conversion Formula

```
databricks_workers = glue_workers
total_source_cpu = glue_workers * worker_type_vcpu
total_source_memory = glue_workers * worker_type_memory_gb
total_target_cpu = databricks_workers * node_type_vcpu
total_target_memory = databricks_workers * node_type_memory_gb
```

### Validation Logic

Compute validation must run **per shared cluster**, checking that the cluster capacity meets the **largest task requirement** assigned to it (since multiple tasks share the same cluster).

```
For each job_cluster in job_clusters:
    assigned_tasks = tasks where task.job_cluster_key == job_cluster.job_cluster_key
    max_source_cpu = max(source_cpu for each assigned_task)
    max_source_memory = max(source_memory for each assigned_task)

    target_cpu = job_cluster.num_workers * lookup.node_vcpu
    target_memory = job_cluster.num_workers * lookup.node_memory

    IF target_cpu >= max_source_cpu AND target_memory >= max_source_memory:
        status = PASS
    ELIF target_cpu >= (max_source_cpu * policy.compute_match_threshold)
         AND target_memory >= (max_source_memory * policy.compute_match_threshold):
        status = WARNING ("Target capacity within {threshold*100}% of source")
    ELSE:
        status = FAIL ("Target capacity significantly below source")
```

### Compute Validation Report Format

The framework must generate `compute_validation_report.md` with values extracted from the source workflow:

```markdown
# Compute Conversion Validation Report

## Source Platform: ${source.platform}
| Job Name | Worker Type | Workers | vCPU/Worker | Memory/Worker | Total vCPU | Total Memory |
|----------|------------|---------|-------------|---------------|------------|--------------|
| ${source.job_name} | ${source.WorkerType} | ${source.NumberOfWorkers} | ${lookup.worker_vcpu} | ${lookup.worker_memory} | ${derived.total_vcpu} | ${derived.total_memory} |

## Target Platform: Databricks
| Task Name | Node Type | Workers | vCPU/Worker | Memory/Worker | Total vCPU | Total Memory |
|-----------|-----------|---------|-------------|---------------|------------|--------------|
| ${derived.task_key} | ${derived.node_type_id} | ${source.NumberOfWorkers} | ${lookup.node_vcpu} | ${lookup.node_memory} | ${derived.target_total_vcpu} | ${derived.target_total_memory} |

## Validation Results
| Job | Source CPU | Target CPU | Source Memory | Target Memory | Status |
|-----|-----------|------------|---------------|---------------|--------|
| ${source.job_name} | ${derived.total_vcpu} | ${derived.target_total_vcpu} | ${derived.total_memory} | ${derived.target_total_memory} | ${derived.validation_status} |
```

**Placeholder resolution:**
- `${source.*}` — Read from the input Glue/ADF workflow JSON
- `${lookup.*}` — Looked up from the Glue Worker Specifications / Databricks Node Type tables above
- `${derived.*}` — Computed (e.g., `total_vcpu = workers * vcpu_per_worker`)

## Timeout Mapping Validation

Converted workflows must enforce layer-specific timeout policies. Timeouts from the source must be converted accurately and then validated against caps.

### Source Timeout Conversion

| Source Platform | Timeout Unit | Conversion |
|----------------|-------------|------------|
| AWS Glue | Minutes | `timeout_seconds = glue_timeout * 60` |
| ADF/Synapse | HH:MM:SS or seconds | Parse and convert to seconds |
| Databricks | Seconds | Direct mapping |

### Layer Timeout Policies

| Pipeline Layer | Max Timeout (seconds) | Max Timeout (hours) |
|---------------|----------------------|---------------------|
| Bronze (ingestion/raw) | 28800 | 8 |
| Silver (cleansed/curated) | 28800 | 8 |
| Gold (aggregated/serving) | 14400 | 4 |

### Layer Detection Logic

Detect the pipeline layer from the job/task name using case-insensitive regex:

| Layer | Regex Pattern | Examples |
|-------|--------------|----------|
| Bronze | `(?i)(bronze\|raw\|landing\|ingest)` | `gen_ai_bronze_full_load`, `raw_extract`, `landing_zone_load` |
| Silver | `(?i)(silver\|clean\|curated\|transform)` | `gen_ai_silver_load`, `curated_merge`, `transform_orders` |
| Gold | `(?i)(gold\|agg\|mart\|serving\|report)` | `gen_ai_gold_load`, `sales_mart`, `report_builder` |
| Default | No match | Apply `policy.layer_timeout.default` (most permissive) |

**Resolution order:** First match wins. If a name matches multiple patterns (e.g., `bronze_to_silver_transform`), the **first matching pattern in order** (Bronze → Silver → Gold) takes precedence.

### Timeout Normalization Logic

```
source_timeout_seconds = convert_to_seconds(source_timeout, source_unit)
layer = detect_layer(job_name)
max_allowed = layer_timeout_policy[layer]

IF source_timeout_seconds > max_allowed:
    adjusted_timeout = max_allowed
    log_warning("Timeout adjusted: {source_timeout_seconds}s → {adjusted_timeout}s. Reason: {layer} pipeline timeout policy")
ELSE:
    adjusted_timeout = source_timeout_seconds
```

### Timeout Validation Report Section

Include in `conversion_validation_report.md` with values from source input:

```markdown
## Timeout Validation
| Task | Source Timeout | Converted Timeout | Layer | Max Allowed | Final Timeout | Status |
|------|---------------|-------------------|-------|-------------|---------------|--------|
| ${source.job_name} | ${source.Timeout} ${source.timeout_unit} | ${derived.converted_seconds}s | ${derived.layer} | ${lookup.layer_max}s | ${derived.final_timeout}s | ${derived.timeout_status} |
```

**Value resolution:**
- `${source.Timeout}` — Raw timeout from source (e.g., `480` for Glue minutes)
- `${source.timeout_unit}` — Unit from source platform (min/sec/HH:MM:SS)
- `${derived.converted_seconds}` — Source timeout converted to seconds (`Timeout * 60` for Glue)
- `${derived.layer}` — Detected from `${source.job_name}` via layer detection logic
- `${lookup.layer_max}` — Max allowed seconds from Layer Timeout Policies table
- `${derived.final_timeout}` — `min(converted_seconds, layer_max)`
- `${derived.timeout_status}` — PASS if unchanged, ADJUSTED if capped

## Workflow Validation Step

Before emitting the final Databricks YAML, execute a validation pipeline with the following checks. All checks must pass or produce documented warnings.

### Validation Checks

| # | Check | Rule | Severity |
|---|-------|------|----------|
| 1 | Bundle structure correctness | `resources.jobs` exists with exactly 1 entry | ERROR |
| 2 | Job name consistency | Key under `resources.jobs` matches `name` field | ERROR |
| 3 | Task key uniqueness | All `task_key` values are unique | ERROR |
| 4 | Dependency validity | All `depends_on` references point to existing `task_key` values | ERROR |
| 5 | Dependency acyclicity | No circular dependencies in task graph | ERROR |
| 6 | Compute equivalence | Target cluster capacity >= `policy.compute_match_threshold` of source | WARNING |
| 7 | Timeout policy compliance | All task timeouts within `policy.layer_timeout` caps | WARNING |
| 8 | Required fields present | `name`, `tasks`, `task_key`, exactly one task type per task | ERROR |
| 9 | Notebook path validity | Paths start with `${policy.workspace_notebook_root}` | WARNING |
| 10 | Parameter completeness | All source parameters mapped to target | WARNING |
| 11 | Cluster reference validity | Every `task.job_cluster_key` exists in `job_clusters[]` | ERROR |
| 12 | Task type exclusivity | Each task defines exactly one execution type | ERROR |

### Validation Severity Levels

- **ERROR**: Conversion output is invalid; must be fixed before deployment
- **WARNING**: Output is functional but may need review; auto-adjusted where possible

### Validation Gate

```
IF any ERROR checks fail:
    status = FAIL
    Do NOT emit workflow YAML until errors fixed
ELIF any WARNING checks triggered:
    status = PASS_WITH_WARNINGS
    Emit workflow YAML with adjustment log
ELSE:
    status = PASS
    Emit workflow YAML
```

## Output Artifacts

For each workflow conversion, the framework must generate:

### 1. Databricks Job Definition (`databricks_job.yml`)
- DAB-compliant YAML with `resources.jobs` structure
- Compute config derived from source with `job_clusters`
- Timeout-policy-normalized task timeouts
- All parameters, dependencies, and notifications mapped

### 2. Compute Validation Report (`compute_validation_report.md`)
- Source compute specs (worker type, count, CPU, memory)
- Target compute specs (node type, count, CPU, memory)
- Per-job comparison with PASS/WARNING/FAIL status

### 3. Conversion Validation Report (`conversion_validation_report.md`)
- Bundle structure validation result
- Compute mapping validation result
- Timeout policy validation result (with adjustment log)
- Task dependency validation result
- Parameter completeness result
- Overall conversion status

**Report format:**
```markdown
# Workflow Conversion Validation Report

**Source:** [platform]
**Target:** Databricks Asset Bundle
**Date:** [date]

## Validation Summary
| Check | Status | Details |
|-------|--------|---------|
| Bundle Structure | PASS/FAIL | ... |
| Compute Mapping | PASS/WARNING/FAIL | ... |
| Timeout Policy | PASS/ADJUSTED | ... |
| Task Dependencies | PASS/FAIL | ... |
| Parameter Completeness | PASS/WARNING | ... |

## Overall Status: [PASS / PASS_WITH_WARNINGS / FAIL]
```

## Error Handling

- **Missing fields:** Provide defaults or mark as MANUAL_REVIEW_REQUIRED
- **Unsupported activity types:** Log warning, create placeholder with TODO comment
- **Complex dependencies:** Simplify to linear or mark for manual review
- **Custom expressions:** Extract as parameters, comment original expression

## Output

For each workflow file, generate:
1. **Converted workflow file:** `<name>_databricks_job.yml` (DAB format)
2. **Compute validation report:** `compute_validation_report.md`
3. **Conversion validation report:** `conversion_validation_report.md`
4. **Mapping report:** Activity mappings, parameters converted, manual review items
