# Exploratory Data Analysis Plan

## Run Metadata

| Field | Value |
|---|---|
| Workflow | Exploratory Data Analysis |
| Run ID | |
| Snapshot ID | |
| Upstream Workflow | Data Preprocessing |
| Target Column | |
| Source File | |
| Row Count | |
| Column Count | |
| Date | |

---

## 1. Univariate Distribution Summary

One row per feature. Populated during Step 3.

| Feature | Type | % Missing | Mean / Mode | Std / Cardinality | Skewness | Kurtosis | Outlier Count | Flags |
|---|---|---|---|---|---|---|---|---|

**Flags key:** `LOW_VARIANCE` | `NEAR_ZERO_VARIANCE` | `HIGH_MISSING` | `LEAKAGE_RISK` | `CANDIDATE_DROP`

---

## 2. Bivariate Correlation Findings

### Numeric Correlations
| Feature A | Feature B | Pearson r | Spearman r | Flag |
|---|---|---|---|---|

**Flag key:** `MULTICOLLINEARITY` (|r| > 0.9) | `STRONG_TARGET_SIGNAL` (|r| > 0.5 with target) | `WEAK_SIGNAL` (|r| < 0.05 with target)

### Categorical Associations
| Feature | Target | Cramér's V | Chi² p-value | Flag |
|---|---|---|---|---|

### Target vs Each Feature (Summary)
| Feature | Association Metric | Value | Direction | Notes |
|---|---|---|---|---|

---

## 3. Seasonality & Temporal Patterns [CONDITIONAL: datetime features present]

| Datetime Column | Granularity | Trend Detected | Seasonal Period | Cyclic Pattern | Stationarity (ADF p) | Notes |
|---|---|---|---|---|---|---|

**Decomposition outputs:** `visualizations/seasonality_<col>.png` — one per datetime column.

---

## 4. Leakage Risk Register

| Feature | Leakage Type | Severity | Evidence | Decision |
|---|---|---|---|---|

**Leakage types:** `TARGET_ENCODED` (derived from target) | `FUTURE_SIGNAL` (post-event data) | `LABEL_PROXY` (high direct correlation with target via non-causal path) | `TEMPORAL_LEAK` (available at training but not inference time)

**Severity:** `HIGH` (must drop) | `MEDIUM` (needs lag or cutoff enforcement) | `LOW` (flag for review)

**Decision:** `DROP` | `LAG` | `CUTOFF_ENFORCE` | `RETAIN_WITH_NOTE`

---

## 5. Visualization Index

| Plot Name | Type | Feature(s) | File Path | Key Finding |
|---|---|---|---|---|

---

## 6. Acceptance Gates

| Gate | Threshold | Status |
|---|---|---|
| All features analyzed | 0 features with no univariate entry | |
| Leakage register complete | 0 HIGH-severity leakage risks unresolved | |
| Correlation matrix computed | Non-empty correlation matrix produced | |
| Seasonality assessed | All datetime columns assessed (or none present) | |
| Visualizations saved | ≥ 1 `.png` in `visualizations/` | |
| EDA report written | `eda_report.md` exists with non-zero size | |

---

## Next Phase Handoff → Feature Engineering

- EDA report path:
- Visualizations path:
- Target column confirmed:
- Features flagged for DROP (leakage):
- Features flagged for LAG (temporal leakage, handle in FE):
- Strong target signals (priority for feature engineering):
- Multicollinearity pairs (consolidate in FE):
- Seasonality periods detected (use for lag/rolling window sizing):
- Open issues:
