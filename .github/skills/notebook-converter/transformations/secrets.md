# Secrets Handling Conversion

Handles conversion of secrets/credential access between cloud platforms.

## Platform Secret Patterns

### AWS (boto3 Secrets Manager)
```python
import boto3
import json

client = boto3.client('secretsmanager', region_name='us-east-1')
response = client.get_secret_value(SecretId='my-secret-id')
secret = json.loads(response['SecretString'])
password = secret['password']
```

### Azure Synapse (mssparkutils)
```python
password = mssparkutils.credentials.getSecret("keyvault-name", "secret-key")
```

### Azure Databricks (dbutils)
```python
password = dbutils.secrets.get(scope="my-scope", key="secret-key")
```

### GCP (Secret Manager)
```python
from google.cloud import secretmanager

client = secretmanager.SecretManagerServiceClient()
name = f"projects/project-id/secrets/secret-name/versions/latest"
response = client.access_secret_version(name=name)
secret = response.payload.data.decode("UTF-8")
```

### Azure Fabric (mssparkutils)
```python
password = mssparkutils.credentials.getSecret("keyvault-name", "secret-key")
```

## Conversion Matrix

| Source | Target | Conversion |
|--------|--------|-----------|
| AWS boto3 → Synapse | Replace boto3 client with `mssparkutils.credentials.getSecret()` |
| AWS boto3 → Databricks | Replace boto3 client with `dbutils.secrets.get()` |
| Synapse → Databricks | Replace `mssparkutils.credentials` with `dbutils.secrets.get()` |
| Databricks → Synapse | Replace `dbutils.secrets.get()` with `mssparkutils.credentials.getSecret()` |
| Synapse → AWS | Replace `mssparkutils.credentials` with boto3 secretsmanager client |
| Databricks → AWS | Replace `dbutils.secrets.get()` with boto3 secretsmanager client |
| GCP → Databricks | Replace google.cloud secretmanager with `dbutils.secrets.get()` |
| GCP → Synapse | Replace google.cloud secretmanager with `mssparkutils.credentials.getSecret()` |

## Rules

1. Convert ALL secret access patterns to target platform
2. NEVER leave hardcoded credentials in the converted code
3. Map secret names/keys consistently (document mapping in comments if names differ)
4. Remove source-platform secret client imports when converting
5. Add target-platform secret client imports as needed
6. Preserve the variable names that hold the retrieved secret values
