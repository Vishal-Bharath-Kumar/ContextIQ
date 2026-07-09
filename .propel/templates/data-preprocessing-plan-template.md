# Data Preprocessing Plan

## Run Metadata

| Field | Value |
|---|---|
| Workflow | Data Preprocessing |
| Run ID | |
| Upstream Workflow | Data Ingestion |
| Date | |

## 1. Data Inventory

| Source | Raw Path | Shape (rows × cols) | Key Columns | Quality Issues from Ingestion |
|---|---|---|---|---|

## 2. Missingness Strategy

| Column | Source | Null Rate (%) | Imputation Method | Justification | Leakage Risk |
|---|---|---|---|---|---|

## 3. Data Type Corrections

| Column | Source | Current Type | Target Type | Conversion Rule |
|---|---|---|---|---|

## 4. Outlier Treatment

| Column | Source | Method | Lower Bound | Upper Bound | Justification |
|---|---|---|---|---|---|

## 5. Deduplication Rules

| Source | Composite Key | Keep Policy | Expected Duplicates (%) |
|---|---|---|---|

## 6. Encoding Rules

| Column | Source | Encoding Method | Cardinality | Unknown Handling |
|---|---|---|---|---|

## 7. Implementation Tasks

| Task ID | Title | Inputs | Outputs | Acceptance Criteria | Status |
|---|---|---|---|---|---|

## 8. Acceptance Gates

| Gate | Threshold | Status |
|---|---|---|
| Null rate after imputation | <= tolerance per column | |
| No future-value imputation | 0 leakage flags | |
| Curated files written | One parquet per source | |
| Preprocessing log written | Non-empty with run_id | |
| Row count retention | >= 90% of raw | |

## Next Phase Handoff

- Curated data paths:
- Column list:
- Remaining quality flags:
- Open issues:
