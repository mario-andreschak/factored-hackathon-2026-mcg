/**
 * Savia Lite - a zero-dependency customer banking portal.
 *
 * No framework, no bundler, no network call. Everything on screen is produced
 * by assets/data.js inside this browser tab.
 *
 * The wording rules this file is built around, each one asserted by
 * tools/selfcheck.mjs:
 *
 *   - a pending charge is never described as settled;
 *   - a reversal entry is never described as a refund that arrived;
 *   - a declined attempt is never described as a charge;
 *   - an absent merchant stays unknown instead of being guessed;
 *   - a duplicate-looking pair is a question, never a fraud finding;
 *   - no screen claims a dispute, a refund, an agent transfer or a deadline.
 */

import {
  DATASET, PROFILES, profileById, buildAccount,
  duplicateIndex, recurringGroups, categoryTotals, monthlySeries,
  coverage, attentionItems, scenarioTour, looksOpaque, CATEGORIES,
} from "./data.js";
import { LANGUAGES, createTranslator } from "./i18n.js";
import {
  dayKey, monthKey, formatDay, formatDayTime, formatMonth, formatMonthShort,
  formatMoney, formatCompact, formatCount, formatPercent, signedMoney,
  toCsv, download,
} from "./format.js";
import { monthlyBars, donut, meter } from "./charts.js";
import { h, frag, clear, bindTabCycle, focusFirst } from "./ui.js";

/* ==================================================================== *
 * Glyphs. Plain characters, so there is no icon font and no SVG sprite
 * to download.
 * ==================================================================== */
const TYPE_GLYPH = {
  purchase: "\u{1F6CD}",
  withdrawal: "\u{1F3E7}",
  deposit: "↓",
  transfer: "⇄",
  payment: "◷",
  adjustment: "⤺",
};
const VIEW_GLYPH = { home: "⌂", movements: "≣", insights: "◴", help: "?" };

/* ==================================================================== *
 * State
 * ==================================================================== */
const STORE_KEY = "savia-lite/preferences/v2";

const emptyFilters = () => ({
  q: "", product: "", type: "", status: "", channel: "",
  currency: "", direction: "", category: "",
  from: "", to: "", min: "", max: "",
  sort: "date-desc", quick: "",
});

const state = {
  language: "es",
  theme: "light",
  bannerDismissed: false,
  gateProfile: PROFILES[0].id,
  profileId: null,
  account: null,
  view: "home",
  selectedId: null,
  dialog: null,        // 'help' | 'tour' | 'palette' | 'triage' | 'summary'
  triage: null,
  summary: null,
  filters: emptyFilters(),
  listLimit: 40,
  insightCurrency: null,
  showFilters: false,
  palette: { query: "", index: 0 },
  toasts: [],
};

let t = createTranslator(state.language);
let toastSeq = 0;
/** Which overlay currently owns focus, and where to send focus when it closes. */
let focusOwner = null;
let unbindTab = null;
let returnFocusTo = null;

/** Preferences only. No profile and no session is ever persisted. */
function loadPreferences() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (LANGUAGES.some((l) => l.code === saved.language)) state.language = saved.language;
    if (saved.theme === "light" || saved.theme === "dark") state.theme = saved.theme;
    state.bannerDismissed = Boolean(saved.bannerDismissed);
  } catch {
    /* A blocked or full storage must never stop the page from rendering. */
  }
}

function savePreferences() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      language: state.language,
      theme: state.theme,
      bannerDismissed: state.bannerDismissed,
    }));
  } catch {
    /* Ignored on purpose. */
  }
}

function setLanguage(code) {
  state.language = code;
  t = createTranslator(code);
  savePreferences();
  render();
}

function setTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  savePreferences();
  render();
}

/* ==================================================================== *
 * Derived data, memoised per account
 * ==================================================================== */
let derived = null;

function rebuildDerived() {
  const rows = state.account.transactions;
  derived = {
    duplicates: duplicateIndex(rows),
    recurring: recurringGroups(rows),
    attention: attentionItems(rows),
    tour: scenarioTour(rows),
    coverage: coverage(rows),
    byId: new Map(rows.map((tx) => [tx.transaction_id, tx])),
    products: new Map(state.account.products.map((p) => [p.product_id, p])),
  };
}

const txById = (id) => derived.byId.get(id) || null;
const productOf = (tx) => derived.products.get(tx.product_id) || null;
const recurringFor = (tx) => derived.recurring.find(
  (group) => group.merchant === tx.merchant_name && group.amount === tx.amount,
) || null;

/* ==================================================================== *
 * Copy-aware presentation helpers
 * ==================================================================== */

/** An absent merchant stays absent. It is never replaced by a guess. */
function merchantText(tx) {
  if (tx.merchant_name) return { text: tx.merchant_name, unknown: false };
  return { text: t("tx.unknownMerchant"), unknown: true };
}

const productName = (product) =>
  (product ? `${t(`product.${product.product_type}`)} · **** ${product.masked_number}` : "—");

function statusPill(tx) {
  return h("span", { class: `pill pill-${tx.transaction_status}` }, t(`status.${tx.transaction_status}`));
}

function directionWord(direction) {
  if (direction === "credit") return t("tx.in");
  if (direction === "debit") return t("tx.out");
  return t("tx.undetermined");
}

function amountClass(tx) {
  if (tx.direction === "credit") return "tx-amount is-in";
  if (tx.direction === "unknown") return "tx-amount is-unknown";
  return "tx-amount";
}

const isOpaque = (tx) => looksOpaque(tx.merchant_name);
const isLateEvent = (tx) => dayKey(tx.transaction_date) !== tx.process_date;

/**
 * Every notice a single transaction deserves, in priority order. Each one is
 * phrased as an observation about the record, never as a verdict.
 */
function noticesFor(tx) {
  const notices = [];
  const others = derived.duplicates.get(tx.transaction_id);
  const product = productOf(tx);

  if (tx.transaction_status === "pending") {
    notices.push({ tone: "warn", mark: "!", text: t("tx.pendingNote") });
  }
  if (tx.transaction_status === "declined") {
    notices.push({ tone: "stop", mark: "⊘", text: t("tx.declinedNote") });
  }
  if (tx.transaction_status === "reversed") {
    notices.push({ tone: "info", mark: "↺", text: t("tx.reversalOriginNote") });
  }
  if (tx.reversal_of) {
    notices.push({
      tone: "info",
      mark: "↺",
      text: t("tx.reversalNote"),
      link: { label: t("tx.reversalSee"), id: tx.reversal_of },
    });
  }
  if (others && others.length) {
    notices.push({
      tone: "flag",
      mark: "⧉",
      text: t("tx.dupNote"),
      link: { label: t("tx.dupSee"), id: others[0].transaction_id },
    });
  }
  if (isOpaque(tx)) {
    notices.push({ tone: "flag", mark: "≡", text: t("tx.opaqueNote") });
  }
  if (product && tx.currency !== product.currency) {
    notices.push({
      tone: "info",
      mark: "⇆",
      text: t("tx.foreignNote", { txCurrency: tx.currency, productCurrency: product.currency }),
    });
  }
  if (isLateEvent(tx)) {
    notices.push({ tone: "info", mark: "◴", text: t("tx.nextDayNote") });
  }
  if (recurringFor(tx)) {
    notices.push({ tone: "ok", mark: "↻", text: t("tx.recurringNote") });
  }
  return notices;
}

function noticeNode(notice) {
  const body = [notice.text];
  if (notice.link) {
    body.push(" ");
    body.push(h("button", {
      class: "link-btn",
      type: "button",
      onClick: (event) => { event.stopPropagation(); select(notice.link.id); },
    }, `${notice.link.label} →`));
  }
  return h("div", { class: `notice notice-${notice.tone}` },
    h("span", { class: "mark", "aria-hidden": "true" }, notice.mark),
    h("span", {}, body));
}

/* ==================================================================== *
 * Small layout builders. Keeping these shallow keeps the view code
 * readable and keeps nesting under control.
 * ==================================================================== */
function card(titleText, noteText, action, ...body) {
  const heading = [];
  if (titleText) heading.push(h("h2", {}, titleText));
  if (noteText) heading.push(h("p", { class: "note" }, noteText));
  const head = heading.length || action
    ? h("div", { class: "card-head" }, h("div", {}, heading), action || null)
    : null;
  return h("section", { class: "card" }, head, ...body);
}

function fact(label, value, mono) {
  return h("div", { class: "fact" },
    h("dt", {}, label),
    h("dd", { class: mono ? "mono" : null }, value));
}

function closeButton(onClose) {
  return h("button", {
    class: "icon-btn",
    type: "button",
    "aria-label": t("a11y.close"),
    onClick: onClose,
  }, "✕");
}

/* ==================================================================== *
 * Toasts
 * ==================================================================== */
