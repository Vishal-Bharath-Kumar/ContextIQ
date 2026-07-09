# Workflow Plan Parser

Parses workflow-related entries from `conversion-plan.md` and extracts structured conversion instructions for the workflow execution engine.

## Input

**File:** `.propel/context/pipelines/conversion-plan.md` (same plan used by notebook converter)

Workflow files are identified by their file type (`.json`, `.yaml`, `.yml`) and the workflow detection results in the plan.

## Parsing Rules

### Step 1: Identify Workflow File Entries

Scan the plan for file entries where:
- File extension is `.json`, `.yaml`, or `.yml`
- File type is classified as "workflow" or "orchestration"
- OR workflow_type field is present (e.g., "adf", "glue_workflow", "databricks_workflow", "step_functions")

### Step 2: Extract Per-File Workflow Fields

For each workflow file entry, extract:

```yaml
workflow_entry:
  source_file: string              # Path to workflow file
  workflow_type: string            # Detected type: adf, glue_workflow, databricks_workflow, step_functions
  source_workflow_adapter: string  # Source adapter name (may match workflow_type)
  target_workflow_adapter: string  # Target adapter name
  transformation: string           # Default: "workflow_transform"
  output_file: string              # Target output filename
  confidence: float                # Detection confidence
```

### Step 3: Resolve Adapter Names

```
IF source_workflow_adapter is specified in plan → use directly
ELSE IF workflow_type is specified → use as source_workflow_adapter
ELSE → ERROR: "Cannot determine source workflow adapter for file: {path}"

IF target_workflow_adapter is specified in plan → use directly
ELSE:
  Derive from plan's target_engine:
    Databricks → "databricks_workflow"
    Synapse → "adf"
    Fabric → "fabric_pipeline"
    Glue → "glue_workflow" (not a target adapter, ERROR)
    EMR → "step_functions" (or "databricks_workflow")
```

### Step 4: Apply Global Defaults

If the plan has a global Workflow Conversion Strategy block:
```
Workflow Conversion Strategy:
  source_workflow_adapter: <platform>
  target_workflow_adapter: <platform>
  transformation: workflow_transform
```

Use these as defaults for any workflow entry missing adapter fields.

## Output Structure

```yaml
workflow_plan:
  files:
    - source_file: "pipeline.json"
      source_workflow_adapter: "adf"
      target_workflow_adapter: "databricks_workflow"
      transformation: "workflow_transform"
      output_file: "pipeline_databricks.yaml"
      workflow_type: "adf"
      confidence: 95.0
```

## Validation

1. At least one workflow file entry exists (or skip workflow conversion entirely)
2. Every entry has non-empty `source_workflow_adapter` and `target_workflow_adapter`
3. All adapter names correspond to existing files in `adapters/source/` or `adapters/target/`
4. If validation fails → print specific errors and continue with notebook conversion only
