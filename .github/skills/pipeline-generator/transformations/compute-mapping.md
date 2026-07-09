# Compute Resource Mapping

Maps compute specifications between source and target platforms for workflow conversion.

## Glue Worker → Databricks Node Type

| Glue Worker Type | Memory | vCPU | Databricks Node (Azure) | Databricks Node (AWS) |
|-----------------|--------|------|------------------------|----------------------|
| Standard | 16 GB | 4 | Standard_DS3_v2 (14 GB, 4 vCPU) | m5.xlarge (16 GB, 4 vCPU) |
| G.1X | 16 GB | 4 | Standard_DS3_v2 (14 GB, 4 vCPU) | m5.xlarge (16 GB, 4 vCPU) |
| G.2X | 32 GB | 8 | Standard_DS4_v2 (28 GB, 8 vCPU) | m5.2xlarge (32 GB, 8 vCPU) |
| G.4X | 64 GB | 16 | Standard_DS5_v2 (56 GB, 16 vCPU) | m5.4xlarge (64 GB, 16 vCPU) |
| G.8X | 128 GB | 32 | Standard_E32s_v3 (256 GB, 32 vCPU) | r5.8xlarge (256 GB, 32 vCPU) |
| Z.2X | 64 GB | 8 | Standard_E8s_v3 (64 GB, 8 vCPU) | r5.2xlarge (64 GB, 8 vCPU) |

## Cluster Tier Derivation

```
IF WorkerType in [Standard, G.1X] → cluster_tier = "small"
IF WorkerType == "G.2X"           → cluster_tier = "medium"
IF WorkerType == "G.4X"           → cluster_tier = "large"
IF WorkerType == "G.8X"           → cluster_tier = "xlarge"
IF WorkerType == "Z.2X"           → cluster_tier = "medium"
ELSE                              → cluster_tier = "medium" (default)
```

## Compute Validation Formula

```
total_source_cpu = num_workers * worker_vcpu
total_source_memory = num_workers * worker_memory_gb
total_target_cpu = num_workers * node_vcpu
total_target_memory = num_workers * node_memory_gb

IF target >= source → PASS
IF target >= source * 0.8 → WARNING
ELSE → FAIL
```

## ADF Compute → Databricks

ADF does not always specify compute directly (uses linked services). When ADF references:
- **Databricks Linked Service:** Extract cluster config from linked service definition
- **HDInsight:** Map HDInsight node sizes to Databricks equivalents
- **Synapse Spark Pool:** Map pool size to Databricks cluster config

## Shared Clusters

When multiple tasks share the same cluster:
- Size the cluster for the **largest task requirement**
- Validate per-cluster, not per-task
- Use `job_cluster_key` naming: `job_cluster_{tier}`
