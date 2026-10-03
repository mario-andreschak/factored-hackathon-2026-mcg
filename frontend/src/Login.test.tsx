import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import App, { Assistant, Login } from "./App";
import type { Overview } from "./types";

const reply = (body: unknown, status = 200) =>
  ({
    ok: status < 400,
    status,
    headers: { get: () => null },
    json: async () => body,
  }) as unknown as Response;

beforeEach(() => {
  localStorage.clear();
  document.documentElement.lang = "es";
  document.title = "Savia · Tu banca personal";
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
  vi.restoreAllMocks();
});

test("Portuguese demo sign-in preserves selected profile and Assistant locale", async () => {
  const calls: { url: string; body?: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, body: init?.body as string | undefined });
      if (url === "/api/auth/profiles")
        return reply({
          mode: "demo",
          profiles: [
            {
              id: "fictional-a",
              alias: "Ana Demo",
              country: "CO",
              primary_currency: "COP",
            },
            {
              id: "fictional-b",
              alias: "Bia Demo",
              country: "BR",
              primary_currency: "BRL",
            },
          ],
        });
      if (url === "/api/auth/login") return reply({});
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const onLogin = vi.fn();
  const view = render(<Login onLogin={onLogin} notice="" />);
  const language = screen.getByRole("combobox", { name: "Idioma de acceso" });
  language.focus();
  expect(document.activeElement).toBe(language);
  fireEvent.change(language, { target: { value: "pt" } });
  expect(document.documentElement.lang).toBe("pt-BR");
  expect(document.title).toBe("Savia · Seu banco pessoal");
  expect(
    screen.getByRole("heading", {
      name: /Seu dinheiro.*Seus planos.*Sua tranquilidade/s,
    }),
  ).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "Que bom ter você aqui." }),
  ).toBeTruthy();
  expect(
    screen.getByText(
      /os produtos, seus detalhes, os movimentos e as informações da demonstração estarão em português/,
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      /Nomes de estabelecimentos, cidades e canais da origem são exibidos como recebidos/,
    ),
  ).toBeTruthy();
  await screen.findByRole("group", {
    name: "Escolha um perfil de demonstração",
  });
  fireEvent.click(screen.getByRole("button", { name: /Bia Demo/ }));
  expect(
    screen
      .getByRole("button", { name: /Bia Demo/ })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.change(screen.getByLabelText("Código de acesso"), {
    target: { value: "synthetic-demo-code" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Entrar no meu banco" }));
  await waitFor(() => expect(onLogin).toHaveBeenCalledWith("demo"));
  expect(
    JSON.parse(calls.find((call) => call.url === "/api/auth/login")!.body!),
  ).toEqual({
    profile: "fictional-b",
    code: "synthetic-demo-code",
  });
  expect(localStorage.getItem("flujo-bank-action-language")).toBe("pt");
  view.unmount();
  expect(document.documentElement.lang).toBe("es");
  render(
    <Assistant
      open
      status={{ available: false }}
      selected={null}
      transactions={[]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic={true}
      onClose={vi.fn()}
      onExpired={vi.fn()}
    />,
  );
  expect(
    (
      screen.getByRole("combobox", {
        name: "Idioma da interface",
      }) as HTMLSelectElement
    ).value,
  ).toBe("pt");
  expect(document.documentElement.lang).toBe("es");
  expect(
    calls.filter((call) => call.url.startsWith("/api/action/")),
  ).toHaveLength(0);
});

test("Portuguese invite retry, error, and success retain invite-only auth", async () => {
  const calls: { url: string; body?: string }[] = [];
  let profiles = 0,
    invites = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, body: init?.body as string | undefined });
      if (url === "/api/auth/profiles") {
        if (++profiles === 1) throw new Error("network unavailable");
        return reply({ mode: "invite", profiles: [] });
      }
      if (url === "/api/auth/invite")
        return ++invites === 1
          ? reply({ detail: "server diagnostic" }, 401)
          : reply({});
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const onLogin = vi.fn();
  render(<Login onLogin={onLogin} notice="session-revoke-unconfirmed" />);
  fireEvent.change(screen.getByRole("combobox", { name: "Idioma de acceso" }), {
    target: { value: "pt" },
  });
  expect(
    await screen.findByText(/conexão com os dados está indisponível/),
  ).toBeTruthy();
  expect(screen.getByText(/encerramento completo da sessão/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
  expect(
    await screen.findByRole("heading", { name: "Seu acesso é só seu." }),
  ).toBeTruthy();
  expect(
    screen.getByText(/Cada convite abre um único perfil fictício/),
  ).toBeTruthy();
  expect(
    screen.queryByRole("group", { name: /perfil de demonstração/i }),
  ).toBeNull();
  fireEvent.change(screen.getByLabelText("Código do convite"), {
    target: { value: "synthetic-invite-code" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Entrar no meu banco" }));
  expect(
    await screen.findByText(
      "O código está incorreto. Confira e tente novamente.",
    ),
  ).toBeTruthy();
  expect(screen.queryByText("server diagnostic")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Entrar no meu banco" }));
  await waitFor(() => expect(onLogin).toHaveBeenCalledWith("invite"));
  expect(calls.filter((call) => call.url === "/api/auth/login")).toHaveLength(
    0,
  );
  const requests = calls.filter((call) => call.url === "/api/auth/invite");
  expect(requests).toHaveLength(2);
  for (const request of requests)
    expect(JSON.parse(request.body!)).toEqual({
      code: "synthetic-invite-code",
    });
});

test("Spanish defaults and non-401 failures remain safe and local", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      if (String(input) === "/api/auth/profiles")
        return reply({
          mode: "demo",
          profiles: [
            {
              id: "fictional-a",
              alias: "Ana Demo",
              country: "CO",
              primary_currency: "COP",
            },
          ],
        });
      if (String(input) === "/api/auth/login")
        return reply({ detail: "server diagnostic" }, 503);
      throw new Error(`Unexpected request: ${input}`);
    }),
  );
  const onLogin = vi.fn();
  render(<Login onLogin={onLogin} notice="" />);
  expect(
    (
      screen.getByRole("combobox", {
        name: "Idioma de acceso",
      }) as HTMLSelectElement
    ).value,
  ).toBe("es");
  expect(document.documentElement.lang).toBe("es");
  await screen.findByRole("button", { name: /Ana Demo/ });
  fireEvent.change(screen.getByLabelText("Código de acceso"), {
    target: { value: "wrong-code" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Entrar a mi banca" }));
  expect(
    await screen.findByText("No pudimos iniciar tu sesión. Intenta de nuevo."),
  ).toBeTruthy();
  expect(screen.queryByText("server diagnostic")).toBeNull();
  expect(onLogin).not.toHaveBeenCalled();
});

const syntheticOverview = {
  profile: {
    id: "fictional-b",
    alias: "Bia Demo",
    country: "BR",
    segment: "demo",
    primary_currency: "BRL",
  },
  products: [],
  transactions: [],
  summary: {
    balances_by_currency: [] as Overview["summary"]["balances_by_currency"],
    transaction_count: 0,
    monthly_activity: [],
  },
  metadata: {
    dataset: "team-synthetic-fixture",
    build_id: "fictional-build",
    source_fingerprint: "fictional-snapshot",
    snapshot_created_at: "2026-10-01",
    data_as_of: "2026-10-01",
    balances_note: "",
    amounts_note: "",
    transactions_returned: 0,
    transactions_total: 0,
    filtered_count: 0,
    transactions_limit: 500,
    transactions_offset: 0,
    transactions_truncated: false,
    next_offset: null,
  },
};

function denyStorageAndServeDemo() {
  const getItem = vi
    .spyOn(Storage.prototype, "getItem")
    .mockImplementation(() => {
      throw new DOMException("Storage denied", "SecurityError");
    });
  const setItem = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new DOMException("Storage denied", "SecurityError");
    });
  const calls: string[] = [];
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = String(input);
      calls.push(url);
      if (url === "/api/auth/me") return reply({}, 401);
      if (url === "/api/auth/profiles")
        return reply({ mode: "demo", profiles: [syntheticOverview.profile] });
      if (url === "/api/auth/login" || url === "/api/auth/logout")
        return reply({});
      if (url === "/api/overview") return reply(syntheticOverview);
      if (url === "/api/chat/status") return reply({ available: false });
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  return { getItem, setItem, calls };
}

async function enterDemo() {
  await screen.findByRole("button", { name: /Bia Demo/ });
  fireEvent.change(screen.getByLabelText(/Código de acceso|Código de acesso/), {
    target: { value: "synthetic-demo-code" },
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: /Entrar a mi banca|Entrar no meu banco/,
    }),
  );
  await screen.findByRole("button", { name: /Cerrar sesión|Encerrar sessão/ });
}

test("Portuguese sign-in reaches Assistant when storage reads and writes are denied", async () => {
  const { getItem, setItem, calls } = denyStorageAndServeDemo();
  render(<App />);
  const language = await screen.findByRole("combobox", {
    name: "Idioma de acceso",
  });
  expect((language as HTMLSelectElement).value).toBe("es");
  fireEvent.change(language, { target: { value: "pt" } });
  expect(
    screen.getByText(/O Assistente usa o idioma escolhido aqui/),
  ).toBeTruthy();
  await enterDemo();
  fireEvent.click(screen.getByRole("button", { name: /^Assistente/ }));
  const assistantLanguage = screen.getByRole("combobox", {
    name: "Idioma da interface",
  }) as HTMLSelectElement;
  expect(assistantLanguage.value).toBe("pt");
  expect(
    screen.getByPlaceholderText("Assistente temporariamente desconectado"),
  ).toBeTruthy();
  expect(document.documentElement.lang).toBe("pt-BR");
  expect(getItem).toHaveBeenCalled();
  expect(setItem).toHaveBeenCalled();
  expect(calls.filter((url) => url.startsWith("/api/action/"))).toHaveLength(0);
});

test("Assistant language returns to Login during the same storage-denied visit", async () => {
  denyStorageAndServeDemo();
  render(<App />);
  await enterDemo();
  fireEvent.click(screen.getByRole("button", { name: /^Asistente/ }));
  fireEvent.change(
    screen.getByRole("combobox", { name: "Idioma de la interfaz" }),
    { target: { value: "pt" } },
  );
  expect(
    (
      screen.getByRole("combobox", {
        name: "Idioma da interface",
      }) as HTMLSelectElement
    ).value,
  ).toBe("pt");
  fireEvent.click(screen.getByRole("button", { name: "Encerrar sessão" }));
  const language = await screen.findByRole("combobox", {
    name: "Idioma de acesso",
  });
  expect((language as HTMLSelectElement).value).toBe("pt");
  expect(
    screen.getByText(/O Assistente usa o idioma escolhido aqui/),
  ).toBeTruthy();
});

const portalCharge = {
  reference: "txn_aaaaaaaaaaaaaaaaaaaaaaaa",
  product_reference: "card-1",
  occurred_at: "2026-09-20T12:00:00Z",
  process_date: "2026-09-20T12:00:00Z",
  type: "Purchase",
  category: "Shopping",
  amount: 42,
  currency: "BRL",
  status: "Approved",
  channel: "Card",
  merchant: "Loja Sol",
  country: "BR",
  city: "São Paulo",
  direction: "debit",
};
const portalOverview = {
  ...syntheticOverview,
  products: [
    {
      reference: "card-1",
      type: "Tarjeta Débito",
      currency: "BRL",
      balance: 0,
      balance_kind: "deposit",
      credit_limit: null,
      interest_rate: null,
      status: "Active",
      opened_at: "2026-01-01",
      last_updated: "2026-09-20",
    },
  ],
  transactions: [
    portalCharge,
    {
      ...portalCharge,
      reference: "txn_bbbbbbbbbbbbbbbbbbbbbbbb",
      merchant: "Loja Lua",
      status: "Pending",
    },
  ],
  metadata: {
    ...syntheticOverview.metadata,
    transactions_returned: 2,
    transactions_total: 2,
  },
};
function servePortal(
  language: "es" | "pt",
  chatAvailable = true,
  overview = portalOverview,
) {
  localStorage.setItem("flujo-bank-action-language", language);
  vi.stubGlobal("scrollTo", vi.fn());
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = String(input);
      calls.push(url);
      if (url === "/api/auth/me") return reply({ auth_mode: "invite" });
      if (url === "/api/overview") return reply(overview);
      if (url === "/api/chat/status")
        return reply({
          available: chatAvailable,
          sandbox_intake_available: false,
        });
      if (url === "/api/chat/history")
        return reply({ active: false, messages: [] });
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  return calls;
}

test.each([
  ["es", "Menú de navegación", "Abrir menú", "Cerrar menú", "Movimientos"],
  ["pt", "Menu de navegação", "Abrir menu", "Fechar menu", "Movimentos"],
] as const)(
  "%s mobile menu keeps keyboard focus inside and restores the trigger",
  async (language, menuName, openName, closeName, destination) => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    servePortal(language, false);
    render(<App />);
    await screen.findByRole("heading", {
      name: language === "pt" ? /Olá, Bia/ : /Hola, Bia/,
    });
    const trigger = screen.getByRole("button", { name: openName });
    trigger.focus();
    fireEvent.click(trigger);
    const menu = screen.getByRole("dialog", { name: menuName });
    const close = within(menu).getByRole("button", { name: closeName });
    const mainShell = document.querySelector(".main-shell");
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(mainShell?.hasAttribute("inert")).toBe(true);
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    const last = within(menu).getByRole("button", {
      name: language === "pt" ? "Encerrar sessão" : "Cerrar sesión",
    });
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: menuName })).toBeNull();
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(mainShell?.hasAttribute("inert")).toBe(false);
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    fireEvent.click(
      within(screen.getByRole("dialog", { name: menuName })).getByRole(
        "button",
        { name: closeName },
      ),
    );
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    fireEvent.click(
      within(screen.getByRole("dialog", { name: menuName })).getByRole(
        "button",
        { name: destination },
      ),
    );
    expect(document.activeElement).toBe(trigger);
    expect(mainShell?.hasAttribute("inert")).toBe(false);

    fireEvent.click(trigger);
    fireEvent.click(document.querySelector(".mobile-shade")!);
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    fireEvent.click(
      within(screen.getByRole("dialog", { name: menuName })).getByRole(
        "button",
        {
          name:
            language === "pt"
              ? "Sobre esta experiência"
              : "Sobre esta experiencia",
        },
      ),
    );
    expect(mainShell?.hasAttribute("inert")).toBe(false);
    expect(screen.queryByRole("dialog", { name: menuName })).toBeNull();
    const about = screen.getByRole("dialog", {
      name:
        language === "pt"
          ? "Um cenário para explorar"
          : "Un escenario para explorar",
    });
    fireEvent.click(
      within(about).getByRole("button", {
        name: language === "pt" ? "Fechar" : "Cerrar",
      }),
    );
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  },
);

