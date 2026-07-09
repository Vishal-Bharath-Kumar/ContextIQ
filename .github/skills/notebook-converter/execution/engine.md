# Adapter-Based Execution Engine

Generic, config-driven conversion engine that reads a conversion plan, dynamically loads source/target adapter YAML files, applies the specified transformation strategy, and generates converted notebooks.

## Design Principles

- **NO hardcoded platform-to-platform mappings** — all routing resolved via `adapters/source/*.yaml` and `adapters/target/*.yaml`
- **NO if/else or switch-case** for platform combinations
- **Fully config-driven** via adapter YAML files
- **Adapter-driven execution** — the engine is generic; adapters carry all platform knowledge
- **Adding a new platform = adding one YAML adapter file, zero engine changes**
- **Plan = single source of truth** — the engine trusts the plan completely, no re-detection
- **Adapters = execution only** — source adapters read, target adapters transform; neither detects
- **Full notebook processing ONLY** — always read ALL cells, ALL metadata, no truncation, no partial reads
- **Execution logging** — every adapter call is logged with `[INFO]` / `[SUCCESS]` / `[ERROR]` in chat

## Required References

Load before execution:
- `core/adapter-loader.md` — Adapter discovery and YAML schema validation
- `core/plan-parser.md` — Conversion plan parsing rules
- `transformations/lift-and-shift.md` — Lift-and-shift transformation rules (or whichever transformation the plan specifies)
- Source adapter YAML — `adapters/source/{source_adapter}.yaml`
- Target adapter YAML — `adapters/target/{target_adapter}.yaml`

## Execution Workflow

```
conversion-plan.md
       │
       ▼
┌──────────────────────┐
│  1. Parse Plan       │  ← core/plan-parser.md
│     Extract:         │
│     - source_adapter │
│     - target_adapter │
│     - transformation │
│     - file list      │
└──────────┬───────────┘
           │
    ┌──────┴────── FOR EACH FILE ──────┐
    │                                   │
    ▼                                   │
┌──────────────────────┐                │
│  2. Load Adapters    │  ← core/adapter-loader.md
│     source.yaml      │                │
│     target.yaml      │                │
└──────────┬───────────┘                │
           │                            │
           ▼                            │
┌──────────────────────┐                │
│  3. Read Source      │                │
│     Parse notebook   │                │
│     Extract cells    │                │
└──────────┬───────────┘                │
           │                            │
           ▼                            │
┌──────────────────────┐                │
│  4. Apply Transform  │  ← transformations/{strategy}.md
│     source.read()    │                │
│     → transform()    │                │
│     → target.write() │                │
└──────────┬───────────┘                │
           │                            │
           ▼                            │
┌──────────────────────┐                │
│  5. Write Target     │                │
│     Generate output  │                │
│     notebook/script  │                │
└──────────┬───────────┘                │
           │                            │
           └────────────────────────────┘
```

## Step-by-Step Instructions

### Step 1: Parse Conversion Plan

**Input:** Path to `conversion-plan.md` (default: `.propel/context/pipelines/conversion-plan.md`)

Follow `core/plan-parser.md` rules to extract:
- Global metadata: `target_cloud`, `target_engine`, `output_format`, `output_dir`
- Per-file entries: `source_file`, `source_adapter`, `target_adapter`, `transformation`, `output_file`

**Validation Gate:**
- If plan has zero parseable file entries → STOP with "No convertible files found in plan"
- Print: "Plan loaded: {N} file(s) to convert"
- Print: "Route: {source_adapter} → [{transformation}] → {target_adapter}"

### Step 2: Load Adapters (Per File)

**Print:** `[INFO] Plan Loaded — {N} file(s) to convert`
**Print:** `[INFO] Source: {source_platform}`
**Print:** `[INFO] Target: {target_platform}`

For each file entry in the plan:

1. **Load source adapter:**
   ```
   READ adapters/source/{entry.source_adapter}.yaml
   PARSE YAML → source_adapter object
   VALIDATE per core/adapter-loader.md validation rules
   ```

2. **Load target adapter:**
   ```
   READ adapters/target/{entry.target_adapter}.yaml
   PARSE YAML → target_adapter object
   VALIDATE per core/adapter-loader.md validation rules
   ```

3. **If either adapter not found** → ERROR with available adapters listed, skip this file

**CRITICAL:** This step uses ONLY the platform name from the plan. No hardcoded routing tables. No lookup maps. The adapter file path is derived purely from the name: `adapters/{type}/{name}.yaml`.

### Step 3: Read Source File

**CRITICAL — FULL READ ENFORCEMENT:**
The source adapter declares `read.mode: full` and `rules: [do_not_detect_source, read_complete_notebook]`. The engine MUST honor these rules:
- Read the ENTIRE source file — no truncation, no partial reads, no chunk-based processing
- For large notebooks (50+ cells, 100KB+), still read ALL cells completely
- Do NOT re-detect the source platform — it is already known from the plan

**Print:** `[INFO] Calling Source Adapter: {source_adapter_name}`
**Print:** `[INFO] Reading FULL notebook...`

Read the source notebook/script and extract code content:

**For `.ipynb` files:**
- Parse COMPLETE JSON structure
- Extract EVERY cell (both `cell_type == "code"` and `cell_type == "markdown"`)
- Collect cell source content as a list of code blocks
- Preserve cell order — no reordering
- Preserve ALL metadata
- **Print:** `[INFO] Read {total_cells} cells ({code_cells} code, {markdown_cells} markdown)`

**For `.py` files:**
- Read FULL file content — entire file, no truncation
- Split into logical blocks by:
  - `# COMMAND ----------` separator (Databricks style)
  - `# %%` separator (VS Code / Jupyter style)
  - Or treat as single block if no separators found

**For `.sql` files:**
- Read full file content
- Treat as single block

Output: Ordered list of source code cells/blocks.

### Step 4: Apply Transformation

**Print:** `[INFO] Calling Target Adapter: {target_adapter_name}`
**Print:** `[INFO] Applying transformations: {transformation_strategy}`

Load the transformation reference file specified in the plan entry:

```
READ transformations/{entry.transformation}.md
```

**For `lift_and_shift` transformation** (follow `transformations/lift-and-shift.md`):

Execute these sub-steps IN ORDER on each source cell:

#### 4a. Import Conversion
```
FOR each import in source_adapter.imports.remove:
    REMOVE matching lines from source code
FOR each import in target_adapter.imports.add:
    COLLECT into import block (to be added later)
KEEP all imports matching source_adapter.imports.keep patterns
```

#### 4b. Initialization Replacement
```
FIND source_adapter.read_logic.spark.initialization block in source code
REMOVE all lines from that block (skip comment-only lines)

IF target_adapter.runtime.spark_session == "pre-initialized":
    INSERT comment: "# SparkSession already provided by the platform"
ELSE:
    INSERT target_adapter.runtime.initialization block

IF source code contains SparkSession.builder.config() chain:
    EXTRACT each .config("key", "value") pair
    FOR each extracted config:
        INSERT: spark.conf.set("{key}", "{value}")
```

#### 4c. Parameter Conversion
```
DETECT source_adapter.parameters.format patterns in code:

IF source format is "getResolvedOptions":
    FIND: args = getResolvedOptions(sys.argv, ['JOB_NAME', 'param1', 'param2'])
    FOR each param (skip JOB_NAME):
        REPLACE with target_adapter.parameters.extraction template:
            e.g., dbutils.widgets.get("{param_name}") for Databricks
    REPLACE subsequent args['{param_name}'] references with the variable directly

IF source format is "mssparkutils":
    FIND: mssparkutils.env.* calls
    REPLACE with target_adapter.parameters.extraction template

IF source format is "dbutils.widgets":
    FIND: dbutils.widgets.get("{param_name}")
    REPLACE with target_adapter.parameters.extraction template

IF source format is "argparse":
    FIND: argparse patterns
    REPLACE with target_adapter.parameters.extraction template
```

#### 4d. Secret Conversion
```
DETECT source_adapter.secrets.method in code:

IF source method is "boto3_ssm":
    FIND: boto3 SSM get_parameter calls
    REPLACE with target_adapter.secrets read/write template

IF source method is "mssparkutils_credentials":
    FIND: mssparkutils.credentials.getSecret calls
    REPLACE with target_adapter.secrets template

IF source method is "dbutils_secrets":
    FIND: dbutils.secrets.get calls
    REPLACE with target_adapter.secrets template

IF source method is "google_secret_manager":
    FIND: google SecretManagerServiceClient calls
    REPLACE with target_adapter.secrets template
```

#### 4e. Storage Path Translation
```
source_prefix = source_adapter.storage.prefix    (e.g., "s3://")
target_prefix = target_adapter.storage.prefix    (e.g., "abfss://")

IF target_adapter.storage has nested cloud-specific keys (e.g., storage.azure.prefix):
    Resolve the appropriate sub-key based on plan.target_cloud

FIND all string occurrences of source_prefix in code
REPLACE with target_prefix

NOTE: For cross-cloud paths (s3:// → abfss://), the full path format changes.
      Use target_adapter.storage.path_format template for full path reconstruction.
```

