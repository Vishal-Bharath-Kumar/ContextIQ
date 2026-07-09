# Databricks-Specific Feature Enhancements

Defines detection rules, applicability criteria, and code transformation patterns for Databricks-native features that can enhance converted notebooks. These enhancements are **optional** and applied only when the user explicitly opts in via an interactive terminal prompt.

## Enhancement Workflow

```
1. Notebook conversion + workflow conversion completes (standard platform conversion)
2. IF target platform is Databricks:
   a. Scan converted NOTEBOOKS against Notebook Enhancement Rules (Auto Loader, DLT, Z-Order, etc.)
   b. Scan converted NOTEBOOKS against Layer-Specific Enhancement Rules (Bronze, Silver, Gold)
   c. Scan converted WORKFLOW YAML against Workflow Enhancement Rules (autoscaling, alerts, etc.)
   d. Collect ALL applicable enhancements with justification
   e. IF applicable_enhancements is NOT empty:
      → Prompt user with categorized enhancement list and brief explanation per item
      → Wait for user confirmation (yes/proceed → apply ALL, no/skip → skip ALL)
      → User can also select specific items by number (e.g., "1, 3, 5 only")
   f. IF applicable_enhancements is empty:
      → Print: "No Databricks-specific enhancements are required for the converted artifacts."
      → Proceed to next pipeline stage
3. If user confirmed, apply enhancement transformations to the converted code AND workflow YAML
4. Continue to anti-pattern fixer and optimizer stages
```

## Feature: Auto Loader (cloudFiles)

### What It Does
Incrementally ingests new files from cloud storage without reprocessing already-loaded files. Uses checkpoint-based tracking to guarantee exactly-once file processing.

### Detection Rules
Scan converted code for ALL of these patterns:

**Positive Indicators (code IS a candidate):**
- `spark.read.format("csv|json|parquet|avro|orc|text").load(path)` where path is a cloud storage directory
- `spark.read.csv(path)` / `spark.read.json(path)` / `spark.read.parquet(path)` from a directory (not a single file)
- File path patterns suggesting a landing zone or inbox: paths containing `landing/`, `raw/`, `inbox/`, `incoming/`, `ingest/`, `bronze/`
- The notebook appears to run as a scheduled/recurring job (parameters for dates, run IDs, incremental flags)
- Source file reads from external storage directories that grow over time

**Negative Indicators (code is NOT a candidate):**
- Reading from catalog tables: `spark.read.table(...)`, `spark.sql("SELECT ... FROM ...")`
- Reading from databases: `spark.read.format("jdbc")`, `.read.synapsesql(...)`, JDBC connections
- Reading a single specific file (not a directory glob)
- One-time migration or backfill scripts (no scheduling parameters)
- Already using `spark.readStream` or structured streaming

**Applicability Threshold:** At least 1 positive indicator AND 0 negative indicators on that specific read operation.

### Transformation Pattern

**Before (standard batch read):**
```python
df = spark.read.format("csv") \
    .option("header", "true") \
    .schema(my_schema) \
    .load("abfss://container@storage.dfs.core.windows.net/landing/orders/")
```

**After (Auto Loader):**
```python
df = (spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "csv")
    .option("header", "true")
    .schema(my_schema)
    .load("abfss://container@storage.dfs.core.windows.net/landing/orders/")
)
```

**Write side must also change to streaming:**
```python
# Before
df.write.format("delta").mode("append").save(target_path)

# After
(df.writeStream
    .format("delta")
    .option("checkpointLocation", f"{target_path}/_checkpoint")
    .trigger(availableNow=True)
    .outputMode("append")
    .start(target_path)
    .awaitTermination()
)
```

### Additional Considerations
- Add `checkpointLocation` for each Auto Loader stream
- Use `trigger(availableNow=True)` for batch-like behavior with incremental tracking
- Schema evolution: add `.option("cloudFiles.schemaEvolutionMode", "addNewColumns")` if source schemas may change
- Supported file formats: csv, json, parquet, avro, orc, text, binaryFile

---

## Feature: Delta Live Tables (DLT)

### What It Does
Declarative ETL framework that manages data quality, dependencies, and pipeline orchestration. Replaces manual read→transform→write chains with `@dlt.table` decorators.

### Detection Rules
Scan converted code for ALL of these patterns:

**Positive Indicators (code IS a candidate):**
- Multiple sequential read→transform→write blocks processing different tables
- Medallion architecture pattern: code writes to paths or tables with `bronze`, `silver`, `gold` naming
- Data quality checks: explicit null checks, value range validations, row count assertions
- Table dependency chains: output of one transformation is input to the next
- The notebook processes 3+ tables in a single pipeline flow

**Negative Indicators (code is NOT a candidate):**
- Single table processing (one read → one transform → one write)
- Ad-hoc analysis or exploration notebooks
- Notebooks that only read data (no writes)
- Notebooks with complex custom orchestration that doesn't fit declarative patterns
- Heavy use of `spark.sql()` with procedural logic (loops, conditionals controlling flow)

**Applicability Threshold:** At least 2 positive indicators AND the notebook processes 3+ tables.

### Transformation Pattern

**Before (imperative ETL):**
```python
# Bronze
raw_df = spark.read.format("csv").load(landing_path)
raw_df.write.format("delta").mode("overwrite").save(bronze_path)

# Silver
bronze_df = spark.read.format("delta").load(bronze_path)
clean_df = bronze_df.filter(F.col("id").isNotNull()).dropDuplicates(["id"])
clean_df.write.format("delta").mode("overwrite").save(silver_path)

# Gold
silver_df = spark.read.format("delta").load(silver_path)
agg_df = silver_df.groupBy("category").agg(F.sum("amount").alias("total"))
agg_df.write.format("delta").mode("overwrite").save(gold_path)
```

