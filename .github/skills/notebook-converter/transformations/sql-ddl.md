# SQL DDL Transformation Rules

**Type:** DDL/DML conversion
**ID:** sql-ddl

## Description

Transforms SQL Data Definition Language (DDL) and Data Manipulation Language (DML) statements from relational database syntax (PostgreSQL, MySQL, SQL Server) to Spark SQL / Delta Lake syntax. Used when the source adapter is a relational database and the target is a Spark-based platform (Fabric, Databricks, Synapse, EMR).

## Scope

This transformation applies to `.sql` files containing:
- `CREATE TABLE` / `ALTER TABLE` / `DROP TABLE`
- `CREATE INDEX` / `DROP INDEX`
- `CREATE VIEW` / `CREATE MATERIALIZED VIEW`
- `INSERT` / `UPDATE` / `DELETE` / `MERGE`
- `CREATE FUNCTION` / `CREATE PROCEDURE`
- `CREATE SEQUENCE`

## Transformation Rules

### CREATE TABLE

| Source Pattern | Target Pattern |
|----------------|----------------|
| `CREATE TABLE {name} ({cols})` | `CREATE TABLE {name} ({cols}) USING DELTA` |
| `SERIAL` / `BIGSERIAL` | `BIGINT` (plain — no IDENTITY; generate IDs at write time via `monotonically_increasing_id()`) |
| `VARCHAR(n)` / `TEXT` / `CHAR(n)` | `STRING` |
| `NUMERIC(p,s)` | `DECIMAL(p,s)` |
| `TIMESTAMP WITH TIME ZONE` | `TIMESTAMP` |
| `BOOLEAN` | `BOOLEAN` |
| `JSONB` / `JSON` | `STRING` (+ `from_json()` usage comment) |
| `UUID` | `STRING` |
| `TEXT[]` / `INTEGER[]` | `ARRAY<STRING>` / `ARRAY<INT>` |
| `BYTEA` | `BINARY` |
| `DEFAULT CURRENT_TIMESTAMP` | `-- Default handled at write time` |
| `DEFAULT NOW()` | `-- Default handled at write time` |
| `DEFAULT uuid_generate_v4()` | `-- Generate UUID at write time` |

#### Constraints Mapping

| Source Constraint | Target Handling |
|-------------------|-----------------|
| `PRIMARY KEY` | Preserve (Delta supports PK declaration) |
| `UNIQUE` | Convert to data quality check or Delta constraint |
| `NOT NULL` | Preserve |
| `CHECK (expr)` | Inline in `CREATE TABLE` column definition — do NOT use separate `ALTER TABLE ADD CONSTRAINT` |
| `FOREIGN KEY REFERENCES` | Convert to inline comment on column |
| `DEFAULT value` | Preserve in DDL — requires `'delta.feature.allowColumnDefaults' = 'supported'` in TBLPROPERTIES |

#### Target Enhancements

Add these clauses to every `CREATE TABLE`:

```sql
USING DELTA
TBLPROPERTIES (
    'delta.feature.allowColumnDefaults' = 'supported',
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
)
```

**CRITICAL:** If any column uses `DEFAULT`, the `'delta.feature.allowColumnDefaults' = 'supported'` property is REQUIRED.
Without it, Fabric throws: *WRONG_COLUMN_DEFAULTS_FOR_DELTA_FEATURE_NOT_ENABLED*.

**CRITICAL:** CHECK constraints MUST be inlined in the `CREATE TABLE` column definition, not in separate `ALTER TABLE ADD CONSTRAINT` statements.
`ALTER TABLE ADD CONSTRAINT` fails on empty tables because the Delta log is not initialized until data is written.
Example: `status STRING CHECK (status IN ('a', 'b', 'c'))` — not a separate ALTER TABLE.

### CREATE INDEX

