# TASK-US039-05 — Kubernetes Admin Portal Deployment and Integration Tests

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US039-05 |
| User Story | US-039 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend / Infrastructure |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Provision the Kubernetes resources required to serve the React Admin Portal SPA in the cluster (AC-6): an nginx `Deployment` serving the Vite production build, a `Service`, a `ConfigMap` with the nginx configuration (SPA history-mode fallback), and an `Ingress` at `/admin`. Write integration tests covering all 7 US-039 acceptance criteria: React Testing Library tests for the frontend components and pytest + httpx for the backend routes.

## Implementation Details

**Technology (infra):** Kubernetes YAML, nginx 1.25-alpine

**Technology (tests):** React Testing Library, Vitest, pytest, httpx, respx, pytest-asyncio

**File locations:**
- `k8s/admin-portal/deployment.yaml`
- `k8s/admin-portal/service.yaml`
- `k8s/admin-portal/nginx-configmap.yaml`
- `k8s/admin-portal/ingress.yaml`
- `frontend/admin-portal/src/__tests__/ConnectorListPage.test.tsx`
- `frontend/admin-portal/src/__tests__/AddConnectorWizard.test.tsx`
- `frontend/admin-portal/src/__tests__/ConnectorToggle.test.tsx`
- `frontend/admin-portal/src/__tests__/TestConnectionButton.test.tsx`
- `tests/knowledge_sources/test_health_check_route.py`
- `tests/knowledge_sources/test_audit_log.py`

---

### nginx `ConfigMap` — SPA history-mode fallback

```yaml
# k8s/admin-portal/nginx-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: admin-portal-nginx-config
  namespace: contextiq
data:
  default.conf: |
    server {
      listen 80;
      root   /usr/share/nginx/html;
      index  index.html;

      # Security headers (OWASP)
      add_header X-Content-Type-Options  "nosniff"    always;
      add_header X-Frame-Options         "DENY"        always;
      add_header Referrer-Policy         "strict-origin-when-cross-origin" always;
      add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'" always;

      # SPA fallback — all routes served as index.html (React Router handles routing)
      location / {
        try_files $uri $uri/ /index.html;
      }

      # Cache static assets aggressively; HTML must not be cached
      location ~* \.(js|css|png|svg|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
      }

      # Health probe endpoint for readiness/liveness checks
      location /healthz {
        return 200 "ok";
        add_header Content-Type text/plain;
      }
    }
```

---

### `Deployment`

```yaml
# k8s/admin-portal/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: admin-portal
  namespace: contextiq
  labels:
    app: admin-portal
spec:
  replicas: 2
  selector:
    matchLabels:
      app: admin-portal
  template:
    metadata:
      labels:
        app: admin-portal
    spec:
      containers:
        - name: nginx
          image: nginx:1.25-alpine
          ports:
            - containerPort: 80
          volumeMounts:
            # Vite build artefacts — injected by CI as an initContainer or pre-built image
            - name: spa-dist
              mountPath: /usr/share/nginx/html
            - name: nginx-config
              mountPath: /etc/nginx/conf.d
              readOnly: true
          readinessProbe:
            httpGet:
              path: /healthz
              port: 80
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /healthz
              port: 80
            initialDelaySeconds: 10
            periodSeconds: 30
          resources:
            requests:
              cpu:    50m
              memory: 64Mi
            limits:
              cpu:    200m
              memory: 128Mi
          securityContext:
            readOnlyRootFilesystem: true
            runAsNonRoot:           true
            runAsUser:              101   # nginx user in alpine image
            allowPrivilegeEscalation: false
      volumes:
        - name: spa-dist
          # In production CI, replace with an initContainer that copies from a
          # build image or use a PVC seeded by the CI build job
          emptyDir: {}
        - name: nginx-config
          configMap:
            name: admin-portal-nginx-config
```

---

### `Service` and `Ingress`

```yaml
# k8s/admin-portal/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: admin-portal
  namespace: contextiq
spec:
  selector:
    app: admin-portal
  ports:
    - name: http
      port:       80
      targetPort: 80
  type: ClusterIP
---
# k8s/admin-portal/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: admin-portal
  namespace: contextiq
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
    - http:
        paths:
          - path:     /admin
            pathType: Prefix
            backend:
              service:
                name: admin-portal
                port:
                  number: 80
```

