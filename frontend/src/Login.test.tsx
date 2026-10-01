import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import App, { Assistant, Login } from "./App";

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
      /a navegação e a consulta de movimentos estarão em português/,
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
    balances_by_currency: [],
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
    screen.getByText(/o Assistente segue o idioma escolhido aqui/),
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
  expect(document.documentElement.lang).toBe("es");
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
    screen.getByText(/o Assistente segue o idioma escolhido aqui/),
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
function servePortal(language: "es" | "pt", chatAvailable = true) {
  localStorage.setItem("flujo-bank-action-language", language);
  vi.stubGlobal("scrollTo", vi.fn());
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = String(input);
      calls.push(url);
      if (url === "/api/auth/me") return reply({ auth_mode: "invite" });
      if (url === "/api/overview") return reply(portalOverview);
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

test("Portuguese charge finder keeps labels and dialog names local while retaining Spanish document semantics", async () => {
  const calls = servePortal("pt");
  render(<App />);
  const navigation = await screen.findByRole("button", { name: "Movimentos" });
  expect(document.documentElement.lang).toBe("es");
  expect(navigation.closest("aside")?.getAttribute("lang")).toBe("pt-BR");
  expect(screen.getByRole("button", { name: "Início" })).toBeTruthy();
  expect(screen.getByRole("main").getAttribute("lang")).toBe("es");
  expect(screen.getByText(/Esta área e as informações.*espanhol/)).toBeTruthy();
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
  expect(screen.getByText(/área de produtos.*espanhol/)).toBeTruthy();
  expect(
    screen.getByRole("combobox", { name: "Filtrar por produto" }),
  ).toBeTruthy();
  const status = screen.getByRole("combobox", { name: "Filtrar por status" });
  fireEvent.change(status, { target: { value: "Pending" } });
  expect(
    screen.getByRole("button", { name: /Loja Lua.*Pendente/s }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Loja Sol/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
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
