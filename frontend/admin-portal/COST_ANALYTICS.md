# LLM Cost Analytics Configuration Guide

## Overview

The LLM Cost Analytics feature tracks and visualizes AI spend across all models in the ContextIQ platform. This guide covers the complete setup and configuration.

## Architecture

### Backend Components

1. **Cost Recording** ([src/observability/cost/llm_metrics.py](../../src/observability/cost/llm_metrics.py))
   - Captures cost data immediately after each LLM response
   - Increments Prometheus metrics synchronously
   - Writes to Langfuse asynchronously (fire-and-forget)

2. **Cost Storage**
   - **Prometheus**: Real-time metrics for dashboards
     - `contextiq_llm_cost_usd_total` - Cumulative spend by model/team
     - `contextiq_llm_tokens_total` - Token usage (prompt/completion)
   - **Langfuse**: Historical analytics database
     - Stores detailed per-request records
     - Enables trend analysis and reporting

3. **Cost Analytics API** ([src/api/admin/routes/model_analytics.py](../../src/api/admin/routes/model_analytics.py))
   - Endpoint: `GET /v1/models/cost-analytics?days=30`
   - Returns per-model cost summaries with daily sparklines
   - Queries Langfuse for historical data

### Frontend Components

1. **Dashboard Integration** ([frontend/admin-portal/src/pages/DashboardPage.tsx](./src/pages/DashboardPage.tsx))
   - Shows 30-day spend trend chart
   - Displays total spend and token usage KPIs
   - Includes per-model cost breakdown panel

2. **Dedicated Cost Analytics Page** ([frontend/admin-portal/src/pages/analytics/CostAnalyticsPage.tsx](./src/pages/analytics/CostAnalyticsPage.tsx))
   - Time range selector (7/30/90 days)
   - Daily spend trend by model (stacked chart)
   - Model comparison charts (spend and tokens)
   - Detailed breakdown table

## Configuration

### 1. Langfuse Setup

The cost analytics feature requires Langfuse to be configured for historical data storage.

**Environment Variables** (add to `docker-compose.yml` or `.env`):

```bash
# Langfuse Configuration
LANGFUSE_PUBLIC_KEY=pk_lf_...
LANGFUSE_SECRET_KEY=sk_lf_...
LANGFUSE_HOST=https://cloud.langfuse.com  # or your self-hosted instance
```

**Data Retention**: Ensure Langfuse project retention is set to ≥ 6 months (as per AC-5 requirements).

### 2. API Configuration

The cost analytics API is automatically registered in [src/main.py](../../src/main.py):

```python
from src.api.admin.routes.model_analytics import router as model_analytics_router
# ...
app.include_router(model_analytics_router)
```

**No additional configuration needed** - the endpoint is available at startup.

### 3. Frontend Configuration

**Environment Variables** ([frontend/admin-portal/.env.example](./admin-portal/.env.example)):

```bash
# API Configuration
VITE_API_BASE_URL=/api
```

In development, the Vite proxy forwards `/api` to `http://localhost:8000` (configured in [vite.config.ts](./admin-portal/vite.config.ts)).

**Production**: Set `VITE_API_BASE_URL` to your actual API URL.

### 4. RBAC Permissions

Cost analytics access requires the `READ_COST_ANALYTICS` permission, which is granted to:

- **PLATFORM_ENGINEER**
- **MANAGER**
- **ADMIN**
- **AUDITOR**
- **DEVELOPER** (read-only access)
- **DEVOPS_SRE**

Configure roles in [src/auth/roles.py](../../src/auth/roles.py).

## Usage

### Dashboard View

1. Navigate to the **Dashboard** (/)
2. View the "30-Day LLM Spend Trend" chart
3. Scroll to the "Cost Analytics — Last 30 Days" panel for per-model breakdown

### Dedicated Cost Analytics Page

1. Click **Cost Analytics** in the sidebar navigation
2. Select time range: 7, 30, or 90 days
3. View charts:
   - Daily spend trend (multi-line chart)
   - Total spend by model (horizontal bar chart)
   - Token usage by model (horizontal bar chart)
   - Detailed breakdown table

