# Feature Engineering Plan

## Run Metadata

| Field | Value |
|---|---|
| Workflow | Feature Engineering |
| Run ID | |
| Snapshot ID | |
| Upstream Workflow | Exploratory Data Analysis |
| Target Column | |
| Source File | |
| Input Feature Count | |
| Output Feature Count | |
| Selection Method | |
| Feature Store Registered | |
| Date | |

---

## 1. Temporal Features [CONDITIONAL: time dimension present]

Lag and rolling aggregate features derived from the time index or datetime columns. Sized using seasonality periods from EDA.

| Feature ID | Source Column | Type | Window / Lag | Aggregation | Leakage Cutoff | Inference-Time Available | Rationale |
|---|---|---|---|---|---|---|---|

**Types:** `LAG` | `ROLLING_MEAN` | `ROLLING_STD` | `ROLLING_MIN` | `ROLLING_MAX` | `ROLLING_SUM` | `EWMA` | `DIFF`

**Leakage Cutoff:** Timestamp or row offset that enforces no future data bleeds into the window.

---

## 2. Encoding & Numeric Transforms

| Feature ID | Source Column | Encoding / Transform | Cardinality Before | Cardinality After | Leakage Check | Rationale |
|---|---|---|---|---|---|---|

**Encodings:** `ONE_HOT` | `ORDINAL` | `TARGET_ENCODE` | `FREQUENCY_ENCODE` | `BINARY`
**Transforms:** `LOG` | `SQRT` | `BOX_COX` | `POLYNOMIAL` | `BINNING` | `STANDARDIZE` | `NORMALIZE`

**Note:** `TARGET_ENCODE` requires fold-level fitting inside cross-validation to prevent leakage — document CV strategy here.

---

## 3. Interaction & Baseline Features

| Feature ID | Source Columns | Operation | Business Rationale | EDA Signal (correlation / finding) | Inference-Time Available |
|---|---|---|---|---|---|

**Operations:** `RATIO` | `PRODUCT` | `DIFFERENCE` | `POLYNOMIAL_CROSS` | `CONCAT_EMBED`

**Baseline features** (simple rule-based or statistical benchmarks that the model must beat):
| Baseline ID | Definition | Expected Performance | Used As |
|---|---|---|---|

---

## 4. Feature Selection Log

One row per eliminated or engineered feature. Never delete rows; append only.

| Feature | Action | Reason | Method | Step |
|---|---|---|---|---|

**Actions:** `DROPPED` | `ENGINEERED` | `RETAINED` | `DEFERRED_TO_STORE`
**Methods:** `VARIANCE_THRESHOLD` | `CORRELATION_FILTER` | `MUTUAL_INFO` | `RFE` | `LASSO` | `BORUTA` | `MANUAL`

---

## 5. Feature Store Registration [CONDITIONAL: feature store configured]

| Feature Group | Feature Names | Store Location | Version | Serving Key | Freshness SLA | Training / Serving Parity Verified |
|---|---|---|---|---|---|---|

**Serving Key:** Column(s) used to join features at inference time (e.g. `customer_id`, `entity_id + timestamp`).
**Training / Serving Parity:** Confirm the same feature computation logic runs at training time and inference time. Mark `YES` only when verified end-to-end.

---

## 6. Final Feature Manifest

| Feature Name | Type | Group | Source | Inference-Time Available | Selected | Notes |
|---|---|---|---|---|---|---|

**Selected:** `YES` | `NO` (with reason in Feature Selection Log)

---

## 7. Acceptance Gates

| Gate | Threshold | Status |
|---|---|---|
| No leakage features in output | 0 features from EDA leakage register (HIGH severity) in feature file | |
| All eliminations logged | Count of Section 4 DROPPED entries ≥ columns present in source but absent in feature file | |
| All engineered features logged | Count of Section 4 ENGINEERED entries = new columns in feature file | |
| Target column last | `$TARGET_COL` is final column in feature file | |
| Null target rows | 0 rows where `$TARGET_COL` is null | |
| Temporal leakage cutoffs enforced | All LAG/ROLLING windows use `t - min_lag` cutoff | |
| Training / serving parity | All feature store entries marked `YES` (if feature store configured) | |
| Feature snapshot written | Non-empty `feature_file.csv` (or `.parquet`) + metadata JSON | |

---

## Next Phase Handoff → Model Selection

- Feature file path:
- Snapshot ID:
- Target column:
- Final feature count:
- Feature store group(s) registered:
- Baseline performance (if computed):
- Open issues:
