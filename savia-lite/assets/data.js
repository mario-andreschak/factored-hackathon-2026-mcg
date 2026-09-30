/**
 * Savia Lite - deterministic demo dataset.
 *
 * Every record in this file is INVENTED by this generator. Nothing here is read
 * from the organizer snapshot, from S3, or from any customer record. The field
 * names mirror the organizer schema (transaction_date / process_date / channel /
 * merchant_name / transaction_status ...) so the screens exercise the same shapes
 * the real API returns, but the values are synthetic by construction.
 *
 * The generator is seeded, so the same build always produces the same rows.
 */

export const DATASET = Object.freeze({
  id: "savia-lite-demo",
  synthetic: true,
  origin: "generated_in_browser",
  build_id: "SAVIA-LITE-0001",
  // Mirrors the historical scenario window used by the banking tooling.
  window_start: "2026-03-01",
  window_end: "2026-06-17",
  latest_process_date: "2026-06-17",
  balances_note: "snapshot_balance_not_recomputed",
  amounts_note: "positive_magnitudes",
});

/* ------------------------------------------------------------------ *
 * Seeded pseudo-random source (mulberry32). Deterministic by design.
 * ------------------------------------------------------------------ */
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

/* ------------------------------------------------------------------ *
 * Reference vocabularies
 * ------------------------------------------------------------------ */
export const TX_TYPES = ["Compra", "Retiro", "Deposito", "Transferencia", "Pago", "Ajuste"];
export const CHANNELS = ["POS", "Ecommerce", "ATM", "App", "Sucursal", "DebitoAutomatico"];
export const STATUSES = ["Aprobada", "Pendiente", "Reversada", "Rechazada"];

/**
 * Only these three types carry a defensible direction in the source schema.
 * Transfers, payments and adjustments keep an unknown leg instead of inventing
 * a debit or a credit.
 */
export function directionFor(type) {
  if (type === "Compra" || type === "Retiro") return "debit";
  if (type === "Deposito") return "credit";
  return "unknown";
}

const CATEGORIES = [
  "Supermercado", "Transporte", "Restaurantes", "Servicios", "Salud",
  "Entretenimiento", "Tecnologia", "Educacion", "Hogar", "Viajes",
];

/** Merchant descriptors deliberately include opaque acquirer strings. */
const MERCHANTS = [
  "Supermercado La Huerta", "Cafe Bracero", "Farmacia Vida", "Tienda Movil 24",
  "Transporte Urbano SA", "Libreria Norte", "Panaderia Dona Rosa",
  "Gimnasio Pulso", "Ferreteria El Clavo", "Optica Claridad",
  "DLC*PAGOS DIGITALES 8829", "SQ *ESTUDIO 41", "PAYU*SUSCRIPCION MX",
  "AMZ MKTPLACE LATAM", "MP*VENTASONLINE 7731",
];

const CITY_BY_COUNTRY = {
  Colombia: ["Bogota", "Medellin", "Cali", "Bucaramanga"],
  Argentina: ["Cordoba", "Buenos Aires", "Rosario", "Mendoza"],
  Brasil: ["Sao Paulo", "Campinas", "Curitiba", "Santos"],
};

/* ------------------------------------------------------------------ *
 * Demo profiles. Aliases, not identity claims.
 * ------------------------------------------------------------------ */
export const PROFILES = [
  {
    id: "SAVIA-DEMO-1",
    alias: "Camila Restrepo",
    initials: "CR",
    country: "Colombia",
    city: "Bogota",
    segment: "Premium",
    primary_currency: "COP",
    language: "es",
    seed: 20260601,
    scale: 1000,
  },
  {
    id: "SAVIA-DEMO-2",
    alias: "Mateo Duarte",
    initials: "MD",
    country: "Argentina",
    city: "Cordoba",
    segment: "Classic",
    primary_currency: "ARS",
    language: "es",
    seed: 20260602,
    scale: 400,
  },
  {
    id: "SAVIA-DEMO-3",
    alias: "Beatriz Nogueira",
    initials: "BN",
    country: "Brasil",
    city: "Sao Paulo",
    segment: "Preferencial",
    primary_currency: "BRL",
    language: "pt",
    seed: 20260603,
    scale: 4,
  },
];

/* ------------------------------------------------------------------ *
 * Date helpers - all dates are handled as plain calendar/clock strings
 * so no host timezone can shift a demo record.
 * ------------------------------------------------------------------ */
