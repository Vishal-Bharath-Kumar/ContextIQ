# Import Conversion Rules

Handles the conversion of import statements between cloud platforms.

## Conversion Rules

### AWS Glue → Azure (Synapse / Databricks)

**Remove:**
```python
import sys
from awsglue.context import GlueContext
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.transforms import *
from awsglue.dynamicframe import DynamicFrame
from awsglue.job import Job
```

**Add (Synapse target):**
```python
from notebookutils import mssparkutils
```

**Add (Databricks target):**
No additional imports needed — `dbutils` is pre-injected.

**Keep (all targets):**
All standard imports: pyspark, datetime, uuid, re, delta, json, etc.

### Azure → AWS Glue

**Add:**
```python
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from awsglue.dynamicframe import DynamicFrame
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
```

**Remove:**
```python
from notebookutils import mssparkutils
```

### Azure Synapse → Databricks

**Remove:**
```python
from notebookutils import mssparkutils
```

**No additions** — `dbutils` is pre-injected by Databricks runtime.

### Databricks → Synapse

**Add:**
```python
from notebookutils import mssparkutils
```

**No removals** — `dbutils` references are converted in the API usage step.

### GCP Dataproc → Azure / Databricks

**Remove:**
```python
from google.cloud import bigquery
from google.cloud import storage
import google.auth
```

**Add (Synapse):**
```python
from notebookutils import mssparkutils
```

**Add (Databricks):**
No additional imports needed.

## Rules

1. Remove all source-platform-specific imports
2. Add target-platform-specific imports
3. Preserve all standard Python/PySpark imports
4. Preserve all business-logic imports (pandas, numpy, etc.)
5. Do NOT reorder existing preserved imports
