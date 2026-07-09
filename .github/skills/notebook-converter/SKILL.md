---
name: notebook-converter
description: Intelligent cloud data pipeline converter that auto-detects source platform (AWS Glue/Azure Synapse/Databricks/GCP Dataproc), converts notebooks and scripts to target platform with service mapping, path translation, and API conversion. Routes to platform-specific adapters dynamically.
---

# Notebook Converter

Converts cloud data pipeline notebooks and scripts between AWS, Azure, and GCP platforms with automatic source detection, config-driven target selection, and dynamic adapter routing.

## Mission

**Migrate data pipelines from one platform to another without changing data schema, data modelling, business logic, or data semantics. Only the platform layer changes. Everything else is preserved exactly.**

Reference: `transformations/lift-and-shift-mission.md` — the authoritative contract for what changes and what never changes during conversion.

## Adapter-Based Conversion Engine

Conversion is driven by a **generic adapter engine** with zero hardcoded platform-to-platform mappings. The engine dynamically loads source and target adapter YAML files based on the conversion plan.

### Architecture

```
conversion-plan.md → parse plan → for each file:
  load adapters/source/{source_adapter}.yaml
  load adapters/target/{target_adapter}.yaml
  load transformations/{transformation}.md
  → source.read() → transformation.apply() → target.write()
  → generate converted notebook
```

### Available Adapters

**Source Adapters** (`adapters/source/`):
| Adapter | Platform | Detects |
|---------|----------|---------|
| `glue.yaml` | AWS | GlueContext, DynamicFrame, s3://, boto3 |
| `synapse.yaml` | Azure | mssparkutils, abfss://, synapsesql |
| `databricks.yaml` | Multi-Cloud | dbutils.widgets, dbfs:/, dbutils.secrets |
| `emr.yaml` | AWS | SparkSession.builder, s3://, hdfs://, hive |
| `dataproc.yaml` | GCP | gs://, google.cloud, bigquery |
| `fabric.yaml` | Azure | notebookutils, onelake.dfs.fabric.microsoft.com, sempy, lakehouse |
| `postgresql.yaml` | Database | SERIAL, ::text, ON CONFLICT, JSONB, ILIKE |

**Target Adapters** (`adapters/target/`):
| Adapter | Platform | Output Format |
|---------|----------|---------------|
| `databricks.yaml` | Multi-Cloud | .ipynb |
| `synapse.yaml` | Azure | .ipynb |
| `emr.yaml` | AWS | .py |
| `fabric.yaml` | Azure | .ipynb |
| `bigquery.yaml` | GCP | .py |

**Total Supported Routes:** 7 source × 5 target = 35 combinations (zero hardcoded mappings)

### Engine References

- `execution/engine.md` — Generic execution engine (orchestrator)
- `core/adapter-loader.md` — Adapter discovery, YAML schema, validation rules
- `core/plan-parser.md` — Conversion plan parsing rules
- `transformations/lift-and-shift.md` — Pass-through transformation strategy
- `transformations/sql-ddl.md` — SQL DDL/DML conversion rules (PostgreSQL, MySQL, SQL Server → Spark SQL / Delta)

### Plan Integration

- If a conversion plan exists at `.propel/context/pipelines/conversion-plan.md`, read the `source_adapter`, `target_adapter`, and `transformation` fields per file.
- If no plan exists, run detection dynamically using `detection/compute-detection.md`.

### Conversion Plan Strategy Format

```
Conversion Strategy:
  source_adapter: <platform>
  target_adapter: <platform>
  transformation: lift_and_shift
```

### Each Adapter YAML Contains

- Detection indicators (source only)
- Connection parameters
- Read logic / Write logic (spark, python, sql)
- Import rules (remove for source, add for target)
- Parameter extraction/definition patterns
- Secret retrieval method
- Storage path prefix and format
- Catalog operation mappings
- Notebook output format (target only)

### Extensibility

To add a new platform: create one `.yaml` file in `adapters/source/` or `adapters/target/`. No engine changes needed.

### Databricks Enhancements (Post-Conversion)

**Reference:** `detection/databricks-enhancements.md` — Used for optional Databricks-specific enhancement detection (Auto Loader, DLT, Z-Order, etc.) applied AFTER adapter-based conversion.

## Core Capabilities

