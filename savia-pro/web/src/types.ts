export type Lang = "es" | "pt" | "en";

export type Profile = {
  slug: string; alias: string; note: string;
  city: string; state: string; country: string;
  segment: string; customer_status: string; registration_date: string;
  transactions: number; products: number; currencies: number;
  first_process_date: string; last_process_date: string;
};

export type Customer = {
  alias: string; note: string; city: string; state: string; country: string;
  segment: string; status: string; customer_since: string;
};

export type Product = {
  reference: string; type: string; currency: string;
  balance: number | null; credit_limit: number | null; interest_rate: number | null;
  opened_at: string | null; expires_at: string | null; status: string;
  opened_channel: string | null; linked_app: boolean | null; days_past_due: number | null;
  last_transaction_at: string | null;
  balance_kind: "deposit" | "credit" | "investment";
  available: number | null; masked: string;
};

export type Txn = {
  reference: string; product_reference: string;
  occurred_at: string; event_date: string; process_date: string; date_gap_days: number | null;
  type: string; category: string | null;
  amount: number; currency: string; amount_usd: number | null;
  channel: string; merchant: string | null; merchant_category: string | null;
  country: string | null; city: string | null;
  status: string; response_code: string | null;
  direction: "debit" | "credit" | "unknown";
  settled: boolean; merchant_missing: boolean; currency_differs_from_product: boolean;
  product_type: string | null; product_status: string | null; product_currency: string | null;
};

export type MonthPoint = {
  month: string; inflow: number; outflow: number; undetermined: number; count: number;
};

export type Overview = {
  customer: { alias: string };
  products: Product[];
  balances: { currency: string; deposit: number; credit: number; investment: number; credit_limit: number; products: number }[];
  currencies: string[];
  series: Record<string, MonthPoint[]>;
  recent: Txn[];
  stats: Record<string, number | string>;
  build: Record<string, string>;
};

export type Ledger = {
  transactions: Txn[]; matched: number; total: number;
  offset: number; limit: number; next_offset: number | null;
  sums: { inflow: number; outflow: number; undetermined: number; currencies: number };
};

export type Detail = {
  transaction: Txn;
  product: Product | null;
  related: { similar: Txn[]; same_merchant: Txn[]; same_amount: Txn[] };
  evidence: { source: string; build_id: string };
};

export type Insights = {
  currency: string | null; currencies: string[];
  categories: { category: string; total: number; count: number }[];
  merchants: { merchant: string; category: string | null; total: number; count: number; last_seen: string }[];
  channels: { channel: string; count: number }[];
  repeat_merchants: {
    merchant: string; currency: string; occurrences: number; months: number;
    min_amount: number; max_amount: number; avg_amount: number;
    last_seen: string; amount_is_constant: boolean;
  }[];
  series: MonthPoint[];
  completeness: { metric: string; count: number; of: number }[];
};

export type Signal = { kind: string; count: number; examples: Txn[] };
export type Signals = { found: Signal[]; clear: Signal[] };

export type Snapshot = {
  build: Record<string, string>;
  totals: Record<string, number>;
  shares: { no_merchant: number; no_category: number; next_day_event: number };
};

export type Review = {
  id: string; created_at: string; reason: string; priority: string;
  customer_answers: Record<string, string>; customer_note: string;
  verified_facts: Txn; evidence: { source: string; build_id: string; facts_sha256: string };
  questions_skipped: boolean; bank_action_taken: boolean; dispute_submitted: boolean;
  chargeback_requested: boolean; refund_issued: boolean; agent_transfer: boolean;
  response_deadline_promised: boolean; local_only: boolean; next_step: string;
};

export type Filters = {
  q: string; product: string; type: string; status: string; channel: string;
  currency: string; direction: string; category: string;
  date_from: string; date_to: string; min_amount: string; max_amount: string;
  flags: string[]; sort: string;
};

export const EMPTY_FILTERS: Filters = {
  q: "", product: "", type: "", status: "", channel: "", currency: "",
  direction: "", category: "", date_from: "", date_to: "",
  min_amount: "", max_amount: "", flags: [], sort: "date_desc",
};

export function activeFilterCount(f: Filters): number {
  let n = f.flags.length;
  for (const [key, value] of Object.entries(f)) {
    if (key === "flags" || key === "sort") continue;
    if (value) n += 1;
  }
  return n;
}
