# Workflow Conversion Validation Report Template

## Conversion Summary

| Field | Value |
|-------|-------|
| Source Platform | ${source.platform} |
| Source Workflow | ${source.workflow_name} |
| Target Platform | ${target.platform} |
| Target Format | ${target.format} |
| Conversion Date | ${conversion.timestamp} |

## Task Mapping

| # | Source Task | Target Task | Type Mapping | Status |
|---|-----------|-------------|-------------|--------|
| ${index} | ${source.task_name} | ${target.task_key} | ${source.type} → ${target.type} | ${mapping.status} |

## Validation Checks

### Structure Validation
| Check | Status | Details |
|-------|--------|---------|
| Valid syntax | ${check.syntax} | ${check.syntax_details} |
| Required fields | ${check.fields} | ${check.fields_details} |
| DAB compliance | ${check.dab} | ${check.dab_details} |
| Cluster references | ${check.clusters} | ${check.clusters_details} |

### Dependency Validation
| Check | Status | Details |
|-------|--------|---------|
| Acyclic graph | ${check.acyclic} | ${check.acyclic_details} |
| Valid references | ${check.refs} | ${check.refs_details} |
| Order preserved | ${check.order} | ${check.order_details} |
| Edge count match | ${check.edges} | Source: ${source.edge_count}, Target: ${target.edge_count} |

### Timeout Validation
| Task | Source Timeout | Converted | Policy Cap | Final | Status |
|------|--------------|-----------|-----------|-------|--------|
| ${task.name} | ${source.timeout} | ${derived.timeout_seconds} | ${policy.layer_cap} | ${derived.policy_validated_timeout} | ${timeout.status} |

### Compute Validation
| Metric | Source | Target | Status |
|--------|--------|--------|--------|
| Total CPU | ${source.total_cpu} | ${target.total_cpu} | ${compute.cpu_status} |
| Total Memory | ${source.total_memory} | ${target.total_memory} | ${compute.memory_status} |

## Overall Result

- **Structure:** ${overall.structure}
- **Dependencies:** ${overall.dependencies}
- **Timeouts:** ${overall.timeouts}
- **Compute:** ${overall.compute}
- **Overall Status:** ${overall.status}
