# DS Requirements Specification

## ML Problem Statement

### Problem Definition
- **Task Type**: [Classification | Regression | Clustering | Ranking | Anomaly Detection | Forecasting | NLP | Computer Vision | Recommendation | Other]
- **Problem Subtype**: [Binary classification | Multi-class | Multi-label | Time-series forecasting | etc.]
- **Target Variable**: `[column_name]` — [Description of what it represents and how it is measured]
- **Prediction Horizon**: [Point-in-time | Rolling window | N-step ahead | Not applicable]
- **Input Features (known at inference)**: [List or describe feature groups available at prediction time — no leakage]
- **Baseline**: [Current rule-based logic | Previous model version | Naive benchmark (e.g. majority class, mean prediction)]

### Business Goal & Justification
- [Business value and user impact]
- [Decision or action this model enables]
- [Problems this solves and for whom]
- [Integration with existing workflows or products]

## Feature Scope
[User-visible and system-visible behaviour the ML capability enables]

### Success Criteria
- [ ] [Primary ML metric] ≥ [threshold] on held-out test set
- [ ] [Business KPI] improved by [N]% vs. baseline
- [ ] [Latency / throughput SLA if applicable]

---

## Data Requirements

### Data Sources
| Source | Owner | Format | Volume Estimate | Freshness / Lag | PII? | Licensed? |
|--------|-------|--------|----------------|-----------------|------|-----------|
| [source name] | [team/system] | [CSV/DB/API/etc.] | [rows or GB] | [daily/real-time/etc.] | [Yes/No] | [Yes/No] |

### Labelling & Ground Truth
- **Label Source**: [How ground truth is obtained — human annotation, system event, proxy signal, etc.]
- **Label Quality**: [Known noise, inter-annotator agreement, proxy validity concerns]
- **Historical Coverage**: [Date range available for training]
- **Class Distribution**: [Balanced | Imbalanced — describe ratio if known]
- **Label Lag**: [How long after the event is the label available]

### Data Quality Constraints
- DR-001: [SOURCE:INPUT|INFERRED|EXTERNAL] Data MUST [constraint — specific, testable]
  Basis: [Justification]
- DR-NNN: [SOURCE:INPUT|INFERRED|EXTERNAL] Data MUST [constraint]
  Basis: [Justification]

---

## Functional Requirements

### [Business Feature/Module Name]
- FR-001: [SOURCE:INPUT|INFERRED|EXTERNAL] System MUST [observable behaviour — specific, testable, unambiguous]
  Basis: [One sentence — what input text, inference reasoning, or external source justifies this requirement]
- FR-002: [TAG] [SOURCE:INPUT|INFERRED|EXTERNAL] System MUST [observable behaviour]
  Basis: [Justification]
- FR-NNN: [TAG] [SOURCE:INPUT|INFERRED|EXTERNAL] System MUST [observable behaviour]
  Basis: [Justification]

---

## Model Performance Requirements

### Primary Metric
| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| [metric name e.g. F1, RMSE, AUC-ROC] | ≥ [value] | [Why this threshold is the acceptance bar] |

### Secondary Metrics
| Metric | Target | Notes |
|--------|--------|-------|
| [metric name] | [target value] | [e.g. used for monitoring, not a release gate] |

### Fairness Criteria [CONDITIONAL: protected attributes identified in scope]
| Protected Attribute | Fairness Metric | Max Allowed Disparity | Mitigation Strategy |
|---------------------|----------------|----------------------|---------------------|
| [e.g. gender, age group] | [e.g. equalized odds, demographic parity] | [≤ N%] | [pre/in/post-processing approach] |

---

## Use Case Analysis

### Actors & System Boundary
(e.g., Data Consumer, Business Analyst, ML Engineer, Downstream System — not limited to these)
- [Primary Actor]: [Role description and responsibilities]
- [Secondary Actor]: [Supporting role and interaction type]
- [System Actor]: [External data sources, model serving infrastructure, monitoring systems]

### System Context Diagram
<!-- RENDER type="plantuml" src="./uml-models/system-context.png" -->

![System Context Diagram](./uml-models/system-context.png)

```plantuml
[System boundary, ML pipeline stages, and interactions with data sources, model consumers, and monitoring systems.]
```

### Use Case Specifications
For each goal derive the use case and provide detailed specifications:

#### UC-[ID]: [Use Case Name]
- **Actor(s)**: [Primary Actor]
- **Parent Requirements**: [FR-XXX, DR-XXX — requirements and data constraints this use case implements]
- **Goal**: [What the actor wants to achieve]
- **Preconditions**: [System state and data state before use case]
- **Success Scenario**:
  1. [Step 1]
  2. [Step 2]
  3. [Step 3]
- **Extensions/Alternatives**:
  - 2a. [Alternative flow]
  - 3a. [Exception handling — e.g. missing feature values, model confidence below threshold]
- **Postconditions**: [System state after successful completion]

##### Use Case Diagram

<!-- RENDER type="plantuml" src="./uml-models/[uc-name].png" -->

![UC-[ID] Use Case Diagram](./uml-models/[uc-name].png)

```plantuml
[MUST replace this line with the generated PlantUML script for UC-[ID] before completing]
```

---

## Deployment & Serving Requirements
- **Inference Mode**: [Batch | Real-time API | Embedded | Streaming]
- **Latency SLA**: [p95 ≤ N ms | N seconds per batch | Not applicable]
- **Throughput**: [N requests/sec | N rows/run]
- **Retraining Frequency**: [On-demand | Weekly | Monthly | Triggered by drift alert]
- **Drift Detection**: [Data drift | Concept drift | Both | Not required]
- **Human-in-the-Loop**: [Required | Optional | Not required] — [Describe review/override workflow if required]

---

## Governance & Ethics
- **Explainability Level**: [None | Feature importance | Local explanations (SHAP/LIME) | Full audit trail]
- **Regulatory Scope**: [GDPR | HIPAA | CCPA | SOC2 | Industry-specific regulation | None identified]
- **Audit Requirements**: [Log predictions | Log input features | Log model version | Retain for N years]
- **Model Card Required**: [Yes | No]
- **Risk Classification**: [High | Medium | Low] — [Rationale]

---

## Risks & Mitigations
- [Risk]: [Mitigation strategy]

## Constraints & Assumptions
- [Constraint or assumption with rationale]
