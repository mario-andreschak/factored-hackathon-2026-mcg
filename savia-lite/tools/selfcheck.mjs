/**
 * Savia Lite self check - `node tools/selfcheck.mjs`
 *
 * Runs with plain Node, no test framework and no install. It asserts the
 * promises the interface makes about the generated scenario, so a reviewer can
 * see them enforced instead of trusting the copy.
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { PROFILES, DATASET, buildAccount, duplicateGroups, directionFor } from "../assets/data.js";
import { translationKeys, createTranslator, LANGUAGES } from "../assets/i18n.js";
import { formatMoney, formatDay, signedMoney, dayKey, monthKey, toCsv } from "../assets/format.js";

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
function section(name) {
  console.log(`\n${name}`);
}

/* ------------------------------------------------------------------ */
section("dataset shape");
const accounts = PROFILES.map((p) => buildAccount(p.id));
check("every profile builds an account", accounts.length === PROFILES.length);
check("every profile has three products", accounts.every((a) => a.products.length === 3));
check("every profile has transactions", accounts.every((a) => a.transactions.length > 60));

const repeat = buildAccount(PROFILES[0].id);
check(
  "generation is deterministic",
  JSON.stringify(repeat.transactions) === JSON.stringify(accounts[0].transactions)
);

check(
  "profiles do not share transaction references",
  new Set(accounts.flatMap((a) => a.transactions.map((x) => x.transaction_id))).size ===
    accounts.reduce((n, a) => n + a.transactions.length, 0)
);

for (const account of accounts) {
  const label = account.profile.id;
  const rows = account.transactions;

  check(`${label}: references are unique`, new Set(rows.map((x) => x.transaction_id)).size === rows.length);
  check(`${label}: every row belongs to an owned product`, rows.every((x) => account.productById.has(x.product_id)));
  check(`${label}: amounts are positive magnitudes`, rows.every((x) => x.amount > 0));
  check(
    `${label}: currency matches the product currency`,
    rows.every((x) => account.productById.get(x.product_id).currency === x.currency)
  );
  check(
    `${label}: processing dates stay inside the scenario window`,
    rows.every((x) => x.process_date >= DATASET.window_start && x.process_date <= DATASET.window_end)
  );
  check(
    `${label}: direction is only claimed for types that support it`,
    rows.every((x) => x.direction === directionFor(x.transaction_type))
  );
  check(
    `${label}: transfers, payments and adjustments keep an unknown direction`,
    rows.filter((x) => ["Transferencia", "Pago", "Ajuste"].includes(x.transaction_type)).every((x) => x.direction === "unknown")
  );
  check(
    `${label}: an absent merchant is null, never an empty or placeholder string`,
    rows.every((x) => x.merchant_name === null || (typeof x.merchant_name === "string" && x.merchant_name.trim().length > 2))
  );
  check(
    `${label}: no fraud score, label or customer identifier leaks into a row`,
    rows.every((x) => !("is_fraud" in x) && !("fraud_score" in x) && !("customer_id" in x) && !("document_number" in x))
  );
  check(
    `${label}: every reversal entry points at a real charge`,
    rows.filter((x) => x.reversal_of).every((x) => rows.some((y) => y.transaction_id === x.reversal_of))
  );

  const eventShift = rows.filter((x) => dayKey(x.transaction_date) !== x.process_date);
  check(`${label}: reproduces the next-day event pattern`, eventShift.length > 0, `${eventShift.length} rows`);

  const missingMerchant = rows.filter((x) => x.merchant_name === null).length;
  check(
    `${label}: most rows carry no merchant, like the published snapshot`,
    missingMerchant / rows.length > 0.5,
    `${((missingMerchant / rows.length) * 100).toFixed(1)}% missing`
  );

  const scenarios = new Set(rows.map((x) => x.scenario).filter(Boolean));
  for (const needed of [
    "opaque_descriptor", "duplicate_candidate", "missing_merchant",
    "reversed_charge", "reversal_entry", "pending_authorisation",
  ]) {
    check(`${label}: scenario present - ${needed}`, scenarios.has(needed));
  }

  check(`${label}: a duplicate-looking pair exists`, account.duplicates.size >= 2);
  check(
    `${label}: the duplicate heuristic never flags a lone transaction`,
    [...account.duplicates].every((id) => {
      const x = rows.find((r) => r.transaction_id === id);
      return rows.some((y) => y.transaction_id !== id && y.merchant_name === x.merchant_name && y.amount === x.amount);
    })
  );
  check(
    `${label}: a pending row is never marked settled`,
    rows.filter((x) => x.transaction_status === "Pendiente").every((x) => x.transaction_status !== "Aprobada")
  );
}

check("the duplicate heuristic ignores rows with no near twin", duplicateGroups([
  { transaction_id: "A", merchant_name: "M", amount: 10, currency: "COP", product_id: "P", transaction_date: "2026-06-01 10:00:00", reversal_of: null },
  { transaction_id: "B", merchant_name: "M", amount: 10, currency: "COP", product_id: "P", transaction_date: "2026-06-30 10:00:00", reversal_of: null },
]).size === 0);

check("the duplicate heuristic flags a near twin", duplicateGroups([
  { transaction_id: "A", merchant_name: "M", amount: 10, currency: "COP", product_id: "P", transaction_date: "2026-06-01 10:00:00", reversal_of: null },
  { transaction_id: "B", merchant_name: "M", amount: 10, currency: "COP", product_id: "P", transaction_date: "2026-06-02 10:00:00", reversal_of: null },
]).size === 2);

