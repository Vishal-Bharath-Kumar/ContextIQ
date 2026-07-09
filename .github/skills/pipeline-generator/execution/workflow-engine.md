# Workflow Execution Engine

Generic, config-driven workflow conversion engine that reads a conversion plan, dynamically loads source/target workflow adapter YAML files, converts through a normalized intermediate schema, and generates target workflow files.

## Design Principles

- **NO hardcoded platform-to-platform mappings** — all routing resolved via `adapters/source/*.yaml` and `adapters/target/*.yaml`
- **NO if/else or switch-case** for platform combinations
- **Normalized intermediate schema** — source adapter produces it, target adapter consumes it
- **Adapter-driven execution** — all platform knowledge lives in adapter YAML files
- **Adding a new workflow platform = adding one YAML adapter file, zero engine changes**

## Required References

Load before execution:
- `core/workflow-adapter-loader.md` — Adapter discovery and YAML schema
- `core/workflow-plan-parser.md` — Plan parsing for workflow entries
- `core/normalized-schema.md` — Universal intermediate workflow representation
- `transformations/workflow-transform.md` — Generic transformation rules
- Source adapter YAML — `adapters/source/{source_workflow_adapter}.yaml`
- Target adapter YAML — `adapters/target/{target_workflow_adapter}.yaml`

## Execution Workflow

```
conversion-plan.md (workflow entries)
       │
       ▼
┌──────────────────────────┐
│  1. Parse Workflow Plan   │  ← core/workflow-plan-parser.md
│     Extract:              │
│     - source_workflow_adapter
│     - target_workflow_adapter
│     - workflow files      │
└──────────┬───────────────┘
           │
    ┌──────┴────── FOR EACH WORKFLOW FILE ──────┐
    │                                            │
    ▼                                            │
┌──────────────────────────┐                     │
│  2. Load Adapters         │  ← core/workflow-adapter-loader.md
│     source_adapter.yaml   │                     │
│     target_adapter.yaml   │                     │
└──────────┬───────────────┘                     │
           │                                      │
           ▼                                      │
┌──────────────────────────┐                     │
│  3. Parse Source File     │                     │
│     Read JSON/YAML        │                     │
│     Apply source adapter  │                     │
│     parsing rules         │                     │
└──────────┬───────────────┘                     │
           │                                      │
           ▼                                      │
┌──────────────────────────┐                     │
│  4. Normalize             │  ← core/normalized-schema.md
│     source → normalized   │                     │
│     Map types, deps,      │                     │
│     triggers, compute     │                     │
└──────────┬───────────────┘                     │
           │                                      │
           ▼                                      │
┌──────────────────────────┐                     │
│  5. Validate              │                     │
│     Check normalized      │                     │
│     schema integrity      │                     │
└──────────┬───────────────┘                     │
           │                                      │
           ▼                                      │
┌──────────────────────────┐                     │
│  6. Generate Target       │                     │
│     normalized → target   │                     │
│     Apply target adapter  │                     │
│     generation rules      │                     │
└──────────┬───────────────┘                     │
           │                                      │
           ▼                                      │
┌──────────────────────────┐                     │
│  7. Validate Output       │  ← validation/*.md  │
│     Structure, deps,      │                     │
│     compute, timeouts     │                     │
└──────────┬───────────────┘                     │
           │                                      │
           ▼                                      │
┌──────────────────────────┐                     │
│  8. Write Target File     │                     │
│     JSON or YAML output   │                     │
└──────────────────────────┘                     │
           │                                      │
           └──────────────────────────────────────┘
```

## Step-by-Step Instructions

### Step 1: Parse Workflow Plan

Follow `core/workflow-plan-parser.md` to extract workflow file entries from the conversion plan.

**Validation Gate:**
- If no workflow files found → print "No workflow files in plan. Skipping workflow conversion."
- Print: "Workflow plan: {N} file(s) to convert"
- Print: "Route: {source_workflow_adapter} → [workflow_transform] → {target_workflow_adapter}"

### Step 2: Load Adapters (Per File)

For each workflow file entry:

```
source_adapter = LOAD adapters/source/{entry.source_workflow_adapter}.yaml
target_adapter = LOAD adapters/target/{entry.target_workflow_adapter}.yaml
```

Follow `core/workflow-adapter-loader.md` rules. If adapter not found → ERROR, skip this file.

**CRITICAL:** This uses ONLY the adapter name from the plan. No routing table. No lookup map.

### Step 3: Parse Source File

Read the workflow file (JSON or YAML):

```
IF file extension is .json:
  Parse as JSON
IF file extension is .yaml or .yml:
  Parse as YAML
```

Then apply the source adapter's parsing rules:

```
workflow_name = extract using source_adapter.parsing.workflow_name path
raw_tasks     = extract using source_adapter.parsing.tasks_path
raw_triggers  = extract using source_adapter.parsing.triggers path (if exists)
raw_params    = extract using source_adapter.parsing.parameters path (if exists)
```

### Step 4: Normalize

Follow `transformations/workflow-transform.md` Step 2 (Normalize):

**4a. Normalize Tasks:**
```
FOR each raw task:
  Detect source type → look up in source_adapter.parsing.type_mapping
  Map to normalized_type
  Extract config keys per mapping
  Normalize parameters (strip prefixes, flatten)
  Normalize timeout (convert to seconds)
  Detect layer (bronze/silver/gold)
```

**4b. Normalize Dependencies:**
```
Follow source_adapter.dependencies.extraction_method:
  "direct"                  → extract depends_on arrays
  "dual_source"             → union Graph.Edges + conditional triggers
  "state_machine_traversal" → walk StartAt → Next chain

Map conditions using source_adapter.dependencies.condition_mapping
```

