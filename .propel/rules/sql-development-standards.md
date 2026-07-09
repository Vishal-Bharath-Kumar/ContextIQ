# SQL Development Standards

## Database Schema Generation
- Table names in singular form
- Column names in singular form
- All tables have primary key column named `id`
- All tables have `created_at` for creation timestamp
- All tables have `updated_at` for last update timestamp
- Include `deleted_at` (nullable) for soft-delete tables; never hard-delete audit-sensitive data

## Database Schema Design
- All tables have primary key constraint
- All foreign key constraints have a name
- Foreign key constraints defined inline
- Foreign key constraints have `ON DELETE CASCADE` option
- Foreign key constraints have `ON UPDATE CASCADE` option
- Foreign key constraints reference primary key of parent table

## Data Integrity
- Apply NOT NULL on every column unless NULL has explicit business meaning
- Use CHECK constraints for domain-restricted values (status codes, ranges, percentages)
- Use UNIQUE constraints for natural keys and business identifiers
- Define DEFAULT values for columns with known initial state
- Prefer database-enforced constraints over application-only validation

## Data Types
- Use NVARCHAR for any user-facing or internationalized text; VARCHAR only for system identifiers
- Use DECIMAL(precision, scale) for monetary/financial values; never FLOAT or REAL
- Use DATE, TIME, DATETIME2, or DATETIMEOFFSET — avoid legacy DATETIME
- Use BIT for boolean flags
- Size VARCHAR/NVARCHAR to realistic maximums; avoid MAX unless truly unbounded
- Avoid implicit type conversions in JOINs and WHERE clauses (match column types)

## Naming Conventions
- Tables: singular PascalCase (`Customer`, `OrderLine`)
- Columns: singular camelCase or PascalCase per project convention
- Stored Procedures: `usp_PascalCase` (e.g., `usp_GetCustomerOrders`)
- Views: `vw_PascalCase` (e.g., `vw_ActiveCustomer`)
- Scalar Functions: `fn_PascalCase` (e.g., `fn_CalculateTax`)
- Table-Valued Functions: `tvf_PascalCase`
- Triggers: `trg_TableName_Action` (e.g., `trg_Order_AfterInsert`)
- Indexes: `IX_TableName_Columns` (non-clustered), `UX_TableName_Columns` (unique)
- Constraints: `PK_`, `FK_`, `CK_`, `DF_` prefixes (e.g., `CK_Order_Status`)

## Index Design
- Every table has a clustered index (typically on the primary key)
- Create non-clustered indexes for columns frequently used in WHERE, JOIN, ORDER BY
- Use composite indexes with most selective column first
- Use covering indexes (INCLUDE columns) to eliminate key lookups for critical queries
- Avoid over-indexing write-heavy tables; each index adds INSERT/UPDATE overhead
- Review execution plans before adding indexes; validate they are used
- Rebuild/reorganize fragmented indexes on a maintenance schedule

## SQL Coding Style
- Uppercase for SQL keywords (SELECT, FROM, WHERE)
- Consistent indentation for nested queries and conditions
- Comments to explain complex logic
- Break long queries into multiple lines for readability
- Organize clauses consistently (SELECT, FROM, JOIN, WHERE, GROUP BY, HAVING, ORDER BY)

## SQL Query Structure
- Explicit column names in SELECT (instead of SELECT *)
- Qualify column names with table name/alias when using multiple tables
- Limit subqueries when joins can be used instead
- Include LIMIT/TOP clauses to restrict result sets
- Use appropriate indexing for frequently queried columns
- Avoid functions on indexed columns in WHERE clauses

## Performance
- Prefer SET-based operations; avoid cursors and row-by-row loops
- Use CTEs for readability; use temp tables when the result is referenced multiple times or needs indexing
- Use table variables only for small, bounded result sets (<1000 rows)
- Avoid SELECT inside loops; batch or join instead
- Review execution plans for scans, implicit conversions, and missing index hints
- Use EXISTS instead of COUNT(*) > 0 for existence checks
- Avoid DISTINCT as a fix for duplicate rows; fix the join logic instead
- Keep transactions as short as possible to reduce lock contention

## Stored Procedure Structure
- Include header comment block: description, parameters, return values
- Return standardized error codes/messages
- Return result sets with consistent column order
- Use OUTPUT parameters for returning status information
- Prefix temporary tables with 'tmp_'
- Begin with SET NOCOUNT ON; SET XACT_ABORT ON

## Parameter Handling
- Prefix parameters with '@'
- Use camelCase for parameter names
- Provide default values for optional parameters
- Validate parameter values before use
- Document parameters with comments
- Arrange parameters: required first, optional later

## Error Handling
- Wrap data-modifying logic in TRY...CATCH blocks
- ROLLBACK open transactions in the CATCH block before re-throwing
- Use THROW (not RAISERROR) for new code; preserve original error context
- Log errors to a dedicated error table (procedure, message, severity, timestamp)
- Never expose internal error details to callers; return safe error codes/messages
- Set XACT_ABORT ON to auto-rollback on severe errors

## Views, Functions & Triggers
- Views: use for reusable read-only projections; avoid nesting views more than one level
- Scalar functions: avoid in WHERE/JOIN (forces row-by-row evaluation); prefer inline TVFs
- Inline table-valued functions: preferred over multi-statement TVFs for performance
- Triggers: use sparingly; only for audit logging or cross-table integrity that cannot be enforced declaratively
- Never place business logic in triggers; keep them lightweight

## SQL Security
- Parameterize all queries to prevent SQL injection
- Use prepared statements when executing dynamic SQL
- Avoid embedding credentials in SQL scripts
- Proper error handling without exposing system details
- Avoid dynamic SQL within stored procedures
- Grant EXECUTE on procedures; avoid granting direct table access
- Use schema separation to isolate sensitive tables

## Transaction Management
- Explicitly begin and commit transactions
- Keep transactions as short as possible
- Use READ COMMITTED as the default isolation level
- Use SNAPSHOT isolation for long-read scenarios to avoid blocking writers
- Use SERIALIZABLE only when phantom reads are unacceptable (document why)
- Avoid long-running transactions that lock tables
- Use batch processing for large data operations (process N rows per batch, commit between batches)
- Include SET NOCOUNT ON for stored procedures that modify data

## Migration & Versioning
- Store all schema changes as versioned migration scripts in source control
- Each migration is forward-only and idempotent (use IF NOT EXISTS guards)
- Pair every destructive migration with a rollback script
- Never modify a migration that has been applied to a shared environment
- Use a migration tool (Flyway, Liquibase, EF Migrations, dbmate) for execution order
- Review migration impact on existing data and indexes before applying
