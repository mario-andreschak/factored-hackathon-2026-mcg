/**
 * Savia Lite - a zero-dependency customer banking portal.
 *
 * No framework, no bundler, no network calls. Everything the screens show is
 * produced by assets/data.js inside this browser tab.
 *
 * Wording rules this file is built around:
 *  - a pending charge is never described as settled;
 *  - a reversal is never described as a refund that arrived;
 *  - an absent merchant stays unknown instead of being guessed;
 *  - a duplicate-looking pair is a question, never a fraud finding;
 *  - no screen claims a bank action, a dispute, an agent transfer or a deadline.
 */

import { PROFILES, buildAccount, DATASET } from "./data.js";
import { LANGUAGES, createTranslator } from "./i18n.js";
import {
  dayKey, monthKey, formatDay, formatDayTime, formatMonth,
  formatMoney, formatNumber, signedMoney, toCsv,
} from "./format.js";

/* ==================================================================== *
 * Tiny hyperscript. Enough to build the whole portal, small enough to read.
 * ==================================================================== */
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "html") el.innerHTML = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "value") el.value = value;
    else if (key === "checked") el.checked = Boolean(value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(4)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}
const frag = (...children) => {
  const f = document.createDocumentFragment();
  for (const c of children.flat(4)) if (c !== null && c !== undefined && c !== false) {
    f.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return f;
};

/* ==================================================================== *
 * State
 * ==================================================================== */
const STORE_KEY = "savia-lite/preferences";
const emptyFilters = () => ({
  query: "", product: "", type: "", status: "", channel: "",
  currency: "", direction: "", from: "", to: "", min: "", max: "",
  sort: "dateDesc",
});

const state = {
  language: "es",
  theme: "light",
  bannerDismissed: false,
  profileId: PROFILES[0].id,
  signedIn: false,
  view: "overview",
  account: null,
  selectedId: null,
  filters: emptyFilters(),
  dialog: null,       // null | "triage" | "summary" | "help"
  triage: null,
  summary: null,
  toast: null,
};

function loadPreferences() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (LANGUAGES.some((l) => l.code === saved.language)) state.language = saved.language;
    if (saved.theme === "dark" || saved.theme === "light") state.theme = saved.theme;
    state.bannerDismissed = Boolean(saved.bannerDismissed);
  } catch { /* preferences are cosmetic; ignore unreadable storage */ }
}
function savePreferences() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      language: state.language, theme: state.theme, bannerDismissed: state.bannerDismissed,
    }));
  } catch { /* private mode - keep running without persistence */ }
}

let t = createTranslator(state.language);
function setLanguage(code) {
  state.language = code;
  t = createTranslator(code);
  document.documentElement.lang = code;
  savePreferences();
  render();
}
function setTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  savePreferences();
  render();
}

let toastTimer = null;
function toast(message) {
  state.toast = message;
  render();
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { state.toast = null; render(); }, 2400);
}

/* ==================================================================== *
 * Derived data
 * ==================================================================== */
const productLabel = (product) => t(product.label_key);

function selectedTransaction() {
  if (!state.account || !state.selectedId) return null;
  return state.account.transactions.find((x) => x.transaction_id === state.selectedId) || null;
}

