# Snowpark Development Standards

Enterprise standards and best practices for building scalable, secure, maintainable, and cost-efficient data pipelines, transformations, and applications using Snowflake Snowpark.

---

# Before Implementation

1. Explain the business objective and affected data domains.
2. Identify impacted datasets, pipelines, and downstream consumers.
3. Validate schema compatibility and data contracts.
4. Review security, governance, performance, and cost implications.
5. Ensure transformations are idempotent and safe to rerun.
6. Confirm proper layering (Bronze, Silver, Gold) and ownership.
7. Validate observability, monitoring, and audit requirements.
8. Justify any use of raw SQL, UDFs, or custom processing over native Snowflake capabilities.

---

# General Principles

* Prefer Snowpark DataFrame APIs over raw SQL strings.
* Push computation to Snowflake whenever possible.
* Avoid moving data outside Snowflake unless required.
* Favor declarative and set-based processing over procedural logic.
* Keep transformations deterministic, repeatable, and idempotent.
* Design pipelines to be restartable without data corruption.
* Use lazy evaluation and allow Snowpark to optimize execution plans.
* Prefer native Snowflake functions before creating UDFs.
* Keep business logic separate from orchestration logic.
* Minimize complexity and avoid speculative abstractions.

---

# Project Structure

* Separate transformation logic from orchestration and scheduling.
* Organize code by business domain or pipeline stage.
* Isolate reusable transformation components.
* Store infrastructure and deployment artifacts separately from application logic.
* Maintain environment-specific configuration outside source code.
* Never hardcode credentials, database names, warehouses, or schemas.

---

# Data Layering

## Bronze Layer

* Store raw source data.
* Preserve original structure whenever possible.
* Avoid business transformations.
* Retain source lineage metadata.

## Silver Layer

* Cleanse, standardize, and validate data.
* Apply business rules and enrichment.
* Resolve schema inconsistencies.
* Enforce data quality requirements.

## Gold Layer

* Create curated, business-ready datasets.
* Optimize for analytics, reporting, and machine learning.
* Expose only validated and trusted data.
* Avoid exposing Bronze datasets directly to consumers.

---

# DataFrame Operations

* Use DataFrame APIs for filtering, joining, aggregating, and transformations.
* Alias derived columns explicitly.
* Apply filtering and projection as early as possible.
* Break complex transformations into named intermediate DataFrames.
* Avoid deeply nested transformation chains that reduce readability.
* Use explain plans during development to validate execution behavior.
* Avoid collect() and to_pandas() unless result sets are guaranteed to be small and bounded.
* Avoid row-by-row processing patterns.
* Prefer set-based operations and vectorized processing.

---

# Schema Management

* Validate schemas before processing.
* Detect schema drift proactively.
* Maintain schema versioning for critical datasets.
* Ensure backward compatibility whenever possible.
* Explicitly handle added, removed, or renamed columns.
* Fail fast when incompatible schema changes are detected.
* Document schema ownership and lifecycle.

---

# Data Contracts

* Define contracts between data producers and consumers.
* Validate contracts during ingestion and transformation.
* Version breaking changes.
* Document expected schema, quality rules, and ownership.
* Reject or quarantine non-compliant data.

---

# Data Quality

* Validate column names, types, and nullability.
* Verify row counts at critical processing stages.
* Apply completeness, uniqueness, and consistency checks.
* Quarantine invalid records instead of failing entire pipelines where appropriate.
* Monitor quality metrics continuously.
* Record validation failures for audit purposes.

---

# Incremental Processing

* Prefer incremental processing over full reloads whenever feasible.
* Track processing checkpoints and watermarks.
* Design incremental logic to be idempotent.
* Handle late-arriving and out-of-order data explicitly.
* Ensure failed executions can resume safely.
* Validate incremental results against source systems.

---

# User-Defined Functions (UDFs)

* Prefer native Snowflake functions before implementing UDFs.
* Use UDFs only when native functionality is insufficient.
* Keep UDFs stateless and deterministic.
* Avoid external dependencies whenever possible.
* Explicitly define return types.
* Minimize package size and dependency footprint.
* Validate performance impact before production deployment.
* Test thoroughly before registration.

---

# Stored Procedures

* Keep procedures focused on orchestration rather than transformation logic.
* Validate all inputs before processing.
* Fail fast with descriptive error messages.
* Wrap multi-step operations in transactions when appropriate.
* Return structured execution results.
* Log execution metadata and outcomes.
* Ensure procedures remain idempotent.

---

# Snowflake Native Features

## Streams

* Prefer Streams for change data capture (CDC) scenarios.
* Monitor stream consumption and retention.

## Tasks

* Use Tasks for lightweight orchestration.
* Avoid overly complex task dependency chains.

## Dynamic Tables

* Use Dynamic Tables for declarative incremental processing where appropriate.
* Monitor refresh costs and execution frequency.

## Materialized Views

* Justify usage based on query performance requirements.
* Review maintenance costs regularly.

## Search Optimization