**After (DLT):**
```python
import dlt
from pyspark.sql import functions as F

@dlt.table(
    name="bronze_orders",
    comment="Raw orders ingested from landing zone"
)
def bronze_orders():
    return spark.read.format("csv").load(landing_path)

@dlt.table(
    name="silver_orders",
    comment="Cleaned and deduplicated orders"
)
@dlt.expect_or_drop("valid_id", "id IS NOT NULL")
def silver_orders():
    return dlt.read("bronze_orders").dropDuplicates(["id"])

@dlt.table(
    name="gold_order_summary",
    comment="Aggregated order summary by category"
)
def gold_order_summary():
    return (
        dlt.read("silver_orders")
        .groupBy("category")
        .agg(F.sum("amount").alias("total"))
    )
```

### Additional Considerations
- DLT manages table creation, schema evolution, and checkpointing automatically
- Replace `spark.read.format("delta").load(path)` with `dlt.read("table_name")` for intra-pipeline reads
- Data quality expectations replace manual filter/assert patterns
- DLT notebooks cannot contain `dbutils.widgets` — parameters come from pipeline configuration
- DLT requires a separate pipeline definition (not a standard job cluster)

---

## Feature: Z-Order Clustering

### What It Does
Colocates related data in the same set of files on Delta tables, dramatically improving query performance for filtered reads on specific columns.

### Detection Rules
Scan converted code for ALL of these patterns:

**Positive Indicators (code IS a candidate):**
- Delta table writes: `.write.format("delta")` or `.saveAsTable(...)` with Delta format
- Identifiable high-cardinality filter columns used in `WHERE`, `JOIN`, or `FILTER` conditions downstream
- Large tables (indicated by partitioning, multiple writes, or explicit comments about data size)
- Columns used frequently in `.filter()`, `.where()`, or SQL `WHERE` clauses on the written table
- Join keys that are queried by downstream consumers

**Negative Indicators (code is NOT a candidate):**
- Writing to non-Delta formats (parquet, csv, json without Delta)
- Small reference/lookup tables
- Temporary or intermediate DataFrames not persisted as tables
- Append-only log tables where Z-ordering adds overhead without benefit
- Tables already using Liquid Clustering

**Applicability Threshold:** Delta table write detected AND at least 1 identifiable filter/join column on that table.

### Transformation Pattern

**Before (Delta write without optimization):**
```python
df.write.format("delta").mode("overwrite").save(target_path)
```

**After (Delta write + Z-Order):**
```python
df.write.format("delta").mode("overwrite").save(target_path)

# Optimize and Z-Order on frequently queried columns
spark.sql(f"OPTIMIZE delta.`{target_path}` ZORDER BY (customer_id, order_date)")
```

**For managed tables:**
```python
df.write.format("delta").mode("overwrite").saveAsTable("catalog.schema.table_name")

spark.sql("OPTIMIZE catalog.schema.table_name ZORDER BY (customer_id, order_date)")
```

### Column Selection Heuristic
- Prefer columns used in `WHERE` / `FILTER` clauses in downstream queries
- Prefer columns used as `JOIN` keys
- Prefer high-cardinality columns (IDs, dates) over low-cardinality (status, type)
- Maximum 4 columns per Z-Order (diminishing returns beyond that)
- Do NOT Z-Order on partition columns (already physically separated)

---

## Feature: OPTIMIZE (Table Compaction)

### What It Does
Compacts small files into larger ones on Delta tables, improving read performance. Often paired with Z-Order.

### Detection Rules
Scan converted code for ALL of these patterns:

**Positive Indicators (code IS a candidate):**
- Delta table writes using `mode("append")` (creates many small files over time)
- Multiple small writes to the same Delta table
- Streaming writes (Auto Loader or structured streaming) that produce small files
- Presence of `.repartition()` or `.coalesce()` before write (indicates file-size awareness)

**Negative Indicators (code is NOT a candidate):**
- Single overwrite operation (already produces optimally sized files)
- Non-Delta format outputs
- The table is already being optimized elsewhere in the pipeline

**Applicability Threshold:** Delta append writes detected.

### Transformation Pattern

**After append writes, add:**
```python
# Compact small files for read performance
spark.sql(f"OPTIMIZE delta.`{target_path}`")
```

---

## Feature: COPY INTO

### What It Does
Idempotent SQL command to load files from cloud storage into a Delta table. Tracks which files have already been loaded, preventing duplicate processing on re-runs.

### Detection Rules
Scan converted code for ALL of these patterns:

**Positive Indicators (code IS a candidate):**
- File-based loading into Delta tables: `spark.read.format("csv|json|parquet").load(path)` followed by `.write.format("delta").mode("append")`
- Landing zone → Bronze layer pattern
- Pipeline that may be re-run (has retry logic, is scheduled, or handles idempotency manually)
- Manual deduplication logic after file reads

**Negative Indicators (code is NOT a candidate):**
- Already using Auto Loader (cloudFiles) — Auto Loader supersedes COPY INTO
- Reading from databases or APIs (not file-based)
- Full overwrite patterns (`mode("overwrite")`) — idempotency already handled
- Complex transformations between read and write (COPY INTO is for direct loading)

**Applicability Threshold:** File-based source → Delta append write detected AND NOT already using Auto Loader.

