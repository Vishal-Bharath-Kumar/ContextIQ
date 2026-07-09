# Architecture Guidelines

SOLID principles and software architecture best practices for robust, maintainable systems.

## Before Implementation
1. Explain SOLID principles applied and affected layers
2. Check SRP adherence and proper dependency inversion
3. Validate interface/class structure and test naming
4. Confirm abstractions are justified and not speculative

## SOLID Principles
- **SRP**: One reason to change per class or module
- **OCP**: Open for extension, closed for modification
- **LSP**: Subtypes must be substitutable for their base types
- **ISP**: No forced dependency on unused interface methods
- **DIP**: Depend on abstractions, not concretions

## General Best Practices
- Non-blocking / async I/O for all network and disk operations
- Strong typing on all public interfaces and data transfer structures
- Structured data transfer objects (DTOs) to cross layer boundaries
- Consistent exception handling with a typed, domain-specific exception hierarchy
- Resource lifecycle managed explicitly (open/close, acquire/release)
- Prefer composition over inheritance; limit inheritance hierarchies to two levels
- Avoid hidden mutable shared state; make dependencies explicit

## Dependency Injection
- Use constructor injection for all dependencies
- Wire the object graph at the composition root (application entry point)
- Define dependencies as interfaces or abstract types, not concrete classes
- Never resolve dependencies from a global registry inside business logic

## Security & Compliance
- Authorization enforced at the service/use-case layer
- Validate all inputs at system boundaries before they reach business logic
- PCI-DSS, SOX, LGPD compliance where applicable
- Immutable audit trails via domain events or append-only logs
- Never log sensitive data (PII, credentials, tokens)
- Use cryptographically secure random sources; never general-purpose RNG for security

## Performance
- Prefer async I/O over blocking threads for network/database work
- Stream or paginate large datasets; avoid loading unbounded collections into memory
- Profile before optimizing; measure with real workloads
- Use connection pooling for database and external service clients
- Cache pure computations at the appropriate layer with explicit invalidation
- Batch database operations; avoid N+1 query patterns

## Layers

### Domain
- No framework or infrastructure imports
- Entities defined by identity; value objects are immutable and equality-based
- Domain services encapsulate logic that spans multiple aggregates
- Raise domain-specific typed exceptions, not generic runtime errors

### Application
- Orchestrate domain operations; contain no business logic itself
- Use cases / interactors accept and return DTOs
- Declare repository and service dependencies as interfaces or abstract types
- Validate input before invoking domain logic

### Infrastructure
- Implement interfaces declared in the domain or application layer
- Encapsulate all persistence, messaging, and external API concerns here
- Keep framework-specific code isolated from domain and application layers

### API
- Thin controllers/routers; delegate all logic to application use cases
- Validate and serialize at the boundary using request/response schemas
- Return consistent error envelopes; map domain exceptions to protocol-level status codes

## Testing
- Naming: `<method>_<condition>_<expected_result>`
- Unit tests for domain logic; no I/O, no framework dependencies
- Integration tests for repository implementations and external adapters
- Acceptance / end-to-end tests for API routes or entry points
- Mock dependencies at layer boundaries; never mock domain objects themselves
- Minimum 85% coverage for domain and application layers

## Test Categories
- Entities/Aggregates: business rules and state transitions
- Value objects: immutability, equality, and validation
- Domain services: complex multi-aggregate operations
- Events: publishing, handling, and ordering
- Use cases: orchestration, validation, and error paths
- Repositories: round-trip persistence (integration tests)

## Financial Domain
- Use a fixed-precision decimal type for all monetary values; never floating-point
- Currency-aware value objects encapsulating amount + ISO 4217 currency code
- Apply rounding per financial standards (e.g., half-even / banker's rounding)
- Saga or process-manager patterns for distributed transactions
- Compensation handlers for rollback on failure
- Immutable audit trails via domain events stored in an append-only event log
