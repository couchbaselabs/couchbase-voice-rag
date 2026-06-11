import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API_BASE } from "@/lib/constants";
import { server } from "@/test/msw-server";
import { toastMock } from "@/test/helpers";

import FileUpload from "./FileUpload";

vi.mock("sonner", () => ({ toast: toastMock }));

function makePdf(): File {
  return new File(["dummy"], "report.pdf", { type: "application/pdf" });
}

describe("FileUpload", () => {
  beforeEach(() => {
    toastMock.error.mockReset();
  });

  it("calls onRefresh after a successful upload", async () => {
    server.use(
      http.post(`${API_BASE}/documents/upload`, () =>
        HttpResponse.json({
          filename: "report.pdf",
          chunk_count: 3,
          status: "vectorizing",
        })
      ),
      http.get(`${API_BASE}/documents/status/:filename`, () =>
        HttpResponse.json({ status: "vectorizing" })
      )
    );
    const onRefresh = vi.fn();
    const user = userEvent.setup();
    render(<FileUpload files={[]} onRefresh={onRefresh} />);

    const input = screen.getByLabelText(/upload pdf/i) as HTMLInputElement;
    await user.upload(input, makePdf());

    await vi.waitFor(() => expect(onRefresh).toHaveBeenCalled());
    expect(toastMock.error).not.toHaveBeenCalled();
  });

  it("shows 413 inline instead of a toast", async () => {
    server.use(
      http.post(`${API_BASE}/documents/upload`, () =>
        HttpResponse.json({ detail: "File too large. Maximum size is 50MB." }, { status: 413 })
      )
    );
    const user = userEvent.setup();
    render(<FileUpload files={[]} onRefresh={vi.fn()} />);
    await user.upload(screen.getByLabelText(/upload pdf/i), makePdf());

    expect(await screen.findByText(/maximum size is 50mb/i)).toBeInTheDocument();
    expect(toastMock.error).not.toHaveBeenCalled();
  });

  it("toasts server errors outside the 400/413 inline set", async () => {
    server.use(
      http.post(`${API_BASE}/documents/upload`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 })
      )
    );
    const user = userEvent.setup();
    render(<FileUpload files={[]} onRefresh={vi.fn()} />);
    await user.upload(screen.getByLabelText(/upload pdf/i), makePdf());

    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalled());
    expect(toastMock.error.mock.calls[0]?.[0]).toMatch(/server error/i);
  });
});