### Transformation Pattern

**Before (manual file load):**
```python
df = spark.read.format("csv").option("header", "true").load(landing_path)
df.write.format("delta").mode("append").save(bronze_path)
```

**After (COPY INTO):**
```python
spark.sql(f"""
    COPY INTO delta.`{bronze_path}`
    FROM '{landing_path}'
    FILEFORMAT = CSV
    FORMAT_OPTIONS ('header' = 'true')
    COPY_OPTIONS ('mergeSchema' = 'true')
""")
```

---

## Feature: Change Data Feed (CDF)

### What It Does
Enables tracking row-level changes (inserts, updates, deletes) on Delta tables. Downstream consumers can read only the changes instead of the full table.

### Detection Rules
Scan converted code for ALL of these patterns:

**Positive Indicators (code IS a candidate):**
- MERGE / UPSERT operations: `DeltaTable.forPath(...).merge(...)` or `MERGE INTO` SQL
- SCD (Slowly Changing Dimension) handling patterns
- Downstream notebooks that re-read full tables just to detect changes
- Incremental processing patterns where change detection is done manually

**Negative Indicators (code is NOT a candidate):**
- Full overwrite only (no incremental updates)
- No downstream consumers that need change tracking
- Simple append-only tables
- One-time data migration scripts

**Applicability Threshold:** MERGE/upsert operation detected on a Delta table.

### Transformation Pattern

**Enable CDF on the target table:**
```python
spark.sql(f"""
    ALTER TABLE delta.`{target_path}`
    SET TBLPROPERTIES (delta.enableChangeDataFeed = true)
""")
```

**Downstream consumers can then read changes:**
```python
# Read only changes since a specific version
changes_df = (spark.read.format("delta")
    .option("readChangeFeed", "true")
    .option("startingVersion", last_processed_version)
    .load(target_path)
)
```

---

## Feature: Liquid Clustering

### What It Does
A modern replacement for Z-Order and partitioning in Databricks. Automatically organizes data for optimal query performance without manual OPTIMIZE runs. Available on Databricks Runtime 13.3+.

### Detection Rules
Same detection rules as Z-Order Clustering, plus:

**Additional Positive Indicators:**
- Tables where partition columns change over time
- Tables where both partitioning and Z-Order would be needed
- New table creation (easier to adopt from scratch)

**When to Prefer Over Z-Order:**
- New tables being created (not migrating existing Z-Ordered tables)
- Tables with evolving query patterns
- When automatic maintenance is preferred over manual OPTIMIZE + ZORDER

### Transformation Pattern

**Before (no clustering):**
```python
df.write.format("delta").mode("overwrite").save(target_path)
```

**After (Liquid Clustering):**
```python
# Create table with Liquid Clustering
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS catalog.schema.table_name
    CLUSTER BY (customer_id, order_date)
    AS SELECT * FROM temp_view
""")
```

**For existing tables:**
```python
df.write.format("delta").mode("overwrite").save(target_path)

spark.sql(f"""
    ALTER TABLE delta.`{target_path}`
    CLUSTER BY (customer_id, order_date)
""")
```

---

# SECTION B: WORKFLOW YAML ENHANCEMENTS

These enhancements apply to the generated Databricks job YAML (DAB format). They are detected by scanning the converted workflow definition.

---

## Workflow Enhancement: Autoscaling

### What It Does
Replaces fixed `num_workers` with dynamic autoscaling, allowing clusters to scale between min and max workers based on workload. Reduces cost during light loads and increases compute during spikes.

### Detection Rules

**Positive Indicators:**
- `num_workers` is set to a fixed value in `job_clusters[].new_cluster`
- No existing `autoscale` block in the cluster definition
- Task processes large or variable-size datasets (detected from notebook content: file reads from directories, multiple tables, partitioned data)

**Negative Indicators:**
- `autoscale` already present in cluster definition
- `num_workers: 1` (single-node mode, autoscaling not applicable)
- Cluster is a single-node cluster (no workers)

**Applicability Threshold:** Fixed `num_workers >= 2` AND no `autoscale` block present.

### Transformation Pattern

**Before:**
```yaml
job_clusters:
  - job_cluster_key: job_cluster_medium
    new_cluster:
      spark_version: "14.3.x-scala2.12"
      node_type_id: Standard_DS4_v2
      num_workers: 5
```

**After:**
```yaml
job_clusters:
  - job_cluster_key: job_cluster_medium
    new_cluster:
      spark_version: "14.3.x-scala2.12"
      node_type_id: Standard_DS4_v2
      autoscale:
        min_workers: 2
        max_workers: ${source.num_workers * 2}  # 2x source for headroom
```

**Scaling Heuristic:**
- `min_workers`: `max(2, floor(source.num_workers / 2))`
- `max_workers`: `source.num_workers * 2` (capped at 50)

---

## Workflow Enhancement: Retry Logic Improvement

### What It Does
Adds `min_retry_interval_millis` alongside `max_retries` to handle transient failures with exponential backoff.

### Detection Rules

**Positive Indicators:**
- `max_retries` is set to 0 or missing in task definitions
- Tasks perform I/O operations (notebook reads from external storage, databases)

**Negative Indicators:**
- `max_retries` already set to a value > 0 AND `min_retry_interval_millis` is present

**Applicability Threshold:** At least one task with `max_retries: 0` or missing retry config.

### Transformation Pattern

**Before:**
```yaml
tasks:
  - task_key: bronze_load
    notebook_task:
      notebook_path: /Workspace/Pipelines/bronze_load
    max_retries: 0
```

