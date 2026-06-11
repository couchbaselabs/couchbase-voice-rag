import { vi } from "vitest";

/**
 * Stable mock of the ``sonner`` module so tests can assert toast calls
 * without mounting a real ``<Toaster />``. Call as:
 *
 *     vi.mock("sonner", () => mockSonner);
 *
 * Then access ``toastMock.error.mock.calls`` for assertions.
 */
export const toastMock = {
  error: vi.fn(),
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  message: vi.fn(),
};

export const mockSonner = {
  toast: toastMock,
  Toaster: () => null,
};
