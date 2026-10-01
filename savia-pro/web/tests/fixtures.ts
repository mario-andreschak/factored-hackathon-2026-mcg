import type { Detail, Ledger, Overview, Profile, Review, Snapshot, Txn } from "../src/types";

export const transaction = (reference = "TX-A", merchant = "Shop A", amount = 100): Txn => ({
  reference, product_reference: "PRODUCT-A", occurred_at: "2026-01-15T10:00:00",
  event_date: "2026-01-15", process_date: "2026-01-15", date_gap_days: 0,
  type: "Purchase", category: "Food", amount, currency: "USD", amount_usd: amount,
  channel: "POS", merchant, merchant_category: "Food", country: "CO", city: "Bogotá",
  status: "Approved", response_code: null, direction: "debit", settled: true,
  merchant_missing: false, currency_differs_from_product: false,
  product_type: "Tarjeta Crédito", product_status: "Active", product_currency: "USD",
});

export const detail = (txn = transaction()): Detail => ({
  transaction: txn, product: null,
  related: { similar: [], same_merchant: [], same_amount: [] },
  evidence: { source: "serving_snapshot", build_id: "fixture-build" },
});

export const ledger = (transactions = [transaction()], next_offset: number | null = null): Ledger => ({
  transactions, matched: transactions.length, total: transactions.length,
  offset: 0, limit: 40, next_offset,
  sums: { inflow: 0, outflow: transactions.reduce((sum, txn) => sum + txn.amount, 0),
    undetermined: 0, currencies: 1 },
});

export const overview: Overview = {
  customer: { alias: "Demo A" }, products: [], currencies: ["USD"],
  balances: [{ currency: "USD", deposit: 0, investment: 0, credit: 100,
    credit_limit: 200, products: 1 }],
  series: { USD: [] }, recent: [], stats: { transactions: 1 }, build: {},
};

export const snapshot: Snapshot = {
  build: { build_id: "fixture-build" }, totals: { transactions: 1 },
  shares: { no_merchant: 0, no_category: 0, next_day_event: 0 },
};

export const profiles: Profile[] = [{
  slug: "ar-premium", alias: "Demo A", note: "Fixture", city: "Bogotá", state: "DC",
  country: "CO", segment: "Premium", customer_status: "Active",
  registration_date: "2020-01-01", transactions: 1, products: 1, currencies: 1,
  first_process_date: "2026-01-15", last_process_date: "2026-01-15",
}];

export const review = (txn = transaction()): Review => ({
  id: "REV-FIXTURE", created_at: "2026-10-01T00:00:00Z", reason: "security_concern",
  priority: "security", customer_answers: {}, customer_note: "", verified_facts: txn,
  evidence: { source: "serving_snapshot", build_id: "fixture-build", facts_sha256: "a".repeat(64) },
  questions_skipped: true, bank_action_taken: false, dispute_submitted: false,
  chargeback_requested: false, refund_issued: false, agent_transfer: false,
  response_deadline_promised: false, local_only: true,
  next_step: "Local review only. No bank decision or response time.",
});

export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

export const reply = (body: unknown, status = 200) => ({
  ok: status < 400, status, statusText: status === 401 ? "Unauthorized" : "OK",
  json: async () => body,
}) as Response;
