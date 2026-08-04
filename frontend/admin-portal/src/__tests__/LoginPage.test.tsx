import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AuthContext } from "../context/AuthContext";
import { LoginPage } from "../pages/errors/LoginPage";

function renderPage(initialEntry = "/login") {
  return render(
    <AuthContext.Provider
      value={{
        user: null,
        isLoading: false,
        signIn: async () => {},
        signOut: () => {},
        hasRole: () => false,
        hasAnyRole: () => false,
      }}
    >
      <MemoryRouter initialEntries={[initialEntry]}>
        <LoginPage />
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("LoginPage", () => {
  it("shows the create account link", () => {
    renderPage();

    expect(screen.getByRole("link", { name: /create one/i })).toHaveAttribute(
      "href",
      "/register",
    );
  });

  it("shows the registration success banner when redirected from register", () => {
    renderPage("/login?registered=1&username=newuser");

    expect(
      screen.getByText(/account created\. sign in with your new username and password\./i),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("newuser")).toBeInTheDocument();
  });
});