**After:**
```yaml
tasks:
  - task_key: bronze_load
    notebook_task:
      notebook_path: /Workspace/Pipelines/bronze_load
    max_retries: 2
    min_retry_interval_millis: 60000    # 1 minute between retries
```

---

## Workflow Enhancement: Alerts & Notifications

### What It Does
Configures email or webhook notifications on job failure, success, or start. Enables faster issue detection and SLA monitoring.

### Detection Rules

**Positive Indicators:**
- `email_notifications.on_failure` is empty array `[]`
- No `webhook_notifications` block present

**Negative Indicators:**
- `email_notifications.on_failure` already has email addresses
- `webhook_notifications` is configured

**Applicability Threshold:** Empty or missing notification configuration.

### Transformation Pattern

**Before:**
```yaml
email_notifications:
  on_failure: []
```

**After:**
```yaml
email_notifications:
  on_failure:
    - ${config.alert_email}       # From pipeline config or parameter
  on_start: []
  on_success: []
# webhook_notifications:          # Uncomment if webhook URL available
#   on_failure:
#     - id: ${config.webhook_id}
```

**Note:** The actual email/webhook values must come from pipeline configuration. The enhancement adds the structure and marks where values should be injected.

---

## Workflow Enhancement: Cluster Policies

### What It Does
Attaches a cluster policy ID to job clusters, enforcing governance constraints (instance types, regions, max workers, auto-termination) set by administrators.

### Detection Rules

**Positive Indicators:**
- `job_clusters[].new_cluster` has no `policy_id` field
- Environment tag indicates production usage (`tags.environment: production`)

**Negative Indicators:**
- `policy_id` already present in cluster definition

**Applicability Threshold:** No `policy_id` in any cluster definition.

### Transformation Pattern

**Before:**
```yaml
job_clusters:
  - job_cluster_key: job_cluster_medium
    new_cluster:
      spark_version: "14.3.x-scala2.12"
      node_type_id: Standard_DS4_v2
      num_workers: 5
```

**After:**
```yaml
job_clusters:
  - job_cluster_key: job_cluster_medium
    new_cluster:
      policy_id: ${config.cluster_policy_id}   # From governance config
      spark_version: "14.3.x-scala2.12"
      node_type_id: Standard_DS4_v2
      num_workers: 5
```

---

## Workflow Enhancement: Job Tags

### What It Does
Adds metadata tags for cost tracking, ownership, and governance. Tags propagate to cloud billing for cost allocation.

### Detection Rules

**Positive Indicators:**
- `tags` section is missing or only has basic tags (environment, source_platform, converted)
- No `owner`, `team`, `cost_center`, or `project` tags

**Negative Indicators:**
- Tags already include `owner`, `team`, and `cost_center`

**Applicability Threshold:** Missing at least 2 of: `owner`, `team`, `cost_center`, `project`.

### Transformation Pattern

**Before:**
```yaml
tags:
  environment: production
  source_platform: aws_glue
  converted: "true"
```

**After:**
```yaml
tags:
  environment: ${config.environment}
  source_platform: aws_glue
  converted: "true"
  owner: ${config.owner}              # From pipeline config
  team: ${config.team}                # From pipeline config
  cost_center: ${config.cost_center}  # From pipeline config
  project: ${config.project}          # From pipeline config
```

---

# SECTION C: BRONZE LAYER ENHANCEMENTS

These enhancements apply to converted notebooks detected as bronze/ingestion layer (path or name contains `bronze`, `raw`, `landing`, `ingest`).

---

## Bronze Enhancement: Bad Records Handling

### What It Does
Captures corrupt or malformed rows to a separate location for debugging instead of silently dropping them.

### Detection Rules

**Positive Indicators:**
- File reads using `spark.read.format("csv|json")` (formats prone to corruption)
- No existing `.option("badRecordsPath", ...)` or `.option("mode", "PERMISSIVE")` with `_corrupt_record` column
- Bronze/ingestion layer detected (path or name pattern)

**Negative Indicators:**
- Already has `badRecordsPath` option
- Reading from Delta tables or databases (structured sources — no bad records)
- Using `FAILFAST` mode intentionally

**Applicability Threshold:** CSV or JSON file reads in bronze layer without bad records handling.

### Transformation Pattern

**Before:**
```python
df = spark.read.format("csv") \
    .option("header", "true") \
    .schema(my_schema) \
    .load(landing_path)
```

**After:**
```python
df = spark.read.format("csv") \
    .option("header", "true") \
    .option("badRecordsPath", f"{error_base_path}/bronze/{table_name}") \
    .schema(my_schema) \
    .load(landing_path)
```

---

## Bronze Enhancement: Error Table

### What It Does
Writes rejected or failed records to a dedicated error table/path for traceability and debugging. Separate from `badRecordsPath` — this captures records that fail validation logic.

### Detection Rules

**Positive Indicators:**
- Data validation or filtering that drops records (`.filter()`, `.where()`, null checks)
- Bronze/ingestion layer notebook
- No existing error table write pattern

**Negative Indicators:**
- Already writes rejected records to a separate path/table
- No filtering or validation (passthrough ingestion)

**Applicability Threshold:** Bronze layer with data validation that drops records.

### Transformation Pattern

**Before:**
```python
df = spark.read.parquet(landing_path)
valid_df = df.filter(F.col("id").isNotNull() & F.col("date").isNotNull())
valid_df.write.format("delta").mode("append").save(bronze_path)
```