* Evaluate Search Optimization before implementing custom workarounds.
* Monitor cost versus performance benefits.

---

# Session & Connection Management

* Create one Session per execution entry point.
* Do not share Sessions across threads.
* Configure warehouse, database, schema, and role explicitly.
* Use key-pair authentication or OAuth where possible.
* Close Sessions explicitly.
* Use secure secret management solutions.

---

# Dependency Management

* Keep dependencies minimal.
* Prefer approved enterprise libraries.
* Pin dependency versions.
* Regularly scan dependencies for vulnerabilities.
* Remove unused dependencies promptly.

---

# Performance

* Filter and project early.
* Minimize unnecessary scans.
* Eliminate N+1 query patterns.
* Use cache_result() only when repeated access justifies caching.
* Prefer set-based transformations.
* Batch writes and loads efficiently.
* Monitor query profiles regularly.
* Optimize partitioning and clustering only when justified by workload analysis.
* Measure performance using production-like datasets before optimization.

---

# Cost Optimization

* Use the smallest warehouse that satisfies workload requirements.
* Enable auto-suspend and auto-resume where appropriate.
* Avoid unnecessary warehouse scaling.
* Reduce repeated full-table scans.
* Monitor warehouse utilization and credit consumption.
* Review expensive queries regularly.
* Justify clustering, materialized views, and search optimization features based on measurable benefits.

---

# Observability

* Emit structured operational logs.
* Capture query IDs for troubleshooting.
* Track execution duration, rows processed, and rows rejected.
* Monitor pipeline success and failure rates.
* Maintain dashboards for critical workloads.
* Define service-level objectives for production pipelines.
* Integrate alerts with enterprise monitoring systems.

---

# Data Lineage

* Maintain lineage from source to consumption layer.
* Track upstream and downstream dependencies.
* Record transformation ownership.
* Support impact analysis before schema modifications.
* Preserve lineage metadata across all processing stages.

---

# Security

* Apply Snowflake RBAC using least-privilege principles.
* Use dedicated service roles for pipeline execution.
* Never expose credentials, tokens, or secrets.
* Never log sensitive information.
* Protect PII and regulated data using masking and access policies.
* Parameterize dynamic SQL.
* Encrypt sensitive information when required.
* Store secrets in approved secret management platforms.

---

# Governance & Compliance

* Assign data ownership for every production dataset.
* Classify data according to enterprise standards.
* Use Snowflake Tags for metadata management.
* Apply masking policies for sensitive data.
* Apply row access policies where appropriate.
* Maintain audit trails for all critical operations.
* Support compliance requirements including PCI-DSS, SOX, GDPR, and LGPD where applicable.

---

# Error Handling

* Classify exceptions as retriable or non-retriable.
* Retry transient failures using controlled exponential backoff.
* Roll back transactions on unrecoverable failures.
* Capture structured error context.
* Alert appropriate operational teams on critical failures.
* Never suppress exceptions silently.

---

# Testing

## Naming Convention

* `<method>_<condition>_<expected_result>`

## Unit Testing

* Test transformation logic independently.
* Validate schemas, calculations, and business rules.
* Avoid external dependencies.

## Integration Testing

* Test against dedicated non-production Snowflake environments.
* Validate repositories, stages, streams, and procedures.

## End-to-End Testing

* Validate complete pipeline execution.
* Verify data quality and business outcomes.

## General Rules

* Assert schema and data correctness.
* Mock external dependencies where appropriate.
* Never test against production environments.
* Maintain minimum 85% coverage for transformation and business logic.

---

# Deployment & CI/CD

* Package Snowpark code as versioned artifacts.
* Deploy through automated CI/CD pipelines.
* Promote identical code across environments.
* Use configuration for environment-specific behavior.
* Tag deployments with version and Git commit identifiers.
* Validate deployments before promotion.
* Support rollback procedures for failed releases.

---

# AI Agent Constraints

* Prefer Snowpark DataFrame APIs over raw SQL.
* Do not introduce collect() or to_pandas() without explicit justification.
* Do not bypass data quality validation steps.
* Do not hardcode environment-specific values.
* Do not introduce unnecessary UDFs when native functions exist.
* Preserve idempotency and restartability.
* Follow established project patterns before creating new abstractions.
* Maintain clear separation between transformation, orchestration, and infrastructure concerns.
* Optimize for maintainability, observability, security, and cost efficiency.

---

# Architecture Enforcement Rules

1. Business transformations must remain independent of orchestration logic.
2. Data quality validation is mandatory at defined stage boundaries.
3. All production pipelines must be observable, auditable, and restartable.
4. Incremental processing should be preferred whenever practical.
5. Security and governance requirements must be enforced by design.
6. Schema evolution must be managed explicitly.
7. Cost optimization must be considered during implementation.
8. Native Snowflake capabilities should be preferred before custom solutions.
9. Every pipeline must support lineage and operational monitoring.
10. Production code must be testable, maintainable, and compliant with enterprise standards.
