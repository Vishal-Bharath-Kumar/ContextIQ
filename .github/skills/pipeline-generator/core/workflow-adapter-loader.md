# Workflow Adapter Loader

Dynamically discovers and loads source/target workflow adapter YAML files by platform name. No hardcoded platform lists — adapters are resolved from the filesystem.

## Adapter Directory Layout

```
adapters/
├── source/                    # One YAML per source workflow platform
│   ├── adf.yaml
│   ├── glue_workflow.yaml
│   ├── databricks_workflow.yaml
│   └── step_functions.yaml
└── target/                    # One YAML per target workflow platform
    ├── databricks_workflow.yaml
    ├── adf.yaml
    ├── step_functions.yaml
    └── fabric_pipeline.yaml
```

## Loading Rules

### Load Source Adapter
```
INPUT: workflow_type (string, e.g., "adf", "glue_workflow")
RESOLVE: adapters/source/{workflow_type}.yaml
IF file exists → read YAML → return adapter object
IF file NOT found → ERROR:
  "No source workflow adapter for '{workflow_type}'.
   Available: [list .yaml files in adapters/source/]"
```

### Load Target Adapter
```
INPUT: target_workflow (string, e.g., "databricks_workflow")
RESOLVE: adapters/target/{target_workflow}.yaml
IF file exists → read YAML → return adapter object
IF file NOT found → ERROR:
  "No target workflow adapter for '{target_workflow}'.
   Available: [list .yaml files in adapters/target/]"
```

### List Available Adapters
```
SOURCE WORKFLOW ADAPTERS: List all .yaml filenames (without extension) in adapters/source/
TARGET WORKFLOW ADAPTERS: List all .yaml filenames (without extension) in adapters/target/
```

## Adapter YAML Schema

### Required Fields (All Workflow Adapters)

| Field | Type | Description |
|-------|------|-------------|
| `adapter.name` | string | Platform identifier (lowercase) |
| `adapter.type` | string | `source` or `target` |
| `adapter.platform` | string | Cloud provider: AWS, Azure, GCP, Multi-Cloud |
| `adapter.description` | string | Human-readable description |

### Source-Specific Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `adapter.detection` | object | File formats and structural markers for identification |
| `adapter.parsing` | object | JSON/YAML paths to extract tasks, deps, triggers |
| `adapter.parsing.type_mapping` | object | Source type → normalized type mapping |
| `adapter.dependencies` | object | How to extract dependency graph |
| `adapter.triggers` | object | How to extract schedule/trigger info |
| `adapter.parameters` | object | Parameter format and normalization rules |
| `adapter.timeout` | object | Timeout format and conversion rules |
| `adapter.compute` | object | Compute resource extraction rules |

### Target-Specific Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `adapter.output_format` | object | Output file type and extension |
| `adapter.generation` | object | How to generate the target structure |
| `adapter.generation.task_generation.type_mapping` | object | Normalized type → target type mapping |
| `adapter.dependencies.generation` | string | How to generate target dependency format |
| `adapter.triggers.generation` | object | How to generate target schedule/trigger |
| `adapter.parameters.generation` | string | How to generate target parameter format |
| `adapter.timeout.generation` | string | How to generate target timeout format |

## Validation Rules

When loading an adapter, validate:

1. `adapter.name` — present and non-empty
2. `adapter.type` — must be `source` or `target`
3. `adapter.platform` — present
4. **If source:** `adapter.parsing` and `adapter.detection` must exist
5. **If target:** `adapter.generation` and `adapter.output_format` must exist

## Adapter Isolation Principle

**CRITICAL:** Each adapter describes ONLY its own platform. No adapter may contain:
- References to other platforms
- Cross-platform mapping logic
- If/else branching based on source/target
- Hardcoded conversion paths (e.g., source-to-target naming)

## Adding a New Workflow Platform

1. Create `adapters/source/{platform}.yaml` — if usable as source
2. Create `adapters/target/{platform}.yaml` — if usable as target
3. Follow the YAML schema above
4. **No other files need to change** — the engine discovers it automatically
