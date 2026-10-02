import type { ReactNode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../src/api";
import { translator } from "../src/i18n";
import type { Insights as InsightsData, Ledger } from "../src/types";
import { ShellContext, type Shell } from "../src/ui";
import Insights from "../src/views/Insights";
import Palette from "../src/views/Palette";
import { ledger, transaction } from "./fixtures";

const shell: Shell = {
  lang: "en", t: translator("en"), toast: vi.fn(), openTxn: vi.fn(), go: vi.fn(),
};
const inShell = (children: ReactNode) => <ShellContext.Provider value={shell}>{children}</ShellContext.Provider>;

function pending<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

function insights(currency: string, merchant: string): InsightsData {
  return {
    currency, currencies: ["COP", "USD"], categories: [], channels: [],
    completeness: [], repeat_merchants: [], series: [],
    merchants: [{ merchant, category: null, total: 100, count: 1, last_seen: "2026-01-15" }],
  };
}

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.clearAllMocks(); });

test.each(["success", "failure"] as const)("an older insights %s cannot replace the current currency", async (outcome) => {
  const old = pending<InsightsData>();
  const latest = pending<InsightsData>();
  let refreshing = false;
  const load = vi.spyOn(api, "insights").mockImplementation((currency) => {
    if (currency === "USD") return old.promise;
    if (currency === "COP" && refreshing) return latest.promise;
    return Promise.resolve(insights("COP", "Initial merchant"));
  });
  render(inShell(<Insights />));
  await screen.findByRole("button", { name: "USD" });
  refreshing = true;
  fireEvent.click(screen.getByRole("button", { name: "USD" }));
  fireEvent.click(screen.getByRole("button", { name: "COP" }));
  await act(async () => { latest.resolve(insights("COP", "Current merchant")); });
  await act(async () => {
    if (outcome === "success") old.resolve(insights("USD", "Obsolete merchant"));
    else old.reject(new Error("Obsolete currency failure"));
  });
  expect(screen.getByText("Current merchant")).toBeTruthy();
  expect(screen.queryByText("Obsolete merchant")).toBeNull();
  expect(screen.queryByText("Obsolete currency failure")).toBeNull();
  expect(screen.getByRole("button", { name: "COP" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("button", { name: "USD" }).getAttribute("aria-pressed")).toBe("false");
  expect(load).toHaveBeenCalledTimes(4);
});

function palette() {
  return render(inShell(<Palette onClose={vi.fn()} onNavigate={vi.fn()} onOpenTxn={vi.fn()} />));
}

async function search(query: string) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: query } });
  await act(async () => { vi.advanceTimersByTime(220); });
}

test.each(["success", "failure"] as const)("an older palette %s cannot replace the current query results", async (outcome) => {
  vi.useFakeTimers();
  const old = pending<Ledger>();
  const latest = pending<Ledger>();
  const load = vi.spyOn(api, "ledger").mockImplementation((filters) => filters.q === "old" ? old.promise : latest.promise);
  palette();
  await search("old");
  await search("current");
  await act(async () => { latest.resolve(ledger([transaction("CURRENT", "Current shop")])); });
  await act(async () => {
    if (outcome === "success") old.resolve(ledger([transaction("OLD", "Obsolete shop")]));
    else old.reject(new Error("Obsolete search failure"));
  });
  expect(screen.getByText("Current shop")).toBeTruthy();
  expect(screen.queryByText("Obsolete shop")).toBeNull();
  expect(load).toHaveBeenCalledTimes(2);
  expect(load.mock.calls[0][3]?.aborted).toBe(true);
});

test("clearing a query prevents an already dispatched search from restoring transactions", async () => {
  vi.useFakeTimers();
  const old = pending<Ledger>();
  const load = vi.spyOn(api, "ledger").mockReturnValue(old.promise);
  palette();
  await search("old");
  await search("");
  await act(async () => { old.resolve(ledger([transaction("OLD", "Obsolete shop")])); });
  expect(screen.queryByText("Obsolete shop")).toBeNull();
  expect(load).toHaveBeenCalledTimes(1);
  expect(load.mock.calls[0][3]?.aborted).toBe(true);
});

test("changing a query clears its previously published transactions during the debounce", async () => {
  vi.useFakeTimers();
  vi.spyOn(api, "ledger").mockResolvedValue(ledger([transaction("OLD", "Obsolete shop")]));
  palette();
  await search("old");
  expect(screen.getByText("Obsolete shop")).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "current" } });
  expect(screen.queryByText("Obsolete shop")).toBeNull();
});
