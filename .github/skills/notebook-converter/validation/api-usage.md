# API Usage Validation

Validates that converted code uses only target platform APIs with no source platform artifacts.

## Validation Checks

### V-API-001: No Platform Utility Mixing
**Rule:** Do NOT mix platform utilities in one file.
**Severity:** ERROR
**Detection:** Flag if more than one of these groups appears:
- Group A (AWS): `boto3`, `GlueContext`, `DynamicFrame`, `getResolvedOptions`
- Group B (Databricks): `dbutils.widgets`, `dbutils.secrets`, `dbutils.fs`
- Group C (Synapse/Fabric): `mssparkutils.credentials`, `mssparkutils.fs`, `mssparkutils.notebook`

### V-API-002: No Source Platform Imports Remaining
**Rule:** All source-platform-specific imports must be removed.
**Severity:** ERROR
**Detection by target:**
- Databricks target: Flag `from awsglue`, `from notebookutils`, `from google.cloud`
- Synapse target: Flag `from awsglue`, `import dbutils`, `from google.cloud`
- Glue target: Flag `from notebookutils`, `import dbutils`

### V-API-003: No Source API Calls Remaining
**Rule:** No source platform API calls should remain in converted code.
**Severity:** ERROR
**Detection by target:**
- Databricks target: Flag `glueContext.`, `mssparkutils.`, `job.commit()`, `boto3.client('secretsmanager')`
- Synapse target: Flag `glueContext.`, `dbutils.`, `job.commit()`, `boto3.client('secretsmanager')`
- Glue target: Flag `dbutils.`, `mssparkutils.`

### V-API-004: Storage Protocol Consistency
**Rule:** All storage paths must use the target platform protocol.
**Severity:** ERROR
**Detection:**
- Azure target: Flag any `s3://`, `s3a://`, `gs://` paths
- AWS target: Flag any `abfss://`, `wasbs://` paths
- Mixed protocols in same file: Flag any combination

### V-API-005: Correct Secret Access
**Rule:** Secrets must use target platform secret service.
**Severity:** ERROR
**Detection:**
- Databricks target: Must use `dbutils.secrets.get()`, flag `mssparkutils.credentials`, `boto3.client('secretsmanager')`
- Synapse target: Must use `mssparkutils.credentials.getSecret()`, flag `dbutils.secrets`, `boto3.client('secretsmanager')`

## Auto-Fix Actions

| Check | Auto-Fix |
|-------|----------|
| V-API-001 | Remove non-target utility calls |
| V-API-002 | Remove leftover source imports |
| V-API-003 | Convert remaining source API calls |
| V-API-004 | Convert remaining wrong-protocol paths |
| V-API-005 | Convert remaining secret access calls |
