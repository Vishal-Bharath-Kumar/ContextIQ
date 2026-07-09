# Storage Path Translation Rules

Handles conversion of cloud storage paths between platforms.

## Path Conversion Patterns

### AWS S3 → Azure ADLS (abfss)

**Pattern:**
```
s3://bucket-name/path/to/data/
→
abfss://container@storageaccount.dfs.core.windows.net/path/to/data/
```

**Rules:**
- Replace `s3://` protocol with `abfss://`
- Map bucket name to container@storageaccount format
- Preserve the path portion after the bucket/container
- Handle both `s3://` and `s3a://` prefixes

### Azure ADLS → AWS S3

**Pattern:**
```
abfss://container@storageaccount.dfs.core.windows.net/path/to/data/
→
s3://bucket-name/path/to/data/
```

**Also convert:**
```
wasbs://container@storageaccount.blob.core.windows.net/path/
→
s3://bucket-name/path/
```

### GCP GCS → Azure ADLS

**Pattern:**
```
gs://bucket-name/path/to/data/
→
abfss://container@storageaccount.dfs.core.windows.net/path/to/data/
```

### GCP GCS → Databricks

**Pattern:**
```
gs://bucket-name/path/
→
abfss://container@storageaccount.dfs.core.windows.net/path/  (Azure Databricks)
OR
s3://bucket-name/path/  (AWS Databricks)
```

### Databricks Mount Paths

**Note:** If source uses `/mnt/` or `dbfs:/mnt/` paths, these are mount-based and need the underlying storage path resolved:
```
/mnt/data/path/ → abfss://container@storage.dfs.core.windows.net/path/
dbfs:/mnt/data/path/ → abfss://container@storage.dfs.core.windows.net/path/
```

## Parameterized Paths

When paths contain variables, convert the base path pattern but preserve the variable:
```python
# Source
path = f"s3://{bucket}/{prefix}/data/"

# Target
path = f"abfss://{container}@{storage_account}.dfs.core.windows.net/{prefix}/data/"
```

## Rules

1. Convert ALL storage path references in the file
2. Handle paths in string literals, f-strings, and variables
3. Preserve the directory structure after the container/bucket
4. Do NOT hardcode specific container/storage account names — use variables
5. Convert paths in both read and write operations