---

### Frontend integration tests

```tsx
// frontend/admin-portal/src/__tests__/ConnectorListPage.test.tsx
import { render, screen }      from "@testing-library/react";
import { server }              from "../../mocks/server";    // MSW service worker mock
import { http, HttpResponse }  from "msw";
import ConnectorListPage       from "../pages/connectors/ConnectorListPage";
import { TestWrapper }         from "../../test-utils/TestWrapper";

const MOCK_CONNECTORS = [
  { id: "a1b2", name: "GitHub Docs", connector_type: "github",
    status: "active", last_sync_at: new Date().toISOString(), document_count: 1234 },
  { id: "c3d4", name: "Confluence KB", connector_type: "confluence",
    status: "error",  last_sync_at: null, document_count: 0 },
];

describe("ConnectorListPage — AC-1", () => {
  beforeEach(() =>
    server.use(
      http.get("/api/v1/knowledge-sources", () => HttpResponse.json(MOCK_CONNECTORS)),
    )
  );

  it("renders a row for each connector with name and status badge", async () => {
    render(<ConnectorListPage />, { wrapper: TestWrapper });
    expect(await screen.findByText("GitHub Docs")).toBeInTheDocument();
    expect(await screen.findByText("Confluence KB")).toBeInTheDocument();
    expect(screen.getByLabelText("Connector status: Active")).toBeInTheDocument();
    expect(screen.getByLabelText("Connector status: Error")).toBeInTheDocument();
  });

  it("shows document_count with thousands separator", async () => {
    render(<ConnectorListPage />, { wrapper: TestWrapper });
    expect(await screen.findByText("1,234")).toBeInTheDocument();
  });

  it("shows 'Never' when last_sync_at is null", async () => {
    render(<ConnectorListPage />, { wrapper: TestWrapper });
    expect(await screen.findByText("Never")).toBeInTheDocument();
  });
});
```

```tsx
// frontend/admin-portal/src/__tests__/TestConnectionButton.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { server }                    from "../../mocks/server";
import { http, HttpResponse }        from "msw";
import { TestConnectionButton }      from "../components/connectors/TestConnectionButton";
import { TestWrapper }               from "../../test-utils/TestWrapper";

describe("TestConnectionButton — AC-3", () => {
  it("shows 'OK (50 ms)' on successful health check", async () => {
    server.use(
      http.post("/api/v1/knowledge-sources/abc/health-check", () =>
        HttpResponse.json({ ok: true, latency_ms: 50, detail: null })
      )
    );
    render(<TestConnectionButton connectorId="abc" />, { wrapper: TestWrapper });
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
    expect(await screen.findByText("OK (50 ms)")).toBeInTheDocument();
  });

  it("shows error detail on failed health check", async () => {
    server.use(
      http.post("/api/v1/knowledge-sources/abc/health-check", () =>
        HttpResponse.json({ ok: false, latency_ms: 120, detail: "Connection refused" })
      )
    );
    render(<TestConnectionButton connectorId="abc" />, { wrapper: TestWrapper });
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
    expect(await screen.findByText(/Connection refused/)).toBeInTheDocument();
  });
});
```

```tsx
// frontend/admin-portal/src/__tests__/ConnectorToggle.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { server }                    from "../../mocks/server";
import { http, HttpResponse }        from "msw";
import { ConnectorToggle }           from "../components/connectors/ConnectorToggle";
import { TestWrapper }               from "../../test-utils/TestWrapper";

describe("ConnectorToggle — AC-4", () => {
  it("fires PATCH request when toggled", async () => {
    let patchCalled = false;
    server.use(
      http.patch("/api/v1/knowledge-sources/xyz/status", () => {
        patchCalled = true;
        return HttpResponse.json({ id: "xyz", status: "inactive" });
      })
    );
    render(<ConnectorToggle connectorId="xyz" enabled={true} />, { wrapper: TestWrapper });
    fireEvent.click(screen.getByRole("switch", { name: /disable connector/i }));
    await screen.findByRole("switch");
    expect(patchCalled).toBe(true);
  });
});
```

