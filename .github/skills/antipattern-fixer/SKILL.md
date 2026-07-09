---
name: antipattern-fixer
description: Detects and fixes business, data pipeline, platform-specific, and observability anti-patterns in converted code. Ensures converted output follows target platform best practices while preserving business logic. Invoked after notebook conversion as a post-processing step.
# Anti-Pattern Fixer

Scans converted pipeline code for business anti-patterns, data engineering anti-patterns, platform-specific bad practices, and observability/reliability gaps. Automatically fixes issues and produces a fix report.

## Core Capabilities

- **Business anti-pattern detection**: Identify logic smells and data pipeline bad practices
- **Platform anti-pattern detection**: Catch target-platform-specific anti-patterns
- **Observability & reliability enforcement**: Schema validation, null handling, audit logging, idempotency, configuration management
- **Automated fixing**: Apply safe fixes preserving business logic
- **Fix traceability**: Document every fix with before/after and justification

## Anti-Pattern Categories

### Category 1: Data Pipeline Anti-Patterns (CRITICAL)

These directly impact data correctness and pipeline reliability.

#### AP-DP-001: Collect on Large Datasets
**Pattern**: `.collect()` on potentially large DataFrames
**Risk**: OOM on driver, pipeline crash
**Detection**: Any `.collect()` not preceded by `.limit()` or aggregation reducing row count
**Fix**: Replace with `.take(N)`, `.foreach()`, or aggregation depending on context
```python
# ANTI-PATTERN
all_rows = df.collect()
for row in all_rows:
    process(row)

# FIX
df.foreach(lambda row: process(row))
```

#### AP-DP-002: Single Partition Write
**Pattern**: `.coalesce(1)` or `.repartition(1)` before write
**Risk**: Single file bottleneck, slow writes, no parallelism
**Detection**: `.coalesce(1)` or `.repartition(1)` immediately before `.write`
**Fix**: Remove coalesce(1), use appropriate partition count or partitionBy
```python
# ANTI-PATTERN
df.coalesce(1).write.parquet(path)

# FIX
df.write.partitionBy("date_column").parquet(path)
# OR if no partition column:
df.write.parquet(path)  # Let Spark determine optimal partitions
```

#### AP-DP-003: Count in Loop
**Pattern**: `.count()` called inside a loop or called multiple times
**Risk**: Triggers full scan each time, O(n*m) operations
**Detection**: `.count()` inside `for`/`while` loops, or same `.count()` called 2+ times
**Fix**: Cache count result in variable
```python
# ANTI-PATTERN
for col in columns:
    if df.filter(F.col(col).isNull()).count() > threshold:
        handle_nulls(col)

# FIX
null_counts = df.select([F.sum(F.col(c).isNull().cast("int")).alias(c) for c in columns]).first()
for col in columns:
    if null_counts[col] > threshold:
        handle_nulls(col)
```

#### AP-DP-004: DataFrame Recomputation
**Pattern**: Same DataFrame lineage computed multiple times without caching
**Risk**: Redundant computation, wasted cluster resources
**Detection**: Same DataFrame variable used 2+ times after complex transformations without `.cache()` or `.persist()`
**Fix**: Add `.cache()` after expensive transformation, `.unpersist()` when done
```python
# ANTI-PATTERN
result = df.join(other, "key").filter(condition).groupBy("group").agg(...)
result.write.parquet(path1)
result.write.parquet(path2)     # Recomputes full lineage

# FIX
result = df.join(other, "key").filter(condition).groupBy("group").agg(...)
result.cache()
result.write.parquet(path1)
result.write.parquet(path2)
result.unpersist()
```

#### AP-DP-005: Schema Assumption Without Validation
**Pattern**: Reading external data without schema enforcement
**Risk**: Silent data corruption if source schema changes
**Detection**: `.read.parquet(path)` or `.read.csv(path)` without `.schema()` on external sources
**Fix**: Add explicit schema definition or schema validation after read
```python
# ANTI-PATTERN
df = spark.read.parquet(external_path)

# FIX
from pyspark.sql.types import StructType, StructField, StringType, IntegerType
expected_schema = StructType([
    StructField("id", IntegerType(), False),
    StructField("name", StringType(), True),
])
df = spark.read.schema(expected_schema).parquet(external_path)
```

