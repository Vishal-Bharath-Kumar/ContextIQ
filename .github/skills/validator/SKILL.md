---
name: validator
description: Validates converted cloud data pipelines with 7-category scoring (0-100 points) and generates structured validation reports. Invoked after optimization as a post-processing step.
---

# Notebook Validator

Validates converted cloud data pipelines and generates quality reports.

## Validation Categories (100 points)

| Category | Max Points | What It Checks |
|----------|-----------|----------------|
| Syntax | 15 | No errors, imports valid, indentation correct, valid JSON |
| Service Mapping | 20 | Protocols consistent, paths converted, APIs correct |
| Security | 20 | No hardcoded creds, auth model converted, secrets proper |
| Execution Engine | 15 | Runtime compatible, no source artifacts, target APIs used |
| Data Integrity | 15 | Schemas preserved, logic intact, partitions maintained |
| Performance | 10 | No anti-patterns (coalesce(1), collect(), loops) |
| Cost | 5 | Appropriate tier, auto-scaling, resource cleanup |

## Scoring Thresholds

- **90-100**: Excellent — Production ready
- **75-89**: Good — Minor fixes needed
- **60-74**: Fair — Several issues
- **40-59**: Poor — Significant rework
- **0-39**: Failed — Major issues

## Validation Checks

### 1. Syntax (15 pts)
- [ ] No Python syntax errors (ast.parse)
- [ ] All imports valid
- [ ] Proper indentation
- [ ] No undefined variables
- [ ] Valid JSON (for notebooks)

### 2. Service Mapping (20 pts)
**Storage paths (8 pts):**
- [ ] No mixed protocols (s3:// and abfss://)
- [ ] All paths converted correctly
- [ ] Container/bucket names valid

**Compute (6 pts):**
- [ ] Context initialization correct
- [ ] No source platform artifacts
- [ ] Target platform APIs used

**Catalog (6 pts):**
- [ ] Table reads converted
- [ ] Table writes converted
- [ ] Database references updated

### 3. Security (20 pts)
**Credentials (8 pts):**
- [ ] No hardcoded access keys
- [ ] No passwords in plain text
- [ ] No connection strings with secrets

**Auth model (6 pts):**
- [ ] IAM/RBAC properly converted
- [ ] Managed Identity used (Azure) / IAM roles (AWS)

**Secrets (6 pts):**
- [ ] Secrets use proper service
- [ ] No secrets in env vars

### 4. Execution Engine (15 pts)
**Compatibility (8 pts):**
- [ ] Code works on target engine
- [ ] No source engine APIs remaining

**Engine-specific checks:**
- **Glue**: GlueContext initialized, DynamicFrames used, job.commit() present
- **Synapse**: No GlueContext, Spark pre-initialized, mssparkutils used
- **Databricks**: dbutils widgets/secrets, no GlueContext/mssparkutils
- **EMR**: Spark configs optimized, S3A configurations set
- **Fabric**: Delta lakehouse tables used, notebookutils for secrets/params, lakehouse context cell present as first code cell, no GlueContext/dbutils/mssparkutils

### 5. Data Integrity (15 pts)
- [ ] Column names preserved
- [ ] Data types maintained
- [ ] Business logic unchanged
- [ ] Aggregations and joins preserved
- [ ] Partition columns preserved

### 6. Performance (10 pts)
**WARN if found:**
- `.coalesce(1)` — Single partition bottleneck
- `.collect()` — Collect to driver
- `df.count()` in loops

**Check:**
- [ ] Storage and compute co-located
- [ ] No cross-region transfers

### 7. Cost (5 pts)
- [ ] Not using premium unnecessarily
- [ ] Auto-scaling enabled
- [ ] Resource cleanup implemented

## Auto-Fix Capability

**Can auto-fix:** Missing imports, path format errors, simple syntax, missing job.commit()
**Cannot auto-fix:** Hardcoded credentials, complex logic errors, schema mismatches

## Report Format

```markdown
============================================================
[CONVERTED PIPELINE] VALIDATION REPORT
============================================================

**Pipeline:** [filename]
**Source:** [AWS Glue/Azure Synapse/Databricks]
**Target:** [Target Cloud + Engine]
**Validation Status:** [EXCELLENT/GOOD/FAIR/POOR/FAILED] ([score]/100)

---

## VALIDATION SUMMARY

| Check | Result | Details |
|-------|--------|---------|
| Source Detection | [PASS/FAIL] | [Confidence %] |
| Target Conversion | [PASS/FAIL] | [Completeness %] |
| Imports | [PASS/FAIL] | [Count converted] |
| Storage Paths | [PASS/FAIL] | [Count converted] |
| APIs | [PASS/FAIL] | [Count converted] |

## CATEGORY SCORES

| Category | Max | Score | Status |
|----------|-----|-------|--------|
| Syntax | 15 | [X] | [PASS/WARN/FAIL] |
| Service Mapping | 20 | [X] | [PASS/WARN/FAIL] |
| Security | 20 | [X] | [PASS/WARN/FAIL] |
| Execution Engine | 15 | [X] | [PASS/WARN/FAIL] |
| Data Integrity | 15 | [X] | [PASS/WARN/FAIL] |
| Performance | 10 | [X] | [PASS/WARN/FAIL] |
| Cost | 5 | [X] | [PASS/WARN/FAIL] |
| **TOTAL** | **100** | **[X]** | **[STATUS]** |

## DETAILED FINDINGS
[Per-category detailed tables with check/status/details]
```