function visibleTransactions() {
  const { transactions, productById } = state.account;
  const f = state.filters;
  const needle = f.query.trim().toLowerCase();
  const min = f.min === "" ? null : Number(f.min);
  const max = f.max === "" ? null : Number(f.max);

  const rows = transactions.filter((x) => {
    if (f.product && x.product_id !== f.product) return false;
    if (f.type && x.transaction_type !== f.type) return false;
    if (f.status && x.transaction_status !== f.status) return false;
    if (f.channel && x.channel !== f.channel) return false;
    if (f.currency && x.currency !== f.currency) return false;
    if (f.direction && x.direction !== f.direction) return false;
    if (f.from && dayKey(x.transaction_date) < f.from) return false;
    if (f.to && dayKey(x.transaction_date) > f.to) return false;
    if (min !== null && !Number.isNaN(min) && x.amount < min) return false;
    if (max !== null && !Number.isNaN(max) && x.amount > max) return false;
    if (needle) {
      const product = productById.get(x.product_id);
      const haystack = [
        x.merchant_name || "", x.transaction_id, x.transaction_type, x.channel,
        x.transaction_city || "", x.transaction_category || "", x.currency,
        t(`type.${x.transaction_type}`), t(`channel.${x.channel}`),
        t(`status.${x.transaction_status}`), product ? productLabel(product) : "",
      ].join(" ").toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });

  const by = {
    dateDesc: (a, b) => (a.transaction_date < b.transaction_date ? 1 : a.transaction_date > b.transaction_date ? -1 : 0),
    dateAsc:  (a, b) => (a.transaction_date > b.transaction_date ? 1 : a.transaction_date < b.transaction_date ? -1 : 0),
    amountDesc: (a, b) => b.amount - a.amount,
    amountAsc:  (a, b) => a.amount - b.amount,
  };
  return rows.sort(by[state.filters.sort] || by.dateDesc);
}

function balancesByCurrency() {
  const map = new Map();
  for (const p of state.account.products) {
    if (!map.has(p.currency)) map.set(p.currency, { currency: p.currency, deposit: 0, credit: 0, investment: 0 });
    const tile = map.get(p.currency);
    if (p.balance_kind === "deposit") tile.deposit += p.current_balance;
    else if (p.balance_kind === "credit") tile.credit += p.current_balance;
    else tile.investment += p.current_balance;
  }
  return [...map.values()].sort((a, b) => a.currency.localeCompare(b.currency));
}

/** Last 30 processing days of the scenario, in the profile's main currency. */
function activityWindow() {
  const currency = state.account.profile.primary_currency;
  const end = DATASET.latest_process_date;
  const endNum = Date.parse(end + "T00:00:00Z");
  const days = [];
  for (let i = 29; i >= 0; i -= 1) {
    days.push(new Date(endNum - i * 86400000).toISOString().slice(0, 10));
  }
  const buckets = new Map(days.map((d) => [d, { day: d, in: 0, out: 0, unknown: 0, count: 0 }]));
  for (const x of state.account.transactions) {
    if (x.currency !== currency) continue;
    if (x.transaction_status === "Rechazada") continue;
    const bucket = buckets.get(x.process_date);
    if (!bucket) continue;
    bucket.count += 1;
    if (x.direction === "credit") bucket.in += x.amount;
    else if (x.direction === "debit") bucket.out += x.amount;
    else bucket.unknown += x.amount;
  }
  const list = [...buckets.values()];
  const peak = Math.max(1, ...list.map((b) => Math.max(b.in, b.out)));
  const totals = list.reduce(
    (acc, b) => ({ in: acc.in + b.in, out: acc.out + b.out, unknown: acc.unknown + b.unknown }),
    { in: 0, out: 0, unknown: 0 }
  );
  return { list, peak, totals, currency };
}

/** Things worth showing on the overview. Observations only, in plain words. */
function attentionItems() {
  const out = [];
  const seenDuplicateKeys = new Set();
  for (const x of state.account.transactions) {
    if (state.account.duplicates.has(x.transaction_id)) {
      const key = [x.merchant_name, x.amount, x.currency].join("|");
      if (!seenDuplicateKeys.has(key)) {
        seenDuplicateKeys.add(key);
        out.push({ kind: "duplicate", transaction: x });
      }
      continue;
    }
    if (x.transaction_status === "Pendiente") out.push({ kind: "pending", transaction: x });
    else if (x.transaction_status === "Reversada") out.push({ kind: "reversed", transaction: x });
    else if (x.scenario === "opaque_descriptor") out.push({ kind: "opaque", transaction: x });
  }
  const rank = { duplicate: 0, opaque: 1, pending: 2, reversed: 3 };
  return out.sort((a, b) => rank[a.kind] - rank[b.kind]).slice(0, 4);
}

/* ==================================================================== *
 * Small shared pieces
 * ==================================================================== */
const STATUS_TONE = { Aprobada: "chip-ok", Pendiente: "chip-warn", Reversada: "chip-info", Rechazada: "chip-stop" };
const TYPE_GLYPH = {
  Compra: "🛍", Retiro: "🏧", Deposito: "↓", Transferencia: "⇄", Pago: "◷", Ajuste: "⤺",
};

const statusChip = (x) => h("span", { class: `chip ${STATUS_TONE[x.transaction_status] || "chip-soft"}` }, t(`status.${x.transaction_status}`));

function merchantText(x) {
  return x.merchant_name ? { text: x.merchant_name, unknown: false } : { text: t("tx.unknownMerchant"), unknown: true };
}

function closeButton(onClose) {
  return h("button", { class: "icon-btn", type: "button", "aria-label": t("a11y.close"), onClick: onClose }, "✕");
}

function field(labelKey, control) {
  return h("label", { class: "filter" }, h("span", { class: "field-label" }, t(labelKey)), control);
}

function selectControl(value, options, onChange, includeAll = true) {
  return h("select", { value, onChange: (e) => onChange(e.target.value) },
    includeAll ? h("option", { value: "" }, t("mov.all")) : null,
    options.map((o) => h("option", { value: o.value, selected: o.value === value }, o.label)));
}

/* ==================================================================== *
 * Sign-in
 * ==================================================================== */
function renderGate() {
  return h("div", { class: "gate" },
    h("div", { class: "gate-card" },
      h("div", { class: "gate-head" },
        h("div", {},
          h("span", { class: "brand" },
            h("span", { class: "brand-word" }, "savia"),
            h("span", { class: "brand-dot" }, "."),
            h("span", { class: "brand-lite" }, "lite")),
          h("p", { class: "gate-tag" }, t("app.tagline"), " · ", t("app.subtitle"))),
        h("div", { style: "min-width:150px" },
          field("login.language", selectControl(state.language,
            LANGUAGES.map((l) => ({ value: l.code, label: l.native })), setLanguage, false)))),

      h("h1", {}, t("login.title")),
      h("p", { class: "gate-lead" }, t("login.lead")),

      h("span", { class: "field-label" }, t("login.choose")),
      h("div", { class: "profile-grid", role: "group", "aria-label": t("login.choose") },
        PROFILES.map((p) => h("button", {
          type: "button", class: "profile-option",
          "aria-pressed": String(p.id === state.profileId),
          onClick: () => {
            state.profileId = p.id;
            if (p.language !== state.language) setLanguage(p.language); else render();
          },
        },
          h("span", { class: "avatar", "aria-hidden": "true" }, p.initials),
          h("span", {},
            h("span", { class: "profile-name" }, p.alias),
            h("br"),
            h("span", { class: "profile-meta" },
              `${p.city}, ${p.country} · ${t("login.segment")}: ${p.segment}`)),
          h("span", { class: "profile-cur" }, p.primary_currency)))),

      h("div", { class: "gate-row" },
        h("button", { class: "btn", type: "button", onClick: signIn }, t("login.enter"), " →"),
        h("button", { class: "btn-ghost btn", type: "button", onClick: () => openDialog("help") }, t("nav.help"))),

      h("p", { class: "gate-note" }, t("login.note")),
      h("p", { class: "gate-note" }, t("help.dataset.window", { start: DATASET.window_start, end: DATASET.window_end }))));
}

function signIn() {
  state.account = buildAccount(state.profileId);
  state.signedIn = true;
  state.view = "overview";
  state.selectedId = null;
  state.filters = emptyFilters();
  render();
}
function signOut() {
  // Nothing to revoke: no session, no server, no stored customer data.
  state.signedIn = false;
  state.account = null;
  state.selectedId = null;
  state.summary = null;
  state.triage = null;
  state.dialog = null;
  state.filters = emptyFilters();
  render();
}

/* ==================================================================== *
 * Overview
 * ==================================================================== */
function renderOverview() {
  const { profile, products } = state.account;
  const activity = activityWindow();
  const attention = attentionItems();
  const recent = state.account.transactions.slice(0, 6);

  return frag(
    h("div", { class: "page-head" },
      h("h1", {}, t("overview.greeting", { name: profile.alias.split(" ")[0] })),
      h("p", { class: "muted" }, t("overview.asof", { date: formatDay(DATASET.latest_process_date, state.language) }))),

    h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, t("overview.totals"))),
      h("div", { class: "grid-3" },
        balancesByCurrency().map((tile) => h("div", { class: "balance-tile" },
          h("div", { class: "balance-cur" }, tile.currency),
          h("div", { class: "balance-val" },
            formatMoney(tile.deposit + tile.investment, tile.currency, state.language)),
          h("div", { class: "balance-split" },
            tile.credit > 0
              ? `${t("product.owed")}: ${formatMoney(tile.credit, tile.currency, state.language)}`
              : `${t("product.balance")} + ${t("product.value")}`)))),
      h("p", { class: "note", style: "margin-top:12px" }, t("overview.balanceNote"))),

    h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, t("overview.products"))),
      h("div", { class: "grid-2" }, products.map(renderProduct))),

    h("section", { class: "card" },
      h("div", { class: "card-head" },
        h("h2", {}, t("overview.activity")),
        h("span", { class: "note" }, activity.currency)),
      renderSparkline(activity)),

    h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, t("overview.attention"))),
      h("p", { class: "note", style: "margin-bottom:12px" }, t("overview.attention.lead")),
      attention.length === 0
        ? h("p", { class: "note" }, t("overview.noAttention"))
        : h("div", { style: "display:grid;gap:10px" }, attention.map(renderAttention))),

    h("section", { class: "card" },
      h("div", { class: "card-head" },
        h("h2", {}, t("overview.recent")),
        h("button", { class: "btn btn-quiet btn-sm", type: "button", onClick: () => { state.view = "movements"; render(); } },
          t("overview.seeAll"), " →")),
      h("ul", { class: "tx-list" }, recent.map(renderTxRow))));
}

