# Compute Conversion Validation Report Template

## Source Platform: ${source.platform}

| Job Name | Worker Type | Workers | vCPU/Worker | Memory/Worker | Total vCPU | Total Memory |
|----------|-----------|---------|-------------|---------------|------------|--------------|
| ${source.job_name} | ${source.worker_type} | ${source.num_workers} | ${lookup.worker_vcpu} | ${lookup.worker_memory} | ${derived.total_source_cpu} | ${derived.total_source_memory} |

## Target Platform: ${target.platform}

| Task Name | Node Type | Workers | vCPU/Worker | Memory/Worker | Total vCPU | Total Memory |
|-----------|----------|---------|-------------|---------------|------------|--------------|
| ${derived.task_key} | ${derived.node_type_id} | ${source.num_workers} | ${lookup.node_vcpu} | ${lookup.node_memory} | ${derived.total_target_cpu} | ${derived.total_target_memory} |

## Validation Results

| Job | Source CPU | Target CPU | Source Memory | Target Memory | Status |
|-----|-----------|-----------|---------------|---------------|--------|
| ${source.job_name} | ${derived.total_source_cpu} | ${derived.total_target_cpu} | ${derived.total_source_memory} | ${derived.total_target_memory} | ${derived.compute_status} |

## Summary

- **Compute Match Threshold:** ${policy.compute_match_threshold * 100}%
- **Overall Status:** ${derived.overall_compute_status}
- **Recommendations:** ${derived.compute_recommendations}
