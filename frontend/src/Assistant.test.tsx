import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useState } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type {
  ActionFacts,
  ActionResult,
  HandoffPacket,
  IntakeReceipt,
  Transaction,
} from "./types";
import { Assistant } from "./App";
const voiceHarness = vi.hoisted(() => ({
  active: false,
  owner: null as symbol | null,
  connecting: false,
  phase: "idle" as const,
  level: 0,
  error: null as null,
  start: vi.fn(async () => {}),
  stop: vi.fn(),
  narrate: vi.fn(() => true),
  getSessionOwner: vi.fn(() =>
    voiceHarness.active ? voiceHarness.owner : null,
  ),
  interrupt: vi.fn(),
  options: null as null | {
    onHeard?: (id: string, text: string, final: boolean) => void;
    onCaption?: (id: string, text: string, final: boolean) => void;
  },
}));
const inquiryHarness = vi.hoisted(() => ({
  props: null as null | {
    onVoiceUpdate?: (caseId: string, eventId: number) => void;
  },
}));
vi.mock("./avatar/useSaviaVoice", () => ({
  useSaviaVoice: (options: unknown) => {
    voiceHarness.options = options as typeof voiceHarness.options;
    return voiceHarness;
  },
}));
vi.mock("./InquiryPanel", () => ({
  InquiryPanel: (props: unknown) => {
    inquiryHarness.props = props as typeof inquiryHarness.props;
    return null;
  },
}));

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

const savedFacts: ActionFacts = {
  transaction_reference: "txn_123456789abc",
  transaction_date: charge.occurred_at,
  process_date: charge.process_date,
  amount: "42.00",
  currency: charge.currency,
  status: charge.status,
  merchant: charge.merchant,
  transaction_type: charge.type,
  channel: charge.channel,
  product: "Tarjeta de débito",
};
const preparedEvidence = { snapshot: "fixture-2026", transaction: savedFacts };
const receipt: IntakeReceipt = {
  id: "CMP-SBX-abcdefgh",
  kind: "simulated_intake",
  simulated: true,
  status: "received",
  snapshot: "fixture-original",
  created_at: "2026-09-21T15:02:00Z",
  transaction: savedFacts,
};
const handoff: HandoffPacket = {
  id: "HOF-abcdefgh",
  reason: "missing_evidence",
  snapshot: "fixture-2026",
  created_at: "2026-09-21T15:02:00Z",
  facts: savedFacts,
  transaction_currentness: "different_snapshot",
  transaction_provenance: {
    source: "owned_serving_snapshot",
    snapshot: "fixture-2026",
    as_of: "2026-09-21T15:01:00Z",
  },
  human_responded: false,
  unanswered_questions: ["¿Puedes aclarar qué ocurrió con este cargo?"],
};
const generalHandoff: HandoffPacket = {
  ...handoff,
  reason: "customer_request",
  snapshot: null,
  facts: {},
  transaction_currentness: "not_applicable",
  transaction_provenance: null,
  unanswered_questions: ["Pregunta guardada anterior?"],
};

const effectiveLanguage = (element: Element) =>
  element.closest("[lang]")?.getAttribute("lang");

const response = (body: unknown) =>
  ({
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => body,
  }) as unknown as Response;

beforeEach(() => {
  localStorage.clear();
  voiceHarness.active = false;
  voiceHarness.owner = null;
  voiceHarness.connecting = false;
  voiceHarness.phase = "idle";
  voiceHarness.level = 0;
  voiceHarness.error = null;
  voiceHarness.start.mockClear();
  voiceHarness.stop.mockClear();
  voiceHarness.narrate.mockClear();
  voiceHarness.narrate.mockReturnValue(true);
  voiceHarness.getSessionOwner.mockClear();
  voiceHarness.interrupt.mockClear();
  voiceHarness.options = null;
  inquiryHarness.props = null;
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
  vi.unstubAllEnvs();
});

test.each([
  ["es", "Retiro", "20 sep 2026", "1,234.50", "Saque", "1.234,50"],
  ["pt", "Saque", "20 de setembro de 2026", "1.234,50", "Retiro", "1,234.50"],
] as const)(
  "%s assistant selection and transcript use localized type, date and amount",
  async (
    language,
    type,
    expectedDate,
    expectedAmount,
    otherType,
    otherAmount,
  ) => {
    const selected: Transaction = {
      ...charge,
      type: "Withdrawal",
      merchant: null,
      amount: 1234.5,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input) === "/api/chat/history")
          return response({
            active: false,
            messages: [
              {
                role: "user",
                text: "Consulta de prueba",
                selection: {
                  reference: selected.reference,
                  occurred_at: selected.occurred_at,
                  type: selected.type,
                  amount: selected.amount,
                  currency: selected.currency,
                  status: selected.status,
                },
              },
            ],
          });
        throw new Error(`Unexpected request: ${input}`);
      }),
    );
    const props = {
      open: true,
      status: { available: true, sandbox_intake_available: false },
      selected,
      transactions: [selected],
      onSelectTransaction: vi.fn(),
      hidden: false,
      synthetic: true,
      onClose: vi.fn(),
      onExpired: vi.fn(),
      initialLanguage: language as "es" | "pt",
    };
    const view = render(<Assistant {...props} />);
    await screen.findByText("Consulta de prueba");

    const summary = document.querySelector(".chat-selection")!;
    const transcript = document.querySelector(".chat-message-selection")!;
    expect(summary.querySelector("strong")?.textContent).toBe(type);
    for (const surface of [summary, transcript]) {
      expect(surface.textContent).toContain(expectedDate);
      expect(surface.textContent).toContain(expectedAmount);
      expect(surface.textContent).not.toContain(otherType);
      expect(surface.textContent).not.toContain(otherAmount);
    }
    expect(transcript.textContent).toContain(type);

    view.rerender(<Assistant {...props} hidden />);
    expect(summary.textContent).toContain("••••••");
    expect(transcript.textContent).toContain("••••••");
    expect(summary.textContent).not.toContain(expectedAmount);
    expect(transcript.textContent).not.toContain(expectedAmount);

    view.rerender(
      <Assistant
        {...props}
        selected={{ ...selected, merchant: "Mercado Central" }}
        hidden={false}
      />,
    );
    expect(summary.querySelector("strong")?.textContent).toBe(
      "Mercado Central",
    );
  },
);

