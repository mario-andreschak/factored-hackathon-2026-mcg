/**
 * Savia Lite - deterministic demo dataset.
 *
 * Every record produced here is INVENTED by this generator, in this browser
 * tab. Nothing is read from the organizer snapshot, from S3, or from any
 * customer record. There is no server and no network call.
 *
 * The field names mirror the organizer schema (transaction_date / process_date /
 * channel / merchant_name / transaction_status / transaction_category) so the
 * screens exercise the same shapes the real API returns.
 *
 * It deliberately reproduces the three properties that make the published
 * snapshot awkward to present, because a demo that hides them teaches the
 * wrong lesson:
 *
 *   1. most rows carry no merchant at all;
 *   2. a quarter of events are stamped one calendar day after the day they
 *      were processed;
 *   3. transfers, payments and adjustments carry no debit/credit indicator,
 *      so their direction is genuinely unknown.
 *
 * The generator is seeded, so a given build always produces the same rows.
 */

export const DATASET = Object.freeze({
  id: "savia-lite-demo",
  synthetic: true,
  origin: "generated_in_browser",
  build_id: "SAVIA-LITE-0002",
  window_start: "2025-07-01",
  window_end: "2026-06-17",
  latest_process_date: "2026-06-17",
  latest_event_date: "2026-06-18",
  balances_note: "snapshot_balance_not_recomputed",
  amounts_note: "positive_magnitudes",
  // Targets the generator aims at, asserted by tools/selfcheck.mjs.
  merchant_coverage: 0.28,
  next_day_event_share: 0.25,
});

/* ==================================================================== *
 * Seeded pseudo-random source (mulberry32). Deterministic by design.
 * ==================================================================== */
