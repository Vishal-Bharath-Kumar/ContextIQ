# ContextIQ — UML Design Models

## Metadata

| Field | Value |
|---|---|
| Project | ContextIQ |
| Document Type | UML Design Models |
| Version | 1.0 |
| Status | Draft |
| Author | GitHub Copilot (generated from design.md v1.0 + spec.md v1.0) |
| Sources | `.propel/context/docs/design.md`, `.propel/context/docs/spec.md` |
| Date | 2026-07-09 |

---

## Diagram Index

| ID | Diagram | Type |
|---|---|---|
| DM-001 | System Context | C4 Context |
| DM-002 | Platform Containers | C4 Container |
| DM-003 | Data Plane Components | C4 Component |
| DM-004 | Control Plane Components | C4 Component |
| DM-005 | Domain Conceptual Model | Class Diagram |
| DM-006 | Agent Class Hierarchy | Class Diagram |
| DM-007 | Connector Class Hierarchy | Class Diagram |
| DM-008 | Relational Data Model | ER Diagram |
| DM-009 | Knowledge Graph Schema | ER Diagram |
| DM-010 | Context Request Lifecycle | Data Flow |
| DM-011 | Connector Synchronization Flow | Data Flow |
| DM-012 | Polyglot Persistence Data Flow | Data Flow |
| DM-013 | End-to-End AI Request | Sequence |
| DM-014 | Governance Agent Processing | Sequence |
| DM-015 | Dynamic Model Routing | Sequence |
| DM-016 | Administrator Connector Configuration | Sequence |
| DM-017 | AI Request Execution State Machine | State Diagram |
| DM-018 | Connector Lifecycle State Machine | State Diagram |
| DM-019 | Kubernetes Deployment Topology | Deployment |

---

## DM-001 — System Context

```mermaid
C4Context
    title ContextIQ — System Context Diagram

    Person(dev, "Developer / SRE", "Submits natural language prompts via AI coding assistant for code search, incident investigation, and documentation lookup.")
    Person(admin, "Platform Administrator", "Configures enterprise connectors, manages knowledge sources, users, and policies.")
    Person(sec, "Security Officer", "Authors OPA governance policies, monitors sensitive data masking, and reviews compliance dashboards.")
    Person(mgr, "Engineering Manager", "Reviews AI usage, cost, and productivity dashboards.")

    System_Boundary(contextiq_boundary, "ContextIQ Platform") {
        System(contextiq, "ContextIQ", "Enterprise AI Context Engineering Platform. Orchestrates context retrieval, compression, governance, and model routing before any LLM invocation.")
    }

    System_Ext(ai_assistants, "AI Coding Assistants", "Cursor, GitHub Copilot, Claude Code, Windsurf, Continue, Cline, Roo Code. Communicate via Model Context Protocol.")
    System_Ext(source_code, "Source Code Systems", "GitHub, GitLab, Bitbucket, Azure DevOps")
    System_Ext(docs, "Documentation Platforms", "Confluence, SharePoint, Notion")
    System_Ext(pm, "Project Management", "Jira, Azure Boards, Linear")
    System_Ext(monitoring, "Monitoring Systems", "Grafana, Prometheus, Datadog, Splunk")
    System_Ext(comms, "Communication Platforms", "Slack, Microsoft Teams")
    System_Ext(llm_providers, "LLM Providers", "OpenAI, Anthropic, Google Gemini, Ollama, vLLM, LM Studio")
    System_Ext(idp, "Identity Providers", "Keycloak, Microsoft Entra ID, Okta, Auth0")

    Rel(dev, ai_assistants, "Submits prompts")
    Rel(ai_assistants, contextiq, "MCP Tool Discovery and Invocation", "MCP over SSE/WebSocket")
    Rel(admin, contextiq, "Configures connectors, policies, users", "HTTPS/Admin Portal")
    Rel(sec, contextiq, "Authors policies, reviews governance", "HTTPS/Admin Portal")
    Rel(mgr, contextiq, "Views dashboards", "HTTPS/Admin Portal")
    Rel(contextiq, source_code, "Retrieves code, commits, PRs", "OAuth2 REST API")
    Rel(contextiq, docs, "Retrieves documentation", "OAuth2 REST API")
    Rel(contextiq, pm, "Retrieves incidents, tickets", "OAuth2 REST API")
    Rel(contextiq, monitoring, "Retrieves metrics, logs", "API Key REST")
    Rel(contextiq, comms, "Retrieves communications", "OAuth2 REST API")
    Rel(contextiq, llm_providers, "Routes AI requests", "LiteLLM unified API")
    Rel(contextiq, idp, "Authenticates users", "OIDC/SAML 2.0")
```

---

## DM-002 — Platform Containers

