# Langfuse Integration Guide

This document explains how to use Langfuse tracing in ContextIQ following best practices from the Langfuse skill.

## Overview

Langfuse is integrated into ContextIQ to provide comprehensive LLM observability with:

- **Automatic LiteLLM tracing** - All LLM calls through LiteLLM are automatically traced
- **Function-level observability** - Use `@observe_llm` decorator to trace any function
- **Trace hierarchy** - Nested spans show which step is slow or failing
- **Rich metadata** - Session IDs, user IDs, tags, and custom metadata
- **Agent graph visualization** - Multi-agent systems visualized in Langfuse
- **Cost tracking** - Automatic token usage and cost calculation

## Configuration

### Environment Variables

Set these in your `.env` file:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com  # or self-hosted URL
LANGFUSE_ENABLED=true
```

API keys are found in your Langfuse project: **Settings > API Keys**

### Initialization

Langfuse is automatically initialized in `src/main.py`:

```python
from src.observability.langfuse_integration import setup_langfuse, teardown_langfuse

# Startup
setup_langfuse()  # Initialize Langfuse SDK

# Shutdown
teardown_langfuse()  # Flush all pending traces
```

## Usage

### 1. Automatic LiteLLM Tracing

All LLM calls through `LiteLLMInvoker` are automatically traced:

```python
from src.model_invoker import LiteLLMInvoker

invoker = LiteLLMInvoker()
response = await invoker.invoke(
    model_id="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}],
    token_budget=1000,
)
# Automatically traced to Langfuse with:
# - Model name
# - Token usage (input/output)
# - Cost calculation
# - Latency
```

### 2. Function-Level Tracing

Use `@observe_llm` decorator to trace any function:

```python
from src.observability.langfuse_integration import observe_llm, update_current_trace

@observe_llm(as_type="span", name="context-retrieval")
async def retrieve_context(query: str, user_id: str, session_id: str) -> Context:
    """
    Retrieves context from enterprise sources.
    Traced as a span in Langfuse.
    """
    # Update trace with metadata
    update_current_trace(
        session_id=session_id,
        user_id=user_id,
        tags=["retrieval", "production"],
        metadata={"query_length": len(query)}
    )
    
    # ... retrieval logic ...
    return context
```

### 3. Observation Types (Best Practices)

Use the correct `as_type` parameter:

#### Generation (LLM Calls)
```python
@observe_llm(as_type="generation", name="summarize-context")
async def summarize_context(context: str) -> str:
    """LLM generation - use for any LLM invocation"""
    response = await llm.invoke(...)
    return response
```

#### Agent (Subagent Execution)
```python
@observe_llm(as_type="agent", name="compression-agent")
async def compress_context(context: str) -> str:
    """
    Subagent execution.
    Shows as a node in the Agent Graph.
    """
    # Agent logic here
    return compressed
```

#### Retriever (Context Lookup)
```python
@observe_llm(as_type="retriever", name="github-retriever")
async def fetch_from_github(repo: str, query: str) -> list[Document]:
    """
    Context retrieval operation.
    Enables retrieval-specific analytics.
    """
    return documents
```

#### Span (Multi-step Operations)
```python
@observe_llm(as_type="span", name="orchestrate-request")
async def handle_request(request: Request) -> Response:
    """
    Multi-step workflow.
    Use for orchestration logic.
    """
    context = await retrieve_context(...)  # Nested span
    summary = await summarize_context(...)  # Nested generation
    return Response(summary)
```

### 4. Adding Metadata

#### Trace-Level Metadata
```python
from src.observability.langfuse_integration import update_current_trace

@observe_llm(as_type="span")
async def handle_chat_request(request: ChatRequest):
    # Add metadata at trace level
    update_current_trace(
        session_id=request.session_id,  # Groups conversations
        user_id=request.user_id,        # Filter by user
        tags=["chat", "production"],    # Categorization
        metadata={
            "intent": request.intent,
            "model_preference": request.model,
            "team_id": request.team_id,
        }
    )
```

#### Observation-Level Metadata
```python
from src.observability.langfuse_integration import update_current_observation

@observe_llm(as_type="generation")
async def invoke_model(api_key: str, user_message: str):
    # Only capture user message, not API key
    update_current_observation(
        input={"message": user_message},
        metadata={"model_selected": "gpt-4o"}
    )
    
    response = await llm.invoke(...)
    
    update_current_observation(
        output={"response": response}
    )
    return response
