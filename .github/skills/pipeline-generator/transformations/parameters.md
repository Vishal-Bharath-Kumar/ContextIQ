# Workflow Parameter Conversion

Converts pipeline parameter formats between orchestration platforms.

## ADF Parameters → Databricks

**Source (ADF):**
```json
"parameters": {
  "param1": { "type": "String", "defaultValue": "value1" },
  "param2": { "type": "Int", "defaultValue": 100 }
}
```

**Target (Databricks base_parameters):**
```yaml
base_parameters:
  param1: "value1"
  param2: "100"
```

## ADF Parameters → Glue Arguments

**Target (Glue):**
```json
"Arguments": {
  "--param1": "value1",
  "--param2": "100"
}
```

**Rule:** Prefix all keys with `--` for Glue argument format.

## Glue Arguments → Databricks

**Source (Glue):**
```json
"Arguments": {
  "--param1": "value1",
  "--param2": "100"
}
```

**Target (Databricks):**
```yaml
base_parameters:
  param1: "value1"
  param2: "100"
```

**Rule:** Strip `--` prefix from Glue argument keys.

## Glue Arguments → ADF

**Target (ADF):**
```json
"parameters": {
  "param1": { "type": "String", "defaultValue": "value1" },
  "param2": { "type": "String", "defaultValue": "100" }
}
```

## Databricks Parameters → ADF

**Source (Databricks):**
```yaml
base_parameters:
  param1: "value1"
```

**Target (ADF):**
```json
"typeProperties": {
  "baseParameters": {
    "param1": "value1"
  }
}
```

## Rules

1. Preserve all parameter names (strip/add prefixes as needed)
2. Preserve all default values
3. Convert types where possible (Glue treats all as strings)
4. Map activity-level parameters to task-level parameters