#### AP-DP-006: Unhandled Nulls in Join Keys
**Pattern**: Join on columns without null handling
**Risk**: Silent data loss (null != null in joins excludes rows)
**Detection**: `.join()` without prior `.filter(F.col(key).isNotNull())` or `.na.drop(subset=[key])`
**Fix**: Add null filter before join on join keys
```python
# ANTI-PATTERN
result = df1.join(df2, "customer_id")

# FIX
df1_clean = df1.filter(F.col("customer_id").isNotNull())
df2_clean = df2.filter(F.col("customer_id").isNotNull())
result = df1_clean.join(df2_clean, "customer_id")
```

#### AP-DP-007: Hardcoded Paths and Values
**Pattern**: Hardcoded storage paths, database names, table names, thresholds
**Risk**: Not portable across environments (dev/staging/prod)
**Detection**: String literals containing `s3://`, `abfss://`, `wasbs://`, `dbfs:/`, database/table names
**Fix**: Extract to configuration variables at top of file
```python
# ANTI-PATTERN
df = spark.read.parquet("abfss://container@storage.dfs.core.windows.net/bronze/customers/")

# FIX (top of file)
STORAGE_ACCOUNT = "storage"
CONTAINER = "container"
BASE_PATH = f"abfss://{CONTAINER}@{STORAGE_ACCOUNT}.dfs.core.windows.net"
BRONZE_CUSTOMERS = f"{BASE_PATH}/bronze/customers/"
# ...
df = spark.read.parquet(BRONZE_CUSTOMERS)
```

### Category 2: Business Logic Anti-Patterns

#### AP-BL-001: Silent Data Drop
**Pattern**: Filter or join that silently drops significant data without logging
**Risk**: Undetected data loss
**Detection**: `.filter()` or `.join()` without logging the before/after count
**Fix**: Add count logging around data-reducing operations
```python
# ANTI-PATTERN
df = df.filter(F.col("status") == "active")

# FIX
before_count = df.count()
df = df.filter(F.col("status") == "active")
after_count = df.count()
logger.info("Filter status=active: %d → %d rows (dropped %d)", before_count, after_count, before_count - after_count)
```

#### AP-BL-002: Assumption About Data Ordering
**Pattern**: Logic depending on DataFrame row order without explicit `.orderBy()`
**Risk**: Non-deterministic results across different engines/runs
**Detection**: Row-dependent logic (first/last/head) without preceding `.orderBy()`
**Fix**: Add explicit ordering before order-dependent operations

#### AP-BL-003: Lossy Type Casting
**Pattern**: Implicit type conversions that can lose precision
**Risk**: Silent data corruption (e.g., decimal → integer, timestamp → date)
**Detection**: `.cast()` to lower precision type without comment
**Fix**: Add explicit validation or comment justifying the cast

#### AP-BL-004: Non-Idempotent Operations
**Pattern**: Pipeline operations that produce different results on re-run
**Risk**: Inconsistent data on retry/recovery
**Detection**: `append` mode writes without dedup, random/time-based columns without deterministic seed
**Fix**: Add dedup logic or use `overwrite` with partition strategy

### Category 3: Target Platform Anti-Patterns

#### Azure Databricks
| Anti-Pattern | Description | Fix |
|-------------|-------------|-----|
| AP-ADB-001 | Using `dbutils.fs.rm(path, True)` for data management | Use Delta Lake VACUUM and time-travel |
| AP-ADB-002 | Not using Delta Lake for structured data | Convert parquet writes to Delta |
| AP-ADB-003 | Ignoring Z-ordering for frequent query columns | Add `.zOrderBy()` for query-heavy tables |

#### Azure Synapse
| Anti-Pattern | Description | Fix |
|-------------|-------------|-----|
| AP-SYN-001 | Not using dedicated SQL pool distribution | Add `DISTRIBUTION` option |
| AP-SYN-002 | Missing temp view cleanup | Add `spark.catalog.dropTempView()` |

#### AWS Glue
| Anti-Pattern | Description | Fix |
|-------------|-------------|-----|
| AP-GLU-001 | Not using bookmarks for incremental| Add `transformation_ctx` |
| AP-GLU-002 | Missing `job.commit()` | Add at end of script |

#### AWS EMR
| Anti-Pattern | Description | Fix |
|-------------|-------------|-----|
| AP-EMR-001 | Not setting S3A optimizations | Add fast upload, multipart config |
| AP-EMR-002 | Missing EMRFS consistent view | Add `spark.hadoop.fs.s3.consistent` |