#### 4f. Catalog Operation Mapping
```
Build catalog map from target_adapter.catalog.operations:
    normalized_pattern → target_specific_pattern

FOR each operation in source_adapter.catalog.operations:
    source_pattern = operation.source
    normalized_form = operation.normalized
    target_form = catalog_map[normalized_form]  (from target adapter)

    FIND source_pattern in code
    REPLACE with target_form
```

#### 4g. Finalization
```
IF source_adapter.read_logic.spark.finalization exists:
    FIND finalization lines (e.g., job.commit(), spark.stop())
    REMOVE from code

Clean up excessive blank lines (3+ consecutive → 2)
Remove empty cells/blocks
```

#### 4h. Assemble Output
```
cells = []

1. ADD target_adapter.notebook_format.header_cell as first cell (markdown)
2. ADD target imports block (collected in step 4a) as second cell
3. ADD target initialization (if not just a comment) as third cell
4. ADD all converted source cells in original order
```

### Step 5: Write Target Notebook

**Print:** `[SUCCESS] Conversion completed → {output_filename}`

Generate the output file based on `target_adapter.notebook_format`:

**If notebook_format.type == "ipynb":**
```json
{
  "nbformat": 4,
  "nbformat_minor": 5,
  "metadata": {
    "kernelspec": {
      "display_name": "Python 3",
      "language": "{notebook_format.metadata.language}",
      "name": "{notebook_format.metadata.kernel}"
    }
  },
  "cells": [
    {
      "cell_type": "markdown" or "code",
      "source": ["line1\n", "line2\n", "line3"],
      "metadata": {},
      "outputs": [],
      "execution_count": null
    }
  ]
}
```

**If notebook_format.type == "py":**
```
Join all cells with separator:
    {notebook_format.cell_separator} (default: "# %%")
Write as .py file
```

**Output path:** `{plan.output_dir}/{entry.output_file}`

### Step 6: Print Summary

After processing all files, print:

```
═══════════════════════════════════════════════════
ADAPTER ENGINE — CONVERSION SUMMARY
═══════════════════════════════════════════════════
Plan:           {plan_path}
Source Adapter:  {source_adapter}
Target Adapter:  {target_adapter}
Transformation:  {transformation}

Available Source Adapters: [glue, synapse, databricks, emr, dataproc, fabric, postgresql]
Available Target Adapters: [databricks, synapse, emr, fabric, bigquery]

| # | Source File | Route | Status | Output |
|---|------------|-------|--------|--------|
| 1 | file1.ipynb | glue → databricks | ✅ Success | file1_databricks.ipynb |
| 2 | file2.ipynb | glue → databricks | ✅ Success | file2_databricks.ipynb |

Total: {N} file(s) — {success} succeeded, {failed} failed, {skipped} skipped
═══════════════════════════════════════════════════
```

## Example Execution Flow

**Input:** source = glue, target = databricks, transformation = lift_and_shift

```
1. Parse plan → extract source_adapter: "glue", target_adapter: "databricks"
2. Load adapters/source/glue.yaml → source adapter loaded
3. Load adapters/target/databricks.yaml → target adapter loaded
4. Read source .ipynb → extract 5 code cells
5. Apply lift-and-shift:
   a. Remove: GlueContext, DynamicFrame, Job imports
   b. Add: "# Databricks notebook — no explicit SparkSession import needed"
   c. Remove: SparkContext(), GlueContext(), job.init() initialization
   d. Insert: "# SparkSession already provided by the platform"
   e. Convert: getResolvedOptions → dbutils.widgets.get
   f. Convert: boto3 SSM → dbutils.secrets.get
   g. Translate: s3:// → abfss://
   h. Map: DynamicFrame reads → spark.table()
   i. Remove: job.commit()
6. Write target .ipynb with Databricks kernel metadata
7. Print summary
```

## Extensibility

### Adding a New Source Platform
1. Create `adapters/source/{platform_name}.yaml` following `core/adapter-loader.md` schema
2. Include: detection indicators, read_logic, imports, parameters, secrets, storage, catalog
3. Done — engine automatically supports `source_adapter: {platform_name}`

### Adding a New Target Platform
1. Create `adapters/target/{platform_name}.yaml` following `core/adapter-loader.md` schema
2. Include: runtime, write_logic, imports, parameters, secrets, storage, catalog, notebook_format
3. Done — engine automatically supports `target_adapter: {platform_name}`

### Adding a New Transformation
1. Create `transformations/{transformation_name}.md`
2. Define the transformation rules (what changes, what stays, step-by-step logic)
3. Done — engine supports `transformation: {transformation_name}` in the plan

### Total Supported Combinations
```
Combinations = (source adapters) × (target adapters) × (transformations)
Current:       7                 ×  5                ×  1  = 35 routes
              (with zero hardcoded mappings)
```
