import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { Assistant } from "./App";
import type {
  ActionFacts,
  ActionResult,
  HandoffPacket,
  IntakeReceipt,
  Transaction,
} from "./types";

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
          return response({ active: false, messages: [] });
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
    expect(confirm.textContent).toContain(
      `${referenceLabel}: ${charge.reference}`,
    );
    const summary = document.getElementById(
      confirm.getAttribute("aria-describedby")!,
    );
    expect(summary).not.toBeNull();
    expect(within(summary!).getByText(charge.reference)).toBeTruthy();
    expect(summary!.textContent).toContain(month);
    expect(summary!.textContent).toContain("COP");
    expect(summary!.textContent).toContain("42");

    fireEvent.change(
      screen.getByRole("textbox", { name: "Mensaje para el asistente" }),
      { target: { value: yes } },
    );
    fireEvent.submit(
      screen
        .getByRole("textbox", { name: "Mensaje para el asistente" })
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
    ).toEqual({ message: yes, transaction_reference: charge.reference });

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
        return response({ active: false, messages: [] });
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
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  const summary = document.getElementById(
    confirm.getAttribute("aria-describedby")!,
  );
  expect(summary!.textContent).toContain("••••••");
  fireEvent.click(
    screen.getByRole("button", { name: "Mostrar monto para confirmar" }),
  );
  expect((confirm as HTMLButtonElement).disabled).toBe(false);
  expect(summary!.textContent).toContain("42");
  expect(summary!.textContent).not.toContain("••••••");
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
          return response({ active: false, messages: [] });
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
          return response({ active: false, messages: [] });
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
    expect(within(evidence).getByText(receipt.id)).toBeTruthy();
    expect(within(evidence).getByText(charge.reference)).toBeTruthy();
    expect(within(evidence).getByText(received)).toBeTruthy();
    expect(within(evidence).getByText("fixture-original")).toBeTruthy();
    expect(within(evidence).getByText("fixture-current-view")).toBeTruthy();
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
    expect(within(evidence).getByText(charge.reference)).toBeTruthy();
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
          return response({ active: false, messages: [] });
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
    expect(within(evidence).getByText(handoff.id)).toBeTruthy();
    expect(within(evidence).getByText(charge.reference)).toBeTruthy();
    expect(
      within(evidence).getByText(handoff.unanswered_questions[0]),
    ).toBeTruthy();
    expect(
      within(evidence).getByText(
        language === "pt" ? "Snapshot consultado em" : "Snapshot consultado el",
      ),
    ).toBeTruthy();
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
        return response({ active: false, messages: [] });
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
          return response({ active: false, messages: [] });
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
          return response({ active: false, messages: [] });
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
          return response({ active: false, messages: [] });
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
    fireEvent.change(
      await screen.findByRole("textbox", { name: questionsLabel }),
      { target: { value: ` ${question} \nSegunda pergunta?` } },
    );
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
    expect(within(evidence).getByText(question)).toBeTruthy();
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
        return response({ active: false, messages: [] });
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
          return response({ active: false, messages: [] });
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
          return response({ active: false, messages: [] });
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
          return response({ active: false, messages: [] });
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
        return response({ active: false, messages: [] });
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