function renderProduct(product) {
  const used = product.balance_kind === "credit" && product.credit_limit
    ? Math.min(1, product.current_balance / product.credit_limit) : null;
  return h("article", { class: "product" },
    h("div", { class: "product-top" },
      h("div", {},
        h("div", { class: "product-kind" }, productLabel(product)),
        h("div", { class: "product-num" }, product.masked_number)),
      h("span", { class: "chip chip-soft" }, product.currency)),
    h("div", { class: "product-amount" },
      formatMoney(product.current_balance, product.currency, state.language)),
    h("div", { class: "product-facts" },
      h("span", {}, product.balance_kind === "credit" ? t("product.owed")
        : product.balance_kind === "investment" ? t("product.value") : t("product.balance")),
      product.credit_limit ? h("span", {}, `${t("product.limit")}: ${formatMoney(product.credit_limit, product.currency, state.language)}`) : null,
      product.interest_rate !== null ? h("span", {}, `${t("product.rate")}: ${product.interest_rate}%`) : null,
      h("span", {}, `${t("product.opened")}: ${formatDay(product.opening_date, state.language)}`)),
    used !== null ? frag(
      h("div", { class: "meter", role: "img", "aria-label": `${t("product.available")} ${Math.round((1 - used) * 100)}%` },
        h("span", { style: `width:${(used * 100).toFixed(1)}%` })),
      h("div", { class: "product-facts" },
        h("span", {}, `${t("product.available")}: ${formatMoney(product.credit_limit - product.current_balance, product.currency, state.language)}`))
    ) : null,
    h("button", {
      class: "btn btn-quiet btn-sm", type: "button", style: "justify-self:start",
      onClick: () => { state.view = "movements"; state.filters = { ...emptyFilters(), product: product.product_id }; render(); },
    }, t("nav.movements"), " →"));
}

function renderSparkline(activity) {
  const lang = state.language;
  return frag(
    h("div", { class: "spark", role: "img",
      "aria-label": `${t("overview.activity")}: ${t("overview.inflow")} ${formatMoney(activity.totals.in, activity.currency, lang)}, ${t("overview.outflow")} ${formatMoney(activity.totals.out, activity.currency, lang)}` },
      activity.list.map((b) => h("span", {
        class: "spark-col",
        title: `${formatDay(b.day, lang)} · ${t("overview.inflow")} ${formatMoney(b.in, activity.currency, lang)} · ${t("overview.outflow")} ${formatMoney(b.out, activity.currency, lang)}`,
      },
        h("span", { class: "spark-in", style: `height:${(b.in / activity.peak * 34).toFixed(1)}px` }),
        h("span", { class: "spark-out", style: `height:${(b.out / activity.peak * 34).toFixed(1)}px` })))),
    h("div", { class: "spark-legend" },
      h("span", {}, h("i", { class: "dot", style: "background:var(--sage-400)" }), `${t("overview.inflow")}: ${formatMoney(activity.totals.in, activity.currency, lang)}`),
      h("span", {}, h("i", { class: "dot", style: "background:var(--accent);opacity:.72" }), `${t("overview.outflow")}: ${formatMoney(activity.totals.out, activity.currency, lang)}`),
      activity.totals.unknown > 0
        ? h("span", {}, `${t("overview.undetermined")}: ${formatMoney(activity.totals.unknown, activity.currency, lang)}`)
        : null));
}

function renderAttention(item) {
  const x = item.transaction;
  const tone = item.kind === "pending" ? "warn" : item.kind === "duplicate" ? "warn" : "";
  const message = {
    duplicate: t("tx.dupNote"),
    pending: t("tx.pendingNote"),
    reversed: t("tx.reversedNote"),
    opaque: t("attention.opaque"),
  }[item.kind];
  const merchant = merchantText(x);
  return h("button", {
    type: "button", class: `note-box ${tone}`,
    style: "width:100%;text-align:left;cursor:pointer;border:0",
    onClick: () => selectTransaction(x.transaction_id),
  },
    h("span", { class: "mark", "aria-hidden": "true" }, item.kind === "reversed" ? "↺" : "!"),
    h("span", {},
      h("strong", {}, merchant.text),
      " · ",
      formatMoney(x.amount, x.currency, state.language),
      " · ",
      formatDay(x.transaction_date, state.language),
      h("br"),
      h("span", { style: "opacity:.9" }, message)));
}

/* ==================================================================== *
 * Transactions
 * ==================================================================== */