#### Microsoft Fabric
| Anti-Pattern | Description | Fix |
|-------------|-------------|-----|
| AP-FAB-001 | Missing default lakehouse context | Every Fabric notebook must set `spark.catalog.setCurrentDatabase(LAKEHOUSE_NAME)` as the first code cell — without it, all `%%sql` cells using unqualified table names throw "No default context found" |
| AP-FAB-002 | `spark.sql("""...""")` triple-quoted SQL | Triple-quoted strings inside `spark.sql()` cause `SyntaxError` in Fabric runtime — replace with `%%sql` cell magic for DDL/DML, or single-line `spark.sql(f"...")` for dynamic SQL |
| AP-FAB-003 | Hardcoded `workspace_id` in OneLake paths | `workspace_id` in `abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/...` must be read from `notebookutils.widgets.get("workspace_id")`, not hardcoded |
| AP-FAB-004 | Missing V-Order and autoOptimize on Delta writes | Fabric Delta tables should include `delta.autoOptimize.optimizeWrite=true` and `delta.autoOptimize.autoCompact=true` table properties for optimal read performance with Power BI and semantic models |
| AP-FAB-005 | `sempy.fabric.read_table()` for large datasets | `fabric.read_table()` loads the full result into driver memory — replace with `spark.read.format("delta").load("Tables/{table}")` for distributed processing on large tables |
| AP-FAB-006 | `notebookutils.credentials.getSecret()` without error handling | Secret retrieval has no fallback on failure — wrap in try/except and fail fast with a clear error message rather than propagating a cryptic `None` value into downstream logic |

#### GCP BigQuery / Dataproc
| Anti-Pattern | Description | Fix |
|-------------|-------------|-----|
| AP-GCP-001 | Missing `temporaryGcsBucket` config | BigQuery connector requires a GCS staging bucket for writes; add `.config("temporaryGcsBucket", "{bucket}")` to SparkSession or `.option("temporaryGcsBucket", "{bucket}")` on write |
| AP-GCP-002 | Large result materialization via `to_dataframe()` | `client.query(query).to_dataframe()` loads full result into driver memory; replace with `spark.read.format("bigquery").option("query", query).load()` for distributed processing |
| AP-GCP-003 | Missing `spark.stop()` on Dataproc scripts | Dataproc `.py` scripts require explicit `spark.stop()` at end; omitting it causes resource leaks on ephemeral clusters |
| AP-GCP-004 | Hardcoded GCP project ID | `project_id` should be read from environment or argparse parameter, not hardcoded in BigQuery table references |

### Category 4: Observability & Reliability (AP-OB-XXX)

These replace the data-governance skill. Applied after platform anti-patterns.

#### AP-OB-001: Missing Audit Logging
**Pattern**: No stage markers or boundary logging around reads, transforms, writes
**Risk**: No observability — impossible to diagnose failures or data loss in production
**Fix**: Add `logger.info()` at pipeline stage start/end and at read/write boundaries with row counts
```python
# FIX
logger.info("=== Stage: %s ===", stage_name)
logger.info("Read: %d rows from %s", df.count(), source_path)
# ... transformations ...
logger.info("Written: %d rows to %s", final_count, output_path)
```

#### AP-OB-002: Missing Empty Dataset Guard
**Pattern**: Pipeline continues silently when a read or transformation produces zero rows
**Risk**: Downstream writes overwrite valid data with empty output
**Fix**: Add empty dataset check after reads and major transformations
```python
# FIX
if df.count() == 0:
    logger.warning("Empty dataset at step: %s — aborting", step_name)
    raise ValueError(f"Empty dataset detected at {step_name}")
```

#### AP-OB-003: External Read Without Explicit Schema
**Pattern**: `.read.parquet()`, `.read.csv()`, `.read.json()` on external sources without `.schema()`
**Risk**: Silent schema drift — source schema changes corrupt downstream logic without error
**Detection**: Any external read without `.schema(expected_schema)` — same as AP-DP-005 but enforced here as HIGH severity observability gap
**Fix**: Add explicit `StructType` schema on all external reads (already covered by AP-DP-005 — skip if already fixed)