```mermaid
C4Container
    title ContextIQ — Container Diagram

    Person(user, "Developer / SRE", "Uses AI assistant")
    Person(admin, "Administrator", "Manages platform")

    System_Ext(ai_assistant, "AI Coding Assistant", "MCP client")
    System_Ext(llm, "LLM Providers", "via LiteLLM")
    System_Ext(idp, "Identity Provider", "Keycloak / Entra ID")
    System_Ext(enterprise_systems, "Enterprise Systems", "GitHub, Jira, Confluence, Grafana")

    System_Boundary(contextiq, "ContextIQ Platform") {

        Container(admin_portal, "Admin Portal", "React + FastAPI", "Web UI for connector management, policy authoring, RBAC, observability dashboards, and replay explorer.")

        Container(mcp_gateway, "Enterprise MCP Gateway", "FastMCP + Python", "Single MCP entry point. Authenticates AI assistants, manages sessions, routes to Supervisor Agent, streams responses.")

        Container(supervisor, "Supervisor Agent", "LangGraph StateGraph", "Coordinates multi-agent pipeline. Initializes execution state, delegates to specialized agents, records replay metadata.")

        Container(agent_pipeline, "Multi-Agent Pipeline", "LangGraph Nodes", "Intent Detection, Context Planning, Retrieval, Knowledge Graph, Ranking, Compression, Governance, Model Router, Response Builder.")

        Container(connector_framework, "Connector Framework", "Python Plugin SDK", "Plugin-based integrations with enterprise systems. BaseConnector SDK with authenticate, discover, search, fetch, sync, health.")

        Container(ai_gateway, "AI Gateway", "LiteLLM", "Unified LLM API. Authentication, rate limiting, retry, fallback, cost tracking, model abstraction across 100+ providers.")

        ContainerDb(postgres, "PostgreSQL", "PostgreSQL 16", "Users, organizations, connectors, policies, executions, audit logs, knowledge sources.")

        ContainerDb(neo4j, "Neo4j", "Neo4j 5", "Enterprise knowledge graph. Service, Repository, Developer, Incident, API, Deployment nodes and relationships.")

        ContainerDb(qdrant, "Qdrant", "Qdrant 1.9", "Vector embeddings for semantic search. Collections: source_code, documentation, incidents, logs, architecture.")

        ContainerDb(opensearch, "OpenSearch", "OpenSearch 2.13", "Keyword and hybrid BM25+kNN search across logs, documentation, wikis, Jira tickets.")

        ContainerDb(redis, "Redis", "Redis 7.2", "Session cache, context cache, prompt cache, response cache with TTL-based eviction.")

        ContainerDb(minio, "MinIO", "MinIO 2024", "S3-compatible object storage for replay snapshots, AI artifacts, architecture diagrams.")

        Container(kafka, "Apache Kafka", "Kafka 3.7 KRaft", "Event streaming for agent pipeline events, observability fan-out, dead letter queues.")

        Container(keycloak, "Keycloak", "Keycloak 24", "OIDC/SAML identity provider. Federates with Entra ID, Okta, Auth0. Issues JWTs for all platform interactions.")

        Container(opa, "Open Policy Agent", "OPA 0.65", "Declarative policy evaluation using Rego. Evaluates access, model, connector, cost, and compliance policies.")

        Container(vault, "HashiCorp Vault", "Vault 1.15", "Secrets management with dynamic credential generation and auto-rotation for all databases and APIs.")

        Container(observability, "Observability Stack", "Prometheus + Grafana + Loki + Jaeger + Langfuse", "Metrics, dashboards, alerts, log aggregation, distributed tracing, AI execution traces.")
    }

    Rel(ai_assistant, mcp_gateway, "MCP Tool Discovery & Invocation", "SSE / WebSocket / HTTP")
    Rel(admin, admin_portal, "Manages platform", "HTTPS")
    Rel(mcp_gateway, keycloak, "Validates JWT", "OIDC introspection")
    Rel(mcp_gateway, opa, "Evaluates access policy", "HTTP")
    Rel(mcp_gateway, supervisor, "Routes authenticated request", "Internal gRPC")
    Rel(supervisor, agent_pipeline, "Orchestrates agents", "LangGraph StateGraph")
    Rel(agent_pipeline, connector_framework, "Executes retrieval", "Plugin calls")
    Rel(connector_framework, enterprise_systems, "Fetches enterprise data", "OAuth2/API Key REST")
    Rel(agent_pipeline, qdrant, "Semantic search", "gRPC")
    Rel(agent_pipeline, opensearch, "Keyword search", "REST")
    Rel(agent_pipeline, neo4j, "Graph traversal", "Bolt")
    Rel(agent_pipeline, redis, "Cache read/write", "Redis protocol")
    Rel(agent_pipeline, opa, "Policy evaluation", "HTTP")
    Rel(agent_pipeline, kafka, "Publishes domain events", "Kafka producer")
    Rel(agent_pipeline, ai_gateway, "Routes LLM request", "REST")
    Rel(ai_gateway, llm, "LLM API calls", "HTTPS REST")
    Rel(agent_pipeline, postgres, "Persists execution traces", "psycopg3")
    Rel(agent_pipeline, minio, "Stores snapshots", "S3 API")
    Rel(kafka, observability, "Streams telemetry events", "Kafka consumer")
    Rel(mcp_gateway, observability, "Emits OTel metrics/traces", "OTel gRPC")
    Rel(vault, agent_pipeline, "Provides dynamic secrets", "Vault API")
    Rel(idp, keycloak, "Federated identity", "SAML / OIDC federation")
```

---

## DM-003 — Data Plane Components

```mermaid
C4Component
    title ContextIQ — Data Plane Component Diagram

    Container_Boundary(gateway_container, "Enterprise MCP Gateway") {
        Component(mcp_server, "MCP Server", "FastMCP", "Handles MCP tool discovery and invocation over SSE, WebSocket, and HTTP transports.")
        Component(auth_filter, "Authentication Filter", "Keycloak OIDC Middleware", "Validates Bearer JWT tokens on every incoming request.")
        Component(session_mgr, "Session Manager", "Redis-backed", "Creates and tracks active AI assistant sessions with TTL.")
        Component(request_router, "Request Router", "FastAPI", "Routes authenticated MCP requests to Supervisor Agent via internal gRPC.")
    }

    Container_Boundary(supervisor_container, "Supervisor Agent") {
        Component(state_init, "State Initializer", "LangGraph", "Creates ExecutionState with executionId, sessionId, user context.")
        Component(graph_runner, "Graph Runner", "LangGraph StateGraph", "Executes the agent pipeline graph, handles conditional routing and retries.")
        Component(replay_recorder, "Replay Recorder", "Kafka Producer", "Emits agent completion events to Kafka replay topic after each node.")
        Component(metrics_emitter, "Metrics Emitter", "OpenTelemetry SDK", "Emits Prometheus metrics and OTel trace spans per agent execution.")
    }

    Container_Boundary(agents_container, "Multi-Agent Pipeline Nodes") {
        Component(intent_agent, "Intent Detection Agent", "LLM + Classifier", "Classifies prompt into intent type, domain, complexity, confidence, and recommended connectors.")
        Component(planner_agent, "Context Planning Agent", "Rule-based + LLM", "Selects connectors, builds parallel execution plan, allocates token budget, estimates cost and latency.")
        Component(retrieval_agent, "Retrieval Agent", "Async Connector Calls", "Executes connector calls concurrently within token budget. Normalizes and deduplicates results.")
        Component(kg_agent, "Knowledge Graph Agent", "Neo4j Cypher", "Extracts entities from documents, traverses knowledge graph up to configured depth.")
        Component(ranking_agent, "Ranking Agent", "Hybrid Scoring", "Scores documents by relevance, freshness, confidence, source reliability using RRF fusion.")
        Component(compression_agent, "AI Compression Agent", "Rule + Semantic + LLM", "Three-stage compression: rule-based dedup, semantic merge (cosine > 0.92), LLM summarization.")
        Component(governance_agent, "Governance Agent", "OPA + Regex + NER", "Context classification, PII detection, secret scanning, data masking, OPA policy evaluation.")
        Component(model_router, "Dynamic Model Router", "Scoring Function + OPA", "Weighted scoring against Model Capability Registry. OPA policy filter. Failover chain.")
        Component(response_builder, "Response Builder", "Aggregator", "Merges governed context, citations, compression metrics, selected model, execution summary.")
    }

    Rel(mcp_server, auth_filter, "Passes request")
    Rel(auth_filter, session_mgr, "Validates and loads session")
    Rel(session_mgr, request_router, "Enriched request + session")
    Rel(request_router, state_init, "Initializes execution state")
    Rel(state_init, graph_runner, "Starts pipeline graph")
    Rel(graph_runner, intent_agent, "Node: detect_intent")
    Rel(graph_runner, planner_agent, "Node: plan_context")
    Rel(graph_runner, retrieval_agent, "Node: retrieve_context [parallel]")
    Rel(graph_runner, kg_agent, "Node: expand_graph")
    Rel(graph_runner, ranking_agent, "Node: rank_context")
    Rel(graph_runner, compression_agent, "Node: compress_context")
    Rel(graph_runner, governance_agent, "Node: apply_governance")
    Rel(graph_runner, model_router, "Node: route_model")
    Rel(graph_runner, response_builder, "Node: build_response")
    Rel(graph_runner, replay_recorder, "After each node completion")
    Rel(graph_runner, metrics_emitter, "Emits span per node")
```

---

## DM-004 — Control Plane Components

```mermaid
C4Component
    title ContextIQ — Control Plane Component Diagram

    Container_Boundary(admin_portal_container, "Admin Portal") {
        Component(portal_ui, "Portal UI", "React + TypeScript", "SPA providing connector management, knowledge source config, policy editor, user management, observability dashboards, replay explorer.")
        Component(portal_api, "Portal API", "FastAPI", "REST API serving the Portal UI. Exposes /api/v1 endpoints for all admin operations.")
        Component(connector_mgr, "Connector Manager", "Python Service", "Registers, tests, and configures connector plugins. Triggers sync schedules.")
        Component(knowledge_mgr, "Knowledge Source Manager", "Python Service", "Manages knowledge source config. Triggers incremental indexing via Kafka.")
        Component(policy_mgr, "Policy Manager", "Python + OPA", "CRUD for OPA Rego policies. Provides policy simulation sandbox. Pushes new versions to OPA.")
        Component(model_registry, "Model Registry", "Python Service", "Stores LLM capability metadata. Monitors model health endpoints. Updates routing registry.")
        Component(user_mgr, "User Manager", "Python + Keycloak Admin API", "RBAC management. Creates users, assigns roles, manages teams and departments.")
        Component(prompt_mgr, "Prompt Template Manager", "Python Service", "CRUD for reusable prompt templates stored in PostgreSQL.")
        Component(replay_service, "Replay Service", "Python Service", "Queries PostgreSQL execution records and MinIO snapshots. Serves replay timeline to Portal UI.")
        Component(obs_service, "Observability Service", "Python + Grafana API", "Aggregates dashboard data from Prometheus, Loki, Jaeger, Langfuse. Serves dashboard API.")
    }

    Rel(portal_ui, portal_api, "REST API calls", "HTTPS JSON")
    Rel(portal_api, connector_mgr, "Connector operations")
    Rel(portal_api, knowledge_mgr, "Knowledge source operations")
    Rel(portal_api, policy_mgr, "Policy CRUD + simulation")
    Rel(portal_api, model_registry, "Model management")
    Rel(portal_api, user_mgr, "User and role management")
    Rel(portal_api, prompt_mgr, "Prompt template management")
    Rel(portal_api, replay_service, "Replay queries")
    Rel(portal_api, obs_service, "Dashboard data")
```

---

## DM-005 — Domain Conceptual Model

```mermaid
classDiagram
    class AIRequest {
        +String requestId
        +String userId
        +String sessionId
        +String assistantType
        +String prompt
        +DateTime timestamp
        +submit()
    }

    class ExecutionState {
        +String executionId
        +String sessionId
        +String userId
        +IntentResult intent
        +ExecutionPlan plan
        +List~Document~ retrievedDocuments
        +GraphContext knowledgeGraph
        +List~Document~ rankedContext
        +String compressedContext
        +String governedContext
        +String selectedModel
        +String response
        +ExecutionMetrics metrics
    }

    class IntentResult {
        +String intent
        +Float confidence
        +String domain
        +String complexity
        +List~String~ recommendedConnectors
    }

    class ExecutionPlan {
        +String executionMode
        +List~String~ selectedConnectors
        +List~String~ selectedTools
        +Int tokenBudget
        +Float estimatedLatencySeconds
        +Float estimatedCostUsd
    }

    class ExecutionMetrics {
        +Int originalTokens
        +Int compressedTokens
        +Float compressionRatio
        +Int latencyMs
        +Float costUsd
        +String selectedModel
        +List~String~ policiesApplied
    }

    class KnowledgeSource {
        +String id
        +String name
        +String connectorType
        +String priority
        +String indexingStrategy
        +Int refreshIntervalMinutes
        +DateTime lastSync
        +configure()
        +triggerSync()
    }

    class MCPTool {
        +String name
        +String description
        +String version
        +JsonSchema inputSchema
        +JsonSchema outputSchema
        +List~String~ requiredPermissions
        +String connectorAssociation
        +invoke(args)
    }

    class Policy {
        +String id
        +String name
        +String version
        +String regoPolicy
        +String status
        +evaluate(input)
        +simulate(input)
    }

    class ModelCapability {
        +String provider
        +String modelId
        +Int codingScore
        +Int reasoningScore
        +Int contextWindow
        +Float costPer1kTokens
        +Int avgLatencyMs
        +Boolean visionSupport
        +Boolean functionCallingSupport
        +Boolean onPremSupport
        +String healthStatus
        +Float score(weights)
    }

    class ConnectorPlugin {
        <<abstract>>
        +String connectorId
        +String type
        +String status
        +authenticate()
        +discover()
        +search(query)
        +fetch(resourceId)
        +sync()
        +health()
    }

    class Execution {
        +String executionId
        +String sessionId
        +String userId
        +String intent
        +String complexity
        +String selectedModel
        +Int tokenIn
        +Int tokenOut
        +Float compressionRatio
        +Int latencyMs
        +Float costUsd
        +String status
        +DateTime createdAt
    }

    class AuditLog {
        +DateTime timestamp
        +String userId
        +String sessionId
        +String executionId
        +String traceId
        +String action
        +String resource
        +String result
        +String ipAddress
        +String userAgent
    }

    AIRequest "1" --> "1" ExecutionState : creates
    ExecutionState "1" *-- "1" IntentResult : contains
    ExecutionState "1" *-- "1" ExecutionPlan : contains
    ExecutionState "1" *-- "1" ExecutionMetrics : contains
    ExecutionPlan "1" --> "many" KnowledgeSource : selects
    ExecutionPlan "1" --> "many" MCPTool : invokes
    Policy "many" --> "1" ExecutionState : governs
    ModelCapability "many" --> "1" ExecutionState : routes to
    ConnectorPlugin "1" --> "many" KnowledgeSource : indexes
    ExecutionState "1" --> "1" Execution : persisted as
    ExecutionState "1" --> "many" AuditLog : generates
```

---

## DM-006 — Agent Class Hierarchy