| Source Pattern | Target Pattern |
|----------------|----------------|
| `CREATE INDEX idx ON t(col1, col2)` | `OPTIMIZE {t} ZORDER BY (col1, col2)` |
| `CREATE INDEX ... USING GIN` | `-- GIN index: no Delta equivalent (skip)` |
| `CREATE INDEX ... USING GiST` | `-- GiST index: no Delta equivalent (skip)` |
| `CREATE UNIQUE INDEX` | `-- Unique constraint: validate via DQ check` |
| `CREATE INDEX CONCURRENTLY` | Remove `CONCURRENTLY` keyword |
| Partial index `WHERE clause` | `-- Partial index: filter in OPTIMIZE or DQ` |

### CREATE VIEW

| Source Pattern | Target Pattern |
|----------------|----------------|
| `CREATE VIEW` | `CREATE OR REPLACE VIEW` |
| `CREATE OR REPLACE VIEW` | `CREATE OR REPLACE VIEW` (preserved) |
| `CREATE MATERIALIZED VIEW` | `CREATE OR REPLACE TABLE ... USING DELTA AS` |
| `REFRESH MATERIALIZED VIEW` | `-- Schedule via orchestration pipeline` |
| `REFRESH ... CONCURRENTLY` | `-- Schedule via orchestration pipeline` |

### INSERT Statements

| Source Pattern | Target Pattern |
|----------------|----------------|
| `INSERT INTO ... VALUES` | `INSERT INTO ... VALUES` (Spark SQL) |
| `INSERT ... ON CONFLICT DO NOTHING` | Delta MERGE: `WHEN NOT MATCHED THEN INSERT` |
| `INSERT ... ON CONFLICT DO UPDATE` | Delta MERGE: full upsert |
| `INSERT ... RETURNING` | `INSERT` + separate `SELECT` |
| `INSERT ... SELECT` | `INSERT INTO ... SELECT` (preserved) |

#### ON CONFLICT → MERGE Conversion Pattern

Source (PostgreSQL):
```sql
INSERT INTO {table} ({cols})
VALUES ({vals})
ON CONFLICT ({conflict_cols}) DO UPDATE
SET {set_clauses};
```

Target (Delta MERGE via PySpark):
```python
from delta.tables import DeltaTable

delta_table = DeltaTable.forPath(spark, 'Tables/{table}')

(
    delta_table.alias('target')
    .merge(
        source_df.alias('source'),
        'target.{conflict_col} = source.{conflict_col}'
    )
    .whenMatchedUpdate(set={set_mapping})
    .whenNotMatchedInsertAll()
    .execute()
)
```

### UPDATE Statements

| Source Pattern | Target Pattern |
|----------------|----------------|
| `UPDATE ... SET ... WHERE` | `UPDATE ... SET ... WHERE` (Delta SQL) |
| `UPDATE ... FROM` (PostgreSQL) | `MERGE INTO` with source subquery |
| `UPDATE ... RETURNING` | `UPDATE` + separate `SELECT` |

### DELETE Statements

| Source Pattern | Target Pattern |
|----------------|----------------|
| `DELETE FROM ... WHERE` | `DELETE FROM ... WHERE` (Delta SQL) |
| `DELETE ... USING` (PostgreSQL) | `DELETE ... WHERE EXISTS (subquery)` |
| `TRUNCATE TABLE` | `DELETE FROM {table}` or `DROP + CREATE` |

### CREATE FUNCTION / PROCEDURE

| Source Pattern | Target Pattern |
|----------------|----------------|
| Simple scalar function | `CREATE FUNCTION ... RETURNS ... RETURN expr` |
| Complex PL/pgSQL function | PySpark UDF (`spark.udf.register()`) |
| Trigger function | `-- Trigger: implement in pipeline logic` |
| `CREATE PROCEDURE` | Convert to notebook cell or pipeline step |

### Sequences

| Source Pattern | Target Pattern |
|----------------|----------------|
| `CREATE SEQUENCE` | `-- Use IDENTITY column or monotonically_increasing_id()` |
| `nextval('seq')` | `monotonically_increasing_id()` or row numbering |
| `currval('seq')` | `-- Not applicable in distributed compute` |