/* ------------------------------------------------------------------ */
section("translations");
const keys = translationKeys();
const base = keys.es;
check("Spanish, Portuguese and English are all present", LANGUAGES.every((l) => keys[l.code]));
for (const [code, list] of Object.entries(keys)) {
  const missing = base.filter((k) => !list.includes(k));
  const extra = list.filter((k) => !base.includes(k));
  check(`${code}: key set matches Spanish`, missing.length === 0 && extra.length === 0,
    [...missing.map((k) => "missing " + k), ...extra.map((k) => "extra " + k)].slice(0, 4).join(", "));
  check(`${code}: no empty string`, list.every((k) => createTranslator(code)(k).trim().length > 0));
}

section("wording guarantees");
for (const code of ["es", "pt", "en"]) {
  const t = createTranslator(code);
  check(`${code}: the reversal note refuses to promise an arrived refund`,
    /no prueba|não prova|not proof/i.test(t("tx.reversedNote")));
  check(`${code}: the pending note refuses to call a pending charge settled`,
    /no está liquidad|não está liquidad|not settled/i.test(t("tx.pendingNote")));
  check(`${code}: the duplicate note refuses to confirm`,
    /no lo damos por confirmado|não tratamos isso como confirmado|do not treat it as confirmed/i.test(t("tx.dupNote")));
  check(`${code}: the summary denies a dispute, refund, agent and deadline`,
    /disputa|contestação|dispute/i.test(t("summary.disclaimer")) &&
    /reembolso|refund/i.test(t("summary.disclaimer")) &&
    /agente|atendente|agent/i.test(t("summary.disclaimer")) &&
    /plazo|prazo|deadline/i.test(t("summary.disclaimer")));
  check(`${code}: the banner says no banking action is taken`,
    /ninguna acción bancaria|nenhuma ação bancária|no banking action/i.test(t("banner.synthetic")));
  check(`${code}: help states no customer authentication is tested`,
    /autenticación|autenticação|authentication/i.test(t("help.isnot.5")));
}

/* ------------------------------------------------------------------ */
section("formatting");
check("money keeps the supplied currency", formatMoney(1234.5, "COP", "es").includes("1"));
check("a credit is signed as incoming", signedMoney({ amount: 10, currency: "USD", direction: "credit" }, "en").startsWith("+"));
check("a debit is signed as outgoing", signedMoney({ amount: 10, currency: "USD", direction: "debit" }, "en").startsWith("−"));
check("an unknown direction gets no invented sign",
  !/^[+−]/.test(signedMoney({ amount: 10, currency: "USD", direction: "unknown" }, "en")));
check("a late event keeps its own calendar day", dayKey("2026-06-18 00:42:00") === "2026-06-18");
check("month grouping uses the event month", monthKey("2026-06-18 00:42:00") === "2026-06");
check("day formatting does not shift across timezones", formatDay("2026-01-01", "es").startsWith("1 ene"));
check("csv quotes a separator inside a value", toCsv([["a,b", "c"]], ["x", "y"]).includes('"a,b"'));

/* ------------------------------------------------------------------ */
section("shipped files");
const files = readdirSync(root);
for (const name of ["index.html", "serve.py", "README.md", "favicon.svg", "assets", "run.sh", "run.ps1"]) {
  check(`present: ${name}`, files.includes(name));
}
const html = readFileSync(join(root, "index.html"), "utf8");
check("index.html loads the app as a module", /type="module"[^>]*app\.js|app\.js[^>]*type="module"/.test(html));
check("index.html has no external origin", !/https?:\/\//.test(html.replace(/https?:\/\/www\.w3\.org/g, "")));
check("index.html asks search engines not to index the demo", /noindex/.test(html));

const sources = ["assets/app.js", "assets/data.js", "assets/i18n.js", "assets/format.js"]
  .map((name) => readFileSync(join(root, name), "utf8"));
check("no source file reaches the network", sources.every((code) => !/\bfetch\(|XMLHttpRequest|WebSocket|EventSource/.test(code)));
check("no source file embeds a remote URL", sources.every((code) => !/https?:\/\/(?!www\.w3\.org)/.test(code)));
check("no source file mentions a bank dispute being submitted",
  sources.every((code) => /dispute_submitted: false/.test(code) || !/dispute_submitted/.test(code)));

/* ------------------------------------------------------------------ */
section("browser modules parse");
// app.js and boot.js need a DOM, so they cannot finish loading under Node.
// They must still *parse*: a SyntaxError here is a blank page in the browser.
for (const name of ["../assets/app.js", "../assets/boot.js"]) {
  let error = null;
  try {
    await import(name);
  } catch (caught) {
    error = caught;
  }
  check(
    `${name.replace("../", "")} parses`,
    !(error instanceof SyntaxError),
    error instanceof SyntaxError ? error.message : ""
  );
  check(
    `${name.replace("../", "")} fails only because Node has no DOM`,
    error === null || /document|window|localStorage|navigator|addEventListener/.test(String(error.message)),
    error ? error.message : ""
  );
}

/* ------------------------------------------------------------------ */
console.log(`\n${checks - failures}/${checks} checks passed`);
if (failures) {
  console.log(`${failures} FAILED`);
  process.exit(1);
}
console.log("Savia Lite self check passed.");
