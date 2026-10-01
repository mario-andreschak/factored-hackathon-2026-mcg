/**
 * Savia Lite - DOM and focus utilities.
 *
 * A deliberately small hyperscript plus the two accessibility behaviours that
 * are easy to get wrong by hand: trapping focus inside a dialog, and giving it
 * back to whatever opened the dialog.
 */

/** Creates an element. `html` is only ever used with strings this app owns. */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "style") el.setAttribute("style", value);
    else if (key === "value") el.value = value;
    else if (key === "checked") el.checked = Boolean(value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  append(el, children);
  return el;
}

export function frag(...children) {
  const f = document.createDocumentFragment();
  append(f, children);
  return f;
}

function append(parent, children) {
  for (const child of children.flat(6)) {
    if (child === null || child === undefined || child === false || child === "") continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(node) {
  while (node.firstChild) node.firstChild.remove();
}

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled])",
  "select:not([disabled])", "textarea:not([disabled])", "[tabindex]:not([tabindex='-1'])",
].join(",");

export const focusables = (root) =>
  [...root.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);

/**
 * Keeps Tab inside `container` while it is open. Returns an unbind function.
 * Focusing is deliberately a separate call, so a re-render can rebind the
 * listener to the new node without yanking focus away from what the person
 * is currently using.
 */
export function bindTabCycle(container) {
  function onKeyDown(event) {
    if (event.key !== "Tab") return;
    const items = focusables(container);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
  container.addEventListener("keydown", onKeyDown);
  return () => container.removeEventListener("keydown", onKeyDown);
}

/** Moves focus into a freshly opened surface. */
export function focusFirst(container) {
  const target = container.querySelector("[data-autofocus]") || focusables(container)[0];
  if (target) target.focus();
  return Boolean(target);
}
