# Configuration Preservation Validation

Validates that all configuration values, business logic, and schemas are preserved during conversion.

## Validation Checks

### V-CFG-001: All Spark Configs Preserved
**Rule:** Every `spark.conf.set()` or builder `.config()` from source must exist in target.
**Severity:** WARNING
**Detection:** Extract all Spark config keys from source, verify each exists in target.

### V-CFG-002: All Parameters Preserved
**Rule:** Every parameter from source must have an equivalent in target.
**Severity:** ERROR
**Detection:**
- Source `getResolvedOptions` params → target `dbutils.widgets` or `mssparkutils.notebook.params`
- Source `dbutils.widgets` → target equivalent
- Count: source param count must equal target param count

### V-CFG-003: All Read Paths Preserved
**Rule:** Every data read operation in source must have a corresponding read in target.
**Severity:** ERROR
**Detection:** Count `spark.read` / `glueContext.create_dynamic_frame` in source vs target.

### V-CFG-004: All Write Paths Preserved
**Rule:** Every data write operation in source must have a corresponding write in target.
**Severity:** ERROR
**Detection:** Count `.write.` / `glueContext.write_dynamic_frame` in source vs target.

### V-CFG-005: Business Logic Preservation
**Rule:** Transformations (filters, joins, aggregations, column operations) must be unchanged.
**Severity:** CRITICAL
**Detection:**
- Count `.filter()` / `.where()` calls: source == target
- Count `.join()` calls: source == target
- Count `.groupBy()` / `.agg()` calls: source == target
- Count `.select()` / `.withColumn()` calls: source >= target (may merge ApplyMapping)
- Verify join conditions are identical
- Verify filter conditions are identical

### V-CFG-006: Schema Preservation
**Rule:** Column names and data types must not change.
**Severity:** CRITICAL
**Detection:**
- All column aliases in source exist in target
- Cast operations preserve the same target types
- No columns dropped that exist in source output

### V-CFG-007: Execution Order Preserved
**Rule:** The sequence of operations must follow the same logical order as source.
**Severity:** ERROR
**Detection:** Verify read → transform → write sequence matches source ordering.

## Scoring Impact

| Check | Category | Points at Risk |
|-------|----------|---------------|
| V-CFG-001 | Execution Engine | 2 pts |
| V-CFG-002 | Execution Engine | 3 pts |
| V-CFG-003 | Data Integrity | 3 pts |
| V-CFG-004 | Data Integrity | 3 pts |
| V-CFG-005 | Data Integrity | 5 pts |
| V-CFG-006 | Data Integrity | 4 pts |
| V-CFG-007 | Data Integrity | 3 pts |
