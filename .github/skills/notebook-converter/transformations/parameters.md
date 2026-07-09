# Parameter Conversion Rules

Handles conversion of pipeline parameters and argument parsing between platforms.

## AWS Glue → Azure Databricks

**Source pattern:**
```python
args = getResolvedOptions(sys.argv, ['JOB_NAME', 'param1', 'param2', 'param3'])
job_name = args['JOB_NAME']
param1 = args['param1']
param2 = args['param2']
```

**Target pattern (Databricks widgets):**
```python
dbutils.widgets.text("param1", "", "Parameter 1")
dbutils.widgets.text("param2", "", "Parameter 2")
dbutils.widgets.text("param3", "", "Parameter 3")

param1 = dbutils.widgets.get("param1")
param2 = dbutils.widgets.get("param2")
param3 = dbutils.widgets.get("param3")
```

**Rules:**
- Extract all parameter names from `getResolvedOptions` array
- Skip `JOB_NAME` (Glue-specific, not needed in Databricks)
- Create one `dbutils.widgets.text()` per parameter
- Create one `dbutils.widgets.get()` per parameter
- Place widget definitions at the SAME position in the code flow as the original `getResolvedOptions`

## AWS Glue → Azure Synapse

**Target pattern (Synapse parameters):**
```python
param1 = mssparkutils.notebook.params.get("param1", "")
param2 = mssparkutils.notebook.params.get("param2", "")
```

## Azure Databricks → AWS Glue

**Source:**
```python
dbutils.widgets.text("param1", "", "Label")
param1 = dbutils.widgets.get("param1")
```

**Target:**
```python
args = getResolvedOptions(sys.argv, ['JOB_NAME', 'param1'])
param1 = args['param1']
```

## Azure Synapse → Databricks

**Source:**
```python
param1 = mssparkutils.notebook.params.get("param1", "")
```

**Target:**
```python
dbutils.widgets.text("param1", "", "param1")
param1 = dbutils.widgets.get("param1")
```

## Flow Preservation Rule

Parameters must remain at the SAME position in the code flow as in the source file. Do NOT move parameter definitions to a separate "Configuration" section.
