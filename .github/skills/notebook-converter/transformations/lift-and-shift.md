# Lift-and-Shift Transformation

**Type:** Pass-through (platform layer only)
**ID:** lift_and_shift

## Mission

Migrate data pipelines from an old platform to a new platform.

**The data stays the same. Only the platform changes.**

Every transformation rule, every validation check, every anti-pattern fix exists to serve this single goal.

---

## The Contract

### What NEVER Changes

| What | Why It Must Not Change |
|------|----------------------|
| Column names | Downstream consumers depend on exact column names |
| Data types | Type changes silently corrupt data or break downstream reads |
| Data schema | The shape of the output must be identical to the source |
| Data model | Table relationships, keys, and cardinality are business decisions |
| Business logic | Filters, joins, aggregations, and transformations encode business rules |
| SQL queries | Query logic defines what data is selected and how it is shaped |
| UDF definitions | User-defined functions encode custom business computation |
| Row counts | The same input must produce the same output row count |
| Join conditions | Changing a join condition changes which data is included |
| Filter conditions | Changing a filter changes which rows survive |
| Aggregation logic | Changing aggregations changes the meaning of the output |
| Execution order | Operations must run in the same sequence as the source |
| NULL handling | Implicit NULL behaviour must be preserved or made explicit |
| Write modes | overwrite vs append is a business decision, not a platform detail |

### What ALWAYS Changes (Platform Layer Only)

| What Changes | Source Example | Target Example |
|-------------|---------------|----------------|
| Imports | `from awsglue.context import GlueContext` | *(removed)* |
| Runtime initialisation | `sc = SparkContext()` | `# SparkSession pre-initialised by platform` |
| Parameter extraction | `getResolvedOptions(sys.argv, [...])` | `dbutils.widgets.get("param")` |
| Secret retrieval | `boto3.client('secretsmanager')` | `dbutils.secrets.get(scope, key)` |
| Storage paths | `s3://bucket/path/` | `abfss://container@account.dfs.core.windows.net/path/` |
| Catalog API | `glueContext.create_dynamic_frame.from_catalog(...)` | `spark.read.table("db.table")` |
| Utility calls | `boto3.client('s3').list_objects(...)` | `dbutils.fs.ls("path")` |
| Notebook metadata | `"kernelspec": "glue_pyspark"` | `"kernelspec": "python3"` |
| Job lifecycle | `job.commit()` | *(removed — not needed on target)* |
| Spark session creation | `SparkSession.builder.getOrCreate()` | *(removed — pre-initialised)* |

### The Boundary Line

```
┌─────────────────────────────────────────────────────────────┐
│                    PLATFORM LAYER                           │
│  (changes during migration)                                 │
│                                                             │
│  imports · initialisation · parameters · secrets           │
│  storage paths · catalog API · utilities · metadata        │
│  job lifecycle · notebook format · kernel                  │
├─────────────────────────────────────────────────────────────┤
│                    BUSINESS LAYER                           │
│  (never changes — preserved exactly as-is)                  │
│                                                             │
│  schema · data types · column names · data model           │
│  filters · joins · aggregations · SQL queries              │
│  UDFs · transformations · write modes · execution order    │
└─────────────────────────────────────────────────────────────┘
```

The conversion engine operates exclusively in the platform layer. It has no authority to touch anything in the business layer.

---

## Transformation Rules

### What Changes (Platform Layer)

| Aspect | Action |
|--------|--------|
| Imports | Remove source-specific imports, add target-specific imports |
| Initialization | Replace source init with target runtime init |
| Read operations | Translate source read patterns to normalized form |
| Write operations | Translate normalized form to target write patterns |
| Parameters | Convert source parameter extraction to target format |
| Secrets | Convert source secret retrieval to target method |
| Storage paths | Translate source storage prefix to target prefix |
| Catalog operations | Map source catalog API to target catalog API |
| Spark config | Extract from source builder → apply via `spark.conf.set()` |

