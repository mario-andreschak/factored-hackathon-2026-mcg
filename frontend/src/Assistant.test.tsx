import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Assistant } from "./App";
import type { Transaction } from "./types";

const charge: Transaction = {
  reference: "txn_aaaaaaaaaaaaaaaaaaaaaaaa",
  product_reference: "card-1",
  occurred_at: "2026-09-20",
  process_date: "2026-09-20",
  type: "Purchase",
  category: "Shopping",
  amount: 42,
  currency: "COP",
  status: "Approved",
  channel: "Card",
  merchant: "Mercado Central",
  country: "CO",
  city: "Bogotá",
  direction: "debit",
};

const response = (body: unknown) =>
  ({
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => body,
  }) as unknown as Response;

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value() {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value() {
      this.removeAttribute("open");
    },
  });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value() {},
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("Portuguese consent and saved status survive refresh without submitting an action", async () => {
  const calls: { url: string; method: string; body?: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || "GET";
      calls.push({ url, method, body: init?.body as string | undefined });
      if (url === "/api/chat/history")
        return response({
          active: false,
          messages: [{ role: "assistant", text: "Consulta anterior" }],
        });
      if (url.startsWith("/api/action/status")) {
        const language = new URL(url, "http://localhost").searchParams.get(
          "language",
        );
        return response({
          state: "pending_confirmation",
          pending_handle: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          target_reference: charge.reference,
          request_id: "00000000-0000-4000-8000-000000000001",
          message:
            language === "pt"
              ? "Estado em português para este lançamento."
              : "Estado en español para este cargo.",
        });
      }
      if (url === "/api/action/confirm")
        return response({
          state: "intake_verified",
          target_reference: charge.reference,
          message: "Registro simulado confirmado.",
        });
      throw new Error(`Unexpected request: ${method} ${url}`);
    }),
  );

  const props = {
    open: true,
    status: { available: true, sandbox_intake_available: true },
    selected: charge,
    transactions: [charge],
    onSelectTransaction: vi.fn(),
    hidden: false,
    synthetic: true,
    onClose: vi.fn(),
    onExpired: vi.fn(),
  };
  const first = render(<Assistant {...props} />);
  await screen.findByRole("button", {
    name: "Confirmo la recepción simulada para este cargo",
  });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "pt" } });

  await screen.findByRole("button", {
    name: "Confirmo o registro simulado para este lançamento",
  });
  await screen.findByText("Estado em português para este lançamento.");
  expect(screen.getByText(/O registro é uma simulação/)).toBeTruthy();
  expect(
    calls.some(({ url }) => url === "/api/action/status?language=pt"),
  ).toBe(true);
  expect(
    calls.filter(
      ({ url, method }) => url.startsWith("/api/action/") && method === "POST",
    ),
  ).toHaveLength(0);

  first.unmount();
  const refreshStart = calls.length;
  render(<Assistant {...props} />);
  await screen.findByText("Estado em português para este lançamento.");
  expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("pt");
  expect(
    calls
      .slice(refreshStart)
      .some(({ url }) => url === "/api/action/status?language=pt"),
  ).toBe(true);
  expect(
    calls.filter(
      ({ url, method }) => url.startsWith("/api/action/") && method === "POST",
    ),
  ).toHaveLength(0);

  fireEvent.click(
    screen.getByRole("button", {
      name: "Confirmo o registro simulado para este lançamento",
    }),
  );
  await waitFor(() =>
    expect(
      calls.filter(
        ({ url, method }) => url === "/api/action/confirm" && method === "POST",
      ),
    ).toHaveLength(1),
  );
  const confirm = calls.find(({ url }) => url === "/api/action/confirm");
  expect(JSON.parse(confirm!.body!)).toMatchObject({
    language: "pt",
    pending_handle: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    transaction_reference: charge.reference,
    confirmed: true,
  });
});

test("exhausted recovery shows one opaque review code and the ES/PT sharing route", async () => {
  const reviewReference = "rev_1234567890abcdef12345678";
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url === "/api/chat/history")
        return response({
          active: false,
          messages: [{ role: "assistant", text: "Consulta anterior" }],
        });
      if (url.startsWith("/api/action/status")) {
        const language = new URL(url, "http://localhost").searchParams.get(
          "language",
        );
        return response({
          state: "prepare_unverified",
          recovery_exhausted: true,
          review_reference: reviewReference,
          target_reference: charge.reference,
          message:
            language === "pt"
              ? "A solicitação continua sem resolução e bloqueada; a referência não avisa a equipe."
              : "La solicitud sigue sin resolver y bloqueada; la referencia no avisa al equipo.",
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );

  render(
    <Assistant
      open
      status={{ available: true, sandbox_intake_available: true }}
      selected={charge}
      transactions={[charge]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );
  await screen.findByText(reviewReference);
  expect(screen.getByText(/Copia esta referencia y compártela/)).toBeTruthy();
  expect(screen.getByText(/sigue sin resolver y bloqueada/)).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /Confirmo la recepción/ }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Revisar recepción simulada" }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Prefiero revisión humana" }),
  ).toBeNull();

  fireEvent.change(screen.getByRole("combobox"), { target: { value: "pt" } });
  await screen.findByText(/A solicitação continua sem resolução e bloqueada/);
  expect(screen.getByText(reviewReference)).toBeTruthy();
  expect(screen.getByText(/Copie esta referência e compartilhe/)).toBeTruthy();
  expect(screen.getByText(/não avisa a equipe/)).toBeTruthy();
  expect(calls).toContain("GET /api/action/status?language=pt");
  expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
});
