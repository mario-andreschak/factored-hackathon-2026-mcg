import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { CardBlockControl } from "./CardBlockControl";
import type { Product } from "./types";

const card: Product = {
  reference: "prod_" + "a".repeat(24),
  type: "Tarjeta Crédito",
  currency: "MXN",
  balance: 100,
  balance_kind: "credit",
  credit_limit: 1000,
  interest_rate: null,
  status: "Active",
  opened_at: "2025-01-01",
  last_updated: "2026-10-05",
};
const pending = {
  state: "pending_confirmation",
  product_reference: card.reference,
  pending_handle: "card_" + "b".repeat(43),
  simulated: true,
  real_bank_action: false,
  message: "Confirma la tarjeta.",
};
const blocked = {
  ...pending,
  state: "card_block_verified",
  message: "Tarjeta ficticia bloqueada; banco real sin cambios.",
  receipt: {
    schema: "savia-simulated-card-block/v1",
    id: "BLK-SBX-12345678",
    status: "blocked",
    simulated: true,
    real_bank_action: false,
    created_at: "2026-10-05T16:00:00Z",
  },
};
const unblocked = {
  state: "card_unblocked",
  product_reference: card.reference,
  simulated: true,
  real_bank_action: false,
  message: "Sin bloqueo confirmado.",
};
const fetchMock = vi.fn();
function respond(body: unknown, status = 200) {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}
beforeEach(() => {
  sessionStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("preparation does not confirm; explicit confirmation shows verified receipt and narrates", async () => {
  const narrate = vi.fn();
  respond(unblocked);
  respond(pending);
  respond(blocked);
  render(
    <CardBlockControl
      products={[card]}
      language="es"
      requested
      onResult={narrate}
    />,
  );
  await waitFor(() =>
    expect(
      (screen.getByText("Preparar bloqueo") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByText("Preparar bloqueo"));
  await screen.findByText("Confirmar bloqueo de mi tarjeta");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).operation).toBe("prepare");
  expect(narrate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Confirmar bloqueo de mi tarjeta"));
  await screen.findByText("Bloqueada · estado verificado");
  expect(screen.getByText("BLK-SBX-12345678")).toBeTruthy();
  expect(JSON.parse(fetchMock.mock.calls[2][1].body).confirmed).toBe(true);
  expect(narrate).toHaveBeenCalledWith(blocked.message);
});

test("uncertain confirmation can only recover status and never retries the write", async () => {
  respond(unblocked);
  respond(pending);
  respond({ detail: "timeout" }, 504);
  respond(blocked);
  render(<CardBlockControl products={[card]} language="es" requested />);
  await waitFor(() =>
    expect(
      (screen.getByText("Preparar bloqueo") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByText("Preparar bloqueo"));
  fireEvent.click(await screen.findByText("Confirmar bloqueo de mi tarjeta"));
  await screen.findByRole("alert");
  expect(screen.queryByText("Confirmar bloqueo de mi tarjeta")).toBeNull();
  fireEvent.click(screen.getByText("Consultar estado guardado"));
  await screen.findByText("Bloqueada · estado verificado");
  expect(
    fetchMock.mock.calls.map((call) => JSON.parse(call[1].body).operation),
  ).toEqual(["status", "prepare", "confirm", "receipt"]);
});

test("invalid receipt never displays or speaks success", async () => {
  const narrate = vi.fn();
  respond(unblocked);
  respond(pending);
  respond({ ...blocked, receipt: { ...blocked.receipt, id: "unverified" } });
  render(
    <CardBlockControl
      products={[card]}
      language="pt"
      requested
      onResult={narrate}
    />,
  );
  await waitFor(() =>
    expect(
      (screen.getByText("Preparar bloqueio") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByText("Preparar bloqueio"));
  fireEvent.click(await screen.findByText("Confirmar bloqueio do meu cartão"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(screen.queryByText("Bloqueado · estado verificado")).toBeNull();
  expect(narrate).not.toHaveBeenCalled();
});

test("expired prepared intent offers a new explicit preparation", async () => {
  respond(unblocked);
  respond(pending);
  respond({ ...pending, pending_handle: undefined, state: "expired" });
  respond(pending);
  render(<CardBlockControl products={[card]} language="es" requested />);
  await waitFor(() =>
    expect(
      (screen.getByText("Preparar bloqueo") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByText("Preparar bloqueo"));
  await screen.findByText("Confirmar bloqueo de mi tarjeta");
  fireEvent.click(screen.getByText("Consultar estado guardado"));
  fireEvent.click(await screen.findByText("Preparar nueva confirmación"));
  await screen.findByText("Confirmar bloqueo de mi tarjeta");
  expect(
    fetchMock.mock.calls.map((call) => JSON.parse(call[1].body).operation),
  ).toEqual(["status", "prepare", "receipt", "prepare"]);
});

test("fresh browser reads durable blocked status without a confirm", async () => {
  const narrate = vi.fn();
  respond(blocked);
  render(
    <CardBlockControl
      products={[card]}
      language="es"
      requested
      onResult={narrate}
    />,
  );
  await screen.findByText("Bloqueada · estado verificado");
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).operation).toBe("status");
  expect(screen.queryByText("Preparar bloqueo")).toBeNull();
  expect(narrate).not.toHaveBeenCalled();
});

test("renewed session safely clears a server-rejected old prepared handle", async () => {
  sessionStorage.setItem(
    `savia.card-block.profile.${card.reference}`,
    pending.pending_handle,
  );
  respond({ ...unblocked, pending_handle_current: false });
  render(
    <CardBlockControl
      products={[card]}
      language="es"
      profileId="profile"
      requested
    />,
  );
  await waitFor(() =>
    expect(
      (screen.getByText("Preparar bloqueo") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  expect(
    sessionStorage.getItem(`savia.card-block.profile.${card.reference}`),
  ).toBeNull();
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).pending_handle).toBe(
    pending.pending_handle,
  );
});
