import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api, clearSession, hasSession, subscribeSession } from "../src/api";
import { EMPTY_FILTERS } from "../src/types";
import { deferred, reply } from "./fixtures";

beforeEach(() => { clearSession(); sessionStorage.clear(); });
afterEach(() => { clearSession(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test.each(["overview", "csv"])("%s 401 clears the session and notifies subscribers", async (kind) => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/session"
    ? reply({ token: "session-a" }) : reply({ detail: "expired" }, 401)));
  await api.signIn("ar-premium");
  const listener = vi.fn();
  const unsubscribe = subscribeSession(listener);
  try {
    const request = kind === "csv" ? api.downloadCsv(EMPTY_FILTERS, "fixture.csv") : api.overview();
    await expect(request).rejects.toMatchObject({ status: 401 });
    expect(hasSession()).toBe(false);
    expect(sessionStorage.getItem("savia.session")).toBeNull();
    expect(listener).toHaveBeenCalledTimes(1);
  } finally { unsubscribe(); }
});

test.each([200, 401])("a delayed old-session %s response cannot publish data or revoke a new session", async (status) => {
  const oldResponse = deferred<Response>();
  let sessions = 0;
  vi.stubGlobal("fetch", vi.fn((url: string) => url === "/api/session"
    ? Promise.resolve(reply({ token: `session-${++sessions}` })) : oldResponse.promise));
  await api.signIn("ar-premium");
  const pending = api.overview();
  await api.signIn("co-plus");
  oldResponse.resolve(reply({ customer: { alias: "old profile" } }, status));
  await expect(pending).rejects.toMatchObject({ status: 401, message: "session changed" });
  expect(hasSession()).toBe(true);
  expect(sessionStorage.getItem("savia.session")).toBe("session-2");
});