### What Does NOT Change (Business Layer)

| Aspect | Action |
|--------|--------|
| Business logic | All transformations, filters, joins, aggregations preserved |
| Column names | No renaming or restructuring |
| Data types | No casting or conversion |
| DataFrame operations | All PySpark DataFrame API calls kept as-is |
| SQL queries | All SQL logic preserved verbatim |
| UDF definitions | All user-defined functions preserved |
| Comments | All comments preserved |

---

## Apply Logic

```python
def apply(source_adapter, target_adapter, source_code):
    """
    Lift-and-shift transformation pipeline:

    1. Parse source code into cells/blocks
    2. Remove source-specific imports (from source_adapter.imports.remove)
    3. Add target-specific imports (from target_adapter.imports.add)
    4. Replace source initialization with target initialization
    5. Convert parameter extraction patterns
    6. Convert secret retrieval patterns
    7. Translate storage paths (source prefix → target prefix)
    8. Map catalog operations (source normalized → target specific)
    9. Extract Spark configs from builder chains → spark.conf.set()
    10. Remove source finalization (e.g., job.commit())
    11. Add target header cell
    12. Return converted code
    """
    pass  # Executed by the engine
```

## Conversion Steps (Detailed)

### Step 1: Import Conversion
```
FOR each import in source_adapter.imports.remove:
    REMOVE from source code
FOR each import in target_adapter.imports.add:
    ADD to import section
KEEP all imports matching source_adapter.imports.keep patterns
```

### Step 2: Initialization Replacement
```
REMOVE source_adapter.read_logic.spark.initialization block
INSERT target_adapter.runtime.initialization
IF source has spark config in builder chain:
    EXTRACT each .config(key, value) call
    INSERT target_adapter.runtime.spark_config_migration for each
```

### Step 3: Parameter Conversion
```
FIND all patterns matching source_adapter.parameters.format
REPLACE with target_adapter.parameters.extraction pattern
IF target requires parameter definition:
    ADD target_adapter.parameters.definition calls
```

### Step 4: Secret Conversion
```
FIND all patterns matching source_adapter.secrets.method
REPLACE with target_adapter.secrets pattern
```

### Step 5: Storage Path Translation
```
FIND all paths starting with source_adapter.storage.prefix
REPLACE prefix with target_adapter.storage.prefix (or full path format)
```

### Step 6: Catalog Operation Mapping
```
FOR each operation in source_adapter.catalog.operations:
    FIND source pattern in code
    REPLACE with matching target_adapter.catalog.operations target pattern
```

### Step 7: Finalization
```
REMOVE source_adapter.read_logic.spark.finalization block
INSERT target_adapter header_cell at top of notebook
```

---

## Output Format

The output follows the target adapter's `notebook_format` specification:
- File type: from `target_adapter.notebook_format.type` (.ipynb or .py)
- Header: from `target_adapter.notebook_format.header_cell`
- Metadata: from `target_adapter.notebook_format.metadata`

---

## Preservation Details

### Schema Preservation

The output schema of every DataFrame and every table must be identical before and after migration:
- Same column names, same order
- Same data types (or the closest lossless equivalent on the target platform)
- Same nullable / not-null constraints
- Same partition columns

If the target platform has no direct equivalent for a source data type, use the closest lossless type and document the mapping. Never silently drop precision or change semantics.

**Lossless type mapping examples:**
```
PostgreSQL NUMERIC(18,4)  →  Spark DECIMAL(18,4)   ✅ lossless
PostgreSQL TEXT           →  Spark STRING           ✅ lossless
PostgreSQL TIMESTAMP TZ   →  Spark TIMESTAMP        ⚠️  timezone info noted in comment
PostgreSQL SERIAL         →  Spark BIGINT           ⚠️  ID generation moved to write time
```

### Business Logic Preservation

