# Performance Optimization

## General Principles
- Measure first, optimize second (profile and benchmark)
- Optimize for common data access patterns; defer edge case optimization
- Avoid premature optimization; write clear, maintainable queries first
- Minimize resource usage (memory, CPU, I/O, storage)
- Prefer simplicity; simple queries and pipelines often perform best
- Document performance-critical queries and transformations
- Understand data platform characteristics (row vs columnar, distributed vs single-node)
- Automate performance testing in CI/CD (query regression tests, pipeline SLAs)
- Set performance budgets for query latency, pipeline duration, and resource consumption

## Data Pipelines (ETL/ELT)

### Pipeline Design
- Prefer incremental/delta loads over full table scans
- Use change data capture (CDC) for real-time or near-real-time ingestion
- Partition data by time or key for efficient processing
- Parallelize independent pipeline stages
- Use idempotent operations for safe retries
- Minimize data movement; push computation to the source when possible

### Batch Processing
- Process data in appropriately sized chunks (avoid too small or too large)
- Use partitioned reads/writes to avoid full table locks
- Schedule heavy jobs during off-peak hours
- Monitor and alert on pipeline duration drift
- Use checkpointing for long-running jobs to enable recovery

### Stream Processing
- Use windowing (tumbling, sliding, session) appropriate to the use case
- Manage watermarks and late data policies explicitly
- Backpressure handling to avoid consumer overwhelm
- Minimize state size; use TTLs to expire stale state
- Prefer at-least-once with idempotent sinks over exactly-once overhead

### Data Quality
- Validate data at ingestion boundaries (schema, nulls, ranges)
- Implement data contracts between producers and consumers
- Monitor row counts, null rates, and distribution drift
- Quarantine bad records rather than failing entire pipelines
- Use checksums or hash-based deduplication

### Troubleshooting
- Monitor pipeline DAG execution times and identify bottlenecks
- Check for data skew causing uneven partition processing
- Profile memory usage in transformation steps
- Log and alert on SLA breaches

## SQL & Query Optimization

### Query Design
- Select only needed columns (never SELECT *)
- Filter early; push WHERE clauses as close to source as possible
- Avoid correlated subqueries; prefer JOINs or CTEs
- Use window functions instead of self-joins for running calculations
- Parameterized queries for security and plan caching
- LIMIT results during development; use pagination in production

### Indexing
- Index columns used in WHERE, JOIN, ORDER BY, GROUP BY
- Use composite indexes matching query patterns (left-prefix rule)
- Avoid over-indexing; each index has write cost
- Use covering indexes for frequently accessed column sets
- Regularly review unused indexes and drop them
- Consider partial/filtered indexes for subset queries

### Joins & Aggregations
- Join on indexed columns; prefer equi-joins
- Order joins from smallest to largest result set
- Pre-aggregate in materialized views or summary tables for repeated queries
- Use approximate aggregations (HyperLogLog, sketches) when exact counts aren't needed
- Avoid DISTINCT as a fix for bad joins; fix the join logic

### Query Plans
- Analyze with EXPLAIN / EXPLAIN ANALYZE before deploying
- Watch for full table scans on large tables
- Identify implicit type conversions that prevent index usage
- Check for spills to disk (sort, hash join overflows)
- Monitor query plan changes after statistics updates

### Troubleshooting
- Slow query logs for identifying bottlenecks
- pg_stat_statements, sys.dm_exec_query_stats, or equivalent
- Monitor lock waits and deadlocks
- Check for parameter sniffing issues in parameterized queries

## Database Design & Modeling

### Schema Design
- Choose appropriate modeling approach (star schema, snowflake, Data Vault, wide tables)
- Use surrogate keys for dimension tables; natural keys for deduplication
- Normalize OLTP; denormalize for analytical/reporting workloads
- Efficient data types (INT over BIGINT when range allows, VARCHAR(n) over TEXT for bounded fields)
- Partition large fact tables by date or tenant
- Archive or purge old data with retention policies

### Columnar & Analytical Stores
- Leverage columnar compression (Parquet, ORC, Delta, Iceberg)
- Sort/cluster data by commonly filtered columns
- Use Z-ordering or data skipping for multi-dimensional filters
- Compact small files regularly (avoid small file problem)
- Use table statistics/ANALYZE for optimizer accuracy

### Transactions & Concurrency
- Short transactions to reduce lock contention
- Use appropriate isolation levels (read committed for most analytics)
- Avoid long-running transactions holding locks
- Use optimistic concurrency for write-heavy workloads
- Batch DML operations (INSERT/UPDATE/DELETE) for throughput

### Replication & Scaling
- Read replicas for scaling analytical reads; monitor replication lag
- Sharding for horizontal write scalability
- Connection pooling (PgBouncer, ProxySQL) for efficient resource use
- Separate OLTP and OLAP workloads (dedicated read replicas or data warehouse)

