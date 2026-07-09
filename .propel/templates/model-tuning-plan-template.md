# Model Tuning Plan

## Run Metadata

| Field | Value |
|---|---|
| Workflow | Model Tuning |
| Run ID | |
| Tuning Seed | |
| Date | |

## 1. Tuning Strategy

| Setting | Value |
|---|---|
| Champion candidate | |
| Tuning method | Bayesian (Optuna) / Grid / Random |
| Budget (n_trials or time) | |
| CV folds | |
| Scoring metric | |
| Test set access | SEALED |

## 2. Search Space

| Hyperparameter | Type | Range / Choices | Prior / Distribution |
|---|---|---|---|

## 3. Reproducibility Controls

| Control | Value |
|---|---|
| Sampler seed | |
| Trial log path | |
| Best params artifact | |

## 4. Retrain Protocol

| Step | Detail |
|---|---|
| Dataset for final retrain | train + val combined |
| Evaluation set | val only |
| Test set | still sealed |

## 5. Implementation Tasks

| Task ID | Title | Inputs | Outputs | Acceptance Criteria | Status |
|---|---|---|---|---|---|

## 6. Acceptance Gates

| Gate | Threshold | Status |
|---|---|---|
| All trials logged | Full trial history present | |
| Best params artifact written | Non-empty JSON | |
| Improvement over training baseline | >= 0% on val metric | |
| Retrain with best params complete | Artifact written + hashed | |
| Tuning seed logged | Present in metadata | |

## Next Phase Handoff

- Best params path:
- Tuned artifact path:
- Val metric improvement:
- Open issues:
