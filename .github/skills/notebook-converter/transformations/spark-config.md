# Spark Configuration Migration

Handles migration of Spark configuration settings between platforms.

## SparkSession Normalization

### Platforms with Pre-initialized SparkSession
- **Databricks**: `spark` variable pre-exists
- **Synapse**: `spark` variable pre-exists
- **Fabric**: `spark` variable pre-exists

### Platforms Requiring Manual Initialization
- **AWS Glue**: Requires GlueContext + spark extraction
- **AWS EMR**: Requires `SparkSession.builder`

## Conversion Rules

### Source Has Manual Initialization → Target Pre-initializes

**Remove manual SparkSession creation:**
```python
# REMOVE these:
spark = SparkSession.builder.getOrCreate()
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
```

**Replace with:**
```python
# SparkSession already provided by the platform
```

### Preserve Embedded Spark Configs

If source embeds config in the builder chain:
```python
spark = SparkSession.builder \
    .config("spark.sql.shuffle.partitions", 200) \
    .config("spark.sql.adaptive.enabled", "true") \
    .getOrCreate()
```

Extract configs and apply separately on pre-initialized platforms:
```python
# SparkSession already provided by the platform
spark.conf.set("spark.sql.shuffle.partitions", 200)
spark.conf.set("spark.sql.adaptive.enabled", "true")
```

### Target Requires Manual Initialization

**Glue target:**
```python
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)
```

**EMR target:**
```python
spark = SparkSession.builder \
    .appName("job_name") \
    .getOrCreate()
```

## EMR-Specific S3 Optimizations

When target is EMR, add S3A performance configs:
```python
spark.conf.set("spark.hadoop.fs.s3a.fast.upload", "true")
spark.conf.set("spark.hadoop.fs.s3a.multipart.size", "104857600")
spark.conf.set("spark.hadoop.fs.s3a.connection.maximum", "100")
spark.conf.set("spark.hadoop.fs.s3.consistent", "true")
```

## Platform Capability Table

| Capability | AWS Glue | Databricks | Synapse | EMR | Fabric |
|-----------|----------|-----------|---------|-----|--------|
| SparkSession | Manual | Pre-initialized | Pre-initialized | Manual | Pre-initialized |
| SparkContext | Manual | Already exists | Already exists | Manual | Already exists |
| Utilities | boto3 | dbutils | mssparkutils | boto3 | mssparkutils |

## Rules

1. Detect ALL Spark config settings in source code
2. Remove redundant SparkSession/SparkContext creation for pre-initialized targets
3. Extract and preserve ALL Spark configs from builder chains
4. Re-apply extracted configs via `spark.conf.set()` on pre-initialized platforms
5. Add platform-specific performance configs for EMR target
6. Do NOT lose any Spark configuration during conversion
