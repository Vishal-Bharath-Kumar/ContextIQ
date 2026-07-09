# Initialization Validation

Validates that platform initialization is correct in converted code.

## Validation Checks

### V-INIT-001: No Redundant SparkSession Creation
**Rule:** Target platforms with pre-initialized SparkSession (Databricks, Synapse, Fabric) must NOT contain manual SparkSession creation.
**Severity:** WARNING
**Detection:**
```python
# Flag if found on Databricks/Synapse/Fabric target:
SparkSession.builder
SparkSession.builder.getOrCreate()
SparkSession.builder.config(...).getOrCreate()
```

### V-INIT-002: No Redundant SparkContext Creation
**Rule:** Do not create SparkContext on platforms that manage it.
**Severity:** WARNING
**Detection:**
```python
# Flag if found on Databricks/Synapse/Fabric target:
sc = SparkContext()
SparkContext()
```

### V-INIT-003: Required Glue Initialization
**Rule:** AWS Glue target must have complete initialization sequence.
**Severity:** ERROR
**Required:**
```python
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)
```

### V-INIT-004: Glue Job Commit
**Rule:** AWS Glue target must end with `job.commit()`.
**Severity:** ERROR
**Detection:** Check last executable statement includes `job.commit()`.

### V-INIT-005: Builder-Chain Configs Preserved
**Rule:** If source had Spark configs in builder chain, they must be preserved via `spark.conf.set()`.
**Severity:** WARNING
**Detection:** Compare source builder configs with target `spark.conf.set()` calls.

## Auto-Fix Actions

| Check | Auto-Fix |
|-------|----------|
| V-INIT-001 | Remove redundant SparkSession.builder |
| V-INIT-002 | Remove redundant SparkContext() |
| V-INIT-003 | Add missing Glue initialization block |
| V-INIT-004 | Add `job.commit()` at end of script |
| V-INIT-005 | Add missing `spark.conf.set()` calls |