function toast(text) {
  const id = ++toastSeq;
  state.toasts.push({ id, text });
  render();
  setTimeout(() => {
    state.toasts = state.toasts.filter((item) => item.id !== id);
    render();
  }, 4200);
}

function renderToasts() {
  return h("div", { class: "toasts", role: "status", "aria-live": "polite" },
    state.toasts.map((item) => h("div", { class: "toast" },
      h("span", { class: "mark", "aria-hidden": "true" }, "✓"),
      h("span", {}, item.text))));
}

/* ==================================================================== *
 * Transaction row
 * ==================================================================== */
function txRow(tx, index) {
  const merchant = merchantText(tx);
  const product = productOf(tx);
  const flags = [];
  if (derived.duplicates.has(tx.transaction_id)) {
    flags.push(h("span", { class: "pill pill-flag" }, t("tx.dupBadge")));
  }
  if (tx.reversal_of) {
    flags.push(h("span", { class: "pill pill-mute" }, t("status.reversed")));
  }

  const metaBits = [
    formatDayTime(tx.transaction_date, state.language),
    t(`type.${tx.transaction_type}`),
    t(`channel.${tx.channel}`),
    product ? `**** ${product.masked_number}` : null,
  ].filter(Boolean);

  const side = [h("div", { class: amountClass(tx) },
    signedMoney(tx.amount, tx.currency, tx.direction, state.language))];
  if (tx.direction === "unknown") {
    side.push(h("div", { class: "tx-sub" }, t("tx.undetermined")));
  }
  side.push(h("div", { class: "tx-sub" }, statusPill(tx)));

  return h("button", {
    class: "tx-row",
    type: "button",
    role: "option",
    "aria-selected": String(state.selectedId === tx.transaction_id),
    dataset: { row: String(index ?? ""), id: tx.transaction_id },
    onClick: () => select(tx.transaction_id),
  },
    h("span", { class: "tx-icon", "aria-hidden": "true" }, TYPE_GLYPH[tx.transaction_type] || "•"),
    h("span", { class: "tx-main" },
      h("span", { class: "tx-title" },
        h("span", { class: merchant.unknown ? "unknown" : null }, merchant.text),
        flags),
      h("span", { class: "tx-meta" }, metaBits.join(" · "))),
    h("span", { class: "tx-side tnum" }, side));
}

/* ==================================================================== *
 * Sign-in
 * ==================================================================== */
function renderGate() {
  const chosen = profileById(state.gateProfile);

  const languageSeg = h("div", { class: "seg", role: "group", "aria-label": t("login.language") },
    LANGUAGES.map((lang) => h("button", {
      type: "button",
      "aria-pressed": String(state.language === lang.code),
      onClick: () => setLanguage(lang.code),
    }, lang.native)));

  const options = PROFILES.map((profile) => h("button", {
    class: "profile-option",
    type: "button",
    "aria-pressed": String(state.gateProfile === profile.id),
    onClick: () => { state.gateProfile = profile.id; setLanguage(profile.language); },
  },
    h("span", { class: "avatar avatar-lg", "aria-hidden": "true" }, profile.initials),
    h("span", { class: "profile-body" },
      h("span", { class: "profile-name" }, profile.alias),
      h("span", { class: "profile-meta" },
        `${profile.city}, ${profile.country} · ${t("login.segment")}: ${profile.segment}`)),
    h("span", { class: "profile-cur" }, profile.currency)));

  const tryList = [
    t("tour.opaque_descriptor.title"),
    t("tour.duplicate_pair.title"),
    t("tour.pending_authorisation.title"),
    t("tour.reversal_entry.title"),
    t("tour.declined_attempt.title"),
    t("tour.foreign_currency.title"),
  ];

  const hero = h("div", { class: "gate-hero" },
    h("span", { class: "brand" }, "savia", h("span", { class: "brand-dot" }, "."),
      h("span", { class: "brand-tag" }, "lite")),
    h("p", { class: "gate-lede" }, t("app.tagline")),
    h("p", { class: "gate-sub" }, t("app.subtitle")),
    h("div", { class: "gate-try" },
      h("h3", {}, t("login.tryTitle")),
      h("p", { class: "note", style: "margin-top:6px" }, t("login.tryLead")),
      h("ul", {}, tryList.map((item) => h("li", {},
        h("span", { class: "mark", "aria-hidden": "true" }, "→"),
        h("span", {}, item))))));

  const form = card(t("login.title"), t("login.lead"), null,
    h("div", { style: "margin-bottom:16px" },
      h("span", { class: "field-label" }, t("login.language")),
      languageSeg),
    h("span", { class: "field-label" }, t("login.choose")),
    h("div", { class: "profile-grid", role: "group", "aria-label": t("login.choose") }, options),
    h("div", { class: "gate-row" },
      h("button", { class: "btn", type: "button", "data-autofocus": "true", onClick: () => signIn(chosen.id) },
        t("login.enter"), " →"),
      h("button", { class: "link-btn", type: "button", onClick: () => openDialog("help") }, t("login.help"))),
    h("p", { class: "note", style: "margin-top:14px" }, t("login.note")),
    h("p", { class: "note", style: "margin-top:4px" },
      t("login.window", { start: DATASET.window_start, end: DATASET.window_end })));

  return h("div", { class: "gate view" }, hero, form);
}

function signIn(profileId) {
  state.profileId = profileId;
  state.account = buildAccount(profileId);
  state.insightCurrency = state.account.profile.currency;
  state.filters = emptyFilters();
  state.listLimit = 40;
  state.view = "home";
  state.selectedId = null;
  rebuildDerived();
  render();
}

function signOut() {
  state.profileId = null;
  state.account = null;
  derived = null;
  state.selectedId = null;
  state.dialog = null;
  state.triage = null;
  state.summary = null;
  state.filters = emptyFilters();
  render();
}

/* ==================================================================== *
 * Home
 * ==================================================================== */