function renderMovements() {
  const rows = visibleTransactions();
  const { transactions, productById } = state.account;
  const uniq = (fn) => [...new Set(transactions.map(fn).filter(Boolean))].sort();

  const groups = [];
  for (const x of rows) {
    const key = monthKey(x.transaction_date);
    if (!groups.length || groups[groups.length - 1].key !== key) groups.push({ key, rows: [] });
    groups[groups.length - 1].rows.push(x);
  }

  const setFilter = (name) => (value) => { state.filters[name] = value; render(); };

  return frag(
    h("div", { class: "page-head" },
      h("h1", {}, t("mov.title")),
      h("p", { class: "muted" },
        t("mov.count", { shown: formatNumber(rows.length, state.language), total: formatNumber(transactions.length, state.language) }),
        " · ", t("mov.dateBasis"))),

    h("section", { class: "card" },
      h("div", { class: "filters-bar" },
        h("div", { class: "search-wrap" },
          h("span", { class: "glyph", "aria-hidden": "true" }, "⌕"),
          h("input", {
            id: "tx-search", type: "search", value: state.filters.query,
            placeholder: t("mov.search"), "aria-label": t("mov.search"),
            onInput: (e) => { state.filters.query = e.target.value; renderKeepFocus("tx-search"); },
          })),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: () => { state.filters = emptyFilters(); render(); } }, t("mov.clear")),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: () => exportCsv(rows) }, "↧ ", t("mov.export"))),

      h("div", { class: "filters" },
        field("mov.product", selectControl(state.filters.product,
          state.account.products.map((p) => ({ value: p.product_id, label: productLabel(p) })), setFilter("product"))),
        field("mov.type", selectControl(state.filters.type,
          uniq((x) => x.transaction_type).map((v) => ({ value: v, label: t(`type.${v}`) })), setFilter("type"))),
        field("mov.status", selectControl(state.filters.status,
          uniq((x) => x.transaction_status).map((v) => ({ value: v, label: t(`status.${v}`) })), setFilter("status"))),
        field("mov.channel", selectControl(state.filters.channel,
          uniq((x) => x.channel).map((v) => ({ value: v, label: t(`channel.${v}`) })), setFilter("channel"))),
        field("mov.currency", selectControl(state.filters.currency,
          uniq((x) => x.currency).map((v) => ({ value: v, label: v })), setFilter("currency"))),
        field("mov.direction", selectControl(state.filters.direction,
          ["debit", "credit", "unknown"].map((v) => ({ value: v, label: t(`dir.${v}`) })), setFilter("direction"))),
        field("mov.from", h("input", { type: "date", value: state.filters.from, min: DATASET.window_start, max: DATASET.window_end, onChange: (e) => setFilter("from")(e.target.value) })),
        field("mov.to", h("input", { type: "date", value: state.filters.to, min: DATASET.window_start, max: DATASET.window_end, onChange: (e) => setFilter("to")(e.target.value) })),
        field("mov.min", h("input", { type: "number", min: "0", step: "0.01", value: state.filters.min, onChange: (e) => setFilter("min")(e.target.value) })),
        field("mov.max", h("input", { type: "number", min: "0", step: "0.01", value: state.filters.max, onChange: (e) => setFilter("max")(e.target.value) })),
        field("mov.sort", selectControl(state.filters.sort,
          ["dateDesc", "dateAsc", "amountDesc", "amountAsc"].map((v) => ({ value: v, label: t(`mov.sort.${v}`) })),
          setFilter("sort"), false)))),

    h("section", { class: "card" },
      rows.length === 0
        ? h("div", { class: "empty" }, h("strong", {}, t("mov.empty")), t("mov.emptyHint"))
        : h("div", { id: "tx-scroll" }, groups.map((group) => frag(
            h("div", { class: "month-head" },
              h("span", {}, formatMonth(group.key, state.language)),
              h("span", { class: "month-count" },
                t("mov.monthCount", { count: formatNumber(group.rows.length, state.language) }))),
            h("ul", { class: "tx-list" }, group.rows.map(renderTxRow)))))));
}

function renderTxRow(x) {
  const merchant = merchantText(x);
  const product = state.account.productById.get(x.product_id);
  const isDuplicate = state.account.duplicates.has(x.transaction_id);
  return h("li", {},
    h("button", {
      class: "tx-row", type: "button", "data-tx": x.transaction_id,
      "aria-current": String(state.selectedId === x.transaction_id),
      "aria-label": t("a11y.selectTx", { reference: x.transaction_id }),
      onClick: () => selectTransaction(x.transaction_id),
    },
      h("span", { class: "tx-glyph", "aria-hidden": "true" }, TYPE_GLYPH[x.transaction_type] || "•"),
      h("span", { class: "tx-main" },
        h("span", { class: `tx-title ${merchant.unknown ? "unknown" : ""}` }, merchant.text),
        h("span", { class: "tx-sub" },
          h("span", {}, formatDayTime(x.transaction_date, state.language)),
          h("span", {}, "·"),
          h("span", {}, t(`type.${x.transaction_type}`)),
          h("span", {}, "·"),
          h("span", {}, t(`channel.${x.channel}`)),
          product ? frag(h("span", {}, "·"), h("span", {}, product.masked_number)) : null)),
      h("span", { class: "tx-right" },
        h("span", { class: `tx-amount ${x.direction === "credit" ? "credit" : x.direction === "unknown" ? "unknown-dir" : ""}` },
          signedMoney(x, state.language)),
        h("span", { style: "display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end" },
          x.direction === "unknown" ? h("span", { class: "chip chip-soft" }, t("dir.unknown")) : null,
          isDuplicate ? h("span", { class: "chip chip-warn" }, t("tx.dupBadge")) : null,
          statusChip(x)))));
}

function selectTransaction(id) {
  state.selectedId = id;
  render();
  requestAnimationFrame(() => {
    const close = document.querySelector(".panel .icon-btn");
    if (close) close.focus();
  });
}

function exportCsv(rows) {
  const header = [
    "transaction_id", "product", "product_reference", "transaction_date", "process_date",
    "transaction_type", "transaction_category", "amount", "currency", "direction",
    "channel", "merchant_name", "transaction_city", "transaction_country", "transaction_status",
    "reversal_of", "dataset", "synthetic",
  ];
  const body = rows.map((x) => {
    const product = state.account.productById.get(x.product_id);
    return [
      x.transaction_id, product ? productLabel(product) : "", product ? product.masked_number : "",
      x.transaction_date, x.process_date, x.transaction_type, x.transaction_category ?? "",
      x.amount.toFixed(2), x.currency, x.direction, x.channel,
      x.merchant_name ?? "", x.transaction_city ?? "", x.transaction_country, x.transaction_status,
      x.reversal_of ?? "", DATASET.id, "true",
    ];
  });
  downloadFile("savia-lite-movimientos.csv", toCsv(body, header), "text/csv;charset=utf-8");
}