### Troubleshooting
- Monitor table bloat and run VACUUM/OPTIMIZE regularly
- Check index fragmentation and rebuild as needed
- Watch for deadlocks in concurrent write patterns
- Use database-specific advisors (pg_stat_user_tables, DTA, Query Store)

## Data Warehouse & Lake

### Storage Optimization
- Use columnar formats (Parquet, ORC) for analytical workloads
- Compress with Snappy (speed) or Zstd/gzip (ratio) based on use case
- Partition by query access patterns (date, region, tenant)
- Cluster/sort within partitions for predicate pushdown
- Lifecycle policies to tier cold data to cheaper storage
- Compact small files to reduce metadata overhead

### Compute Optimization
- Right-size compute clusters; use auto-scaling where available
- Use query result caching for repeated queries
- Materialized views for expensive, frequently accessed aggregations
- Separate compute for ingestion vs. querying (workload isolation)
- Use serverless/on-demand compute for sporadic workloads
- Suspend idle clusters to reduce cost

### Cost Management
- Monitor cost per query and per pipeline
- Set budgets and alerts for compute and storage spend
- Use reserved capacity for predictable baseline workloads
- Optimize scan volume (partition pruning, column pruning)
- Avoid unnecessary data duplication across layers

### Troubleshooting
- Query profile/execution plan for identifying expensive stages
- Monitor queue times and concurrency slot usage
- Check for data skew in distributed joins and aggregations
- Review spill-to-disk metrics and increase memory/reduce data volume

## Caching & Materialization

### Caching Strategies
- Cache hot query results in Redis/Memcached for sub-second responses
- Use materialized views for pre-computed aggregations
- Implement TTL-based invalidation aligned with data refresh schedules
- Cache at the right layer (application, query result, intermediate dataset)
- Avoid caching volatile data that changes faster than TTL

### Materialization
- Materialize expensive joins/aggregations as summary tables
- Refresh materialized data incrementally when possible
- Use dbt or equivalent for dependency-aware materialization
- Balance freshness vs. cost (full refresh vs. incremental)
- Document refresh schedules and downstream dependencies

### Troubleshooting
- Monitor cache hit/miss ratios
- Alert on stale cache serving outdated data
- Check materialized view refresh duration and failures
- Profile query latency with and without cache

## Python & Spark (Data Processing)

### Python
- Use vectorized operations (pandas, NumPy) over row-by-row loops
- Profile with cProfile, Py-Spy, or line_profiler
- Use chunked reading for large files (pd.read_csv with chunksize)
- Prefer Polars or DuckDB for single-node analytical workloads
- Use generators/iterators for memory-efficient processing
- multiprocessing for CPU-bound; asyncio for I/O-bound tasks
- lru_cache / functools.cache for repeated computations

### Spark / Distributed Processing
- Minimize shuffles (avoid unnecessary repartition, groupBy on high-cardinality keys)
- Broadcast small tables in joins (broadcast hint)
- Use predicate pushdown and column pruning on reads
- Repartition data to avoid skew; use salting if needed
- Cache/persist intermediate DataFrames only when reused multiple times
- Use Spark UI to identify slow stages and skewed tasks
- Prefer DataFrame/SQL API over RDD for optimizer benefits
- Tune executor memory, cores, and parallelism for cluster size

### Troubleshooting
- Spark UI stages tab for identifying shuffle-heavy operations
- Check for OOM errors and increase executor memory or reduce partition size
- Monitor GC times; switch to off-heap if excessive
- Profile Python UDFs; replace with native Spark functions where possible

## Data Governance & Observability

### Monitoring
- Track data freshness (time since last update) per table/dataset
- Monitor row counts, null rates, schema changes
- Alert on anomalies in data volume or distribution
- Log pipeline lineage for impact analysis
- Dashboard key metrics: pipeline duration, data latency, error rates

### Lineage & Cataloging
- Maintain column-level lineage for debugging and compliance
- Use data catalogs (DataHub, Amundsen, Unity Catalog) for discovery
- Tag sensitive data (PII, PHI) for access control
- Document data ownership and SLAs per dataset

### Troubleshooting
- Trace data quality issues back through lineage
- Check freshness monitors when downstream reports look stale
- Review schema evolution logs for breaking changes
- Validate row counts at each pipeline stage for data loss detection

## Performance Review Checklist
- Queries optimized with proper indexes and no full scans on large tables?
- Pipeline using incremental loads instead of full refreshes?
- Data partitioned and clustered for access patterns?
- Appropriate data formats (columnar for analytics, row for OLTP)?
- No unnecessary data movement or duplication?
- Shuffles minimized in distributed processing?
- Caching and materialization used for repeated expensive queries?
- Data quality checks at ingestion boundaries?
- Compute resources right-sized with auto-scaling?
- Storage tiered with lifecycle policies?
- Monitoring and alerts on latency, freshness, and cost?
- Query plans reviewed and no regressions introduced?
- Pipeline SLAs defined and tracked?
- Data skew identified and mitigated? 