### PostgreSQL-Specific Syntax

| Source Pattern | Target Equivalent |
|----------------|-------------------|
| `::type` cast | `CAST(expr AS type)` |
| `ILIKE` | `LOWER(col) LIKE LOWER(pattern)` |
| `~` regex | `RLIKE(col, pattern)` |
| `\|\|` concat | `CONCAT(a, b)` |
| `NOW()` | `CURRENT_TIMESTAMP()` |
| `EXTRACT(EPOCH FROM ...)` | `UNIX_TIMESTAMP(...)` |
| `STRING_AGG(expr, delim)` | `CONCAT_WS(delim, COLLECT_LIST(expr))` |
| `ARRAY_AGG(expr)` | `COLLECT_LIST(expr)` |
| `col ->> 'key'` | `GET_JSON_OBJECT(col, '$.key')` |
| `DISTINCT ON (col)` | `ROW_NUMBER() OVER (PARTITION BY col ...) = 1` |
| `GENERATE_SERIES(a, b)` | `SEQUENCE(a, b)` |
| `TO_CHAR(expr, fmt)` | `DATE_FORMAT(expr, spark_fmt)` |

## What Does NOT Change

| Aspect | Action |
|--------|--------|
| Business logic in SELECT queries | All joins, filters, aggregations preserved |
| Column names | No renaming |
| Table relationships | Documented as comments |
| SQL comments | All comments preserved |
| CTE (WITH clause) | Non-recursive CTEs preserved as-is |
| Window functions | Preserved (Spark supports standard window functions) |
| CASE expressions | Preserved |
| Subqueries | Preserved |

## Output Strategy

| Input Statement Type | Output Format |
|----------------------|---------------|
| DDL (CREATE TABLE, INDEX, VIEW) | `.ipynb` notebook (`%%sql` cells) |
| Simple DML (INSERT VALUES, UPDATE, DELETE) | `.ipynb` notebook (`%%sql` cells) |
| Complex DML (ON CONFLICT, MERGE patterns) | `.ipynb` notebook (PySpark + Delta) |
| Functions / Procedures | `.ipynb` notebook (PySpark UDFs) |
| Analytical queries (SELECT) | `.ipynb` notebook (`%%sql` cells) |

### Notebook Cell Format Rules (Fabric / Databricks / Synapse)

**CRITICAL: Lakehouse Context (Fabric only)**
Every Fabric notebook MUST include a lakehouse configuration cell as the **first code cell**:
```python
LAKEHOUSE_NAME = "your_lakehouse_name"  # Replace with actual name
spark.catalog.setCurrentDatabase(LAKEHOUSE_NAME)
```
Without this, all `%%sql` cells fail with: *"No default context found, please attach a lakehouse"*.
Alternatively, the user can attach a lakehouse via the Fabric notebook sidebar.

**CRITICAL:** Never wrap SQL in `spark.sql("""...""")` triple-quoted strings for notebook output.
Triple-quoted strings inside `spark.sql()` cause `SyntaxError: unterminated triple-quoted string literal` in Fabric Spark runtime.

**Use `%%sql` cell magic for pure SQL:**
```
%%sql
CREATE TABLE IF NOT EXISTS {table} (
    {columns}
)
USING DELTA
TBLPROPERTIES (...)
```

**Use `spark.sql()` with single-line strings ONLY for:**
- Dynamic SQL with Python variables: `spark.sql(f"SELECT * FROM {table_name}")`
- SQL inside Python loops: `spark.sql(cmd)` where `cmd` is a variable
- Conditional execution: `if condition: spark.sql("...")`

**Use PySpark DataFrame API for:**
- Complex DML with ON CONFLICT → Delta MERGE (`DeltaTable.forPath().merge()`)
- Data loading with schema inference or explicit types
- Multi-step transformations with intermediate variables