function rng(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const pick = (r, list) => list[Math.floor(r() * list.length)];
const between = (r, lo, hi) => lo + r() * (hi - lo);
const money = (r, lo, hi) => Math.round(between(r, lo, hi) * 100) / 100;
const chance = (r, p) => r() < p;

/* ==================================================================== *
 * Calendar helpers. All arithmetic runs in UTC so the host timezone can
 * never move a transaction to a different calendar day.
 * ==================================================================== */
const pad = (n) => String(n).padStart(2, "0");

function toDay(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}
function fromDay(ms) {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}
function addDays(iso, n) {
  return fromDay(toDay(iso) + n * 86400000);
}
function dayCount(startIso, endIso) {
  return Math.round((toDay(endIso) - toDay(startIso)) / 86400000);
}
function weekday(iso) {
  return new Date(toDay(iso)).getUTCDay(); // 0 = Sunday
}
const stamp = (iso, hh, mm) => `${iso} ${pad(hh)}:${pad(mm)}:00`;

/* ==================================================================== *
 * Reference vocabularies. Codes are language-neutral; assets/i18n.js owns
 * every human-readable label.
 * ==================================================================== */
export const TYPES = ["purchase", "withdrawal", "deposit", "transfer", "payment", "adjustment"];
export const STATUSES = ["approved", "pending", "declined", "reversed"];
export const CHANNELS = ["atm", "app", "direct_debit", "ecommerce", "pos", "branch"];
export const CATEGORIES = [
  "groceries", "dining", "transport", "health", "education",
  "home", "tech", "entertainment", "services", "travel",
];

/**
 * Only `purchase`, `withdrawal` and `deposit` carry a reliable sign in the
 * organizer schema. Everything else is genuinely ambiguous, and the interface
 * must say so instead of inventing a direction.
 */
export function directionFor(type) {
  if (type === "purchase" || type === "withdrawal") return "debit";
  if (type === "deposit") return "credit";
  return "unknown";
}

/** Invented merchant names, grouped by the category they are booked under. */
const MERCHANTS = [
  { name: "Mercado Verdemar", category: "groceries", channels: ["pos", "ecommerce"] },
  { name: "Super La Colina", category: "groceries", channels: ["pos"] },
  { name: "Frutas del Valle", category: "groceries", channels: ["pos"] },
  { name: "Cafe Bracero", category: "dining", channels: ["pos"] },
  { name: "Panaderia Dona Rosa", category: "dining", channels: ["pos"] },
  { name: "Cocina Abuela Ines", category: "dining", channels: ["pos", "ecommerce"] },
  { name: "Sushi Nueve", category: "dining", channels: ["ecommerce"] },
  { name: "Transporte Urbano SA", category: "transport", channels: ["app", "pos"] },
  { name: "Estacion Norte Combustible", category: "transport", channels: ["pos"] },
  { name: "Taxi Directo", category: "transport", channels: ["app"] },
  { name: "Farmacia San Lucas", category: "health", channels: ["pos"] },
  { name: "Laboratorio Vital", category: "health", channels: ["branch", "pos"] },
  { name: "Instituto Aurora", category: "education", channels: ["direct_debit"] },
  { name: "Libreria Papel y Tinta", category: "education", channels: ["pos", "ecommerce"] },
  { name: "Ferreteria El Yunque", category: "home", channels: ["pos"] },
  { name: "Muebles Nogal", category: "home", channels: ["ecommerce"] },
  { name: "AMZ MKTPLACE LATAM", category: "tech", channels: ["ecommerce"] },
  { name: "Tienda Pixel", category: "tech", channels: ["ecommerce", "pos"] },
  { name: "Cine Estelar", category: "entertainment", channels: ["pos", "ecommerce"] },
  { name: "Teatro Municipal", category: "entertainment", channels: ["pos"] },
  { name: "Lavanderia Clara", category: "services", channels: ["pos"] },
  { name: "Viajes Horizonte", category: "travel", channels: ["ecommerce"] },
  { name: "Hostal Miramar", category: "travel", channels: ["ecommerce", "branch"] },
];

/* ==================================================================== *
 * Demo profiles. The names are invented aliases and represent nobody.
 * `scale` only moves the order of magnitude so each currency reads
 * plausibly; it is not an exchange rate.
 * ==================================================================== */
export const PROFILES = [
  {
    id: "co-premium",
    seed: 20260601,
    alias: "Camila Restrepo",
    first_name: "Camila",
    initials: "CR",
    country: "Colombia",
    city: "Bogota",
    segment: "Premium",
    currency: "COP",
    language: "es",
    scale: 1,
    salary: 4_200_000,
    products: ["savings", "credit_card", "investment"],
  },
  {
    id: "ar-classic",
    seed: 20260602,
    alias: "Mateo Duarte",
    first_name: "Mateo",
    initials: "MD",
    country: "Argentina",
    city: "Cordoba",
    segment: "Classic",
    currency: "ARS",
    language: "es",
    scale: 0.42,
    salary: 1_650_000,
    products: ["checking", "credit_card"],
  },
  {
    id: "br-preferencial",
    seed: 20260603,
    alias: "Beatriz Nogueira",
    first_name: "Beatriz",
    initials: "BN",
    country: "Brasil",
    city: "Sao Paulo",
    segment: "Preferencial",
    currency: "BRL",
    language: "pt",
    scale: 0.0052,
    salary: 21_800,
    products: ["savings", "credit_card", "investment"],
  },
];

export const profileById = (id) => PROFILES.find((p) => p.id === id) || PROFILES[0];

/* ==================================================================== *
 * Products
 * ==================================================================== */
const PRODUCT_SHAPES = {
  savings:     { kind: "deposit",    rate: [1.2, 2.4],   opened: "2021-04-19" },
  checking:    { kind: "deposit",    rate: [0, 0.4],     opened: "2020-08-03" },
  credit_card: { kind: "credit",     rate: [18, 34],     opened: "2022-11-02" },
  investment:  { kind: "investment", rate: [4.1, 6.9],   opened: "2024-02-15" },
};

function buildProducts(profile, r) {
  return profile.products.map((type, index) => {
    const shape = PRODUCT_SHAPES[type];
    const isInvestment = type === "investment";
    const currency = isInvestment ? "USD" : profile.currency;
    const base = isInvestment ? money(r, 3200, 9400) : money(r, 900_000, 3_600_000) * profile.scale;
    const limit = type === "credit_card" ? Math.round(profile.salary * between(r, 0.6, 1.1)) : null;
    return {
      product_id: `${profile.id.toUpperCase()}-P${index + 1}`,
      masked_number: String(1000 + Math.floor(r() * 8999)),
      product_type: type,
      balance_kind: shape.kind,
      currency,
      // Snapshot value. It is never recomputed by summing the rows below.
      current_balance: type === "credit_card"
        ? Math.round(limit * between(r, 0.14, 0.42) * 100) / 100
        : Math.round(base * 100) / 100,
      credit_limit: limit,
      interest_rate: Math.round(between(r, shape.rate[0], shape.rate[1]) * 100) / 100,
      opening_date: shape.opened,
      product_status: "active",
    };
  });
}

/* ==================================================================== *
 * Transactions
 * ==================================================================== */
const TYPE_WEIGHTS = [
  ["purchase", 0.56],
  ["payment", 0.12],
  ["transfer", 0.11],
  ["withdrawal", 0.09],
  ["adjustment", 0.07],
  ["deposit", 0.05],
];
function weightedType(r) {
  let roll = r();
  for (const [type, weight] of TYPE_WEIGHTS) {
    if (roll < weight) return type;
    roll -= weight;
  }
  return "purchase";
}

const AMOUNT_RANGES = {
  purchase:    [8_000, 260_000],
  withdrawal:  [40_000, 420_000],
  deposit:     [180_000, 1_400_000],
  transfer:    [60_000, 900_000],
  payment:     [30_000, 700_000],
  adjustment:  [5_000, 180_000],
};

function statusFor(r) {
  const roll = r();
  if (roll < 0.9) return "approved";
  if (roll < 0.955) return "pending";
  if (roll < 0.985) return "declined";
  return "reversed";
}

/**
 * Channels are constrained per type so the scenario never produces a nonsense
 * pairing such as a purchase "at an ATM" or a transfer through a card terminal.
 */
function channelFor(r, type, merchant) {
  if (type === "withdrawal") return "atm";
  if (type === "purchase") return merchant ? pick(r, merchant.channels) : pick(r, ["pos", "ecommerce", "app"]);
  if (type === "payment") return merchant ? "direct_debit" : pick(r, ["direct_debit", "app", "branch"]);
  if (type === "deposit") return pick(r, ["branch", "app", "atm"]);
  if (type === "transfer") return pick(r, ["app", "branch"]);
  return pick(r, ["app", "branch", "direct_debit"]);
}

/**
 * Builds one everyday movement.
 *
 * The merchant is deliberately absent most of the time. When it is absent the
 * category is absent too: the interface must not infer a category it was
 * never given.
 */
function makeRow(profile, products, r, processDate, seq) {
  const type = weightedType(r);
  const hasMerchant = type === "purchase" ? chance(r, 0.33)
    : type === "payment" ? chance(r, 0.12)
    : false;
  const merchant = hasMerchant ? pick(r, MERCHANTS) : null;
  const channel = channelFor(r, type, merchant);
  const product = pick(r, products.filter((p) => p.product_type !== "investment"));
  const range = AMOUNT_RANGES[type];
  const amount = Math.round(money(r, range[0], range[1]) * profile.scale * 100) / 100;

  // A quarter of events are stamped on the calendar day after processing.
  const lateEvent = chance(r, 0.25);
  const eventDate = lateEvent ? addDays(processDate, 1) : processDate;
  const hour = lateEvent ? Math.floor(between(r, 0, 3)) : Math.floor(between(r, 6, 23));
  const minute = Math.floor(r() * 60);

  return {
    transaction_id: `TXS-${String(seq).padStart(5, "0")}`,
    product_id: product.product_id,
    process_date: processDate,
    transaction_date: stamp(eventDate, hour, minute),
    transaction_type: type,
    transaction_category: merchant ? merchant.category : null,
    amount,
    currency: product.currency,
    channel,
    merchant_name: merchant ? merchant.name : null,
    transaction_country: profile.country,
    transaction_city: merchant ? profile.city : null,
    transaction_status: statusFor(r),
    direction: directionFor(type),
    reversal_of: null,
    scenario: null,
  };
}

/** Three monthly subscriptions plus the monthly salary credit. */
function makeRecurring(profile, products, r, seq) {
  const rows = [];
  const card = products.find((p) => p.product_type === "credit_card") || products[0];
  const main = products.find((p) => p.balance_kind === "deposit") || products[0];

  const subs = [
    { name: "Nube Global", category: "services", day: 4, amount: 38_900, channel: "direct_debit" },
    { name: "Gimnasio Pulso", category: "services", day: 13, amount: 129_000, channel: "direct_debit" },
    { name: "Estelar Streaming", category: "entertainment", day: 21, amount: 26_500, channel: "ecommerce" },
  ];

  let cursor = "2025-07-01";
  while (cursor <= DATASET.window_end) {
    const [year, month] = cursor.split("-").map(Number);
    for (const sub of subs) {
      const date = `${year}-${pad(month)}-${pad(sub.day)}`;
      if (date < DATASET.window_start || date > DATASET.window_end) continue;
      rows.push({
        transaction_id: `TXS-R${String(seq++).padStart(4, "0")}`,
        product_id: card.product_id,
        process_date: date,
        transaction_date: stamp(date, 9, 12),
        transaction_type: "purchase",
        transaction_category: sub.category,
        amount: Math.round(sub.amount * profile.scale * 100) / 100,
        currency: card.currency,
        channel: sub.channel,
        merchant_name: sub.name,
        transaction_country: profile.country,
        transaction_city: profile.city,
        transaction_status: "approved",
        direction: "debit",
        reversal_of: null,
        scenario: "recurring",
      });
    }
    // Salary credit, paid on the 28th.
    const payday = `${year}-${pad(month)}-28`;
    if (payday >= DATASET.window_start && payday <= DATASET.window_end) {
      rows.push({
        transaction_id: `TXS-R${String(seq++).padStart(4, "0")}`,
        product_id: main.product_id,
        process_date: payday,
        transaction_date: stamp(payday, 7, 30),
        transaction_type: "deposit",
        transaction_category: null,
        amount: Math.round(profile.salary * between(r, 0.98, 1.02) * 100) / 100,
        currency: main.currency,
        channel: "branch",
        merchant_name: null,
        transaction_country: profile.country,
        transaction_city: null,
        transaction_status: "approved",
        direction: "credit",
        reversal_of: null,
        scenario: "payroll",
      });
    }
    cursor = month === 12 ? `${year + 1}-01-01` : `${year}-${pad(month + 1)}-01`;
  }
  return rows;
}

/**
 * Six hand-placed situations, so a reviewer can always find the hard cases
 * instead of hunting for them. Each one exists to prove a wording rule.
 */
function makeScenarios(profile, products, r) {
  const card = products.find((p) => p.product_type === "credit_card") || products[0];
  const main = products.find((p) => p.balance_kind === "deposit") || products[0];
  const s = profile.scale;
  const base = (value) => Math.round(value * s * 100) / 100;
  const row = (over) => ({
    transaction_country: profile.country,
    transaction_city: profile.city,
    reversal_of: null,
    ...over,
  });

  const dupAmount = base(94_300);

  return [
    // 1. Opaque acquirer descriptor, and an event stamped the day after processing.
    row({
      transaction_id: "TXS-S01",
      product_id: card.product_id,
      process_date: "2026-06-14",
      transaction_date: "2026-06-15 22:41:00",
      transaction_type: "purchase",
      transaction_category: "tech",
      amount: base(236_400),
      currency: card.currency,
      channel: "ecommerce",
      merchant_name: "DLC*PAGOS DIGITALES 8829",
      transaction_status: "approved",
      direction: "debit",
      scenario: "opaque_descriptor",
    }),
    // 2 + 3. A duplicate-looking pair: same merchant, amount and currency, 4h apart.
    row({
      transaction_id: "TXS-S02",
      product_id: card.product_id,
      process_date: "2026-06-12",
      transaction_date: "2026-06-12 13:08:00",
      transaction_type: "purchase",
      transaction_category: "dining",
      amount: dupAmount,
      currency: card.currency,
      channel: "pos",
      merchant_name: "Cafe Bracero",
      transaction_status: "approved",
      direction: "debit",
      scenario: "duplicate_pair",
    }),
    row({
      transaction_id: "TXS-S03",
      product_id: card.product_id,
      process_date: "2026-06-12",
      transaction_date: "2026-06-12 17:52:00",
      transaction_type: "purchase",
      transaction_category: "dining",
      amount: dupAmount,
      currency: card.currency,
      channel: "pos",
      merchant_name: "Cafe Bracero",
      transaction_status: "pending",
      direction: "debit",
      scenario: "duplicate_pair",
    }),
    // 4. Pending withdrawal with no merchant at all, event stamped the next day.
    row({
      transaction_id: "TXS-S04",
      product_id: main.product_id,
      process_date: "2026-06-17",
      transaction_date: "2026-06-18 00:42:00",
      transaction_type: "withdrawal",
      transaction_category: null,
      amount: base(221_000),
      currency: main.currency,
      channel: "atm",
      merchant_name: null,
      transaction_city: null,
      transaction_status: "pending",
      direction: "debit",
      scenario: "pending_authorisation",
    }),
    // 5 + 6. A charge and a separate reversal entry. A reversal entry is not
    // proof that money arrived back, and the interface must not say it is.
    row({
      transaction_id: "TXS-S05",
      product_id: card.product_id,
      process_date: "2026-06-05",
      transaction_date: "2026-06-05 11:24:00",
      transaction_type: "purchase",
      transaction_category: "home",
      amount: base(418_700),
      currency: card.currency,
      channel: "ecommerce",
      merchant_name: "Muebles Nogal",
      transaction_status: "reversed",
      direction: "debit",
      scenario: "reversal_origin",
    }),
    row({
      transaction_id: "TXS-S06",
      product_id: card.product_id,
      process_date: "2026-06-09",
      transaction_date: "2026-06-09 08:15:00",
      transaction_type: "adjustment",
      transaction_category: "home",
      amount: base(418_700),
      currency: card.currency,
      channel: "direct_debit",
      merchant_name: "Muebles Nogal",
      transaction_status: "approved",
      direction: "unknown",
      reversal_of: "TXS-S05",
      scenario: "reversal_entry",
    }),
    // 7. A declined attempt. Declined is not the same as charged.
    row({
      transaction_id: "TXS-S07",
      product_id: card.product_id,
      process_date: "2026-06-16",
      transaction_date: "2026-06-16 19:03:00",
      transaction_type: "purchase",
      transaction_category: "travel",
      amount: base(1_390_000),
      currency: card.currency,
      channel: "ecommerce",
      merchant_name: "Viajes Horizonte",
      transaction_status: "declined",
      direction: "debit",
      scenario: "declined_attempt",
    }),
    // 8. A purchase billed in another currency than the product itself.
    row({
      transaction_id: "TXS-S08",
      product_id: card.product_id,
      process_date: "2026-06-10",
      transaction_date: "2026-06-10 16:47:00",
      transaction_type: "purchase",
      transaction_category: "tech",
      amount: 12.99,
      currency: "USD",
      channel: "ecommerce",
      merchant_name: "Tienda Pixel",
      transaction_status: "approved",
      direction: "debit",
      scenario: "foreign_currency",
    }),
  ];
}

/** Newest first, by event timestamp, with the id as a stable tiebreaker. */
function byEventDesc(a, b) {
  if (a.transaction_date !== b.transaction_date) {
    return a.transaction_date < b.transaction_date ? 1 : -1;
  }
  return a.transaction_id < b.transaction_id ? 1 : -1;
}

const CACHE = new Map();

export function buildAccount(profileId) {
  if (CACHE.has(profileId)) return CACHE.get(profileId);

  const profile = profileById(profileId);
  const r = rng(profile.seed);
  const products = buildProducts(profile, r);

  const rows = [];
  let seq = 1;
  const total = dayCount(DATASET.window_start, DATASET.window_end);
  for (let i = 0; i <= total; i += 1) {
    const processDate = addDays(DATASET.window_start, i);
    const busy = weekday(processDate) === 0 || weekday(processDate) === 6 ? 0.55 : 1;
    const count = Math.floor(between(r, 0, 3.4 * busy + 0.6));
    for (let k = 0; k < count; k += 1) {
      rows.push(makeRow(profile, products, r, processDate, seq));
      seq += 1;
    }
  }

  rows.push(...makeRecurring(profile, products, r, 1));
  rows.push(...makeScenarios(profile, products, r));
  rows.sort(byEventDesc);

  const account = Object.freeze({
    profile,
    products,
    transactions: rows,
    currencies: [...new Set(products.map((p) => p.currency))],
  });
  CACHE.set(profileId, account);
  return account;
}

/* ==================================================================== *
 * Derived views. Pure functions, so tools/selfcheck.mjs can assert them
 * without a DOM.
 * ==================================================================== */

/**
 * Groups charges that look like the same thing twice: identical merchant,
 * amount and currency, within 72 hours. This is a similarity observation,
 * never a fraud finding, and never a confirmed duplicate.
 */
export function duplicateGroups(transactions) {
  const buckets = new Map();
  for (const tx of transactions) {
    if (!tx.merchant_name) continue;
    if (tx.transaction_status === "declined") continue;
    const key = `${tx.merchant_name}|${tx.amount}|${tx.currency}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(tx);
  }
  const groups = [];
  for (const rows of buckets.values()) {
    if (rows.length < 2) continue;
    const sorted = [...rows].sort((a, b) => {
      if (a.transaction_date === b.transaction_date) return 0;
      return a.transaction_date < b.transaction_date ? -1 : 1;
    });
    let run = [sorted[0]];
    for (let i = 1; i < sorted.length; i += 1) {
      const gap = toDay(sorted[i].transaction_date.slice(0, 10))
        - toDay(run[run.length - 1].transaction_date.slice(0, 10));
      if (gap <= 3 * 86400000) {
        run.push(sorted[i]);
      } else {
        if (run.length > 1) groups.push(run);
        run = [sorted[i]];
      }
    }
    if (run.length > 1) groups.push(run);
  }
  return groups;
}

/** Index from transaction id to the other rows that look like it. */
export function duplicateIndex(transactions) {
  const index = new Map();
  for (const group of duplicateGroups(transactions)) {
    for (const tx of group) {
      index.set(tx.transaction_id, group.filter((other) => other !== tx));
    }
  }
  return index;
}

/**
 * A charge repeated on a similar day of month, at the same amount, at least
 * three times. Reported as an observation the customer can confirm.
 */
export function recurringGroups(transactions) {
  const buckets = new Map();
  for (const tx of transactions) {
    if (!tx.merchant_name || tx.direction !== "debit") continue;
    if (tx.transaction_status !== "approved") continue;
    const key = `${tx.merchant_name}|${tx.amount}|${tx.currency}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(tx);
  }
  const out = [];
  for (const rows of buckets.values()) {
    const months = new Set(rows.map((tx) => tx.process_date.slice(0, 7)));
    if (rows.length < 3 || months.size < 3) continue;
    const sorted = [...rows].sort((a, b) => {
      if (a.transaction_date === b.transaction_date) return 0;
      return a.transaction_date < b.transaction_date ? 1 : -1;
    });
    out.push({
      merchant: sorted[0].merchant_name,
      category: sorted[0].transaction_category,
      amount: sorted[0].amount,
      currency: sorted[0].currency,
      count: sorted.length,
      months: months.size,
      last: sorted[0],
    });
  }
  return out.sort((a, b) => b.amount - a.amount);
}

/** Outgoing totals per category for one currency. Null merchants land in `unknown`. */
export function categoryTotals(transactions, currency) {
  const totals = new Map();
  let unknown = 0;
  let known = 0;
  for (const tx of transactions) {
    if (tx.currency !== currency) continue;
    if (tx.direction !== "debit") continue;
    if (tx.transaction_status === "declined" || tx.transaction_status === "reversed") continue;
    if (!tx.transaction_category) {
      unknown += tx.amount;
      continue;
    }
    known += tx.amount;
    totals.set(tx.transaction_category, (totals.get(tx.transaction_category) || 0) + tx.amount);
  }
  const slices = [...totals.entries()]
    .map(([category, value]) => ({ category, value }))
    .sort((a, b) => b.value - a.value);
  return { slices, unknown, known, total: known + unknown };
}

/** Month by month inflow / outflow / undetermined, oldest first. */
export function monthlySeries(transactions, currency) {
  const months = new Map();
  for (const tx of transactions) {
    if (tx.currency !== currency) continue;
    if (tx.transaction_status === "declined") continue;
    const key = tx.transaction_date.slice(0, 7);
    if (!months.has(key)) {
      months.set(key, { month: key, inflow: 0, outflow: 0, undetermined: 0, count: 0 });
    }
    const bucket = months.get(key);
    bucket.count += 1;
    if (tx.direction === "credit") bucket.inflow += tx.amount;
    else if (tx.direction === "debit") bucket.outflow += tx.amount;
    else bucket.undetermined += tx.amount;
  }
  return [...months.values()].sort((a, b) => (a.month < b.month ? -1 : 1));
}

/**
 * Honest coverage numbers for the data-quality panel. The interface shows
 * these instead of pretending the scenario is complete.
 */
export function coverage(transactions) {
  const total = transactions.length;
  let withMerchant = 0;
  let nextDay = 0;
  let undetermined = 0;
  let pending = 0;
  for (const tx of transactions) {
    if (tx.merchant_name) withMerchant += 1;
    if (tx.transaction_date.slice(0, 10) !== tx.process_date) nextDay += 1;
    if (tx.direction === "unknown") undetermined += 1;
    if (tx.transaction_status === "pending") pending += 1;
  }
  return {
    total,
    withMerchant,
    withoutMerchant: total - withMerchant,
    merchantShare: total ? withMerchant / total : 0,
    nextDay,
    nextDayShare: total ? nextDay / total : 0,
    undetermined,
    undeterminedShare: total ? undetermined / total : 0,
    pending,
  };
}

/** A merchant string that reads like an acquirer descriptor rather than a shop. */
export const looksOpaque = (name) => Boolean(name) && /[*#]|\d{4}/.test(name);

/** Rows a customer usually asks about. Observations, never conclusions. */
export function attentionItems(transactions) {
  const candidates = [];

  // One entry per duplicate-looking group, not one per row in it.
  for (const group of duplicateGroups(transactions)) {
    const newest = group.reduce((a, b) => (a.transaction_date > b.transaction_date ? a : b));
    candidates.push({ kind: "duplicate", tx: newest });
  }

  for (const tx of transactions) {
    if (tx.reversal_of) candidates.push({ kind: "reversal", tx });
    else if (tx.transaction_status === "pending") candidates.push({ kind: "pending", tx });
    else if (tx.transaction_status === "declined") candidates.push({ kind: "declined", tx });
    else if (looksOpaque(tx.merchant_name)) candidates.push({ kind: "opaque", tx });
  }

  // Newest first inside each kind, then taken round-robin across kinds. One
  // noisy category must never crowd the others out of the list.
  candidates.sort((a, b) => {
    // A comparator must return 0 for equal keys, otherwise the sort is
    // inconsistent and the stable ordering we rely on falls apart.
    if (a.tx.transaction_date === b.tx.transaction_date) return 0;
    return a.tx.transaction_date < b.tx.transaction_date ? 1 : -1;
  });

  const ORDER = ["duplicate", "reversal", "declined", "pending", "opaque"];
  const queues = new Map(ORDER.map((kind) => [kind, []]));
  const seen = new Set();
  for (const item of candidates) {
    if (seen.has(item.tx.transaction_id)) continue;
    seen.add(item.tx.transaction_id);
    queues.get(item.kind)?.push(item);
  }

  const out = [];
  for (let round = 0; round < 2 && out.length < 6; round += 1) {
    for (const kind of ORDER) {
      if (out.length >= 6) break;
      const queue = queues.get(kind);
      if (queue && queue.length > round) out.push(queue[round]);
    }
  }
  return out;
}

/** The guided tour targets: one representative row per hard case. */
export function scenarioTour(transactions) {
  const find = (scenario) => transactions.find((tx) => tx.scenario === scenario);
  return [
    { key: "opaque_descriptor", tx: find("opaque_descriptor") },
    { key: "duplicate_pair", tx: transactions.find((tx) => tx.scenario === "duplicate_pair" && tx.transaction_status === "pending") },
    { key: "pending_authorisation", tx: find("pending_authorisation") },
    { key: "reversal_entry", tx: find("reversal_entry") },
    { key: "declined_attempt", tx: find("declined_attempt") },
    { key: "foreign_currency", tx: find("foreign_currency") },
  ].filter((item) => Boolean(item.tx));
}