- **Auto-detect source**: AWS Glue, Azure Synapse, Databricks
- **Cross-cloud migration**: AWS ↔ Azure
- **Same-cloud engine adaptation**: Synapse → Databricks, Glue → EMR, etc.
- **Service mapping**: Glue ↔ Synapse, S3 ↔ ADLS, IAM ↔ RBAC
- **Path translation**: s3:// → abfss:// and reverse
- **API conversion**: DynamicFrame ↔ DataFrame, boto3 ↔ mssparkutils
- **Notebook conversion**: Complete .ipynb cell extraction and conversion
- **Format output**: .py, .ipynb, .sql

## Detection Logic

**All detection logic is defined in modular detection files. Use these files as the single source of truth:**

### Compute File Detection
**File:** `detection/compute-detection.md`

Detects source platform for `.ipynb`, `.py`, `.sql` files by scanning for platform indicators:
- AWS Glue (GlueContext, DynamicFrame, s3://, boto3)
- Azure Synapse (mssparkutils, abfss://, pre-initialized spark)
- Databricks (dbutils.widgets, dbfs:/, dbutils.secrets)
- GCP Dataproc (google.cloud imports, gs://)

Returns: `source_platform`, `file_format`, `migration_mode`, `detection_confidence`, `source_adapter` (resolved from `adapters/source/{source_platform}.yaml`)

### Workflow File Detection
**File:** `detection/workflow-detection.md`

Detects orchestration platform for `.json`, `.yaml`, `.yml` files by inspecting structural markers:
- Azure Data Factory / Synapse Pipeline
- AWS Glue Workflow
- Databricks Workflow
- AWS Step Functions

Returns: `workflow_type`, `file_format`, `marker_count`, `detection_confidence`

**Usage:** Load the appropriate detection file and apply its rules. Do not duplicate detection logic in this file.

## Migration Modes

### Mode A: Cross-Cloud Migration (AWS ↔ Azure)
- Source contains "AWS" and Target Cloud = "Azure" → Cross-cloud
- Source contains "Azure"/"Synapse" and Target Cloud = "AWS" → Cross-cloud
- Route to appropriate source/target adapter pair via `adapters/source/*.yaml` and `adapters/target/*.yaml`

### Mode B: Same-Cloud Engine Adaptation
- Source and Target are on the same cloud but different engines
- Skip cloud conversion, load target adapter and apply engine-specific adaptations only

## Platform Native Capability Detection

Before generating target code, the converter must detect runtime objects that are **already available by default on the target platform**. If such capabilities exist, the converter must **avoid recreating or overloading them**.

### Detection Rule

```
IF target_platform provides runtime capability X by default
AND source code manually initializes capability X
THEN remove initialization and use platform-provided instance
```

### Platform Capability Mapping

| Capability | AWS Glue | Databricks | Synapse | EMR | Fabric |
|---|---|---|---|---|---|
| SparkSession | Manual creation required | Pre-initialized as `spark` | Pre-initialized as `spark` | Manual creation required | Pre-initialized as `spark` |
| SparkContext | Manual | Already exists | Already exists | Manual | Already exists |
| Utilities | boto3 | dbutils | mssparkutils | boto3 | mssparkutils |
| Secrets | boto3 secretsmanager | dbutils.secrets | mssparkutils.credentials | boto3 secretsmanager | mssparkutils.credentials |
| Filesystem | boto3 S3 API | dbutils.fs | mssparkutils.fs | HDFS / S3A | mssparkutils.fs |

### Spark Session Normalization

#### Source Pattern Detection

Detect manual Spark initialization patterns:

```
SparkSession.builder
SparkSession.builder.getOrCreate()
SparkSession.builder.config(...).getOrCreate()
SparkContext()
GlueContext(sc)
glueContext.spark_session
```

#### Conversion Rules

**Glue / EMR → Databricks / Synapse / Fabric:**

Remove:
```python
spark = SparkSession.builder.getOrCreate()
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
```

Replace with:
```python
# SparkSession already provided by the platform
```

Use the pre-existing `spark` variable directly.

**Databricks / Synapse / Fabric → Glue:**

Add Spark initialization:
```python
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
```

**Databricks / Synapse / Fabric → EMR:**

Add Spark initialization:
```python
spark = SparkSession.builder \
    .appName("job_name") \
    .getOrCreate()
```

#### Config Migration

If the source embeds Spark config inside the builder chain:
```python
spark = SparkSession.builder.config("spark.sql.shuffle.partitions", 200).getOrCreate()
```

And the target platform pre-initializes SparkSession, extract the config and apply it separately:
```python
# SparkSession already provided by the platform
spark.conf.set("spark.sql.shuffle.partitions", 200)
```

### Converter Pipeline Stages

The conversion pipeline must execute these stages in order:

```
1. Detect source platform
2. Extract code / cells
3. Identify runtime capabilities (match against Platform Capability Mapping)
4. Remove redundant initialization (SparkSession, SparkContext, platform utilities)
5. Extract embedded Spark configs from builder chains
6. Apply platform conversion rules (imports, paths, APIs, secrets)
7. Re-apply extracted Spark configs via spark.conf.set (if target pre-initializes session)
8. Generate target code / notebook
9. [DATABRICKS TARGET ONLY] Run Databricks Enhancement Detection (see below)
```

## Databricks-Specific Enhancement Detection (Post-Conversion)

**Applies only when target platform is Databricks.**

After the standard conversion completes, run an additional detection pass to identify enhancements across THREE categories:
1. **Notebook Enhancements** — Databricks-native features (Auto Loader, DLT, Z-Order, etc.)
2. **Layer-Specific Enhancements** — Bronze, Silver, Gold layer improvements
3. **Workflow YAML Enhancements** — Job-level improvements (autoscaling, retry, alerts, tags, policies)

This step is **interactive** — the user must opt in via terminal prompt before any enhancements are applied.

### Enhancement Detection Flow

```
IF target_platform == "Databricks":
    1. Scan converted NOTEBOOKS against notebook enhancement rules
       (defined in detection/databricks-enhancements.md — Section A)
    2. Detect pipeline layer per notebook (Bronze/Silver/Gold) and scan against layer rules
       (defined in detection/databricks-enhancements.md — Sections C, D, E)
    3. Scan converted WORKFLOW YAML against workflow enhancement rules
       (defined in detection/databricks-enhancements.md — Section B)
    4. Collect applicable_enhancements = [all that passed detection + threshold]
    5. IF len(applicable_enhancements) > 0:
         → Print categorized enhancement summary to terminal
         → Ask user: "Approve / Skip / Select specific items"
         → IF user responds approve/yes/proceed:
              Apply ALL enhancement transformations
         → IF user responds skip/no:
              Skip enhancements, proceed with standard output
         → IF user specifies numbers (e.g., "1, 3, 5"):
              Apply ONLY selected enhancements
    6. IF len(applicable_enhancements) == 0:
         → Print: "No Databricks-specific enhancements are required."
         → Proceed to anti-pattern fixer / optimizer
```

### Supported Enhancements

**Notebook Enhancements (Section A):**

| Feature | Enhancement | When Applicable |
|---------|-------------|----------------|
| Auto Loader (`cloudFiles`) | Incremental file ingestion with exactly-once guarantees | File reads from cloud storage directories in recurring pipelines |
| Delta Live Tables (DLT) | Declarative ETL with built-in data quality and dependency management | Multi-table medallion pipelines (3+ tables, bronze→silver→gold) |
| Z-Order Clustering | Optimized data layout for filtered/joined queries | Delta writes with identifiable high-cardinality filter/join columns |
| OPTIMIZE (Compaction) | Small file compaction for read performance | Delta append writes that produce many small files |
| COPY INTO | Idempotent file loading preventing duplicate processing | File→Delta append pattern without Auto Loader |
| Change Data Feed (CDF) | Row-level change tracking for downstream consumers | MERGE/upsert operations on Delta tables |
| Liquid Clustering | Automatic data organization (modern Z-Order replacement) | New Delta tables with evolving query patterns |

**Layer-Specific Enhancements (Sections C, D, E):**

| Layer | Enhancement | When Applicable |
|-------|-------------|----------------|
| Bronze | Bad Records Handling | CSV/JSON reads without badRecordsPath |
| Bronze | Error Table | Validation filters dropping records without error capture |
| Bronze | Partitioning Strategy | Delta writes without partitionBy on date columns |
| Bronze | Audit Columns | File reads without _ingest_timestamp, _source_file |
| Silver | Schema Evolution Control | Delta appends without mergeSchema handling |
| Silver | Primary Key Validation | dropDuplicates without PK uniqueness enforcement |
| Silver | CDC Watermark Validation | Incremental loads without watermark column validation |
| Silver | SCD Audit Columns | MERGE/upsert without _created_on, _modified_on |
| Silver | Skew Handling (AQE) | JOIN operations without AQE enabled |
| Silver | Data Drift Monitoring | External source reads without schema drift detection |
| Gold | Business Rule Validation | Aggregation output without domain checks |
| Gold | Aggregation Reconciliation | Gold aggregation without Silver vs Gold count comparison |
| Gold | SCD1 Audit Logging | Overwrite mode without overwrite history logging |
| Gold | Serving Layer Optimization | Gold tables without autoOptimize properties |

**Workflow YAML Enhancements (Section B):**

| Enhancement | What It Adds | When Applicable |
|-------------|-------------|----------------|
| Autoscaling | Dynamic cluster scaling (min/max workers) | Fixed num_workers >= 2 without autoscale |
| Retry Logic | max_retries + min_retry_interval_millis | Tasks with max_retries: 0 |
| Alerts & Notifications | Email/webhook on failure | Empty on_failure notification list |
| Cluster Policies | Governance policy_id attachment | No policy_id in cluster definitions |
| Job Tags | owner, team, cost_center metadata | Missing cost tracking tags |

### Detection and Transformation Rules

Full detection logic, applicability thresholds, code transformation patterns, conflict resolution, and validation checks are defined in:

**Reference:** `detection/databricks-enhancements.md`

### Rules
- Only list enhancements that passed BOTH detection AND applicability threshold
- Group by category in the prompt: Notebook → Layer-Specific → Workflow YAML
- If zero enhancements are applicable across all categories, inform the user and proceed
- Do NOT apply enhancements without user confirmation
- Accept: `approve`, `yes`, `y`, `proceed` → apply ALL enhancements
- Accept: `no`, `n`, `skip` → skip ALL, continue with standard output
- Accept: specific numbers → apply only selected items (e.g., "1, 3, 5")
- Resolve feature conflicts per the conflict table in `detection/databricks-enhancements.md`

### Redundant Initialization Validation

After conversion, validate the output against these rules:

| Check | Rule | Severity |
|---|---|---|
| SparkSession initialization | Do not create if target platform provides it | WARNING |
| SparkContext initialization | Remove if target platform manages it | WARNING |
| Platform utility mixing | Do not mix dbutils + boto3 + mssparkutils in one file | ERROR |
| Builder-chain configs lost | Ensure Spark configs from builder chain are preserved via `spark.conf.set` | WARNING |

## Platform Conversion Rules

All platform-specific conversion rules (imports, initialization, storage paths, catalog operations, parameters, secrets, finalization) are now defined in **adapter YAML files**:

- **Source adapters** (`adapters/source/*.yaml`) — define what to remove/detect
- **Target adapters** (`adapters/target/*.yaml`) — define what to add/generate
- **Transformations** (`transformations/*.md`) — define the conversion strategy

The execution engine (`execution/engine.md`) applies these rules generically. See `core/adapter-loader.md` for the full YAML schema.

**No inline conversion rules are needed in this file.** All platform knowledge is externalized to adapter YAML files.

## Script → Notebook Conversion Flow Preservation

**CRITICAL: Preserve the original script's logical flow when converting to notebooks.**

### Flow Preservation Rules
1. **DO NOT reorganize** the script into arbitrary sections (e.g., "Configuration & Parameters", "Imports & Initialization", etc.)
2. **Maintain exact logical sequence** from the source script
3. **Keep sections together** as they appear in the original (e.g., if imports follow parameters in source, keep that order)
4. **Minimal markdown headers** — only add a header at the very top with conversion metadata
5. **Code blocks follow source order** — each logical block becomes one cell in the same sequence

### Conversion Pattern for .py → .ipynb

**For Python Scripts:**
1. Create **one markdown cell at top** with file metadata (source, target, purpose)
2. Convert the entire script into **code cells** that follow the **exact flow** of the original
3. Split into cells only at natural boundaries (function definitions, main processing blocks, history writes)
4. **DO NOT** add section headers like "## Imports", "## Configuration", etc. unless they exist as comments in the source

**Example:**
```
Original .py:
  import statements
  args = getResolvedOptions(...)
  spark context init
  function definitions
  config loading
  main processing loop
  history writes

Converted .ipynb:
  Cell 1: [markdown] "# Pipeline Name - Conversion metadata"
  Cell 2: [code] Widget parameters (converted from args)
  Cell 3: [code] Imports
  Cell 4: [code] Spark initialization
  Cell 5: [code] Function definitions
  Cell 6: [code] Config loading
  Cell 7: [code] Main processing loop
  Cell 8: [code] History writes
```

**DO NOT reorganize into:**
```
  WRONG:
  Cell 1: ## Configuration & Parameters
  Cell 2: ## Imports & Initialization  
  Cell 3: ## Utility Functions
  Cell 4: ## Schema Definitions
  Cell 5: ## Load Configuration
  ...
```

## Notebook Cell Extraction

**CRITICAL for .ipynb files:**

1. Extract **ALL cells** from notebook JSON (`notebook["cells"]`)
2. Preserve **ALL code cells** — every single code block
3. Convert markdown cells → Python comments (`# ===` section headers) OR preserve as markdown cells if they contain important documentation
4. Maintain sequential execution order
5. Apply platform conversions to EVERY code line
6. Keep ALL business logic, joins, aggregations, transformations

**Conversion process:**
```
For each cell in notebook["cells"]:
  if cell_type == "markdown":
    → Preserve as markdown OR convert to # comments if just section headers
  if cell_type == "code":
    → Extract all lines from cell["source"]
    → Apply platform conversions
    → Write with blank line separator
```

## Engine-Specific Adaptations

### Databricks (AWS/Azure)
- **Parameters:** `dbutils.widgets.text("name", "", "Label")` / `dbutils.widgets.get("name")`
- **Secrets:** `dbutils.secrets.get(scope="scope", key="key")`
- **Files:** `dbutils.fs.ls("path")`, `dbutils.fs.cp("src", "dest")`
- **Storage (AWS):** `s3://` or `/mnt/` or `dbfs:/mnt/`
- **Storage (Azure):** `abfss://` or `/mnt/`
- **Remove:** GlueContext, mssparkutils

### Azure Synapse
- **Utilities:** `from notebookutils import mssparkutils`
- **Secrets:** `mssparkutils.credentials.getSecret("vault", "key")`
- **Files:** `mssparkutils.fs.ls("abfss://...")`, `mssparkutils.fs.exists("path")`
- **Storage:** `abfss://container@storage.dfs.core.windows.net/path/`
- **Remove:** GlueContext, dbutils

### AWS Glue
- **Context:** Full GlueContext initialization (see above)
- **I/O:** DynamicFrames for catalog, DataFrame for S3
- **Job commit:** `job.commit()` at end
- **Bookmarks:** `transformation_ctx="unique_name"` on each operation
- **Remove:** mssparkutils, dbutils

### AWS EMR
- **Session:** Standard `SparkSession.builder` with EMR configs
- **S3 optimization:** `spark.hadoop.fs.s3a.fast.upload`, `multipart.size`, `connection.maximum`
- **EMRFS:** `spark.hadoop.fs.s3.consistent = true`
- **Remove:** GlueContext, mssparkutils, dbutils

### Azure Fabric
- **Lakehouse:** `spark.read.format("delta").load("Tables/table_name")`
- **Write:** `df.write.format("delta").mode("overwrite").save("Tables/table_name")`
- **Secrets:** `mssparkutils.credentials.getSecret("vault", "key")`

## Metadata Conversion

**AWS notebook metadata:**
```json
{ "kernelspec": { "display_name": "Glue PySpark", "name": "glue_pyspark" } }
```

**Azure notebook metadata:**
```json
{ "kernelspec": { "display_name": "Python 3", "name": "python3" } }
```

## Pipeline Connection JSON Parsing

### Supported Connection JSON Formats

#### Azure Data Factory (ADF) / Synapse Pipeline JSON
**Detection**: Look for `"properties"` → `"activities"` array, `"type": "Microsoft.DataFactory/factories/pipelines"`
```json
{
  "name": "pipeline_name",
  "properties": {
    "activities": [
      {
        "name": "activity_name",
        "type": "Copy|DatabricksNotebook|SparkJob|ExecutePipeline|WebActivity|...",
        "typeProperties": { ... },
        "linkedServiceName": { "referenceName": "...", "type": "LinkedServiceReference" },
        "inputs": [{ "referenceName": "...", "type": "DatasetReference" }],
        "outputs": [{ "referenceName": "...", "type": "DatasetReference" }],
        "dependsOn": [{ "activity": "...", "dependencyConditions": ["Succeeded"] }]
      }
    ],
    "parameters": { ... },
    "annotations": []
  }
}
```

**Extract:**
- `activities[]` → Activity graph (name, type, dependencies, inputs, outputs)
- `linkedServiceName` → Connection/credential references
- `datasets` (inputs/outputs) → Source/sink definitions
- `parameters` → Pipeline parameters
- `dependsOn` → Activity execution order (DAG)

#### AWS Glue Workflow JSON
**Detection**: Look for `"Actions"` array, `"Triggers"` array, `"Crawlers"` array
```json
{
  "Name": "workflow_name",
  "Actions": [
    { "JobName": "glue_job_name", "Arguments": { "--key": "value" } }
  ],
  "Triggers": [
    { "Name": "trigger_name", "Type": "SCHEDULED|ON_DEMAND|CONDITIONAL", "Schedule": "cron(...)" }
  ],
  "Crawlers": [
    { "Name": "crawler_name", "DatabaseName": "db", "Targets": { "S3Targets": [{ "Path": "s3://..." }] } }
  ]
}
```

**Extract:**
- `Actions[]` → Glue job references and arguments
- `Triggers[]` → Trigger type, schedule, conditions
- `Crawlers[]` → Catalog crawler definitions and targets
- `Connections` → Data source configurations

#### Databricks Workflow JSON
**Detection**: Look for `"tasks"` array, `"job_clusters"` array
```json
{
  "name": "workflow_name",
  "tasks": [
    {
      "task_key": "task_name",
      "notebook_task": { "notebook_path": "/path/to/notebook" },
      "depends_on": [{ "task_key": "previous_task" }],
      "job_cluster_key": "cluster_name"
    }
  ],
  "job_clusters": [
    { "job_cluster_key": "cluster_name", "new_cluster": { "spark_version": "...", "num_workers": 2 } }
  ],
  "schedule": { "quartz_cron_expression": "0 0 * * * ?", "timezone_id": "UTC" }
}
```

**Extract:**
- `tasks[]` → Task graph (notebook paths, dependencies, cluster config)
- `job_clusters[]` → Compute configuration
- `schedule` → Trigger/schedule definition
- `parameters` → Job-level parameters

### Connection JSON Conversion Rules

#### ADF Pipeline → AWS Step Functions + Glue
| ADF Activity Type | AWS Equivalent |
|-------------------|---------------|
| Copy | Glue Job (ETL) or Step Function State (Lambda) |
| DatabricksNotebook | Glue Job (PySpark) or EMR Step |
| SparkJob | Glue Job or EMR Step |
| ExecutePipeline | Step Function nested execution |
| WebActivity | Lambda Function |
| ForEach | Step Function Map state |
| IfCondition | Step Function Choice state |
| Wait | Step Function Wait state |

#### Glue Workflow → ADF Pipeline
| Glue Component | ADF Equivalent |
|---------------|----------------|
| Glue Job | DatabricksNotebook or SparkJob activity |
| Crawler | Metadata-driven Copy activity |
| Trigger (SCHEDULED) | ADF Trigger (Schedule) |
| Trigger (CONDITIONAL) | ADF dependsOn with conditions |
| Connection | ADF Linked Service |

#### ADF Pipeline → Databricks Workflow
| ADF Activity Type | Databricks Equivalent |
|-------------------|-----------------------|
| DatabricksNotebook | notebook_task |
| SparkJob | spark_jar_task or spark_python_task |
| ExecutePipeline | run_job_task |
| ForEach | for_each_task |
| Copy | notebook_task (with COPY INTO) |

#### Linked Service / Connection Conversion
| Source | Target | Conversion |
|--------|--------|-----------|
| ADF Linked Service (Azure SQL) | Glue Connection (JDBC) | Convert connection string → JDBC URL |
| ADF Linked Service (ADLS) | Glue Connection (S3) | Convert abfss:// → s3:// |
| Glue Connection (S3) | ADF Linked Service (ADLS) | Convert s3:// → abfss:// |
| Glue Connection (JDBC) | ADF Linked Service | Convert JDBC URL → connection string |
| ADF Key Vault | AWS Secrets Manager | Map vault/secret → secret ID |
| AWS Secrets Manager | ADF Key Vault | Map secret ID → vault/secret |