test.each([
  ["es", "Menú de navegación", "Abrir menú", "Cerrar menú", "Inicio"],
  ["pt", "Menu de navegação", "Abrir menu", "Fechar menu", "Início"],
] as const)(
  "%s responsive 390→900→390 menu focus follows the visible navigation",
  async (language, menuName, openName, closeName, desktopName) => {
    let mobile = true;
    let onChange: (() => void) | undefined;
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        get matches() {
          return mobile;
        },
        addEventListener: (_type: string, listener: () => void) => {
          onChange = listener;
        },
        removeEventListener: vi.fn(),
      })),
    );
    servePortal(language, false);
    render(<App />);
    await screen.findByRole("heading", {
      name: language === "pt" ? /Olá, Bia/ : /Hola, Bia/,
    });
    const trigger = screen.getByRole("button", { name: openName });
    fireEvent.click(trigger);
    const close = within(
      screen.getByRole("dialog", { name: menuName }),
    ).getByRole("button", { name: closeName });
    expect(document.activeElement).toBe(close);
    expect(onChange).toBeDefined();

    act(() => {
      mobile = false;
      onChange?.();
    });

    const desktopNavigation = screen.getByRole("button", {
      name: desktopName,
    });
    expect(screen.queryByRole("dialog", { name: menuName })).toBeNull();
    expect(document.querySelector(".main-shell")?.hasAttribute("inert")).toBe(
      false,
    );
    expect(document.activeElement).toBe(desktopNavigation);
    expect(document.activeElement).not.toBe(trigger);

    act(() => {
      mobile = true;
      // jsdom does not apply the mobile CSS that hides the sidebar. Simulate
      // the browser clearing focus before the media-query event is delivered.
      desktopNavigation.blur();
      expect(document.activeElement).toBe(document.body);
      onChange?.();
    });
    expect(document.activeElement).toBe(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    // A visible main-shell control keeps focus across the same resize.
    act(() => {
      mobile = false;
      onChange?.();
    });
    const snapshot =
      document.querySelector<HTMLButtonElement>(".snapshot-pill");
    expect(snapshot).not.toBeNull();
    snapshot!.focus();
    act(() => {
      mobile = true;
      onChange?.();
    });
    expect(document.activeElement).toBe(snapshot);

    // A prior, intentional blur on desktop is not a hidden-control transfer.
    act(() => {
      mobile = false;
      onChange?.();
    });
    desktopNavigation.focus();
    desktopNavigation.blur();
    expect(document.activeElement).toBe(document.body);
    act(() => {
      mobile = true;
      onChange?.();
    });
    expect(document.activeElement).toBe(document.body);
  },
);

