# Workflow Structure Validation

Validates the structural integrity of generated workflow definitions.

## Checks

### WV-STR-001: Valid Syntax
- JSON workflows must parse as valid JSON
- YAML workflows must parse as valid YAML
- **Severity:** ERROR

### WV-STR-002: Required Fields Present
**Databricks DAB:**
- `resources.jobs.<key>.name` must exist
- `resources.jobs.<key>.tasks` must be non-empty array
- Each task must have `task_key`
- Each task must have exactly one of: `notebook_task`, `spark_python_task`, `spark_jar_task`, `sql_task`, `run_job_task`
- **Severity:** ERROR

**ADF Pipeline:**
- `name` must exist
- `properties.activities` must be non-empty array
- Each activity must have `name` and `type`
- **Severity:** ERROR

**Glue Workflow:**
- `Name` must exist
- `Actions` must be non-empty array
- Each action must have `JobName`
- **Severity:** ERROR

### WV-STR-003: DAB Format Compliance
- Job definition must be nested under `resources.jobs`
- Exactly one entry under `resources.jobs`
- `format: MULTI_TASK` must NOT be included (implicit in DAB)
- **Severity:** ERROR

### WV-STR-004: No Hardcoded Values
- Task keys must be derived from source activity/job names
- Timeouts must be derived from source or policy
- Compute configs must be mapped from source
- **Severity:** WARNING

### WV-STR-005: Cluster Reference Integrity
- Every `job_cluster_key` in tasks must exist in `job_clusters[]`
- No orphaned cluster definitions (unused by any task)
- **Severity:** ERROR