function renderHome() {
  const { profile, products } = state.account;
  const rows = state.account.transactions;

  const head = h("div", { class: "page-head" },
    h("h1", {}, t("home.greeting", { name: profile.first_name })),
    h("p", { class: "note" }, t("home.asof", {
      date: formatDay(DATASET.latest_process_date, state.language),
    })));

  /* --- balances, grouped by the currency each product is actually in --- */
  const byCurrency = new Map();
  for (const product of products) {
    if (!byCurrency.has(product.currency)) {
      byCurrency.set(product.currency, { deposit: 0, credit: 0, investment: 0 });
    }
    const bucket = byCurrency.get(product.currency);
    bucket[product.balance_kind] = (bucket[product.balance_kind] || 0) + product.current_balance;
  }

  const balanceCells = [...byCurrency.entries()].map(([currency, bucket]) => {
    const primary = bucket.deposit || bucket.investment || bucket.credit;
    const subs = [];
    if (bucket.credit) {
      subs.push(`${t("home.used")}: ${formatMoney(bucket.credit, currency, state.language)}`);
    }
    if (bucket.investment && bucket.deposit) {
      subs.push(`${t("home.value")}: ${formatMoney(bucket.investment, currency, state.language)}`);
    }
    return h("div", { class: "hero-cell" },
      h("div", { class: "hero-cur" }, currency),
      h("div", { class: "hero-amount tnum" }, formatMoney(primary, currency, state.language)),
      subs.length ? h("div", { class: "hero-sub tnum" }, subs.join(" · ")) : null);
  });

  const balances = card(t("home.balances"), null, null,
    h("div", { class: "hero" }, balanceCells),
    h("p", { class: "note", style: "margin-top:14px" }, t("home.balancesNote")));

  /* --- products --- */
  const productCards = products.map((product) => {
    const kindLabel = product.balance_kind === "credit"
      ? t("home.used")
      : product.balance_kind === "investment" ? t("home.value") : t("home.balance");
    const facts = [];
    if (product.credit_limit) {
      facts.push(h("span", {}, `${t("home.limit")}: ${formatMoney(product.credit_limit, product.currency, state.language)}`));
      const available = product.credit_limit - product.current_balance;
      facts.push(h("span", {}, `${t("home.available")}: ${formatMoney(available, product.currency, state.language)}`));
    }
    facts.push(h("span", {}, `${t("home.rate")}: ${product.interest_rate}%`));
    facts.push(h("span", {}, `${t("home.opened")}: ${formatDay(product.opening_date, state.language)}`));

    const utilisation = product.credit_limit
      ? h("div", { class: "product-bar" },
          meter(product.current_balance / product.credit_limit, {
            cls: "meter-warn",
            ariaLabel: `${kindLabel} ${formatPercent(product.current_balance / product.credit_limit, state.language, 0)}`,
          }))
      : null;

    return h("article", { class: "product" },
      h("div", { class: "product-top" },
        h("div", {},
          h("div", { class: "product-type" }, t(`product.${product.product_type}`)),
          h("div", { class: "product-num" }, `**** ${product.masked_number}`)),
        h("span", { class: "profile-cur" }, product.currency)),
      h("div", { class: "product-amount tnum" }, formatMoney(product.current_balance, product.currency, state.language)),
      h("div", { class: "product-kind" }, kindLabel),
      utilisation,
      h("div", { class: "product-facts tnum" }, facts),
      h("div", { class: "product-foot" },
        h("button", {
          class: "link-btn",
          type: "button",
          onClick: () => goToProduct(product.product_id),
        }, `${t("home.productMovements")} →`)));
  });

  const productsCard = card(t("home.products"), null, null,
    h("div", { class: "grid grid-3" }, productCards));

  /* --- money in and out --- */
  const series = monthlySeries(rows, profile.currency).slice(-12);
  const flow = card(t("home.flow"), t("home.flowNote"), null,
    monthlyBars(series, {
      ariaLabel: t("home.flow"),
      labelFor: (month) => formatMonthShort(month, state.language),
      valueFor: (value) => formatMoney(value, profile.currency, state.language),
      legend: {
        inflow: t("home.in"),
        outflow: t("home.out"),
        undetermined: t("home.undetermined"),
      },
      emptyText: t("ins.noData"),
    }));

  /* --- worth a look --- */
  const attentionCopy = {
    duplicate: t("tx.dupNote"),
    reversal: t("tx.reversalNote"),
    pending: t("tx.pendingNote"),
    declined: t("tx.declinedNote"),
    opaque: t("tx.opaqueNote"),
  };
  const attentionNodes = derived.attention.map((item) => {
    const merchant = merchantText(item.tx);
    const title = [
      merchant.text,
      formatMoney(item.tx.amount, item.tx.currency, state.language),
      formatDay(item.tx.transaction_date, state.language),
    ].join(" · ");
    return h("button", {
      class: "attention-item",
      type: "button",
      onClick: () => select(item.tx.transaction_id),
    },
      h("span", { class: "attention-mark", "aria-hidden": "true" }, "!"),
      h("span", {},
        h("span", { class: "attention-title" }, title),
        h("span", { class: "attention-why" }, attentionCopy[item.kind] || "")));
  });
  const attention = derived.attention.length
    ? card(t("home.attention"), t("home.attentionNote"), null, attentionNodes)
    : null;

  /* --- guided tour --- */
  const tourCards = derived.tour.map((item, index) => h("button", {
    class: "tour-card",
    type: "button",
    onClick: () => select(item.tx.transaction_id),
  },
    h("span", { class: "tour-n", "aria-hidden": "true" }, String(index + 1)),
    h("span", { class: "tour-title" }, t(`tour.${item.key}.title`)),
    h("span", { class: "tour-why" }, t(`tour.${item.key}.why`))));

  const tour = card(t("home.tour"), t("home.tourNote"), null,
    h("div", { class: "tour-grid" }, tourCards));

  /* --- recent --- */
  const recent = card(t("home.recent"), null,
    h("button", { class: "link-btn", type: "button", onClick: () => goTo("movements") },
      `${t("home.seeAll")} →`),
    h("div", { class: "tx-list", role: "listbox", "aria-label": t("home.recent") },
      rows.slice(0, 7).map((tx, index) => txRow(tx, index))));

  return h("div", { class: "view" }, head, balances, productsCard,
    h("div", { class: "grid grid-2", style: "margin-top:14px" }, flow, tour),
    attention, recent);
}

/* ==================================================================== *
 * Insights
 *
 * Everything here is a sum of the rows on screen. No model, no forecast,
 * no score. The dominant fact of this dataset is how much is missing, so
 * the page states that first instead of hiding it behind a tidy chart.
 * ==================================================================== */
function renderInsights() {
  const rows = state.account.transactions;
  const currencies = state.account.currencies;
  const currency = currencies.includes(state.insightCurrency)
    ? state.insightCurrency
    : state.account.profile.currency;

  const head = h("div", { class: "page-head" },
    h("h1", {}, t("ins.title")),
    h("p", { class: "note" }, t("ins.lead")));

  const currencySeg = currencies.length > 1
    ? h("div", { class: "seg", role: "group", "aria-label": t("ins.currency") },
        currencies.map((code) => h("button", {
          type: "button",
          "aria-pressed": String(code === currency),
          onClick: () => { state.insightCurrency = code; render(); },
        }, code)))
    : null;

  /* --- categories, with the unclassified remainder as its own slice --- */
  const totals = categoryTotals(rows, currency);
  const top = totals.slices.slice(0, 10);

  const slices = top.map((slice, index) => ({
    label: t(`cat.${slice.category}`),
    value: slice.value,
    cls: `cat-${(index % 10) + 1}`,
  }));
  if (totals.unknown > 0) {
    slices.push({ label: t("ins.unknownSlice"), value: totals.unknown, cls: "cat-unknown" });
  }

  const unknownShare = totals.total ? totals.unknown / totals.total : 0;

  const legendRows = slices.map((slice) => h("div", {
    class: `legend-row ${slice.cls === "cat-unknown" ? "is-unknown" : ""}`.trim(),
  },
    h("span", { class: `legend-dot ${slice.cls}`, "aria-hidden": "true" }),
    h("span", {}, slice.label),
    h("span", { class: "legend-val" },
      `${formatMoney(slice.value, currency, state.language)} · ${formatPercent(totals.total ? slice.value / totals.total : 0, state.language, 1)}`)));

  const categoryCard = card(t("ins.spendByCategory"), t("ins.spendNote"), currencySeg,
    donut(slices, {
      ariaLabel: t("ins.spendByCategory"),
      valueFor: (value) => formatMoney(value, currency, state.language),
      centreValue: formatCompact(totals.total, state.language),
      centreLabel: t("home.out"),
      emptyText: t("ins.noData"),
    }),
    totals.unknown > 0
      ? h("div", { class: "notice notice-info", style: "margin-top:16px" },
          h("span", { class: "mark", "aria-hidden": "true" }, "◌"),
          h("span", {}, t("ins.unknownNote", {
            share: formatPercent(unknownShare, state.language, 1),
          })))
      : null,
    h("div", { class: "legend-rows" }, legendRows));

  /* --- repeating charges --- */
  const subs = derived.recurring.filter((group) => group.currency === currency);
  const subNodes = subs.length
    ? subs.map((group) => h("button", {
        class: "sub-row",
        type: "button",
        onClick: () => select(group.last.transaction_id),
      },
        h("span", {},
          h("span", { class: "sub-name" }, group.merchant),
          h("span", { class: "sub-meta" },
            `${t("ins.subsCount", { count: group.count, months: group.months })} · ${t("ins.subsLast", { date: formatDay(group.last.transaction_date, state.language) })}`)),
        h("span", { class: "tnum", style: "font-weight:640" },
          formatMoney(group.amount, group.currency, state.language))))
    : h("p", { class: "note" }, t("ins.subsEmpty"));

  const subsCard = card(t("ins.subs"), t("ins.subsNote"), null, subNodes);

  /* --- how complete the scenario is --- */
  const cov = derived.coverage;
  const qualityRows = [
    { label: t("ins.qMerchant"), value: cov.withoutMerchant, share: 1 - cov.merchantShare, cls: "meter-warn" },
    { label: t("ins.qNextDay"), value: cov.nextDay, share: cov.nextDayShare, cls: "meter-mute" },
    { label: t("ins.qUnknownDir"), value: cov.undetermined, share: cov.undeterminedShare, cls: "meter-mute" },
    { label: t("ins.qPending"), value: cov.pending, share: cov.total ? cov.pending / cov.total : 0, cls: "" },
  ].map((row) => h("div", { class: "quality-row" },
    h("div", { class: "quality-top" },
      h("span", {}, row.label),
      h("span", { class: "quality-val" },
        `${formatCount(row.value, state.language)} / ${formatCount(cov.total, state.language)} · ${formatPercent(row.share, state.language, 1)}`)),
    meter(row.share, { cls: row.cls, ariaLabel: `${row.label}: ${formatPercent(row.share, state.language, 1)}` })));

  const qualityCard = card(t("ins.quality"), t("ins.qualityNote"), null, qualityRows);

  return h("div", { class: "view" }, head, categoryCard,
    h("div", { class: "grid grid-2", style: "margin-top:14px" }, subsCard, qualityCard));
}

/* ==================================================================== *
 * Transactions
 * ==================================================================== */
const QUICK_FILTERS = [
  { key: "pending", label: "mov.quickPending" },
  { key: "dupes", label: "mov.quickDupes" },
  { key: "no-merchant", label: "mov.quickNoMerchant" },
  { key: "unknown-dir", label: "mov.quickUnknownDir" },
  { key: "this-month", label: "mov.quickThisMonth" },
];

