/**
 * Savia Lite self check - `node tools/selfcheck.mjs`
 *
 * Runs on plain Node with no test framework and nothing installed. It asserts
 * the promises this portal makes, so a reviewer can watch them being enforced
 * instead of taking the copy at its word.
 *
 * Exits non-zero on the first failing category, so it is usable in CI.
 */

import { readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  PROFILES, DATASET, buildAccount, duplicateGroups, duplicateIndex,
  recurringGroups, categoryTotals, monthlySeries, coverage,
  attentionItems, scenarioTour, directionFor, looksOpaque, CATEGORIES,
} from "../assets/data.js";
import { translationKeys, createTranslator, LANGUAGES } from "../assets/i18n.js";
import {
  formatMoney, formatDay, formatPercent, signedMoney,
  dayKey, monthKey, toCsv,
} from "../assets/format.js";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

let failures = 0;
let checks = 0;
function check(label, condition, detail = "") {
  checks += 1;
  if (condition) {
    console.log(`  ok   ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? " -> " + detail : ""}`);
  }
}
const section = (name) => console.log(`\n${name}`);

const accounts = PROFILES.map((profile) => buildAccount(profile.id));

/* ================================================================== */
section("dataset shape");

check("three demo profiles", PROFILES.length === 3);
check("the dataset declares itself synthetic", DATASET.synthetic === true && DATASET.origin === "generated_in_browser");

for (const account of accounts) {
  const id = account.profile.id;
  const rows = account.transactions;

  check(`${id}: has a year of rows`, rows.length > 300 && rows.length < 900, String(rows.length));
  check(`${id}: transaction ids are unique`,
    new Set(rows.map((tx) => tx.transaction_id)).size === rows.length);
  check(`${id}: every row belongs to one of this profile's products`,
    rows.every((tx) => account.products.some((p) => p.product_id === tx.product_id)));
  check(`${id}: no processing date escapes the declared window`,
    rows.every((tx) => tx.process_date >= DATASET.window_start && tx.process_date <= DATASET.window_end));
  check(`${id}: rows arrive newest first`,
    rows.every((tx, i) => i === 0 || rows[i - 1].transaction_date >= tx.transaction_date));
  check(`${id}: amounts are positive magnitudes, never signed`,
    rows.every((tx) => tx.amount > 0));
}

check("the generator is deterministic",
  JSON.stringify(buildAccount(PROFILES[0].id).transactions)
  === JSON.stringify(buildAccount(PROFILES[0].id).transactions));

/* ================================================================== */
section("the real snapshot's defects are reproduced, not hidden");

for (const account of accounts) {
  const id = account.profile.id;
  const cov = coverage(account.transactions);
  const missing = 1 - cov.merchantShare;

  // The published organizer build is 76.7% missing. Staying in this band keeps
  // the demo honest about how little merchant text actually arrives.
  check(`${id}: most rows carry no merchant (60-85%)`,
    missing > 0.6 && missing < 0.85, formatPercent(missing, "en"));
  check(`${id}: a meaningful share of events land a day after processing (15-35%)`,
    cov.nextDayShare > 0.15 && cov.nextDayShare < 0.35, formatPercent(cov.nextDayShare, "en"));
  check(`${id}: transfers, payments and adjustments keep an unknown direction`,
    cov.undeterminedShare > 0.1, formatPercent(cov.undeterminedShare, "en"));
  check(`${id}: a row without a merchant also has no category`,
    account.transactions.every((tx) => tx.merchant_name || tx.transaction_category === null));
}

check("only purchases, withdrawals and deposits carry a sign",
  directionFor("purchase") === "debit"
  && directionFor("withdrawal") === "debit"
  && directionFor("deposit") === "credit"
  && directionFor("transfer") === "unknown"
  && directionFor("payment") === "unknown"
  && directionFor("adjustment") === "unknown");

/* ================================================================== */
section("the scenario stays plausible");

for (const account of accounts) {
  const id = account.profile.id;
  const rows = account.transactions;

  check(`${id}: no purchase is booked at an ATM`,
    !rows.some((tx) => tx.transaction_type === "purchase" && tx.channel === "atm"));
  check(`${id}: no transfer runs through a card terminal or an online shop`,
    !rows.some((tx) => tx.transaction_type === "transfer" && ["pos", "ecommerce"].includes(tx.channel)));
  check(`${id}: every withdrawal is at an ATM`,
    rows.filter((tx) => tx.transaction_type === "withdrawal").every((tx) => tx.channel === "atm"));
  check(`${id}: a merchant only appears where the schema can carry one`,
    rows.filter((tx) => tx.merchant_name)
      .every((tx) => ["purchase", "payment", "adjustment"].includes(tx.transaction_type)));
  check(`${id}: every category is a known category`,
    rows.every((tx) => tx.transaction_category === null || CATEGORIES.includes(tx.transaction_category)));
}

/* ================================================================== */
section("the hard cases are always reachable");

const WANTED = [
  "opaque_descriptor", "duplicate_pair", "pending_authorisation",
  "reversal_entry", "declined_attempt", "foreign_currency",
];

for (const account of accounts) {
  const id = account.profile.id;
  const rows = account.transactions;
  const scenarios = new Set(rows.map((tx) => tx.scenario).filter(Boolean));

  for (const wanted of WANTED) {
    check(`${id}: scenario present - ${wanted}`, scenarios.has(wanted));
  }
  check(`${id}: the guided tour resolves every entry`, scenarioTour(rows).length === 6);

  const groups = duplicateGroups(rows);
  check(`${id}: a duplicate-looking pair exists`, groups.length >= 1);
  check(`${id}: every duplicate group shares merchant, amount and currency`,
    groups.every((group) => group.every((tx) =>
      tx.merchant_name === group[0].merchant_name
      && tx.amount === group[0].amount
      && tx.currency === group[0].currency)));
  check(`${id}: a duplicate group never spans more than 72 hours`,
    groups.every((group) => {
      const days = group.map((tx) => Date.parse(`${dayKey(tx.transaction_date)}T00:00:00Z`));
      return Math.max(...days) - Math.min(...days) <= 3 * 86400000;
    }));

  const index = duplicateIndex(rows);
  check(`${id}: a row is never listed as its own duplicate`,
    [...index.entries()].every(([key, others]) => others.every((tx) => tx.transaction_id !== key)));

  const reversalEntry = rows.find((tx) => tx.scenario === "reversal_entry");
  check(`${id}: the reversal entry points at a row that exists`,
    Boolean(reversalEntry) && rows.some((tx) => tx.transaction_id === reversalEntry.reversal_of));

  const foreign = rows.find((tx) => tx.scenario === "foreign_currency");
  const product = account.products.find((p) => p.product_id === foreign.product_id);
  check(`${id}: the foreign charge really is in another currency than its product`,
    foreign.currency !== product.currency);

  const declined = rows.find((tx) => tx.scenario === "declined_attempt");
  check(`${id}: the declined attempt is declined`, declined.transaction_status === "declined");
}

/* ================================================================== */
section("derived views");

for (const account of accounts) {
  const id = account.profile.id;
  const rows = account.transactions;
  const currency = account.profile.currency;

  const totals = categoryTotals(rows, currency);
  const sum = totals.slices.reduce((acc, slice) => acc + slice.value, 0);
  check(`${id}: category slices add up to the known total`,
    Math.abs(sum - totals.known) < 0.01);
  check(`${id}: the unclassified remainder is kept, not dropped`, totals.unknown > 0);
  check(`${id}: slices are ordered by size`,
    totals.slices.every((slice, i) => i === 0 || totals.slices[i - 1].value >= slice.value));

  const series = monthlySeries(rows, currency);
  check(`${id}: a full year of months`, series.length === 12, String(series.length));
  check(`${id}: months are ordered oldest first`,
    series.every((month, i) => i === 0 || series[i - 1].month < month.month));
  check(`${id}: a declined attempt never counts as money moved`,
    series.every((month) => month.inflow >= 0 && month.outflow >= 0));

  const recurring = recurringGroups(rows);
  check(`${id}: the repeating charges are found`, recurring.length >= 3, String(recurring.length));
  check(`${id}: a repeating charge spans at least three months`,
    recurring.every((group) => group.months >= 3));

  const attention = attentionItems(rows);
  check(`${id}: the attention list stays short`, attention.length > 0 && attention.length <= 6);
  check(`${id}: the attention list never repeats a row`,
    new Set(attention.map((item) => item.tx.transaction_id)).size === attention.length);
  const kinds = new Set(attention.map((item) => item.kind));
  for (const kind of ["duplicate", "reversal", "declined", "pending", "opaque"]) {
    check(`${id}: attention covers - ${kind}`, kinds.has(kind));
  }
}

