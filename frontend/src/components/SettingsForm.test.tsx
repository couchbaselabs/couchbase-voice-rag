import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API_BASE } from "@/lib/constants";
import { server } from "@/test/msw-server";
import { toastMock } from "@/test/helpers";

import SettingsForm from "./SettingsForm";

vi.mock("sonner", () => ({ toast: toastMock }));

// Backend echoes saved secrets so the UI can pre-fill them; type=password
// + the eye toggle handle the masking client-side.
const populatedSecretsResponse = {
  settings: {
    cb_connection_string: "couchbases://cb.example",
    cb_username: "admin",
    cb_password: "stored-password",
    cb_bucket: "rag",
    cb_scope: "_default",
    cb_collection: "documents_capella",
    cb_search_index: "vector-search-index-capella",
    embedding_method: "capella",
    azure_openai_endpoint: "https://example.openai.azure.com",
    openai_api_key: "stored-openai",
    openai_realtime_model: "gpt-realtime",
    openai_embedding_model: "text-embedding-3-small",
    capella_api_key_id: "stored-cap-id",
    capella_api_key_token: "stored-cap-tok",
    deepgram_api_key: "stored-dg",
    tavily_api_key: "stored-tv",
    web_search_enabled: false,
  },
};

describe("SettingsForm", () => {
  beforeEach(() => {
    toastMock.error.mockReset();
  });

  it("renders secret fields populated with stored values, masked", async () => {
    server.use(http.get(`${API_BASE}/settings`, () => HttpResponse.json(populatedSecretsResponse)));
    render(<SettingsForm onSuccess={vi.fn()} />);

    const password = (await screen.findByLabelText(/^password$/i)) as HTMLInputElement;
    expect(password).toHaveValue("stored-password");
    expect(password).toHaveAttribute("type", "password");
    // No "Change" button anymore
    expect(screen.queryByRole("button", { name: /change/i })).toBeNull();
  });

  it("eye toggle reveals stored secret as plaintext", async () => {
    server.use(http.get(`${API_BASE}/settings`, () => HttpResponse.json(populatedSecretsResponse)));
    const user = userEvent.setup();
    render(<SettingsForm onSuccess={vi.fn()} />);

    const password = (await screen.findByLabelText(/^password$/i)) as HTMLInputElement;
    expect(password).toHaveAttribute("type", "password");

    const showButtons = screen.getAllByRole("button", { name: /show value/i });
    // First show button = first secret field (cb_password) in DOM order
    await user.click(showButtons[0]!);
    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveValue("stored-password");
  });

  it("submits a fully typed SettingsRequest payload including new fields", async () => {
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API_BASE}/settings`, () => HttpResponse.json(populatedSecretsResponse)),
      http.post(`${API_BASE}/settings`, async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true, message: "Connected" });
      })
    );
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    render(<SettingsForm onSuccess={onSuccess} />);

    const password = (await screen.findByLabelText(/^password$/i)) as HTMLInputElement;
    // Replace the pre-filled "stored-password" with a fresh value
    await user.clear(password);
    await user.type(password, "newsecret");
    await user.click(screen.getByRole("button", { name: /connect & initialize/i }));

    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(captured).toMatchObject({
      cb_connection_string: "couchbases://cb.example",
      cb_username: "admin",
      cb_password: "newsecret",
      cb_bucket: "rag",
      cb_scope: "_default",
      embedding_method: "capella",
      // Untouched secrets round-trip the stored value
      openai_api_key: "stored-openai",
      capella_api_key_id: "stored-cap-id",
      capella_api_key_token: "stored-cap-tok",
      deepgram_api_key: "stored-dg",
      tavily_api_key: "stored-tv",
      web_search_enabled: false,
    });
  });

  it("web search toggle is reflected in the payload", async () => {
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API_BASE}/settings`, () => HttpResponse.json(populatedSecretsResponse)),
      http.post(`${API_BASE}/settings`, async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true, message: "Connected" });
      })
    );
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    render(<SettingsForm onSuccess={onSuccess} />);

    await screen.findByRole("switch", { name: /web search fallback/i });
    await user.click(screen.getByRole("switch", { name: /web search fallback/i }));
    await user.click(screen.getByRole("button", { name: /connect & initialize/i }));

    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(captured).toMatchObject({ web_search_enabled: true });
  });

  it("blocks submit and shows inline errors when required fields are blank", async () => {
    server.use(
      http.get(`${API_BASE}/settings`, () =>
        HttpResponse.json({ settings: { cb_scope: "_default", embedding_method: "capella" } })
      )
    );
    let posted = false;
    server.use(
      http.post(`${API_BASE}/settings`, () => {
        posted = true;
        return HttpResponse.json({ ok: true });
      })
    );
    const user = userEvent.setup();
    render(<SettingsForm onSuccess={vi.fn()} />);

    await screen.findByRole("button", { name: /connect & initialize/i });
    await user.click(screen.getByRole("button", { name: /connect & initialize/i }));

    expect(await screen.findByText(/connection string is required/i)).toBeInTheDocument();
    expect(posted).toBe(false);
  });

  it("shows the backend error inline when connect fails with 400", async () => {
    server.use(
      http.get(`${API_BASE}/settings`, () => HttpResponse.json(populatedSecretsResponse)),
      http.post(`${API_BASE}/settings`, () =>
        HttpResponse.json(
          { detail: "Connection failed: unknown host" },
          { status: 400, headers: { "X-Request-ID": "req-1" } }
        )
      )
    );
    const user = userEvent.setup();
    render(<SettingsForm onSuccess={vi.fn()} />);

    await screen.findByLabelText(/^password$/i);
    await user.click(screen.getByRole("button", { name: /connect & initialize/i }));

    expect(await screen.findByText(/unknown host/i)).toBeInTheDocument();
    expect(screen.getByText(/req-1/)).toBeInTheDocument();
    expect(toastMock.error).not.toHaveBeenCalled();
  });
});