test.each([
  ["pt", "COP"],
  ["pt", "ARS"],
  ["es", "COP"],
  ["es", "ARS"],
] as const)(
  "%s Home shows %s once in visible and hidden balances",
  async (language, currency) => {
    servePortal(language, false, {
      ...portalOverview,
      profile: { ...portalOverview.profile, primary_currency: currency },
      summary: {
        ...portalOverview.summary,
        balances_by_currency: [
          {
            currency,
            deposit_balance: 1234.5,
            credit_balance: 0,
            investment_balance: 0,
            other_balance: 0,
          },
        ],
      },
    });
    render(<App />);
    await screen.findByRole("heading", {
      name: language === "pt" ? /Olá, Bia/ : /Hola, Bia/,
    });
    const balance = document.querySelector(".balance-value");
    expect(balance).toBeTruthy();
    const visible = balance?.textContent || "";
    expect(visible.match(new RegExp(currency, "g"))).toHaveLength(1);
    expect(visible).toContain(language === "pt" ? "1.234,50" : "1,234.50");
    fireEvent.click(screen.getByRole("button", { name: "Ocultar saldos" }));
    expect(balance?.textContent).toBe(`•••••• ${currency}`);
  },
);

test.each([
  ["Compra en línea", "Compras online"],
  ["Compra anulada", "Compra cancelada"],
  ["Cafetería", "Cafeteria"],
  ["Nómina", "Salário"],
  ["Transferencia", "Transferência"],
  ["Hogar", "Casa e lar"],
  ["Supermercado", "Supermercado"],
  ["Efectivo", "Dinheiro"],
  ["Suscripción", "Assinaturas"],
  ["Categoria inédita", "Categoria inédita"],
] as const)(
  "Portuguese Home displays source category %s as %s in Spending",
  async (category, expected) => {
    servePortal("pt", false, {
      ...portalOverview,
      transactions: [{ ...portalCharge, category }],
      metadata: {
        ...portalOverview.metadata,
        transactions_returned: 1,
        transactions_total: 1,
      },
    });
    render(<App />);
    await screen.findByRole("heading", { name: /Olá, Bia/ });
    const spending = document.querySelector(".spending-panel");
    expect(spending).toBeTruthy();
    expect(within(spending as HTMLElement).getByText(expected)).toBeTruthy();
    expect(
      within(spending as HTMLElement).getByText(
        /Categorias conhecidas aparecem em português; as demais mantêm o nome da origem/,
      ),
    ).toBeTruthy();
    if (category !== expected) {
      expect(within(spending as HTMLElement).queryByText(category)).toBeNull();
    }
  },
);