Every line of transformation code that operates on data must survive the migration unchanged:
- Every `.filter()` and `.where()` call with its exact condition
- Every `.join()` call with its exact join type and condition
- Every `.groupBy()` and `.agg()` call
- Every `.select()`, `.withColumn()`, `.drop()` call
- Every SQL `WHERE`, `JOIN`, `GROUP BY`, `HAVING` clause
- Every `CASE WHEN` expression, window function, UDF call and definition, CTE

### Platform-Specific Notes

**AWS Glue → Databricks / Synapse / Fabric**
- `ApplyMapping` column renames → preserve the exact target column names from the mapping
- `DropNullFields` → `df.dropna()` — same semantic, different API
- `ResolveChoice` → explicit `.cast()` — preserve the target type exactly
- `transformation_ctx` names are Glue bookmarking metadata — remove them

**PostgreSQL → Spark SQL (Fabric / Databricks)**
- Preserve all table/column names, data type semantics, CHECK constraints, NOT NULL constraints, business logic in views and functions
- FOREIGN KEY → inline comment on the column
- MATERIALIZED VIEW → Delta table with scheduled refresh note
- PL/pgSQL functions → PySpark UDF with equivalent logic

**Databricks → Synapse / Fabric**
- Unity Catalog three-part names (`catalog.schema.table`) must be preserved — only the catalog access API changes

---

## How the System Enforces This

| Phase | Enforcement |
|-------|-------------|
| Conversion (Steps 1–7) | Adapter engine applies only platform-layer transformations — no rules touch business logic |
| Anti-pattern fixing | Safety rule: **NEVER remove or alter business logic.** If a fix risks altering business logic, mark DEFERRED. Never modify BL-XXX items. |
| Optimisation | Adds error handling, logging, resource cleanup only — never changes column names, data types, schemas, business logic, or platform APIs already converted |
| Data governance | Adds observability and reliability safeguards only — never changes business logic, output schema, data semantics, or execution order |
| Validation | V-CFG-005 and V-CFG-006 failures are **CRITICAL severity** — converted file must not be delivered until resolved |

---

## Failure Modes to Prevent

| Failure | How It Happens | Prevention |
|---------|---------------|------------|
| Column dropped | Conversion removes a `.select()` or `ApplyMapping` entry | V-CFG-006 check |
| Type narrowed | `DECIMAL(18,4)` converted to `FLOAT` | Lossless type mapping table |
| Filter removed | Anti-pattern fixer removes a `.filter()` thinking it is redundant | Safety rule: never touch filters |
| Join type changed | `LEFT JOIN` converted to `INNER JOIN` | V-CFG-005 check |
| Row duplicated | Append mode used where overwrite was intended | Write mode preserved exactly |
| NULL semantics changed | Explicit null filter added where source relied on implicit behaviour | DG-NH rules add logging, not removal |
| Execution order changed | Cells reorganised into "logical sections" | Flow preservation rule: no reorganisation |
| Aggregation lost | `.groupBy().agg()` removed during optimisation | Optimiser safety rule |

---

## Validation Checklist

### Platform Layer (must all be true)
- [ ] All source-specific imports removed
- [ ] Target-specific imports added
- [ ] No source initialisation code remains
- [ ] Target runtime initialisation present
- [ ] All storage paths use target prefix
- [ ] Parameters use target extraction method
- [ ] Secrets use target retrieval method
- [ ] Output format matches target specification

### Business Layer (must all be true — zero tolerance)
- [ ] Column names identical to source
- [ ] Data types identical to source (or documented lossless mapping)
- [ ] Row count of every DataFrame operation unchanged
- [ ] Filter conditions identical to source
- [ ] Join conditions and join types identical to source
- [ ] Aggregation logic identical to source
- [ ] SQL queries preserved verbatim
- [ ] UDF definitions preserved verbatim
- [ ] Write modes (overwrite / append / merge) identical to source
- [ ] Execution order identical to source
- [ ] All read operations present (count matches source)
- [ ] All write operations present (count matches source)
