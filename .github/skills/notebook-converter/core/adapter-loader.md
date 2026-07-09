# Adapter Loader

Dynamically discovers and loads source/target adapter YAML files by platform name. No hardcoded platform lists — adapters are resolved from the filesystem.

## Adapter Directory Layout

```
adapters/
├── source/           # One YAML per source platform
│   ├── glue.yaml
│   ├── synapse.yaml
│   ├── databricks.yaml
│   ├── emr.yaml
│   ├── dataproc.yaml
│   ├── fabric.yaml
│   └── postgresql.yaml
└── target/           # One YAML per target platform
    ├── databricks.yaml
    ├── synapse.yaml
    ├── emr.yaml
    ├── fabric.yaml
    └── bigquery.yaml
```

## Loading Rules

### Load Source Adapter
```
INPUT: platform_name (string, e.g., "glue")
RESOLVE: adapters/source/{platform_name}.yaml
IF file exists → read YAML → return adapter object
IF file NOT found → ERROR: "No source adapter for '{platform_name}'. Available: [list .yaml files in adapters/source/]"
```

### Load Target Adapter
```
INPUT: platform_name (string, e.g., "databricks")
RESOLVE: adapters/target/{platform_name}.yaml
IF file exists → read YAML → return adapter object
IF file NOT found → ERROR: "No target adapter for '{platform_name}'. Available: [list .yaml files in adapters/target/]"
```

### List Available Adapters
```
SOURCE ADAPTERS: List all .yaml filenames (without extension) in adapters/source/
TARGET ADAPTERS: List all .yaml filenames (without extension) in adapters/target/
```

## Adapter YAML Schema

Each adapter YAML file must be structured under an `adapter:` root key with these required and optional fields:

### Required Fields (All Adapters)

| Field | Type | Description |
|-------|------|-------------|
| `adapter.name` | string | Platform identifier (lowercase, e.g., "glue") |
| `adapter.type` | string | `source`, `target`, or `both` |
| `adapter.platform` | string | Cloud provider: AWS, Azure, GCP, Multi-Cloud |
| `adapter.description` | string | Human-readable description of the adapter |
| `adapter.connection.parameters` | list | Connection parameters with name, type, description |
| `adapter.parameters` | object | Parameter extraction/definition patterns |
| `adapter.secrets` | object | Secret retrieval method and pattern |
| `adapter.imports` | object | Imports to remove (source) or add (target) |
| `adapter.catalog.operations` | list | Catalog operation mappings (source→normalized or normalized→target) |
| `adapter.storage` | object | Storage path prefix and format templates |

### Source-Specific Fields

| Field | Type | Description |
|-------|------|-------------|
| `adapter.detection.indicators` | list | Code strings that identify this platform |
| `adapter.detection.file_patterns` | list | File extensions this adapter handles |
| `adapter.detection.storage_prefix` | string | Storage path prefix (e.g., "s3://") |
| `adapter.read_logic.spark` | object | Spark read patterns: initialization, catalog_read, path_read, finalization |
| `adapter.read_logic.python` | object | Python read patterns (optional) |
| `adapter.read_logic.sql` | object | SQL read patterns (optional) |
| `adapter.imports.remove` | list | Source-specific imports to strip during conversion |
| `adapter.imports.keep` | list | Import patterns to preserve (regex-compatible) |

### Target-Specific Fields

| Field | Type | Description |
|-------|------|-------------|
| `adapter.runtime.spark_session` | string | "pre-initialized" or "manual" |
| `adapter.runtime.initialization` | string | Target initialization code block |
| `adapter.runtime.spark_config_migration` | string | Template for migrating Spark configs |
| `adapter.write_logic.spark` | object | Spark write patterns: catalog_write, path_write, merge_write |
| `adapter.write_logic.sql` | object | SQL write patterns (optional) |
| `adapter.write_logic.python` | object | Python write patterns (optional) |
| `adapter.imports.add` | list | Target-specific imports to inject |
| `adapter.imports.platform_specific` | list | Platform SDK imports |
| `adapter.notebook_format.type` | string | Output format: "ipynb" or "py" |
| `adapter.notebook_format.header_cell` | string | Header comment for converted notebook |
| `adapter.notebook_format.metadata` | object | Notebook kernel and language metadata |
| `adapter.enhancements` | list | Platform-specific optimization capabilities |

## Validation Rules

When loading an adapter, validate:

1. `adapter.name` — Must be present and non-empty
2. `adapter.type` — Must be one of: `source`, `target`, `both`
3. `adapter.platform` — Must be present
4. **If type = "source" or "both":**
   - `adapter.detection` section must exist with at least one indicator
   - `adapter.read_logic` section must exist with at least one read pattern
5. **If type = "target" or "both":**
   - `adapter.write_logic` section must exist with at least one write pattern
   - `adapter.runtime` section must exist with spark_session and initialization

If validation fails → ERROR with specific missing field(s) listed.

## Adapter Isolation Principle

**CRITICAL:** Each adapter YAML describes ONLY its own platform. No adapter may contain:
- References to other platforms
- Cross-platform mapping logic
- If/else branching based on source or target
- Hardcoded conversion paths (e.g., source-to-target naming)

Cross-platform wiring is handled exclusively by the execution engine (`execution/engine.md`) using the conversion plan's `source_adapter` + `target_adapter` fields.

## Adding a New Platform

To support a new platform (e.g., "snowpark"):

1. Create `adapters/source/snowpark.yaml` — if usable as source
2. Create `adapters/target/snowpark.yaml` — if usable as target
3. Follow the YAML schema above
4. **No other files need to change** — the adapter loader discovers it automatically
5. The execution engine will support `source_adapter: snowpark` or `target_adapter: snowpark` with zero code changes
