# Dependency Graph Conversion

Converts task/activity dependency definitions between orchestration platforms.

## ADF dependsOn → Databricks depends_on

**Source (ADF):**
```json
"dependsOn": [
  { "activity": "Extract_Data", "dependencyConditions": ["Succeeded"] },
  { "activity": "Load_Config", "dependencyConditions": ["Succeeded"] }
]
```

**Target (Databricks):**
```yaml
depends_on:
  - task_key: extract_data
  - task_key: load_config
```

**Rules:**
- Extract `activity` name from each `dependsOn` entry
- Sanitize to lowercase with underscores for `task_key`
- Only `Succeeded` condition maps directly; other conditions need special handling

## Glue Dependencies → Databricks depends_on

Glue dependencies come from TWO sources:

### Source 1: Graph Edges
```json
"Edges": [
  { "SourceId": "node-001", "DestinationId": "node-002" }
]
```
Resolve node IDs to job names via `Graph.Nodes`.

### Source 2: Conditional Triggers
```json
{
  "Type": "TRIGGER",
  "TriggerDetails": {
    "Trigger": {
      "Type": "CONDITIONAL",
      "Predicate": {
        "Conditions": [
          { "LogicalOperator": "EQUALS", "JobName": "job_a", "State": "SUCCEEDED" }
        ]
      }
    }
  }
}
```

**Resolution:**
```
derived.depends_on = union(
    resolve_predecessors_from_edges(Graph.Edges, Graph.Nodes),
    extract_job_names_from_conditional_triggers(Graph.Nodes[Type=TRIGGER])
)
deduplicate(derived.depends_on)
```

## Databricks depends_on → ADF dependsOn

**Source (Databricks):**
```yaml
depends_on:
  - task_key: extract
```

**Target (ADF):**
```json
"dependsOn": [
  { "activity": "extract", "dependencyConditions": ["Succeeded"] }
]
```

## Validation Rules

1. Dependency graph must be acyclic (no circular dependencies)
2. All referenced task/activity names must exist in the workflow
3. Root tasks (no dependencies) must not have empty depends_on arrays — omit the field entirely
4. Preserve topological execution order
