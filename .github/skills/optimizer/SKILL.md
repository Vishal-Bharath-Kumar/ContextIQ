---
name: optimizer
description: Enhances converted pipelines with production-grade improvements (error handling, logging, caching, resource cleanup) while preserving all business logic. Invoked after anti-pattern fixing as a post-processing step.
---

# Code Optimizer

Enhances converted cloud data pipelines with production-grade improvements.

## Optimization Strategy

Analyze converted code and apply improvements based on patterns detected.

### ALWAYS Add
- Error handling around I/O operations (try-except)
- Logging for key operations (read, transform, write)
- Resource cleanup in finally blocks

### INTELLIGENTLY Add (Based on Code Analysis)
- **Caching**: Only if DataFrame used 2+ times
- **Broadcast**: Only for joins with small tables (<10MB)
- **Partitioning**: Only for large writes
- **Functions**: Only if monolithic (>50 lines) or repeated patterns
- **Schema validation**: Only if reading external data
- **Retry logic**: Only for external I/O operations

### NEVER Change
- Business logic (filters, joins, aggregations, transformations)
- Column names, data types, or schemas
- Output paths or formats
- Platform-specific APIs (already converted)

## Optimization Categories

### 1. Performance
- `.cache()` when DataFrame used multiple times
- `broadcast()` for joins with small tables
- `.repartition()` / `.partitionBy()` for large writes
- Replace `.collect()` with `.foreach()` or aggregations

### 1a. Databricks-Specific Performance (Post-Enhancement)
If the Databricks Enhancement Detection step (from notebook-converter) was executed and the user opted in, the following features may already be present in the code. The optimizer must **recognize and preserve** them — do not duplicate or conflict with:
- **Auto Loader** (`cloudFiles` format reads + streaming writes with checkpoints)
- **Delta Live Tables** (`@dlt.table` decorators, `dlt.read()` calls)
- **Z-Order / Liquid Clustering** (`OPTIMIZE ... ZORDER BY` or `CLUSTER BY` statements)
- **COPY INTO** (SQL-based idempotent file loading)
- **Change Data Feed** (`delta.enableChangeDataFeed` table property)
- **OPTIMIZE** (table compaction SQL commands)

If these features are detected in the code, do NOT add conflicting patterns:
- Do NOT add `.cache()` on DLT-managed tables (DLT handles caching internally)
- Do NOT add manual retry/checkpoint logic around Auto Loader streams (already handled)
- Do NOT add `.repartition()` before writes to Z-Ordered or Liquid Clustered tables (conflicts with optimization)
- Do NOT wrap `COPY INTO` in try-except retry loops (already idempotent)

### 2. Error Handling
```python
try:
    df = spark.read.format("parquet").load(input_path)
    if df.count() == 0:
        logger.warning("Empty dataset read from %s", input_path)
except Exception as e:
    logger.error("Failed to read from %s: %s", input_path, str(e))
    raise
```

### 3. Logging
```python
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

logger.info("Reading data from %s", input_path)
logger.info("Loaded %d rows", df.count())
logger.warning("Found %d null values in column %s", null_count, col)
logger.error("Write failed: %s", str(e))
```

### 4. Resource Management
```python
try:
    df = spark.read.load(path)
    df.cache()
    # ... operations ...
finally:
    df.unpersist()
    spark.catalog.clearCache()
```

## Process

1. **Analyze** converted code for optimization opportunities
2. **Apply** targeted improvements (error handling, logging, caching)
3. **Preserve** all business logic and execution order
4. **Return** optimized code