function activeFilterCount() {
  const f = state.filters;
  let count = 0;
  for (const key of ["product", "type", "status", "channel", "currency", "direction", "category", "from", "to", "min", "max"]) {
    if (f[key]) count += 1;
  }
  if (f.quick) count += 1;
  if (f.sort !== "date-desc") count += 1;
  return count;
}

function matchesQuery(tx, query) {
  if (!query) return true;
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [
    tx.merchant_name || "",
    tx.transaction_id,
    t(`type.${tx.transaction_type}`),
    t(`status.${tx.transaction_status}`),
    t(`channel.${tx.channel}`),
    tx.transaction_category ? t(`cat.${tx.transaction_category}`) : "",
    String(tx.amount),
    tx.transaction_date,
    tx.process_date,
  ].join(" ").toLowerCase();
  return haystack.includes(needle);
}

function filteredRows() {
  const f = state.filters;
  const min = f.min === "" ? null : Number(f.min);
  const max = f.max === "" ? null : Number(f.max);

  let rows = state.account.transactions.filter((tx) => {
    if (f.product && tx.product_id !== f.product) return false;
    if (f.type && tx.transaction_type !== f.type) return false;
    if (f.status && tx.transaction_status !== f.status) return false;
    if (f.channel && tx.channel !== f.channel) return false;
    if (f.currency && tx.currency !== f.currency) return false;
    if (f.direction && tx.direction !== f.direction) return false;
    if (f.category === "__none") {
      if (tx.transaction_category) return false;
    } else if (f.category && tx.transaction_category !== f.category) return false;
    const day = dayKey(tx.transaction_date);
    if (f.from && day < f.from) return false;
    if (f.to && day > f.to) return false;
    if (min !== null && !Number.isNaN(min) && tx.amount < min) return false;
    if (max !== null && !Number.isNaN(max) && tx.amount > max) return false;
    if (!matchesQuery(tx, f.q)) return false;

    if (f.quick === "pending" && tx.transaction_status !== "pending") return false;
    if (f.quick === "dupes" && !derived.duplicates.has(tx.transaction_id)) return false;
    if (f.quick === "no-merchant" && tx.merchant_name) return false;
    if (f.quick === "unknown-dir" && tx.direction !== "unknown") return false;
    if (f.quick === "this-month" && monthKey(tx.transaction_date) !== "2026-06") return false;
    return true;
  });

  const sorters = {
    "date-desc": (a, b) => (a.transaction_date < b.transaction_date ? 1 : a.transaction_date > b.transaction_date ? -1 : 0),
    "date-asc": (a, b) => (a.transaction_date > b.transaction_date ? 1 : a.transaction_date < b.transaction_date ? -1 : 0),
    "amount-desc": (a, b) => b.amount - a.amount,
    "amount-asc": (a, b) => a.amount - b.amount,
  };
  rows = [...rows].sort(sorters[f.sort] || sorters["date-desc"]);
  return rows;
}

function selectField(label, key, options, includeAll = true) {
  const children = [];
  if (includeAll) children.push(h("option", { value: "" }, t("mov.all")));
  for (const option of options) {
    children.push(h("option", { value: option.value, selected: state.filters[key] === option.value }, option.label));
  }
  return h("label", {},
    h("span", { class: "field-label" }, label),
    h("select", {
      onChange: (event) => { state.filters[key] = event.target.value; state.listLimit = 40; render(); },
    }, children));
}

function renderMovements() {
  const rows = filteredRows();
  const total = state.account.transactions.length;
  const shown = rows.slice(0, state.listLimit);
  const filterCount = activeFilterCount();

  const head = h("div", { class: "page-head" },
    h("h1", {}, t("mov.title")),
    h("p", { class: "note" },
      `${t("mov.count", { shown: formatCount(rows.length, state.language), total: formatCount(total, state.language) })} · ${t("mov.dateBasis")}`));

  const searchBar = h("div", { class: "search-bar" },
    h("div", { class: "search-field" },
      h("span", { class: "glyph", "aria-hidden": "true" }, "⌕"),
      h("input", {
        id: "tx-search",
        type: "search",
        value: state.filters.q,
        placeholder: t("mov.search"),
        "aria-label": t("mov.search"),
        onInput: (event) => {
          state.filters.q = event.target.value;
          state.listLimit = 40;
          renderKeepCaret("#tx-search");
        },
      })),
    h("button", {
      class: "filter-toggle",
      type: "button",
      "aria-expanded": String(state.showFilters),
      onClick: () => { state.showFilters = !state.showFilters; render(); },
    }, "⚙", h("span", {}, t("mov.filters")),
      filterCount ? h("span", { class: "filter-count" }, String(filterCount)) : null),
    h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: exportCsv }, "↧ ", t("mov.export")),
    filterCount
      ? h("button", {
          class: "link-btn",
          type: "button",
          onClick: () => { state.filters = emptyFilters(); state.listLimit = 40; render(); },
        }, t("mov.clear"))
      : null);

  const chips = h("div", { class: "chips", role: "group", "aria-label": t("mov.quickTitle") },
    QUICK_FILTERS.map((quick) => h("button", {
      class: "chip",
      type: "button",
      "aria-pressed": String(state.filters.quick === quick.key),
      onClick: () => {
        state.filters.quick = state.filters.quick === quick.key ? "" : quick.key;
        state.listLimit = 40;
        render();
      },
    }, t(quick.label))));

  const filters = state.showFilters
    ? h("div", { class: "filters" },
        selectField(t("mov.product"), "product",
          state.account.products.map((p) => ({
            value: p.product_id,
            label: `${t(`product.${p.product_type}`)} · **** ${p.masked_number}`,
          }))),
        selectField(t("mov.type"), "type",
          ["purchase", "withdrawal", "deposit", "transfer", "payment", "adjustment"]
            .map((v) => ({ value: v, label: t(`type.${v}`) }))),
        selectField(t("mov.status"), "status",
          ["approved", "pending", "declined", "reversed"].map((v) => ({ value: v, label: t(`status.${v}`) }))),
        selectField(t("mov.channel"), "channel",
          ["atm", "app", "direct_debit", "ecommerce", "pos", "branch"]
            .map((v) => ({ value: v, label: t(`channel.${v}`) }))),
        selectField(t("mov.currency"), "currency",
          state.account.currencies.map((v) => ({ value: v, label: v }))),
        selectField(t("mov.direction"), "direction",
          [
            { value: "debit", label: t("tx.out") },
            { value: "credit", label: t("tx.in") },
            { value: "unknown", label: t("tx.undetermined") },
          ]),
        selectField(t("mov.category"), "category",
          [{ value: "__none", label: t("tx.unknownCategory") }].concat(
            CATEGORIES.map((v) => ({ value: v, label: t(`cat.${v}`) })))),
        h("label", {},
          h("span", { class: "field-label" }, t("mov.from")),
          h("input", {
            type: "date", value: state.filters.from,
            min: DATASET.window_start, max: DATASET.latest_event_date,
            onChange: (event) => { state.filters.from = event.target.value; render(); },
          })),
        h("label", {},
          h("span", { class: "field-label" }, t("mov.to")),
          h("input", {
            type: "date", value: state.filters.to,
            min: DATASET.window_start, max: DATASET.latest_event_date,
            onChange: (event) => { state.filters.to = event.target.value; render(); },
          })),
        h("label", {},
          h("span", { class: "field-label" }, t("mov.min")),
          h("input", {
            id: "f-min", type: "number", inputmode: "decimal", value: state.filters.min, min: "0",
            onInput: (event) => { state.filters.min = event.target.value; renderKeepCaret("#f-min"); },
          })),
        h("label", {},
          h("span", { class: "field-label" }, t("mov.max")),
          h("input", {
            id: "f-max", type: "number", inputmode: "decimal", value: state.filters.max, min: "0",
            onInput: (event) => { state.filters.max = event.target.value; renderKeepCaret("#f-max"); },
          })),
        selectField(t("mov.sort"), "sort",
          [
            { value: "date-desc", label: t("mov.sortDateDesc") },
            { value: "date-asc", label: t("mov.sortDateAsc") },
            { value: "amount-desc", label: t("mov.sortAmountDesc") },
            { value: "amount-asc", label: t("mov.sortAmountAsc") },
          ], false))
    : null;

  /* --- grouped by the month of the event date --- */
  const groups = [];
  for (const tx of shown) {
    const key = monthKey(tx.transaction_date);
    const last = groups[groups.length - 1];
    if (last && last.month === key) last.rows.push(tx);
    else groups.push({ month: key, rows: [tx] });
  }

  let cursor = 0;
  const listNodes = groups.map((group) => frag(
    h("div", { class: "month-head" },
      h("span", { class: "month-name" }, formatMonth(group.month, state.language)),
      h("span", { class: "month-count" },
        t("mov.monthCount", { count: formatCount(group.rows.length, state.language) }))),
    h("div", { class: "tx-list", role: "listbox", "aria-label": formatMonth(group.month, state.language) },
      group.rows.map((tx) => txRow(tx, cursor++)))));

  const remaining = rows.length - shown.length;
  const footer = rows.length === 0
    ? h("div", { style: "padding:34px 10px;text-align:center" },
        h("p", { style: "font-weight:600" }, t("mov.empty")),
        h("p", { class: "note", style: "margin-top:5px" }, t("mov.emptyHint")))
    : remaining > 0
      ? h("div", { style: "margin-top:18px;text-align:center" },
          h("button", {
            class: "btn btn-ghost",
            type: "button",
            onClick: () => { state.listLimit += 60; render(); },
          }, t("mov.more", { count: formatCount(Math.min(remaining, 60), state.language) })))
      : h("p", { class: "note", style: "margin-top:18px;text-align:center" }, t("mov.allShown"));

  return h("div", { class: "view" }, head,
    card(null, null, null, searchBar, chips, filters),
    h("div", { style: "margin-top:6px" }, listNodes, footer));
}

