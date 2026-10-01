import { useState, type ReactNode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../src/App";
import { api, clearSession, hasSession } from "../src/api";
import { translator } from "../src/i18n";
import { EMPTY_FILTERS, type Filters } from "../src/types";
import { ShellContext, type Shell } from "../src/ui";
import Home from "../src/views/Home";
import Movements from "../src/views/Movements";
import SignIn from "../src/views/SignIn";
import TxnDrawer from "../src/views/TxnDrawer";
import { deferred, detail, ledger, overview, profiles, reply, review, snapshot, transaction } from "./fixtures";

const shell: Shell = { lang: "en", t: translator("en"), toast: vi.fn(), openTxn: vi.fn(), go: vi.fn() };
const inShell = (children: ReactNode) => <ShellContext.Provider value={shell}>{children}</ShellContext.Provider>;

beforeEach(() => {
  clearSession();
  localStorage.clear();
  sessionStorage.clear();
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
});
afterEach(() => { cleanup(); clearSession(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks(); });

function LedgerHarness({ initial = EMPTY_FILTERS }: { initial?: Filters }) {
  const [filters, setFilters] = useState(initial);
  return inShell(<Movements filters={filters} setFilters={setFilters} />);
}

function finishQuestions() {
  for (let step = 0; step < 4; step += 1) {
    fireEvent.click(screen.getByRole("button", { name: "Yes" }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
  }
}

test("a delayed detail cannot replace the selected transaction or enable review while loading", async () => {
  const old = deferred<ReturnType<typeof detail>>();
  const latest = detail(transaction("TX-B", "Shop B"));
  vi.spyOn(api, "detail").mockImplementation((reference) => reference === "TX-A" ? old.promise : Promise.resolve(latest));
  const view = render(inShell(<TxnDrawer reference="TX-A" onClose={vi.fn()} />));
  expect(screen.getByRole("button", { name: "I do not recognise this movement" }).hasAttribute("disabled")).toBe(true);
  view.rerender(inShell(<TxnDrawer reference="TX-B" onClose={vi.fn()} />));
  await screen.findByRole("heading", { name: "Shop B" });
  await act(async () => { old.resolve(detail()); await old.promise; });
  expect(screen.queryByRole("heading", { name: "Shop A" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Shop B" })).toBeTruthy();
});

test("switching transactions clears reason and note, and requires the fifth answer", async () => {
  vi.spyOn(api, "detail").mockImplementation(async (reference) => detail(transaction(reference, `Shop ${reference}`)));
  const view = render(inShell(<TxnDrawer reference="TX-A" onClose={vi.fn()} />));
  await screen.findByRole("heading", { name: "Shop TX-A" });
  fireEvent.click(screen.getByRole("button", { name: "I do not recognise this movement" }));
  finishQuestions();
  expect(screen.getByRole("button", { name: "Create the record" }).hasAttribute("disabled")).toBe(true);
  fireEvent.change(screen.getByRole("combobox", { name: "Reason" }), { target: { value: "amount_wrong" } });
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Note about transaction A" } });
  view.rerender(inShell(<TxnDrawer reference="TX-B" onClose={vi.fn()} />));
  await screen.findByRole("heading", { name: "Shop TX-B" });
  fireEvent.click(screen.getByRole("button", { name: "I do not recognise this movement" }));
  finishQuestions();
  expect((screen.getByRole("combobox", { name: "Reason" }) as HTMLSelectElement).value).toBe("unrecognised_charge");
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("");
  fireEvent.click(screen.getByRole("button", { name: "Yes" }));
  expect(screen.getByRole("button", { name: "Create the record" }).hasAttribute("disabled")).toBe(false);
});

test("detail for a different reference cannot enable a review", async () => {
  vi.spyOn(api, "detail").mockResolvedValue(detail(transaction("TX-OTHER", "Other transaction")));
  const create = vi.spyOn(api, "openReview");
  render(inShell(<TxnDrawer reference="TX-A" onClose={vi.fn()} />));
  await screen.findByText("Something failed", { selector: "b" });
  const button = screen.getByRole("button", { name: "I do not recognise this movement" });
  expect(button.hasAttribute("disabled")).toBe(true);
  fireEvent.click(button);
  expect(create).not.toHaveBeenCalled();
  expect(screen.queryByRole("heading", { name: "Other transaction" })).toBeNull();
});

test("a review submitted for A cannot replace B's drawer with A's receipt", async () => {
  vi.spyOn(api, "detail").mockImplementation(async (reference) => detail(transaction(reference, `Shop ${reference}`)));
  const pending = deferred<ReturnType<typeof review>>();
  const create = vi.spyOn(api, "openReview").mockReturnValue(pending.promise);
  const view = render(inShell(<TxnDrawer reference="TX-A" onClose={vi.fn()} />));
  await screen.findByRole("heading", { name: "Shop TX-A" });
  fireEvent.click(screen.getByRole("button", { name: "I do not recognise this movement" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /My card is lost or stolen/ }));
  fireEvent.click(screen.getByRole("button", { name: "Create the record" }));
  expect(create).toHaveBeenCalledWith(expect.objectContaining({ reference: "TX-A", urgent: true, answers: {} }));
  view.rerender(inShell(<TxnDrawer reference="TX-B" onClose={vi.fn()} />));
  await screen.findByRole("heading", { name: "Shop TX-B" });
  await act(async () => { pending.resolve(review()); await pending.promise; });
  expect(screen.queryByText("REV-FIXTURE")).toBeNull();
  expect(screen.getByRole("button", { name: "I do not recognise this movement" })).toBeTruthy();
});

test("the urgent receipt is translated and retains the local-only action boundaries", async () => {
  vi.spyOn(api, "detail").mockResolvedValue(detail());
  vi.spyOn(api, "openReview").mockResolvedValue(review());
  render(inShell(<TxnDrawer reference="TX-A" onClose={vi.fn()} />));
  await screen.findByRole("heading", { name: "Shop A" });
  fireEvent.click(screen.getByRole("button", { name: "I do not recognise this movement" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /My card is lost or stolen/ }));
  fireEvent.click(screen.getByRole("button", { name: "Create the record" }));
  await screen.findByText("REV-FIXTURE");
  expect(screen.getByText("Security concern")).toBeTruthy();
  expect(screen.getByText("No dispute or chargeback was opened.")).toBeTruthy();
  const receipt = JSON.parse(document.querySelector(".receipt-json")!.textContent!);
  expect(receipt.local_only).toBe(true);
  expect(receipt.bank_action_taken).toBe(false);
  expect(receipt.dispute_submitted).toBe(false);
  expect(receipt.agent_transfer).toBe(false);
});

test("old paging cannot append rows or restore metadata after a filter change", async () => {
  vi.spyOn(api, "overview").mockResolvedValue(overview);
  const oldPage = deferred<ReturnType<typeof ledger>>();
  vi.spyOn(api, "ledger").mockImplementation(async (filters, offset) => {
    if (offset) return oldPage.promise;
    return filters.flags?.includes("pending")
      ? ledger([{ ...transaction("TX-P", "Pending shop"), status: "Pending", settled: false }])
      : ledger([transaction()], 40);
  });
  render(<LedgerHarness />);
  await screen.findByText("Shop A");
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  fireEvent.click(screen.getByRole("button", { name: "Pending" }));
  await screen.findByText("Pending shop");
  await act(async () => { oldPage.resolve(ledger([transaction("TX-OLD", "Old page")], 80)); await oldPage.promise; });
  expect(screen.queryByText("Old page")).toBeNull();
  expect(screen.queryByText("Shop A")).toBeNull();
  expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  expect(screen.getByText("Pending shop")).toBeTruthy();
});

test("amount sorting preserves API order across different months", async () => {
  vi.spyOn(api, "overview").mockResolvedValue(overview);
  const rows = [transaction("TX-1", "Largest", 100),
    { ...transaction("TX-2", "Middle", 90), event_date: "2026-02-15" },
    transaction("TX-3", "Smallest", 80)];
  vi.spyOn(api, "ledger").mockResolvedValue(ledger(rows));
  const view = render(<LedgerHarness initial={{ ...EMPTY_FILTERS, sort: "amount_desc" }} />);
  await screen.findByText("Smallest");
  expect([...view.container.querySelectorAll(".row-title")].map((node) => node.textContent))
    .toEqual(["Largest", "Middle", "Smallest"]);
});

test("sign-in retries catalogue loading without changing language", async () => {
  const load = vi.spyOn(api, "profiles").mockRejectedValueOnce(new Error("temporary outage")).mockResolvedValue(profiles);
  vi.spyOn(api, "snapshot").mockResolvedValue(snapshot);
  render(<SignIn lang="en" setLang={vi.fn()} onSignedIn={vi.fn()} />);
  await screen.findByText(/temporary outage/);
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText("Demo A");
  expect(load).toHaveBeenCalledTimes(2);
});

test("movements retries the same filters after a temporary error", async () => {
  vi.spyOn(api, "overview").mockResolvedValue(overview);
  const load = vi.spyOn(api, "ledger").mockRejectedValueOnce(new Error("temporary outage")).mockResolvedValue(ledger());
  render(<LedgerHarness />);
  await screen.findByText(/temporary outage/);
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText("Shop A");
  expect(load).toHaveBeenCalledTimes(2);
});

test("an API 401 returns the portal to sign-in and clears the profile session", async () => {
  localStorage.setItem("savia.lang", "en");
  vi.spyOn(api, "profiles").mockResolvedValue(profiles);
  vi.spyOn(api, "snapshot").mockResolvedValue(snapshot);
  vi.spyOn(api, "signals").mockResolvedValue({ found: [], clear: [] });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/session"
    ? reply({ token: "fixture-session" }) : reply({ detail: "expired" }, 401)));
  await api.signIn("ar-premium");
  render(<App />);
  await screen.findByRole("heading", { name: "Sign in to your bank" });
  expect(hasSession()).toBe(false);
  expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
});

test("nullable balances stay unknown and do not acquire a utilization percentage", async () => {
  vi.spyOn(api, "overview").mockResolvedValue({ ...overview,
    balances: [{ ...overview.balances[0], deposit: null, credit: null, credit_limit: null }] });
  vi.spyOn(api, "signals").mockResolvedValue({ found: [], clear: [] });
  const view = render(inShell(<Home onAlias={vi.fn()} />));
  await screen.findByRole("heading", { name: "Hello, Demo" });
  await waitFor(() => expect(view.container.querySelector(".kpi-value")?.textContent).toBe("—"));
  expect(view.container.querySelector(".kpi-row b")?.textContent).toBe("—");
  expect(view.container.querySelector(".kpi .meter")).toBeNull();
});

test.each([
  ["es", "Asunto de seguridad"], ["pt", "Assunto de segurança"], ["en", "Security concern"],
] as const)("%s translates the urgent review reason", (lang, label) => {
  expect(translator(lang)("rev.reason.security_concern")).toBe(label);
});