**After:**
```python
df = spark.read.parquet(landing_path)
valid_df = df.filter(F.col("id").isNotNull() & F.col("date").isNotNull())
error_df = df.filter(F.col("id").isNull() | F.col("date").isNull())

valid_df.write.format("delta").mode("append").save(bronze_path)

if error_df.count() > 0:
    error_df = error_df.withColumn("_error_reason", F.lit("null_key_columns")) \
                       .withColumn("_error_timestamp", F.current_timestamp())
    error_df.write.format("delta").mode("append").save(f"{error_base_path}/bronze/{table_name}")
    logger.warning("Rejected %d records to error table", error_df.count())
```

---

## Bronze Enhancement: Partitioning Strategy

### What It Does
Adds `partitionBy` on ingestion date or batch date columns for efficient downstream queries and data lifecycle management.

### Detection Rules

**Positive Indicators:**
- Delta writes without `.partitionBy()` in bronze layer
- Table has date/timestamp columns (`ingest_date`, `load_date`, `batch_date`, `created_at`)
- Large data volumes (indicated by scheduled loads, directory reads)

**Negative Indicators:**
- Already has `.partitionBy()` on the write
- Small reference/lookup table
- Using Liquid Clustering (supersedes partitioning)

**Applicability Threshold:** Bronze Delta write without partitioning AND identifiable date column.

### Transformation Pattern

**Before:**
```python
df.write.format("delta").mode("append").save(bronze_path)
```

**After:**
```python
df.write.format("delta").mode("append").partitionBy("ingest_date").save(bronze_path)
```

**Column Selection Heuristic:**
- Prefer `ingest_date` or `load_date` if present
- Prefer `batch_date` or `created_at`
- If no date column exists, suggest adding `ingest_date = current_date()` as audit column

---

## Bronze Enhancement: Audit Columns

### What It Does
Adds standardized ingestion metadata columns (`_ingest_timestamp`, `_source_file`, `_batch_id`) for data lineage tracking.

### Detection Rules

**Positive Indicators:**
- Bronze/ingestion layer notebook
- No existing audit/metadata columns (`_ingest_timestamp`, `_source_file`, `_load_id`)
- File-based reads from landing zone

**Negative Indicators:**
- Already has audit columns
- Reading from catalog tables (not raw ingestion)

**Applicability Threshold:** Bronze layer file reads without audit columns.

### Transformation Pattern

**Before:**
```python
df = spark.read.format("csv").option("header", "true").load(landing_path)
df.write.format("delta").mode("append").save(bronze_path)
```

**After:**
```python
df = spark.read.format("csv").option("header", "true").load(landing_path)
df = df.withColumn("_ingest_timestamp", F.current_timestamp()) \
       .withColumn("_source_file", F.input_file_name()) \
       .withColumn("_batch_id", F.lit(batch_id))
df.write.format("delta").mode("append").save(bronze_path)
```

---

# SECTION D: SILVER LAYER ENHANCEMENTS

These enhancements apply to converted notebooks detected as silver/cleansing layer (path or name contains `silver`, `clean`, `curated`, `transform`).

---

## Silver Enhancement: Schema Evolution Control

### What It Does
Adds explicit `mergeSchema` handling for Delta writes to prevent silent schema corruption while allowing controlled schema evolution.

### Detection Rules

**Positive Indicators:**
- Delta writes using `mode("append")` or Delta MERGE operations
- Silver/transform layer notebook
- Source data may evolve (file-based inputs, external sources)

**Negative Indicators:**
- Already has `.option("mergeSchema", "true")` or `overwriteSchema`
- Full overwrite mode with static schema

**Applicability Threshold:** Silver layer Delta writes without explicit schema evolution handling.

### Transformation Pattern

**Before:**
```python
clean_df.write.format("delta").mode("append").save(silver_path)
```

**After:**
```python
clean_df.write.format("delta").mode("append") \
    .option("mergeSchema", "true") \
    .save(silver_path)
logger.info("Schema evolution enabled for silver write to %s", silver_path)
```

---

## Silver Enhancement: Primary Key Validation

### What It Does
Enforces uniqueness and non-null constraints on primary key columns before writing to silver layer. Prevents duplicate or orphan records.

### Detection Rules

**Positive Indicators:**
- Silver/transform layer notebook
- MERGE or upsert operations that imply a primary key
- `dropDuplicates()` call (indicates PK awareness)
- Columns named `id`, `pk`, `key`, `*_id` used in joins or dedup

**Negative Indicators:**
- Already validates PK uniqueness before write
- Append-only log tables (no PK concept)

**Applicability Threshold:** Silver layer with identifiable primary key columns.

### Transformation Pattern

**Before:**
```python
clean_df = clean_df.dropDuplicates(["npi"])
clean_df.write.format("delta").mode("overwrite").save(silver_path)
```

**After:**
```python
# Primary key validation
pk_columns = ["npi"]
for pk_col in pk_columns:
    null_count = clean_df.filter(F.col(pk_col).isNull()).count()
    if null_count > 0:
        logger.error("PK column '%s' has %d null values — rejecting", pk_col, null_count)
        raise ValueError(f"Primary key validation failed: {pk_col} has {null_count} nulls")

dup_count = clean_df.count() - clean_df.dropDuplicates(pk_columns).count()
if dup_count > 0:
    logger.warning("Found %d duplicate PKs — deduplicating", dup_count)
clean_df = clean_df.dropDuplicates(pk_columns)

clean_df.write.format("delta").mode("overwrite").save(silver_path)
```

---

## Silver Enhancement: CDC Watermark Validation