```mermaid
classDiagram
    class BaseAgent {
        <<abstract>>
        +String agentId
        +String agentType
        +ExecutionState state
        +KafkaProducer eventProducer
        +OTelTracer tracer
        +execute(state) ExecutionState*
        +emitEvent(topic, payload)
        +recordSpan(spanName)
    }

    class SupervisorAgent {
        +LangGraph stateGraph
        +initializeState(request) ExecutionState
        +runPipeline(state) ExecutionState
        +handleRetry(node, error)
        +aggregateResults(state) ExecutionState
    }

    class IntentDetectionAgent {
        +LLMClient llmClient
        +List~String~ intentClasses
        +Float confidenceThreshold
        +classifyIntent(prompt) IntentResult
        +recommendConnectors(intent) List~String~
        +execute(state) ExecutionState
    }

    class ContextPlanningAgent {
        +ConnectorRegistry connectorRegistry
        +TokenBudgetCalculator budgetCalc
        +buildExecutionPlan(intent) ExecutionPlan
        +estimateLatency(connectors) Float
        +estimateCost(tokens, model) Float
        +execute(state) ExecutionState
    }

    class RetrievalAgent {
        +ConnectorFramework connectorFramework
        +QdrantClient qdrantClient
        +OpenSearchClient openSearchClient
        +retrieveParallel(plan) List~Document~
        +hybridSearch(query) List~Document~
        +normalizeResults(raw) List~Document~
        +execute(state) ExecutionState
    }

    class KnowledgeGraphAgent {
        +Neo4jDriver neo4jDriver
        +EntityExtractor entityExtractor
        +Int maxTraversalDepth
        +extractEntities(docs) List~Entity~
        +traverseGraph(entities) GraphContext
        +execute(state) ExecutionState
    }

    class RankingAgent {
        +Float vectorWeight
        +Float keywordWeight
        +reciprocalRankFusion(docs) List~Document~
        +scoreByFreshness(doc) Float
        +scoreByConfidence(doc) Float
        +execute(state) ExecutionState
    }

    class CompressionAgent {
        +RuleBasedCompressor ruleCompressor
        +SemanticCompressor semanticCompressor
        +LLMSummarizer llmSummarizer
        +Float cosineThreshold
        +compress(docs, budget) String
        +execute(state) ExecutionState
    }

    class GovernanceAgent {
        +PIIDetector piiDetector
        +SecretDetector secretDetector
        +DataMasker dataMasker
        +OPAClient opaClient
        +classifyContext(text) SensitivityLevel
        +maskSensitiveData(text) String
        +evaluatePolicy(input) PolicyResult
        +execute(state) ExecutionState
    }

    class DynamicModelRouter {
        +ModelCapabilityRegistry modelRegistry
        +OPAClient opaClient
        +WeightConfig weights
        +scoreModel(model, intent) Float
        +filterByPolicy(models) List~ModelCapability~
        +selectWithFailover(candidates) ModelCapability
        +execute(state) ExecutionState
    }

    class ResponseBuilder {
        +CitationGenerator citationGenerator
        +ExecutionSummarizer summarizer
        +assembleResponse(state) FinalResponse
        +attachCitations(context, docs) String
        +generateSummary(state) ExecutionSummary
        +execute(state) ExecutionState
    }

    BaseAgent <|-- SupervisorAgent
    BaseAgent <|-- IntentDetectionAgent
    BaseAgent <|-- ContextPlanningAgent
    BaseAgent <|-- RetrievalAgent
    BaseAgent <|-- KnowledgeGraphAgent
    BaseAgent <|-- RankingAgent
    BaseAgent <|-- CompressionAgent
    BaseAgent <|-- GovernanceAgent
    BaseAgent <|-- DynamicModelRouter
    BaseAgent <|-- ResponseBuilder

    SupervisorAgent "1" *-- "1" IntentDetectionAgent : orchestrates
    SupervisorAgent "1" *-- "1" ContextPlanningAgent : orchestrates
    SupervisorAgent "1" *-- "1" RetrievalAgent : orchestrates
    SupervisorAgent "1" *-- "1" KnowledgeGraphAgent : orchestrates
    SupervisorAgent "1" *-- "1" RankingAgent : orchestrates
    SupervisorAgent "1" *-- "1" CompressionAgent : orchestrates
    SupervisorAgent "1" *-- "1" GovernanceAgent : orchestrates
    SupervisorAgent "1" *-- "1" DynamicModelRouter : orchestrates
    SupervisorAgent "1" *-- "1" ResponseBuilder : orchestrates
```

---

## DM-007 — Connector Class Hierarchy

```mermaid
classDiagram
    class BaseConnector {
        <<abstract>>
        +String connectorId
        +String connectorType
        +AuthConfig authConfig
        +ConnectorStatus status
        +DateTime lastSync
        +authenticate()
        +discover() ConnectorMetadata
        +search(query, filters) List~Document~
        +fetch(resourceId) Document
        +sync() SyncResult
        +health() HealthStatus
        +metadata() ConnectorMetadata
    }

    class GitHubConnector {
        +String organization
        +List~String~ repositories
        +String branch
        +searchCode(query) List~CodeSnippet~
        +getCommitHistory(repo, since) List~Commit~
        +getPullRequests(repo, state) List~PR~
        +getWorkflowRuns(repo) List~WorkflowRun~
    }

    class ConfluenceConnector {
        +String spaceKey
        +String baseUrl
        +searchPages(query) List~Page~
        +getPage(pageId) Page
        +getChildPages(pageId) List~Page~
        +searchLabels(label) List~Page~
    }

    class JiraConnector {
        +String projectKey
        +String baseUrl
        +searchIssues(jql) List~Issue~
        +getIssue(issueKey) Issue
        +getLinkedIssues(issueKey) List~Issue~
        +getSprintIssues(sprintId) List~Issue~
    }

    class GrafanaConnector {
        +String grafanaUrl
        +String datasourceUid
        +queryLogs(logqlExpr, range) List~LogLine~
        +queryMetrics(promqlExpr, range) MetricResult
        +getAlerts(state) List~Alert~
        +getDashboards() List~Dashboard~
    }

    class SlackConnector {
        +String workspaceId
        +List~String~ channels
        +searchMessages(query) List~Message~
        +getThreadReplies(ts) List~Message~
        +getChannelHistory(channel, since) List~Message~
    }

    class RESTApiConnector {
        +String baseUrl
        +String openApiSpec
        +Map~String, String~ headers
        +invokeEndpoint(method, path, body) Response
        +discoverEndpoints() List~Endpoint~
    }

    class ConnectorRegistry {
        +Map~String, BaseConnector~ connectors
        +register(connector)
        +deregister(connectorId)
        +getConnector(connectorId) BaseConnector
        +listHealthy() List~BaseConnector~
        +checkAllHealth()
    }

    BaseConnector <|-- GitHubConnector
    BaseConnector <|-- ConfluenceConnector
    BaseConnector <|-- JiraConnector
    BaseConnector <|-- GrafanaConnector
    BaseConnector <|-- SlackConnector
    BaseConnector <|-- RESTApiConnector

    ConnectorRegistry "1" *-- "many" BaseConnector : manages
```

---

## DM-008 — Relational Data Model (PostgreSQL ERD)

```mermaid
erDiagram

    ORGANIZATIONS {
        uuid id PK
        string name
        string subscription_tier
        datetime created_at
        datetime updated_at
    }

    PROJECTS {
        uuid id PK
        uuid organization_id FK
        string name
        string description
        datetime created_at
    }

    USERS {
        uuid id PK
        uuid organization_id FK
        string name
        string email
        string role
        string status
        datetime created_at
        datetime updated_at
    }

    TEAM_MEMBERSHIPS {
        uuid id PK
        uuid user_id FK
        string team_name
        string department
    }

    CONNECTORS {
        uuid id PK
        uuid project_id FK
        string type
        string name
        string status
        jsonb configuration
        string auth_type
        datetime last_sync
        datetime created_at
        datetime updated_at
    }

    KNOWLEDGE_SOURCES {
        uuid id PK
        uuid connector_id FK
        string name
        string source_path
        string priority
        string indexing_strategy
        int refresh_interval_minutes
        datetime last_indexed
        datetime created_at
    }

    POLICIES {
        uuid id PK
        uuid organization_id FK
        string name
        string version
        string status
        text rego_policy
        string policy_type
        datetime created_at
        datetime updated_at
        uuid created_by FK
    }

    MODELS {
        uuid id PK
        uuid organization_id FK
        string provider
        string model_id
        int coding_score
        int reasoning_score
        int context_window
        decimal cost_per_1k_tokens
        int avg_latency_ms
        boolean vision_support
        boolean function_calling_support
        boolean on_prem_support
        string health_status
        boolean is_default
        datetime updated_at
    }

    PROMPT_TEMPLATES {
        uuid id PK
        uuid organization_id FK
        string name
        string version
        text template_content
        string intent_type
        datetime created_at
        uuid created_by FK
    }

    EXECUTIONS {
        uuid execution_id PK
        uuid session_id
        uuid user_id FK
        uuid organization_id FK
        string intent
        string intent_domain
        string complexity
        float confidence
        string selected_model
        int token_in
        int token_out
        float compression_ratio
        int latency_ms
        decimal cost_usd
        string status
        string assistant_type
        datetime created_at
    }

    EXECUTION_CONNECTOR_USAGE {
        uuid id PK
        uuid execution_id FK
        string connector_type
        int documents_retrieved
        int latency_ms
        string status
    }

    AUDIT_LOGS {
        uuid id PK
        datetime timestamp
        uuid user_id FK
        uuid session_id
        uuid execution_id FK
        string trace_id
        string action
        string resource
        string result
        string ip_address
        string user_agent
        jsonb additional_context
    }

    ORGANIZATIONS ||--o{ PROJECTS : "has"
    ORGANIZATIONS ||--o{ USERS : "has"
    ORGANIZATIONS ||--o{ POLICIES : "owns"
    ORGANIZATIONS ||--o{ MODELS : "registers"
    ORGANIZATIONS ||--o{ PROMPT_TEMPLATES : "owns"
    ORGANIZATIONS ||--o{ EXECUTIONS : "generates"

    PROJECTS ||--o{ CONNECTORS : "configures"
    CONNECTORS ||--o{ KNOWLEDGE_SOURCES : "indexes"

    USERS ||--o{ TEAM_MEMBERSHIPS : "belongs to"
    USERS ||--o{ EXECUTIONS : "initiates"
    USERS ||--o{ AUDIT_LOGS : "generates"
    USERS ||--o{ POLICIES : "authors"

    EXECUTIONS ||--o{ EXECUTION_CONNECTOR_USAGE : "uses"
    EXECUTIONS ||--o{ AUDIT_LOGS : "logged in"
```

---

## DM-009 — Knowledge Graph Schema (Neo4j)

```mermaid
erDiagram

    SERVICE {
        string id PK
        string name
        string language
        string repository_url
        string team
        string status
        datetime last_updated
    }

    REPOSITORY {
        string id PK
        string name
        string url
        string default_branch
        string language
        string connector_id
        datetime last_synced
    }

    DEVELOPER {
        string id PK
        string username
        string email
        string team
        string department
    }

    TEAM {
        string id PK
        string name
        string department
        string slack_channel
    }

    API {
        string id PK
        string name
        string endpoint
        string method
        string protocol
        string version
        string service_id
    }

    DATABASE_INSTANCE {
        string id PK
        string name
        string type
        string host
        string environment
    }

    INCIDENT {
        string id PK
        string title
        string severity
        string status
        datetime occurred_at
        datetime resolved_at
        string jira_key
    }

    DEPLOYMENT {
        string id PK
        string service_id
        string version
        string environment
        string status
        datetime deployed_at
        string deployed_by
    }

    WIKI_PAGE {
        string id PK
        string title
        string space_key
        string url
        datetime last_updated
        string author
    }

    ARCHITECTURE_DOC {
        string id PK
        string title
        string doc_type
        string url
        string service_id
        datetime last_updated
    }

    BUSINESS_CAPABILITY {
        string id PK
        string name
        string domain
        string description
    }

    SERVICE ||--o{ API : "EXPOSES"
    SERVICE ||--o{ DATABASE_INSTANCE : "USES"
    SERVICE ||--o{ ARCHITECTURE_DOC : "DOCUMENTED_BY"
    SERVICE ||--o{ BUSINESS_CAPABILITY : "IMPLEMENTS"
    SERVICE ||--o{ INCIDENT : "RELATED_TO"
    SERVICE ||--o{ DEPLOYMENT : "HAS"
    SERVICE ||--o{ SERVICE : "DEPENDS_ON"

    REPOSITORY ||--|| SERVICE : "IMPLEMENTS"
    DEVELOPER ||--o{ REPOSITORY : "OWNS"
    DEVELOPER ||--o{ INCIDENT : "ASSIGNED_TO"
    DEVELOPER ||--|{ TEAM : "MEMBER_OF"

    TEAM ||--o{ SERVICE : "OWNS"
    TEAM ||--o{ BUSINESS_CAPABILITY : "RESPONSIBLE_FOR"

    DEPLOYMENT ||--o{ INCIDENT : "TRIGGERED"
    WIKI_PAGE ||--o{ SERVICE : "DOCUMENTS"
    WIKI_PAGE ||--o{ INCIDENT : "REFERENCES"

    API ||--o{ SERVICE : "CALLED_BY"
```

---

## DM-010 — Context Request Lifecycle (Data Flow)

