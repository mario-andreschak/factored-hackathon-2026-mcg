import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Assistant } from "../App";
import { spokenText } from "./useSaviaVoice";

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

function open(status: {
  available: boolean;
  voice?: { available: boolean; conversation?: boolean; persona?: "moss" };
}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/chat/history")
        return new Response(JSON.stringify({ active: false, messages: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      throw new Error(`Unexpected request: ${input}`);
    }),
  );
  return render(
    <Assistant
      open
      status={status}
      selected={null}
      transactions={[]}
      onSelectTransaction={vi.fn()}
      hidden={false}
      synthetic
      onClose={vi.fn()}
      onExpired={vi.fn()}
      initialLanguage="es"
    />,
  );
}

test("the assistant shows the eyes, and offers voice only when the server does", async () => {
  const view = open({ available: true });
  await screen.findByText("Vamos a entender tus movimientos.");
  expect(document.querySelector("[data-phase='idle']")).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Hablar con Savia" })).toBeNull();
  view.unmount();

  open({ available: true, voice: { available: true } });
  await screen.findByText("Vamos a entender tus movimientos.");
  expect(
    screen.getByRole("button", { name: "Hablar con Savia" }),
  ).toHaveProperty("ariaPressed", "false");
});

test("the calm persona's eyes are the default, with or without the conversational voice", async () => {
  open({ available: true, voice: { available: true } });
  await screen.findByText("Vamos a entender tus movimientos.");
  expect(document.querySelector("[data-avatar='moss']")).not.toBeNull();
  cleanup();
  open({
    available: true,
    voice: { available: true, conversation: true, persona: "moss" },
  });
  await screen.findByText("Vamos a entender tus movimientos.");
  expect(document.querySelector("[data-avatar='moss']")).not.toBeNull();
});

test("a browser without a microphone explains itself and keeps the chat usable", async () => {
  open({ available: true, voice: { available: true } });
  await screen.findByText("Vamos a entender tus movimientos.");
  fireEvent.click(screen.getByRole("button", { name: "Hablar con Savia" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Puedes escribir",
  );
  expect(
    screen.getByRole("textbox", { name: "Mensaje para el asistente" }),
  ).toHaveProperty("disabled", false);
});

test("spoken text drops markdown and internal references", () => {
  expect(
    spokenText(
      "**Tu cargo** de `42.00` fue [recibido](https://x.test).\n- Referencia txn_aaaaaaaaaaaaaaaaaaaaaaaa",
    ),
  ).toBe("Tu cargo de 42.00 fue recibido. Referencia");
});