**4c. Normalize Triggers:**
```
Extract trigger info using source_adapter.triggers rules
Convert to normalized cron format (6-field: sec min hr dom mon dow)
Preserve timezone
```

**4d. Normalize Compute:**
```
Extract compute info using source_adapter.compute.extraction rules
Map worker types to tier (small/medium/large/xlarge)
Calculate vCPU and memory_gb
```

**4e. Assemble Normalized Workflow:**
```
Build the complete normalized_workflow object per core/normalized-schema.md
```

### Step 5: Validate Normalized Schema

Apply all validation rules from `core/normalized-schema.md`:

1. Unique task IDs
2. Valid dependency references
3. Acyclic graph (topological sort)
4. At least one root task
5. Valid task types from allowed list
6. Positive timeout values

If validation fails → ERROR with details, skip this file.

### Step 6: Generate Target

Follow `transformations/workflow-transform.md` Step 4 (Generate):

**6a. Generate Tasks:**
```
FOR each normalized task:
  Look up target_adapter.generation.task_generation.type_mapping[task.task_type]
  Build target task structure using the type mapping fields
  Sanitize task keys per target_adapter rules
  Map parameters to target format (using target_adapter.parameters.generation)
  Convert timeout to target format (using target_adapter.timeout.generation)
```

**6b. Generate Dependencies:**
```
Follow target_adapter.dependencies.generation rules
Map conditions: success/failure/completed → target-specific values
Omit empty dependency arrays for root tasks
```

**6c. Generate Triggers:**
```
Follow target_adapter.triggers.generation rules
Convert normalized cron → target cron format
Generate schedule structure per target adapter
```

**6d. Generate Compute:**
```
Follow target_adapter.compute.generation rules
Map tier → target node type using target_adapter.compute.node_type_mapping
Generate cluster/resource definitions
```

**6e. Assemble Target Workflow:**
```
Build the complete target workflow structure per target_adapter.generation.structure
Apply any wrappers (e.g., DAB resources.jobs wrapper for Databricks)
Add metadata tags (source_platform, conversion tracking)
```

### Step 7: Validate Output

Run validation checks (still available in `validation/` folder):
- `validation/structure.md` — Syntax, required fields, DAB compliance
- `validation/dependency.md` — Acyclic graph, valid references, order preserved
- `validation/timeout.md` — Layer policy caps, reasonable ranges
- `validation/compute.md` — Capacity match, valid node types

Generate validation report using `reports/conversion-validation.md` template.

### Step 8: Write Target File

Write the generated workflow to the output path:

```
output_format = target_adapter.output_format.type
output_extension = target_adapter.output_format.extension

IF output_format == "yaml":
  Write YAML with proper indentation
IF output_format == "json":
  Write JSON with 2-space indentation

Output path: {plan.output_dir}/{entry.output_file}
```

### Step 9: Print Summary

```
═══════════════════════════════════════════════════
WORKFLOW ENGINE — CONVERSION SUMMARY
═══════════════════════════════════════════════════
Source Adapter:  {source_workflow_adapter}
Target Adapter:  {target_workflow_adapter}
Transformation:  workflow_transform

Available Source Adapters: [adf, glue_workflow, databricks_workflow, step_functions, fabric_pipeline, synapse, emr, dataproc]
Available Target Adapters: [databricks_workflow, adf, step_functions, fabric_pipeline, synapse, emr, glue_workflow, bigquery]

| # | Source File | Route | Tasks | Deps | Status | Output |
|---|------------|-------|-------|------|--------|--------|
| 1 | pipeline.json | adf → databricks_workflow | 3 | 2 | ✅ | pipeline_databricks.yaml |

Validation: {pass_count} passed, {warn_count} warnings, {error_count} errors
═══════════════════════════════════════════════════
```

## Example Execution Flow

**Input:** ADF Pipeline → Databricks Workflow

```
1. Parse plan → source_workflow_adapter: "adf", target: "databricks_workflow"
2. Load adapters/source/adf.yaml
3. Load adapters/target/databricks_workflow.yaml
4. Read ADF pipeline JSON
5. Parse using adf adapter:
   - Extract activities[] as tasks
   - Extract dependsOn as dependencies
   - Extract recurrence trigger
   - Extract parameters
6. Normalize:
   - DatabricksNotebook → "notebook"
   - Copy → "data_copy"
   - ISO 8601 timeout → seconds
   - ADF parameters → flat key-value
7. Validate normalized schema (acyclic, unique IDs, etc.)
8. Generate using databricks_workflow adapter:
   - "notebook" → notebook_task
   - Dependencies → depends_on arrays
   - Cron → quartz_cron_expression
   - Compute tier → Standard_DS3_v2
   - Wrap in resources.jobs.<key>
9. Validate output (DAB compliance, structure, timeouts)
10. Write pipeline_databricks.yaml
```

## Extensibility

### Adding a New Source Workflow Platform
1. Create `adapters/source/{platform}.yaml`
2. Include: detection, parsing rules, type_mapping, dependencies, triggers, parameters, timeout, compute
3. Done — engine supports `source_workflow_adapter: {platform}`

### Adding a New Target Workflow Platform
1. Create `adapters/target/{platform}.yaml`
2. Include: output_format, generation rules, type_mapping, dependencies, triggers, parameters, timeout, compute
3. Done — engine supports `target_workflow_adapter: {platform}`

### Total Supported Combinations
```
Combinations = (source adapters) × (target adapters)
Current:       8                 ×  8               = 64 routes
              (with zero hardcoded mappings)
```
