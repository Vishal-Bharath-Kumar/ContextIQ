# Catalog Operation Mapping

Handles conversion of data catalog operations (read/write) between platforms.

## AWS Glue Catalog → Spark SQL

### Read Operations

**AWS Glue (DynamicFrame from catalog):**
```python
dyf = glueContext.create_dynamic_frame.from_catalog(
    database="db_name",
    table_name="table_name",
    transformation_ctx="ctx_name"
)
df = dyf.toDF()
```

**Azure / Databricks (Spark SQL):**
```python
df = spark.read.table("db_name.table_name")
```

### Write Operations

**AWS Glue (DynamicFrame to catalog):**
```python
output_dyf = DynamicFrame.fromDF(df, glueContext, "output")
glueContext.write_dynamic_frame.from_catalog(
    frame=output_dyf,
    database="db_name",
    table_name="table_name"
)
```

**Azure / Databricks (Spark SQL):**
```python
df.write.mode("overwrite").saveAsTable("db_name.table_name")
```

### DynamicFrame Transformations → DataFrame

**AWS Glue:**
```python
mapped = ApplyMapping.apply(frame=dyf, mappings=[
    ("old_col", "string", "new_col", "string"),
    ("old_num", "long", "new_num", "int")
])
```

**Spark DataFrame:**
```python
df = df.select(
    F.col("old_col").alias("new_col").cast("string"),
    F.col("old_num").alias("new_num").cast("int")
)
```

**AWS Glue DropNullFields:**
```python
cleaned = DropNullFields.apply(frame=dyf)
```

**Spark DataFrame:**
```python
df = df.dropna()
```

## Azure → AWS Glue Catalog

### Read
```python
# Azure
df = spark.read.table("db_name.table_name")

# AWS Glue
dyf = glueContext.create_dynamic_frame.from_catalog(
    database="db_name", table_name="table_name"
)
df = dyf.toDF()
```

### Write
```python
# Azure
df.write.mode("overwrite").saveAsTable("db_name.table_name")

# AWS Glue
output_dyf = DynamicFrame.fromDF(df, glueContext, "output")
glueContext.write_dynamic_frame.from_catalog(
    frame=output_dyf, database="db_name", table_name="table_name"
)
```

## Fabric Lakehouse

### Read
```python
df = spark.read.format("delta").load("Tables/table_name")
```

### Write
```python
df.write.format("delta").mode("overwrite").save("Tables/table_name")
```

## Rules

1. Convert ALL catalog read/write operations to target platform equivalent
2. Only use DynamicFrame for Glue Catalog operations — keep DataFrame for file I/O
3. Preserve database and table name references
4. Maintain read/write modes (overwrite, append, etc.)
5. Keep all business transformations between read and write unchanged
