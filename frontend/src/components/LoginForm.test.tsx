import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { toastMock } from "@/test/helpers";

import LoginForm from "./LoginForm";

vi.mock("sonner", () => ({ toast: toastMock }));

describe("LoginForm", () => {
  beforeEach(() => {
    toastMock.error.mockReset();
  });

  it("submits the credentials through onLogin", async () => {
    const onLogin = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<LoginForm onLogin={onLogin} />);

    await user.type(screen.getByLabelText(/username/i), "tester");
    await user.type(screen.getByLabelText(/password/i), "secret1234");
    await user.click(screen.getByRole("button", { name: /login/i }));

    expect(onLogin).toHaveBeenCalledWith("tester", "secret1234");
    expect(toastMock.error).not.toHaveBeenCalled();
  });

  it("shows an inline error (no toast) on 401", async () => {
    const onLogin = vi.fn().mockRejectedValue(new ApiError(401, "Invalid credentials", undefined));
    const user = userEvent.setup();
    render(<LoginForm onLogin={onLogin} />);

    await user.type(screen.getByLabelText(/username/i), "tester");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /login/i }));

    expect(await screen.findByText(/invalid username or password/i)).toBeInTheDocument();
    expect(toastMock.error).not.toHaveBeenCalled();
  });

  it("toasts other ApiError statuses (e.g., 429 rate limit)", async () => {
    const onLogin = vi.fn().mockRejectedValue(new ApiError(429, "too many", undefined));
    const user = userEvent.setup();
    render(<LoginForm onLogin={onLogin} />);

    await user.type(screen.getByLabelText(/username/i), "tester");
    await user.type(screen.getByLabelText(/password/i), "whatever");
    await user.click(screen.getByRole("button", { name: /login/i }));

    // Wait for the async rejection path to land.
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalled());
    expect(toastMock.error.mock.calls[0]?.[0]).toMatch(/too many requests/i);
  });
});
