import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AuthContext } from "../context/AuthContext";
import { hasAnyRole as checkHasAnyRole } from "../auth/roles";
import type { PlatformRoleValue } from "../auth/roles";
import type { User } from "../context/AuthContext";
import { TraceDetailPage } from "../pages/traces/TraceDetailPage";

const REQUEST_ID = "req-abc-123";
let exportRequestCount = 0;
let exportAuthHeader = "";

const server = setupServer(
  http.get("/api/v1/traces/:id", ({ params }) => {
    if (params.id !== REQUEST_ID) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    return HttpResponse.json({
      request_id: REQUEST_ID,
      user_id: "user-1",
      timestamp: "2026-07-09T12:00:00Z",
      latency_ms: 182,
      intent_classification: "debugging",
      intent_confidence: 0.92,
      retrieved_sources: [
        {
          chunk_id: "chunk-001",
          source_id: "github",
          relevance_score: 0.93,
          classification_label: "internal",
          redacted: false,
          opa_denied: false,
        },
      ],
      compression_delta: {
        tokens_before: 1200,
        tokens_after: 600,
        chunks_before: 8,
        chunks_after: 4,
        reduction_pct: 50,
      },
      governance_decisions: {
        findings_count: 1,
        redacted_count: 0,
        opa_denied_count: 0,
        opa_bundle_version: "local-inline-policy",
        governance_blocked: false,
      },
      model_selected: "gpt-4o-mini",
      prompt_tokens: 345,
      completion_tokens: 128,
      response_summary: "Trace replay summary.",
      timeline: [
        { step_number: 1, node: "intent_agent", eval_ms: 12.4, metadata: {} },
        { step_number: 2, node: "routing_agent", eval_ms: 8.1, metadata: {} },
      ],
    });
  }),
  http.get("/api/v1/traces/:id/export", async ({ request, params }) => {
    if (params.id !== REQUEST_ID) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    exportRequestCount += 1;
    exportAuthHeader = request.headers.get("authorization") ?? "";
    return new HttpResponse('{"request_id":"req-abc-123"}', {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Content-Disposition": `attachment; filename="contextiq-trace-${REQUEST_ID}.json"`,
      },
    });
  })
);

beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  sessionStorage.clear();
  exportRequestCount = 0;
  exportAuthHeader = "";
});
afterAll(() => server.close());

function makeUser(id: string, email: string, roles: string[]): User {
  return { id, email, roles };
}

function buildMockContextValue(user: User | null) {
  return {
    user,
    isLoading: false,
    signIn: async (_token: string) => {},
    signOut: () => {},
    hasRole: (role: PlatformRoleValue) =>
      user ? checkHasAnyRole(user.roles, [role]) : false,
    hasAnyRole: (roles: PlatformRoleValue[]) =>
      user ? checkHasAnyRole(user.roles, roles) : false,
  };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPage(user: User | null) {
  return render(
    <MemoryRouter initialEntries={[`/traces/${REQUEST_ID}`]}>
      <AuthContext.Provider value={buildMockContextValue(user)}>
        <QueryClientProvider client={makeQueryClient()}>
          <Routes>
            <Route path="/traces/:id" element={<TraceDetailPage />} />
          </Routes>
        </QueryClientProvider>
      </AuthContext.Provider>
    </MemoryRouter>
  );
}

describe("TraceDetailPage", () => {
  it("renders the trace detail view from the replay API", async () => {
    renderPage(makeUser("u1", "auditor@test.com", ["auditor"]));

    expect(await screen.findByRole("heading", { name: /Trace req-abc-123/i })).toBeInTheDocument();
    expect(screen.getByText("Intent Classification")).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
    expect(screen.getByText("Pipeline Timeline (2 steps)")).toBeInTheDocument();
    expect(screen.getByText("Model Routing")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
  });

  it("downloads the raw trace export through the authenticated api client", async () => {
    sessionStorage.setItem(
      "admin_user",
      JSON.stringify({ token: "test-token", user: makeUser("u1", "auditor@test.com", ["auditor"]) })
    );

    const originalCreateObjectUrl = URL.createObjectURL;
    const originalRevokeObjectUrl = URL.revokeObjectURL;
    const createObjectUrl = vi.fn(() => "blob:trace-export");
    const revokeObjectUrl = vi.fn(() => {});
    Object.defineProperty(URL, "createObjectURL", {
      writable: true,
      value: createObjectUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      writable: true,
      value: revokeObjectUrl,
    });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    try {
      renderPage(makeUser("u1", "auditor@test.com", ["auditor"]));

      await screen.findByRole("button", { name: /Export trace as JSON file/i });
      await userEvent.click(screen.getByRole("button", { name: /Export trace as JSON file/i }));

      await waitFor(() => {
        expect(exportRequestCount).toBe(1);
        expect(exportAuthHeader).toBe("Bearer test-token");
        expect(createObjectUrl).toHaveBeenCalled();
        expect(clickSpy).toHaveBeenCalled();
        expect(revokeObjectUrl).toHaveBeenCalledWith("blob:trace-export");
      });
    } finally {
      Object.defineProperty(URL, "createObjectURL", {
        writable: true,
        value: originalCreateObjectUrl,
      });
      Object.defineProperty(URL, "revokeObjectURL", {
        writable: true,
        value: originalRevokeObjectUrl,
      });
      clickSpy.mockRestore();
    }
  });
});