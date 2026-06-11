import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import { ErrorBoundary } from "./ErrorBoundary";

// React logs "The above error occurred" to console.error from the class body
// — silence it so the test output stays readable.
let consoleErrorSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  consoleErrorSpy.mockRestore();
});

function Throw({ error }: { error: Error }): never {
  throw error;
}

describe("ErrorBoundary", () => {
  it("renders children when there is no error", () => {
    render(
      <ErrorBoundary>
        <p>OK</p>
      </ErrorBoundary>
    );
    expect(screen.getByText("OK")).toBeInTheDocument();
  });

  it("renders fallback with the error message when a child throws", () => {
    render(
      <ErrorBoundary>
        <Throw error={new Error("something broke")} />
      </ErrorBoundary>
    );
    expect(screen.getByText("Something went wrong.")).toBeInTheDocument();
    expect(screen.getByText("something broke")).toBeInTheDocument();
  });

  it("shows request id when the thrown error is an ApiError", () => {
    render(
      <ErrorBoundary>
        <Throw error={new ApiError(500, "server blew up", "req-deadbeef")} />
      </ErrorBoundary>
    );
    expect(screen.getByText(/req-deadbeef/)).toBeInTheDocument();
  });
});
