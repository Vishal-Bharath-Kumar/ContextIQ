# Schedule/Trigger Conversion

Converts pipeline trigger and schedule formats between orchestration platforms.

## ADF Trigger → Databricks Schedule

**Source (ADF ScheduleTrigger):**
```json
{
  "type": "ScheduleTrigger",
  "recurrence": {
    "frequency": "Day",
    "interval": 1,
    "schedule": {
      "hours": [10],
      "minutes": [0]
    },
    "timeZone": "UTC"
  }
}
```

**Target (Databricks quartz cron):**
```yaml
schedule:
  quartz_cron_expression: "0 0 10 * * ?"
  timezone_id: "UTC"
```

## ADF Recurrence → Quartz Cron Mapping

| ADF Frequency | ADF Example | Quartz Cron |
|--------------|-------------|-------------|
| Minute | interval: 30 | `0 */30 * * * ?` |
| Hour | interval: 1 | `0 0 * * * ?` |
| Day | interval: 1, hours: [10], minutes: [0] | `0 0 10 * * ?` |
| Week | interval: 1, daysOfWeek: ["Monday"] | `0 0 0 ? * MON` |
| Month | interval: 1, daysOfMonth: [1] | `0 0 0 1 * ?` |

## Glue Trigger → Databricks Schedule

**Source (Glue SCHEDULED trigger):**
```json
{
  "Type": "SCHEDULED",
  "Schedule": "cron(0 10 * * ? *)"
}
```

**Target (Databricks):**
```yaml
schedule:
  quartz_cron_expression: "0 0 10 * * ?"
  timezone_id: "UTC"
```

**Rule:** Glue cron format uses 6 fields (minute hour day month day-of-week year). Quartz also uses 6 fields (second minute hour day month day-of-week). Convert accordingly.

## Databricks → ADF Trigger

**Source (Databricks):**
```yaml
schedule:
  quartz_cron_expression: "0 0 10 * * ?"
  timezone_id: "UTC"
```

**Target (ADF):**
```json
{
  "type": "ScheduleTrigger",
  "recurrence": {
    "frequency": "Day",
    "interval": 1,
    "schedule": { "hours": [10], "minutes": [0] },
    "timeZone": "UTC"
  }
}
```

## Databricks → Glue Trigger

**Target (Glue):**
```json
{
  "Type": "SCHEDULED",
  "Schedule": "cron(0 10 * * ? *)"
}
```

## Rules

1. Preserve exact schedule timing during conversion
2. Preserve timezone (default to UTC if not specified)
3. Handle both scheduled and event-based triggers
4. CONDITIONAL triggers (Glue) → dependsOn (ADF/Databricks)