### What It Does
Validates that the watermark/timestamp column used for incremental processing exists and contains valid values. Prevents data loss in CDC pipelines.

### Detection Rules

**Positive Indicators:**
- Incremental read based on timestamp column: `.filter(F.col("ingest_timestamp") > last_watermark)`
- MERGE/upsert with timestamp-based condition
- Parameters for `last_run_timestamp`, `watermark`, or similar

**Negative Indicators:**
- Full load (no incremental pattern)
- No timestamp-based filtering

**Applicability Threshold:** Incremental processing detected with timestamp-based watermark.

### Transformation Pattern

**Before:**
```python
new_data = df.filter(F.col("ingest_timestamp") > last_timestamp)
```

**After:**
```python
# Validate watermark column exists and has valid values
if "ingest_timestamp" not in df.columns:
    raise ValueError("Watermark column 'ingest_timestamp' not found in source data")

null_watermarks = df.filter(F.col("ingest_timestamp").isNull()).count()
if null_watermarks > 0:
    logger.warning("Found %d rows with null watermark — these will be excluded from incremental load", null_watermarks)

new_data = df.filter(
    F.col("ingest_timestamp").isNotNull() &
    (F.col("ingest_timestamp") > last_timestamp)
)
logger.info("Incremental load: %d new rows since %s", new_data.count(), last_timestamp)
```

---

## Silver Enhancement: SCD Audit Columns

### What It Does
Adds `_created_on` and `_modified_on` columns for tracking record history in slowly changing dimension (SCD) patterns.

### Detection Rules

**Positive Indicators:**
- MERGE/upsert operations that update existing records
- SCD pattern detected (matched + unmatched handling)
- Silver layer notebook
- No existing `created_on`, `modified_on`, `_created_on`, `_modified_on` columns

**Negative Indicators:**
- Already has SCD audit columns
- Append-only pattern (no updates)
- Full overwrite (no history tracking needed)

**Applicability Threshold:** Silver layer with MERGE/upsert and no SCD audit columns.

### Transformation Pattern

**Before (MERGE):**
```python
delta_table.alias("target").merge(
    source_df.alias("source"),
    "target.id = source.id"
).whenMatchedUpdateAll() \
 .whenNotMatchedInsertAll() \
 .execute()
```

**After (MERGE with audit columns):**
```python
source_df = source_df.withColumn("_modified_on", F.current_timestamp())

delta_table.alias("target").merge(
    source_df.alias("source"),
    "target.id = source.id"
).whenMatchedUpdate(set={
    **{col: f"source.{col}" for col in update_columns},
    "_modified_on": F.current_timestamp()
}).whenNotMatchedInsert(values={
    **{col: f"source.{col}" for col in insert_columns},
    "_created_on": F.current_timestamp(),
    "_modified_on": F.current_timestamp()
}).execute()
```

---

## Silver Enhancement: Skew Handling (AQE)

### What It Does
Enables Adaptive Query Execution (AQE) with skew join optimization to handle data skew in joins, preventing task stragglers and OOM errors.

### Detection Rules

**Positive Indicators:**
- JOIN operations on columns that may have skewed distribution (e.g., customer_id, provider_id)
- Large table joins (multi-million rows)
- Silver layer with complex transformations
- AQE not already explicitly enabled

**Negative Indicators:**
- AQE already enabled via `spark.conf.set("spark.sql.adaptive.enabled", "true")`
- Small dataset joins (lookup tables)
- No joins in the notebook

**Applicability Threshold:** Silver layer with JOIN operations AND AQE not explicitly configured.

### Transformation Pattern

**Add at the top of the notebook (after SparkSession):**
```python
# Enable Adaptive Query Execution for skew handling
spark.conf.set("spark.sql.adaptive.enabled", "true")
spark.conf.set("spark.sql.adaptive.skewJoin.enabled", "true")
spark.conf.set("spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes", "256mb")
```

---

## Silver Enhancement: Data Drift Monitoring

### What It Does
Compares the current schema of incoming data against expected schema and logs differences. Detects when upstream sources add, remove, or change column types.

### Detection Rules

**Positive Indicators:**
- Reads from external or bronze layer sources
- Silver layer notebook
- No existing schema comparison logic

**Negative Indicators:**
- Already has schema validation (DG-SV checks)
- Reading from tightly controlled internal sources

**Applicability Threshold:** Silver layer reading from external or bronze sources without schema drift detection.

### Transformation Pattern

**After reading source data:**
```python
# Data drift monitoring — compare actual vs expected schema
expected_columns = set(expected_schema.fieldNames())
actual_columns = set(df.columns)

new_columns = actual_columns - expected_columns
dropped_columns = expected_columns - actual_columns

if new_columns:
    logger.warning("Schema drift detected — new columns: %s", new_columns)
if dropped_columns:
    logger.error("Schema drift detected — missing columns: %s", dropped_columns)
    raise ValueError(f"Critical schema drift: missing columns {dropped_columns}")

# Type drift check
for field in expected_schema.fields:
    if field.name in df.columns:
        actual_type = str(df.schema[field.name].dataType)
        expected_type = str(field.dataType)
        if actual_type != expected_type:
            logger.warning("Type drift on '%s': expected %s, got %s", field.name, expected_type, actual_type)
```

---

# SECTION E: GOLD LAYER ENHANCEMENTS

These enhancements apply to converted notebooks detected as gold/serving layer (path or name contains `gold`, `agg`, `mart`, `serving`, `report`).

---

## Gold Enhancement: Business Rule Validation