const DAY_MS = 86400000;
const toDayNumber = (iso) => Math.round(Date.parse(iso + "T00:00:00Z") / DAY_MS);
const fromDayNumber = (n) => new Date(n * DAY_MS).toISOString().slice(0, 10);
const pad = (n) => String(n).padStart(2, "0");

function stamp(dayNumber, hour, minute) {
  return `${fromDayNumber(dayNumber)} ${pad(hour)}:${pad(minute)}:00`;
}

/* ------------------------------------------------------------------ *
 * Product construction
 * ------------------------------------------------------------------ */
function buildProducts(profile) {
  const r = rng(profile.seed * 7 + 11);
  const s = profile.scale;
  const cur = profile.primary_currency;
  return [
    {
      product_id: `${profile.id}-P1`,
      label_key: "product.savings",
      product_type: "CuentaAhorros",
      masked_number: `**** ${1000 + Math.floor(r() * 8999)}`,
      currency: cur,
      balance_kind: "deposit",
      current_balance: money(r, 900 * s, 4200 * s),
      credit_limit: null,
      interest_rate: Math.round(between(r, 0.4, 3.1) * 100) / 100,
      opening_date: "2021-04-19",
      product_status: "Active",
      opening_channel: "Sucursal",
    },
    {
      product_id: `${profile.id}-P2`,
      label_key: "product.card",
      product_type: "TarjetaCredito",
      masked_number: `**** ${1000 + Math.floor(r() * 8999)}`,
      currency: cur,
      balance_kind: "credit",
      current_balance: money(r, 120 * s, 900 * s),
      credit_limit: money(r, 1800 * s, 3600 * s),
      interest_rate: Math.round(between(r, 18, 42) * 100) / 100,
      opening_date: "2022-11-02",
      product_status: "Active",
      opening_channel: "App",
    },
    {
      product_id: `${profile.id}-P3`,
      label_key: "product.investment",
      product_type: "Inversion",
      masked_number: `**** ${1000 + Math.floor(r() * 8999)}`,
      currency: "USD",
      balance_kind: "investment",
      current_balance: money(r, 1200, 9800),
      credit_limit: null,
      interest_rate: Math.round(between(r, 3.5, 6.4) * 100) / 100,
      opening_date: "2024-02-15",
      product_status: "Active",
      opening_channel: "App",
    },
  ];
}

/* ------------------------------------------------------------------ *
 * Transaction construction
 * ------------------------------------------------------------------ */
let sequence = 0;
function nextReference(profile) {
  sequence += 1;
  return `TXS-${profile.seed}-${String(sequence).padStart(5, "0")}`;
}

function baseTransaction(profile, products, r, dayNumber) {
  const product = r() < 0.58 ? products[1] : products[0];
  const type = pick(r, ["Compra", "Compra", "Compra", "Retiro", "Deposito", "Transferencia", "Pago", "Ajuste"]);
  const hour = Math.floor(between(r, 6, 23));
  const minute = Math.floor(between(r, 0, 59));

  // The published snapshot has a large set of events whose calendar day falls
  // one day after the processing day. Reproduce that shape, never hide it.
  const lateNight = hour >= 21 && r() < 0.65;
  const eventDay = lateNight ? dayNumber + 1 : dayNumber;

  // Most source rows carry no merchant at all.
  const hasMerchant = (type === "Compra" || type === "Pago") && r() < 0.42;

  let status = "Aprobada";
  const roll = r();
  if (roll > 0.955) status = "Pendiente";
  else if (roll > 0.935) status = "Rechazada";

  const magnitude =
    type === "Deposito" ? money(r, 40 * profile.scale, 320 * profile.scale)
    : type === "Retiro" ? money(r, 10 * profile.scale, 90 * profile.scale)
    : money(r, 1.5 * profile.scale, 70 * profile.scale);

  return {
    transaction_id: nextReference(profile),
    product_id: product.product_id,
    transaction_date: stamp(eventDay, hour, minute),
    process_date: fromDayNumber(dayNumber),
    transaction_type: type,
    transaction_category: type === "Compra" ? pick(r, CATEGORIES) : null,
    amount: magnitude,
    currency: product.currency,
    channel:
      type === "Retiro" ? "ATM"
      : type === "Deposito" ? pick(r, ["Sucursal", "App"])
      : pick(r, CHANNELS),
    merchant_name: hasMerchant ? pick(r, MERCHANTS) : null,
    transaction_country: profile.country,
    transaction_city: r() < 0.8 ? pick(r, CITY_BY_COUNTRY[profile.country]) : null,
    transaction_status: status,
    direction: directionFor(type),
    reversal_of: null,
    scenario: null,
  };
}

/**
 * Hand-placed scenarios. Each one exists so a reviewer can exercise a rule that
 * the copy in this portal claims to respect.
 */
function scenarioTransactions(profile, products, endDay) {
  const card = products[1];
  const savings = products[0];
  const s = profile.scale;
  const out = [];

  // 1. Opaque acquirer descriptor - the classic unrecognised charge.
  out.push({
    transaction_id: `TXS-${profile.seed}-S001`,
    product_id: card.product_id,
    transaction_date: stamp(endDay - 2, 22, 41),
    process_date: fromDayNumber(endDay - 3),
    transaction_type: "Compra",
    transaction_category: "Tecnologia",
    amount: money(rng(profile.seed + 1), 18 * s, 26 * s),
    currency: card.currency,
    channel: "Ecommerce",
    merchant_name: "DLC*PAGOS DIGITALES 8829",
    transaction_country: profile.country,
    transaction_city: null,
    transaction_status: "Aprobada",
    direction: "debit",
    reversal_of: null,
    scenario: "opaque_descriptor",
  });

  // 2. Duplicate-looking pair: same merchant, same amount, hours apart.
  //    One settled, one still pending. NOT confirmed fraud, NOT confirmed duplicate.
  const dupAmount = money(rng(profile.seed + 2), 9 * s, 14 * s);
  out.push({
    transaction_id: `TXS-${profile.seed}-S002`,
    product_id: card.product_id,
    transaction_date: stamp(endDay - 5, 13, 8),
    process_date: fromDayNumber(endDay - 5),
    transaction_type: "Compra",
    transaction_category: "Restaurantes",
    amount: dupAmount,
    currency: card.currency,
    channel: "POS",
    merchant_name: "Cafe Bracero",
    transaction_country: profile.country,
    transaction_city: profile.city,
    transaction_status: "Aprobada",
    direction: "debit",
    reversal_of: null,
    scenario: "duplicate_candidate",
  });
  out.push({
    transaction_id: `TXS-${profile.seed}-S003`,
    product_id: card.product_id,
    transaction_date: stamp(endDay - 5, 17, 52),
    process_date: fromDayNumber(endDay - 5),
    transaction_type: "Compra",
    transaction_category: "Restaurantes",
    amount: dupAmount,
    currency: card.currency,
    channel: "POS",
    merchant_name: "Cafe Bracero",
    transaction_country: profile.country,
    transaction_city: profile.city,
    transaction_status: "Pendiente",
    direction: "debit",
    reversal_of: null,
    scenario: "duplicate_candidate",
  });

  // 3. A charge with no merchant text at all.
  out.push({
    transaction_id: `TXS-${profile.seed}-S004`,
    product_id: card.product_id,
    transaction_date: stamp(endDay - 8, 9, 27),
    process_date: fromDayNumber(endDay - 8),
    transaction_type: "Pago",
    transaction_category: null,
    amount: money(rng(profile.seed + 4), 30 * s, 55 * s),
    currency: card.currency,
    channel: "DebitoAutomatico",
    merchant_name: null,
    transaction_country: profile.country,
    transaction_city: null,
    transaction_status: "Aprobada",
    direction: "unknown",
    reversal_of: null,
    scenario: "missing_merchant",
  });

  // 4. A charge plus its reversal. A reversal is not proof a refund landed.
  const revAmount = money(rng(profile.seed + 5), 22 * s, 38 * s);
  out.push({
    transaction_id: `TXS-${profile.seed}-S005`,
    product_id: card.product_id,
    transaction_date: stamp(endDay - 12, 20, 15),
    process_date: fromDayNumber(endDay - 12),
    transaction_type: "Compra",
    transaction_category: "Viajes",
    amount: revAmount,
    currency: card.currency,
    channel: "Ecommerce",
    merchant_name: "AMZ MKTPLACE LATAM",
    transaction_country: profile.country,
    transaction_city: null,
    transaction_status: "Reversada",
    direction: "debit",
    reversal_of: null,
    scenario: "reversed_charge",
  });
  out.push({
    transaction_id: `TXS-${profile.seed}-S006`,
    product_id: card.product_id,
    transaction_date: stamp(endDay - 11, 4, 3),
    process_date: fromDayNumber(endDay - 12),
    transaction_type: "Ajuste",
    transaction_category: null,
    amount: revAmount,
    currency: card.currency,
    channel: "DebitoAutomatico",
    merchant_name: "AMZ MKTPLACE LATAM",
    transaction_country: profile.country,
    transaction_city: null,
    transaction_status: "Aprobada",
    direction: "unknown",
    reversal_of: `TXS-${profile.seed}-S005`,
    scenario: "reversal_entry",
  });

  // 5. Pending authorisation on the last processing day - not settled.
  out.push({
    transaction_id: `TXS-${profile.seed}-S007`,
    product_id: savings.product_id,
    transaction_date: stamp(endDay + 1, 0, 42),
    process_date: fromDayNumber(endDay),
    transaction_type: "Retiro",
    transaction_category: null,
    amount: money(rng(profile.seed + 7), 12 * s, 40 * s),
    currency: savings.currency,
    channel: "ATM",
    merchant_name: null,
    transaction_country: profile.country,
    transaction_city: profile.city,
    transaction_status: "Pendiente",
    direction: "debit",
    reversal_of: null,
    scenario: "pending_authorisation",
  });

  return out;
}