```mermaid
flowchart TD
    A(["AI Coding Assistant\n(Cursor / Copilot / Claude Code)"])
    B["Enterprise MCP Gateway\nFastMCP"]
    C{"JWT Valid\n& OPA ALLOW?"}
    D["403 Forbidden"]
    E["Supervisor Agent\nInitialize ExecutionState"]

    F["Intent Detection Agent\nClassify intent, domain, complexity"]
    G{"Confidence\n≥ 0.80?"}
    H["Clarification Step\n(return ambiguity signal)"]

    I["Context Planning Agent\nSelect connectors, allocate token budget"]

    J{"Context Store\nCache HIT?"}
    K["Skip Retrieval\n(use cached context)"]
    L["Retrieval Agent\nParallel connector calls"]

    M["Knowledge Graph Agent\nNeo4j entity traversal (2 hops)"]
    N["Ranking Agent\nHybrid RRF scoring\n(vector 0.7 + BM25 0.3)"]
    O["AI Compression Agent\nRule-Based → Semantic → LLM Summarize"]
    P["Store compressed context\nin Redis (TTL: 15 min)"]

    Q["Governance Agent\nPII detect → Secret mask → OPA evaluate"]
    R{"OPA ALLOW\nall chunks?"}
    S["Remove DENY chunks\nEmit governance.violated event"]

    T["Dynamic Model Router\nScore models → Policy filter → Select"]
    U["Response Builder\nMerge context + citations + metrics"]
    V["LiteLLM AI Gateway\nForward to selected LLM provider"]
    W["LLM Provider\n(OpenAI / Anthropic / Gemini / Ollama)"]
    X["Persist ExecutionTrace\n(PostgreSQL + MinIO snapshot)"]
    Y(["AI Assistant\nStreamed MCP response"])

    A -->|"MCP Tool Invocation"| B
    B --> C
    C -->|"DENY"| D
    C -->|"ALLOW"| E
    E --> F
    F --> G
    G -->|"< 0.80"| H
    H -->|"Re-submit"| F
    G -->|"≥ 0.80"| I
    I --> J
    J -->|"HIT"| K
    K --> Q
    J -->|"MISS"| L
    L --> M
    M --> N
    N --> O
    O --> P
    P --> Q
    Q --> R
    R -->|"Partial DENY"| S
    S --> T
    R -->|"Full ALLOW"| T
    T --> U
    U --> V
    V --> W
    W -->|"LLM response"| U
    U --> X
    X --> Y
```

---

## DM-011 — Connector Synchronization Flow (Data Flow)

```mermaid
flowchart TD
    A["Connector Scheduler\n(Cron / Temporal)"]
    B["Publish connector.sync event\n→ Kafka"]
    C["Connector Pod\n(per connector type)"]
    D{"Connector\nHealthy?"}
    E["Emit: connector.health.failed\nAlert → Slack/Email"]
    F["Authenticate\n(OAuth2 / API Key / PAT)"]
    G["Discover metadata\n(repos, spaces, projects)"]
    H["Fetch incremental updates\n(since last_sync timestamp)"]
    I["Normalize documents\n(title, content, metadata, source)"]
    J["Generate embeddings\n(configurable embedding model)"]
    K["Upsert vectors\n→ Qdrant collection"]
    L["Index documents\n→ OpenSearch"]
    M["Extract entities\n(services, APIs, developers, incidents)"]
    N["Update Knowledge Graph\n→ Neo4j (incremental node/edge upsert)"]
    O["Update last_sync\n→ PostgreSQL connectors table"]
    P["Emit connector.sync.completed\n→ Kafka"]
    Q["Observability Stack\n(Prometheus counter update)"]

    A -->|"Schedule trigger"| B
    B --> C
    C --> D
    D -->|"Unhealthy"| E
    D -->|"Healthy"| F
    F --> G
    G --> H
    H --> I
    I --> J
    J --> K
    I --> L
    I --> M
    M --> N
    K --> O
    L --> O
    N --> O
    O --> P
    P --> Q
```

---

## DM-012 — Polyglot Persistence Data Flow

```mermaid
flowchart LR
    subgraph Write_Path["Write Path (AI Request)"]
        WA["Agent Pipeline"]
        WB["ExecutionTrace\n→ PostgreSQL"]
        WC["AgentSnapshots\n→ MinIO (JSON.gz)"]
        WD["DomainEvents\n→ Kafka topics"]
        WE["ContextCache\n→ Redis (TTL 15m)"]
        WF["SessionState\n→ Redis (TTL session)"]
    end

    subgraph Read_Path["Read Path (Context Retrieval)"]
        RA["Retrieval Agent"]
        RB["Semantic Search\n← Qdrant (ANN kNN)"]
        RC["Keyword Search\n← OpenSearch (BM25)"]
        RD["Graph Traversal\n← Neo4j (Cypher)"]
        RE["Cache Lookup\n← Redis"]
        RF["Config / Policy\n← PostgreSQL"]
    end

    subgraph Indexing_Path["Indexing Path (Connector Sync)"]
        IA["Connector Pod"]
        IB["Embeddings\n→ Qdrant"]
        IC["Full-text Index\n→ OpenSearch"]
        ID["Graph Nodes/Edges\n→ Neo4j"]
        IE["Sync Metadata\n→ PostgreSQL"]
    end

    WA --> WB
    WA --> WC
    WA --> WD
    WA --> WE
    WA --> WF

    RA --> RE
    RA --> RB
    RA --> RC
    RA --> RD
    RA --> RF

    IA --> IB
    IA --> IC
    IA --> ID
    IA --> IE
```

---

## DM-013 — End-to-End AI Request (Sequence)

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant AI as AI Assistant
    participant GW as MCP Gateway
    participant KC as Keycloak
    participant OPA as OPA
    participant SA as Supervisor Agent
    participant ID as Intent Agent
    participant CP as Planning Agent
    participant RA as Retrieval Agent
    participant CF as Connector Framework
    participant KG as Graph Agent
    participant RK as Ranking Agent
    participant CM as Compression Agent
    participant GA as Governance Agent
    participant MR as Model Router
    participant RB as Response Builder
    participant LLM as LiteLLM Gateway
    participant PG as PostgreSQL

    Dev->>AI: Submit prompt
    AI->>GW: tools/call — search_code(query)
    GW->>KC: Validate JWT
    KC-->>GW: Claims: userId, role, org
    GW->>OPA: Check access policy
    OPA-->>GW: ALLOW
    GW->>SA: Initialize ExecutionState(executionId, user, session)
    SA->>ID: detect_intent(prompt)
    ID-->>SA: {intent: CodeSearch, confidence: 0.97, complexity: Medium}
    SA->>CP: plan_context(intent)
    CP-->>SA: {connectors: [github, confluence], tokenBudget: 2000, parallelism: true}

    SA->>RA: retrieve_context(plan) [async parallel]
    par GitHub Connector
        RA->>CF: search_code(query)
        CF-->>RA: code snippets + metadata
    and Confluence Connector
        RA->>CF: search_documentation(query)
        CF-->>RA: doc pages + metadata
    end

    SA->>KG: expand_graph(documents)
    KG-->>SA: graph-enriched context (owner, dependencies, related incidents)
    SA->>RK: rank_context(documents)
    RK-->>SA: top-8 ranked documents (RRF score > 0.7)
    SA->>CM: compress_context(documents, budget=2000)
    CM-->>SA: {compressedContext: "...", originalTokens: 18400, compressedTokens: 820, ratio: 0.955}
    SA->>GA: apply_governance(context, user)
    GA->>OPA: Evaluate context access policies
    OPA-->>GA: ALLOW (no violations)
    GA-->>SA: governed context (masking applied to 2 secrets)
    SA->>MR: route_model(intent, complexity, tokens)
    MR-->>SA: {selectedModel: "openai/gpt-4o", rationale: "coding + medium complexity"}
    SA->>RB: build_response(state)
    RB->>LLM: Complete(model=gpt-4o, context=governed)
    LLM-->>RB: AI response text
    RB-->>SA: {response, citations, metrics, executionSummary}
    SA->>PG: Persist ExecutionTrace (immutable)
    SA-->>GW: Final context package
    GW-->>AI: Streamed MCP response
    AI-->>Dev: Enriched AI response with citations