### What It Does
Adds domain-specific data quality checks on curated/aggregated data (e.g., no negative values in amount columns, valid date ranges, referential integrity).

### Detection Rules

**Positive Indicators:**
- Gold/serving layer notebook
- Aggregation operations (`groupBy`, `agg`, `sum`, `count`)
- Numeric columns that should not be negative (amount, count, quantity, total)
- Date columns that should be within valid ranges

**Negative Indicators:**
- Already has business rule validation
- Raw data passthrough (no aggregation)

**Applicability Threshold:** Gold layer with aggregations or derived columns.

### Transformation Pattern

**After aggregation, before write:**
```python
# Business rule validation on curated data
neg_count = gold_df.filter(F.col("total_amount") < 0).count()
if neg_count > 0:
    logger.warning("Business rule violation: %d records with negative total_amount", neg_count)

future_dates = gold_df.filter(F.col("report_date") > F.current_date()).count()
if future_dates > 0:
    logger.warning("Business rule violation: %d records with future report_date", future_dates)

null_keys = gold_df.filter(F.col("group_key").isNull()).count()
if null_keys > 0:
    logger.error("Business rule violation: %d records with null group_key", null_keys)
```

---

## Gold Enhancement: Aggregation Reconciliation

### What It Does
Compares record counts between silver (input) and gold (output) layers to ensure no data loss during aggregation. Logs the ratio for audit.

### Detection Rules

**Positive Indicators:**
- Gold layer notebook reading from silver layer
- Aggregation operations that reduce row count
- No existing count reconciliation logic

**Negative Indicators:**
- Already has cross-layer count comparison
- 1:1 transformation (no aggregation)

**Applicability Threshold:** Gold layer with aggregation from silver source.

### Transformation Pattern

**After aggregation:**
```python
# Cross-layer reconciliation
silver_count = silver_df.count()
gold_count = gold_df.count()
logger.info("Reconciliation: Silver=%d rows → Gold=%d rows (ratio=%.2f)",
            silver_count, gold_count, gold_count / max(silver_count, 1))

if gold_count == 0 and silver_count > 0:
    logger.error("Reconciliation FAILED: Gold layer has 0 rows from %d silver rows", silver_count)
    raise ValueError("Gold layer aggregation produced zero rows")
```

---

## Gold Enhancement: SCD1 Audit Logging

### What It Does
Tracks overwrite history for gold tables by logging what was replaced and when, enabling audit trails for regulatory compliance.

### Detection Rules

**Positive Indicators:**
- Gold layer writing with `mode("overwrite")`
- Business-critical tables (mart, report, serving)
- No existing audit logging for overwrites

**Negative Indicators:**
- Already logs overwrite metadata
- Append-only gold tables
- Using Delta time travel (implicit audit)

**Applicability Threshold:** Gold layer with overwrite mode writes.

### Transformation Pattern

**Before write:**
```python
# SCD1 audit — log overwrite event
try:
    existing_df = spark.read.format("delta").load(gold_path)
    existing_count = existing_df.count()
    logger.info("SCD1 audit: Overwriting %d existing rows with %d new rows at %s",
                existing_count, gold_df.count(), gold_path)
except Exception:
    logger.info("SCD1 audit: Creating new gold table at %s with %d rows",
                gold_path, gold_df.count())

gold_df.write.format("delta").mode("overwrite").save(gold_path)
```

---

## Gold Enhancement: Serving Layer Optimization

### What It Does
Optimizes gold tables for downstream BI/reporting consumption by adding table properties, caching hints, and materialized view suggestions.

### Detection Rules

**Positive Indicators:**
- Gold/serving layer notebook
- Tables consumed by BI tools (Power BI, Tableau) — indicated by naming patterns (mart, report, dashboard)
- No existing table optimization after write

**Negative Indicators:**
- Already has OPTIMIZE or Z-Order (handled by existing Z-Order enhancement)
- Temporary or intermediate tables

**Applicability Threshold:** Gold layer tables that serve downstream consumers.

### Transformation Pattern

**After writing gold table:**
```python
# Serving layer optimization
spark.sql(f"OPTIMIZE delta.`{gold_path}`")
logger.info("Gold table optimized for serving: %s", gold_path)

# Set Delta table properties for BI performance
spark.sql(f"""
    ALTER TABLE delta.`{gold_path}`
    SET TBLPROPERTIES (
        'delta.autoOptimize.optimizeWrite' = 'true',
        'delta.autoOptimize.autoCompact' = 'true'
    )
""")
```

---

## Interactive Prompt Format

When applicable enhancements are detected, prompt the user in the terminal with this categorized format:

```
═══════════════════════════════════════════════════════════════
  Databricks Enhancements Detected
═══════════════════════════════════════════════════════════════

[N] enhancement(s) detected across [M] file(s):

── NOTEBOOK ENHANCEMENTS ──────────────────────────────────────

File: <filename>

  1. Auto Loader (cloudFiles)
     → Incremental file ingestion with exactly-once guarantees
     → Detected: File reads from cloud storage directories

  2. Z-Order Clustering
     → Optimized data layout for faster filtered queries
     → Detected: Delta writes with identifiable filter columns

── LAYER-SPECIFIC ENHANCEMENTS ────────────────────────────────

  Bronze: <filename>

  3. Bad Records Handling
     → Capture corrupt rows for debugging
     → Detected: CSV reads in bronze layer without badRecordsPath

  4. Error Table
     → Write rejected records to error path for traceability
     → Detected: Validation filters dropping records without error capture

  5. Audit Columns
     → Add _ingest_timestamp, _source_file for lineage
     → Detected: Bronze file reads without ingestion metadata

  Silver: <filename>

  6. Primary Key Validation
     → Enforce PK uniqueness and non-null before write
     → Detected: dropDuplicates on npi column, no PK validation

  7. Schema Evolution Control
     → Controlled mergeSchema for safe schema changes
     → Detected: Delta append writes without schema handling

  8. Skew Handling (AQE)
     → Adaptive query execution for skewed joins
     → Detected: JOIN operations without AQE enabled

  Gold: <filename>

  9. Business Rule Validation
     → Domain checks (no negative values, valid ranges)
     → Detected: Aggregation output without validation

  10. Aggregation Reconciliation
      → Silver vs Gold row count comparison
      → Detected: Gold aggregation from silver source without reconciliation

── WORKFLOW YAML ENHANCEMENTS ─────────────────────────────────

  File: databricks_job.yml

  11. Autoscaling
      → Dynamic cluster scaling (min:2, max:10)
      → Detected: Fixed num_workers=5 without autoscale block

  12. Retry Logic
      → Retry failed tasks with interval (max_retries:2, interval:60s)
      → Detected: Tasks with max_retries=0

  13. Alerts & Notifications
      → Email/webhook alerts on failure
      → Detected: Empty on_failure notification list

  14. Cluster Policies
      → Attach governance policy to clusters
      → Detected: No policy_id in cluster definitions

  15. Job Tags
      → Cost tracking and ownership metadata
      → Detected: Missing owner, team, cost_center tags

═══════════════════════════════════════════════════════════════

Would you like to apply these enhancements?
  [Approve] — Apply all enhancements
  [Skip]    — Keep original code as-is
  [Select]  — Choose specific items (e.g., "1, 3, 5, 11")
═══════════════════════════════════════════════════════════════
```

### Prompt Rules
- List ONLY enhancements that passed detection AND applicability threshold
- Group by category: Notebook Enhancements → Layer-Specific (Bronze, Silver, Gold) → Workflow YAML
- Include a one-line benefit and the detection justification for each
- Do NOT list enhancements that are not applicable
- Do NOT prompt if zero enhancements are applicable
- Accept: `yes`, `y`, `proceed`, `approve` → apply ALL listed enhancements
- Accept: `no`, `n`, `skip` → skip ALL enhancements, proceed with standard conversion
- Accept: specific numbers → apply only selected items (e.g., "1, 3, 5, 11")
- If user selects specific items, apply ONLY those and skip the rest

## Layer Detection

To determine which layer-specific enhancements apply, detect the pipeline layer from notebook name/path:

| Layer | Regex Pattern | Examples |
|-------|--------------|----------|
| Bronze | `(?i)(bronze\|raw\|landing\|ingest\|full_load)` | `gen_ai_bronze_full_load`, `raw_extract` |
| Silver | `(?i)(silver\|clean\|curated\|transform\|merge)` | `gen_ai_silver_load`, `curated_merge` |
| Gold | `(?i)(gold\|agg\|mart\|serving\|report)` | `gen_ai_gold_load`, `sales_mart` |

**If no layer detected:** Skip layer-specific enhancements. Apply only Notebook Enhancements and Workflow YAML Enhancements.

## Feature Conflict Resolution

Some features are mutually exclusive or have precedence rules:

| Feature A | Feature B | Resolution |
|-----------|-----------|------------|
| Auto Loader | COPY INTO | Auto Loader takes precedence (superset of COPY INTO) |
| Z-Order | Liquid Clustering | Offer Liquid Clustering for new tables, Z-Order for existing |
| DLT | Auto Loader | DLT can use Auto Loader internally — both can apply |
| DLT | Z-Order | DLT manages optimization — Z-Order not needed separately |
| OPTIMIZE | Z-Order | Usually paired together — offer as single enhancement |
| Partitioning | Liquid Clustering | Liquid Clustering supersedes partitioning for new tables |
| Bad Records | Error Table | Both can apply — bad records captures parse failures, error table captures validation failures |
| Schema Evolution | Data Drift | Both can apply — evolution enables changes, drift monitors them |
| Autoscaling | Fixed Workers | Autoscaling replaces fixed workers — mutually exclusive |

## Enhancement Validation

After applying enhancements, verify:

| Check | Rule | Applies To |
|-------|------|-----------|
| Business logic preserved | All original transformations, filters, joins unchanged | Notebooks |
| Data output equivalent | Same columns, same rows, same values written | Notebooks |
| No import conflicts | New Databricks imports don't conflict with existing | Notebooks |
| Checkpoint paths set | Auto Loader / streaming writes have checkpoint locations | Notebooks |
| DLT compatibility | If DLT applied, `dbutils.widgets` removed and parameters externalized | Notebooks |
| Error paths configured | Bad records and error table paths use configurable base path | Bronze |
| Audit columns non-breaking | New columns added at end, not altering existing schema order | Bronze |
| PK validation safe | PK checks raise errors only on genuine violations | Silver |
| AQE non-conflicting | AQE settings don't override existing Spark configs | Silver |
| Schema drift safe | Drift warnings don't block pipeline unless critical columns missing | Silver |
| Reconciliation non-blocking | Count mismatches log warnings, only raise on zero-row gold | Gold |
| YAML valid | Generated YAML remains DAB-compliant after modifications | Workflow |
| Tags use config vars | All new tag values reference `${config.*}` not hardcoded values | Workflow |
| Autoscale bounds valid | min_workers >= 1, max_workers <= 50, min < max | Workflow |