#### AP-OB-004: Missing Column Presence Validation
**Pattern**: Pipeline assumes required columns exist without checking
**Risk**: `AnalysisException` at runtime instead of a clear validation error at pipeline start
**Fix**: Add column presence check before processing
```python
# FIX
required_cols = ["id", "date", "amount"]
missing = [c for c in required_cols if c not in df.columns]
if missing:
    raise ValueError(f"Missing required columns: {missing}")
```

#### AP-OB-005: Null Monitoring on Critical Columns
**Pattern**: No null count logging for join keys or business-critical columns
**Risk**: Null values silently excluded from joins, causing undetected data loss
**Fix**: Log null counts for critical columns after reads (complements AP-DP-006 null filter)
```python
# FIX
for col_name in critical_columns:
    null_count = df.filter(F.col(col_name).isNull()).count()
    if null_count > 0:
        logger.warning("Nulls in %s: %d rows", col_name, null_count)
```

#### AP-OB-006: Missing Environment-Based Configuration
**Pattern**: No environment separation — same hardcoded values used across dev/staging/prod
**Risk**: Dev pipelines accidentally write to production paths
**Detection**: No `env`, `environment`, or `stage` parameter/widget present in pipeline
**Fix**: Add environment parameter and derive paths/table names from it (complements AP-DP-007)
```python
# FIX
env = dbutils.widgets.get("environment")  # or getResolvedOptions / notebookutils
output_path = config[f"{env}_output_path"]
```

#### AP-OB-007: Non-Safe Write Mode
**Pattern**: `append` mode write without deduplication, or no explicit write mode
**Risk**: Duplicate data on pipeline re-run or retry
**Detection**: `.write.mode("append")` without preceding `.dropDuplicates()`, or `.write` without `.mode()`
**Fix**: Use `overwrite` for full loads, `merge`/`upsert` for incremental, or add dedup before append
```python
# FIX — full load
df.write.mode("overwrite").parquet(path)

# FIX — incremental
delta_table.alias("t").merge(
    df.alias("s"), "t.id = s.id"
).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
```

#### AP-OB-008: Missing Execution Timing
**Pattern**: No timing instrumentation on pipeline stages
**Risk**: No baseline for performance regression detection after conversion
**Fix**: Add `time.time()` markers around major stages
```python
import time
start = time.time()
# ... stage processing ...
logger.info("Stage '%s' completed in %.2fs", stage_name, time.time() - start)
```

## Execution Process

### Step 1: Scan Converted Code
- Parse all code lines
- Match against anti-pattern signatures from all 4 categories
- Build findings list with pattern ID, location, severity

### Step 2: Prioritize Findings
| Severity | Description | Action |
|----------|-------------|--------|
| CRITICAL | Data correctness risk | Must fix |
| HIGH | Performance/reliability risk | Should fix |
| MEDIUM | Best practice violation | Fix if safe |
| LOW | Style/convention | Note only |

### Step 3: Apply Fixes
Apply in order: Categories 1 → 2 → 3 → 4
1. Verify the fix won't alter business logic
2. Apply the code transformation
3. Record before/after code snippet
4. Update the business logic catalog (from analyzer) to verify preservation

### Step 4: Produce Fix Report

```yaml
anti_pattern_report:
  total_scanned: <line_count>
  total_found: <count>
  total_fixed: <count>
  total_deferred: <count>   # Couldn't safely fix

  findings:
    - id: AP-DP-001
      severity: CRITICAL
      location: "line 45"
      description: ".collect() on unfiltered DataFrame"
      status: FIXED
      before: |
        all_rows = df.collect()
      after: |
        sample_rows = df.take(100)

    - id: AP-OB-003
      severity: HIGH
      location: "line 12"
      description: "External read without explicit schema"
      status: FIXED
      before: |
        df = spark.read.parquet(external_path)
      after: |
        df = spark.read.schema(expected_schema).parquet(external_path)

  summary:
    critical_fixed: <N>
    high_fixed: <N>
    medium_fixed: <N>
    low_noted: <N>
    business_logic_preserved: true|false   # MUST be true
```

## Safety Rules

1. **NEVER remove or alter business logic** (filters, joins, aggregations, column derivations)
2. **NEVER change output schemas** (column names, types, order)
3. **NEVER change data output paths** (only parameterize them)
4. **NEVER change join conditions** (only add null safety around them)
5. **ALWAYS verify business logic catalog after fixes** — every BL-XXX must still be present
6. If a fix risks altering business logic → Mark as `DEFERRED` with explanation