function goToProduct(productId) {
  state.filters = emptyFilters();
  state.filters.product = productId;
  state.listLimit = 40;
  state.view = "movements";
  state.selectedId = null;
  render();
}

function exportCsv() {
  const rows = filteredRows();
  const header = [
    "reference", "event_date", "event_time", "process_date", "type", "category",
    "amount", "currency", "direction", "status", "channel", "merchant",
    "product", "country", "city", "synthetic",
  ];
  const body = rows.map((tx) => {
    const product = productOf(tx);
    return [
      tx.transaction_id,
      dayKey(tx.transaction_date),
      tx.transaction_date.slice(11, 16),
      tx.process_date,
      t(`type.${tx.transaction_type}`),
      tx.transaction_category ? t(`cat.${tx.transaction_category}`) : "",
      tx.amount,
      tx.currency,
      directionWord(tx.direction),
      t(`status.${tx.transaction_status}`),
      t(`channel.${tx.channel}`),
      tx.merchant_name || "",
      product ? `${t(`product.${product.product_type}`)} ****${product.masked_number}` : "",
      tx.transaction_country,
      tx.transaction_city || "",
      "true",
    ];
  });
  download("savia-lite-movimientos.csv", toCsv([header, ...body]), "text/csv;charset=utf-8");
  toast(t("mov.exported"));
}

/* ==================================================================== *
 * Detail panel
 * ==================================================================== */
function select(id) {
  if (!derived.byId.has(id)) return;
  // Only remember a return target when the row itself is on screen, so the
  // keyboard lands back where the person left off.
  if (document.querySelector(`.tx-row[data-id="${id}"]`)) {
    returnFocusTo = `.tx-row[data-id="${id}"]`;
  }
  state.selectedId = id;
  render();
}

function closePanel() {
  state.selectedId = null;
  render();
}

function journeySteps(tx) {
  const steps = [
    {
      title: t("tx.jRegistered"),
      note: formatDayTime(tx.transaction_date, state.language),
      dot: "is-done",
    },
    {
      title: t("tx.jProcessed", { date: formatDay(tx.process_date, state.language) }),
      note: tx.process_date,
      dot: "is-done",
    },
  ];
  if (tx.transaction_status === "approved") {
    steps.push({ title: t("tx.jApplied"), note: null, dot: "is-done" });
  } else if (tx.transaction_status === "pending") {
    steps.push({ title: t("tx.jPending"), note: t("tx.pendingNote"), dot: "is-open" });
  } else if (tx.transaction_status === "declined") {
    steps.push({ title: t("tx.jDeclined"), note: null, dot: "is-stop" });
  } else if (tx.transaction_status === "reversed") {
    steps.push({ title: t("tx.jReversed"), note: t("tx.reversalOriginNote"), dot: "is-open" });
  }
  return steps;
}

function renderDetail() {
  const tx = txById(state.selectedId);
  if (!tx) return null;
  const merchant = merchantText(tx);
  const product = productOf(tx);

  const badges = [statusPill(tx), h("span", { class: "pill pill-mute" }, t(`type.${tx.transaction_type}`)),
    h("span", { class: "pill pill-mute" }, t(`channel.${tx.channel}`))];
  if (derived.duplicates.has(tx.transaction_id)) {
    badges.push(h("span", { class: "pill pill-flag" }, t("tx.dupBadge")));
  }

  const facts = h("dl", { class: "facts" },
    fact(t("tx.reference"), tx.transaction_id, true),
    fact(t("tx.amount"), `${formatMoney(tx.amount, tx.currency, state.language)} (${tx.currency})`),
    fact(t("tx.direction"), directionWord(tx.direction)),
    fact(t("tx.eventDate"), formatDayTime(tx.transaction_date, state.language)),
    fact(t("tx.processDate"), formatDay(tx.process_date, state.language)),
    fact(t("tx.status"), t(`status.${tx.transaction_status}`)),
    fact(t("tx.product"), productName(product)),
    fact(t("tx.channel"), t(`channel.${tx.channel}`)),
    fact(t("tx.merchant"),
      tx.merchant_name || h("span", { class: "unknown" }, t("tx.unknownMerchant"))),
    fact(t("tx.category"),
      tx.transaction_category
        ? t(`cat.${tx.transaction_category}`)
        : h("span", { class: "unknown" }, t("tx.unknownCategory"))),
    fact(t("tx.place"),
      tx.transaction_city
        ? `${tx.transaction_city}, ${tx.transaction_country}`
        : tx.transaction_country || h("span", { class: "unknown" }, t("tx.unknownPlace"))));

  const timeline = h("div", { class: "timeline" },
    journeySteps(tx).map((step) => h("div", { class: "step" },
      h("span", { class: "step-rail", "aria-hidden": "true" },
        h("span", { class: `step-dot ${step.dot}` }),
        h("span", { class: "step-line" })),
      h("span", { class: "step-body" },
        h("span", { class: "step-title" }, step.title),
        step.note ? h("span", { class: "step-note" }, step.note) : null))));

  return h("aside", {
    class: "panel",
    role: "dialog",
    "aria-modal": "true",
    "aria-label": t("tx.detail"),
    dataset: { panel: "detail" },
  },
    h("div", { class: "panel-head" },
      h("div", {},
        h("div", { class: "panel-eyebrow" }, t("tx.detail")),
        h("div", { class: `panel-title ${merchant.unknown ? "unknown" : ""}`.trim() }, merchant.text)),
      closeButton(closePanel)),
    h("div", { class: "panel-body" },
      h("div", { class: "big-amount tnum" },
        h("strong", { class: tx.direction === "credit" ? "is-in" : null },
          signedMoney(tx.amount, tx.currency, tx.direction, state.language))),
      h("div", { class: "chips", style: "margin-top:10px" }, badges),
      h("div", { style: "margin-top:16px" }, noticesFor(tx).map(noticeNode)),
      facts,
      h("h3", { style: "margin-top:22px" }, t("tx.journey")),
      timeline),
    h("div", { class: "panel-foot" },
      h("button", { class: "btn", type: "button", onClick: () => openTriage(tx.transaction_id) }, t("tx.notMine")),
      h("button", { class: "btn btn-ghost", type: "button", onClick: () => copyDetail(tx) }, t("tx.copy"))));
}

async function copyDetail(tx) {
  const product = productOf(tx);
  const lines = [
    `${t("tx.reference")}: ${tx.transaction_id}`,
    `${t("tx.merchant")}: ${tx.merchant_name || t("tx.unknownMerchant")}`,
    `${t("tx.amount")}: ${formatMoney(tx.amount, tx.currency, state.language)} (${tx.currency})`,
    `${t("tx.direction")}: ${directionWord(tx.direction)}`,
    `${t("tx.eventDate")}: ${formatDayTime(tx.transaction_date, state.language)}`,
    `${t("tx.processDate")}: ${formatDay(tx.process_date, state.language)}`,
    `${t("tx.status")}: ${t(`status.${tx.transaction_status}`)}`,
    `${t("tx.product")}: ${productName(product)}`,
    `${t("tx.channel")}: ${t(`channel.${tx.channel}`)}`,
    `${DATASET.id} · ${DATASET.build_id} · synthetic=true`,
  ];
  await copyText(lines.join("\n"), t("tx.copied"));
}

async function copyText(text, okMessage) {
  try {
    await navigator.clipboard.writeText(text);
    toast(okMessage);
  } catch {
    toast(t("tx.copyFailed"));
  }
}

/* ==================================================================== *
 * Guided triage
 * ==================================================================== */
