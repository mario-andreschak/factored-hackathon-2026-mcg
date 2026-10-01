/**
 * Savia Lite - boot guard.
 *
 * Loaded before the app module. If a module fails to parse or throws while
 * starting up, a blank page is the worst possible outcome for somebody testing
 * a demo, so this prints the actual error on screen instead.
 */

let reported = false;

function show(kind, detail) {
  if (reported) return;
  reported = true;
  const root = document.getElementById("root");
  if (!root) return;
  while (root.firstChild) root.firstChild.remove();

  const box = document.createElement("div");
  box.className = "boot-error";
  box.setAttribute("role", "alert");

  const title = document.createElement("strong");
  title.textContent = `Savia Lite could not start (${kind})`;

  const pre = document.createElement("pre");
  pre.textContent = detail;

  const hint = document.createElement("p");
  hint.style.cssText = "margin:12px 0 0;font-size:.85rem;opacity:.9";
  hint.textContent =
    "Run \"python serve.py\" and open the address it prints, instead of opening "
    + "this file directly. To see what broke: node tools/selfcheck.mjs";

  box.append(title, pre, hint);
  root.append(box);
}

addEventListener("error", (event) => {
  show("script error", `${event.message}\n${event.filename || ""}:${event.lineno || "?"}`);
});

addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  show("promise rejection", String(reason && reason.stack ? reason.stack : reason));
});

// If the app never rendered anything, say so rather than showing a blank page.
addEventListener("load", () => {
  setTimeout(() => {
    const root = document.getElementById("root");
    if (root && root.childElementCount === 0) {
      show("no render", "The application module loaded but produced no output.");
    }
  }, 600);
});