### API Usage

**Get Cost Analytics:**

```bash
curl -H "Authorization: Bearer <jwt_token>" \
  "http://localhost:8000/v1/models/cost-analytics?days=30"
```

**Response:**

```json
[
  {
    "model_id": "gpt-4o",
    "total_cost_usd": 127.45,
    "total_tokens": 5200000,
    "daily_series": [
      { "date": "2026-07-01", "cost_usd": 4.23 },
      { "date": "2026-07-02", "cost_usd": 5.67 }
    ]
  }
]
```

## Troubleshooting

### No Cost Data Showing

1. **Check Langfuse Connection:**
   ```bash
   docker compose exec api python -c "
   from src.observability.cost.settings import LangfuseProjectSettings
   s = LangfuseProjectSettings()
   print('Public Key:', s.public_key[:10] + '...' if s.public_key else '(empty)')
   print('Host:', s.host)
   "
   ```

2. **Verify LLM Calls Are Being Made:**
   - Check Prometheus metrics: `http://localhost:9090/graph`
   - Query: `contextiq_llm_cost_usd_total`

3. **Check Langfuse Dashboard:**
   - Visit your Langfuse instance
   - Verify GENERATION observations are being recorded

### API Errors

**403 Forbidden:**
- Ensure your JWT token includes the `READ_COST_ANALYTICS` permission
- Check user role assignments in Keycloak

**Empty Response:**
- Langfuse may not be configured (returns empty array gracefully)
- Check API logs: `docker compose logs api | grep cost`

### Frontend Issues

**Charts Not Loading:**

1. Check browser console for API errors
2. Verify API proxy in `vite.config.ts`:
   ```bash
   curl -s http://localhost:3000/api/v1/models/cost-analytics?days=7
   ```

3. Check network tab - should see request to `/api/v1/models/cost-analytics`

## Grafana Dashboards

Cost metrics are exposed to Grafana via Prometheus:

**Metric Families:**
- `contextiq_llm_cost_usd_total` - Cumulative spend
- `contextiq_llm_tokens_total` - Token usage

**Labels:**
- `service` - Service name (contextiq-api)
- `model_id` - LLM model identifier
- `team_id` - Team/organization ID
- `tenant_id` - Tenant ID (multi-tenancy)
- `intent_type` - Request intent classification

**Example PromQL Queries:**

```promql
# Total spend by model (last 24h)
increase(contextiq_llm_cost_usd_total[24h])

# Token usage by intent type
sum by(intent_type) (contextiq_llm_tokens_total)

# Cost per team
sum by(team_id) (contextiq_llm_cost_usd_total)
```

## Cost Calculation

Costs are calculated using **LiteLLM's cost map**:

```python
cost = (prompt_tokens × input_rate + completion_tokens × output_rate) / 1M
```

**Pricing Table** ([src/observability/cost/llm_metrics.py](../../src/observability/cost/llm_metrics.py)):

| Model | Input (per 1M) | Output (per 1M) |
|-------|----------------|-----------------|
| claude-opus-4-7 | $15.00 | $75.00 |
| claude-sonnet-4-6 | $3.00 | $15.00 |
| gpt-4o | $5.00 | $15.00 |

Update the `_MODEL_PRICING` dict as provider pricing changes.

## Performance Considerations

- **Prometheus writes**: Synchronous, no I/O latency (~0.1ms)
- **Langfuse writes**: Async fire-and-forget, zero impact on request latency
- **API queries**: Cached for 5 minutes (`staleTime: 5 * 60 * 1000`)
- **Dashboard refresh**: Auto-refresh every 5 minutes via React Query

## Compliance & Retention

Per **AC-5** requirements:
- Historical cost data must be retained for **≥ 6 months**
- Configure Langfuse project retention accordingly
- Audit trail available via `model_audit_log` table

## Support

For issues or questions:
1. Check logs: `docker compose logs api | grep cost`
2. Review Langfuse dashboard for data ingestion
3. Verify Prometheus metrics are being collected
4. Contact platform engineering team