function downloadFile(name, text, mime) {
  const blob = new Blob(["﻿" + text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = h("a", { href: url, download: name });
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

/* ==================================================================== *
 * Detail panel
 * ==================================================================== */
function journeySteps(x) {
  const lang = state.language;
  const steps = [{ cls: "done", title: t("tx.journey.registered"), when: formatDayTime(x.transaction_date, lang) }];
  steps.push({ cls: "done", title: t("tx.journey.processed", { date: formatDay(x.process_date, lang) }), when: x.process_date });

  if (x.transaction_status === "Aprobada") steps.push({ cls: "done", title: t("tx.journey.settled"), when: "" });
  else if (x.transaction_status === "Pendiente") steps.push({ cls: "wait", title: t("tx.journey.pending"), when: "" });
  else if (x.transaction_status === "Reversada") steps.push({ cls: "stop", title: t("tx.journey.reversed"), when: "" });
  else if (x.transaction_status === "Rechazada") steps.push({ cls: "stop", title: t("tx.journey.declined"), when: "" });

  if (x.reversal_of) steps.push({ cls: "done", title: t("tx.journey.adjustment", { reference: x.reversal_of }), when: "" });
  return steps;
}

function duplicatePartner(x) {
  if (!state.account.duplicates.has(x.transaction_id)) return null;
  return state.account.transactions.find((y) =>
    y.transaction_id !== x.transaction_id &&
    state.account.duplicates.has(y.transaction_id) &&
    y.merchant_name === x.merchant_name &&
    y.amount === x.amount &&
    y.currency === x.currency) || null;
}

function renderPanel() {
  const x = selectedTransaction();
  if (!x) return null;
  const lang = state.language;
  const merchant = merchantText(x);
  const product = state.account.productById.get(x.product_id);
  const eventDay = dayKey(x.transaction_date);
  const gap = eventDay !== x.process_date;
  const partner = duplicatePartner(x);
  const reversalEntry = state.account.transactions.find((y) => y.reversal_of === x.transaction_id) || null;
  const close = () => { state.selectedId = null; render(); };

  return frag(
    h("div", { class: "scrim", onClick: close }),
    h("aside", { class: "panel", role: "dialog", "aria-modal": "true", "aria-label": t("tx.detail") },
      h("div", { class: "panel-head" },
        h("div", {},
          h("p", { class: "note" }, t("tx.detail")),
          h("h2", { class: merchant.unknown ? "unknown" : "", style: merchant.unknown ? "color:var(--ink-3);font-style:italic" : "" }, merchant.text)),
        closeButton(close)),

      h("div", { class: "panel-body" },
        h("div", {},
          h("div", { class: `hero-amount ${x.direction === "credit" ? "credit" : ""}` }, signedMoney(x, lang)),
          h("div", { style: "display:flex;gap:6px;flex-wrap:wrap;margin-top:8px" },
            statusChip(x),
            h("span", { class: "chip chip-soft" }, t(`type.${x.transaction_type}`)),
            h("span", { class: "chip chip-soft" }, t(`channel.${x.channel}`)),
            x.direction === "unknown" ? h("span", { class: "chip chip-info" }, t("tx.unknownDirection")) : null,
            partner ? h("span", { class: "chip chip-warn" }, t("tx.dupBadge")) : null)),

        x.transaction_status === "Pendiente" ? h("div", { class: "note-box warn" }, h("span", { class: "mark" }, "!"), t("tx.pendingNote")) : null,
        x.transaction_status === "Reversada" ? h("div", { class: "note-box" }, h("span", { class: "mark" }, "↺"), t("tx.reversedNote")) : null,
        x.transaction_status === "Rechazada" ? h("div", { class: "note-box" }, h("span", { class: "mark" }, "✕"), t("tx.declinedNote")) : null,
        x.direction === "unknown" ? h("div", { class: "note-box" }, h("span", { class: "mark" }, "?"), t("overview.undetermined")) : null,

        partner ? h("div", { class: "note-box warn" },
          h("span", { class: "mark" }, "⧉"),
          h("span", {}, t("tx.dupNote"), " ",
            h("button", { class: "btn btn-quiet btn-sm", type: "button", onClick: () => selectTransaction(partner.transaction_id) },
              t("tx.dupSee"), " →"))) : null,

        reversalEntry ? h("div", { class: "note-box" },
          h("span", { class: "mark" }, "⤺"),
          h("span", {}, t("tx.reversalPair"), ": ",
            h("button", { class: "btn btn-quiet btn-sm", type: "button", onClick: () => selectTransaction(reversalEntry.transaction_id) },
              reversalEntry.transaction_id, " →"))) : null,

        h("dl", { class: "kv" },
          h("dt", {}, t("tx.reference")), h("dd", { class: "mono" }, x.transaction_id),
          h("dt", {}, t("tx.amount")), h("dd", {}, `${formatMoney(x.amount, x.currency, lang)} (${x.currency})`),
          h("dt", {}, t("mov.direction")), h("dd", { class: x.direction === "unknown" ? "unknown" : "" }, t(`dir.${x.direction}`)),
          h("dt", {}, t("tx.eventDate")), h("dd", {}, formatDayTime(x.transaction_date, lang)),
          h("dt", {}, t("tx.processDate")), h("dd", {}, formatDay(x.process_date, lang)),
          h("dt", {}, t("mov.status")), h("dd", {}, t(`status.${x.transaction_status}`)),
          h("dt", {}, t("mov.product")), h("dd", {}, product ? `${productLabel(product)} · ${product.masked_number}` : t("tx.none")),
          h("dt", {}, t("mov.channel")), h("dd", {}, t(`channel.${x.channel}`)),
          h("dt", {}, t("tx.merchant")), h("dd", { class: merchant.unknown ? "unknown" : "" }, merchant.text),
          h("dt", {}, t("tx.category")), h("dd", { class: x.transaction_category ? "" : "unknown" }, x.transaction_category || t("tx.none")),
          h("dt", {}, t("tx.place")), h("dd", { class: x.transaction_city ? "" : "unknown" },
            x.transaction_city ? `${x.transaction_city}, ${x.transaction_country}` : x.transaction_country)),

        gap ? h("div", { class: "note-box" }, h("span", { class: "mark" }, "🕐"), t("tx.dateGap")) : null,

        h("div", {},
          h("h3", { style: "margin-bottom:10px" }, t("tx.journey")),
          h("ul", { class: "timeline" }, journeySteps(x).map((step) =>
            h("li", { class: step.cls },
              h("div", { class: "step-title" }, step.title),
              step.when ? h("div", { class: "step-when" }, step.when) : null))))),

      h("div", { class: "panel-foot" },
        h("button", { class: "btn", type: "button", onClick: () => openTriage(x) }, t("tx.notRecognised")),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: () => copyDetail(x) }, t("tx.copy")))));
}

function copyDetail(x) {
  const product = state.account.productById.get(x.product_id);
  const lines = [
    `${t("tx.reference")}: ${x.transaction_id}`,
    `${t("tx.amount")}: ${formatMoney(x.amount, x.currency, state.language)} (${x.currency})`,
    `${t("mov.status")}: ${t(`status.${x.transaction_status}`)}`,
    `${t("tx.eventDate")}: ${x.transaction_date}`,
    `${t("tx.processDate")}: ${x.process_date}`,
    `${t("mov.type")}: ${t(`type.${x.transaction_type}`)}`,
    `${t("mov.channel")}: ${t(`channel.${x.channel}`)}`,
    `${t("tx.merchant")}: ${x.merchant_name ?? t("tx.unknownMerchant")}`,
    `${t("mov.direction")}: ${t(`dir.${x.direction}`)}`,
    `${t("mov.product")}: ${product ? `${productLabel(product)} ${product.masked_number}` : t("tx.none")}`,
    `${DATASET.id} · synthetic=true`,
  ];
  copyText(lines.join("\n"), t("tx.copied"));
}

function copyText(text, message) {
  const done = () => toast(message);
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
  else fallbackCopy(text, done);
}
function fallbackCopy(text, done) {
  const box = h("textarea", { style: "position:fixed;top:-1000px" }, text);
  document.body.append(box);
  box.select();
  try { document.execCommand("copy"); } catch { /* clipboard unavailable */ }
  box.remove();
  done();
}

/* ==================================================================== *
 * Guided triage - concrete questions, then a local summary
 * ==================================================================== */
const QUESTIONS = [
  { id: "shared", key: "triage.q.shared" },
  { id: "merchant", key: "triage.q.merchant" },
  { id: "subscription", key: "triage.q.subscription" },
  { id: "card", key: "triage.q.card" },
];

function openTriage(x) {
  state.triage = { transactionId: x.transaction_id, step: 0, answers: {}, notes: "", urgent: false };
  state.dialog = "triage";
  render();
  focusDialog();
}

function renderTriage() {
  const tr = state.triage;
  const x = state.account.transactions.find((y) => y.transaction_id === tr.transactionId);
  const question = QUESTIONS[tr.step];
  const merchant = merchantText(x);
  const answered = tr.answers[question.id] !== undefined;
  const last = tr.step === QUESTIONS.length - 1;
  const close = () => { state.dialog = null; state.triage = null; render(); };

  return h("div", { class: "modal", onClick: (e) => { if (e.target.classList.contains("modal")) close(); } },
    h("div", { class: "modal-card", role: "dialog", "aria-modal": "true", "aria-label": t("triage.title") },
      h("div", { class: "modal-head" },
        h("div", {},
          h("h2", {}, t("triage.title")),
          h("p", { class: "note", style: "margin-top:4px;max-width:52ch" }, t("triage.lead"))),
        closeButton(close)),

      h("div", { class: "note-box", style: "margin-bottom:16px" },
        h("span", { class: "mark", "aria-hidden": "true" }, "→"),
        h("span", {},
          h("strong", {}, t("triage.selected")), ": ",
          h("span", { class: merchant.unknown ? "unknown" : "" }, merchant.text),
          " · ", formatMoney(x.amount, x.currency, state.language),
          " · ", formatDay(x.transaction_date, state.language),
          " · ", t(`status.${x.transaction_status}`))),

      h("p", { class: "note" }, t("triage.step", { current: tr.step + 1, total: QUESTIONS.length })),
      h("div", { class: "progress" }, h("span", { style: `width:${((tr.step + (answered ? 1 : 0)) / QUESTIONS.length * 100).toFixed(0)}%` })),

      h("h3", {}, t(question.key)),
      h("div", { class: "answers", role: "group", "aria-label": t(question.key) },
        ["yes", "no", "unsure"].map((value) => h("button", {
          type: "button", class: "answer", "aria-pressed": String(tr.answers[question.id] === value),
          onClick: () => { tr.answers[question.id] = value; render(); },
        }, t(`triage.${value}`)))),

      last ? h("label", { class: "field-label", style: "margin-top:20px;display:block" }, t("triage.notes"),
        h("textarea", {
          style: "margin-top:8px", value: tr.notes, maxlength: "600",
          onInput: (e) => { tr.notes = e.target.value; },
        })) : null,

      h("label", { class: "check" },
        h("input", { type: "checkbox", checked: tr.urgent, onChange: (e) => { tr.urgent = e.target.checked; render(); } }),
        h("span", {},
          h("span", { class: "check-title" }, t("triage.urgent")),
          h("br"),
          h("span", { class: "check-note" }, t("triage.urgentNote")))),

      h("div", { class: "modal-foot" },
        tr.step > 0 && !tr.urgent ? h("button", { class: "btn btn-ghost", type: "button", onClick: () => { tr.step -= 1; render(); } }, "← ", t("triage.back")) : null,
        tr.urgent || last
          ? h("button", { class: `btn ${tr.urgent ? "btn-danger" : ""}`, type: "button", onClick: () => buildSummary() }, t("triage.finish"))
          : h("button", { class: "btn", type: "button", disabled: !answered, onClick: () => { tr.step += 1; render(); } }, t("triage.next"), " →"))));
}

/**
 * Builds the local review summary. Only fields taken from the generated dataset
 * are placed under `transaction`; anything the person typed or clicked stays
 * under `customer_answers`, never mixed into the transaction facts.
 */
function buildSummary() {
  const tr = state.triage;
  const x = state.account.transactions.find((y) => y.transaction_id === tr.transactionId);
  const product = state.account.productById.get(x.product_id);
  const unresolved = [];

  if (!tr.urgent) {
    if (tr.answers.merchant === "unsure") unresolved.push(t("triage.q.merchant"));
    if (tr.answers.subscription === "unsure") unresolved.push(t("triage.q.subscription"));
    if (tr.answers.shared === "unsure") unresolved.push(t("triage.q.shared"));
    if (tr.answers.card === "unsure") unresolved.push(t("triage.q.card"));
    if (duplicatePartner(x)) unresolved.push(t("tx.dupNote"));
    if (x.transaction_status === "Pendiente") unresolved.push(t("tx.pendingNote"));
  }

  state.summary = {
    schema: "savia-lite-local-review/v1",
    local_only: true,
    id: "REV-LOCAL-" + randomId(8),
    created_at: new Date().toISOString(),
    language: state.language,
    reason: tr.urgent ? "security_concern" : "unrecognised_charge",
    dataset: { id: DATASET.id, synthetic: true, build_id: DATASET.build_id, origin: DATASET.origin },
    transaction: {
      reference: x.transaction_id,
      event_date: x.transaction_date,
      process_date: x.process_date,
      amount: x.amount.toFixed(2),
      currency: x.currency,
      status: x.transaction_status,
      type: x.transaction_type,
      channel: x.channel,
      merchant: x.merchant_name,
      merchant_known: x.merchant_name !== null,
      direction: x.direction,
      product: product ? `${product.product_type} ${product.masked_number}` : null,
      duplicate_candidate: Boolean(duplicatePartner(x)),
      settled: x.transaction_status === "Aprobada",
    },
    customer_answers: tr.urgent ? { card_lost_or_stolen: true } : { ...tr.answers, card_lost_or_stolen: false },
    customer_note: tr.urgent ? "" : tr.notes.trim(),
    unresolved_questions: unresolved.slice(0, 4),
    bank_action_taken: false,
    dispute_submitted: false,
    refund_issued: false,
    agent_contacted: false,
    next_step: "Local human review; no bank decision or response deadline promised.",
  };
  state.dialog = "summary";
  state.triage = null;
  render();
  focusDialog();
}

function randomId(length) {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = new Uint8Array(length);
  (globalThis.crypto || {}).getRandomValues?.(bytes);
  let out = "";
  for (let i = 0; i < length; i += 1) out += alphabet[(bytes[i] || Math.floor(Math.random() * 256)) % alphabet.length];
  return out;
}

function renderSummary() {
  const s = state.summary;
  const close = () => { state.dialog = null; render(); };
  const answerLabel = (value) => value === "yes" ? t("triage.yes") : value === "no" ? t("triage.no") : t("triage.unsure");

  return h("div", { class: "modal", onClick: (e) => { if (e.target.classList.contains("modal")) close(); } },
    h("div", { class: "modal-card", role: "dialog", "aria-modal": "true", "aria-label": t("summary.title") },
      h("div", { class: "modal-head" },
        h("div", {},
          h("h2", {}, t("summary.title")),
          h("p", { class: "note", style: "margin-top:4px" },
            t("summary.reason"), ": ", t(`summary.reason.${s.reason}`))),
        closeButton(close)),

      h("div", { class: `note-box ${s.reason === "security_concern" ? "stop" : "ok"}`, style: "margin-bottom:16px" },
        h("span", { class: "mark", "aria-hidden": "true" }, s.reason === "security_concern" ? "!" : "✓"),
        t("summary.disclaimer")),

      h("p", { class: "field-label" }, t("summary.id")),
      h("p", { class: "receipt-id" }, s.id),
      h("p", { class: "note", style: "margin-top:8px" }, t("summary.created"), ": ", s.created_at),

      h("h3", { style: "margin-top:20px;margin-bottom:8px" }, t("summary.facts")),
      h("dl", { class: "kv" },
        h("dt", {}, t("tx.reference")), h("dd", { class: "mono" }, s.transaction.reference),
        h("dt", {}, t("tx.amount")), h("dd", {}, `${s.transaction.amount} ${s.transaction.currency}`),
        h("dt", {}, t("mov.status")), h("dd", {}, t(`status.${s.transaction.status}`)),
        h("dt", {}, t("tx.eventDate")), h("dd", {}, s.transaction.event_date),
        h("dt", {}, t("tx.processDate")), h("dd", {}, s.transaction.process_date),
        h("dt", {}, t("tx.merchant")), h("dd", { class: s.transaction.merchant ? "" : "unknown" }, s.transaction.merchant ?? t("tx.unknownMerchant")),
        h("dt", {}, t("mov.direction")), h("dd", {}, t(`dir.${s.transaction.direction}`)),
        h("dt", {}, t("mov.channel")), h("dd", {}, t(`channel.${s.transaction.channel}`))),

      h("h3", { style: "margin-top:20px;margin-bottom:8px" }, t("summary.answers")),
      s.reason === "security_concern"
        ? h("p", { class: "note" }, t("triage.urgent"))
        : h("ul", { class: "bullets" }, QUESTIONS.filter((q) => s.customer_answers[q.id] !== undefined).map((q) =>
            h("li", {}, t(q.key), " — ", h("strong", {}, answerLabel(s.customer_answers[q.id]))))),

      s.customer_note ? frag(
        h("h3", { style: "margin-top:18px;margin-bottom:6px" }, t("summary.notes")),
        h("p", { class: "note" }, s.customer_note)) : null,

      h("h3", { style: "margin-top:20px;margin-bottom:8px" }, t("summary.open")),
      s.unresolved_questions.length === 0
        ? h("p", { class: "note" }, t("summary.nothing"))
        : h("ul", { class: "bullets" }, s.unresolved_questions.map((q) => h("li", {}, q))),

      h("p", { class: "note", style: "margin-top:18px" }, t("summary.nextStep")),

      h("div", { class: "modal-foot" },
        h("button", { class: "btn btn-ghost", type: "button", onClick: close }, t("summary.close")),
        h("button", { class: "btn btn-ghost", type: "button", onClick: () => copyText(JSON.stringify(s, null, 2), t("tx.copied")) }, t("summary.copy")),
        h("button", { class: "btn", type: "button", onClick: () => downloadFile(`${s.id}.json`, JSON.stringify(s, null, 2), "application/json") }, "↧ ", t("summary.download")))));
}

/* ==================================================================== *
 * Help
 * ==================================================================== */
function renderHelpDialog() {
  const close = () => { state.dialog = null; render(); };
  return h("div", { class: "modal", onClick: (e) => { if (e.target.classList.contains("modal")) close(); } },
    h("div", { class: "modal-card", role: "dialog", "aria-modal": "true", "aria-label": t("help.title") },
      h("div", { class: "modal-head" }, h("h2", {}, t("help.title")), closeButton(close)),
      renderHelpBody(),
      h("div", { class: "modal-foot" }, h("button", { class: "btn", type: "button", onClick: close }, t("summary.close")))));
}

function renderHelpBody() {
  return frag(
    h("div", { class: "two-col" },
      h("div", {},
        h("h3", { style: "margin-bottom:8px" }, "✓ ", t("help.is")),
        h("ul", { class: "bullets list-ok" }, [1, 2, 3, 4, 5].map((n) => h("li", {}, t(`help.is.${n}`))))),
      h("div", {},
        h("h3", { style: "margin-bottom:8px" }, "✕ ", t("help.isnot")),
        h("ul", { class: "bullets list-no" }, [1, 2, 3, 4, 5].map((n) => h("li", {}, t(`help.isnot.${n}`)))))),

    h("h3", { style: "margin-top:20px;margin-bottom:8px" }, t("help.dataset")),
    h("ul", { class: "bullets" },
      h("li", {}, t("help.dataset.window", { start: DATASET.window_start, end: DATASET.window_end })),
      state.account ? h("li", {}, t("help.dataset.rows", { count: formatNumber(state.account.transactions.length, state.language) })) : null,
      h("li", {}, t("help.dataset.build", { build: DATASET.build_id }))),

    h("h3", { style: "margin-top:20px;margin-bottom:8px" }, t("help.shortcuts")),
    h("ul", { class: "bullets" },
      h("li", {}, h("kbd", {}, "/"), " — ", t("help.sc.search")),
      h("li", {}, h("kbd", {}, "Esc"), " — ", t("help.sc.close")),
      h("li", {}, h("kbd", {}, "↑ ↓"), " — ", t("help.sc.move"))));
}

function renderHelpPage() {
  return frag(
    h("div", { class: "page-head" }, h("h1", {}, t("help.title"))),
    h("section", { class: "card" }, renderHelpBody()));
}

/* ==================================================================== *
 * Shell
 * ==================================================================== */
function renderShell() {
  const { profile } = state.account;
  const views = [["overview", "nav.overview"], ["movements", "nav.movements"], ["help", "nav.help"]];

  return h("div", { class: "shell" },
    h("header", { class: "topbar" },
      h("span", { class: "brand" },
        h("span", { class: "brand-word" }, "savia"),
        h("span", { class: "brand-dot" }, "."),
        h("span", { class: "brand-lite" }, "lite")),
      h("nav", { class: "tabs", "aria-label": t("app.subtitle") },
        views.map(([id, key]) => h("button", {
          class: "tab", type: "button", "aria-current": state.view === id ? "page" : null,
          onClick: () => { state.view = id; render(); },
        }, t(key)))),
      h("span", { class: "topbar-spacer" }),
      h("label", { class: "sr", for: "lang-select" }, t("login.language")),
      h("select", { id: "lang-select", style: "width:auto", onChange: (e) => setLanguage(e.target.value) },
        LANGUAGES.map((l) => h("option", { value: l.code, selected: l.code === state.language }, l.native))),
      h("button", {
        class: "icon-btn", type: "button", "aria-label": t("nav.theme"),
        onClick: () => setTheme(state.theme === "dark" ? "light" : "dark"),
      }, state.theme === "dark" ? "☀" : "☾"),
      h("span", { class: "who" },
        h("span", { class: "avatar", "aria-hidden": "true" }, profile.initials),
        h("span", { class: "who-name" }, profile.alias)),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: signOut }, t("nav.logout"))),

    h("main", { id: "main" },
      state.view === "overview" ? renderOverview()
      : state.view === "movements" ? renderMovements()
      : renderHelpPage()),

    h("footer", { class: "foot" },
      h("span", {}, "© 2026 Savia Lite · ", t("app.tagline")),
      h("span", {}, DATASET.id, " · ", DATASET.build_id, " · synthetic=true")));
}