```tsx
// frontend/admin-portal/src/__tests__/AddConnectorWizard.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent                              from "@testing-library/user-event";
import AddConnectorPage                       from "../pages/connectors/AddConnectorPage";
import { TestWrapper }                        from "../../test-utils/TestWrapper";

describe("AddConnectorPage wizard — AC-2", () => {
  it("advances through all 4 steps and submits", async () => {
    render(<AddConnectorPage />, { wrapper: TestWrapper });

    // Step 1: type selection
    fireEvent.click(screen.getByLabelText(/github/i));
    await userEvent.type(screen.getByLabelText(/name/i), "My GitHub");
    fireEvent.click(screen.getByRole("button", { name: /next/i }));

    // Step 2: credentials — vault path
    await screen.findByText(/credentials/i);
    await userEvent.type(
      screen.getByLabelText(/vault secret path/i),
      "secret/data/connectors/github/my-org"
    );
    fireEvent.click(screen.getByRole("button", { name: /next/i }));

    // Step 3: scope
    await screen.findByText(/scope/i);
    await userEvent.type(screen.getByLabelText(/scope/i), "my-org/my-repo");
    fireEvent.click(screen.getByRole("button", { name: /next/i }));

    // Step 4: schedule
    await screen.findByText(/schedule/i);
    await userEvent.type(screen.getByLabelText(/cron/i), "0 2 * * *");
    fireEvent.click(screen.getByRole("button", { name: /add connector/i }));

    await waitFor(() =>
      expect(screen.queryByText(/add connector/i)).not.toBeInTheDocument()
    );
  });

  it("shows cron validation error for invalid expression", async () => {
    render(<AddConnectorPage />, { wrapper: TestWrapper });

    // Navigate to step 4
    fireEvent.click(screen.getByLabelText(/github/i));
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.type(screen.getByLabelText(/vault secret path/i), "secret/data/connectors/github/x");
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.type(screen.getByLabelText(/scope/i), "org/repo");
    fireEvent.click(screen.getByRole("button", { name: /next/i }));

    await userEvent.type(screen.getByLabelText(/cron/i), "not-a-cron");
    fireEvent.click(screen.getByRole("button", { name: /add connector/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/valid cron/i);
  });
});
```

---

### Backend integration tests

```python
# tests/knowledge_sources/test_health_check_route.py
import pytest
import uuid
from unittest.mock import AsyncMock, patch
from httpx         import AsyncClient, ASGITransport
from src.main      import app   # FastAPI app


@pytest.mark.asyncio
async def test_health_check_returns_ok(fake_db, admin_headers):
    """AC-3: successful health_check() returns ok=True with latency_ms."""
    source_id = str(uuid.uuid4())

    with patch(
        "src.knowledge_sources.services.health_check_service.HealthCheckService.run",
        new=AsyncMock(return_value={"ok": True, "latency_ms": 42, "detail": None}),
    ):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            r = await client.post(
                f"/v1/knowledge-sources/{source_id}/health-check",
                headers=admin_headers,
            )

    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["latency_ms"] == 42


@pytest.mark.asyncio
async def test_health_check_returns_ok_false_on_connector_error(fake_db, admin_headers):
    """AC-3: connector exception returns ok=False with detail — not a 5xx."""
    source_id = str(uuid.uuid4())

    with patch(
        "src.knowledge_sources.services.health_check_service.HealthCheckService.run",
        new=AsyncMock(return_value={"ok": False, "latency_ms": 10, "detail": "Connection refused"}),
    ):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            r = await client.post(
                f"/v1/knowledge-sources/{source_id}/health-check",
                headers=admin_headers,
            )

    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "Connection refused" in r.json()["detail"]
```

