# Compute Validation

Validates that target compute configuration provides equivalent or greater capacity than source.

## Checks

### WV-CMP-001: Compute Capacity Match
Validate per shared cluster that target capacity meets source requirements.

```
For each job_cluster:
    assigned_tasks = tasks where task.job_cluster_key matches
    max_source_cpu = max(source_cpu for assigned tasks)
    max_source_memory = max(source_memory for assigned tasks)
    target_cpu = num_workers * node_vcpu
    target_memory = num_workers * node_memory

    PASS: target >= source
    WARNING: target >= source * 0.8
    FAIL: target < source * 0.8
```
**Severity:** WARNING (if within threshold) / ERROR (if below)

### WV-CMP-002: Node Type Valid
- `node_type_id` must be a valid Databricks node type for the target cloud
- Azure nodes must start with `Standard_`
- AWS nodes must match known instance families
- **Severity:** ERROR

### WV-CMP-003: Worker Count Reasonable
- `num_workers` must be > 0
- `num_workers` should not exceed 100 without explicit justification
- **Severity:** WARNING (if > 100)

### WV-CMP-004: Spark Runtime Valid
- `spark_version` must match a valid Databricks runtime
- Format: `X.Y.x-scala2.12` or `X.Y.x-photon-scala2.12`
- **Severity:** ERROR

## Compute Validation Report Template

```markdown
# Compute Conversion Validation Report

## Source Platform: {source_platform}
| Job Name | Worker Type | Workers | vCPU | Memory | Total CPU | Total Mem |
|----------|-----------|---------|------|--------|-----------|-----------|

## Target Platform: {target_platform}
| Task Name | Node Type | Workers | vCPU | Memory | Total CPU | Total Mem |
|-----------|----------|---------|------|--------|-----------|-----------|

## Validation Results
| Job | Source CPU | Target CPU | Source Mem | Target Mem | Status |
|-----|-----------|-----------|-----------|-----------|--------|
```