const QUESTIONS = [
  { id: "recognise", key: "triage.q_recognise" },
  { id: "authorised", key: "triage.q_authorised" },
  { id: "card_present", key: "triage.q_card" },
  { id: "bought_before", key: "triage.q_repeated" },
];

function openTriage(id) {
  state.triage = { transactionId: id, step: 0, answers: {}, notes: "", urgent: false };
  openDialog("triage");
}

function renderTriage() {
  const tr = state.triage;
  const tx = txById(tr.transactionId);
  if (!tx) return null;
  const merchant = merchantText(tx);
  const question = QUESTIONS[tr.step];
  const answered = tr.answers[question.id] !== undefined;
  const last = tr.step === QUESTIONS.length - 1;
  const close = () => { closeDialog(); state.triage = null; render(); };

  const selected = h("div", { class: "notice", style: "margin-bottom:16px" },
    h("span", { class: "mark", "aria-hidden": "true" }, "→"),
    h("span", {},
      h("strong", {}, t("triage.selected")), ": ",
      h("span", { class: merchant.unknown ? "unknown" : null }, merchant.text),
      " · ", formatMoney(tx.amount, tx.currency, state.language),
      " · ", formatDay(tx.transaction_date, state.language),
      " · ", t(`status.${tx.transaction_status}`)));

  const progressWidth = ((tr.step + (answered ? 1 : 0)) / QUESTIONS.length * 100).toFixed(0);

  const answerButtons = ["yes", "no", "unsure"].map((value) => h("button", {
    class: "answer",
    type: "button",
    "aria-pressed": String(tr.answers[question.id] === value),
    onClick: () => { tr.answers[question.id] = value; render(); },
  }, t(`triage.${value}`)));

  const notesField = last
    ? h("label", { style: "display:block;margin-top:20px" },
        h("span", { class: "field-label" }, t("triage.notes")),
        h("textarea", {
          id: "tr-notes",
          maxlength: "600",
          value: tr.notes,
          onInput: (event) => { tr.notes = event.target.value; },
        }))
    : null;

  const urgentCheck = h("label", { class: "check" },
    h("input", {
      type: "checkbox",
      checked: tr.urgent,
      onChange: (event) => { tr.urgent = event.target.checked; render(); },
    }),
    h("span", {},
      h("span", { class: "check-title" }, t("triage.urgent")),
      h("br"),
      h("span", { class: "check-note" }, t("triage.urgentNote"))));

  const footButtons = [];
  if (tr.step > 0 && !tr.urgent) {
    footButtons.push(h("button", {
      class: "btn btn-ghost",
      type: "button",
      onClick: () => { tr.step -= 1; render(); },
    }, "← ", t("triage.back")));
  }
  if (tr.urgent || last) {
    footButtons.push(h("button", {
      class: `btn ${tr.urgent ? "btn-danger" : ""}`.trim(),
      type: "button",
      onClick: buildSummary,
    }, t("triage.finish")));
  } else {
    footButtons.push(h("button", {
      class: "btn",
      type: "button",
      disabled: !answered,
      onClick: () => { tr.step += 1; render(); },
    }, t("triage.next"), " →"));
  }

  const body = tr.urgent
    ? [selected, h("div", { class: "notice notice-stop" },
        h("span", { class: "mark", "aria-hidden": "true" }, "!"),
        h("span", {}, t("sum.urgentAdvice")))]
    : [
        selected,
        h("p", { class: "note" }, t("triage.step", { current: tr.step + 1, total: QUESTIONS.length })),
        h("div", { class: "progress" }, h("span", { style: `width:${progressWidth}%` })),
        h("h3", {}, t(question.key)),
        h("div", { class: "answers", role: "group", "aria-label": t(question.key) }, answerButtons),
        notesField,
      ];

  return modalShell({
    label: t("triage.title"),
    title: t("triage.title"),
    lead: t("triage.lead"),
    onClose: close,
    body: [...body, urgentCheck],
    foot: footButtons,
  });
}

/* ==================================================================== *
 * Local review summary
 * ==================================================================== */
function randomId(length) {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let out = "";
  for (const byte of bytes) out += alphabet[byte % alphabet.length];
  return out;
}

/**
 * Builds the local summary. Only fields taken from the generated dataset go
 * under `transaction`; anything the person typed or clicked stays under
 * `customer_answers`, never mixed into the transaction facts.
 */
function buildSummary() {
  const tr = state.triage;
  const tx = txById(tr.transactionId);
  if (!tx) return;
  const product = productOf(tx);

  const open = [];
  if (!tr.urgent) {
    for (const question of QUESTIONS) {
      const answer = tr.answers[question.id];
      if (answer === undefined || answer === "unsure") open.push(t(question.key));
    }
    if (!tx.merchant_name) open.push(t("tx.unknownMerchant"));
    if (tx.transaction_status === "pending") open.push(t("tx.pendingNote"));
  }

  state.summary = {
    schema: "savia-lite/local-review/v1",
    local_only: true,
    synthetic: true,
    reference: `REV-LOCAL-${randomId(8)}`,
    created_at: new Date().toISOString(),
    language: state.language,
    reason: tr.urgent ? "security_concern" : "unrecognised_charge",
    transaction: {
      reference: tx.transaction_id,
      event_date: tx.transaction_date,
      process_date: tx.process_date,
      amount: tx.amount,
      currency: tx.currency,
      direction: tx.direction,
      status: tx.transaction_status,
      type: tx.transaction_type,
      channel: tx.channel,
      merchant: tx.merchant_name,
      category: tx.transaction_category,
      product: product ? product.product_type : null,
      country: tx.transaction_country,
      city: tx.transaction_city,
      dataset: DATASET.id,
      build_id: DATASET.build_id,
    },
    customer_answers: tr.urgent ? { card_lost_or_stolen: true } : { ...tr.answers },
    customer_note: tr.notes.trim(),
    open_questions: open.slice(0, 4),
    bank_action_taken: false,
    dispute_submitted: false,
    refund_issued: false,
    agent_transfer: false,
    response_deadline_promised: false,
    next_step: "Local human review. No bank decision and no response deadline promised.",
  };
  openDialog("summary");
}

function renderSummary() {
  const summary = state.summary;
  if (!summary) return null;
  const close = () => { closeDialog(); state.triage = null; state.summary = null; render(); };
  const tx = summary.transaction;

  const reasonLabel = summary.reason === "security_concern"
    ? t("sum.reasonSecurity")
    : t("sum.reasonUnrecognised");

  const factRows = h("dl", { class: "facts" },
    fact(t("tx.reference"), tx.reference, true),
    fact(t("tx.merchant"), tx.merchant || h("span", { class: "unknown" }, t("tx.unknownMerchant"))),
    fact(t("tx.amount"), `${formatMoney(tx.amount, tx.currency, state.language)} (${tx.currency})`),
    fact(t("tx.eventDate"), formatDayTime(tx.event_date, state.language)),
    fact(t("tx.processDate"), formatDay(tx.process_date, state.language)),
    fact(t("tx.status"), t(`status.${tx.status}`)),
    fact(t("tx.direction"), directionWord(tx.direction)));

  const answerRows = Object.entries(summary.customer_answers).map(([key, value]) => {
    const question = QUESTIONS.find((item) => item.id === key);
    const label = question ? t(question.key) : t("triage.urgent");
    const shown = value === true ? t("triage.yes") : t(`triage.${value}`);
    return h("div", { class: "qa-row" }, h("span", {}, label), h("strong", {}, shown));
  });

  const openRows = summary.open_questions.length
    ? h("ul", { class: "help-list" }, summary.open_questions.map((question) => h("li", {},
        h("span", { class: "mark", "aria-hidden": "true" }, "?"),
        h("span", {}, question))))
    : h("p", { class: "note" }, t("sum.none"));

  const notDone = h("ul", { class: "not-done" },
    [t("sum.notDone1"), t("sum.notDone2"), t("sum.notDone3"), t("sum.notDone4")]
      .map((line) => h("li", {},
        h("span", { class: "mark", "aria-hidden": "true" }, "✕"),
        h("span", {}, line))));

  const body = [
    h("div", { class: "sum-id" },
      h("span", { "aria-hidden": "true" }, "#"),
      h("span", {}, summary.reference)),
    h("p", { class: "note", style: "margin-top:10px" }, t("sum.lead")),
    summary.reason === "security_concern"
      ? h("div", { class: "notice notice-stop", style: "margin-top:14px" },
          h("span", { class: "mark", "aria-hidden": "true" }, "!"),
          h("span", {}, t("sum.urgentAdvice")))
      : null,
    h("div", { class: "sum-block" },
      h("h4", {}, t("sum.reason")),
      h("p", { style: "margin-top:5px;font-weight:600" }, reasonLabel)),
    h("div", { class: "sum-block" },
      h("h4", {}, t("sum.facts")),
      h("p", { class: "note" }, t("sum.factsNote")),
      factRows),
    h("div", { class: "sum-block" },
      h("h4", {}, t("sum.answers")),
      h("p", { class: "note" }, t("sum.answersNote")),
      h("div", { class: "qa" }, answerRows),
      summary.customer_note
        ? frag(h("h4", { style: "margin-top:16px" }, t("sum.notes")),
            h("p", { style: "margin-top:5px" }, summary.customer_note))
        : null),
    h("div", { class: "sum-block" },
      h("h4", {}, t("sum.open")),
      openRows),
    h("div", { class: "sum-block" },
      h("h4", { style: "color:var(--stop)" }, t("sum.notDoneTitle")),
      notDone),
  ];

  const json = JSON.stringify(summary, null, 2);
  const foot = [
    h("button", { class: "btn btn-ghost", type: "button", onClick: () => copyText(json, t("sum.copied")) },
      t("sum.copy")),
    h("button", {
      class: "btn btn-ghost",
      type: "button",
      onClick: () => {
        download(`${summary.reference}.json`, json, "application/json;charset=utf-8");
        toast(t("sum.downloaded"));
      },
    }, t("sum.download")),
    h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-autofocus": "true", onClick: close }, t("sum.close")),
  ];

  return modalShell({
    label: t("sum.title"),
    title: t("sum.title"),
    lead: null,
    wide: true,
    onClose: close,
    body,
    foot,
  });
}

