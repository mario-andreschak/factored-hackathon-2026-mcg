import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./lib";
import { InquiryPanel } from "./InquiryPanel";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock("./lib", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./lib")>()),
  api: apiMock,
}));

const caseItem = {
  id: "case-1",
  message: "No reconozco este movimiento",
  state: "queued",
  status_message: "Tu consulta está en espera.",
  created_at: 1791115200,
  updated_at: 1791115200,
  next_check_at: 1791116100,
  next_step: "Un equipo revisará la consulta.",
  workers: [
    {
      role: "support",
      state: "queued",
      suggestion: "Revisa si el comercio te resulta familiar.",
    },
    { role: "specialist", state: "queued", suggestion: null },
  ],
  events: [
    {
      id: 101,
      kind: "queued",
      at: 1791115200,
      message: "La consulta está en espera de atención.",
    },
  ],
  informational_only: true as const,
  bank_authority: false as const,
};
const props = {
  language: "es" as const,
  transactionReference: "txn-23",
  onExpired: vi.fn(),
};

describe("InquiryPanel API boundaries", () => {
  beforeEach(() => {
    apiMock.mockReset();
    props.onExpired.mockReset();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("renders the actual backend state, localized status and numeric event timestamps", async () => {
    apiMock.mockResolvedValue({ items: [caseItem] });
    render(<InquiryPanel {...props} />);
    expect(await screen.findByText("En espera")).toBeTruthy();
    expect(screen.getByText("Tu consulta está en espera.")).toBeTruthy();
    expect(screen.getByText("Un equipo revisará la consulta.")).toBeTruthy();
    fireEvent.click(screen.getByText("Actualizaciones (1)"));
    expect(
      screen.getByText("La consulta está en espera de atención."),
    ).toBeTruthy();
    expect(screen.getByRole("time").getAttribute("datetime")).toBe(
      new Date(1791115200 * 1000).toISOString(),
    );
    expect(
      screen.queryByText("Revisa si el comercio te resulta familiar."),
    ).toBeNull();
    expect(
      screen.queryByText("Esta respuesta resolvió mi consulta"),
    ).toBeNull();
    expect(apiMock).toHaveBeenCalledWith("/api/assistant/cases?language=es");
  });

  it("sends the editable prompt, language and selected transaction reference", async () => {
    const originalParent = Object.getOwnPropertyDescriptor(window, "parent");
    const postMessage = vi.fn();
    const onVoiceUpdate = vi.fn();
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: { postMessage } as unknown as Window,
    });
    const saved = { ...caseItem, id: `i_${"b".repeat(32)}` };
    apiMock.mockImplementation((url: string) =>
      Promise.resolve(
        url === "/api/assistant/cases"
          ? { id: saved.id, items: [saved] }
          : { items: [saved] },
      ),
    );
    render(
      <InquiryPanel
        {...props}
        message="Seeded question"
        onVoiceUpdate={onVoiceUpdate}
      />,
    );
    expect(await screen.findByText("En espera")).toBeTruthy();
    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(onVoiceUpdate).toHaveBeenCalledTimes(1);
    expect(onVoiceUpdate).toHaveBeenLastCalledWith(saved.id, 101);
    const input = (await screen.findByLabelText(
      "¿Qué necesitas aclarar?",
    )) as HTMLTextAreaElement;
    fireEvent.change(input, {
      target: { value: "  ¿Por qué se procesó esta compra?  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar consulta" }));
    await waitFor(() =>
      expect(
        apiMock.mock.calls.some(([url]) => url === "/api/assistant/cases"),
      ).toBe(true),
    );
    const postCall = apiMock.mock.calls.find(
      ([url]) => url === "/api/assistant/cases",
    );
    expect(postCall).toEqual([
      "/api/assistant/cases",
      {
        method: "POST",
        body: JSON.stringify({
          message: "¿Por qué se procesó esta compra?",
          language: "es",
          transaction_reference: "txn-23",
        }),
      },
    ]);
    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(onVoiceUpdate).toHaveBeenCalledTimes(1);
    if (originalParent) Object.defineProperty(window, "parent", originalParent);
  });

  it("polls active work at two seconds and dispatches a bounded transition update", async () => {
    const originalParent = Object.getOwnPropertyDescriptor(window, "parent");
    const postMessage = vi.fn();
    const onVoiceUpdate = vi.fn();
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: { postMessage } as unknown as Window,
    });
    const voiceCase = { ...caseItem, id: `i_${"a".repeat(32)}` };
    const working = {
      ...voiceCase,
      state: "team_working",
      status_message: "Un equipo está revisando tu consulta.",
      events: [
        {
          ...caseItem.events[0],
          id: 102,
          kind: "working",
          message: "El equipo está revisando la consulta.",
        },
      ],
    };
    let getCount = 0;
    apiMock.mockImplementation(() =>
      Promise.resolve({ items: ++getCount === 1 ? [voiceCase] : [working] }),
    );
    const updates: Record<string, unknown>[] = [];
    const captureUpdate = (event: Event) =>
      updates.push((event as CustomEvent).detail);
    window.addEventListener("savia:inquiries", captureUpdate);
    render(<InquiryPanel {...props} onVoiceUpdate={onVoiceUpdate} />);
    expect(await screen.findByText("En espera")).toBeTruthy();
    expect(
      await screen.findByText("En revisión", {}, { timeout: 3_500 }),
    ).toBeTruthy();
    expect(getCount).toBeGreaterThanOrEqual(2);
    expect(postMessage).toHaveBeenCalledTimes(2);
    expect(postMessage.mock.calls[0]).toEqual([
      { type: "savia:inquiry-update", case_id: voiceCase.id, event_id: 101 },
      window.location.origin,
    ]);
    expect(postMessage).toHaveBeenLastCalledWith(
      { type: "savia:inquiry-update", case_id: voiceCase.id, event_id: 102 },
      window.location.origin,
    );
    expect(onVoiceUpdate.mock.calls).toEqual([
      [voiceCase.id, 101],
      [voiceCase.id, 102],
    ]);
    expect(screen.getByRole("status").textContent).toBe(
      "Un equipo está revisando tu consulta.",
    );
    expect(updates).toHaveLength(1);
    expect(updates[0]).toEqual({
      items: [
        {
          message: caseItem.message,
          state: "team_working",
          status_message: working.status_message,
          next_step: working.next_step,
          suggestions: [],
        },
      ],
    });
    expect(JSON.stringify(updates)).not.toContain("case-1");
    expect(JSON.stringify(updates)).not.toContain("txn-23");
    await waitFor(() => expect(getCount).toBeGreaterThanOrEqual(3), {
      timeout: 3_500,
    });
    expect(postMessage).toHaveBeenCalledTimes(2);
    expect(onVoiceUpdate).toHaveBeenCalledTimes(2);
    window.removeEventListener("savia:inquiries", captureUpdate);
    if (originalParent) Object.defineProperty(window, "parent", originalParent);
  });

  it("marks team responses helpful through the explicit resolve contract", async () => {
    const completed = {
      ...caseItem,
      state: "team_completed",
      status_message: "El equipo compartió su respuesta.",
      workers: [
        {
          role: "support",
          state: "completed",
          suggestion: "Revisa el comercio.",
        },
        {
          role: "specialist",
          state: "completed",
          suggestion: "Confirma el monto en tus registros.",
        },
      ],
    };
    apiMock
      .mockResolvedValueOnce({ items: [completed] })
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({
        items: [{ ...completed, state: "informational_resolved" }],
      });
    render(<InquiryPanel {...props} />);
    expect(await screen.findByText("Respuesta disponible")).toBeTruthy();
    expect(screen.getByText("Revisa el comercio.")).toBeTruthy();
    expect(
      screen.getByText("Confirma el monto en tus registros."),
    ).toBeTruthy();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Esta respuesta resolvió mi consulta",
      }),
    );
    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    expect(apiMock.mock.calls[1]).toEqual([
      "/api/assistant/cases/case-1/resolve",
      { method: "POST", body: JSON.stringify({ resolved: true }) },
    ]);
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: "Esta respuesta resolvió mi consulta",
      }),
    ).toBeNull();
    expect(screen.getByText("Revisa el comercio.")).toBeTruthy();
  });

  it("shows service unavailability and expires an unauthorized session", async () => {
    apiMock.mockRejectedValueOnce(new ApiError("offline", 503));
    render(<InquiryPanel {...props} />);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "El servicio de ayuda no está disponible ahora.",
    );
    cleanup();
    apiMock.mockRejectedValueOnce(new ApiError("unauthorized", 401));
    render(<InquiryPanel {...props} />);
    await waitFor(() => expect(props.onExpired).toHaveBeenCalledOnce());
  });

  it("requires active voice and an intentional once-only click for saved recommendations", async () => {
    const saved = {
      ...caseItem,
      id: `i_${"d".repeat(32)}`,
      state: "awaiting_customer",
      workers: [
        {
          role: "evidence",
          state: "completed",
          suggestion: "Compara el comercio con tus recibos.",
        },
      ],
    };
    apiMock.mockResolvedValue({ items: [saved] });
    const listen = vi.fn().mockResolvedValue(true);
    const view = render(
      <InquiryPanel {...props} onListenRecommendations={listen} />,
    );
    const button = await screen.findByRole("button", {
      name: "Escuchar recomendaciones",
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByText("Activa Hablar con Savia para escucharlas."),
    ).toBeTruthy();
    fireEvent.click(button);
    expect(listen).not.toHaveBeenCalled();
    view.rerender(
      <InquiryPanel {...props} voiceActive onListenRecommendations={listen} />,
    );
    expect(listen).not.toHaveBeenCalled();
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() =>
      expect(listen).toHaveBeenCalledExactlyOnceWith(saved.id, 101),
    );
    const queued = await screen.findByRole("button", {
      name: "Recomendaciones enviadas a la voz",
    });
    expect((queued as HTMLButtonElement).disabled).toBe(true);
    expect(
      apiMock.mock.calls.every(
        ([url]) => url === "/api/assistant/cases?language=es",
      ),
    ).toBe(true);
  });

  it("offers no Listen control for closed or unfinished results and localizes its label", async () => {
    const workers = [
      {
        role: "evidence",
        state: "completed",
        suggestion: "Confira seus recibos.",
      },
    ];
    apiMock.mockResolvedValue({
      items: [
        {
          ...caseItem,
          id: `i_${"e".repeat(32)}`,
          state: "informational_resolved",
          workers,
        },
        {
          ...caseItem,
          id: `i_${"f".repeat(32)}`,
          state: "team_completed",
          workers: [],
        },
      ],
    });
    const listen = vi.fn().mockResolvedValue(true);
    const view = render(
      <InquiryPanel {...props} voiceActive onListenRecommendations={listen} />,
    );
    await screen.findByText("Consulta informativa completada");
    expect(
      screen.queryByRole("button", { name: "Escuchar recomendaciones" }),
    ).toBeNull();
    apiMock.mockResolvedValue({
      items: [
        {
          ...caseItem,
          id: `i_${"a".repeat(32)}`,
          state: "team_completed",
          workers,
        },
      ],
    });
    view.rerender(
      <InquiryPanel
        {...props}
        language="pt"
        voiceActive
        onListenRecommendations={listen}
      />,
    );
    expect(
      await screen.findByRole("button", { name: "Ouvir recomendações" }),
    ).toBeTruthy();
    expect(listen).not.toHaveBeenCalled();
  });

  it("keeps a rejected Listen request available and reports that the written advice remains", async () => {
    apiMock.mockResolvedValue({
      items: [
        {
          ...caseItem,
          id: `i_${"a".repeat(32)}`,
          state: "team_completed",
          workers: [
            {
              role: "evidence",
              state: "completed",
              suggestion: "Compara tus recibos.",
            },
          ],
        },
      ],
    });
    const listen = vi.fn().mockResolvedValue(false);
    render(
      <InquiryPanel {...props} voiceActive onListenRecommendations={listen} />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Escuchar recomendaciones" }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Puedes leerlas aquí.",
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Escuchar recomendaciones",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    expect(screen.getByText("Compara tus recibos.")).toBeTruthy();
  });
});
