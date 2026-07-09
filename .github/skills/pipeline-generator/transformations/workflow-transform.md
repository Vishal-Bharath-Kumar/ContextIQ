# Workflow Transformation: Generic Pass-Through

**ID:** workflow_transform
**Type:** Structural mapping (no business logic changes)

## Description

The generic workflow transformation converts a **normalized workflow** into target-platform format by applying the target adapter's generation rules. The transformation itself performs no business logic changes — it maps the normalized schema fields to the target's expected structure.

## Transformation Pipeline

```
Source Workflow File (JSON/YAML)
       │
       ▼
┌─────────────────────────────┐
│  1. PARSE                   │  ← Source adapter parses platform-specific format
│     source adapter.parsing  │
│     → extract tasks         │
│     → extract dependencies  │
│     → extract triggers      │
│     → extract compute       │
│     → extract parameters    │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  2. NORMALIZE               │  ← Map to normalized schema
│     source adapter.type_map │
│     → map task types        │
│     → normalize timeouts    │
│     → normalize parameters  │
│     → build dependency graph│
│     → validate schema       │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  3. VALIDATE                │  ← Check normalized output
│     normalized-schema.md    │
│     → unique task IDs       │
│     → valid dependencies    │
│     → acyclic graph         │
│     → root tasks exist      │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  4. GENERATE                │  ← Target adapter builds output
│     target adapter.gen      │
│     → map task types back   │
│     → generate dependencies │
│     → generate triggers     │
│     → generate compute      │
│     → apply timeout policy  │
└──────────┬──────────────────┘
           │
           ▼
Target Workflow File (JSON/YAML)
```

## Step-by-Step Rules

### Step 1: Parse Source

Load the source adapter YAML. Use its `parsing` section to extract:

```
workflow_name     ← source_adapter.parsing.workflow_name (JSON path)
tasks             ← source_adapter.parsing.tasks_path (iterate)
  FOR each task:
    task_id       ← source_adapter.parsing.task_extraction.task_id
    task_type     ← source_adapter.parsing.task_extraction.task_type_field
    config        ← source_adapter.parsing.task_extraction.task_config
    depends_on    ← source_adapter.parsing.task_extraction.depends_on_field
    parameters    ← source_adapter.parsing.task_extraction.parameters_field
    timeout       ← source_adapter.parsing.task_extraction.timeout_field
    retries       ← source_adapter.parsing.task_extraction.retry_field
```

### Step 2: Normalize

Map source-specific types to normalized types using `source_adapter.parsing.type_mapping`:

```
FOR each parsed task:
  source_type = task's native type (e.g., "DatabricksNotebook")
  mapping = source_adapter.parsing.type_mapping[source_type]
  
  normalized_task:
    task_id         = sanitize(task_id)      # lowercase, underscores, alphanumeric
    task_type       = mapping.normalized_type # e.g., "notebook"
    original_type   = source_type            # preserved for audit
    config          = extract mapping.config_keys from task data
    parameters      = normalize_parameters(task_params, source_adapter.parameters)
    timeout_seconds = normalize_timeout(task_timeout, source_adapter.timeout)
    retries         = task_retries OR 0
    parallel        = false (updated later if part of parallel group)
    layer           = detect_layer(task_id)  # bronze/silver/gold/default
```

**Timeout normalization:**
```
IF source_adapter.timeout.format == "minutes":  value × 60
IF source_adapter.timeout.format == "iso8601":  parse ISO → seconds
IF source_adapter.timeout.format == "seconds":  no change
```

**Parameter normalization:**
```
IF source_adapter.parameters.format == "double_dash_prefix":
  Strip "--" from all keys
IF source_adapter.parameters.format == "typed_with_default":
  Extract defaultValue from typed objects
IF source_adapter.parameters.format == "json_path_interpolation":
  Strip ".$ " suffix, resolve to flat key-value
Result: always flat {"key": "value"} format
```

**Dependency extraction:**
```
Follow source_adapter.dependencies.extraction_method:
  IF "direct":
    Read depends_on arrays directly
  IF "dual_source":
    Union Graph.Edges + CONDITIONAL triggers, deduplicate
  IF "state_machine_traversal":
    Walk StartAt → Next chain, build dependency edges
```

### Step 3: Validate

Apply all validation rules from `core/normalized-schema.md`:
- Unique task IDs
- Valid dependency references
- Acyclic graph (topological sort)
- At least one root task
- Valid task types

If validation fails → ERROR with specific issue, STOP conversion for this file.

### Step 4: Generate Target

Load the target adapter YAML. Use its `generation` section to build output:

```
FOR each normalized task:
  target_type = target_adapter.generation.task_generation.type_mapping[task.task_type]
  
  Generate task structure using target_adapter pattern:
    - Map task_type → target-specific type
    - Map parameters → target parameter format
    - Map timeout → target timeout format
    - Map config fields → target typeProperties/fields

FOR each normalized dependency:
  Generate dependency using target_adapter.dependencies.generation rules

FOR each normalized trigger:
  Generate trigger/schedule using target_adapter.triggers.generation rules

FOR each normalized compute entry:
  Generate compute resource using target_adapter.compute.generation rules
    Map tier → target node type using target_adapter.compute.node_type_mapping
```

**Timeout policy enforcement (during generation):**
```
IF target is Databricks:
  Apply layer-based policy caps:
    bronze: min(timeout, 28800)
    silver: min(timeout, 28800)
    gold: min(timeout, 14400)
    default: min(timeout, 28800)
```

## What Changes (Structural Only)

| Aspect | Action |
|--------|--------|
| Task types | Map from source-native → normalized → target-native |
| Dependencies | Convert from source format (arrays/edges/Next) → target format |
| Triggers/Schedule | Convert between cron formats and recurrence structures |
| Parameters | Convert between typed/flat/prefixed formats |
| Timeouts | Convert between seconds/minutes/ISO-8601 |
| Compute | Map source worker types to target node types |

## What Does NOT Change

| Aspect | Action |
|--------|--------|
| Task names/IDs | Preserved (sanitized only) |
| Execution order | Dependency graph topology preserved |
| Parameter values | Values passed through unchanged |
| Business logic | Notebook/script content NOT changed by workflow conversion |
| Number of tasks | Same count (except parallel group flattening) |

## Layer Detection

Detect pipeline layer from task ID or notebook path keywords:

```
IF task_id OR config.notebook_path contains:
  "ingest", "raw", "landing", "bronze", "source" → "bronze"
  "transform", "clean", "curated", "silver", "standard" → "silver"
  "aggregate", "serve", "report", "gold", "business" → "gold"
ELSE → "default"
```