```python
# tests/knowledge_sources/test_audit_log.py
import pytest
import uuid
from sqlalchemy import select
from src.knowledge_sources.models.connector_audit_log import ConnectorAuditLog


@pytest.mark.asyncio
async def test_create_connector_writes_audit_entry(async_session, admin_headers, client):
    """AC-5: POST /v1/knowledge-sources inserts a 'created' audit entry."""
    payload = {
        "name":           "Test Source",
        "connector_type": "github",
        "vault_path":     "secret/data/connectors/github/test",
        "scope":          "my-org/my-repo",
        "sync_schedule":  "0 2 * * *",
    }
    r = await client.post("/v1/knowledge-sources", json=payload, headers=admin_headers)
    assert r.status_code == 201
    source_id = uuid.UUID(r.json()["id"])

    rows = (await async_session.execute(
        select(ConnectorAuditLog).where(ConnectorAuditLog.connector_id == source_id)
    )).scalars().all()

    assert len(rows) == 1
    assert rows[0].event_type == "created"


@pytest.mark.asyncio
async def test_status_change_writes_audit_entry(async_session, admin_headers, client, existing_source_id):
    """AC-5: PATCH /status inserts a 'status_changed' audit entry."""
    r = await client.patch(
        f"/v1/knowledge-sources/{existing_source_id}/status",
        json={"status": "inactive"},
        headers=admin_headers,
    )
    assert r.status_code == 200

    rows = (await async_session.execute(
        select(ConnectorAuditLog).where(
            ConnectorAuditLog.connector_id == existing_source_id,
            ConnectorAuditLog.event_type   == "status_changed",
        )
    )).scalars().all()

    assert len(rows) >= 1
    assert "inactive" in rows[-1].detail


@pytest.mark.asyncio
async def test_health_check_writes_audit_entry(async_session, admin_headers, client, existing_source_id):
    """AC-5: POST /health-check inserts a 'health_checked' audit entry."""
    from unittest.mock import patch, AsyncMock
    from src.knowledge_sources.schemas.connector_audit import HealthCheckResponse

    with patch(
        "src.knowledge_sources.services.health_check_service.HealthCheckService.run",
        new=AsyncMock(return_value=HealthCheckResponse(ok=True, latency_ms=5, detail=None)),
    ):
        r = await client.post(
            f"/v1/knowledge-sources/{existing_source_id}/health-check",
            headers=admin_headers,
        )
    assert r.status_code == 200

    rows = (await async_session.execute(
        select(ConnectorAuditLog).where(
            ConnectorAuditLog.connector_id == existing_source_id,
            ConnectorAuditLog.event_type   == "health_checked",
        )
    )).scalars().all()
    assert len(rows) >= 1
```

## Acceptance Criteria

- [ ] `kubectl apply -f k8s/admin-portal/` creates the Deployment, Service, ConfigMap, and Ingress (AC-6)
- [ ] Nginx container is `Ready` within 30 s; `GET /healthz` returns 200 (AC-6)
- [ ] Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `CSP`) are present on all responses (OWASP)
- [ ] `ConnectorListPage` test: connector name, status badge `aria-label`, doc count with thousands separator, "Never" for null sync (AC-1)
- [ ] `AddConnectorWizard` test: full 4-step submit succeeds; cron validation error shown (AC-2)
- [ ] `TestConnectionButton` test: OK result and failure detail rendered inline (AC-3)
- [ ] `ConnectorToggle` test: PATCH called on toggle (AC-4)
- [ ] `test_create_connector_writes_audit_entry` — audit row with `event_type="created"` (AC-5)
- [ ] `test_status_change_writes_audit_entry` — audit row with `event_type="status_changed"` (AC-5)
- [ ] `test_health_check_writes_audit_entry` — audit row with `event_type="health_checked"` (AC-5)

## Dependencies

- TASK-US039-01 through TASK-US039-04 (all frontend and backend tasks)
- US-025 TASK-US025-04 (existing routes extended, not replaced)

## Definition of Done

- [ ] All frontend tests pass with `pnpm test`
- [ ] All backend tests pass with `pytest tests/knowledge_sources/`
- [ ] `kubectl apply --dry-run=client -f k8s/admin-portal/` exits 0
- [ ] Alembic migration `0016` has been run; `connector_audit_log` table exists