function buildTransactions(profile, products) {
  const r = rng(profile.seed);
  const startDay = toDayNumber(DATASET.window_start);
  const endDay = toDayNumber(DATASET.window_end);
  const rows = [];

  for (let day = startDay; day <= endDay; day += 1) {
    const weekday = (day + 4) % 7; // 1970-01-01 was a Thursday
    const busy = weekday === 5 || weekday === 6 ? 1.6 : 1;
    const count = Math.floor(between(r, 0, 3.2 * busy));
    for (let i = 0; i < count; i += 1) rows.push(baseTransaction(profile, products, r, day));
  }

  // Salary-like inflow twice a month, so the savings view is not only outflow.
  for (let day = startDay; day <= endDay; day += 1) {
    const dom = Number(fromDayNumber(day).slice(8, 10));
    if (dom === 15 || dom === 30) {
      rows.push({
        transaction_id: nextReference(profile),
        product_id: products[0].product_id,
        transaction_date: stamp(day, 8, 5),
        process_date: fromDayNumber(day),
        transaction_type: "Deposito",
        transaction_category: null,
        amount: money(r, 260 * profile.scale, 340 * profile.scale),
        currency: products[0].currency,
        channel: "Sucursal",
        merchant_name: null,
        transaction_country: profile.country,
        transaction_city: profile.city,
        transaction_status: "Aprobada",
        direction: "credit",
        reversal_of: null,
        scenario: "recurring_inflow",
      });
    }
  }

  rows.push(...scenarioTransactions(profile, products, endDay));

  rows.sort((a, b) =>
    a.transaction_date === b.transaction_date
      ? a.transaction_id.localeCompare(b.transaction_id)
      : a.transaction_date < b.transaction_date ? 1 : -1
  );
  return rows;
}

/* ------------------------------------------------------------------ *
 * Duplicate candidates - a heuristic, explicitly not a determination.
 * ------------------------------------------------------------------ */
const NEAR_HOURS = 72;
export function duplicateGroups(transactions) {
  const groups = new Map();
  for (const t of transactions) {
    if (t.reversal_of) continue;
    const key = [t.merchant_name || "?", t.amount.toFixed(2), t.currency, t.product_id].join("|");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(t);
  }
  const flagged = new Set();
  for (const [, list] of groups) {
    if (list.length < 2) continue;
    const sorted = [...list].sort((a, b) => (a.transaction_date < b.transaction_date ? -1 : 1));
    for (let i = 1; i < sorted.length; i += 1) {
      const gapHours =
        (Date.parse(sorted[i].transaction_date.replace(" ", "T") + "Z") -
          Date.parse(sorted[i - 1].transaction_date.replace(" ", "T") + "Z")) / 3600000;
      if (gapHours <= NEAR_HOURS) {
        flagged.add(sorted[i - 1].transaction_id);
        flagged.add(sorted[i].transaction_id);
      }
    }
  }
  return flagged;
}

/* ------------------------------------------------------------------ *
 * Public entry point
 * ------------------------------------------------------------------ */
export function buildAccount(profileId) {
  const profile = PROFILES.find((p) => p.id === profileId) || PROFILES[0];
  sequence = 0;
  const products = buildProducts(profile);
  const transactions = buildTransactions(profile, products);
  const productById = new Map(products.map((p) => [p.product_id, p]));
  return {
    profile,
    products,
    productById,
    transactions,
    duplicates: duplicateGroups(transactions),
    metadata: {
      ...DATASET,
      transactions_total: transactions.length,
      generated_for: profile.id,
    },
  };
}
