# Compute File Platform Detection

Detects the source cloud platform for compute files (.ipynb, .py, .sql) by scanning for platform-specific indicators.

## Supported Platforms

| Platform | Key Indicators |
|----------|---------------|
| AWS Glue | GlueContext, DynamicFrame, getResolvedOptions, s3://, boto3, job.commit() |
| Azure Synapse | mssparkutils, abfss://, wasbs://, pre-initialized spark |
| Databricks | dbutils.widgets, dbfs:/, dbutils.secrets |
| GCP Dataproc | google.cloud imports, gs:// paths, BigQuery format |

## Detection Algorithm

1. Scan file content for all platform indicators
2. Count matches per platform
3. Platform with highest match count = detected source
4. **Tiebreaker priority:** context initialization > storage paths > imports

## Detection Priority Order

When indicator counts are tied or ambiguous, apply this strict priority:

| Priority | Platform | Decisive Indicators |
|----------|----------|--------------------|
| 1 (highest) | AWS Glue | `GlueContext`, `DynamicFrame`, `getResolvedOptions`, `job.commit()` — these are Glue-exclusive |
| 2 | Microsoft Fabric | `notebookutils`, `onelake.dfs.fabric.microsoft.com`, `sempy` — Fabric-exclusive; takes priority over Synapse |
| 3 | Azure Synapse | `mssparkutils` without Fabric indicators, `synapsesql`, `TokenLibrary` |
| 4 | Databricks | `dbutils.widgets`, `dbutils.secrets`, `dbfs:/` |
| 5 | GCP Dataproc | `google.cloud`, `gs://`, `BigQueryClient` |
| 6 (lowest) | AWS EMR | `SparkSession.builder`, `s3://`, `boto3` — only when no higher-priority indicators match |

**Rules:**
- If `GlueContext` or `DynamicFrame` is present → always Glue, regardless of other indicators
- If `notebookutils` or `onelake.dfs.fabric.microsoft.com` is present → always Fabric, not Synapse
- If `mssparkutils` is present without Fabric indicators → Synapse
- `s3://` and `boto3` alone are insufficient for EMR — require absence of Glue indicators
- `SparkSession.builder` appears in both EMR and Dataproc; use storage prefix (`s3://` vs `gs://`) as tiebreaker

## AWS Glue Indicators (Strong)

```
from awsglue.context import GlueContext
glueContext = GlueContext(sc)
getResolvedOptions
DynamicFrame
job.commit()
s3://
import boto3
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from awsglue.dynamicframe import DynamicFrame
from awsglue.job import Job
```

## Azure Synapse Indicators (Strong)

```
from notebookutils import mssparkutils
mssparkutils.credentials
mssparkutils.fs
abfss://
wasbs://
# Pre-initialized spark (no GlueContext, no SparkSession.builder)
```

## Databricks Indicators (Strong)

```
dbutils.widgets
dbutils.widgets.text
dbutils.widgets.get
dbfs:/
dbutils.secrets.get
dbutils.fs
# Pre-initialized spark
```

## GCP Dataproc Indicators (Strong)

```
from google.cloud import bigquery
from google.cloud import storage
gs://
BigQueryClient
google.auth
```

## File Format Detection

| Extension | Type | Processing |
|-----------|------|-----------|
| `.py` | Python script | Scan full file content |
| `.ipynb` | Jupyter notebook | Extract cells from JSON, scan all code cells |
| `.sql` | SQL script | Scan for platform-specific SQL extensions |

## Migration Mode Determination

After detecting source platform:

| Condition | Mode | Action |
|-----------|------|--------|
| Source cloud != Target cloud | CROSS_CLOUD | Full conversion (imports, paths, APIs, secrets) |
| Source cloud = Target cloud, engine differs | SAME_CLOUD_ENGINE | Engine-specific adaptations only |

## Output

Returns per file:
- `source_platform`: AWS Glue | Azure Synapse | Databricks | GCP Dataproc
- `file_format`: .py | .ipynb | .sql
- `migration_mode`: CROSS_CLOUD | SAME_CLOUD_ENGINE
- `detection_confidence`: HIGH (3+ indicators) | MEDIUM (2) | LOW (1)
- `source_adapter`: resolved adapter path (`adapters/source/{source_platform}.yaml`)
