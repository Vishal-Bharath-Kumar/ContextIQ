import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, it, expect, beforeAll, afterEach, afterAll } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { RegisterPage } from "../pages/errors/RegisterPage";

let capturedBody: unknown = null;

const server = setupServer(
  http.post("/api/auth/dev-register", async ({ request }) => {
    capturedBody = await request.json();
    return HttpResponse.json(
      {
        username: "newuser",
        email: "newuser@example.com",
        assigned_role: "developer",
        message: "Registration successful. Sign in with your new account.",
      },
      { status: 201 },
    );
  }),
)

beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  capturedBody = null;
});
afterAll(() => server.close());

function renderPage() {
  const user = userEvent.setup();

  function LoginProbe() {
    const location = useLocation();
    return <div data-testid="login-probe">{location.pathname}{location.search}</div>;
  }

  render(
    <MemoryRouter initialEntries={["/register"]}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/login" element={<LoginProbe />} />
      </Routes>
    </MemoryRouter>,
  );
  return { user };
}

describe("RegisterPage", () => {
  it("submits the registration payload and redirects to login success state", async () => {
    const { user } = renderPage();

    await user.type(screen.getByLabelText(/First name/i), "New");
    await user.type(screen.getByLabelText(/Last name/i), "User");
    await user.type(screen.getByLabelText(/^Username$/i), "newuser");
    await user.type(screen.getByLabelText(/Email/i), "newuser@example.com");
    await user.type(screen.getByLabelText(/^Password$/i), "supersecret");
    await user.type(screen.getByLabelText(/Confirm password/i), "supersecret");
    await user.selectOptions(screen.getByLabelText(/User role/i), "admin");

    await user.click(screen.getByRole("button", { name: /Create account/i }));

    await waitFor(() => {
      expect(screen.getByTestId("login-probe")).toHaveTextContent(
        "/login?registered=1&username=newuser",
      );
    });

    expect(capturedBody).toMatchObject({
      username: "newuser",
      email: "newuser@example.com",
      first_name: "New",
      last_name: "User",
      password: "supersecret",
      role: "admin",
    });
  });

  it("shows password mismatch validation", async () => {
    const { user } = renderPage();

    await user.type(screen.getByLabelText(/First name/i), "New");
    await user.type(screen.getByLabelText(/Last name/i), "User");
    await user.type(screen.getByLabelText(/^Username$/i), "newuser");
    await user.type(screen.getByLabelText(/Email/i), "newuser@example.com");
    await user.type(screen.getByLabelText(/^Password$/i), "supersecret");
    await user.type(screen.getByLabelText(/Confirm password/i), "different");

    await user.click(screen.getByRole("button", { name: /Create account/i }));

    await waitFor(() => {
      expect(screen.getByText("Passwords do not match")).toBeInTheDocument();
    });
  });
});