/* ==================================================================== *
 * Help
 * ==================================================================== */
function helpList(items, kind, mark) {
  return h("ul", { class: `help-list ${kind}` }, items.map((item) => h("li", {},
    h("span", { class: "mark", "aria-hidden": "true" }, mark),
    h("span", {}, item))));
}

function renderHelpBody() {
  const keys = [
    { combo: "Ctrl / ⌘ + K", label: t("help.keyPalette") },
    { combo: "/", label: t("help.keySearch") },
    { combo: "↑ ↓", label: t("help.keyList") },
    { combo: "Enter", label: t("help.keyOpen") },
    { combo: "Esc", label: t("help.keyClose") },
    { combo: "Shift + T", label: t("help.keyTheme") },
  ];

  return frag(
    h("div", { class: "help-grid" },
      card(t("help.isTitle"), null, null,
        helpList([t("help.is1"), t("help.is2"), t("help.is3"), t("help.is4")], "is-yes", "✓")),
      card(t("help.isNotTitle"), null, null,
        helpList([t("help.isNot1"), t("help.isNot2"), t("help.isNot3"), t("help.isNot4")], "is-no", "✕"))),
    h("div", { class: "help-grid", style: "margin-top:14px" },
      card(t("help.dataTitle"), null, null,
        helpList([t("help.data1"), t("help.data2"), t("help.data3"), t("help.data4")], "", "·")),
      card(t("help.keysTitle"), null, null,
        h("div", { class: "keys" }, keys.map((key) => h("div", { class: "key-row" },
          h("span", { class: "kbd" }, key.combo),
          h("span", {}, key.label)))))),
    h("div", { class: "help-grid", style: "margin-top:14px" },
      card(t("help.a11yTitle"), null, null,
        helpList([t("help.a11y1"), t("help.a11y2"), t("help.a11y3")], "", "·")),
      card(t("help.checkTitle"), null, null,
        h("p", { style: "font-size:.85rem;line-height:1.55;color:var(--ink-2)" }, t("help.check")))));
}

function renderHelpPage() {
  return h("div", { class: "view" },
    h("div", { class: "page-head" },
      h("h1", {}, t("help.title")),
      h("p", { class: "note" }, t("help.lead"))),
    renderHelpBody());
}

function renderHelpDialog() {
  return modalShell({
    label: t("help.title"),
    title: t("help.title"),
    lead: t("help.lead"),
    wide: true,
    onClose: closeDialog,
    body: [renderHelpBody()],
    foot: [h("button", { class: "btn", type: "button", "data-autofocus": "true", onClick: closeDialog }, t("sum.close"))],
  });
}

/* ==================================================================== *
 * Command palette
 * ==================================================================== */
function paletteItems() {
  const query = state.palette.query.trim().toLowerCase();
  const groups = [];

  const navItems = [
    { glyph: VIEW_GLYPH.home, label: t("nav.home"), run: () => goTo("home") },
    { glyph: VIEW_GLYPH.movements, label: t("nav.movements"), run: () => goTo("movements") },
    { glyph: VIEW_GLYPH.insights, label: t("nav.insights"), run: () => goTo("insights") },
    { glyph: VIEW_GLYPH.help, label: t("nav.help"), run: () => goTo("help") },
  ].filter((item) => !query || item.label.toLowerCase().includes(query));
  if (navItems.length) groups.push({ title: t("cmd.navSection"), items: navItems });

  const actions = [
    { glyph: "◐", label: t("nav.theme"), run: () => setTheme(state.theme === "dark" ? "light" : "dark") },
    { glyph: "↧", label: t("mov.export"), run: exportCsv },
    { glyph: "→", label: t("home.tour"), run: () => goTo("home") },
    ...LANGUAGES.map((lang) => ({
      glyph: "⌘", label: `${t("nav.language")}: ${lang.native}`, run: () => setLanguage(lang.code),
    })),
    { glyph: "⇥", label: t("nav.logout"), run: signOut },
  ].filter((item) => !query || item.label.toLowerCase().includes(query));
  if (actions.length) groups.push({ title: t("cmd.actionSection"), items: actions });

  if (query) {
    const matches = state.account.transactions
      .filter((tx) => matchesQuery(tx, query))
      .slice(0, 6)
      .map((tx) => {
        const merchant = merchantText(tx);
        return {
          glyph: TYPE_GLYPH[tx.transaction_type] || "•",
          label: merchant.text,
          sub: `${formatDay(tx.transaction_date, state.language)} · ${signedMoney(tx.amount, tx.currency, tx.direction, state.language)}`,
          run: () => { closeDialog(); select(tx.transaction_id); },
        };
      });
    if (matches.length) groups.push({ title: t("cmd.txSection"), items: matches });
  }

  const flat = [];
  for (const group of groups) for (const item of group.items) flat.push(item);
  return { groups, flat };
}

function renderPalette() {
  const { groups, flat } = paletteItems();
  if (state.palette.index >= flat.length) state.palette.index = Math.max(0, flat.length - 1);

  let cursor = 0;
  const list = groups.length
    ? groups.map((group) => frag(
        h("div", { class: "palette-group" }, group.title),
        group.items.map((item) => {
          const index = cursor++;
          return h("button", {
            class: `palette-item ${index === state.palette.index ? "is-active" : ""}`.trim(),
            type: "button",
            onMouseEnter: () => { state.palette.index = index; },
            onClick: () => { item.run(); },
          },
            h("span", { class: "palette-glyph", "aria-hidden": "true" }, item.glyph),
            h("span", {}, item.label,
              item.sub ? h("span", { class: "palette-sub", style: "display:block" }, item.sub) : null),
            h("span", { class: "palette-sub" }, index === state.palette.index ? "↵" : ""));
        })))
    : h("p", { class: "palette-empty" }, t("cmd.empty"));

  const paletteCard = h("div", { class: "modal-card palette-card", role: "dialog", "aria-modal": "true", "aria-label": t("cmd.title") },
    h("input", {
      id: "palette-input",
      class: "palette-input",
      type: "text",
      value: state.palette.query,
      placeholder: t("cmd.placeholder"),
      "aria-label": t("cmd.title"),
      "data-autofocus": "true",
      autocomplete: "off",
      onInput: (event) => {
        state.palette.query = event.target.value;
        state.palette.index = 0;
        renderKeepCaret("#palette-input");
      },
      onKeyDown: (event) => {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          state.palette.index = Math.min(state.palette.index + 1, flat.length - 1);
          render();
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          state.palette.index = Math.max(state.palette.index - 1, 0);
          render();
        } else if (event.key === "Enter") {
          event.preventDefault();
          const chosen = flat[state.palette.index];
          if (chosen) chosen.run();
        }
      },
    }),
    h("div", { class: "palette-list" }, list),
    h("div", { class: "palette-foot" }, t("cmd.hint")));

  return h("div", {
    class: "modal",
    dataset: { dialog: "palette" },
    onClick: (event) => { if (event.target.classList.contains("modal")) closeDialog(); },
  }, paletteCard);
}

/* ==================================================================== *
 * Modal shell
 * ==================================================================== */