```

---

## DM-014 — Governance Agent Processing (Sequence)

```mermaid
sequenceDiagram
    autonumber
    participant SA as Supervisor Agent
    participant GA as Governance Agent
    participant CC as Context Classifier
    participant PII as PII Detector
    participant SD as Secret Detector
    participant DM as Data Masker
    participant RV as Role Validator
    participant OPA as Open Policy Agent
    participant KF as Kafka

    SA->>GA: apply_governance(rankedContext, executionState)
    GA->>CC: classify_context(chunks)
    CC-->>GA: sensitivity levels [PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED]

    GA->>PII: detect_pii(chunks)
    PII-->>GA: [{field: "email", value: "dev@corp.com", chunk: 3}]

    GA->>SD: detect_secrets(chunks)
    SD-->>GA: [{type: "AWS_KEY", value: "AKIA...", chunk: 5}]

    GA->>DM: mask_sensitive(chunks, piiFindings, secretFindings)
    DM-->>GA: masked chunks [{chunk: 3, masked: "dev@***.***, chunk: 5, masked: "AKIA***"}]

    GA->>RV: validate_role(userId, requiredPermissions)
    RV-->>GA: ALLOWED (role: Developer → permission: read:code, read:docs)

    GA->>OPA: evaluate({user, context_sensitivity, connectors, org})
    OPA-->>GA: [{chunk: 7, decision: DENY, policy: "restricted-arch-docs"}, {remaining: ALLOW}]

    alt Policy violation found
        GA->>GA: remove DENY chunks from context
        GA->>KF: publish governance.events (governance.violated)
        note over KF: Alert Engine consumes → triggers notification
    end

    GA-->>SA: {governedContext, maskingActions, policyResults, governanceMetadata}
```

---

## DM-015 — Dynamic Model Routing (Sequence)

```mermaid
sequenceDiagram
    autonumber
    participant SA as Supervisor Agent
    participant MR as Dynamic Model Router
    participant OPA as Open Policy Agent
    participant MCR as Model Capability Registry
    participant HC as Health Checker
    participant LLM as LiteLLM Gateway
    participant KF as Kafka

    SA->>MR: route_model(intent, complexity, tokens, userPreference, orgId)

    MR->>OPA: evaluate_model_policies({orgId, department, intent})
    OPA-->>MR: [{modelId: "anthropic/*", decision: DENY, policy: "no-external-llm"}, {modelId: "openai/*", decision: ALLOW}]

    MR->>MCR: get_eligible_models(filter=ALLOW_list)
    MCR-->>MR: [gpt-4o, gpt-4o-mini, gpt-4.1, ollama/qwen3]

    MR->>HC: check_health([gpt-4o, gpt-4o-mini, gpt-4.1, ollama/qwen3])
    HC-->>MR: {gpt-4o: HEALTHY, gpt-4o-mini: HEALTHY, gpt-4.1: DEGRADED, ollama/qwen3: HEALTHY}

    MR->>MR: score_models(eligibleHealthy, intent=CodeSearch, complexity=Medium, weights={coding:0.4, reasoning:0.3, cost:0.2, latency:0.1})
    note over MR: gpt-4o: 87.3, gpt-4o-mini: 79.1, ollama/qwen3: 72.4

    MR->>MR: select top-scored: gpt-4o

    alt User specified model
        MR->>OPA: validate_user_model_choice(userId, "openai/gpt-4o")
        OPA-->>MR: ALLOW
    end

    MR->>KF: publish model.events {selectedModel, evaluatedModels, rationale}
    MR-->>SA: {selectedModel: "openai/gpt-4o", selectionRationale, policyConstraints, fallbackChain}

    SA->>LLM: complete(model="openai/gpt-4o", messages, stream=true)
    LLM-->>SA: streamed response tokens

    note over LLM: If gpt-4o fails → LiteLLM auto-retries → gpt-4o-mini (fallback)
```

---

## DM-016 — Administrator Connector Configuration (Sequence)

```mermaid
sequenceDiagram
    autonumber
    actor Admin as Enterprise Administrator
    participant Portal as Admin Portal UI
    participant API as Portal API
    participant CM as Connector Manager
    participant CP as Connector Plugin
    participant KC as Keycloak
    participant PG as PostgreSQL
    participant KF as Kafka
    participant AL as Audit Log

    Admin->>Portal: Navigate → Connector Management → Add Connector
    Portal->>API: POST /api/v1/connectors {type: "github", name, config}
    API->>KC: Validate admin JWT (role: Administrator)
    KC-->>API: ALLOW

    API->>CP: test_connectivity(config)
    CP->>CP: authenticate(config.authConfig)
    CP-->>API: {status: HEALTHY, metadata: {repos: 42, lastCommit: "2026-07-09"}}

    alt Connectivity FAILED
        API-->>Portal: 422 {error: "CTX-CON-001", message: "Authentication failed"}
        Portal-->>Admin: Show error with diagnostic details
    else Connectivity OK
        API->>PG: INSERT INTO connectors {id, project_id, type, status: ACTIVE, configuration, created_at}
        API->>CM: register_connector(connectorId, config)
        CM->>KF: publish connector.sync {connectorId, trigger: INITIAL}
        API->>AL: INSERT INTO audit_logs {action: "connector.created", resource: connectorId, userId}
        API-->>Portal: 201 {connectorId, status: ACTIVE}
        Portal-->>Admin: Show success toast + connector card
    end

    note over KF: connector.sync event triggers first full synchronization
```

---

## DM-017 — AI Request Execution State Machine

```mermaid
stateDiagram-v2
    [*] --> RECEIVED : MCP Tool Invocation

    RECEIVED --> AUTHENTICATING : JWT received
    AUTHENTICATING --> REJECTED : JWT invalid / OPA DENY
    AUTHENTICATING --> PLANNING : Auth ALLOW

    PLANNING --> INTENT_DETECTING : State initialized
    INTENT_DETECTING --> CLARIFYING : Confidence < 0.80
    CLARIFYING --> INTENT_DETECTING : Re-submitted
    INTENT_DETECTING --> CONTEXT_PLANNING : Confidence ≥ 0.80

    CONTEXT_PLANNING --> CACHE_CHECK : Plan generated
    CACHE_CHECK --> RETRIEVING : Cache MISS
    CACHE_CHECK --> GOVERNING : Cache HIT

    RETRIEVING --> GRAPH_EXPANDING : Documents retrieved
    GRAPH_EXPANDING --> RANKING : Graph enriched
    RANKING --> COMPRESSING : Context ranked
    COMPRESSING --> CACHING : Context compressed
    CACHING --> GOVERNING : Cached in Redis

    GOVERNING --> ROUTING : Governance ALLOW
    GOVERNING --> PARTIALLY_GOVERNED : Some chunks DENY
    PARTIALLY_GOVERNED --> ROUTING : DENY chunks removed

    ROUTING --> BUILDING : Model selected
    BUILDING --> INFERRING : Response assembled
    INFERRING --> COMPLETING : LLM response received
    COMPLETING --> PERSISTING : Execution trace written

    PERSISTING --> COMPLETED : Trace persisted

    REJECTED --> [*]
    COMPLETED --> [*]

    RETRIEVING --> DEGRADED : Connector timeout (partial results)
    DEGRADED --> RANKING : Partial context available
    INFERRING --> FAILING : LLM unavailable + failover exhausted
    FAILING --> [*]

    note right of COMPLETED
        ExecutionTrace persisted
        immutably in PostgreSQL.
        Replay available immediately.
    end note

    note right of GOVERNING
        PII masked, secrets redacted,
        OPA policies evaluated.
        Audit metadata recorded.
    end note
```

---

## DM-018 — Connector Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> REGISTERED : Administrator registers connector

    REGISTERED --> AUTHENTICATING : Connectivity test triggered
    AUTHENTICATING --> AUTH_FAILED : Credentials invalid
    AUTH_FAILED --> AUTHENTICATING : Credentials updated + retry

    AUTHENTICATING --> DISCOVERING : Authentication OK
    DISCOVERING --> HEALTH_CHECKING : Metadata discovered
    HEALTH_CHECKING --> UNHEALTHY : Health probe failed
    UNHEALTHY --> HEALTH_CHECKING : Retry after backoff
    UNHEALTHY --> DISABLED : Max retries exceeded

    HEALTH_CHECKING --> SYNCING : Health OK + sync triggered
    SYNCING --> INDEXING : Data fetched + normalized
    INDEXING --> READY : Embeddings generated + indexed

    READY --> SYNCING : Scheduled sync trigger
    READY --> HEALTH_CHECKING : Periodic health probe

    READY --> DEGRADED : Partial sync failure (some repos failed)
    DEGRADED --> SYNCING : Next sync cycle

    DISABLED --> AUTHENTICATING : Administrator re-enables

    note right of READY
        Connector available for
        selection by Context
        Planning Agent.
    end note

    note right of SYNCING
        Parallel fetch from all
        configured source paths.
        Incremental since last_sync.
    end note
```

---

## DM-019 — Kubernetes Deployment Topology

```mermaid
graph TB
    subgraph Internet["Internet / Enterprise Network"]
        Client["AI Coding Assistants\n+ Admin Portal Users"]
    end

    subgraph Ingress_Layer["Ingress Layer"]
        NGINX["NGINX Ingress Controller\nTLS 1.3 Termination\nLoadBalancer Service"]
    end

    subgraph contextiq_system["namespace: contextiq-system"]
        GW["MCP Gateway\nDeployment (HPA)\nreplicas: 2–10"]
        SA["Supervisor Agent\nDeployment (HPA)\nreplicas: 2–8"]
        AGT["Agent Services\nDeployment (HPA)\nreplicas: 2–6 each"]
    end

    subgraph contextiq_platform["namespace: contextiq-platform"]
        PORTAL["Admin Portal\nDeployment (HPA)\nreplicas: 2–4"]
        CONN_MGR["Connector Manager\nDeployment\nreplicas: 2"]
        POLICY_MGR["Policy Manager\nDeployment\nreplicas: 2"]
    end

    subgraph contextiq_connectors["namespace: contextiq-connectors"]
        GH_CONN["GitHub Connector\nDeployment\nreplicas: 1–3"]
        CF_CONN["Confluence Connector\nDeployment\nreplicas: 1–3"]
        JR_CONN["Jira Connector\nDeployment\nreplicas: 1–3"]
        GF_CONN["Grafana Connector\nDeployment\nreplicas: 1–3"]
    end

    subgraph contextiq_security["namespace: contextiq-security"]
        KEYCLOAK["Keycloak\nDeployment (HPA)\nreplicas: 2–4"]
        VAULT["HashiCorp Vault\nStatefulSet HA Raft\nreplicas: 3"]
        OPA_SVC["Open Policy Agent\nDeployment\nreplicas: 2"]
    end

    subgraph contextiq_databases["namespace: contextiq-databases"]
        PG_SS["PostgreSQL\nStatefulSet\nreplicas: 1 primary + 2 read"]
        NEO_SS["Neo4j\nStatefulSet\nCausal Cluster: 3"]
        QD_SS["Qdrant\nStatefulSet\nDistributed: 3"]
        OS_SS["OpenSearch\nStatefulSet\n3 nodes"]
        RD_SS["Redis Sentinel\nStatefulSet\n1 primary + 2 replicas"]
    end

    subgraph contextiq_storage["namespace: contextiq-storage"]
        MINIO_SS["MinIO\nStatefulSet\nDistributed: 4 nodes"]
        KAFKA_SS["Apache Kafka\nStatefulSet KRaft\n3 brokers"]
    end

    subgraph contextiq_observability["namespace: contextiq-observability"]
        PROM["Prometheus\nStatefulSet"]
        GRAFANA["Grafana\nDeployment"]
        LOKI["Loki\nStatefulSet"]
        JAEGER["Jaeger\nDeployment"]
        LANGFUSE["Langfuse\nDeployment"]
    end

    Client -->|"HTTPS / WSS"| NGINX
    NGINX --> GW
    NGINX --> PORTAL
    GW --> KEYCLOAK
    GW --> OPA_SVC
    GW --> SA
    SA --> AGT
    AGT --> GH_CONN
    AGT --> CF_CONN
    AGT --> JR_CONN
    AGT --> GF_CONN
    AGT --> PG_SS
    AGT --> NEO_SS
    AGT --> QD_SS
    AGT --> OS_SS
    AGT --> RD_SS
    AGT --> KAFKA_SS
    AGT --> VAULT
    AGT --> OPA_SVC
    PORTAL --> CONN_MGR
    PORTAL --> POLICY_MGR
    CONN_MGR --> PG_SS
    POLICY_MGR --> OPA_SVC
    KAFKA_SS --> MINIO_SS
    KAFKA_SS --> contextiq_observability
    AGT --> LANGFUSE
    GW --> PROM
    SA --> PROM
```

---

*End of UML Design Models*
