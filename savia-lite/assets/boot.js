/**
 * Savia Lite - boot guard.
 *
 * Loaded before the app. If a module fails to parse or throws during start-up,
 * a blank page is the worst possible outcome for someone testing a demo, so
 * this prints the actual error on screen instead.
 */

function show(kind, detail) {
  const root = document.getElementById("root");
  if (!root) return;
  root.innerHTML = "";
  const box = document.createElement("div");
  box.setAttribute("role", "alert");
  box.style.cssText =
    "max-width:70ch;margin:56px auto;padding:22px 24px;border:1px solid #f0c6bf;" +
    "border-radius:16px;background:#fae8e5;color:#93342b;font-family:system-ui,sans-serif";
  const title = document.createElement("strong");
  title.textContent = "Savia Lite could not start (" + kind + ")";
  const pre = document.createElement("pre");
  pre.style.cssText = "white-space:pre-wrap;overflow-wrap:anywhere;margin:12px 0 0;font-size:.85rem";
  pre.textContent = detail;
  const hint = document.createElement("p");
  hint.style.cssText = "margin:12px 0 0;font-size:.85rem;opacity:.85";
  hint.textContent =
    "Serve the folder over http:// rather than opening the file directly, " +
    "or run: node tools/selfcheck.mjs";
  box.append(title, pre, hint);
  root.append(box);
}

addEventListener("error", (event) => {
  show("script error", `${event.message}\n${event.filename || ""}:${event.lineno || "?"}`);
});
addEventListener("unhandledrejection", (event) => {
  show("promise rejection", String(event.reason && event.reason.stack ? event.reason.stack : event.reason));
});

// If the app never renders, say so rather than showing an empty page.
addEventListener("load", () => {
  setTimeout(() => {
    const root = document.getElementById("root");
    if (root && root.childElementCount === 0) {
      show("no render", "The application module loaded but produced no output.");
    }
  }, 900);
});