function modalShell({ label, title, lead, body, foot, onClose, wide }) {
  return h("div", {
    class: "modal",
    dataset: { dialog: "modal" },
    onClick: (event) => { if (event.target.classList.contains("modal")) onClose(); },
  },
    h("div", {
      class: `modal-card ${wide ? "is-wide" : ""}`.trim(),
      role: "dialog",
      "aria-modal": "true",
      "aria-label": label,
    },
      h("div", { class: "modal-head" },
        h("div", {},
          h("h2", {}, title),
          lead ? h("p", { class: "note", style: "margin-top:4px;max-width:58ch" }, lead) : null),
        closeButton(onClose)),
      h("div", { class: "modal-body" }, body),
      h("div", { class: "modal-foot" }, foot)));
}

/* ==================================================================== *
 * Shell
 * ==================================================================== */
function goTo(view) {
  state.view = view;
  state.selectedId = null;
  if (state.dialog === "palette") closeDialog();
  render();
  window.scrollTo({ top: 0, behavior: "auto" });
}

function openDialog(name) {
  if (name === "palette" && !returnFocusTo) returnFocusTo = ".search-trigger";
  state.dialog = name;
  if (name === "palette") state.palette = { query: "", index: 0 };
  render();
}

function closeDialog() {
  state.dialog = null;
  render();
}

const VIEWS = ["home", "movements", "insights", "help"];

function renderShell(viewNode) {
  const profile = state.account.profile;

  const tabs = h("nav", { class: "tabs", "aria-label": t("a11y.menu") },
    VIEWS.map((view) => h("button", {
      class: "tab",
      type: "button",
      "aria-current": state.view === view ? "page" : null,
      onClick: () => goTo(view),
    }, t(`nav.${view}`))));

  const topbar = h("header", { class: "topbar" },
    h("button", { class: "brand", type: "button", onClick: () => goTo("home") },
      "savia", h("span", { class: "brand-dot" }, "."), h("span", { class: "brand-tag" }, "lite")),
    tabs,
    h("span", { class: "topbar-spacer" }),
    h("button", { class: "search-trigger", type: "button", onClick: () => openDialog("palette") },
      h("span", { "aria-hidden": "true" }, "⌕"),
      h("span", { class: "label" }, t("cmd.open")),
      h("span", { class: "kbd" }, "Ctrl K")),
    h("div", { class: "seg", role: "group", "aria-label": t("nav.language") },
      LANGUAGES.map((lang) => h("button", {
        type: "button",
        "aria-pressed": String(state.language === lang.code),
        onClick: () => setLanguage(lang.code),
      }, lang.code.toUpperCase()))),
    h("button", {
      class: "icon-btn",
      type: "button",
      "aria-label": t("nav.theme"),
      onClick: () => setTheme(state.theme === "dark" ? "light" : "dark"),
    }, state.theme === "dark" ? "☀" : "☾"),
    h("div", { class: "who" },
      h("span", { class: "avatar", "aria-hidden": "true" }, profile.initials),
      h("span", { class: "who-name" }, profile.alias),
      h("button", { type: "button", onClick: signOut }, t("nav.logout"))));

  const bottomNav = h("nav", { class: "bottom-nav", "aria-label": t("a11y.menu") },
    VIEWS.map((view) => h("button", {
      type: "button",
      "aria-current": state.view === view ? "page" : null,
      onClick: () => goTo(view),
    },
      h("span", { class: "glyph", "aria-hidden": "true" }, VIEW_GLYPH[view]),
      h("span", {}, t(`nav.${view}`)))));

  const footer = h("footer", { class: "foot" },
    h("span", {}, `© 2026 Savia Lite · ${t("app.tagline")}`),
    h("code", {}, `${DATASET.id} · ${DATASET.build_id} · synthetic=true`));

  return h("div", { class: "shell" }, topbar,
    h("main", { id: "main", tabindex: "-1", "aria-label": t("a11y.main") }, viewNode),
    footer, bottomNav);
}

function renderBanner() {
  if (state.bannerDismissed) return null;
  return h("div", { class: "banner" },
    h("span", { class: "banner-text" },
      h("strong", {}, "Savia Lite ·"),
      t("banner.synthetic")),
    h("button", {
      type: "button",
      onClick: () => { state.bannerDismissed = true; savePreferences(); render(); },
    }, t("banner.dismiss")));
}

/* ==================================================================== *
 * Render
 * ==================================================================== */
const root = document.getElementById("root");

function currentView() {
  if (state.view === "movements") return renderMovements();
  if (state.view === "insights") return renderInsights();
  if (state.view === "help") return renderHelpPage();
  return renderHome();
}

function activeDialog() {
  if (state.dialog === "palette") return renderPalette();
  if (state.dialog === "triage") return renderTriage();
  if (state.dialog === "summary") return renderSummary();
  if (state.dialog === "help") return renderHelpDialog();
  return null;
}

function render() {
  document.documentElement.lang = state.language;
  document.documentElement.dataset.theme = state.theme;
  document.title = t("app.title");

  const scrollY = window.scrollY;
  clear(root);

  root.append(h("a", { class: "skip", href: "#main" }, t("a11y.skip")));
  const banner = renderBanner();
  if (banner) root.append(banner);

  if (!state.account) {
    root.append(renderGate());
  } else {
    root.append(renderShell(currentView()));
    const panel = renderDetail();
    if (panel) {
      root.append(h("div", { class: "scrim", onClick: closePanel }), panel);
    }
  }

  const dialog = activeDialog();
  if (dialog) root.append(dialog);
  root.append(renderToasts());

  if (state.account) window.scrollTo({ top: scrollY, behavior: "auto" });
  manageFocus();
}

/**
 * Binds Tab cycling to whichever overlay is on screen, moves focus into it the
 * first time it appears, and hands focus back when it goes away. Re-renders
 * while the same overlay stays open never move focus, so typing and clicking
 * inside a dialog behave normally.
 */
function manageFocus() {
  if (unbindTab) {
    unbindTab();
    unbindTab = null;
  }

  const surface = root.querySelector("[data-dialog] .modal-card")
    || root.querySelector('[data-panel="detail"]');
  const owner = state.dialog
    ? `dialog:${state.dialog}`
    : state.selectedId ? `panel:${state.selectedId}` : null;

  if (surface) unbindTab = bindTabCycle(surface);

  if (owner === focusOwner) return;

  if (owner && surface) {
    focusFirst(surface);
  } else if (!owner) {
    const target = returnFocusTo ? document.querySelector(returnFocusTo) : null;
    if (target) target.focus();
    returnFocusTo = null;
  }
  focusOwner = owner;
}

/** Re-render while keeping the caret inside the field the user is typing in. */
function renderKeepCaret(selector) {
  const before = document.querySelector(selector);
  const caret = before && typeof before.selectionStart === "number" ? before.selectionStart : null;
  render();
  const after = document.querySelector(selector);
  if (!after) return;
  after.focus();
  if (caret !== null && typeof after.setSelectionRange === "function") {
    try {
      after.setSelectionRange(caret, caret);
    } catch {
      /* Some input types refuse selection ranges; focus alone is fine. */
    }
  }
}

/* ==================================================================== *
 * Keyboard
 * ==================================================================== */
function isTyping(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

function moveRowFocus(step) {
  const rows = [...document.querySelectorAll(".tx-row")];
  if (!rows.length) return false;
  const index = rows.indexOf(document.activeElement);
  if (index === -1) {
    rows[0].focus();
    return true;
  }
  const next = rows[Math.min(Math.max(index + step, 0), rows.length - 1)];
  next.focus();
  return true;
}

document.addEventListener("keydown", (event) => {
  const key = event.key;

  if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === "k") {
    event.preventDefault();
    if (state.account) openDialog("palette");
    return;
  }

  if (key === "Escape") {
    if (state.dialog) {
      if (state.dialog === "triage") { state.triage = null; }
      if (state.dialog === "summary") { state.triage = null; state.summary = null; }
      closeDialog();
    } else if (state.selectedId) {
      closePanel();
    }
    return;
  }

  if (isTyping(event.target)) {
    if ((key === "ArrowDown") && event.target.id === "tx-search") {
      event.preventDefault();
      moveRowFocus(1);
    }
    return;
  }

  if (!state.account) return;

  if (key === "/") {
    event.preventDefault();
    const search = document.getElementById("tx-search");
    if (search) search.focus();
    else openDialog("palette");
    return;
  }

  if (key === "T" && event.shiftKey) {
    event.preventDefault();
    setTheme(state.theme === "dark" ? "light" : "dark");
    return;
  }

  if (key === "ArrowDown" || key === "j") {
    if (moveRowFocus(1)) event.preventDefault();
    return;
  }
  if (key === "ArrowUp" || key === "k") {
    if (moveRowFocus(-1)) event.preventDefault();
  }
});

/* ==================================================================== *
 * Boot
 * ==================================================================== */
loadPreferences();
t = createTranslator(state.language);
state.gateProfile = PROFILES[0].id;
document.documentElement.dataset.theme = state.theme;
render();