```

### 5. Multi-Agent Systems

For nested agent executions:

```python
@observe_llm(as_type="agent", name="supervisor-agent")
async def supervisor(task: Task) -> Result:
    """Main orchestrator agent"""
    
    # Dispatch to retrieval agent (nested)
    context = await retrieval_agent(task.query)
    
    # Dispatch to compression agent (nested)
    compressed = await compression_agent(context)
    
    return Result(compressed)


@observe_llm(as_type="agent", name="retrieval-agent")
async def retrieval_agent(query: str) -> Context:
    """Retrieval subagent - shows as separate node in Agent Graph"""
    return await retrieve(query)


@observe_llm(as_type="agent", name="compression-agent")
async def compression_agent(context: Context) -> str:
    """Compression subagent - shows as separate node in Agent Graph"""
    return await compress(context)
```

## Best Practices

### 1. Session IDs for Conversations
```python
# Group multi-turn conversations
update_current_trace(session_id=conversation_id)
```

### 2. User IDs for Attribution
```python
# Filter traces by user, calculate per-user costs
update_current_trace(user_id=user.id)
```

### 3. Tags for Categorization
```python
# Tag by feature, environment, intent
update_current_trace(tags=["chat", "production", "code-generation"])
```

### 4. Masked Sensitive Data
```python
# Never log PII or secrets
@observe_llm(capture_input=False)  # Disable auto-capture
async def process_secret(api_key: str):
    # Manually set safe input
    update_current_observation(input={"message": "Processing request"})
```

### 5. Descriptive Names
```python
# Good: descriptive, filterable
@observe_llm(name="github-pr-retrieval")

# Bad: generic
@observe_llm(name="span-1")
```

### 6. Proper Nesting
```python
# Nest operations to show hierarchy
@observe_llm(as_type="span", name="handle-request")
async def handle_request():
    await retrieve_context()   # Nested
    await summarize()          # Nested
    await invoke_llm()         # Nested
```

## Common Mistakes to Avoid

### ❌ DON'T: Log sensitive data
```python
@observe_llm()
async def call_api(api_key: str, data: dict):
    # BAD: api_key will be logged
    return await client.call(api_key, data)
```

### ✅ DO: Mask sensitive input
```python
@observe_llm(capture_input=False)
async def call_api(api_key: str, data: dict):
    update_current_observation(input={"data_keys": list(data.keys())})
    return await client.call(api_key, data)
```

### ❌ DON'T: Use generic names
```python
@observe_llm(name="process")  # Too generic
```

### ✅ DO: Use descriptive names
```python
@observe_llm(name="context-compression")  # Clear intent
```

### ❌ DON'T: Forget to flush in scripts
```python
# Script without flush - traces never sent
from src.observability.langfuse_integration import get_langfuse

@observe_llm()
def process():
    ...

if __name__ == "__main__":
    process()
    # Missing: get_langfuse().flush()
```

### ✅ DO: Always flush before exit
```python
from src.observability.langfuse_integration import get_langfuse

@observe_llm()
def process():
    ...

if __name__ == "__main__":
    process()
    langfuse = get_langfuse()
    if langfuse:
        langfuse.flush()  # Ensure traces are sent
```

## Viewing Traces

After instrumentation, view traces in the Langfuse UI:

1. **Traces view**: Individual requests with full execution tree
2. **Sessions view**: Grouped conversations (when `session_id` added)
3. **Dashboard**: Filter by tags, users, models
4. **Scores**: Quality metrics and user feedback
5. **Agent Graph**: Visualize multi-agent execution flows

## Auditing Traces

After adding instrumentation, always verify traces:

```bash
# Fetch recent traces to verify
npx langfuse-cli api traces list --limit 5

# Check specific trace
npx langfuse-cli api traces get --id <trace-id>
```

Compare against best practices: https://langfuse.com/docs/observability/best-practices

## Further Reading

- [Langfuse Docs](https://langfuse.com/docs)
- [LiteLLM Integration](https://langfuse.com/docs/integrations/litellm)
- [Python SDK](https://langfuse.com/docs/sdk/python)
- [Best Practices](https://langfuse.com/docs/observability/best-practices)