/* ==================================================================== *
 * Render
 * ==================================================================== */
const root = document.getElementById("root");

function render() {
  document.title = t("app.title");
  const view = frag(
    !state.bannerDismissed ? h("div", { class: "disclaimer", role: "note" },
      h("p", {}, h("strong", {}, "Savia Lite · "), t("banner.synthetic")),
      h("button", { type: "button", onClick: () => { state.bannerDismissed = true; savePreferences(); render(); } }, t("banner.dismiss"))) : null,
    h("a", { class: "skip", href: "#main" }, t("a11y.skip")),
    state.signedIn ? renderShell() : renderGate(),
    state.signedIn && state.selectedId ? renderPanel() : null,
    state.dialog === "triage" && state.triage ? renderTriage()
    : state.dialog === "summary" && state.summary ? renderSummary()
    : state.dialog === "help" ? renderHelpDialog() : null,
    state.toast ? h("div", { class: "toast", role: "status" }, state.toast) : null);

  root.replaceChildren(view);
}

/** Re-render while keeping the caret inside a text field the user is typing in. */
function renderKeepFocus(id) {
  const before = document.getElementById(id);
  const caret = before ? before.selectionStart : null;
  render();
  const after = document.getElementById(id);
  if (after) {
    after.focus();
    if (caret !== null) { try { after.setSelectionRange(caret, caret); } catch { /* search inputs may refuse */ } }
  }
}