test("Portuguese charge finder keeps labels and dialog names local across the portal", async () => {
  const calls = servePortal("pt");
  render(<App />);
  const navigation = await screen.findByRole("button", { name: "Movimentos" });
  expect(document.documentElement.lang).toBe("pt-BR");
  expect(document.title).toBe("Savia · Seu banco pessoal");
  expect(navigation.closest("aside")?.getAttribute("lang")).toBe("pt-BR");
  expect(screen.getByRole("button", { name: "Início" })).toBeTruthy();
  expect(screen.getByRole("main").getAttribute("lang")).toBe("pt-BR");
  expect(screen.getByRole("heading", { name: /Olá, Bia/ })).toBeTruthy();
  const globalSearch = screen.getByRole("textbox", {
    name: "Buscar movimentos",
  });
  fireEvent.change(globalSearch, { target: { value: "Loja Sol" } });
  expect(
    screen.getByRole("button", { name: /Loja Sol.*Aprovado/s }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Loja Lua/ })).toBeNull();
  fireEvent.change(globalSearch, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Início" }));
  fireEvent.click(navigation);
  const main = screen.getByRole("main");
  expect(main.getAttribute("lang")).toBe("pt-BR");
  expect(
    screen.getByRole("heading", { name: "Seu dinheiro em movimento." }),
  ).toBeTruthy();
  expect(
    screen.getByText(/Nomes de estabelecimentos, cidades e canais da origem/),
  ).toBeTruthy();
  expect(
    screen.getByRole("combobox", { name: "Filtrar por produto" }),
  ).toBeTruthy();
  const status = screen.getByRole("combobox", { name: "Filtrar por status" });
  fireEvent.change(status, { target: { value: "Pending" } });
  expect(screen.getByText("Filtros ativos")).toBeTruthy();
  expect(
    screen.getByRole("button", { name: /Loja Lua.*Pendente/s }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Loja Sol/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
  const filterSearch = document.querySelector<HTMLInputElement>(
    ".filter-search input",
  );
  expect(filterSearch?.getAttribute("placeholder")).toBe("Loja, tipo ou moeda");
  expect(filterSearch?.getAttribute("aria-label")).toBe("Filtrar movimentos");
  const search = screen.getByRole("textbox", { name: "Buscar movimentos" });
  fireEvent.change(search, { target: { value: "Loja Sol" } });
  fireEvent.click(screen.getByRole("button", { name: /Loja Sol.*Aprovado/s }));
  const dialog = screen.getByRole("dialog", { name: "Detalhes do movimento" });
  expect(dialog.querySelector("h2")?.getAttribute("lang")).toBe("pt-BR");
  expect(screen.getByRole("button", { name: "Fechar" })).toBeTruthy();
  expect(screen.getByText("Não reconhece esta cobrança?")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Revisar esta cobrança" }),
  );
  expect(
    screen.getByRole("combobox", { name: "Idioma da interface" }),
  ).toBeTruthy();
  expect(calls.some((url) => url.startsWith("/api/action/"))).toBe(false);
});

test("Portuguese transaction amounts, dates, type and pagination use one currency label", async () => {
  const transactions = Array.from({ length: 12 }, (_, index) => ({
    ...portalCharge,
    reference: `txn_${String(index).padStart(24, "0")}`,
    merchant: `Loja ${index + 1}`,
    currency: index === 0 ? "BRL" : "COP",
  }));
  servePortal("pt", false, {
    ...portalOverview,
    transactions,
    metadata: {
      ...portalOverview.metadata,
      transactions_returned: transactions.length,
      transactions_total: transactions.length,
    },
  });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Movimentos" }));
  const first = Array.from(
    document.querySelectorAll<HTMLButtonElement>(".transaction-row"),
  ).find((row) => row.querySelector("strong")?.textContent === "Loja 1");
  expect(first).toBeTruthy();
  expect(first?.querySelector(".amount")?.textContent).toContain("R$");
  expect(first?.querySelector(".amount")?.textContent).not.toContain("BRL");
  expect(first?.textContent).toContain("Compra");
  expect(first?.textContent).toContain("set.");
  fireEvent.click(screen.getByRole("button", { name: "Próxima página" }));
  const previous = screen.getByRole("button", {
    name: "Página anterior",
  }) as HTMLButtonElement;
  expect(previous.disabled).toBe(false);
  expect(previous.getAttribute("lang")).toBe("pt-BR");
  const cop = Array.from(
    document.querySelectorAll<HTMLButtonElement>(".transaction-row"),
  ).find((row) => row.querySelector("strong")?.textContent === "Loja 12");
  expect(cop).toBeTruthy();
  expect(
    cop?.querySelector(".amount")?.textContent?.match(/COP/g),
  ).toHaveLength(1);
  fireEvent.click(previous);
  expect(
    Array.from(
      document.querySelectorAll<HTMLButtonElement>(".transaction-row"),
    ).some((row) => row.querySelector("strong")?.textContent === "Loja 1"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Início" }));
  fireEvent.click(screen.getByRole("button", { name: "Ocultar saldos" }));
  fireEvent.click(screen.getByRole("button", { name: "Movimentos" }));
  const hidden = Array.from(
    document.querySelectorAll<HTMLButtonElement>(".transaction-row"),
  ).find((row) => row.querySelector("strong")?.textContent === "Loja 1");
  expect(hidden?.querySelector(".amount")?.textContent).toContain("••••••");
  expect(hidden?.querySelector(".amount")?.textContent).toContain("BRL");
});

test("Portuguese Movimentos snapshot error, retry and boot use Portuguese semantics", async () => {
  localStorage.setItem("flujo-bank-action-language", "pt");
  vi.stubGlobal("scrollTo", vi.fn());
  let overviewCalls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = String(input);
      if (url === "/api/auth/me") return reply({ auth_mode: "invite" });
      if (url === "/api/overview") {
        overviewCalls += 1;
        if (overviewCalls === 1) return reply({}, 503);
        return new Promise<Response>(() => {});
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  render(<App />);
  expect(document.documentElement.lang).toBe("pt-BR");
  expect(document.title).toBe("Savia · Seu banco pessoal");
  expect(
    screen
      .getByText("Preparando seu espaço…")
      .closest("[lang]")
      ?.getAttribute("lang"),
  ).toBe("pt-BR");
  fireEvent.click(await screen.findByRole("button", { name: "Movimentos" }));
  const main = screen.getByRole("main");
  expect(main.getAttribute("lang")).toBe("pt-BR");
  expect(
    screen.getByRole("heading", { name: "Um momento para reconectar." }),
  ).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain(
    "Não foi possível carregar os dados bancários.",
  );
  expect(screen.queryByText("Un momento para reconectar.")).toBeNull();
  expect(
    within(main).getByRole("button", { name: "Encerrar sessão" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
  expect(
    screen
      .getByLabelText("Carregando dados")
      .closest("[lang]")
      ?.getAttribute("lang"),
  ).toBe("pt-BR");
  expect(overviewCalls).toBe(2);
});

test("Spanish charge finder retains its navigation, filters and review entry", async () => {
  servePortal("es");
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Movimientos" }));
  expect(screen.getByRole("main").getAttribute("lang")).toBe("es");
  expect(
    screen.getByRole("textbox", { name: "Buscar movimientos" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("combobox", { name: "Filtrar por estado" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Loja Sol.*Aprobado/s }));
  expect(
    screen.getByRole("dialog", { name: "Detalle del movimiento" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Revisar este cargo" }),
  ).toBeTruthy();
});

test("Portuguese charge review says when the Assistant is unavailable", async () => {
  const calls = servePortal("pt", false);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Movimentos" }));
  fireEvent.click(screen.getByRole("button", { name: /Loja Sol.*Aprovado/s }));
  const review = screen.getByRole("button", {
    name: "Revisar esta cobrança",
  }) as HTMLButtonElement;
  expect(review.disabled).toBe(true);
  expect(
    screen.getByText(/revisão assistida ainda não está disponível/),
  ).toBeTruthy();
  expect(screen.getByText(/Nenhum caso foi registrado/)).toBeTruthy();
  expect(calls.some((url) => url.startsWith("/api/action/"))).toBe(false);
});

test.each([
  [
    "pt",
    "pt-BR",
    "Olá, Bia",
    "Seus produtos, juntos.",
    "Cartão de débito",
    "Referência do produto",
    "Um cenário para explorar",
  ],
  [
    "es",
    "es",
    "Hola, Bia",
    "Tus productos, juntos.",
    "Tarjeta de débito",
    "Referencia del producto",
    "Un escenario para explorar",
  ],
] as const)(
  "%s Home, Products, detail and About use matching language and synthetic disclosure",
  async (
    language,
    locale,
    greeting,
    productHeading,
    productName,
    referenceLabel,
    aboutTitle,
  ) => {
    const calls = servePortal(language, false);
    render(<App />);
    const home = await screen.findByRole("heading", {
      name: new RegExp(greeting),
    });
    expect(home.closest("main")?.getAttribute("lang")).toBe(locale);
    expect(document.documentElement.lang).toBe(locale);
    expect(
      screen.getByRole("heading", {
        name: language === "pt" ? "Para onde vai" : "En qué se mueve",
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("img", {
        name:
          language === "pt"
            ? /Entradas e saídas identificadas/
            : /Entradas y salidas identificadas/,
      }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        language === "pt" ? "Total de saídas" : "Total de salidas",
      ),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", {
        name: language === "pt" ? /cobrança/ : /cargo/,
      }),
    );
    expect(
      screen.getByRole("heading", {
        name:
          language === "pt"
            ? "Seu dinheiro em movimento."
            : "Tu dinero en movimiento.",
      }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("dialog", {
        name: language === "pt" ? "Seu assistente Savia" : "Tu asistente Savia",
      }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", {
        name: language === "pt" ? "Início" : "Inicio",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: language === "pt" ? "Meus produtos" : "Mis productos",
      }),
    );
    expect(screen.getByRole("heading", { name: productHeading })).toBeTruthy();
    expect(screen.getByRole("main").getAttribute("lang")).toBe(locale);
    const product = screen.getByRole("button", {
      name: new RegExp(productName),
    });
    expect(product.getAttribute("lang")).toBe(locale);
    fireEvent.click(product);
    const detail = screen.getByRole("dialog", { name: productName });
    expect(detail.querySelector("h2")?.getAttribute("lang")).toBe(locale);
    expect(within(detail).getByText(referenceLabel)).toBeTruthy();
    expect(
      within(detail).getByText(
        language === "pt"
          ? /Não representa saldo bancário em tempo real/
          : /No representa un saldo bancario en tiempo real/,
      ),
    ).toBeTruthy();
    fireEvent.click(
      within(detail).getByRole("button", {
        name:
          language === "pt"
            ? "Ver movimentos deste produto"
            : "Ver movimientos de este producto",
      }),
    );
    expect(
      screen.getByRole("heading", {
        name:
          language === "pt"
            ? "Seu dinheiro em movimento."
            : "Tu dinero en movimiento.",
      }),
    ).toBeTruthy();
    expect(
      (
        screen.getByRole("combobox", {
          name:
            language === "pt" ? "Filtrar por produto" : "Filtrar por producto",
        }) as HTMLSelectElement
      ).value,
    ).toBe("card-1");
    const aboutTrigger = screen.getByRole("button", {
      name:
        language === "pt" ? "Sobre esta experiência" : "Sobre esta experiencia",
    });
    aboutTrigger.focus();
    fireEvent.click(aboutTrigger);
    const about = screen.getByRole("dialog", { name: aboutTitle });
    expect(about.querySelector("h2")?.getAttribute("lang")).toBe(locale);
    expect(
      within(about).getByText(
        language === "pt"
          ? /perfis, produtos, saldos e movimentos deste cenário foram criados pela equipe/
          : /perfiles, productos, saldos y movimientos de este escenario fueron creados por el equipo/,
      ),
    ).toBeTruthy();
    expect(
      within(about).getByText(
        language === "pt"
          ? /Assistente e o registro de casos não estão disponíveis/
          : /asistente y el registro de casos no están disponibles/,
      ),
    ).toBeTruthy();
    const closeButton = within(about).getByRole("button", {
      name: language === "pt" ? "Fechar" : "Cerrar",
    });
    closeButton.focus();
    expect(document.activeElement).toBe(closeButton);
    expect(
      fireEvent.keyDown(closeButton, { key: "Tab", cancelable: true }),
    ).toBe(false);
    expect(document.activeElement).toBe(closeButton);
    expect(
      fireEvent.keyDown(closeButton, {
        key: "Tab",
        shiftKey: true,
        cancelable: true,
      }),
    ).toBe(false);
    expect(document.activeElement).toBe(closeButton);
    fireEvent.click(closeButton);
    expect(screen.queryByRole("dialog", { name: aboutTitle })).toBeNull();
    expect(document.activeElement).toBe(aboutTrigger);
    expect(calls.some((url) => url.startsWith("/api/action/"))).toBe(false);
  },
);

test("Portuguese invite uses organizer source wording when metadata identifies organizer data", async () => {
  servePortal("pt", true, {
    ...portalOverview,
    metadata: {
      ...portalOverview.metadata,
      dataset: "organizer-synthetic-snapshot",
    },
  });
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Sobre esta experiência" }),
  );
  const about = screen.getByRole("dialog", {
    name: "Dados sintéticos do organizador",
  });
  expect(
    within(about).getByText(/conjunto de dados sintéticos do organizador/),
  ).toBeTruthy();
  expect(
    within(about).getByText(/Os nomes são apelidos de demonstração/),
  ).toBeTruthy();
  expect(
    within(about).queryByText(
      /Assistente e o registro de casos não estão disponíveis/,
    ),
  ).toBeNull();
});

const periodNames = [
  [
    "es",
    "Periodo de los movimientos",
    "Buscar movimientos",
    "Volver a intentar",
  ],
  ["pt", "Período dos movimentos", "Buscar movimentos", "Tentar novamente"],
] as const;

test.each(periodNames)(
  "%s period change restores focus after the chosen window loads",
  async (language, periodName) => {
    localStorage.setItem("flujo-bank-action-language", language);
    vi.stubGlobal("scrollTo", vi.fn());
    const calls: string[] = [];
    let resolveWeek!: (response: Response) => void;
    const pendingWeek = new Promise<Response>((resolve) => {
      resolveWeek = resolve;
    });
    const weekly = {
      ...portalOverview,
      transactions: [{ ...portalCharge, merchant: "Loja Semana" }],
      metadata: {
        ...portalOverview.metadata,
        period: "week",
        transactions_returned: 1,
        transactions_total: 1,
        filtered_count: 1,
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        calls.push(url);
        if (url === "/api/auth/me") return reply({ auth_mode: "invite" });
        if (url === "/api/overview") return reply(portalOverview);
        if (url === "/api/overview?period=week") return pendingWeek;
        if (url === "/api/chat/status")
          return reply({ available: false, sandbox_intake_available: false });
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: language === "pt" ? "Movimentos" : "Movimientos",
      }),
    );
    const period = () =>
      screen.getByRole("combobox", { name: periodName }) as HTMLSelectElement;
    expect(period().value).toBe("quarter");
    expect(
      Array.from(period().options).map((option) => [option.value, option.text]),
    ).toEqual([
      ["week", "Última semana"],
      ["month", language === "pt" ? "Último mês" : "Último mes"],
      ["quarter", "Últimos 3 meses"],
    ]);
    expect(document.querySelectorAll(".transaction-row")).toHaveLength(2);
    period().focus();
    fireEvent.change(period(), { target: { value: "week" } });
    expect(
      screen.getByLabelText(
        language === "pt" ? "Carregando dados" : "Cargando datos",
      ),
    ).toBeTruthy();
    expect(document.activeElement).toBe(document.body);
    await act(async () => resolveWeek(reply(weekly)));
    await waitFor(() => expect(period().value).toBe("week"));
    expect(document.activeElement).toBe(period());
    expect(document.querySelectorAll(".transaction-row")).toHaveLength(1);
    expect(screen.getByText("Loja Semana")).toBeTruthy();
    expect(screen.queryByText("Loja Lua")).toBeNull();
    expect(calls).toContain("/api/overview?period=week");
    expect(calls.filter((url) => url.includes("period=quarter"))).toEqual([]);
  },
);

test.each(periodNames)(
  "%s failed period fetch focuses the visible retry control",
  async (language, periodName, _searchName, retryName) => {
    localStorage.setItem("flujo-bank-action-language", language);
    vi.stubGlobal("scrollTo", vi.fn());
    let resolveWeek!: (response: Response) => void;
    const pendingWeek = new Promise<Response>((resolve) => {
      resolveWeek = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url === "/api/auth/me") return reply({ auth_mode: "invite" });
        if (url === "/api/overview") return reply(portalOverview);
        if (url === "/api/overview?period=week") return pendingWeek;
        if (url === "/api/chat/status")
          return reply({ available: false, sandbox_intake_available: false });
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: language === "pt" ? "Movimentos" : "Movimientos",
      }),
    );
    const period = screen.getByRole("combobox", { name: periodName });
    period.focus();
    fireEvent.change(period, { target: { value: "week" } });
    expect(document.activeElement).toBe(document.body);
    await act(async () => resolveWeek(reply({}, 503)));
    const retry = await screen.findByRole("button", { name: retryName });
    expect(document.activeElement).toBe(retry);
    expect(screen.getByRole("alert")).toBeTruthy();
  },
);

test.each(periodNames)(
  "%s period loading leaves focus on another chosen control",
  async (language, periodName, searchName) => {
    localStorage.setItem("flujo-bank-action-language", language);
    vi.stubGlobal("scrollTo", vi.fn());
    let resolveWeek!: (response: Response) => void;
    const pendingWeek = new Promise<Response>((resolve) => {
      resolveWeek = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url === "/api/auth/me") return reply({ auth_mode: "invite" });
        if (url === "/api/overview") return reply(portalOverview);
        if (url === "/api/overview?period=week") return pendingWeek;
        if (url === "/api/chat/status")
          return reply({ available: false, sandbox_intake_available: false });
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: language === "pt" ? "Movimentos" : "Movimientos",
      }),
    );
    const period = screen.getByRole("combobox", { name: periodName });
    period.focus();
    fireEvent.change(period, { target: { value: "week" } });
    const search = screen.getByRole("textbox", { name: searchName });
    search.focus();
    expect(document.activeElement).toBe(search);
    await act(async () =>
      resolveWeek(
        reply({
          ...portalOverview,
          transactions: [],
          metadata: {
            ...portalOverview.metadata,
            period: "week",
            transactions_returned: 0,
            transactions_total: 0,
            filtered_count: 0,
          },
        }),
      ),
    );
    await screen.findByRole("combobox", { name: periodName });
    expect(document.activeElement).toBe(search);
  },
);