check("an acquirer descriptor is recognised", looksOpaque("DLC*PAGOS DIGITALES 8829"));
check("an ordinary shop name is not flagged as a descriptor", !looksOpaque("Cafe Bracero"));
check("a missing merchant is not flagged as a descriptor", !looksOpaque(null));

/* ================================================================== */
section("translations");

const baseKeys = translationKeys("es");
check("the copy carries a real key set", baseKeys.length > 200, String(baseKeys.length));

for (const lang of LANGUAGES) {
  const keys = translationKeys(lang.code);
  const missing = baseKeys.filter((key) => !keys.includes(key));
  const extra = keys.filter((key) => !baseKeys.includes(key));
  check(`${lang.code}: no missing key`, missing.length === 0, missing.slice(0, 4).join(", "));
  check(`${lang.code}: no stray key`, extra.length === 0, extra.slice(0, 4).join(", "));

  const t = createTranslator(lang.code);
  check(`${lang.code}: no empty string`, keys.every((key) => t(key).trim().length > 0));
  check(`${lang.code}: no unresolved placeholder in a no-argument string`,
    keys.filter((key) => !/\{/.test(t(key))).length > keys.length * 0.8);
}

check("an unknown key is loud rather than silent", createTranslator("es")("no.such.key") === "no.such.key");
check("placeholders are substituted",
  createTranslator("pt")("ins.subsCount", { count: 3, months: 4 }) === "3 cobranças em 4 meses");

/* ================================================================== */
section("the wording rules, in every language");

const PROMISES = {
  es: {
    "tx.pendingNote": /no est[áa] liquidad/i,
    "tx.reversalNote": /no prueba/i,
    "tx.reversalOriginNote": /no equivale/i,
    "tx.declinedNote": /no es un cargo/i,
    "tx.dupNote": /no lo damos por confirmado/i,
    "tx.unknownMerchant": /no informado/i,
    "banner.synthetic": /no ejecuta ninguna acci[óo]n bancaria/i,
    "help.isNot2": /no prueba la autenticaci[óo]n/i,
    "sum.notDone1": /no se abri[óo] una disputa/i,
    "sum.notDone2": /no se transfiri[óo]/i,
    "sum.notDone3": /no se emiti[óo] ning[úu]n reembolso/i,
    "sum.notDone4": /no se prometi[óo] ning[úu]n plazo/i,
  },
  pt: {
    "tx.pendingNote": /n[ãa]o est[áa] liquidada/i,
    "tx.reversalNote": /n[ãa]o prova/i,
    "tx.reversalOriginNote": /n[ãa]o equivale/i,
    "tx.declinedNote": /n[ãa]o é uma cobran[çc]a/i,
    "tx.dupNote": /n[ãa]o tratamos isso como confirmado/i,
    "tx.unknownMerchant": /n[ãa]o informado/i,
    "banner.synthetic": /n[ãa]o executa nenhuma a[çc][ãa]o banc[áa]ria/i,
    "help.isNot2": /n[ãa]o testa autentica[çc][ãa]o/i,
    "sum.notDone1": /nenhuma disputa/i,
    "sum.notDone2": /n[ãa]o foi transferida/i,
    "sum.notDone3": /nenhum reembolso/i,
    "sum.notDone4": /nenhum prazo/i,
  },
  en: {
    "tx.pendingNote": /is not settled/i,
    "tx.reversalNote": /not proof/i,
    "tx.reversalOriginNote": /not the same as a refund/i,
    "tx.declinedNote": /is not a charge/i,
    "tx.dupNote": /do not treat it as confirmed/i,
    "tx.unknownMerchant": /not reported/i,
    "banner.synthetic": /takes no banking action/i,
    "help.isNot2": /does not test customer authentication/i,
    "sum.notDone1": /no dispute or chargeback/i,
    "sum.notDone2": /not transferred to an agent/i,
    "sum.notDone3": /no refund was issued/i,
    "sum.notDone4": /no response deadline/i,
  },
};

for (const [code, rules] of Object.entries(PROMISES)) {
  const t = createTranslator(code);
  for (const [key, pattern] of Object.entries(rules)) {
    check(`${code}: ${key} keeps its promise`, pattern.test(t(key)), t(key).slice(0, 60));
  }
  // No string may *assert* that a dispute was filed or a refund arrived.
  //
  // Banning the vocabulary outright would be the wrong test: the strings that
  // protect the reader are exactly the ones that mention a refund in order to
  // deny it ("that is not the same as a refund confirmed in your balance").
  // So each occurrence of a claim phrase has to be negated in its own clause.
  const claim = {
    es: /(disputa|reclamaci[oó]n)\s+(enviada|presentada|abierta)|reembolso\s+(emitido|confirmado|recibido|acreditado)/gi,
    pt: /(disputa|contesta[cç][aã]o)\s+(enviada|aberta|registrada)|reembolso\s+(emitido|confirmado|recebido|creditado)/gi,
    en: /(dispute|chargeback)\s+(filed|submitted|opened)|refund\s+(issued|confirmed|received|credited)/gi,
  }[code];
  const negator =
    /\b(no|not|n[aã]o|never|nunca|jam[aá]s|sin|sem|without|nenhum|nenhuma|ning[uú]n|ninguna|ningún)\b/i;

  const offenders = translationKeys(code).filter((key) => {
    const text = t(key);
    claim.lastIndex = 0;
    for (let hit = claim.exec(text); hit; hit = claim.exec(text)) {
      // The clause the phrase sits in: back to the previous sentence or comma
      // boundary. A denial has to be inside that same clause to count.
      const before = text.slice(0, hit.index);
      const clause = before.slice(Math.max(0, before.search(/[^.;:,]*$/)));
      if (!negator.test(clause)) return true;
    }
    return false;
  });
  check(`${code}: no string asserts a dispute or an arrived refund`, offenders.length === 0, offenders.join(", "));

  // The negation-aware check above must still be able to catch a real claim,
  // otherwise it would pass by being toothless.
  claim.lastIndex = 0;
  const positive = { es: "Reembolso emitido", pt: "Reembolso emitido", en: "Refund issued" }[code];
  check(`${code}: that check would still catch a real claim`, claim.test(positive));
}

/* ================================================================== */
section("formatting");

check("money keeps the currency it was recorded in",
  formatMoney(1234.5, "COP", "es").includes("1.234,5")
  && formatMoney(1234.5, "BRL", "pt").includes("1.234,5"));
check("a credit is signed as incoming", signedMoney(10, "USD", "credit", "en").startsWith("+"));
check("a debit is signed as outgoing", signedMoney(10, "USD", "debit", "en").startsWith("−"));
check("an unknown direction gets no invented sign",
  !/^[+−-]/.test(signedMoney(10, "USD", "unknown", "en")));
check("a late-night event keeps its own calendar day",
  dayKey("2026-06-18 00:42:00") === "2026-06-18");
check("month grouping uses the event month", monthKey("2026-06-18 00:42:00") === "2026-06");
check("formatting a day never shifts it across a timezone",
  formatDay("2026-01-01 00:30:00", "es").startsWith("1 ene"));
check("csv quotes a separator inside a value",
  toCsv([["a,b", "c"]]) === '"a,b",c');
check("csv escapes an embedded quote", toCsv([['say "hi"']]) === '"say ""hi"""');

/* ================================================================== */
section("nothing leaves this machine");

const SOURCES = [
  "index.html", "assets/app.js", "assets/data.js", "assets/i18n.js",
  "assets/format.js", "assets/charts.js", "assets/ui.js", "assets/boot.js",
  "assets/styles.css",
];

for (const name of SOURCES) {
  check(`present: ${name}`, existsSync(join(root, name)));
}

const sourceText = SOURCES.map((name) => readFileSync(join(root, name), "utf8")).join("\n");

check("no source file calls the network",
  !/\bfetch\s*\(|XMLHttpRequest|new WebSocket|EventSource|sendBeacon|importScripts/.test(sourceText));
check("no source file embeds a remote URL",
  !/https?:\/\/(?!www\.w3\.org)/.test(sourceText));
// A stacking margin between adjacent cards must not leak onto grid siblings,
// which would drop every second column by that margin.
const cssText = readFileSync(join(root, "assets/styles.css"), "utf8");
check("the card stacking margin is neutralised inside grid containers",
  /\.card \+ \.card/.test(cssText)
  && /\.grid > \.card \+ \.card[\s,]/.test(cssText)
  && /\.help-grid > \.card \+ \.card\s*\{\s*margin-top:\s*0/.test(cssText));

check("no stylesheet pulls a remote font or image",
  !/@import|url\(\s*["']?https?:/.test(readFileSync(join(root, "assets/styles.css"), "utf8")));
check("no fraud score or label is anywhere in the product",
  !/fraud_score|is_fraud/i.test(sourceText));

/* ================================================================== */
section("the local summary cannot overclaim");

const appText = readFileSync(join(root, "assets/app.js"), "utf8");
for (const flag of [
  "bank_action_taken: false",
  "dispute_submitted: false",
  "refund_issued: false",
  "agent_transfer: false",
  "response_deadline_promised: false",
  "local_only: true",
  "synthetic: true",
]) {
  check(`the summary hard-codes ${flag}`, appText.includes(flag));
}
check("the summary keeps customer answers out of the transaction facts",
  /customer_answers:/.test(appText) && /transaction: \{/.test(appText));
check("an urgent card report is treated as a security concern",
  /tr\.urgent \? "security_concern"/.test(appText));
check("an urgent card report asks no further questions",
  /if \(!tr\.urgent\) \{\s*\n\s*for \(const question of QUESTIONS\)/.test(appText));

/* ================================================================== */
section("page shell");

const html = readFileSync(join(root, "index.html"), "utf8");
check("the app is loaded as a module", /<script type="module" src="assets\/app\.js">/.test(html));
check("the boot guard loads first", html.indexOf("boot.js") < html.indexOf("app.js"));
check("the demo asks search engines to stay away", /noindex/.test(html));
check("there is a no-JavaScript explanation", /<noscript/.test(html));

/* ================================================================== */
section("browser modules parse");

// app.js, boot.js and ui.js need a DOM, so they cannot finish loading under
// Node. They must still parse: a SyntaxError here is a blank page in a browser.
for (const name of ["../assets/app.js", "../assets/boot.js", "../assets/ui.js", "../assets/charts.js"]) {
  let error = null;
  try {
    await import(name);
  } catch (caught) {
    error = caught;
  }
  const short = name.replace("../", "");
  check(`${short} parses`, !(error instanceof SyntaxError), error ? error.message : "");
  check(`${short} fails only because Node has no DOM`,
    error === null || /document|window|localStorage|navigator|addEventListener|crypto/.test(String(error.message)),
    error ? error.message : "");
}

/* ================================================================== */
console.log(`\n${checks - failures}/${checks} checks passed`);
if (failures) {
  console.log(`${failures} FAILED`);
  process.exit(1);
}
console.log("Savia Lite self check passed.");