function openDialog(name) { state.dialog = name; render(); focusDialog(); }
function focusDialog() {
  requestAnimationFrame(() => {
    const target = document.querySelector(".modal-card .icon-btn, .modal-card .btn");
    if (target) target.focus();
  });
}

/* ==================================================================== *
 * Keyboard
 * ==================================================================== */
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (state.dialog) { state.dialog = null; state.triage = null; render(); return; }
    if (state.selectedId) { state.selectedId = null; render(); return; }
  }
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
  if (event.key === "/" && !typing && state.signedIn) {
    event.preventDefault();
    if (state.view !== "movements") { state.view = "movements"; render(); }
    requestAnimationFrame(() => document.getElementById("tx-search")?.focus());
    return;
  }
  if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !typing && !state.dialog && state.signedIn) {
    const rows = [...document.querySelectorAll(".tx-row")];
    if (!rows.length) return;
    event.preventDefault();
    const index = rows.findIndex((r) => r.dataset.tx === state.selectedId);
    const next = event.key === "ArrowDown"
      ? Math.min(rows.length - 1, index + 1)
      : Math.max(0, index <= 0 ? 0 : index - 1);
    const id = rows[next]?.dataset.tx;
    if (id) { state.selectedId = id; render(); }
  }
});

/* ==================================================================== *
 * Boot
 * ==================================================================== */
loadPreferences();
document.documentElement.lang = state.language;
document.documentElement.dataset.theme = state.theme;
t = createTranslator(state.language);
render();
