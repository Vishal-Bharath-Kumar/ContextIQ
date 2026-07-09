# Dependency Validation

Validates the dependency graph in generated workflow definitions.

## Checks

### WV-DEP-001: Acyclic Graph
- Dependency graph must have no circular dependencies
- Run topological sort; if cycle detected → ERROR
- **Severity:** ERROR
- **Detection:** Build directed graph from depends_on/dependsOn, detect cycles

### WV-DEP-002: Valid References
- All task/activity names in dependency lists must exist in the workflow
- `depends_on[].task_key` must match an existing `task_key` in `tasks[]`
- `dependsOn[].activity` must match an existing activity `name`
- **Severity:** ERROR

### WV-DEP-003: Root Tasks
- At least one task must have no dependencies (entry point)
- Root tasks should NOT have empty `depends_on: []` — omit the field entirely
- **Severity:** WARNING (if empty array present instead of omitted)

### WV-DEP-004: Dependency Count Preserved
- Number of dependency edges in target should match source
- If source has N dependency relationships, target must have N
- **Severity:** WARNING (if mismatch)

### WV-DEP-005: Execution Order Preserved
- Topological order in target must respect source execution order
- If source has A → B → C, target must maintain A before B before C
- **Severity:** ERROR

### WV-DEP-006: No Orphaned Tasks
- Every task must be reachable from a root task through the dependency graph
- OR every task must be a root task itself
- Unreachable tasks indicate missing dependencies
- **Severity:** WARNING

## Validation Method

```
1. Build adjacency list from depends_on fields
2. Run topological sort (Kahn's algorithm)
3. If cycle → ERROR with cycle path
4. Verify all references resolve to existing tasks
5. Count edges: source_edges == target_edges
6. Verify reachability from root tasks
```
