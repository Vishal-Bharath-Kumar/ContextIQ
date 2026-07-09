# Timeout Validation

Validates and normalizes timeout values across workflow conversions.

## Timeout Conversion

### Unit Conversion
| Source Platform | Source Unit | Target Unit | Conversion |
|----------------|-----------|-------------|-----------|
| AWS Glue | Minutes | Seconds | Multiply by 60 |
| ADF/Synapse | ISO 8601 duration | Seconds | Parse to seconds |
| Databricks | Seconds | Seconds | Direct |

### ISO 8601 Parsing (ADF)
```
"01:00:00" → 3600 seconds (1 hour)
"00:30:00" → 1800 seconds (30 minutes)
"1.00:00:00" → 86400 seconds (1 day)
```

## Policy Caps

Layer-based timeout limits (from policy defaults):

| Layer | Max Timeout (seconds) | Detection Regex |
|-------|----------------------|-----------------|
| Bronze | 28800 (8 hours) | `bronze\|ingest\|raw\|landing\|extract` |
| Silver | 28800 (8 hours) | `silver\|transform\|clean\|curated` |
| Gold | 14400 (4 hours) | `gold\|aggregate\|serve\|report\|analytics` |
| Default | 28800 (8 hours) | Fallback when layer undetectable |

## Checks

### WV-TMO-001: Timeout Present
- Every task should have `timeout_seconds` defined
- If source has no timeout, apply layer-based policy default
- **Severity:** WARNING

### WV-TMO-002: Policy Cap Applied
```
policy_validated_timeout = min(converted_timeout, layer_max_timeout)
IF policy_validated_timeout < converted_timeout:
    log_warning("Timeout adjusted: {source}s → {capped}s. Reason: {layer} policy")
```
- **Severity:** WARNING (when adjusted)

### WV-TMO-003: Reasonable Range
- Timeout should be > 60 seconds (minimum)
- Timeout should not exceed 86400 seconds (24 hours) without justification
- **Severity:** WARNING

### WV-TMO-004: Job-Level Timeout
- Job-level `timeout_seconds` = max(all task timeout_seconds)
- Must be >= any individual task timeout
- **Severity:** ERROR (if job timeout < any task timeout)