test("assistant selection and transcript metadata follow ES to PT to ES without changing the charge", async () => {
  const selected: Transaction = {
    ...charge,
    reference: "txn_locale_switch_123456789abc",
    occurred_at: "2026-09-20",
    type: "Withdrawal",
    merchant: null,
    amount: 1234.5,
  };
  const original = { ...selected };
  const onSelectTransaction = vi.fn();
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    if (String(input) === "/api/chat/history")
      return response({
        active: false,
        messages: [
          {
            role: "user",
            text: "Consulta de prueba",
            selection: {
              reference: selected.reference,
              occurred_at: selected.occurred_at,
              type: selected.type,
              amount: selected.amount,
              currency: selected.currency,
              status: selected.status,
            },
          },
        ],
      });
    throw new Error(`Unexpected request: ${input}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  const props = {
    open: true,
    status: { available: true, sandbox_intake_available: false },
    selected,
    transactions: [selected],
    onSelectTransaction,
    hidden: false,
    synthetic: true,
    onClose: vi.fn(),
    onExpired: vi.fn(),
    initialLanguage: "es" as const,
  };
  const view = render(<Assistant {...props} />);
  await screen.findByText("Consulta de prueba");
  const summary = document.querySelector(".chat-selection")!;
  const transcript = document.querySelector(".chat-message-selection")!;
  const checkMetadata = (
    type: string,
    expectedDate: string,
    expectedAmount: string,
    excludedAmount: string,
    hidden = false,
  ) => {
    expect(summary.querySelector("strong")?.textContent).toBe(type);
    for (const surface of [summary, transcript]) {
      expect(surface.textContent).toContain(expectedDate);
      expect(surface.textContent).toContain(type);
      expect(surface.textContent?.match(/COP/g)).toHaveLength(1);
      if (hidden) {
        expect(surface.textContent).toContain("•••••• COP");
        expect(surface.textContent).not.toContain(expectedAmount);
        expect(surface.textContent).not.toContain(excludedAmount);
      } else {
        expect(surface.textContent).toContain(expectedAmount);
        expect(surface.textContent).not.toContain(excludedAmount);
        expect(surface.textContent).not.toContain("••••••");
      }
    }
  };
  checkMetadata("Retiro", "20 sep 2026", "1,234.50", "1.234,50");

  fireEvent.change(
    screen.getByRole("combobox", { name: "Idioma de la interfaz" }),
    {
      target: { value: "pt" },
    },
  );
  checkMetadata("Saque", "20 de setembro de 2026", "1.234,50", "1,234.50");

  view.rerender(<Assistant {...props} hidden />);
  checkMetadata(
    "Saque",
    "20 de setembro de 2026",
    "1.234,50",
    "1,234.50",
    true,
  );

  fireEvent.change(
    screen.getByRole("combobox", { name: "Idioma da interface" }),
    {
      target: { value: "es" },
    },
  );
  checkMetadata("Retiro", "20 sep 2026", "1,234.50", "1.234,50", true);

  view.rerender(<Assistant {...props} hidden={false} />);
  checkMetadata("Retiro", "20 sep 2026", "1,234.50", "1.234,50");
  expect(selected).toEqual(original);
  expect(selected.reference).toBe(original.reference);
  expect(onSelectTransaction).not.toHaveBeenCalled();
  const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
  expect(
    requestedUrls.filter((url) => url === "/api/chat/history"),
  ).toHaveLength(1);
  expect(
    requestedUrls.every(
      (url) =>
        url === "/api/chat/history" ||
        url.startsWith("/api/followups?language="),
    ),
  ).toBe(true);
});

test.each([
  ["es", "charge", "Mensaje para el asistente", "Consulta para continuar"],
  ["pt", "general", "Mensagem para o assistente", "Consulta a continuar"],
] as const)(
  "%s parent reopen to %s clears an incompatible hidden query before sending",
  async (language, destination, messageLabel, queryLabel) => {
    const queryId = "q_" + "a".repeat(32);
    const previousMessage =
      language === "pt"
        ? "Consulta anterior em português"
        : "Consulta anterior";
    const message =
      language === "pt" ? "E esta consulta?" : "¿Y esta consulta?";
    const otherCharge: Transaction = {
      ...charge,
      reference: "txn_bbbbbbbbbbbbbbbbbbbbbbbb",
      merchant: language === "pt" ? "Outra loja" : "Otra tienda",
    };
    const chatPosts: Record<string, unknown>[] = [];
    const onExpired = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "assistant", text: previousMessage }],
            queries: [
              {
                query_id: queryId,
                label: "Compra anterior",
                transaction_reference: charge.reference,
              },
            ],
            active_query_id: queryId,
          });
        if (url === "/api/chat/messages") {
          chatPosts.push(JSON.parse(init!.body as string));
          return response({
            reply: language === "pt" ? "Resposta atual." : "Respuesta actual.",
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );

    function Parent() {
      const [open, setOpen] = useState(true);
      const [selected, setSelected] = useState<Transaction | null>(charge);
      return (
        <>
          <button
            onClick={() => {
              setOpen(false);
              setSelected(null);
            }}
          >
            Close from parent
          </button>
          <button
            onClick={() => {
              setSelected(destination === "charge" ? otherCharge : null);
              setOpen(true);
            }}
          >
            Reopen from parent
          </button>
          <Assistant
            open={open}
            status={{ available: true, sandbox_intake_available: false }}
            selected={selected}
            transactions={[charge, otherCharge]}
            onSelectTransaction={setSelected}
            hidden={false}
            synthetic
            onClose={() => {
              setOpen(false);
              setSelected(null);
            }}
            onExpired={onExpired}
            initialLanguage={language}
          />
        </>
      );
    }

    render(<Parent />);
    await screen.findByText(previousMessage);
    expect(document.querySelector(".chat-selection")?.textContent).toContain(
      charge.merchant,
    );
    expect(screen.queryByRole("combobox", { name: queryLabel })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Close from parent" }));
    fireEvent.click(screen.getByRole("button", { name: "Reopen from parent" }));
    const visibleSelection = document.querySelector(".chat-selection");
    if (destination === "charge") {
      expect(visibleSelection?.textContent).toContain(otherCharge.merchant);
      expect(visibleSelection?.textContent).not.toContain(charge.merchant);
    } else {
      expect(visibleSelection).toBeNull();
    }
    expect(screen.queryByRole("combobox", { name: queryLabel })).toBeNull();

    const input = screen.getByRole("textbox", { name: messageLabel });
    fireEvent.change(input, { target: { value: message } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(chatPosts).toHaveLength(1));
    expect(chatPosts[0]).toEqual({
      message,
      language,
      ...(destination === "charge"
        ? { transaction_reference: otherCharge.reference }
        : {}),
    });
  },
);

test("restored null-reference query clears the stale charge on chat submit", async () => {
  const first = "q_" + "a".repeat(32),
    second = "q_" + "b".repeat(32);
  const queries = [
    {
      query_id: first,
      label: "Compra en Mercado Central",
      transaction_reference: charge.reference,
    },
    {
      query_id: second,
      label: "Estado de otra compra",
      transaction_reference: null,
    },
  ];
  const calls: { url: string; body?: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, body: init?.body as string | undefined });
      if (url === "/api/chat/history")
        return response({
          messages: [],
          active: false,
          queries,
          active_query_id: first,
        });
      if (url === "/api/chat/messages")
        return response({
          reply: "Estado verificado.",
          queries,
          active_query_id: second,
        });
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const onSelectTransaction = vi.fn();
  render(
    <Assistant
      open
      status={{ available: true, sandbox_intake_available: false }}
      selected={charge}
      transactions={[charge]}
      onSelectTransaction={onSelectTransaction}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );
  const choice = await screen.findByRole("combobox", {
    name: "Consulta para continuar",
  });
  fireEvent.change(choice, { target: { value: second } });
  expect(onSelectTransaction).toHaveBeenCalledWith(null);
  const input = screen.getByRole("textbox", {
    name: "Mensaje para el asistente",
  });
  fireEvent.change(input, { target: { value: "sí" } });
  fireEvent.submit(input.closest("form")!);
  await screen.findByText("Estado verificado.");
  expect(
    JSON.parse(calls.find((call) => call.url === "/api/chat/messages")!.body!),
  ).toEqual({
    message: "sí",
    language: "es",
    query_scope_id: second,
  });
  expect(calls.some((call) => call.url.startsWith("/api/action/"))).toBe(false);
  expect(document.body.textContent).not.toContain(first);
  expect(document.body.textContent).not.toContain(second);
});

test("rapid Portuguese query switch submits its different charge reference", async () => {
  localStorage.setItem("flujo-bank-action-language", "pt");
  const first = "q_" + "a".repeat(32);
  const second = "q_" + "b".repeat(32);
  const otherCharge = {
    ...charge,
    reference: "txn_bbbbbbbbbbbbbbbbbbbbbbbb",
    merchant: "Outra loja",
  };
  const queries = [
    {
      query_id: first,
      label: "Compra no Mercado Central",
      transaction_reference: charge.reference,
    },
    {
      query_id: second,
      label: "Compra em outra loja",
      transaction_reference: otherCharge.reference,
    },
  ];
  const calls: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/chat/history")
        return response({
          messages: [],
          active: false,
          queries,
          active_query_id: first,
        });
      if (url === "/api/chat/messages") {
        calls.push(JSON.parse(init!.body as string));
        return response({
          reply: "Consulta concluída.",
          queries,
          active_query_id: second,
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const onSelectTransaction = vi.fn();
  render(
    <Assistant
      open
      status={{ available: true, sandbox_intake_available: false }}
      selected={charge}
      transactions={[charge, otherCharge]}
      onSelectTransaction={onSelectTransaction}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );
  const choice = await screen.findByRole("combobox", {
    name: "Consulta a continuar",
  });
  const message = screen.getByRole("textbox", {
    name: "Mensagem para o assistente",
  });
  fireEvent.change(message, { target: { value: "E esta compra?" } });
  act(() => {
    fireEvent.change(choice, { target: { value: second } });
    fireEvent.submit(message.closest("form")!);
  });
  await screen.findByText("Consulta concluída.");
  expect(onSelectTransaction).toHaveBeenCalledWith(otherCharge);
  expect(calls).toEqual([
    {
      message: "E esta compra?",
      language: "pt",
      transaction_reference: otherCharge.reference,
      query_scope_id: second,
    },
  ]);
});

test("mismatched stored query blocks a stale charge action before POST", async () => {
  const first = "q_" + "a".repeat(32);
  const second = "q_" + "b".repeat(32);
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method || "GET" });
      if (url === "/api/chat/history")
        return response({
          active: false,
          messages: [{ role: "assistant", text: "Consulta anterior" }],
          queries: [
            {
              query_id: first,
              label: "Cargo inicial",
              transaction_reference: charge.reference,
            },
            {
              query_id: second,
              label: "Consulta general",
              transaction_reference: null,
            },
          ],
          active_query_id: first,
        });
      if (url.startsWith("/api/action/status"))
        return response({ state: "none" });
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
  const choice = await screen.findByRole("combobox", {
    name: "Consulta para continuar",
  });
  const prepare = await screen.findByRole("button", {
    name: "Revisar recepción simulada",
  });
  act(() => {
    fireEvent.change(choice, { target: { value: second } });
    fireEvent.click(prepare);
  });
  expect(
    await screen.findByText(
      "Esta consulta corresponde a otro movimiento. Elige la consulta de este movimiento antes de continuar.",
    ),
  ).toBeTruthy();
  expect(
    calls.filter(
      ({ url, method }) => url.startsWith("/api/action/") && method === "POST",
    ),
  ).toHaveLength(0);
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
          ...preparedEvidence,
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
    name: /Confirmo la recepción simulada para Mercado Central/,
  });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "pt" } });

  await screen.findByRole("button", {
    name: /Confirmo o registro simulado para Mercado Central/,
  });
  const actionStatus = await screen.findByText(
    "Estado em português para este lançamento.",
  );
  expect(effectiveLanguage(actionStatus)).toBe("pt-BR");
  expect(actionStatus.getAttribute("role")).toBe("status");
  const consentButton = screen.getByRole("button", {
    name: /Confirmo o registro simulado para Mercado Central/,
  });
  expect(effectiveLanguage(consentButton)).toBe("pt-BR");
  const consentSummary = screen
    .getByText(/Solicitação pendente para este lançamento/)
    .closest('[role="status"]');
  expect(consentSummary).not.toBeNull();
  expect(effectiveLanguage(consentSummary!)).toBe("pt-BR");
  expect(
    effectiveLanguage(
      within(consentSummary as HTMLElement).getByText(charge.merchant!),
    ),
  ).toBe("");
  expect(
    effectiveLanguage(within(consentButton).getByText(charge.merchant!)),
  ).toBe("");
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
      name: /Confirmo o registro simulado para Mercado Central/,
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

test.each([
  [
    "es",
    "sí",
    "Confirmo la recepción simulada para",
    "Referencia del cargo",
    "septiembre",
  ],
  [
    "pt",
    "sim",
    "Confirmo o registro simulado para",
    "Referência do lançamento",
    "setembro",
  ],
])(
  "%s explicit consent names the saved charge and chat yes has no action authority",
  async (language, yes, consent, referenceLabel, month) => {
    localStorage.setItem("flujo-bank-action-language", language);
    const similarCharge = {
      ...charge,
      reference: "txn_cccccccccccccccccccccccc",
    };
    const calls: { url: string; method: string; body?: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const url = String(input);
        calls.push({
          url,
          method: init?.method || "GET",
          body: init?.body as string | undefined,
        });
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status"))
          return response({
            state: "pending_confirmation",
            ...preparedEvidence,
            pending_handle: "b".repeat(43),
            target_reference: charge.reference,
          });
        if (url === "/api/chat/messages")
          return response({ reply: "Consulta de solo lectura." });
        if (url === "/api/action/confirm")
          return response({
            state: "intake_verified",
            target_reference: charge.reference,
          });
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const props = {
      open: true,
      status: { available: true, sandbox_intake_available: true },
      selected: charge,
      transactions: [charge, similarCharge],
      onSelectTransaction: vi.fn(),
      hidden: false,
      synthetic: true,
      onClose: vi.fn(),
      onExpired: vi.fn(),
    };
    const view = render(<Assistant {...props} />);
    const confirm = await screen.findByRole("button", {
      name: new RegExp(consent),
    });
    expect(confirm.textContent).toContain(charge.merchant);
    expect(confirm.textContent).toContain(month);
    expect(confirm.textContent).toContain("COP");
    expect(confirm.textContent).toContain("42");
    expect(confirm.textContent).not.toContain(charge.reference);
    const summary = document.getElementById(
      confirm.getAttribute("aria-describedby")!,
    );
    expect(summary).not.toBeNull();
    expect(summary!.textContent).not.toContain(charge.reference);
    expect(summary!.textContent).toContain(month);
    expect(summary!.textContent).toContain("COP");
    expect(summary!.textContent).toContain("42");
    const technicalReference = screen.getByText(charge.reference);
    expect(technicalReference.closest("details")?.open).toBe(false);
    expect(within(confirm).queryByText(referenceLabel)).toBeNull();

    fireEvent.change(
      screen.getByRole("textbox", {
        name:
          language === "pt"
            ? "Mensagem para o assistente"
            : "Mensaje para el asistente",
      }),
      { target: { value: yes } },
    );
    fireEvent.submit(
      screen
        .getByRole("textbox", {
          name:
            language === "pt"
              ? "Mensagem para o assistente"
              : "Mensaje para el asistente",
        })
        .closest("form")!,
    );
    await screen.findByText("Consulta de solo lectura.");
    expect(
      calls.filter(
        ({ url, method }) =>
          url.startsWith("/api/action/") && method === "POST",
      ),
    ).toHaveLength(0);
    expect(
      JSON.parse(calls.find(({ url }) => url === "/api/chat/messages")!.body!),
    ).toEqual({
      message: yes,
      language,
      transaction_reference: charge.reference,
    });

    view.rerender(<Assistant {...props} selected={similarCharge} />);
    expect(
      screen.queryByRole("button", { name: new RegExp(consent) }),
    ).toBeNull();
    expect(screen.getByText(charge.reference)).toBeTruthy();
    expect(screen.queryByText(similarCharge.reference)).toBeNull();
    view.rerender(<Assistant {...props} />);
    fireEvent.click(screen.getByRole("button", { name: new RegExp(consent) }));
    await waitFor(() =>
      expect(
        calls.filter(({ url }) => url === "/api/action/confirm"),
      ).toHaveLength(1),
    );
    expect(
      JSON.parse(calls.find(({ url }) => url === "/api/action/confirm")!.body!),
    ).toEqual({
      pending_handle: "b".repeat(43),
      transaction_reference: charge.reference,
      confirmed: true,
      language,
    });
  },
);

test("hidden amount requires a local review before explicit consent", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url === "/api/chat/history")
        return response({
          active: false,
          messages: [{ role: "user", text: "Consulta previa" }],
        });
      if (url.startsWith("/api/action/status"))
        return response({
          state: "pending_confirmation",
          ...preparedEvidence,
          pending_handle: "b".repeat(43),
          target_reference: charge.reference,
        });
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
      hidden
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );
  const confirm = await screen.findByRole("button", {
    name: /Confirmo la recepción simulada/,
  });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Consultar estado de la solicitud",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  const summary = document.getElementById(
    confirm.getAttribute("aria-describedby")!,
  );
  expect(summary!.textContent).toContain("••••••");
  fireEvent.click(
    screen.getByRole("button", { name: "Mostrar monto para confirmar" }),
  );
  await waitFor(() => {
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
    expect(summary!.textContent).toContain("42");
    expect(summary!.textContent).not.toContain("••••••");
  });
  expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
});

test("amount review and confirmation wait for status recovery", async () => {
  const calls: string[] = [];
  const heldStatus: Array<(result: Response) => void> = [];
  let statusRequests = 0;
  const pending = {
    state: "pending_confirmation",
    ...preparedEvidence,
    pending_handle: "b".repeat(43),
    target_reference: charge.reference,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url === "/api/chat/history")
        return response({
          active: false,
          messages: [{ role: "user", text: "Consulta previa" }],
        });
      if (url.startsWith("/api/action/status")) {
        statusRequests += 1;
        if (statusRequests === 1) return response(pending);
        return new Promise<Response>((resolve) => heldStatus.push(resolve));
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
      hidden
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );
  const confirm = await screen.findByRole("button", {
    name: /Confirmo la recepción simulada/,
  });
  const status = screen.getByRole("button", {
    name: "Consultar estado de la solicitud",
  }) as HTMLButtonElement;
  await waitFor(() => expect(status.disabled).toBe(false));
  const summary = document.getElementById(
    confirm.getAttribute("aria-describedby")!,
  )!;
  const reveal = screen.getByRole("button", {
    name: "Mostrar monto para confirmar",
  }) as HTMLButtonElement;
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  expect(summary.textContent).toContain("••••••");

  fireEvent.click(status);
  await waitFor(() => expect(reveal.disabled).toBe(true));
  fireEvent.click(reveal);
  fireEvent.click(confirm);
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  expect(summary.textContent).toContain("••••••");
  expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
  await act(async () => heldStatus.shift()!(response(pending)));
  await waitFor(() => expect(status.disabled).toBe(false));

  fireEvent.click(reveal);
  await waitFor(() => {
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
    expect(summary.textContent).toContain("42");
    expect(summary.textContent).not.toContain("••••••");
  });

  fireEvent.click(status);
  await waitFor(() =>
    expect((confirm as HTMLButtonElement).disabled).toBe(true),
  );
  fireEvent.click(confirm);
  expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
  await act(async () => heldStatus.shift()!(response(pending)));
  await waitFor(() => expect(status.disabled).toBe(false));
  expect((confirm as HTMLButtonElement).disabled).toBe(false);
  expect(summary.textContent).toContain("42");
  expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
});

test.each([
  ["missing saved facts", { transaction: undefined }],
  ["missing saved snapshot", { snapshot: undefined }],
  ["changed amount", { transaction: { ...savedFacts, amount: "42.01" } }],
  [
    "changed event date",
    { transaction: { ...savedFacts, transaction_date: "2026-09-19" } },
  ],
  ["changed currency", { transaction: { ...savedFacts, currency: "USD" } }],
  [
    "wrong reference shape",
    { transaction: { ...savedFacts, transaction_reference: charge.reference } },
  ],
])(
  "%s prevents explicit confirmation of an unverified prepared charge",
  async (_name, override) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status"))
          return response({
            state: "pending_confirmation",
            pending_handle: "b".repeat(43),
            target_reference: charge.reference,
            ...preparedEvidence,
            ...override,
          });
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
    await screen.findByRole("alert");
    expect(
      screen.queryByRole("button", { name: /Confirmo la recepción simulada/ }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Revisar recepción simulada" }),
    ).toBeNull();
  },
);

test.each([
  [
    "es",
    "Preguntas para la revisión (opcional)",
    "Prefiero revisión humana",
    "¿Qué ocurrió con este cargo? ÁÉÍÓÚ 😊",
  ],
  [
    "pt",
    "Perguntas para a análise (opcional)",
    "Prefiro análise humana",
    "O que ocorreu com este lançamento? ÁÉÍÓÚ 😊",
  ],
])(
  "%s explicit human review after a saved intake lets the host prepare the existing case",
  async (language, questionsLabel, preferLabel, question) => {
    localStorage.setItem("flujo-bank-action-language", language);
    const writes: { url: string; body: Record<string, unknown> }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status"))
          return response({
            state: "intake_verified",
            target_reference: charge.reference,
            pending_handle: "b".repeat(43),
            request_id: "11111111-1111-4111-8111-111111111111",
            ...preparedEvidence,
            receipt,
          });
        if (url === "/api/action/handoff") {
          const body = JSON.parse(init!.body as string);
          writes.push({ url, body });
          return response({
            state: "handoff_verified",
            target_reference: charge.reference,
            handoff: {
              ...handoff,
              reason: "customer_request",
              unanswered_questions: body.unanswered_questions,
            },
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
    const input = await screen.findByRole("textbox", { name: questionsLabel });
    const prefer = screen.getByRole("button", {
      name: preferLabel,
    }) as HTMLButtonElement;
    for (const malformed of [
      "Pregunta\u0000",
      "Pregunta\u001b",
      "Pregunta\ud800",
      "Pregunta\tpendiente",
    ]) {
      fireEvent.change(input, { target: { value: malformed } });
      expect(prefer.disabled).toBe(true);
    }
    expect(writes).toHaveLength(0);
    fireEvent.change(input, { target: { value: ` ${question} ` } });
    expect(prefer.disabled).toBe(false);
    expect(screen.queryByRole("button", { name: /Confirmo/ })).toBeNull();
    fireEvent.click(prefer);
    const evidence = await screen.findByRole("region", {
      name:
        language === "pt" ? "Referência da análise" : "Referencia de revisión",
    });
    expect(writes).toEqual([
      {
        url: "/api/action/handoff",
        body: {
          reason: "customer_request",
          transaction_reference: charge.reference,
          unanswered_questions: [question],
          language,
        },
      },
    ]);
    expect(within(evidence).getByText(question)).toBeTruthy();
  },
);

test.each([
  ["es", "Comprobante local", "Recibido", "Revisar recepción simulada"],
  ["pt", "Comprovante local", "Recebido", "Revisar registro simulado"],
])(
  "%s existing case readback shows the local receipt and prevents another intake for the same charge",
  async (language, receiptLabel, received, reviewLabel) => {
    localStorage.setItem("flujo-bank-action-language", language);
    const calls: { url: string; method: string }[] = [];
    let reviewed = false;
    const result = {
      state: "existing_case_verified",
      receipt,
      pending_handle: "b".repeat(43),
      transaction: savedFacts,
      target_reference: charge.reference,
      snapshot: "fixture-current-view",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, method: init?.method || "GET" });
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "assistant", text: "Consulta anterior" }],
          });
        if (url.startsWith("/api/action/status"))
          return response(reviewed ? result : { state: "none" });
        if (url === "/api/action/prepare") {
          reviewed = true;
          return response(result);
        }
        if (url === "/api/action/handoff") {
          expect(JSON.parse(init!.body as string)).toEqual({
            reason: "customer_request",
            request_id: expect.any(String),
            pending_handle: "b".repeat(43),
            transaction_reference: charge.reference,
            unanswered_questions: [],
            language,
          });
          return response({
            state: "handoff_verified",
            target_reference: charge.reference,
            handoff: {
              ...handoff,
              reason: "customer_request",
              unanswered_questions: [],
            },
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const props = {
      open: true,
      status: { available: true, sandbox_intake_available: true },
      selected: charge,
      transactions: [
        charge,
        { ...charge, reference: "txn_cccccccccccccccccccccccc" },
      ],
      onSelectTransaction: vi.fn(),
      hidden: false,
      synthetic: true,
      onClose: vi.fn(),
      onExpired: vi.fn(),
    };
    const view = render(<Assistant {...props} />);
    fireEvent.click(await screen.findByRole("button", { name: reviewLabel }));
    const evidence = await screen.findByRole("region", { name: receiptLabel });
    expect(effectiveLanguage(evidence)).toBe(
      language === "pt" ? "pt-BR" : "es",
    );
    expect(
      effectiveLanguage(within(evidence).getByText(charge.merchant!)),
    ).toBe("");
    expect(within(evidence).getByText(receipt.id)).toBeTruthy();
    const receiptReference = within(evidence).getByText(charge.reference);
    expect(receiptReference.closest("details")?.open).toBe(false);
    expect(within(evidence).getByText(received)).toBeTruthy();
    expect(
      within(evidence).getByText("fixture-original").closest("details")?.open,
    ).toBe(false);
    expect(
      within(evidence).getByText("fixture-current-view").closest("details")
        ?.open,
    ).toBe(false);
    expect(evidence.textContent).toContain(
      language === "pt"
        ? "Não indica uma devolução"
        : "No indica una devolución",
    );
    expect(screen.queryByRole("button", { name: /Confirmo/ })).toBeNull();
    expect(screen.queryByRole("button", { name: reviewLabel })).toBeNull();
    expect(
      screen.getByRole("button", {
        name:
          language === "pt"
            ? "Prefiro análise humana"
            : "Prefiero revisión humana",
      }),
    ).toBeTruthy();
    expect(calls.filter(({ method }) => method === "POST")).toEqual([
      { url: "/api/action/prepare", method: "POST" },
    ]);
    view.rerender(<Assistant {...props} selected={props.transactions[1]} />);
    expect(screen.getByRole("button", { name: reviewLabel })).toBeTruthy();
    expect(
      within(evidence).getByText(charge.reference).closest("details")?.open,
    ).toBe(false);
    view.rerender(<Assistant {...props} />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          language === "pt"
            ? "Prefiro análise humana"
            : "Prefiero revisión humana",
      }),
    );
    const review = await screen.findByRole("region", {
      name:
        language === "pt" ? "Referência da análise" : "Referencia de revisión",
    });
    expect(within(review).getByText(handoff.id)).toBeTruthy();
    expect(calls.filter(({ method }) => method === "POST")).toEqual([
      { url: "/api/action/prepare", method: "POST" },
      { url: "/api/action/handoff", method: "POST" },
    ]);
    expect(calls.some(({ url }) => url === "/api/action/confirm")).toBe(false);
  },
);

test.each([
  [
    "es",
    false,
    "Referencia de revisión",
    "Solicitud de revisión guardada",
    "No hay respuesta humana registrada",
  ],
  [
    "pt",
    false,
    "Referência da análise",
    "Solicitação de análise salva",
    "Não há resposta humana registrada",
  ],
  [
    "es",
    true,
    "Referencia de revisión",
    "Solicitud de revisión guardada",
    "No hay respuesta humana registrada",
  ],
  [
    "pt",
    true,
    "Referência da análise",
    "Solicitação de análise salva",
    "Não há resposta humana registrada",
  ],
])(
  "%s saved handoff %s displays only verified packet facts, questions and no human response",
  async (language, nested, regionLabel, title, noHuman) => {
    localStorage.setItem("flujo-bank-action-language", language as string);
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const url = String(input);
        calls.push(`${init?.method || "GET"} ${url}`);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status"))
          return response({
            state: nested ? "action_unverified" : "handoff_verified",
            handoff: nested ? { state: "handoff_verified", handoff } : handoff,
            target_reference: charge.reference,
          });
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
    const evidence = await screen.findByRole("region", {
      name: regionLabel as string,
    });
    expect(within(evidence).getByText(title as string)).toBeTruthy();
    expect(
      within(evidence).getByText(handoff.id).closest("details")?.open,
    ).toBe(false);
    expect(
      within(evidence).getByText(charge.reference).closest("details")?.open,
    ).toBe(false);
    expect(
      within(evidence).getByText(handoff.unanswered_questions[0]),
    ).toBeTruthy();
    expect(
      within(evidence)
        .getByText(
          language === "pt"
            ? "Snapshot consultado em"
            : "Snapshot consultado el",
        )
        .closest("details")?.open,
    ).toBe(false);
    expect(evidence.textContent).toContain(
      language === "pt"
        ? "não atualiza os registros bancários"
        : "no actualiza los registros bancarios",
    );
    expect(evidence.textContent).toContain(noHuman as string);
    expect(evidence.textContent).toContain(
      language === "pt" ? "snapshot anterior" : "snapshot anterior",
    );
    expect(evidence.textContent).toContain(
      language === "pt" ? "setembro" : "septiembre",
    );
    expect(evidence.textContent).toContain("15:01:00 UTC");
    expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
  },
);

test.each<[string, Record<string, unknown>]>([
  ["unverified outer state", { state: "handoff_unverified", handoff }],
  [
    "human response claimed",
    {
      state: "handoff_verified",
      handoff: { ...handoff, human_responded: true },
    },
  ],
  [
    "mismatched provenance",
    {
      state: "handoff_verified",
      handoff: {
        ...handoff,
        transaction_provenance: {
          ...handoff.transaction_provenance,
          snapshot: "another-snapshot",
        },
      },
    },
  ],
  [
    "missing packet questions",
    {
      state: "handoff_verified",
      handoff: { ...handoff, unanswered_questions: undefined },
    },
  ],
  [
    "oversized questions",
    {
      state: "handoff_verified",
      handoff: { ...handoff, unanswered_questions: Array(9).fill("Question") },
    },
  ],
  ...[
    "Pregunta\u0000",
    "Pregunta\u001b",
    "Pregunta\ud800",
    "Pregunta\r\npendiente",
    " Pregunta",
  ].map((question): [string, Record<string, unknown>] => [
    "noncanonical or control-bearing saved question",
    {
      state: "handoff_verified",
      handoff: { ...handoff, unanswered_questions: [question] },
    },
  ]),
])("%s cannot surface a handoff packet as verified", async (_name, result) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = String(input);
      if (url === "/api/chat/history")
        return response({
          active: false,
          messages: [{ role: "user", text: "Consulta previa" }],
        });
      if (url.startsWith("/api/action/status"))
        return response({ ...result, target_reference: charge.reference });
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
  await screen.findByRole("button", {
    name: "Consultar estado de la solicitud",
  });
  expect(
    screen.queryByRole("region", { name: "Referencia de revisión" }),
  ).toBeNull();
  expect(screen.queryByText(handoff.id)).toBeNull();
});

test.each([
  ["wrong receipt status", { ...receipt, status: "resolved" }],
  ["not simulated", { ...receipt, simulated: false }],
  ["missing original snapshot", { ...receipt, snapshot: undefined }],
])(
  "%s leaves an existing case unverified and locked",
  async (_name, malformedReceipt) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status"))
          return response({
            state: "existing_case_verified",
            receipt: malformedReceipt,
            pending_handle: "b".repeat(43),
            target_reference: charge.reference,
            ...preparedEvidence,
          });
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
    await screen.findByRole("button", {
      name: "Consultar estado de la solicitud",
    });
    expect(
      screen.queryByRole("region", { name: "Comprobante local" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirmo/ })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Revisar recepción simulada" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Prefiero revisión humana" }),
    ).toBeNull();
  },
);

test.each([
  ["es", "Referencia de revisión", "123,456,789,012,345,678.25 COP"],
  ["pt", "Referência da análise", "123.456.789.012.345.678,25 COP"],
])(
  "%s saved handoff keeps exact decimal precision in displayed facts",
  async (language, regionLabel, expectedAmount) => {
    localStorage.setItem("flujo-bank-action-language", language);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status"))
          return response({
            state: "handoff_verified",
            target_reference: charge.reference,
            handoff: {
              ...handoff,
              facts: { ...savedFacts, amount: "123456789012345678.25" },
            },
          });
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
    const evidence = await screen.findByRole("region", { name: regionLabel });
    expect(within(evidence).getByText(expectedAmount)).toBeTruthy();
  },
);

test.each([
  [
    "es",
    "Preguntas para la revisión (opcional)",
    "Prefiero revisión humana",
    "Verificar revisión humana pendiente",
    "¿Qué pasó con este cargo?",
  ],
  [
    "pt",
    "Perguntas para a análise (opcional)",
    "Prefiro análise humana",
    "Verificar análise humana pendente",
    "O que aconteceu com este lançamento?",
  ],
])(
  "%s explicit handoff freezes questions and charge binding across retry",
  async (language, questionsLabel, preferLabel, retryLabel, question) => {
    localStorage.setItem("flujo-bank-action-language", language);
    const similarCharge = {
      ...charge,
      reference: "txn_cccccccccccccccccccccccc",
    };
    const requestId = "00000000-0000-4000-8000-000000000001";
    const writes: Record<string, unknown>[] = [];
    const saved = {
      state: "pending_confirmation",
      pending_handle: "b".repeat(43),
      request_id: requestId,
      target_reference: charge.reference,
      ...preparedEvidence,
    };
    let savedQuestions: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status")) return response(saved);
        if (url === "/api/action/handoff") {
          const body = JSON.parse(init!.body as string);
          writes.push(body);
          if (writes.length === 1) {
            savedQuestions = body.unanswered_questions;
            return response({
              ...saved,
              state: "handoff_unverified",
              reason: "customer_request",
            });
          }
          return response({
            state: "handoff_verified",
            target_reference: charge.reference,
            handoff: {
              ...handoff,
              reason: "customer_request",
              unanswered_questions: savedQuestions,
            },
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const props = {
      open: true,
      status: { available: true, sandbox_intake_available: true },
      selected: charge,
      transactions: [charge, similarCharge],
      onSelectTransaction: vi.fn(),
      hidden: true,
      synthetic: true,
      onClose: vi.fn(),
      onExpired: vi.fn(),
    };
    const view = render(<Assistant {...props} />);
    const questionDraft = await screen.findByRole("textbox", {
      name: questionsLabel,
    });
    expect(effectiveLanguage(questionDraft)).toBe("");
    fireEvent.change(questionDraft, {
      target: { value: ` ${question} \nSegunda pergunta?` },
    });
    const prefer = screen.getByRole("button", { name: preferLabel });
    expect((prefer as HTMLButtonElement).disabled).toBe(false);
    expect(writes).toHaveLength(0);
    fireEvent.click(prefer);
    await screen.findByRole("button", { name: retryLabel });
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({
      pending_handle: "b".repeat(43),
      transaction_reference: charge.reference,
      request_id: requestId,
      reason: "customer_request",
      unanswered_questions: [question, "Segunda pergunta?"],
      language,
    });
    expect(screen.queryByRole("textbox", { name: questionsLabel })).toBeNull();
    expect(screen.queryByText(question)).toBeNull();

    view.rerender(<Assistant {...props} selected={similarCharge} />);
    expect(screen.queryByRole("button", { name: retryLabel })).toBeNull();
    expect(screen.queryByRole("button", { name: preferLabel })).toBeNull();
    expect(screen.queryByRole("textbox", { name: questionsLabel })).toBeNull();
    expect(screen.getByText(charge.reference)).toBeTruthy();
    view.rerender(<Assistant {...props} />);
    fireEvent.click(screen.getByRole("button", { name: retryLabel }));
    const evidence = await screen.findByRole("region", {
      name:
        language === "pt" ? "Referência da análise" : "Referencia de revisión",
    });
    expect(effectiveLanguage(evidence)).toBe(
      language === "pt" ? "pt-BR" : "es",
    );
    expect(effectiveLanguage(within(evidence).getByText(question))).toBe("");
    expect(within(evidence).getByText(handoff.id)).toBeTruthy();
    expect(writes).toHaveLength(2);
    expect(writes[1]).toEqual({
      pending_handle: "b".repeat(43),
      transaction_reference: charge.reference,
      request_id: requestId,
      reason: "customer_request",
      language,
    });
  },
);

test("question limits prevent malformed explicit handoff without submitting", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url === "/api/chat/history")
        return response({
          active: false,
          messages: [{ role: "user", text: "Consulta previa" }],
        });
      if (url.startsWith("/api/action/status"))
        return response({
          state: "pending_confirmation",
          pending_handle: "b".repeat(43),
          target_reference: charge.reference,
          ...preparedEvidence,
        });
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
  const input = await screen.findByRole("textbox", {
    name: "Preguntas para la revisión (opcional)",
  });
  const prefer = screen.getByRole("button", {
    name: "Prefiero revisión humana",
  }) as HTMLButtonElement;
  fireEvent.change(input, {
    target: { value: Array(9).fill("Pregunta").join("\n") },
  });
  expect(prefer.disabled).toBe(true);
  fireEvent.change(input, { target: { value: "q".repeat(241) } });
  expect(prefer.disabled).toBe(true);
  fireEvent.change(input, { target: { value: "q".repeat(240) } });
  expect(prefer.disabled).toBe(false);
  fireEvent.change(input, { target: { value: "😊".repeat(240) } });
  expect(prefer.disabled).toBe(false);
  fireEvent.change(input, { target: { value: "😊".repeat(241) } });
  expect(prefer.disabled).toBe(true);
  expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
});

test.each(["es", "pt"])(
  "%s retained previous receipt survives an uncertain follow-up without consent authority or relabeling",
  async (language) => {
    localStorage.setItem("flujo-bank-action-language", language);
    const otherCharge = {
      ...charge,
      reference: "txn_cccccccccccccccccccccccc",
      merchant: "Otro comercio",
    };
    const writes: Record<string, unknown>[] = [];
    let saved: ActionResult = {
      state: "intake_verified",
      target_reference: charge.reference,
      pending_handle: "b".repeat(43),
      receipt,
      ...preparedEvidence,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status")) return response(saved);
        if (url === "/api/action/handoff") {
          writes.push(JSON.parse(init!.body as string));
          saved = {
            state: "prepare_unverified",
            target_reference: charge.reference,
            request_id: "22222222-2222-4222-8222-222222222222",
            prior_receipt: { target_reference: charge.reference, receipt },
          };
          return response(saved);
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const props = {
      open: true,
      status: { available: true, sandbox_intake_available: true },
      selected: charge,
      transactions: [charge, otherCharge],
      onSelectTransaction: vi.fn(),
      hidden: false,
      synthetic: true,
      onClose: vi.fn(),
      onExpired: vi.fn(),
    };
    let view = render(<Assistant {...props} />);
    fireEvent.click(
      await screen.findByRole("button", {
        name:
          language === "pt"
            ? "Prefiro análise humana"
            : "Prefiero revisión humana",
      }),
    );
    const previousLabel =
      language === "pt"
        ? "Comprovante local anterior"
        : "Comprobante local anterior";
    const previous = await screen.findByRole("region", { name: previousLabel });
    expect(within(previous).getByText(receipt.id)).toBeTruthy();
    expect(within(previous).getByText(charge.reference)).toBeTruthy();
    expect(within(previous).getByText(receipt.snapshot)).toBeTruthy();
    expect(within(previous).getByText(charge.merchant!)).toBeTruthy();
    expect(previous.textContent).toContain(
      language === "pt"
        ? "Registro simulado anterior verificado"
        : "Recepción simulada anterior verificada",
    );
    expect(previous.textContent).toContain(
      language === "pt"
        ? "Não confirma o resultado"
        : "No confirma el resultado",
    );
    expect(previous.textContent).toContain(
      language === "pt" ? "setembro" : "septiembre",
    );
    expect(screen.queryByRole("button", { name: /Confirmo/ })).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: /Revisar (recepción|registro) simulad/,
      }),
    ).toBeNull();
    view.rerender(<Assistant {...props} selected={otherCharge} />);
    expect(screen.queryByRole("region", { name: previousLabel })).toBeNull();
    expect(screen.queryByText(receipt.id)).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirmo/ })).toBeNull();
    view.rerender(<Assistant {...props} />);
    expect(
      screen.getByRole("region", { name: previousLabel }).textContent,
    ).not.toContain(otherCharge.reference);
    view.unmount();
    view = render(<Assistant {...props} />);
    expect(
      within(
        await screen.findByRole("region", { name: previousLabel }),
      ).getByText(receipt.id),
    ).toBeTruthy();
    const nextLanguage = language === "pt" ? "es" : "pt";
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: nextLanguage },
    });
    expect(
      within(
        await screen.findByRole("region", {
          name:
            nextLanguage === "pt"
              ? "Comprovante local anterior"
              : "Comprobante local anterior",
        }),
      ).getByText(receipt.id),
    ).toBeTruthy();
    expect(writes).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Confirmo/ })).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: /Revisar (recepción|registro) simulad/,
      }),
    ).toBeNull();
  },
);

test.each(["es", "pt"])(
  "%s terminal general handoff reload and language change create a fresh request UUID and preserve prior evidence through retry",
  async (language) => {
    localStorage.setItem("flujo-bank-action-language", language);
    const completedId = "11111111-1111-4111-8111-111111111111";
    const writes: Record<string, unknown>[] = [];
    const newQuestion = "¿Cuál es el próximo paso? ÁÉ 😊";
    let saved: ActionResult = {
      state: "handoff_verified",
      request_id: completedId,
      reason: "customer_request",
      handoff: generalHandoff,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status")) return response(saved);
        if (url === "/api/action/handoff") {
          const body = JSON.parse(init!.body as string);
          writes.push(body);
          if (writes.length === 1) {
            saved = {
              state: "handoff_unverified",
              request_id: body.request_id,
              reason: "customer_request",
              prior_handoff: {
                target_reference: null,
                handoff: generalHandoff,
              },
            };
          } else {
            saved = {
              state: "handoff_verified",
              request_id: body.request_id,
              reason: "customer_request",
              handoff: {
                ...generalHandoff,
                id: "HOF-ijklmnop",
                unanswered_questions: [newQuestion],
              },
            };
          }
          return response(saved);
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const props = {
      open: true,
      status: { available: true, sandbox_intake_available: true },
      selected: null,
      transactions: [charge],
      onSelectTransaction: vi.fn(),
      hidden: false,
      synthetic: true,
      onClose: vi.fn(),
      onExpired: vi.fn(),
    };
    let view = render(<Assistant {...props} />);
    await screen.findByText(generalHandoff.id);
    const nextLanguage = language === "pt" ? "es" : "pt";
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: nextLanguage },
    });
    const prefer = await screen.findByRole("button", {
      name:
        nextLanguage === "pt"
          ? "Prefiro análise humana"
          : "Prefiero revisión humana",
    });
    await waitFor(() =>
      expect((prefer as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.change(
      screen.getByRole("textbox", {
        name:
          nextLanguage === "pt"
            ? "Perguntas para a análise (opcional)"
            : "Preguntas para la revisión (opcional)",
      }),
      { target: { value: newQuestion } },
    );
    expect(writes).toHaveLength(0);
    fireEvent.click(prefer);
    const previousLabel =
      nextLanguage === "pt"
        ? "Referência da análise anterior"
        : "Referencia de revisión anterior";
    const previous = await screen.findByRole("region", { name: previousLabel });
    expect(writes[0].request_id).not.toBe(completedId);
    expect(writes[0]).toEqual({
      request_id: expect.any(String),
      reason: "customer_request",
      unanswered_questions: [newQuestion],
      language: nextLanguage,
    });
    expect(within(previous).getByText(generalHandoff.id)).toBeTruthy();
    expect(
      within(previous).getByText(generalHandoff.unanswered_questions[0]),
    ).toBeTruthy();
    expect(within(previous).queryByText(newQuestion)).toBeNull();
    expect(
      screen.queryByRole("textbox", { name: /Preguntas para|Perguntas para/ }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirmo/ })).toBeNull();
    view.unmount();
    view = render(<Assistant {...props} />);
    await screen.findByRole("region", { name: previousLabel });
    fireEvent.click(
      await screen.findByRole("button", {
        name:
          nextLanguage === "pt"
            ? "Verificar análise humana pendente"
            : "Verificar revisión humana pendiente",
      }),
    );
    await screen.findByText("HOF-ijklmnop");
    expect(writes).toHaveLength(2);
    expect(writes[1]).toEqual({
      request_id: writes[0].request_id,
      reason: "customer_request",
      language: nextLanguage,
    });
  },
);

test.each([
  { target_reference: "txn_cccccccccccccccccccccccc", receipt },
  {
    target_reference: charge.reference,
    receipt: { ...receipt, status: "resolved" },
  },
  {
    target_reference: charge.reference,
    receipt: { ...receipt, simulated: false },
  },
])(
  "mismatched or malformed retained receipt stays hidden and supplies no authority",
  async (prior_receipt) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status"))
          return response({
            state: "prepare_unverified",
            target_reference: charge.reference,
            prior_receipt,
          });
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
    await screen.findByRole("button", {
      name: "Consultar estado de la solicitud",
    });
    expect(screen.queryByText(receipt.id)).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirmo/ })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Revisar recepción simulada" }),
    ).toBeNull();
  },
);

test.each([
  { target_reference: charge.reference, handoff: generalHandoff },
  { target_reference: null, handoff },
])("a nongeneral retained handoff stays hidden", async (prior_handoff) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = String(input);
      if (url === "/api/chat/history")
        return response({
          active: false,
          messages: [{ role: "user", text: "Consulta previa" }],
        });
      if (url.startsWith("/api/action/status"))
        return response({
          state: "handoff_unverified",
          request_id: "22222222-2222-4222-8222-222222222222",
          reason: "customer_request",
          prior_handoff,
        });
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  render(
    <Assistant
      open
      status={{ available: true, sandbox_intake_available: true }}
      selected={null}
      transactions={[charge]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );
  await screen.findByRole("button", {
    name: "Verificar revisión humana pendiente",
  });
  expect(screen.queryByText(handoff.id)).toBeNull();
  expect(
    screen.queryByRole("region", { name: "Referencia de revisión anterior" }),
  ).toBeNull();
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

test("Portuguese is selectable before history loads and stays available when chat is unavailable", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const props = {
    open: true,
    status: { available: false, sandbox_intake_available: false },
    selected: null,
    transactions: [],
    onSelectTransaction: vi.fn(),
    hidden: false,
    synthetic: true,
    onClose: vi.fn(),
    onExpired: vi.fn(),
  };
  render(<Assistant {...props} />);
  fireEvent.change(
    screen.getByRole("combobox", { name: "Idioma de la interfaz" }),
    {
      target: { value: "pt" },
    },
  );
  const dialog = screen.getByRole("dialog", { name: "Seu assistente Savia" });
  expect(within(dialog).getByRole("button", { name: "Fechar" })).toBeTruthy();
  expect(
    screen.getByRole("combobox", { name: "Idioma da interface" }),
  ).toBeTruthy();
  expect(
    screen.getByText("O assistente não está disponível agora"),
  ).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "Vamos entender seus lançamentos." }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Mostre meus lançamentos recentes" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(dialog.querySelector("h2")?.getAttribute("lang")).toBe("pt-BR");
  expect(
    screen
      .getByRole("textbox", { name: "Mensagem para o assistente" })
      .getAttribute("lang"),
  ).toBe("pt-BR");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("Portuguese recovery copy permits retry while server transcript remains unlabelled", async () => {
  let historyAttempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      if (String(input) !== "/api/chat/history")
        throw new Error(`Unexpected request: ${input}`);
      historyAttempts += 1;
      if (historyAttempts === 1) throw new Error("temporary failure");
      return response({
        active: false,
        messages: [
          { role: "assistant", text: "Respuesta guardada en español" },
        ],
      });
    }),
  );
  render(
    <Assistant
      open={true}
      status={{ available: true, sandbox_intake_available: false }}
      selected={null}
      transactions={[]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic={true}
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );
  await screen.findByRole("button", { name: "Recuperar conversación" });
  fireEvent.change(
    screen.getByRole("combobox", { name: "Idioma de la interfaz" }),
    { target: { value: "pt" } },
  );
  const retry = screen.getByRole("button", { name: "Recuperar conversa" });
  expect(screen.getByRole("alert").textContent).toContain(
    "Não foi possível recuperar sua conversa",
  );
  fireEvent.click(retry);
  const transcript = await screen.findByText("Respuesta guardada en español");
  expect(transcript.closest(".chat-message")?.getAttribute("lang")).toBeNull();
  expect(
    screen.getByRole("dialog", { name: "Seu assistente Savia" }),
  ).toBeTruthy();
  expect(historyAttempts).toBe(2);
});

test("Portuguese selection before the first chat avoids unbound action status and logs no customer out", async () => {
  const statusReads: string[] = [];
  const sentMessages: Record<string, unknown>[] = [];
  const onExpired = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/chat/history")
        return response({ active: false, messages: [] });
      if (url.startsWith("/api/action/status?language=")) {
        statusReads.push(url);
        if (url === "/api/action/status?language=pt")
          return response({ state: "none" });
        else
          return {
            ok: false,
            status: 401,
            headers: { get: () => null },
            json: async () => ({ detail: "No admitted action row" }),
          } as unknown as Response;
      }
      if (url === "/api/chat/messages") {
        sentMessages.push(JSON.parse(init!.body as string));
        return response({ reply: "Este lançamento aparece como aprovado." });
      }
      if (url.startsWith("/api/followups?")) return response({ items: [] });
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
      onExpired={onExpired}
    />,
  );

  await screen.findByRole("textbox", { name: "Mensaje para el asistente" });
  expect(statusReads).toEqual([]);
  fireEvent.change(
    screen.getByRole("combobox", { name: "Idioma de la interfaz" }),
    { target: { value: "pt" } },
  );
  await screen.findByRole("textbox", { name: "Mensagem para o assistente" });
  expect(statusReads).toEqual([]);
  expect(onExpired).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "Revisar registro simulado" }),
  ).toBeNull();
  fireEvent.change(
    screen.getByRole("textbox", { name: "Mensagem para o assistente" }),
    { target: { value: "O que significa este lançamento?" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Enviar mensagem" }));

  await screen.findByText("Este lançamento aparece como aprovado.");
  expect(
    await screen.findByRole("button", { name: "Revisar registro simulado" }),
  ).toBeTruthy();
  expect(statusReads).toEqual(["/api/action/status?language=pt"]);
  expect(onExpired).not.toHaveBeenCalled();
  expect(sentMessages).toEqual([
    {
      message: "O que significa este lançamento?",
      language: "pt",
      transaction_reference: charge.reference,
    },
  ]);
});

test.each([
  {
    language: "es" as const,
    optIn: "Quiero recibir seguimiento de esta recepción",
    last: "Última consulta",
    check: "Consultar ahora",
    state: "Programado",
  },
  {
    language: "pt" as const,
    optIn: "Quero receber acompanhamento deste registro",
    last: "Última consulta",
    check: "Consultar agora",
    state: "Agendado",
  },
])(
  "$language customers can opt into and inspect simulated follow-up",
  async (copy) => {
    vi.stubEnv("TZ", "America/Bogota");
    const saved: Record<string, unknown>[] = [];
    let enrolled = false;
    const followup = {
      id: "fup-internal-id",
      target_reference: charge.reference,
      receipt_id: receipt.id,
      simulated: true,
      state: "scheduled",
      created_at: "2026-09-21T15:02:00Z",
      last_checked_at: 1790000000000,
      next_check_at: 1790000900000,
      message: "El seguimiento está programado.",
      next_step: "Consulta el resultado más tarde.",
      updates: [
        {
          checked_at: 1790000000000,
          state: "scheduled",
          message: "Se guardó el seguimiento simulado.",
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/chat/history")
          return response({
            active: false,
            messages: [{ role: "user", text: "Consulta previa" }],
          });
        if (url.startsWith("/api/action/status"))
          return response({
            state: "intake_verified",
            target_reference: charge.reference,
            receipt,
          });
        if (url.startsWith("/api/followups?"))
          return response({ items: enrolled ? [followup] : [] });
        if (url === "/api/followups" && init?.method === "POST") {
          saved.push(JSON.parse(init.body as string));
          enrolled = true;
          return response({ item: followup });
        }
        if (url === "/api/followups/check" && init?.method === "POST") {
          saved.push(JSON.parse(init.body as string));
          return response({ checked: 1 });
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
        initialLanguage={copy.language}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: copy.optIn }));
    const state = await screen.findByText(copy.state);
    const item = state.closest(".followup-item") as HTMLElement;
    expect(
      within(item).getByText("El seguimiento está programado."),
    ).toBeTruthy();
    expect(
      within(item).getAllByText("El seguimiento está programado."),
    ).toHaveLength(1);
    expect(
      within(item).getByText("Consulta el resultado más tarde."),
    ).toBeTruthy();
    expect(within(item).getByText(copy.last)).toBeTruthy();
    expect(within(item).getByText("Próxima consulta")).toBeTruthy();
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe(
      "America/Bogota",
    );
    const localCheckTime = new Intl.DateTimeFormat(
      copy.language === "pt" ? "pt-BR" : "es-MX",
      {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZoneName: "short",
        hourCycle: "h23",
      },
    ).format(new Date(1790000000000));
    expect(within(item).getByText(localCheckTime)).toBeTruthy();
    expect(document.body.textContent).not.toContain("fup-internal-id");
    expect(saved[0]).toEqual({ language: copy.language });

    fireEvent.click(screen.getByRole("button", { name: copy.check }));
    await waitFor(() => expect(saved).toHaveLength(2));
    expect(saved[1]).toEqual({ language: copy.language });
    expect(screen.queryByRole("button", { name: copy.optIn })).toBeNull();
  },
);

test("saved follow-up remains reachable without the current receipt and follows conversation", async () => {
  const priorFollowup = {
    id: "followup-prior-id",
    target_reference: "txn_bbbbbbbbbbbbbbbbbbbbbbbb",
    receipt_id: "CMP-SBX-ijklmnop",
    simulated: true as const,
    state: "checked" as const,
    created_at: "2026-09-21T15:02:00Z",
    last_checked_at: 1790000000000,
    next_check_at: null,
    message: "La consulta anterior sigue guardada.",
    next_step: "Revisa esta actualización cuando quieras.",
    updates: [
      {
        checked_at: 1790000000000,
        state: "checked",
        message: "La consulta anterior sigue guardada.",
      },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/chat/history")
        return response({
          active: false,
          messages: [{ role: "assistant", text: "¿En qué te ayudo ahora?" }],
        });
      if (url.startsWith("/api/action/status"))
        return response({ state: "none" });
      if (url.startsWith("/api/followups?"))
        return response({ items: [priorFollowup] });
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const view = render(
    <Assistant
      open
      status={{ available: true, sandbox_intake_available: true }}
      selected={null}
      transactions={[]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );

  await screen.findByText("¿En qué te ayudo ahora?");
  const followup = await screen.findByText(
    "La consulta anterior sigue guardada.",
  );
  const item = followup.closest(".followup-item") as HTMLElement;
  expect(within(item).getByText("CMP-SBX-ijklmnop")).toBeTruthy();
  expect(
    within(item).getByText("Revisa esta actualización cuando quieras."),
  ).toBeTruthy();
  expect(
    within(item).getAllByText("La consulta anterior sigue guardada."),
  ).toHaveLength(1);
  expect(
    screen.queryByRole("button", {
      name: "Quiero recibir seguimiento de esta recepción",
    }),
  ).toBeNull();
  const chat = view.container.querySelector(".chat-messages")!;
  const panel = view.container.querySelector(".followup-panel")!;
  expect(
    chat.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

test("new chat archives visible history per profile, survives reload and keeps follow-ups", async () => {
  voiceHarness.active = true;
  const priorFollowup = {
    id: "followup-archived-test",
    target_reference: charge.reference,
    receipt_id: "CMP-SBX-archive1",
    simulated: true as const,
    state: "scheduled" as const,
    created_at: "2026-09-21T15:02:00Z",
    last_checked_at: null,
    next_check_at: null,
    message: "El seguimiento sigue guardado.",
    next_step: "Te avisaremos cuando haya una actualización.",
    updates: [],
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/chat/history")
      return response({
        active: false,
        messages: [
          { role: "user", text: "No reconozco este cargo" },
          { role: "assistant", text: "Revisemos la información disponible." },
        ],
      });
    if (url.startsWith("/api/action/status"))
      return response({ state: "none" });
    if (url.startsWith("/api/followups?"))
      return response({ items: [priorFollowup] });
    if (url.startsWith("/api/assistant/cases?")) return response({ items: [] });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  const onSelectTransaction = vi.fn();
  const props = {
    open: true,
    status: { available: true, sandbox_intake_available: true },
    selected: charge,
    transactions: [charge],
    onSelectTransaction,
    hidden: false,
    synthetic: true,
    onClose: vi.fn(),
    onExpired: vi.fn(),
    profileId: "profile-archive-test",
  };

  const first = render(<Assistant {...props} />);
  await screen.findByText("Revisemos la información disponible.");
  await screen.findByText("El seguimiento sigue guardado.");
  fireEvent.click(screen.getByRole("button", { name: "Empezar chat nuevo" }));
  expect(voiceHarness.stop).toHaveBeenCalled();
  expect(screen.queryByText("No reconozco este cargo")).toBeNull();
  expect(screen.queryByText("Revisemos la información disponible.")).toBeNull();
  expect(onSelectTransaction).toHaveBeenCalledWith(null);
  await screen.findByText("El seguimiento sigue guardado.");
  expect(
    screen.getByRole("button", { name: "Ver conversación anterior" }),
  ).toBeTruthy();
  await waitFor(() =>
    expect(
      localStorage.getItem("savia-chat-archive:profile-archive-test"),
    ).toBe("2"),
  );
  first.unmount();

  render(<Assistant {...props} />);
  await screen.findByText("Vamos a entender tus movimientos.");
  expect(screen.queryByText("No reconozco este cargo")).toBeNull();
  await screen.findByText("El seguimiento sigue guardado.");
  fireEvent.click(
    screen.getByRole("button", { name: "Ver conversación anterior" }),
  );
  expect(screen.getByText("No reconozco este cargo")).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Volver al chat actual" }),
  ).toBeTruthy();
});

test("voice stage shows heard/caption turns and stops when the Assistant closes", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/chat/history")
      return response({ active: false, messages: [] });
    if (url.startsWith("/api/followups?")) return response({ items: [] });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  const props = {
    open: true,
    status: {
      available: true,
      sandbox_intake_available: false,
      voice: { available: true, conversation: true, persona: "moss" as const },
    },
    selected: null,
    transactions: [],
    onSelectTransaction: vi.fn(),
    hidden: false,
    synthetic: true,
    onClose: vi.fn(),
    onExpired: vi.fn(),
  };
  const view = render(<Assistant {...props} />);
  await screen.findByText("Vamos a entender tus movimientos.");
  expect(view.container.querySelector(".assistant-eyes")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Hablar con Savia" }));
  expect(voiceHarness.start).toHaveBeenCalledOnce();
  voiceHarness.options?.onHeard?.(
    "heard-turn",
    "No reconozco este cargo",
    true,
  );
  voiceHarness.options?.onCaption?.("voice-turn", "Revisémoslo juntos", false);
  await screen.findByText("Revisémoslo juntos");
  expect(screen.getByText("Moss")).toBeTruthy();
  expect(
    screen
      .getByText("Revisémoslo juntos")
      .closest(".chat-message")
      ?.getAttribute("aria-busy"),
  ).toBe("true");
  voiceHarness.options?.onCaption?.("voice-turn", "", true);
  await waitFor(() =>
    expect(screen.queryByText("Revisémoslo juntos")).toBeNull(),
  );

  view.rerender(<Assistant {...props} open={false} />);
  await waitFor(() => expect(voiceHarness.stop).toHaveBeenCalled());
});

test("spoken chat and authenticated completed team updates narrate their canonical replies", async () => {
  voiceHarness.active = true;
  voiceHarness.owner = Symbol("voice-session");
  const exactChatReply =
    "El movimiento figura aprobado en el registro disponible.";
  const exactTeamReply = "El equipo confirmó que hay una respuesta disponible.";
  const caseId = `i_${"c".repeat(32)}`;
  const calls: string[] = [];
  const pendingUpdates: ((response: Response) => void)[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url === "/api/chat/history")
        return response({ active: false, messages: [] });
      if (url === "/api/chat/messages")
        return response({ reply: exactChatReply });
      if (url.startsWith("/api/followups?")) return response({ items: [] });
      if (url.startsWith("/api/assistant/voice-update?")) {
        expect(url).toContain(`case_id=${caseId}`);
        expect(url).toContain(
          `after_event_id=${pendingUpdates.length ? 101 : 0}`,
        );
        expect(url).toContain("language=es");
        return new Promise<Response>((resolve) => pendingUpdates.push(resolve));
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const view = render(
    <Assistant
      open
      status={{
        available: true,
        sandbox_intake_available: false,
        voice: { available: true, conversation: true, persona: "moss" },
      }}
      selected={null}
      transactions={[]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
      profileId="voice-update-profile"
    />,
  );

  act(() => inquiryHarness.props?.onVoiceUpdate?.(caseId, 101));
  await waitFor(() => expect(pendingUpdates).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: "Terminar voz" }));
  voiceHarness.active = false;
  voiceHarness.owner = null;
  view.rerender(
    <Assistant
      open
      status={{
        available: true,
        sandbox_intake_available: false,
        voice: { available: true, conversation: true, persona: "moss" },
      }}
      selected={null}
      transactions={[]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
      profileId="voice-update-profile"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Hablar con Savia" }));
  voiceHarness.active = true;
  const restartedOwner = Symbol("restarted-voice-session");
  voiceHarness.owner = restartedOwner;
  view.rerender(
    <Assistant
      open
      status={{
        available: true,
        sandbox_intake_available: false,
        voice: { available: true, conversation: true, persona: "moss" },
      }}
      selected={null}
      transactions={[]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
      profileId="voice-update-profile"
    />,
  );
  act(() => inquiryHarness.props?.onVoiceUpdate?.(caseId, 102));
  await waitFor(() => expect(pendingUpdates).toHaveLength(2));
  await act(async () => {
    pendingUpdates[0](
      response({
        reply: "Stale update from the prior voice session.",
        event_id: 101,
        inquiry_state: "team_completed",
        bank_authority: false,
      }),
    );
    await Promise.resolve();
  });
  await act(async () => {
    pendingUpdates[1](
      response({
        reply: exactTeamReply,
        event_id: 102,
        inquiry_state: "team_completed",
        bank_authority: false,
      }),
    );
    await Promise.resolve();
  });
  await waitFor(() =>
    expect(voiceHarness.narrate).toHaveBeenCalledWith(
      exactTeamReply,
      restartedOwner,
    ),
  );
  expect(voiceHarness.narrate).not.toHaveBeenCalledWith(
    "Stale update from the prior voice session.",
  );
  expect(voiceHarness.narrate).toHaveBeenCalledTimes(1);
  fireEvent.change(
    screen.getByRole("textbox", { name: "Mensaje para el asistente" }),
    { target: { value: "¿Qué significa el estado?" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Enviar mensaje" }));
  const assistantReply = await screen.findByText(exactChatReply);
  expect(
    assistantReply.closest(".chat-message")?.getAttribute("data-savia-reply"),
  ).toBe(exactChatReply);
  await waitFor(() =>
    expect(voiceHarness.narrate).toHaveBeenCalledWith(
      exactChatReply,
      restartedOwner,
    ),
  );
  expect(voiceHarness.narrate).toHaveBeenCalledTimes(2);
  expect(
    calls.filter((call) => call.includes("/api/assistant/voice-update?")),
  ).toHaveLength(2);
});

test("savia context events publish public selection and history without references", async () => {
  const contexts: {
    selection: Record<string, unknown> | null;
    messages: Record<string, unknown>[];
  }[] = [];
  const listener = (event: Event) => {
    contexts.push((event as CustomEvent).detail);
  };
  window.addEventListener("savia:context", listener);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/chat/history")
        return response({
          active: false,
          messages: [
            {
              role: "user",
              text: "No reconozco este cargo",
              selection: {
                reference: charge.reference,
                occurred_at: charge.occurred_at,
                type: charge.type,
                amount: charge.amount,
                currency: charge.currency,
                status: charge.status,
              },
            },
          ],
        });
      if (String(input).startsWith("/api/followups?"))
        return response({ items: [] });
      throw new Error(`Unexpected request: ${input}`);
    }),
  );
  render(
    <Assistant
      open
      status={{ available: true, sandbox_intake_available: false }}
      selected={charge}
      transactions={[charge]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );

  await screen.findByText("No reconozco este cargo");
  await waitFor(() => expect(contexts.at(-1)?.messages).toHaveLength(1));
  const context = contexts.at(-1)!;
  expect(context.selection).toMatchObject({
    occurred_at: charge.occurred_at,
    merchant: charge.merchant,
  });
  expect(context.selection).not.toHaveProperty("reference");
  expect(context.selection).not.toHaveProperty("product_reference");
  expect(context.messages[0]).not.toHaveProperty("query_id");
  expect(context.messages[0].selection).not.toHaveProperty("reference");
  window.removeEventListener("savia:context", listener);
});
